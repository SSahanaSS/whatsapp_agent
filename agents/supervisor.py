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
- order      → user wants to PLACE a NEW order or MODIFY their current cart ONLY
               (add items, remove items, view cart, checkout, payment, delivery address, show menu)
- faq        → questions about food details OR questions about the business
               (ingredients, allergens, spice levels, what's in a dish,
               timings, location, delivery areas, policies)
- complaint  → ANY issue or question about an EXISTING order
               (order status, delivery time, late orders, wrong items,
               missing items, refunds, payment issues)
- greeting   → hi, hello, thanks, bye, acknowledgements like "ok", "okay", "noted"
- unknown    → truly cannot determine intent even with context

━━━━━━━━━━ HOW TO CLASSIFY ━━━━━━━━━━

Think about what the user MEANS, not what language they used.

order examples — user wants to PLACE or MODIFY a new order:
- "Biryani vennum" → want biryani → order
- "Ek biryani do" → give one biryani → order
- "Menu kaattu" → show menu → order
- "Enna iruku" → what's available → order
- "Kya milega" → what's available → order
- "What's there to eat" → order
- "menu?" → order
- "Remove sambar from cart" → order
- "Confirm my order" → order

faq examples — user is ASKING about food details or business info:
- "Does sambhar contain egg?" → ingredient question → faq
- "Is the biryani spicy?" → food detail question → faq
- "Sambar la chicken poduveengala" → ingredient question → faq
- "What's in the masala dosa?" → dish detail question → faq
- "Is it veg or non veg?" → food detail question → faq
- "Eppo close aaguveenga" → what time do you close → faq
- "Deliver pannuveenga?" → do you deliver → faq
- "Kab tak open ho" → when are you open → faq
- "Which areas do you deliver to?" → faq

complaint examples — ANY issue with an EXISTING order:
- "Thambi food ku taste illai" → food had no taste → complaint
- "Wrong item achu" → wrong item came → complaint
- "Khana sahi nahi tha" → food wasn't right → complaint
- "Order eppo varum" → when will my order come → complaint
- "Order varala" → order hasn't arrived → complaint
- "Where is my order" → order status → complaint
- "Delivery late achu" → delivery is late → complaint
- "Item missing" → missing item → complaint
- "Payment pochi but order illai" → paid but no order → complaint
- "Wrong order vanduchu" → wrong order came → complaint
- "Order cancel pannunga" → cancel my order → complaint
- "Refund venum" → need refund → complaint

greeting examples:
- "okay thanks", "ok", "thanks", "seri", "achha", "theek hai" → greeting
- "hi", "hello", "vanakkam", "namaste" → greeting

unknown — ONLY use this if you genuinely cannot figure out intent even with history:
- Random characters, gibberish, completely unrelated topics

━━━━━━━━━━ KEY RULES ━━━━━━━━━━
PLACING or MODIFYING a new order → order
Question ABOUT food or business → faq
ANYTHING about an existing order → complaint

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
