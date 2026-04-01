import json
from datetime import datetime
import pytz
from services.gemini import run_agent_loop
from services.db import (
    get_active_session,
    save_session,
    merge_cart,
    finalize_order,
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
            f"Menu for {now_label}\n\n"
            "No items are available right now.\n"
            "Please try again during breakfast, lunch, or drinks hours."
        )

    headers = ["ID", "Item", "Price", "From", "Until"]
    rows = [
        [
            str(item.get("item_id", "")),
            str(item.get("item_name", "")),
            f"{float(item.get('price', 0)):.2f}",
            str(item.get("available_from", "")),
            str(item.get("available_until", "")),
        ]
        for item in menu
    ]
    widths = [
        max(len(headers[idx]), max(len(row[idx]) for row in rows))
        for idx in range(len(headers))
    ]

    def fmt_row(row: list[str]) -> str:
        return " | ".join(value.ljust(widths[idx]) for idx, value in enumerate(row))

    divider = "-+-".join("-" * width for width in widths)
    lines = [fmt_row(headers), divider]
    lines.extend(fmt_row(row) for row in rows)

    return f"Menu available right now ({now_label})\n\n" + "\n".join(lines)


ORDER_TOOLS = [
    {
        "name": "show_menu",
        "description": (
            "Show the currently available menu items with item ID, price, and time window. "
            "Use this when the customer asks to see the menu or asks what is available now."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_last_order",
        "description": "Fetches the customer's last completed order from the database.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
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
                            "qty": {"type": "integer"},
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
                        "properties": {
                            "item_name": {"type": "string"},
                        },
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
                            "qty": {"type": "integer"},
                        },
                        "required": ["item_name", "qty"],
                    },
                }
            },
            "required": ["items"],
        },
    },
    {
        "name": "collect_address",
        "description": (
            "Handles delivery address collection. "
            "Call with no arguments to check if a saved address exists. "
            "Call with address once the customer provides or confirms one. "
            "The tool returns status: 'confirmed', 'awaiting_confirmation', or 'awaiting_input'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "The delivery address provided by the customer. Omit if not yet known.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "confirm_order",
        "description": (
            "Finalizes the order and generates a Razorpay payment link. "
            "Will return an error if no delivery address has been collected yet — "
            "in that case use collect_address first."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "reply_only",
        "description": "Send a plain message to the customer without touching the cart.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "escalate",
        "description": (
              "Use this ONLY when the current message is clearly NOT about placing or modifying a food order. "
        "Do NOT escalate for menu browsing, food availability questions, "
        "or 'what do you have' type queries. These are part of ordering.\n\n"
        "Escalate immediately for these mid-conversation topic shifts:\n"
        "- FAQ or business-info questions: ingredients, spice level, veg/non-veg, timings, delivery areas, policies\n"
        "- Payment method questions: UPI, GPay, PhonePe, cash, card, accepted payment options\n"
        "- Existing-order support: where is my order, delivery delay, wrong item, missing item, refund, payment failed\n"
        "- Complaints or support requests unrelated to building the current cart\n\n"
        "Examples that MUST escalate:\n"
        "- 'Is it spicy?'\n"
        "- 'Do you accept UPI?'\n"
        "- 'Can I pay by GPay?'\n"
        "- 'Where is my order?'\n"
        "- 'Refund venum'\n\n"
        "Examples that must NOT escalate:\n"
        "- 'Show menu'\n"
        "- 'Add 2 idli'\n"
        "- 'Remove dosa'\n"
        "- 'Confirm order'"
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


def _make_execute_fn(state: dict):
    customer_id = state["customer_id"]
    sender      = state["sender"]
    menu_items  = [item["item_name"].lower() for item in state.get("menu", [])]

    if not state.get("delivery_address"):
        saved = get_saved_address(customer_id)
        if saved:
            state["delivery_address"] = saved
            print(f"[order_agent] Restored delivery_address from DB: {saved}")

    def execute_fn(tool_name: str, args: dict) -> dict:
        args = args or {}

        if tool_name == "reply_only":
            msg = args.get("message", "")
            state["reply"]  = msg
            state["action"] = "NONE"
            return {"reply": msg}

        if tool_name == "show_menu":
            msg = _format_menu_for_reply(state.get("menu", []))
            state["reply"] = msg
            state["action"] = "NONE"
            return {"reply": msg}

        if tool_name == "escalate":
            print(f"[order_agent] Escalating to supervisor")
            state["sticky_route"] = None
            save_sticky_route(customer_id, None) 
            state["escalated"]    = True
            state["reply"]        = ""
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

            invalid = [
                i["item_name"] for i in items
                if i["item_name"].lower() not in menu_items
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

        if tool_name == "collect_address":
            address = args.get("address", "").strip()

            if address:
                state["delivery_address"] = address
                cur.execute("""
                    UPDATE orders
                    SET customer_address = %s
                    WHERE customer_id = %s
                    AND created_at = (
                        SELECT MAX(created_at) FROM orders WHERE customer_id = %s
                    )
                """, (address, customer_id, customer_id))
                conn.commit()
                print(f"[order_agent] Address saved to DB: {address}")
                return {
                    "status":      "confirmed",
                    "address":     address,
                    "next_action": "Address confirmed. Call confirm_order now to finalize the order.",
                }

            saved = get_saved_address(customer_id)
            if saved:
                return {
                    "status":        "awaiting_confirmation",
                    "saved_address": saved,
                }
            return {"status": "awaiting_input"}

        if tool_name == "confirm_order":
            delivery_address = state.get("delivery_address", "").strip()
            print(f"[confirm_order] address='{delivery_address}'")

            if not delivery_address:
                return {
                    "error": "Cannot confirm order — no delivery address collected yet.",
                    "hint":  "Call collect_address to get or confirm the customer's address first.",
                }

            session = get_active_session(customer_id)
            print(f"[confirm_order] session={session}")

            if not session or not session[1]:
                return {"error": "Cart is empty."}

            _, items = session
            total    = finalize_order(customer_id, items)
            state["total_amount"] = total

            summary_lines = "\n".join(
                f"• {i['qty']} x {i['item_name'].title()}" for i in items
            )
            summary = (
                f"🧾 *Order Summary*\n\n"
                f"{summary_lines}\n\n"
                f"📍 *Delivering to:* {delivery_address}\n\n"
                f"*Total: ₹{total}*"
            )

            try:
                print(f"[confirm_order] Creating Razorpay link for ₹{total}")
                payment_link = razorpay_client.payment_link.create({
                    "amount":      int(total * 100),
                    "currency":    "INR",
                    "description": "Food Order Payment",
                    "customer":    {"contact": sender.replace("whatsapp:", "")},
                    "notify":      {"sms": False, "email": False},
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
        save_sticky_route(state["customer_id"], "order")  # persist immediately

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

    prompt = f"""
You are an ordering assistant. Your only job is to help customers
place orders, manage their cart, and complete payment.

Always reply in the same language as the customer.

IMPORTANT BOUNDARY:
You handle only order-building actions for the current cart:
- showing menu for purchase
- adding, removing, or updating items
- collecting delivery address
- confirming the order and generating the payment link

If the user changes topic in the middle of ordering, do NOT answer it here.
Call escalate immediately for:
- food detail questions: ingredients, spice level, veg/non-veg, what's in a dish
- business questions: opening time, delivery areas, policies
- payment method questions: UPI, GPay, PhonePe, cash, card, accepted payment methods
- existing-order support: where is my order, order status, delay, wrong item, missing item, refund, payment failed
- complaints about a previous or current order

Do NOT escalate these:
- menu browsing for purchase
- adding/removing/updating cart items
- address confirmation
- confirming the order

Examples:
- "2 idli" -> add_items
- "Show menu" -> show_menu
- "What is available now?" -> show_menu
- "Is it spicy?" -> escalate
- "Do you accept UPI?" -> escalate
- "Can I pay via PhonePe?" -> escalate
- "Where is my order?" -> escalate
- "Refund venum" -> escalate

--- MENU ---
{json.dumps(menu, ensure_ascii=False)}

--- CURRENT CART ---
{json.dumps(current_order, ensure_ascii=False)}

--- SAVED DELIVERY ADDRESS ---
{saved_address if saved_address else "None"}

--- CONVERSATION HISTORY ---
{history[-1000:] if history else "(none)"}

--- CUSTOMER MESSAGE ---
"{message}"
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
