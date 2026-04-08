import json

from config import groq_client
from services.db import cur, save_sticky_route
from services.dbservice import (
    create_replacement_order,
    escalate_ticket,
    issue_coupon,
    log_complaint,
    process_refund,
    resolve_complaint,
    save_complaint,
)

COMPLAINT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "initiate_refund",
            "description": (
                "Initiates a refund for the customer's order. "
                "Only call this after the customer has explicitly asked for a refund."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "offer_replacement",
            "description": (
                "Creates a replacement order. "
                "Only call this after the customer has explicitly asked for a replacement."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "issue_coupon",
            "description": (
                "Issues a discount coupon as goodwill compensation. "
                "Only call this after the customer has agreed to receive compensation "
                "and has not asked for a refund or replacement."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_and_escalate",
            "description": (
                "Logs the complaint and escalates to human support. "
                "Use for serious issues (food safety, harassment, repeated failures) "
                "or when the customer is repeatedly unsatisfied after compensation."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve",
            "description": (
                "Marks the complaint as resolved and closes the support session. "
                "Only call this when the customer has clearly expressed satisfaction "
                "or said something like 'ok thanks', 'that's fine', 'no problem', "
                "'seri', or 'okay'. Do NOT call this while the issue is still open."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reply_only",
            "description": (
                "Sends a message to the customer. "
                "This is the ONLY way to send a message. "
                "Always call this as your LAST action in a turn after any backend tool "
                "to inform the customer what was done or to ask a follow-up question."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate",
            "description": (
                "Exits the complaint flow entirely. "
                "Use ONLY when the customer wants to do something unrelated to their complaint, "
                "like placing a new order, browsing the menu, or asking an FAQ. "
                "Do NOT use for complaint-related issues."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

FIRST_TURN_TOOLS = [
    tool for tool in COMPLAINT_TOOLS
    if tool["function"]["name"] in {"reply_only", "escalate"}
]

FIRST_TURN_SYSTEM_PROMPT = """You are an empathetic support agent for Amma's Kitchen, a home-based food delivery business on WhatsApp.
Reply in the same language as the customer: Tamil, Tanglish, or English.

You are handling the FIRST turn of a complaint conversation.

YOUR GOAL IN THIS TURN:
- Decide whether the message is actually a complaint about an existing order.
- If it is NOT a complaint, call escalate immediately.
- If it IS a complaint, ask exactly ONE clarifying question using reply_only.

STRICT RULES:
- Do NOT propose a solution yet.
- Do NOT mention refund, replacement, coupon, or escalation as the answer yet.
- Do NOT take any backend action.
- Do NOT ask for the order number.
- Your question should help you understand the exact issue better.
- Keep the question short, human, and specific to the customer's message.
"""

SYSTEM_PROMPT = """You are an empathetic support agent for Amma's Kitchen, a home-based food delivery business on WhatsApp.
Reply in the same language as the customer: Tamil, Tanglish, or English.

YOU ALREADY HAVE ALL ORDER DETAILS IN THE PROMPT.
- Never say \"let me check\", \"give me a moment\", or ask for an order number.
- Never stall. Respond based on what you already know.

STEP 0 - CHECK IF THIS IS A COMPLAINT
- Determine whether the user's message is a complaint about an existing order.
- If it is not a complaint, call escalate immediately.
- Do NOT ask questions or use reply_only for non-complaint messages.

CORE FLOW
STEP 1 - UNDERSTAND THE ISSUE:
- Carefully read the customer's message.
- Identify the complaint clearly (delay, wrong item, missing item, payment issue, quality issue, etc.).
- If anything important is still unclear, ask one clarifying question.
- Do NOT take any backend action yet.

STEP 2 - VALIDATE THE COMPLAINT:
- Use the order details provided to determine if the complaint is valid.
- If the complaint is clearly valid, proceed.
- If unsure, ask one more clarifying question.
- Do NOT call backend tools yet.

COMPLAINT TYPES:
- Serious conduct/safety issue:
  rude or abusive delivery behaviour, harassment, threats, discrimination, unsafe interaction
  -> use log_and_escalate once understood.
- Objective service failure:
  wrong item, missing item, delivery delay, spill, payment problem, spoiled/unsafe food, foreign object
  -> these may justify refund, replacement, coupon, or escalation depending on severity.
- Subjective feedback:
  too much ice, too spicy, too salty, not tasty, too oily, not hot enough, texture/taste preference
  -> usually treat as feedback first, not automatic refund/replacement/coupon.

STEP 3 - PROPOSE ONE RESOLUTION:
- Suggest the single best next action for the situation.
- Briefly explain why.
- Ask for user confirmation before taking action.
- Do NOT call backend tools in this step.
- For subjective feedback, the default resolution is a brief apology plus noting the feedback.
- Do NOT offer compensation just because the customer disliked the taste or preference balance.

STEP 4 - EXECUTE ONLY AFTER CONFIRMATION:
- If the customer clearly agrees (for example: \"yes\", \"ok\", \"refund\", \"do it\"), call the matching backend tool.
- Refund -> initiate_refund
- Replacement -> offer_replacement
- Coupon -> issue_coupon
- Serious issue -> log_and_escalate
- After any backend tool, you MUST call reply_only to inform the customer.
- For rude delivery behaviour or any conduct/safety issue, prefer log_and_escalate over compensation tools.
- Do NOT give refund/replacement/coupon for preference-style feedback unless there is a clear objective failure too.

STEP 5 - HANDLE CHANGES:
- If the customer changes their preference, adapt and call the correct tool.
- Do NOT repeat unnecessary questions.

STEP 6 - CLOSE:
- If the customer says \"ok\", \"thanks\", \"fine\", \"seri\", \"okay\", or similar after resolution, call resolve.
- Do NOT call resolve while the complaint is still active.

TOOL RULES
- reply_only is the ONLY way to send a message to the customer.
- Every turn must end with reply_only, except resolve or escalate.
- You may call only one backend tool per turn, followed by reply_only.
- NEVER call backend tools before user confirmation.
- NEVER take action without explicit user approval.

BEHAVIOR RULES
- Be empathetic, polite, and concise.
- Suggest one best action, not multiple choices, unless absolutely necessary.
- Do NOT over-explain.
- Do NOT repeat the same question.
- Always sound human and helpful.
- Stay agentic: decide the best next step yourself using these rules, not a generic menu of options.
"""


def _get_full_order_details(customer_id: int) -> dict:
    cur.execute(
        """
        SELECT order_id, order_status, payment_status,
               order_details, total_amount, customer_address,
               eta_minutes, created_at
        FROM orders
        WHERE customer_id = %s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (customer_id,),
    )
    row = cur.fetchone()
    if not row:
        return {}

    items = json.loads(row[3]) if isinstance(row[3], str) else (row[3] or [])
    return {
        "order_id": row[0],
        "order_status": row[1],
        "payment_status": row[2],
        "items": items,
        "total_amount": float(row[4]) if row[4] else 0,
        "address": row[5] or "N/A",
        "eta_minutes": row[6],
        "ordered_at": str(row[7]) if row[7] else "N/A",
    }


def _parse_args(tool_call) -> dict:
    """Safely parse tool call arguments, handling Groq's malformed XML-style output."""
    raw = tool_call.function.arguments or "{}"

    if raw.strip().startswith("<function="):
        brace = raw.find("{")
        if brace != -1:
            raw = raw[brace:]
            end = raw.rfind("}")
            if end != -1:
                raw = raw[: end + 1]

    try:
        return json.loads(raw)
    except Exception:
        return {}


def _classify_complaint_signal(message: str, history: str = "") -> dict:
    """
    Lightweight guardrails around model tool choice.

    Keeps the agentic flow, but nudges obvious cases:
    - rude/unsafe delivery behavior -> serious issue -> escalate
    - subjective taste/temperature/ice feedback -> do not auto-compensate
    """
    text = f"{history or ''}\n{message or ''}".lower()

    serious_keywords = [
        "rude delivery",
        "delivery boy rude",
        "delivery person rude",
        "delivery guy rude",
        "rude behaviour",
        "rude behavior",
        "spoke rudely",
        "was rude",
        "misbehaved",
        "harassed",
        "abused",
        "threatened",
        "unsafe",
        "scared",
        "driver rude",
        "delivery rude",
    ]
    feedback_keywords = [
        "too much ice",
        "more ice",
        "too cold",
        "not hot",
        "cold food",
        "too salty",
        "too spicy",
        "too sweet",
        "taste bad",
        "tasted bad",
        "didn't taste good",
        "not tasty",
        "less spicy",
        "more spicy",
        "quality was bad",
        "food is bad",
        "food was bad",
        "bad taste",
        "too oily",
    ]
    objective_failure_keywords = [
        "wrong item",
        "missing item",
        "missing",
        "not delivered",
        "late",
        "delay",
        "delayed",
        "spilled",
        "spoiled",
        "stale",
        "undercooked",
        "raw",
        "smells bad",
        "smelled bad",
        "hair in food",
        "insect",
        "plastic",
        "stone",
        "payment issue",
        "paid twice",
        "double charged",
    ]

    serious_issue = any(keyword in text for keyword in serious_keywords)
    subjective_feedback = any(keyword in text for keyword in feedback_keywords)
    objective_failure = any(keyword in text for keyword in objective_failure_keywords)

    return {
        "serious_issue": serious_issue,
        "subjective_feedback": subjective_feedback,
        "objective_failure": objective_failure,
    }


def _run_complaint_turn(
    prompt: str,
    customer_id: int,
    order_id,
    state: dict,
    first_turn: bool = False,
) -> tuple[str, bool, bool]:
    """
    Runs one customer message turn through the complaint loop.

    On the first complaint turn, the model may only ask a clarifying question
    or escalate out if the message is not actually a complaint.
    """

    messages = [
        {
            "role": "system",
            "content": FIRST_TURN_SYSTEM_PROMPT if first_turn else SYSTEM_PROMPT,
        },
        {"role": "user", "content": prompt},
    ]

    final_reply = ""
    resolved = False
    escalated = False
    tools = FIRST_TURN_TOOLS if first_turn else COMPLAINT_TOOLS
    complaint_signal = _classify_complaint_signal(
        state.get("message", ""),
        state.get("history", ""),
    )

    for iteration in range(6):
        print(f"[Complaint] Calling Groq, iteration={iteration}, first_turn={first_turn}")
        try:
            response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                tools=tools,
                tool_choice="required",
                parallel_tool_calls=False,
                max_tokens=500,
                temperature=0.3,
            )
        except Exception as e:
            err_str = str(e)
            print(f"[Complaint] Groq API error at iteration {iteration}: {err_str}")
            if "tool_use_failed" in err_str and iteration < 4:
                print("[Complaint] Groq tool_use_failed, retrying...")
                continue
            break

        msg = response.choices[0].message

        if not msg.tool_calls:
            print(f"[Complaint] No tool call returned. Raw content: {msg.content}")
            final_reply = (msg.content or "").strip()
            break

        tool_call = msg.tool_calls[0]
        tool_name = tool_call.function.name
        args = _parse_args(tool_call)

        print(f"[Complaint] iter={iteration} -> tool={tool_name} args={args}")

        if (
            complaint_signal["serious_issue"]
            and tool_name in {"initiate_refund", "offer_replacement", "issue_coupon", "resolve"}
        ):
            tool_name = "log_and_escalate"
            print("[Complaint] Overriding tool -> log_and_escalate for serious complaint.")

        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(args),
                        },
                    }
                ],
            }
        )

        if tool_name == "escalate":
            save_sticky_route(customer_id, None)
            state["sticky_route"] = None
            state["escalated"] = True
            escalated = True
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps({"status": "escalated"}),
                }
            )
            print("[Complaint] Escalated out of complaint flow.")
            break

        if tool_name == "resolve":
            if order_id:
                resolve_complaint(customer_id, order_id)
            resolved = True
            final_reply = "Glad we could sort this out. If you need anything else, just message me."
            state["resolved"] = True
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps({"status": "resolved"}),
                }
            )
            print("[Complaint] Complaint resolved.")
            break

        if tool_name == "reply_only":
            final_reply = args.get("message", "").strip()
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps({"status": "sent"}),
                }
            )
            print(f"[Complaint] Reply sent: {final_reply[:80]}")
            break

        result = {}

        if (
            tool_name in {"initiate_refund", "offer_replacement", "issue_coupon"}
            and complaint_signal["subjective_feedback"]
            and not complaint_signal["objective_failure"]
        ):
            result = {
                "status": "blocked",
                "message": (
                    "This sounds like subjective product feedback, not a verified service failure. "
                    "Do not offer refund, replacement, or coupon automatically. "
                    "Acknowledge the feedback, apologise briefly, and either ask one short clarifying "
                    "question if needed or say you will note the feedback."
                ),
            }
            print(f"[Complaint] Blocked compensation for subjective feedback -> {result}")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result),
                }
            )
            continue

        if tool_name == "initiate_refund":
            if order_id:
                process_refund(order_id)
                result = {
                    "status": "success",
                    "message": f"Refund initiated for order {order_id}.",
                }
            else:
                result = {"status": "error", "message": "No order found to refund."}
            print(f"[Complaint] initiate_refund -> {result}")

        elif tool_name == "offer_replacement":
            if order_id:
                new_order_id = create_replacement_order(order_id, customer_id)
                result = {
                    "status": "success",
                    "message": f"Replacement order {new_order_id} created.",
                }
            else:
                result = {"status": "error", "message": "No order found to replace."}
            print(f"[Complaint] offer_replacement -> {result}")

        elif tool_name == "issue_coupon":
            issue_coupon(customer_id)
            result = {
                "status": "success",
                "message": "Discount coupon issued to customer.",
            }
            print(f"[Complaint] issue_coupon -> {result}")

        elif tool_name == "log_and_escalate":
            if order_id:
                log_complaint(order_id, "ESCALATED")
                escalate_ticket(order_id, customer_id)
                result = {
                    "status": "success",
                    "message": "Complaint logged and escalated to human support.",
                }
            else:
                result = {"status": "error", "message": "No order found to escalate."}
            print(f"[Complaint] log_and_escalate -> {result}")

        else:
            result = {"status": "unknown_tool", "tool": tool_name}
            print(f"[Complaint] Unknown tool called: {tool_name}")

        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result),
            }
        )

    print(
        f"[Complaint] Turn complete. final_reply='{final_reply[:80]}' "
        f"resolved={resolved} escalated={escalated}"
    )
    return final_reply, resolved, escalated


