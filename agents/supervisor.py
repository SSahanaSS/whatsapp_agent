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

    # Truncate by lines instead of characters
    history_trimmed = "\n".join(history_str.split("\n")[-10:]) if history_str else "(none)"
    prompt = f"""
You are a STRICT intent classifier for a food delivery WhatsApp assistant.

Your job: classify the user message into EXACTLY ONE of these:
- order
- faq
- complaint
- greeting
- unknown

━━━━━━━━━━ RULES (VERY IMPORTANT) ━━━━━━━━━━

1. ORDER → ONLY if the user is CLEARLY trying to BUY food
   Examples:
   - "I want 2 biryanis"
   - "Give me menu"
   - "Can I order now"
   - "1 chicken roll please"

2. FAQ → ANY question about:
   - delivery, timings, open/close hours
   - weekends, location, availability
   - ingredients, menu info (WITHOUT ordering)
   Examples:
   - "Do you deliver on weekends?"
   - "What time do you open?"
   - "Where are you located?"

3. COMPLAINT → ONLY if referring to PAST order issues
   Examples:
   - "My food was cold"
   - "Wrong item delivered"

4. GREETING → ONLY pure greetings
   - "hi", "hello", "hey"

5. UNKNOWN → 
   - incomplete / unclear / typos
   - short messages like "ok", "hmm", "can i orde"
   - anything ambiguous

━━━━━━━━━━ CRITICAL BEHAVIOUR ━━━━━━━━━━

- If message is INCOMPLETE or has TYPO → return "unknown"
- DO NOT assume intent
- "can i orde" → unknown (NOT order)
- "menu?" → order
- "order?" → unknown (not clear enough)
- "ok", "hmm", "thanks" → use HISTORY context

━━━━━━━━━━ HISTORY ━━━━━━━━━━
{history_trimmed}

━━━━━━━━━━ MESSAGE ━━━━━━━━━━
"{message}"

━━━━━━━━━━ OUTPUT ━━━━━━━━━━
Reply with ONLY ONE WORD:
order / faq / complaint / greeting / unknown
"""

    routed_to = "unknown"  # safe default

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=5,
            temperature=0,
        )

        raw = response.choices[0].message.content.strip().lower()

        # Strip punctuation in case model returns "faq." or "faq\n"
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