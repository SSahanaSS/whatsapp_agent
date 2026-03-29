import json
from services.gemini import run_agent_loop
from services.db import (
    get_active_session,
    save_session,
    merge_cart,
    finalize_order,
)
import razorpay
from config import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET

razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))


ORDER_TOOLS = [
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
        "description": "Add one or more items to the customer's cart.",
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
        "name": "confirm_order",
        "description": "Finalizes the customer's order and returns an order summary with total amount. Call when the customer is done ordering.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "create_payment",
        "description": "Generates a Razorpay payment link for the customer to complete payment.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "reply_only",
        "description": "Send a message to the customer without taking any cart action.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
            },
            "required": ["message"],
        },
    },
]

def _make_execute_fn(state: dict):

    customer_id = state["customer_id"]

    sender = state["sender"]

    menu_items = [item["item_name"].lower() for item in state.get("menu", [])]



    def execute_fn(tool_name: str, args: dict) -> dict:

        args = args or {}



        # 1. REPLY ONLY

        if tool_name == "reply_only":

            msg = args.get("message", "")

            state["reply"] = msg

            state["action"] = "NONE"

            return {"reply": msg, "stage": state["stage"]}



        # 2. GET LAST ORDER

        if tool_name == "get_last_order":

            from services.db import cur

            cur.execute("""

                SELECT order_details FROM orders 

                WHERE customer_id = %s 

                ORDER BY created_at DESC LIMIT 1

            """, (customer_id,))

            row = cur.fetchone()

            if not row:

                return {"error": "No previous order found."}

            items = json.loads(row[0]) if isinstance(row[0], str) else row[0]

            return {"last_order": items, "message": "Previous order retrieved. Ask user if they want to repeat it."}



        # 3. ADD ITEMS (With Validation)

        if tool_name == "add_items":

            items = args.get("items", [])

            if isinstance(items, dict): items = [items]

            

            # Validation: Check if items are actually on the menu

            invalid_items = [i["item_name"] for i in items if i["item_name"].lower() not in menu_items]

            if invalid_items:

                return {"error": f"The following items are not on the menu: {', '.join(invalid_items)}. Please check the menu and try again."}



            for item in items: item.setdefault("qty", 1)

            

            session = get_active_session(customer_id)

            current_cart = session[1] if session else []

            updated_cart = merge_cart(current_cart, "ADD", items)

            save_session(customer_id, updated_cart)

            

            state["current_order"] = updated_cart

            state["action"] = "ADD"

            cart_str = ", ".join(f"{i['qty']}× {i['item_name']}" for i in updated_cart)

            return {"reply": f"Added. Cart: {cart_str}", "cart": updated_cart}



        # 4. REMOVE / UPDATE (Standard Logic)

        if tool_name in ["remove_items", "update_items"]:

            items = args.get("items", [])

            if isinstance(items, dict): items = [items]

            

            op = "REMOVE" if tool_name == "remove_items" else "UPDATE"

            session = get_active_session(customer_id)

            current_cart = session[1] if session else []

            updated_cart = merge_cart(current_cart, op, items)

            save_session(customer_id, updated_cart)

            

            state["current_order"] = updated_cart

            state["action"] = op

            cart_str = ", ".join(f"{i['qty']}× {i['item_name']}" for i in updated_cart) or "empty"

            return {"reply": f"Cart updated: {cart_str}", "cart": updated_cart}



        # 5. CONFIRM & AUTO-PAY (Merged for better UX)

        if tool_name == "confirm_order":

            session = get_active_session(customer_id)

            if not session or not session[1]:

                return {"error": "Cart is empty."}

            

            _, items = session

            total = finalize_order(customer_id, items)

            state["total_amount"] = total

            

            # Generate Summary

            summary_lines = "\n".join(f"• {i['qty']} x {i['item_name'].title()}" for i in items)

            summary = f"🧾 *Order Summary*\n\n{summary_lines}\n\n*Total: ₹{total}*"

            

            # Auto-trigger Payment Link

            try:

                amount_in_paise = int(total * 100)

                payment_link = razorpay_client.payment_link.create({

                    "amount": amount_in_paise,

                    "currency": "INR",

                    "description": "Food Order Payment",

                    "customer": {"contact": sender.replace("whatsapp:", "")},

                    "notify": {"sms": False, "email": False}

                })

                payment_url = payment_link["short_url"]

                state["payment_link_id"] = payment_link["id"]

                

                final_msg = f"{summary}\n\n💳 *Payment Link:*\n{payment_url}"

                state["reply"] = final_msg

                state["stage"] = "payment"

                return {"reply": final_msg, "status": "success", "payment_url": payment_url}

            

            except Exception as e:

                print(f"Razorpay Error: {e}")

                return {"reply": f"{summary}\n\n(Error generating payment link. Please try again.)"}



        return {"reply": "I'm not sure how to help with that.", "stage": state["stage"]}



    return execute_fn




def order_agent(state: dict) -> dict:
    menu = state.get("menu", [])
    current_order = state.get("current_order", [])
    message = state.get("message", "")
    history = state.get("history", "")

    prompt = f"""
Persona: You are a helpful, professional ordering assistant for a home kitchen.
Language: Always reply in the same language the customer uses.

Operational Rules:
1. Validation: Only add items that exist in the --- MENU ---. If an item isn't there, suggest the closest alternative from the menu.
2. Quantities: If the user doesn't specify how many (e.g., "Add Biryani"), assume quantity is 1.
3. Flow: 
   - Manage the cart using 'add_items', 'remove_items', or 'update_items'.
   - When the user is ready to pay (e.g., "checkout", "done", "bill please"), call 'confirm_order'.
   - IMPORTANT: 'confirm_order' will automatically generate the final summary AND the payment link. You do NOT need to call any other tools after it.
4. Non-Order Talk: Use 'reply_only' for greetings, jokes, or general questions.

--- MENU ---
{json.dumps(menu, ensure_ascii=False)}

--- CURRENT CART ---
{json.dumps(current_order, ensure_ascii=False)}

--- RECENT HISTORY ---
{history[-1000:] if history else "(none)"}

--- CUSTOMER MESSAGE ---
"{message}"
"""
    try:
        execute_fn = _make_execute_fn(state)
        final_reply, stage = run_agent_loop(prompt, ORDER_TOOLS, execute_fn)
        state["reply"] = final_reply or state.get("reply", "Sorry, something went wrong.")
        state["stage"] = stage
        return state

    except Exception as e:
        print("Order Agent Error:", e)
        import traceback
        traceback.print_exc()
        state["reply"] = "Sorry, something went wrong. Please try again."
        state["action"] = "NONE"
        return state