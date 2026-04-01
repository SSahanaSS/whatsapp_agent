import json
from config import cur, conn
from datetime import datetime
import pytz

IST = pytz.timezone("Asia/Kolkata")


def _current_ist_time():
    return datetime.now(IST).time().replace(microsecond=0)


def get_or_create_customer(phone):
    clean_phone = phone.replace("whatsapp:", "").lstrip("+")
    cur.execute("SELECT customer_id FROM customers WHERE phone=%s", (clean_phone,))
    result = cur.fetchone()
    if result:
        return result[0]
    cur.execute(
        "INSERT INTO customers (phone) VALUES (%s) RETURNING customer_id",
        (clean_phone,)
    )
    conn.commit()
    return cur.fetchone()[0]


def get_history(customer_id):
    cur.execute("""
        SELECT sender, message_text FROM messages
        WHERE customer_id=%s
        ORDER BY created_at ASC
    """, (customer_id,))
    rows = cur.fetchall()
    return "\n".join([f"{r[0]}: {r[1]}" for r in rows])


def save_message(customer_id, sender, text):
    cur.execute("""
        INSERT INTO messages (customer_id, sender, message_text)
        VALUES (%s, %s, %s)
    """, (customer_id, sender, text))
    conn.commit()




def get_menu():
    current_time = _current_ist_time()
    cur.execute("""
        SELECT item_id, item_name, price, availability, available_from, available_until
        FROM menu
        WHERE availability = TRUE
        AND %s::time BETWEEN available_from AND available_until
        ORDER BY available_from, item_id
    """, (current_time,))
    rows = cur.fetchall()
    return [
        {
            "item_id": r[0],
            "item_name": r[1],
            "price": float(r[2]),
            "availability": bool(r[3]),
            "available_from": str(r[4]),
            "available_until": str(r[5]),
        }
        for r in rows
    ]


def get_active_session(customer_id):
    cur.execute("""
        SELECT session_id, items
        FROM order_sessions
        WHERE customer_id=%s AND status='active'
    """, (customer_id,))
    row = cur.fetchone()
    if not row:
        return None
    session_id, items = row
    if isinstance(items, str):
        items = json.loads(items)
    return session_id, items


def save_session(customer_id, items):
    existing = get_active_session(customer_id)
    items_json = json.dumps(items)
    if existing:
        cur.execute("""
            UPDATE order_sessions
            SET items=%s, updated_at=CURRENT_TIMESTAMP
            WHERE session_id=%s
        """, (items_json, existing[0]))
    else:
        cur.execute("""
            INSERT INTO order_sessions (customer_id, items, status)
            VALUES (%s, %s, 'active')
        """, (customer_id, items_json))
    conn.commit()


def finalize_order(customer_id, items):
    if isinstance(items, str):
        items = json.loads(items)
    total = 0
    for item in items:
        cur.execute(
            "SELECT price FROM menu WHERE item_name=%s",
            (item["item_name"],)
        )
        price = cur.fetchone()
        if price:
            total += float(price[0]) * item["qty"]
    cur.execute("""
        INSERT INTO orders
        (customer_id, order_details, total_amount, payment_status, order_status)
        VALUES (%s, %s, %s, %s, %s)
    """, (
        customer_id,
        json.dumps(items),
        total,
        "pending",
        "confirmed"
    ))
    cur.execute("""
        UPDATE order_sessions
        SET status='completed'
        WHERE customer_id=%s AND status='active'
    """, (customer_id,))
    conn.commit()
    return total


def merge_cart(current_order, action, items):
    if isinstance(current_order, str):
        current_order = json.loads(current_order)
    if not current_order:
        current_order = []
    cart = {item["item_name"]: item["qty"] for item in current_order}
    for item in items:
        name = item["item_name"]
        qty = item.get("qty", 1)
        if action == "ADD":
            cart[name] = cart.get(name, 0) + qty
        elif action == "REMOVE":
            cart.pop(name, None)
        elif action == "UPDATE":
            if qty <= 0:
                cart.pop(name, None)
            else:
                cart[name] = qty
    return [{"item_name": k, "qty": v} for k, v in cart.items()]


def mark_session_completed(customer_id: int):
    cur.execute("""
        UPDATE order_sessions
        SET status = 'completed'
        WHERE customer_id = %s AND status = 'active'
    """, (customer_id,))
    conn.commit()
    print(f"[DB] Session completed for customer_id={customer_id}")


# ── ETA FUNCTIONS ──────────────────────────────────────────────────────────────

def get_prep_time(items):
    """Base prep time from total quantity of items ordered."""
    total_qty = sum(item["qty"] for item in items)
    if total_qty <= 2:
        return 15
    elif total_qty <= 5:
        return 25
    elif total_qty <= 10:
        return 35
    else:
        return 50


def get_kitchen_queue_delay():
    """Each confirmed+unpaid order in last 2 hours adds 10 mins of queue delay."""
    cur.execute("""
        SELECT COUNT(*) FROM orders
        WHERE order_status = 'confirmed'
        AND payment_status = 'pending'
        AND created_at > NOW() - INTERVAL '2 hours'
    """)
    pending_count = cur.fetchone()[0]
    return pending_count * 10


def save_eta(customer_id, eta_minutes, address=None):
    """Save ETA and delivery address to the most recent order."""
    cur.execute("""
        UPDATE orders
        SET eta_minutes = %s,
            customer_address = %s
        WHERE customer_id = %s
        AND created_at = (
            SELECT MAX(created_at) FROM orders WHERE customer_id = %s
        )
    """, (eta_minutes, address, customer_id, customer_id))
    conn.commit()
    print(f"[DB] ETA {eta_minutes} mins saved for customer_id={customer_id}")


def get_saved_address(customer_id):
    """Fetch the last used delivery address for returning customers."""
    cur.execute("""
        SELECT customer_address FROM orders
        WHERE customer_id = %s
        AND customer_address IS NOT NULL
        ORDER BY created_at DESC LIMIT 1
    """, (customer_id,))
    row = cur.fetchone()
    return row[0] if row else None

def get_sticky_route(customer_id: int):
    cur.execute("""
        SELECT sticky_route FROM customers
        WHERE customer_id = %s
    """, (customer_id,))
    row = cur.fetchone()
    return row[0] if row else None

def save_sticky_route(customer_id: int, route):
    cur.execute("""
        UPDATE customers
        SET sticky_route = %s, sticky_updated_at = NOW()
        WHERE customer_id = %s
    """, (route, customer_id))
    conn.commit()
