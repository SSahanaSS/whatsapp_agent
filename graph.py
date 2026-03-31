from langgraph.graph import StateGraph, END
from models.state import AgentState
from agents.supervisor import supervisor_agent
from agents.oagent import order_agent
from agents.complaint import complaint_agent
from agents.faq import faq_agent


def _entry_router(state: dict) -> str:
    sticky = state.get("sticky_route")
    if sticky in ("order", "complaint", "faq"):
        print(f"[Entry] Sticky route → {sticky}")
        return sticky
    print("[Entry] No sticky → supervisor")
    return "supervisor"


def _order_exit(state: dict) -> str:
    if state.get("escalated"):
        print("[order_exit] Escalated → supervisor")
        return "supervisor"
    return "end"


def _route(state: dict) -> str:
    route = state.get("route", "unknown")
    print(f"[Router] Received route: {route}")
    if route not in ("order", "complaint", "faq"):
        print("[Router] Invalid or terminal route → END")
        return "end"
    return route

def _complaint_exit(state: dict) -> str:
    if state.get("sticky_route") is None:
        print("[complaint_exit] Resolved → END")
        return "end"
    return "end"  # always ends for now, sticky handled by _entry_router next turn

 # stays the same, sticky via _entry_router


def build_graph():
    workflow = StateGraph(AgentState)

    workflow.add_node("supervisor", supervisor_agent)
    workflow.add_node("order", order_agent)
    workflow.add_node("complaint", complaint_agent)
    workflow.add_node("faq", faq_agent)

    workflow.set_conditional_entry_point(
        _entry_router,
        {
            "supervisor": "supervisor",
            "order":      "order",
            "complaint":  "complaint",
            "faq":        "faq",
        }
    )

    workflow.add_conditional_edges(
        "supervisor",
        _route,
        {
            "order":     "order",
            "complaint": "complaint",
            "faq":       "faq",
            "end":       END,
        },
    )

    # ✅ order uses conditional exit — escalate goes back to supervisor
    workflow.add_conditional_edges(
        "order",
        _order_exit,
        {
            "supervisor": "supervisor",
            "end":        END,
        }
    )

    # complaint and faq always end
    workflow.add_edge("complaint", END)
    workflow.add_edge("faq", END)

    return workflow.compile()