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
You are an intent classifier for a food ordering WhatsApp chatbot.

VERY IMPORTANT: Users may write in ANY language or mix of languages.
This includes Tamil, Hindi, Tamil+English, Hindi+English, or pure English.
You MUST understand the meaning — do NOT rely on specific keywords or spelling.

Your job: understand what the user MEANS and classify into ONE of:
- order      → anything about food, menu, ordering, cart, checkout, payment, delivery address
- faq        → questions about the business (timings, location, delivery areas, policies)
- complaint  → issues with a past order
- greeting   → hi, hello, thanks, bye, acknowledgements like "ok", "okay", "noted"
- unknown    → truly cannot determine intent even with context

━━━━━━━━━━ HOW TO CLASSIFY ━━━━━━━━━━

Think about what the user MEANS, not what language they used.

order examples (any language):
- "Enna iruku" → asking what's available → order
- "Sambar la chicken poduveengala" → asking about food → order  
- "Menu kaattu" → show menu → order
- "Biryani vennum" → want biryani → order
- "Kya milega" → what's available → order
- "Ek biryani do" → give one biryani → order
- "What's there to eat" → order
- "menu?" → order

greeting examples:
- "okay thanks", "ok", "thanks", "seri", "achha", "theek hai" → greeting
- "hi", "hello", "vanakkam", "namaste" → greeting

faq examples:
- "Eppo close aaguveenga" → what time do you close → faq
- "Deliver pannuveenga?" → do you deliver → faq
- "Kab tak open ho" → when are you open → faq

complaint examples:
- "Thambi food ku taste illai" → food had no taste → complaint
- "Wrong item achu" → wrong item came → complaint
- "Khana sahi nahi tha" → food wasn't right → complaint

unknown — ONLY use this if you genuinely cannot figure out intent even with history:
- Random characters, gibberish, completely unrelated topics

━━━━━━━━━━ HISTORY CONTEXT ━━━━━━━━━━
Use history to resolve ambiguous messages.
If user said "ok" or "seri" after a bot message about an order → greeting
If user said "ok" after bot asked for address → that's part of order flow → order

{history_trimmed}

━━━━━━━━━━ MESSAGE ━━━━━━━━━━
"{message}"

━━━━━━━━━━ OUTPUT ━━━━━━━━━━
Reply with ONLY ONE WORD: order / faq / complaint / greeting / unknown
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