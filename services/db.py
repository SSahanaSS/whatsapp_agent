import json
from config import cur,conn

def get_or_create_customer(phone):
    clean_phone = phone.replace("whatsapp:", "")
    cur.execute("SELECT customer_id FROM customers WHERE phone=%s", (clean_phone,))
    result = cur.fetchone()
    if result:
        return result[0]
    cur.execute(
        "INSERT INTO customers (phone) VALUES (%s) RETURNING customer_id",
        (clean_phone,)
    )
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


def get_menu():
    cur.execute("SELECT item_name, price FROM menu WHERE availability=TRUE")
    rows = cur.fetchall()
    return [{"item_name": r[0], "price": float(r[1])} for r in rows]


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
    conn.commit()  # ✅ don't forget to commit!
    print(f"[DB] Session completed for customer_id={customer_id}")