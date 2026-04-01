import psycopg2

from config import conn


def get_cursor():
    return conn.cursor()


# ── Orders ────────────────────────────────────────────────────────────────────

def get_latest_order(customer_id):
    """Returns (order_id, order_status, payment_status) for the latest order."""
    cur = get_cursor()
    cur.execute("""
        SELECT order_id, order_status, payment_status
        FROM orders
        WHERE customer_id = %s
        ORDER BY created_at DESC
        LIMIT 1
    """, (customer_id,))
    return cur.fetchone()


# ── Payments ──────────────────────────────────────────────────────────────────

def process_refund(order_id):
    """Marks the order payment as refunded."""
    cur = get_cursor()
    cur.execute("""
        UPDATE orders
        SET payment_status = 'refunded'
        WHERE order_id = %s
    """, (order_id,))
    conn.commit()


# ── Coupons ───────────────────────────────────────────────────────────────────

def issue_coupon(customer_id, discount_pct=10):
    """
    Issues a compensation coupon for the customer.
    Requires a `coupons` table:
      CREATE TABLE coupons (
        id SERIAL PRIMARY KEY,
        customer_id INT,
        discount_pct INT,
        issued_at TIMESTAMP DEFAULT NOW(),
        used BOOLEAN DEFAULT FALSE
      );
    """
    cur = get_cursor()
    cur.execute("""
        INSERT INTO coupons (customer_id, discount_pct)
        VALUES (%s, %s)
    """, (customer_id, discount_pct))
    conn.commit()


# ── Replacements ─────────────────────────────────────────────────────────────

def create_replacement_order(order_id, customer_id):
    """
    Creates a new replacement order cloned from the original.
    Requires orders table to have a self-referencing replacement_for column:
      ALTER TABLE orders ADD COLUMN replacement_for INT REFERENCES orders(order_id);
    """
    cur = get_cursor()
    cur.execute("""
        INSERT INTO orders (customer_id, order_status, payment_status, replacement_for)
        SELECT customer_id, 'confirmed', 'paid', order_id
        FROM orders
        WHERE order_id = %s
        RETURNING order_id
    """, (order_id,))
    new_order_id = cur.fetchone()[0]
    cur.execute("""
        UPDATE orders SET order_status = 'replaced' WHERE order_id = %s
    """, (order_id,))
    conn.commit()
    return new_order_id


# ── Complaints ────────────────────────────────────────────────────────────────

def log_complaint(order_id, complaint_type):
    """
    Logs a formal complaint against an order.
    Requires a `complaints` table:
      CREATE TABLE complaints (
        id SERIAL PRIMARY KEY,
        order_id INT,
        complaint_type VARCHAR(50),
        logged_at TIMESTAMP DEFAULT NOW()
      );
    """
    cur = get_cursor()
    cur.execute("""
        INSERT INTO complaints (order_id, complaint_type)
        VALUES (%s, %s)
    """, (order_id, complaint_type))
    conn.commit()


def save_complaint(customer_id, order_id, complaint_type, description):
    """
    Saves a complaint record when a real complaint is detected.
    Requires a `complaint_records` table:
      CREATE TABLE complaint_records (
        id SERIAL PRIMARY KEY,
        customer_id INT,
        order_id INT,
        complaint_type VARCHAR(50),
        description TEXT,
        status VARCHAR(20) DEFAULT 'OPEN',
        created_at TIMESTAMP DEFAULT NOW(),
        resolved_at TIMESTAMP
      );
    """
    cur = get_cursor()
    cur.execute("""
        INSERT INTO complaint_records (customer_id, order_id, complaint_type, description, status)
        VALUES (%s, %s, %s, %s, 'OPEN')
        RETURNING id
    """, (customer_id, order_id, complaint_type, description))
    complaint_id = cur.fetchone()[0]
    conn.commit()
    return complaint_id


def resolve_complaint(customer_id, order_id):
    """
    Marks the most recent open complaint for this order as resolved.
    """
    cur = get_cursor()
    cur.execute("""
        UPDATE complaint_records
        SET status = 'RESOLVED', resolved_at = NOW()
        WHERE customer_id = %s AND order_id = %s AND status = 'OPEN'
    """, (customer_id, order_id))
    conn.commit()


def escalate_ticket(order_id, customer_id):
    """
    Escalates an issue by inserting a high-priority support ticket.
    Requires a `support_tickets` table:
      CREATE TABLE support_tickets (
        id SERIAL PRIMARY KEY,
        order_id INT,
        customer_id INT,
        priority VARCHAR(20) DEFAULT 'HIGH',
        status VARCHAR(20) DEFAULT 'OPEN',
        created_at TIMESTAMP DEFAULT NOW()
      );
    """
    cur = get_cursor()
    cur.execute("""
        INSERT INTO support_tickets (order_id, customer_id, priority, status)
        VALUES (%s, %s, 'HIGH', 'OPEN')
    """, (order_id, customer_id))
    conn.commit()


# ── Messages ──────────────────────────────────────────────────────────────────

def save_message(customer_id, sender, message_text, intent):
    """Persists a conversation message."""
    cur = get_cursor()
    cur.execute("""
        INSERT INTO messages (customer_id, sender, message_text, intent)
        VALUES (%s, %s, %s, %s)
    """, (customer_id, sender, message_text, intent))
    conn.commit()

def get_customer_by_phone(phone):
    cur = get_cursor()
    cur.execute("""
        SELECT customer_id FROM customers
        WHERE phone = %s
    """, (phone,))
    row = cur.fetchone()
    return row[0] if row else None