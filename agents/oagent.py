import json
from datetime import datetime
import pytz
from services.gemini import run_agent_loop
from services.db import (
    get_active_session,
    save_session,
    merge_cart,
    finalize_order,
    get_saved_name,
    get_saved_address,
    save_sticky_route,
    cur,
    conn,
)
import razorpay
from config import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET

razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
IST = pytz.timezone("Asia/Kolkata")


def _format_menu_for_reply(menu: list[dict]) -> str:
    now_label = datetime.now(IST).strftime("%I:%M %p IST")

    if not menu:
        return (
            f"No items available right now ({now_label}).\n"
            "Please try again during breakfast, lunch, or drinks hours."
        )

    lines = [f"*Menu right now* ({now_label})\n"]
    for item in menu:
        lines.append(f"• {item['item_name']} — Rs{float(item['price']):.0f}")

    return "\n".join(lines)


ORDER_TOOLS = [
    {
        "name": "show_menu",
        "description": (
            "Show the currently available menu items with item ID, price, and time window. "
            "Use this when the customer asks to see the menu or asks what is available now."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_last_order",
        "description": "Fetches the customer's last completed order from the database.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "add_items",
        "description": "Add one or more items to the customer's cart. Only add items that exist in the menu.",
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item_name": {"type": "string"},
                            "qty":       {"type": "integer"},
                        },
                        "required": ["item_name", "qty"],
                    },
                }
            },
            "required": ["items"],
        },
    },
    {
        "name": "remove_items",
        "description": "Remove one or more items from the customer's cart.",
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"item_name": {"type": "string"}},
                        "required": ["item_name"],
                    },
                }
            },
            "required": ["items"],
        },
    },
    {
        "name": "update_items",
        "description": "Update the quantity of one or more items already in the cart.",
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item_name": {"type": "string"},
                            "qty":       {"type": "integer"},
                        },
                        "required": ["item_name", "qty"],
                    },
                }
            },
            "required": ["items"],
        },
    },
    {
        "name": "collect_name",
        "description": (
            "Handles customer name collection before confirming an order. "
            "Call with no arguments to check if a saved name exists. "
            "Call with name once the customer provides or confirms one. "
            "Returns status: 'confirmed', 'awaiting_confirmation', or 'awaiting_input'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The customer's name. Omit if not yet known."},
            },
            "required": [],
        },
    },
    {
        "name": "collect_address",
        "description": (
            "Handles delivery address or location collection. "
            "If the customer shared a WhatsApp location (message starts with '__location__'), "
            "call this with address='__use_location__' to confirm the coordinates already in state. "
            "Otherwise call with the text address the customer provided, "
            "or call with no args to check for a previously saved address. "
            "Returns status: 'confirmed', 'awaiting_confirmation', or 'awaiting_input'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "Text address, or '__use_location__' when using shared WhatsApp coordinates.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "confirm_order",
        "description": (
            "Finalizes the order and generates a Razorpay payment link. "
            "Requires both a customer name and a delivery address (or shared location). "
            "The tool will return an error indicating what is missing."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "reply_only",
        "description": "Send a plain message to the customer without touching the cart.",
        "parameters": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    },
    {
        "name": "escalate",
        "description": (
            "Use this ONLY when the current message is clearly NOT about placing or modifying a food order.\n\n"
            "Escalate immediately for:\n"
            "- FAQ: ingredients, spice level, veg/non-veg, timings, delivery areas, policies\n"
            "- Payment method questions: UPI, GPay, PhonePe, cash, card\n"
            "- Existing-order support: where is my order, delay, wrong item, missing item, refund, payment failed\n\n"
            "Do NOT escalate: menu browsing, adding/removing items, address/name/location, confirming order."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
]


def _make_execute_fn(state: dict):
    customer_id = state["customer_id"]
    sender      = state["sender"]
    menu_items  = [item["item_name"].lower() for item in state.get("menu", [])]

    # ── Restore delivery address ───────────────────────────────────────────────
    if not state.get("delivery_address"):
        saved = get_saved_address(customer_id)
        if saved:
            state["delivery_address"] = saved
            print(f"[order_agent] Restored delivery_address from DB: {saved}")

    # ── Restore customer name ──────────────────────────────────────────────────
    if not state.get("customer_name"):
        saved_name = get_saved_name(customer_id)
        if saved_name:
            state["customer_name"] = saved_name
            print(f"[order_agent] Restored customer_name from DB: {saved_name}")

    # ── Restore coords from customers table ────────────────────────────────────
    if not state.get("customer_lat"):
        cur.execute("""
            SELECT customer_lat, customer_lng FROM customers
            WHERE customer_id = %s
        """, (customer_id,))
        row = cur.fetchone()
        if row and row[0]:
            state["customer_lat"] = float(row[0])
            state["customer_lng"] = float(row[1])
            print(f"[order_agent] Restored coords from DB: ({row[0]}, {row[1]})")

    def execute_fn(tool_name: str, args: dict) -> dict:
        args = args or {}

        if tool_name == "reply_only":
            msg = args.get("message", "")
            state["reply"]  = msg
            state["action"] = "NONE"
            return {"reply": msg}

        if tool_name == "show_menu":
            msg = _format_menu_for_reply(state.get("menu", []))
            state["reply"]  = msg
            state["action"] = "NONE"
            return {"reply": msg}

        if tool_name == "escalate":
            print(f"[order_agent] Escalating to supervisor")
            state["sticky_route"] = None
            save_sticky_route(customer_id, None)
            state["escalated"] = True
            state["reply"]     = ""
            cur.execute("""
                DELETE FROM order_sessions
                WHERE customer_id = %s AND status = 'active' AND items = '[]'
            """, (customer_id,))
            conn.commit()
            return {"status": "escalated"}

        if tool_name == "get_last_order":
            cur.execute("""
                SELECT order_details FROM orders
                WHERE customer_id = %s
                ORDER BY created_at DESC LIMIT 1
            """, (customer_id,))
            row = cur.fetchone()
            if not row:
                return {"error": "No previous order found."}
            items = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            return {"last_order": items}

        if tool_name == "add_items":
            items = args.get("items", [])
            if isinstance(items, dict):
                items = [items]

            menu = state.get("menu", [])
            for i in items:
                if "item_name" not in i and "item_id" in i:
                    match = next((m for m in menu if m["item_id"] == int(i["item_id"])), None)
                    if match:
                        i["item_name"] = match["item_name"]
                    else:
                        return {"error": f"Item ID {i['item_id']} not found in menu."}
                if "quantity" in i and "qty" not in i:
                    i["qty"] = int(i["quantity"])

            invalid = [
                i["item_name"] for i in items
                if i.get("item_name", "").lower() not in menu_items
            ]
            if invalid:
                return {"error": f"Items not on menu: {', '.join(invalid)}."}

            for item in items:
                item.setdefault("qty", 1)

            session      = get_active_session(customer_id)
            current_cart = session[1] if session else []
            updated_cart = merge_cart(current_cart, "ADD", items)
            save_session(customer_id, updated_cart)

            state["current_order"] = updated_cart
            state["action"]        = "ADD"
            cart_str = ", ".join(f"{i['qty']}× {i['item_name']}" for i in updated_cart)
            return {"cart": updated_cart, "cart_summary": cart_str}

        if tool_name in ["remove_items", "update_items"]:
            items = args.get("items", [])
            if isinstance(items, dict):
                items = [items]

            op           = "REMOVE" if tool_name == "remove_items" else "UPDATE"
            session      = get_active_session(customer_id)
            current_cart = session[1] if session else []
            updated_cart = merge_cart(current_cart, op, items)
            save_session(customer_id, updated_cart)

            state["current_order"] = updated_cart
            state["action"]        = op
            cart_str = ", ".join(f"{i['qty']}× {i['item_name']}" for i in updated_cart) or "empty"
            return {"cart": updated_cart, "cart_summary": cart_str}

        if tool_name == "collect_name":
            name = args.get("name", "").strip()

            if name:
                state["customer_name"] = name
                cur.execute("UPDATE customers SET name = %s WHERE customer_id = %s", (name, customer_id))
                conn.commit()
                print(f"[order_agent] Customer name saved: {name}")
                return {"status": "confirmed", "name": name}

            saved_name = state.get("customer_name") or get_saved_name(customer_id)
            if saved_name:
                return {"status": "awaiting_confirmation", "saved_name": saved_name}
            return {"status": "awaiting_input"}

        if tool_name == "collect_address":
            address = args.get("address", "").strip()

            # ── WhatsApp location share ────────────────────────────────────────
            if address == "__use_location__" or state.get("message", "").startswith("__location__"):
                lat = state.get("customer_lat")
                lng = state.get("customer_lng")

                if lat and lng:
                    location_label = f"📍 Shared location ({lat:.4f}, {lng:.4f})"
                    state["delivery_address"] = location_label
                    # coords saved to DB in confirm_order after order row exists
                    print(f"[order_agent] Location stored in state: ({lat}, {lng})")
                    return {
                        "status":      "confirmed",
                        "address":     location_label,
                        "next_action": "Location confirmed. Call confirm_order now to finalize the order.",
                    }
                return {
                    "error": "Location data missing. Ask customer to share their WhatsApp location or type their address.",
                }

            # ── Text address — save to state only, DB updated in confirm_order ─
            if address:
                state["delivery_address"] = address
                print(f"[order_agent] Address stored in state: {address}")
                return {
                    "status":      "confirmed",
                    "address":     address,
                    "next_action": "Address confirmed. Call confirm_order now to finalize the order.",
                }

            # ── Check for saved address ────────────────────────────────────────
            saved = get_saved_address(customer_id)
            if saved:
                return {"status": "awaiting_confirmation", "saved_address": saved}
            return {
                "status": "awaiting_input",
                "hint":   "Ask the customer to type their address or share their WhatsApp location.",
            }

        if tool_name == "confirm_order":
            delivery_address = state.get("delivery_address", "").strip()
            customer_name    = state.get("customer_name", "").strip()

            print(f"[confirm_order] address='{delivery_address}' name='{customer_name}'")

            if not customer_name:
                return {
                    "error":       "missing_name",
                    "description": "Customer name is required before confirming. Call collect_name.",
                }

            if not delivery_address:
                return {
                    "error":       "missing_address",
                    "description": "Delivery address is required before confirming. Call collect_address.",
                }

            session = get_active_session(customer_id)
            print(f"[confirm_order] session={session}")

            if not session or not session[1]:
                return {"error": "Cart is empty."}

            _, items = session
            total = finalize_order(customer_id, items)
            state["total_amount"] = total

            # ── Save address + coords to the newly created order row ───────────
            cur.execute("""
                UPDATE orders SET customer_address = %s
                WHERE customer_id = %s
                AND created_at = (SELECT MAX(created_at) FROM orders WHERE customer_id = %s)
            """, (delivery_address, customer_id, customer_id))

            lat = state.get("customer_lat")
            lng = state.get("customer_lng")
            if lat and lng:
                cur.execute("""
                    UPDATE customers SET customer_lat = %s, customer_lng = %s
                    WHERE customer_id = %s
                """, (lat, lng, customer_id))

            conn.commit()
            print(f"[confirm_order] Address + coords saved to DB")

            summary_lines = "\n".join(f"• {i['qty']} x {i['item_name'].title()}" for i in items)
            summary = (
                f"🧾 *Order Summary*\n\n"
                f"👤 *Name:* {customer_name}\n"
                f"{summary_lines}\n\n"
                f"📍 *Delivering to:* {delivery_address}\n\n"
                f"*Total: ₹{total}*"
            )

            try:
                cur.execute("""
                    SELECT order_id FROM orders
                    WHERE customer_id = %s
                    ORDER BY created_at DESC LIMIT 1
                """, (customer_id,))
                order_row   = cur.fetchone()
                db_order_id = order_row[0] if order_row else "N/A"

                print(f"[confirm_order] Creating Razorpay link for ₹{total}")
                payment_link = razorpay_client.payment_link.create({
                    "amount":      int(total * 100),
                    "currency":    "INR",
                    "description": "Food Order Payment",
                    "customer": {
                        "contact": sender.replace("whatsapp:", ""),
                        "name":    customer_name,
                    },
                    "notify": {"sms": False, "email": False},
                    "notes": {
                        "order_id":      str(db_order_id),
                        "customer_name": customer_name,
                    },
                })
                payment_url              = payment_link["short_url"]
                state["payment_link_id"] = payment_link["id"]
                state["stage"]           = "payment"
                state["sticky_route"]    = None
                save_sticky_route(customer_id, None)
                print(f"[confirm_order] ✅ Payment link: {payment_url}")

                return {
                    "status":        "success",
                    "order_summary": summary,
                    "payment_url":   payment_url,
                }

            except Exception as e:
                print(f"[confirm_order] ❌ Razorpay Error: {e}")
                return {
                    "status":        "payment_error",
                    "order_summary": summary,
                    "error":         "Could not generate payment link.",
                }

        return {"error": "Unknown tool."}

    return execute_fn


def order_agent(state: dict) -> dict:
    if not state.get("escalated"):
        state["sticky_route"] = "order"
        save_sticky_route(state["customer_id"], "order")

    state["escalated"] = False

    session = get_active_session(state["customer_id"])
    if not session:
        save_session(state["customer_id"], [])

    menu          = state.get("menu", [])
    current_order = state.get("current_order", [])
    message       = state.get("message", "")
    history       = state.get("history", "")
    customer_id   = state["customer_id"]
    saved_address = get_saved_address(customer_id)
    saved_name    = get_saved_name(customer_id)

    # ── Is this a location share? ──────────────────────────────────────────────
    is_location = message.startswith("__location__")

    # ── Detect language ────────────────────────────────────────────────────────
    tamil_chars     = any('\u0B80' <= c <= '\u0BFF' for c in message)
    has_tamil_words = any(w in message.lower() for w in [
        "venum", "vendam", "enna", "iruku", "sollu", "order", "mudich",
        "add", "remove", "menu", "kaattu", "confirm", "ready",
    ])
    if tamil_chars:
        language_hint = "Customer is writing in Tamil script. Reply in Tamil."
    elif has_tamil_words:
        language_hint = "Customer is writing in Tanglish (Tamil words in English script). Reply in Tanglish."
    else:
        language_hint = "Reply in English."

    # ── Build display message for prompt ──────────────────────────────────────
    if is_location:
        lat = state.get("customer_lat")
        lng = state.get("customer_lng")
        display_message = (
            f"[Customer shared their WhatsApp location: lat={lat}, lng={lng}. "
            f"Treat this as their delivery location. Call collect_address with address='__use_location__'.]"
        )
    else:
        display_message = message

    prompt = f"""
You are an ordering assistant for Amma's Kitchen, a home-based food business.
Your only job is to help customers place orders, manage their cart, and complete payment.

LANGUAGE RULE — THIS IS MANDATORY:
{language_hint}
You MUST reply in the same language/script as the customer used.
Never switch languages unless the customer does first.

IMPORTANT BOUNDARY:
You handle only order-building actions for the current cart:
- showing menu for purchase
- adding, removing, or updating items
- collecting customer name
- collecting delivery address (text or shared WhatsApp location)
- confirming the order and generating the payment link

If the customer shares their WhatsApp location, call collect_address with address='__use_location__' immediately.

Call escalate for:
- food detail questions: ingredients, spice level, veg/non-veg
- business questions: opening time, delivery areas, policies
- payment method questions: UPI, GPay, PhonePe, cash, card
- existing-order support: where is my order, delay, wrong item, refund, payment failed

Do NOT escalate: menu browsing, cart changes, name/address/location, confirming order.

--- MENU ---
{json.dumps(menu, ensure_ascii=False)}

--- CURRENT CART ---
{json.dumps(current_order, ensure_ascii=False)}

--- SAVED CUSTOMER NAME ---
{saved_name if saved_name else "None"}

--- SAVED DELIVERY ADDRESS ---
{saved_address if saved_address else "None"}

--- CONVERSATION HISTORY ---
{history[-1000:] if history else "(none)"}

--- CUSTOMER MESSAGE ---
"{display_message}"
"""

    try:
        execute_fn         = _make_execute_fn(state)
        final_reply, stage = run_agent_loop(prompt, ORDER_TOOLS, execute_fn)
        state["reply"]     = final_reply or state.get("reply", "")
        state["stage"]     = stage
        return state

    except Exception as e:
        print("Order Agent Error:", e)
        import traceback
        traceback.print_exc()
        state["reply"]  = "Sorry, something went wrong. Please try again."
        state["action"] = "NONE"
        return state