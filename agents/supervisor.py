from config import groq_client

_FALLBACK_GREETING = (
    "👋 Welcome! How can I help you today?\n\n"
    "I can help you place an order, answer questions, or sort out any issues. 😊"
)

_UNKNOWN_REPLY = (
    "Sorry, I didn't quite understand that. 😅\n\n"
    "I can help you with:\n"
    "🍽️ Placing an order\n"
    "❓ General questions\n"
    "📢 Complaints about a past order\n\n"
    "What would you like to do?"
)

_VALID_ROUTES = {"order", "complaint", "faq", "greeting", "unknown"}


def supervisor_agent(state: dict) -> dict:

    # ── Sticky route (skip LLM) ────────────────────────────────────────────────
    if state.get("sticky_route"):
        print(f"[Supervisor] Sticky → '{state['sticky_route']}' (skipped LLM)")
        state["route"] = state["sticky_route"]
        return state

    message = state.get("message", "")
    history = state.get("history", "")
    history_str = history if isinstance(history, str) else str(history)
    history_trimmed = "\n".join(history_str.split("\n")[-10:]) if history_str else "(none)"

    prompt = f"""
You are an intent classifier for Amma's Kitchen, a home-based food business on WhatsApp.

Users write in English, Tamil, Hindi, Tanglish, or any mix.
Classify the MESSAGE into exactly one of: order / faq / complaint / greeting / unknown

order     → customer is ready to buy OR exploring items BEFORE ordering —
         includes asking what items are available, menu, combos, pricing,
         or showing intent to choose food
        
faq      → customer is ASKING about business details — wants to know if something is possible,
            how something works, what the business offers, timings, areas, policies,
            ingredients, payment options, or any general information before deciding
complaint → customer is unhappy about something that already happened
greeting  → pure greeting or acknowledgement, nothing else
unknown   → cannot determine even with history

HISTORY:
{history_trimmed}

MESSAGE: "{message}"

Reply with ONE WORD only: order / faq / complaint / greeting / unknown
"""
    routed_to = "unknown"

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=5,
            temperature=0,
        )

        raw = response.choices[0].message.content.strip().lower()
        raw = raw.strip(".,!?\n\r ")

        routed_to = raw if raw in _VALID_ROUTES else "unknown"

        print(f"[Supervisor LLM Output] → '{raw}'")
        print(f"[Supervisor Final Route] → '{routed_to}'")

    except Exception as e:
        print(f"[Supervisor ERROR] {e} → default 'unknown'")

    # ── Inline handling ────────────────────────────────────────────────────────
    if routed_to == "greeting":
        state["reply"] = _FALLBACK_GREETING
        state["route"] = "greeting"
        return state

    if routed_to == "unknown":
        state["reply"] = _UNKNOWN_REPLY
        state["route"] = "unknown"
        return state

    state["route"] = routed_to
    return state
