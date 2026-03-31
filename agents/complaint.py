import json
import google.generativeai as genai
from config import model
from services.dbservice import (
    get_latest_order,
    process_refund,
    save_complaint,
    log_complaint,
    issue_coupon,
    escalate_ticket,
    create_replacement_order,
    resolve_complaint,
)
from services.db import save_sticky_route

COMPLAINT_TOOLS = [
    {
        "name": "get_order_status",
        "description": "Fetches the latest order status, payment status, order details and ETA from the database.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "initiate_refund",
        "description": (
            "Initiates a refund for the customer's order. "
            "Only call this after the customer has explicitly asked for a refund — "
            "never offer or initiate a refund on your own."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "offer_replacement",
        "description": (
            "Creates a replacement order. "
            "Only call this after the customer has explicitly asked for a replacement — "
            "never offer or initiate a replacement on your own."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "issue_coupon",
        "description": (
            "Issues a discount coupon as compensation. "
            "Only call this after you have acknowledged the issue, understood what went wrong, "
            "and the customer has not asked for a refund or replacement. "
            "Never call this as the first response to a complaint."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "log_and_escalate",
        "description": (
            "Logs the complaint and escalates to human support. "
            "Use for serious issues or when the customer is repeatedly unsatisfied."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "resolve",
        "description": (
            "Marks the complaint as resolved. "
            "Only call when the customer has explicitly expressed satisfaction "
            "or said something like 'ok thanks', 'that's fine', 'no problem'."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "reply_only",
        "description": (
            "Sends a message to the customer without taking any action. "
            "Use this to acknowledge the issue, express empathy, or ask clarifying questions. "
            "Always use this first before calling any resolution tool."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string"}
            },
            "required": ["message"],
        },
    },
    {
        "name": "escalate",
        "description": (
            "Use this when the customer wants to switch away from the complaint flow — "
            "for example, they want to place a new order, browse the menu, or ask an FAQ. "
            "Do NOT use this for complaint-related issues. "
            "Examples: 'I want to order biryani', 'menu kaattu', 'add dosa', 'enna iruku'."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
]


def _schema_to_proto(prop: dict):
    type_map = {
        "string":  genai.protos.Type.STRING,
        "integer": genai.protos.Type.INTEGER,
        "boolean": genai.protos.Type.BOOLEAN,
        "array":   genai.protos.Type.ARRAY,
        "object":  genai.protos.Type.OBJECT,
    }
    t = type_map.get(prop.get("type", "string"), genai.protos.Type.STRING)
    kwargs = {"type": t}
    if "description" in prop:
        kwargs["description"] = prop["description"]
    return genai.protos.Schema(**kwargs)


def _get_full_order_details(customer_id: int) -> dict:
    from config import cur
    cur.execute("""
        SELECT order_id, order_status, payment_status,
               order_details, total_amount, customer_address,
               eta_minutes, created_at
        FROM orders
        WHERE customer_id = %s
        ORDER BY created_at DESC
        LIMIT 1
    """, (customer_id,))
    row = cur.fetchone()
    if not row:
        return {}
    items = json.loads(row[3]) if isinstance(row[3], str) else (row[3] or [])
    return {
        "order_id":       row[0],
        "order_status":   row[1],
        "payment_status": row[2],
        "items":          items,
        "total_amount":   float(row[4]) if row[4] else 0,
        "address":        row[5] or "N/A",
        "eta_minutes":    row[6],
        "ordered_at":     str(row[7]) if row[7] else "N/A",
    }


def _run_complaint_loop(
    prompt: str,
    customer_id: int,
    order_id,
    state: dict,
) -> tuple[str, bool, bool]:
    """
    Returns: (final_reply, resolved, escalated)
    """

    gemini_tools = [
        genai.protos.Tool(
            function_declarations=[
                genai.protos.FunctionDeclaration(
                    name=t["name"],
                    description=t["description"],
                    parameters=genai.protos.Schema(
                        type=genai.protos.Type.OBJECT,
                        properties={
                            k: _schema_to_proto(v)
                            for k, v in t["parameters"]["properties"].items()
                        },
                        required=t["parameters"].get("required", []),
                    ),
                )
            ]
        )
        for t in COMPLAINT_TOOLS
    ]

    contents     = [{"role": "user", "parts": [{"text": prompt}]}]
    final_reply  = ""
    resolved     = False
    escalated    = False
    acknowledged = False

    for iteration in range(10):
        response  = model.generate_content(contents, tools=gemini_tools)
        candidate = response.candidates[0]
        parts     = candidate.content.parts if candidate.content.parts else []

        if not parts:
            print(f"[Complaint] iteration {iteration + 1}: empty response, stopping")
            break

        part = parts[0]

        if not part.function_call:
            final_reply = part.text or final_reply
            break

        tool_name = part.function_call.name
        args      = dict(part.function_call.args) if part.function_call.args else {}
        print(f"[Complaint] Tool: {tool_name}")

        result = {}

        # ── Escalate → hand back to supervisor ────────────────────────────────
        if tool_name == "escalate":
            print(f"[Complaint] Escalating to supervisor")
            save_sticky_route(customer_id, None)
            state["sticky_route"] = None
            state["escalated"]    = True
            escalated             = True
            final_reply           = ""
            contents.append({
                "role": "model",
                "parts": [{"function_call": {"name": tool_name, "args": args}}],
            })
            contents.append({
                "role": "user",
                "parts": [{"function_response": {"name": tool_name, "response": {"status": "escalated"}}}],
            })
            break

        # ── Block resolution tools until acknowledged ──────────────────────────
        resolution_tools = {"initiate_refund", "offer_replacement", "issue_coupon", "log_and_escalate"}
        if tool_name in resolution_tools and not acknowledged:
            print(f"[Complaint] Blocked {tool_name} — not acknowledged yet")
            result = {
                "error": (
                    "You must acknowledge the customer and understand what went wrong "
                    "before taking any action. Use reply_only first to ask clarifying questions."
                )
            }
            contents.append({
                "role": "model",
                "parts": [{"function_call": {"name": tool_name, "args": args}}],
            })
            contents.append({
                "role": "user",
                "parts": [{"function_response": {"name": tool_name, "response": result}}],
            })
            continue

        if tool_name == "reply_only":
            acknowledged = True
            final_reply  = args.get("message", "")
            contents.append({
                "role": "model",
                "parts": [{"function_call": {"name": tool_name, "args": args}}],
            })
            contents.append({
                "role": "user",
                "parts": [{"function_response": {"name": tool_name, "response": {"reply": final_reply}}}],
            })
            break

        if tool_name == "get_order_status":
            details = _get_full_order_details(customer_id)
            if details:
                order_id = details["order_id"]
                result   = details
            else:
                result = {"message": "No order found for this customer."}

        elif tool_name == "initiate_refund":
            if order_id:
                process_refund(order_id)
                result = {"message": f"Refund initiated for order {order_id}."}
            else:
                result = {"message": "No order found to refund."}

        elif tool_name == "offer_replacement":
            if order_id:
                new_order_id = create_replacement_order(order_id, customer_id)
                result = {"message": f"Replacement order {new_order_id} created."}
            else:
                result = {"message": "No order found to replace."}

        elif tool_name == "issue_coupon":
            issue_coupon(customer_id)
            result = {"message": "Coupon issued to customer."}

        elif tool_name == "log_and_escalate":
            if order_id:
                log_complaint(order_id, "ESCALATED")
                escalate_ticket(order_id, customer_id)
                result = {"message": "Complaint logged and escalated to support team."}
            else:
                result = {"message": "No order found to escalate."}

        elif tool_name == "resolve":
            if order_id:
                resolve_complaint(customer_id, order_id)
            resolved = True
            result   = {"message": "Complaint marked as resolved."}

        contents.append({
            "role": "model",
            "parts": [{"function_call": {"name": tool_name, "args": args}}],
        })
        contents.append({
            "role": "user",
            "parts": [{"function_response": {"name": tool_name, "response": result}}],
        })

    return final_reply, resolved, escalated


def complaint_agent(state: dict) -> dict:

    # ── Sticky ─────────────────────────────────────────────────────────────────
    state["sticky_route"] = "complaint"
    save_sticky_route(state["customer_id"], "complaint")
    state["escalated"]    = False

    message     = state.get("message", "")
    history     = state.get("history", "")
    customer_id = state.get("customer_id")

    details        = _get_full_order_details(customer_id)
    order_id       = details.get("order_id")
    order_status   = details.get("order_status", "not found")
    payment_status = details.get("payment_status", "not found")
    items          = details.get("items", [])
    total_amount   = details.get("total_amount", 0)
    address        = details.get("address", "N/A")
    eta_minutes    = details.get("eta_minutes", "N/A")
    ordered_at     = details.get("ordered_at", "N/A")

    history_str = history if isinstance(history, str) else str(history)

    prompt = f"""
You are an empathetic support agent for a home-based food business on WhatsApp.
Reply in the same language as the customer.
Be warm, understanding, and solution-focused.

If the customer wants to place a new order, browse the menu, or do anything
unrelated to their complaint — use the escalate tool immediately.

--- LATEST ORDER ---
Order ID      : {order_id or "N/A"}
Order Status  : {order_status}
Payment Status: {payment_status}
Items         : {json.dumps(items, ensure_ascii=False)}
Total         : ₹{total_amount}
Address       : {address}
ETA           : {f"{eta_minutes} minutes" if eta_minutes and eta_minutes != "N/A" else "N/A"}
Ordered At    : {ordered_at}

--- RECENT HISTORY ---
{history_str[-600:] if history_str else "(none)"}

--- CUSTOMER MESSAGE ---
"{message}"
"""

    try:
        final_reply, resolved, escalated = _run_complaint_loop(
            prompt, customer_id, order_id, state
        )

        # ── If escalated, let supervisor re-route fresh ────────────────────────
        if escalated:
            return state

        if not final_reply:
            final_reply = "Sorry, something went wrong. Please try again."

        if order_id:
            save_complaint(customer_id, order_id, "GENERAL", message)

        # ── Clear sticky when resolved ─────────────────────────────────────────
        resolved_route = None if resolved else "complaint"
        state["sticky_route"] = resolved_route
        save_sticky_route(customer_id, resolved_route)

        state["reply"] = final_reply
        return state

    except Exception as e:
        print("Complaint Agent Error:", e)
        import traceback
        traceback.print_exc()
        state["reply"] = "Sorry, something went wrong. Please try again."
        return state