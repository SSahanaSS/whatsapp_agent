from langgraph.graph import StateGraph, END
from models.state import AgentState

from agents.supervisor import supervisor_agent
from agents.oagent import order_agent
from agents.complaint import complaint_agent
from agents.faq import faq_agent


# 🔥 SAFE ROUTER
def _route(state: dict) -> str:
    route = state.get("route", "unknown")  # ✅ FIXED

    print(f"[Router] Received route: {route}")

    # safety check
    if route not in ("order", "complaint", "faq"):
        print("[Router] Invalid or terminal route → END")
        return "end"

    return route


def build_graph():
    workflow = StateGraph(AgentState)

    # Nodes
    workflow.add_node("supervisor", supervisor_agent)
    workflow.add_node("order", order_agent)
    workflow.add_node("complaint", complaint_agent)
    workflow.add_node("faq", faq_agent)

    # Entry
    workflow.set_entry_point("supervisor")

    # Routing
    workflow.add_conditional_edges(
        "supervisor",
        _route,
        {
            "order": "order",
            "complaint": "complaint",
            "faq": "faq",
            "end": END,
        },
    )

    # End after each agent
    workflow.add_edge("order", END)
    workflow.add_edge("complaint", END)
    workflow.add_edge("faq", END)

    return workflow.compile()