def complaint_agent(state: dict) -> dict:
    incoming_sticky = state.get("sticky_route")
    first_turn = incoming_sticky != "complaint"

    state["sticky_route"] = "complaint"
    save_sticky_route(state["customer_id"], "complaint")
    state["escalated"] = False

    message = state.get("message", "")
    history = state.get("history", "")
    customer_id = state.get("customer_id")

    details = _get_full_order_details(customer_id)
    order_id = details.get("order_id")
    order_status = details.get("order_status", "not found")
    payment_status = details.get("payment_status", "not found")
    items = details.get("items", [])
    total_amount = details.get("total_amount", 0)
    address = details.get("address", "N/A")
    eta_minutes = details.get("eta_minutes", "N/A")
    ordered_at = details.get("ordered_at", "N/A")

    print(
        f"[Complaint] customer_id={customer_id} order_id={order_id} "
        f"status={order_status} first_turn={first_turn}"
    )

    history_str = history if isinstance(history, str) else str(history)

    prompt = f"""
--- LATEST ORDER ---
Order ID      : {order_id or "N/A"}
Order Status  : {order_status}
Payment Status: {payment_status}
Items         : {json.dumps(items, ensure_ascii=False)}
Total         : Rs.{total_amount}
Address       : {address}
ETA           : {f"{eta_minutes} minutes" if eta_minutes and eta_minutes != "N/A" else "N/A"}
Ordered At    : {ordered_at}

--- CONVERSATION HISTORY ---
{history_str[-800:] if history_str else "(none)"}

--- CUSTOMER MESSAGE ---
"{message}"

--- COMPLAINT FLOW CONTEXT ---
First complaint turn: {"yes" if first_turn else "no"}
"""

    try:
        final_reply, resolved, escalated = _run_complaint_turn(
            prompt,
            customer_id,
            order_id,
            state,
            first_turn=first_turn,
        )

        if escalated:
            return state

        if not final_reply and not resolved:
            print("[Complaint] WARNING: final_reply is empty after loop. Falling back.")
            final_reply = "Sorry, something went wrong. Please try again."

        if order_id:
            cur.execute("SELECT 1 FROM complaints WHERE order_id = %s LIMIT 1", (order_id,))
            if not cur.fetchone():
                save_complaint(customer_id, order_id, "GENERAL", message)

        state["sticky_route"] = None if resolved else "complaint"
        save_sticky_route(customer_id, None if resolved else "complaint")

        state["reply"] = final_reply
        return state

    except Exception as e:
        print(f"[Complaint] Unhandled exception: {e}")
        import traceback

        traceback.print_exc()
        state["reply"] = "Sorry, something went wrong. Please try again."
        return state
