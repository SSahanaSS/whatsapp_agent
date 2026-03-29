from typing import TypedDict, List, Dict, Any, Optional


class AgentState(TypedDict):
    # ── Customer context ───────────────────────────────────────────────────────
    customer_id: int
    sender: str
    message: str
    history: str
    menu: List[Dict[str, Any]]

    # ── Order state ────────────────────────────────────────────────────────────
    current_order: List[Dict[str, Any]]
    intent: str
    action: str
    items: List[Dict[str, Any]]
    reply: str
    summary: str
    total_amount: float
    payment_status: Optional[str]
    payment_link_id: Optional[str]
    stage: str

    # ── Supervisor routing ─────────────────────────────────────────────────────
    route: str          # 'order' | 'complaint' | 'faq' | 'greeting'
    sticky_route: Optional[str]   # 👈 holds route across turns

    # ── Complaint handling (supervisor fills these) ─────────────────────────────
    resolved: bool   

    # ── FAQ handling (supervisor fills these) ─────────────────────────────
    stuck:          bool              # 👈 faq couldn't answer
    stuck_reason:   str               # 👈 why it got stuck
    faq_confidence: Optional[float]   # 👈 debug info
    faq_searches:   Optional[int] 