"""
faq_agent.py
------------
FAQ Agent with enhanced RAG pipeline + all edge cases handled.

Flow:
- Hybrid search (semantic + keyword) → top 10
- MMR → diverse top 3  
- Confidence scoring → track best result across retries
- After each search: if confidence < 0.65 and searches < 3 → retry
- After 3 searches OR good confidence → LLM finalizes from best context
- LLM is the final judge — not the threshold
"""

import json
import os
from groq import Groq
from services.faqtools import search_faq, search_menu_info

from config import groq_client
CONFIDENCE_THRESHOLD = 0.65

FAQ_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_faq",
            "description": (
                "Search FAQ using hybrid search (semantic + keyword). "
                "Returns top 3 diverse results with confidence scores. "
                "If top_confidence < 0.65 retry with a rephrased query. "
                "Use for delivery areas, timings, payment, policy, ingredients."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query — rephrase if confidence is low"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_menu_info",
            "description": (
                "Search menu for specific dish info — price, availability. "
                "Use when customer asks about a specific food item."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Dish name to search"
                    }
                },
                "required": ["query"]
            }
        }
    }
]

SYSTEM_PROMPT = """
You are a FAQ agent for a home-based food business called Amma's Kitchen.

STRICT RULE — ONE ACTION PER RESPONSE:
Either call ONE tool OR give a final text reply. Never both together.

YOUR PROCESS:
1. Call search_faq with the customer's question
2. Check top_confidence in result:
   - >= 0.65 → stop searching, answer will be finalized by validator
   - < 0.65  → retry with different phrasing (max 3 searches total)
3. After 3 searches → stop, best context will be sent to validator

REFLECTION — when confidence is low try:
- Simpler terms ("delivery timing" instead of "what time do you deliver")
- Key concepts separately ("area" instead of "which areas do you deliver")
- Synonyms ("location" for "area", "hours" for "timing")

ANSWER RULES:
- Do NOT answer in plain text yourself — the validator will finalize
- Just search and retry if needed
- Reply in SAME language as customer (English/Tamil/Tanglish)
"""

FINAL_DECISION_PROMPT = """
You are validating whether retrieved FAQ context is sufficient to answer a user's original question.

Rules:
- Use ONLY the retrieved context provided.
- Infer the user's intent naturally. For example, if they ask about an unusual or unknown
  payment method, interpret it as a payment-method question and answer using supported methods.
- If the user asks whether a specific area is covered and it's NOT in the delivery list,
  explicitly say it is not covered and mention which areas are covered.
- If the user asks about a specific day/time and the context has opening hours info,
  use that to reason and answer (e.g. "open every day" means Sunday too).
- Do not invent business facts not in the context.
- If context is truly not relevant, set should_answer=false.

Return valid JSON only with this exact schema:
{"should_answer": true/false, "interpreted_intent": "...", "reply": "...", "reason": "..."}
"""


def execute_faq_tool(tool_name: str, tool_args: dict) -> str:
    print(f"    [FAQ Agent Tool] {tool_name} | query: {tool_args.get('query', '')}")
    try:
        if tool_name == "search_faq":
            result = search_faq(query=tool_args.get("query", ""))
            return json.dumps(result)
        elif tool_name == "search_menu_info":
            result = search_menu_info(query=tool_args.get("query", ""))
            return json.dumps(result)
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    except Exception as e:
        print(f"    [FAQ Agent Tool Error] {tool_name}: {e}")
        return json.dumps({"error": str(e), "found": False, "top_confidence": 0.0})


def _fallback_reply() -> str:
    return (
        "Sorry, I don't have information on that. "
        "Please contact us directly on WhatsApp during working hours. 😊"
    )


def _llm_finalize_faq_answer(original_query: str, best_result: dict) -> dict:
    """Final LLM reasoning step — decides if context is enough and generates reply."""
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": FINAL_DECISION_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Original user question:\n{original_query}\n\n"
                        f"Retrieved FAQ context:\n{json.dumps(best_result)}"
                    ),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=300,
        )
        content = (response.choices[0].message.content or "{}").strip()
        return json.loads(content)
    except Exception as e:
        print(f"    [FAQ Agent] Final decision error: {e}")
        return {
            "should_answer": False,
            "interpreted_intent": "",
            "reply": "",
            "reason": str(e),
        }


def _finalize(state: dict, best_result: dict, best_confidence: float, search_count: int) -> dict:
    """
    Always called at the end.
    Passes best context to LLM to reason and reply.
    Only falls back if truly no context or LLM says not relevant.
    """
    original_query = state.get("message", "")

    # ── No context at all ──────────────────────────────────────────────────────
    if not best_result:
        print(f"    [FAQ Agent] No context found — fallback")
        state["reply"]          = _fallback_reply()
        state["stuck"]          = False
        state["stuck_reason"]   = "No FAQ results found"
        state["faq_confidence"] = best_confidence
        state["faq_searches"]   = search_count
        return state

    # ── LLM reasons over best context ─────────────────────────────────────────
    print(f"    [FAQ Agent] Finalizing with LLM. Best confidence={best_confidence}")
    decision = _llm_finalize_faq_answer(original_query, best_result)
    print(f"    [FAQ Agent] LLM decision: should_answer={decision.get('should_answer')}")
    print(f"    [FAQ Agent] Interpreted intent: {decision.get('interpreted_intent', '')}")

    if not decision.get("should_answer"):
        state["reply"]        = _fallback_reply()
        state["stuck"]        = False
        state["stuck_reason"] = decision.get("reason", "Context not relevant")
    else:
        reply = decision.get("reply", "").strip()
        if not reply or reply.startswith("CANNOT_ANSWER"):
            state["reply"]        = _fallback_reply()
            state["stuck_reason"] = reply
        else:
            state["reply"]        = reply
            state["stuck_reason"] = ""
        state["stuck"] = False

    state["faq_confidence"] = best_confidence
    state["faq_searches"]   = search_count
    return state


