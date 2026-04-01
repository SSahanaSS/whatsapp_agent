from langgraph.graph import StateGraph, END
from models.state import AgentState
from agents.supervisor import supervisor_agent
from agents.oagent import order_agent
from agents.complaint import complaint_agent
from agents.faq import faq_agent
from services.db import save_sticky_route


def clarification_node(state: dict) -> dict:
    state["sticky_route"] = None
    customer_id = state.get("customer_id")
    if customer_id:
        save_sticky_route(customer_id, None)
    state["stuck"] = False
    state["reply"] = (
        "I can help with placing an order, order support, or menu and business questions. "
        "Please rephrase your message a little."
    )
    return state


def _entry_router(state: dict) -> str:
    sticky = state.get("sticky_route")
    if sticky in ("order", "complaint", "faq"):
        print(f"[Entry] Sticky route → {sticky}")
        return sticky
    print("[Entry] No sticky → supervisor")
    return "supervisor"


def _agent_exit(state: dict) -> str:
    if state.get("stuck"):
        print("[agent_exit] Stuck → clarification")
        return "clarification"
    if state.get("escalated"):
        print("[agent_exit] Escalated → supervisor")
        return "supervisor"
    return "end"


def _route(state: dict) -> str:
    route = state.get("route", "unknown")
    print(f"[Router] Received route: {route}")
    if route == "greeting":
        print("[Router] Greeting route → END")
        return "end"
    if route not in ("order", "complaint", "faq"):
        print("[Router] Invalid or unclear route → clarification")
        return "clarification"
    return route


def build_graph():
    workflow = StateGraph(AgentState)

    workflow.add_node("supervisor", supervisor_agent)
    workflow.add_node("order", order_agent)
    workflow.add_node("complaint", complaint_agent)
    workflow.add_node("faq", faq_agent)
    workflow.add_node("clarification", clarification_node)

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
            "clarification": "clarification",
            "end": END,
        },
    )

    workflow.add_conditional_edges(
        "order",
        _agent_exit,
        {
            "supervisor": "supervisor",
            "clarification": "clarification",
            "end":        END,
        }
    )

    workflow.add_conditional_edges(
        "complaint",
        _agent_exit,
        {
            "supervisor": "supervisor",
            "clarification": "clarification",
            "end": END,
        }
    )

    workflow.add_conditional_edges(
        "faq",
        _agent_exit,
        {
            "supervisor": "supervisor",
            "clarification": "clarification",
            "end": END,
        }
    )

    workflow.add_edge("clarification", END)

    return workflow.compile()
