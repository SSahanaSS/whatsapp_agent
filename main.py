import json
import hmac
import hashlib

from fastapi import FastAPI, Request, Form, Header

from config import TWILIO_WHATSAPP_NUMBER, RAZORPAY_WEBHOOK_SECRET, client
from graph import build_graph

from services.eta import calculate_full_eta
from services.wa import send_whatsapp

app = FastAPI()
graph = build_graph()

from services.db import (
    get_or_create_customer,
    get_history,
    get_menu,
    get_active_session,
    mark_session_completed,
    save_message,
    save_eta,
    get_sticky_route,
    cur,
    conn,
)


def _build_state(phone: str, message: str, lat: float = None, lng: float = None) -> dict:
    customer_id   = get_or_create_customer(phone)
    history       = get_history(customer_id)
    conn.rollback()  # prevent stale transaction from caching old menu
    menu          = get_menu()
    session       = get_active_session(customer_id)
    current_order = session[1] if session else []

    # ── Restore delivery address from most recent order ────────────────────────
    cur.execute("""
        SELECT customer_address FROM orders
        WHERE customer_id = %s
        ORDER BY created_at DESC LIMIT 1
    """, (customer_id,))
    row              = cur.fetchone()
    delivery_address = row[0] if row and row[0] else ""

    # ── Restore coords from customers table ────────────────────────────────────
    cur.execute("""
        SELECT customer_lat, customer_lng FROM customers
        WHERE customer_id = %s
    """, (customer_id,))
    coord_row = cur.fetchone()
    saved_lat  = lat  or (float(coord_row[0]) if coord_row and coord_row[0] else None)
    saved_lng  = lng  or (float(coord_row[1]) if coord_row and coord_row[1] else None)

    # ── Sticky route ───────────────────────────────────────────────────────────
    sticky = get_sticky_route(customer_id)
    print(f"[State] sticky_route from DB: {sticky}")

    return {
        "customer_id":      customer_id,
        "sender":           phone,
        "message":          message,
        "history":          history,
        "menu":             menu,
        "current_order":    current_order,
        "delivery_address": delivery_address,
        "customer_lat":     saved_lat,
        "customer_lng":     saved_lng,
        "intent":           "",
        "action":           "",
        "items":            [],
        "reply":            "",
        "summary":          "",
        "total_amount":     0,
        "payment_status":   None,
        "payment_link_id":  None,
        "stage":            "ordering",
        "route":            "",
        "sticky_route":     sticky,
        "resolved":         False,
        "stuck":            False,
        "stuck_reason":     "",
        "faq_confidence":   None,
        "faq_searches":     None,
        "escalated":        False,
    }


# ── WhatsApp Webhook ───────────────────────────────────────────────────────────

@app.post("/webhook/whatsapp")
async def whatsapp_webhook(
    request: Request,
    Body: str      = Form(default=""),
    From: str      = Form(...),
    Latitude: str  = Form(default=None),
    Longitude: str = Form(default=None),
):
    print(f"[Webhook] ✅ HIT — From: {From} | Body: {Body}") 
    phone   = From.replace("whatsapp:", "")
    message = Body.strip()
    lat     = float(Latitude)  if Latitude  else None
    lng     = float(Longitude) if Longitude else None

    if lat and lng:
        message = f"__location__{lat},{lng}"
        print(f"[Webhook] 📍 Location received: ({lat}, {lng})")

    try:
        state  = _build_state(phone, message, lat=lat, lng=lng)
        result = graph.invoke(state)
        reply  = result.get("reply") or "Sorry, something went wrong."

        customer_id = result.get("customer_id") or get_or_create_customer(phone)
        save_message(customer_id, "customer", Body or f"[Location: {lat},{lng}]")
        save_message(customer_id, "bot", reply)

    except Exception as e:
        import traceback
        traceback.print_exc()
        reply = "Sorry, something went wrong. Please try again."

    send_whatsapp(From, reply)
    return "OK"


# ── Razorpay Webhook ───────────────────────────────────────────────────────────