def faq_agent(state: dict) -> dict:
    print("\n  [FAQ Agent] Starting enhanced RAG pipeline...")
    state["escalated"] = False

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f'Customer question: "{state.get("message", "")}"\n\n'
                f"Search for the answer. Check confidence. "
                f"Retry with different phrasing if confidence < 0.65 (max 3 searches).\n"
                f"ONE tool call per response only."
            )
        }
    ]

    MAX_ITERATIONS = 10
    MAX_SEARCHES   = 3
    iteration      = 0
    search_count   = 0
    best_result    = None
    best_confidence = 0.0

    while iteration < MAX_ITERATIONS:
        iteration += 1
        print(f"    [FAQ Agent] Iteration {iteration} | Searches: {search_count}")

        try:
            response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                tools=FAQ_TOOLS,
                tool_choice="auto",
                parallel_tool_calls=False,
                max_tokens=500,
                temperature=0.0,
            )
        except Exception as e:
            error_str = str(e)
            print(f"    [FAQ Agent] Groq error: {error_str}")

            if "429" in error_str or "rate_limit" in error_str:
                state["reply"] = "Sorry, I'm a bit busy right now. Please try again in a moment! 🙏"
                state["stuck"] = False
                return state

            if "tool_use_failed" in error_str or "400" in error_str:
                if best_result:
                    return _finalize(state, best_result, best_confidence, search_count)
                state["reply"] = _fallback_reply()
                state["stuck"] = False
                return state

            state["reply"] = "Sorry, something went wrong. Please try again! 🙏"
            state["stuck"] = False
            return state

        message = response.choices[0].message

        # ── Tool call, searches remaining ──────────────────────────────────────
        if message.tool_calls and search_count < MAX_SEARCHES:
            tool_call = message.tool_calls[0]  # one at a time
            tool_name = tool_call.function.name

            try:
                tool_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            search_count += 1
            tool_result     = execute_faq_tool(tool_name, tool_args)
            tool_result_str = tool_result

            if tool_name == "search_faq":
                try:
                    parsed     = json.loads(tool_result)
                    confidence = parsed.get("top_confidence", 0.0)
                    print(f"    [FAQ Agent] Confidence: {confidence}")

                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_result     = parsed

                    if confidence >= CONFIDENCE_THRESHOLD:
                        # Good enough — finalize immediately
                        messages.append({
                            "role": "assistant",
                            "content": message.content or "",
                            "tool_calls": [{
                                "id": tool_call.id,
                                "type": "function",
                                "function": {
                                    "name": tool_call.function.name,
                                    "arguments": tool_call.function.arguments,
                                }
                            }]
                        })
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_result_str,
                        })
                        return _finalize(state, best_result, best_confidence, search_count)

                    # Low confidence — add reflection note and retry
                    print(f"    [FAQ Agent] Low confidence — adding reflection note")
                    tool_result_str = (
                        tool_result +
                        f"\n[REFLECTION] Confidence {confidence} is below {CONFIDENCE_THRESHOLD}. "
                        f"Try a simpler or rephrased query."
                    )
                except Exception:
                    pass
            elif tool_name == "search_menu_info":
                try:
                    parsed = json.loads(tool_result)
                    if parsed.get("found"):
                        best_result = parsed
                        best_confidence = max(best_confidence, 1.0)
                        messages.append({
                            "role": "assistant",
                            "content": message.content or "",
                            "tool_calls": [{
                                "id": tool_call.id,
                                "type": "function",
                                "function": {
                                    "name": tool_call.function.name,
                                    "arguments": tool_call.function.arguments,
                                }
                            }]
                        })
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_result_str,
                        })
                        return _finalize(state, best_result, best_confidence, search_count)
                except Exception:
                    pass

            messages.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [{
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    }
                }]
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_result_str,
            })

        # ── Max searches hit → finalize now ───────────────────────────────────
        elif message.tool_calls and search_count >= MAX_SEARCHES:
            print(f"    [FAQ Agent] Max searches reached. Finalizing.")
            return _finalize(state, best_result, best_confidence, search_count)

        # ── LLM gave plain text directly ───────────────────────────────────────
        else:
            print(f"    [FAQ Agent] LLM gave plain text directly.")
            if best_result:
                return _finalize(state, best_result, best_confidence, search_count)
            state["reply"]          = (message.content or "").strip() or _fallback_reply()
            state["stuck"]          = False
            state["faq_confidence"] = best_confidence
            state["faq_searches"]   = search_count
            return state

    # ── Max iterations exceeded ────────────────────────────────────────────────
    print(f"    [FAQ Agent] Max iterations exceeded.")
    return _finalize(state, best_result, best_confidence, search_count)
