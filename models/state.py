from typing import TypedDict, List, Dict, Any, Optional


class AgentState(TypedDict):
    customer_id:      int
    sender:           str
    message:          str
    history:          str
    menu:             List[Dict[str, Any]]
    current_order:    List[Dict[str, Any]]
    delivery_address: str
    intent:           str
    action:           str
    items:            List[Dict[str, Any]]
    reply:            str
    summary:          str
    total_amount:     float
    payment_status:   Optional[str]
    payment_link_id:  Optional[str]
    stage:            str
    route:            str
    sticky_route:     Optional[str]
    resolved:         bool
    stuck:            bool
    stuck_reason:     str
    faq_confidence:   Optional[float]
    faq_searches:     Optional[int]
    escalated:        Optional[bool]   # ✅ only new field needed