@app.post("/webhook/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(None),
):
    body = await request.body()

    generated_signature = hmac.new(
        bytes(RAZORPAY_WEBHOOK_SECRET, "utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(generated_signature, x_razorpay_signature):
        print("[Razorpay] ❌ Invalid signature")
        return {"status": "invalid"}

    data  = json.loads(body)
    event = data.get("event")
    print(f"[Razorpay] Event: {event}")

    if event not in ("payment_link.paid", "payment_link.cancelled", "payment.failed"):
        print(f"[Razorpay] Ignoring event: {event}")
        return {"status": "ignored"}

    payload = (
        data.get("payload", {})
            .get("payment_link", {})
            .get("entity")
    )

    if not payload:
        print(f"[Razorpay] ❌ No payment_link entity for event: {event}")
        return {"status": "no_payload"}

    raw_contact = payload.get("customer", {}).get("contact", "")
    if not raw_contact:
        print("[Razorpay] ❌ No contact found in payload")
        return {"status": "no_contact"}

    formatted_phone  = raw_contact if raw_contact.startswith("+") else f"+{raw_contact}"
    twilio_recipient = f"whatsapp:{formatted_phone}"
    print(f"[Razorpay] Contact: {formatted_phone}")

    customer_id = get_or_create_customer(formatted_phone)
    print(f"[Razorpay] customer_id: {customer_id}")

    if event == "payment_link.paid":
        amount   = payload.get("amount", 0) / 100
        order_id = payload.get("notes", {}).get("order_id", "N/A") if payload.get("notes") else "N/A"

        mark_session_completed(customer_id)
        print(f"[Razorpay] ✅ Session marked completed")

        cur.execute("""
            UPDATE orders SET payment_status = 'paid'
            WHERE customer_id = %s
            AND created_at = (SELECT MAX(created_at) FROM orders WHERE customer_id = %s)
        """, (customer_id, customer_id))
        conn.commit()

        # ── Fetch order details + coords from customers table ──────────────────
        cur.execute("""
            SELECT o.order_details, o.customer_address, c.customer_lat, c.customer_lng
            FROM orders o
            JOIN customers c ON o.customer_id = c.customer_id
            WHERE o.customer_id = %s
            ORDER BY o.created_at DESC LIMIT 1
        """, (customer_id,))
        row = cur.fetchone()

        eta_line = ""
        if row:
            order_details, customer_address, c_lat, c_lng = row
            items = json.loads(order_details) if isinstance(order_details, str) else order_details

            eta_result = calculate_full_eta(
                items,
                customer_address=customer_address,
                lat=float(c_lat) if c_lat else None,
                lng=float(c_lng) if c_lng else None,
            )
            total_eta = eta_result["total"]
            breakdown = eta_result["breakdown"]
            save_eta(customer_id, total_eta, customer_address)

            queue_line = (
                f"👨‍🍳 Kitchen queue: {breakdown['queue_delay']} mins\n"
                if breakdown["queue_delay"] > 0 else ""
            )
            eta_line = (
                f"\n\n🕐 *Estimated Delivery: {total_eta} minutes*\n"
                f"📦 Prep time: {breakdown['prep_time']} mins\n"
                f"{queue_line}"
                f"🚗 Travel time: {breakdown['travel_time']} mins\n"
                f"📍 Delivering to: {customer_address or 'your location'}"
            )

        reply = (
            f"✅ *Payment Received!*\n\n"
            f"Thank you! We've received your payment of ₹{amount:.2f}. "
            f"Your order is now being prepared. 🍳\n\n"
            f"Order ID: {order_id}"
            f"{eta_line}"
        )

        save_message(customer_id, "bot", reply)
        send_whatsapp(twilio_recipient, reply)
        print(f"[Razorpay] ✅ ETA message sent to {twilio_recipient}")

    elif event in ("payment_link.cancelled", "payment.failed"):
        reply = (
            "⚠️ Your payment was not successful.\n\n"
            "If you'd like to try again, use the link above "
            "or type anything and I'll help you out! 😊"
        )
        send_whatsapp(twilio_recipient, reply)
        print(f"[Razorpay] ⚠️ Failure message sent")

    return {"status": "ok"}


# ── CLI (for local testing) ────────────────────────────────────────────────────

def run_cli():
    phone = input("Enter your phone number (e.g. +91XXXXXXXXXX): ").strip()
    print("Type your message. Type 'exit' to quit.\n")

    while True:
        message = input("You: ").strip()
        if message.lower() == "exit":
            break

        try:
            state  = _build_state(phone, message)
            result = graph.invoke(state)
            reply  = result.get("reply") or "Sorry, something went wrong."

            customer_id = result.get("customer_id") or get_or_create_customer(phone)
            save_message(customer_id, "customer", message)
            save_message(customer_id, "bot", reply)

            print(f"\nBot: {reply}\n")

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Error: {e}\n")


if __name__ == "__main__":
    run_cli()