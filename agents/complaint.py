"""
Complaint Agent — placeholder.
Replace the body of complaint_agent() with your real logic when ready.
"""

import google.generativeai as genai
from config import model
from services.db import get_or_create_customer
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

COMPLAINT_TOOLS = [
    {
        "name": "get_order_status",
        "description": "Fetches the latest order status and payment status from the database.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "initiate_refund",
        "description": "Initiates a refund. Only call once the customer has explicitly asked for a refund.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "offer_replacement",
        "description": "Creates a replacement order. Only call when customer explicitly asks for replacement.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "issue_coupon",
        "description": "Issues a discount coupon as compensation for a bad experience or delay.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "log_and_escalate",
        "description": "Logs the complaint and escalates to human support. Use for serious issues.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "resolve",
        "description": "Marks the complaint as resolved. Only call when customer is clearly satisfied.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "reply_only",
        "description": "Sends a message without taking any action. Use to ask clarifying questions or acknowledge.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string"}
            },
            "required": ["message"],
        },
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


def _run_complaint_loop(
    prompt: str,
    customer_id: int,
    order_id,
) -> tuple[str, bool]:
    """Runs the agentic complaint loop. Returns (reply, resolved)."""

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

    contents = [{"role": "user", "parts": [{"text": prompt}]}]
    final_reply = ""
    resolved = False

    for iteration in range(10):
        response = model.generate_content(contents, tools=gemini_tools)

        # ── Guard: empty response ──────────────────────────────────────────────
        candidate = response.candidates[0]
        parts = candidate.content.parts if candidate.content.parts else []
        if not parts:
            print(f"[Complaint] iteration {iteration + 1}: empty response, stopping")
            break

        part = parts[0]

        # ── No tool call → plain text reply ───────────────────────────────────
        if not part.function_call:
            final_reply = part.text or final_reply
            break

        tool_name = part.function_call.name
        args = dict(part.function_call.args) if part.function_call.args else {}
        print(f"[Complaint] Tool: {tool_name}")

        result = {}

        if tool_name == "get_order_status":
            order = get_latest_order(customer_id)
            if order:
                result = {
                    "order_id":       order[0],
                    "order_status":   order[1],
                    "payment_status": order[2],
                }
                # update order_id in case it wasn't known before
                order_id = order[0]
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
            result = {"message": "Complaint marked as resolved."}

        elif tool_name == "reply_only":
            final_reply = args.get("message", "")
            contents.append({
                "role": "model",
                "parts": [{"function_call": {"name": tool_name, "args": args}}],
            })
            contents.append({
                "role": "user",
                "parts": [{"function_response": {"name": tool_name, "response": {"reply": final_reply}}}],
            })
            break

        contents.append({
            "role": "model",
            "parts": [{"function_call": {"name": tool_name, "args": args}}],
        })
        contents.append({
            "role": "user",
            "parts": [{"function_response": {"name": tool_name, "response": result}}],
        })

    return final_reply, resolved


def complaint_agent(state: dict) -> dict:
    """
    Drop-in complaint agent for your project's plain-dict AgentState.
    Reads: state['message'], state['history'], state['customer_id']
    Writes: state['reply'], state['sticky_route']
    """
    message     = state.get("message", "")
    history     = state.get("history", "")
    customer_id = state.get("customer_id")

    # ── Fetch latest order ─────────────────────────────────────────────────────
    order          = get_latest_order(customer_id)
    order_id       = order[0] if order else None
    order_status   = order[1] if order else "not found"
    payment_status = order[2] if order else "not found"

    history_str = history if isinstance(history, str) else str(history)

    prompt = f"""
You are an empathetic support agent for a home-based food business on WhatsApp.
Reply in the SAME language as the customer.
Be warm, understanding, and solution-focused.

Your resolution options (use tools):
- Ask what happened first (reply_only) — never assume the issue
- Refund        → initiate_refund      (only if customer explicitly asks)
- Replacement   → offer_replacement    (only if customer explicitly asks)
- Coupon        → issue_coupon         (for bad experience / delay)
- Escalate      → log_and_escalate     (serious or repeated issues)
- Resolve       → resolve              (customer is satisfied)

Rules:
- Always use get_order_status first if order details are unknown
- Never offer refund AND replacement at the same time
- Ask what resolution the customer wants before acting
- If customer is just venting, acknowledge with reply_only first

--- CURRENT ORDER ---
Order ID      : {order_id or "N/A"}
Order Status  : {order_status}
Payment Status: {payment_status}

--- RECENT HISTORY ---
{history_str[-600:] if history_str else "(none)"}

--- CUSTOMER MESSAGE ---
"{message}"
"""

    final_reply, resolved = _run_complaint_loop(prompt, customer_id, order_id)

    if not final_reply:
        final_reply = "Sorry, something went wrong. Please try again."

    # ── Save complaint record ──────────────────────────────────────────────────
    if order_id:
        save_complaint(customer_id, order_id, "GENERAL", message)

    # ── Sticky: stay on complaint until resolved ───────────────────────────────
    state["sticky_route"] = None if resolved else "complaint"
    state["reply"]        = final_reply

    return state