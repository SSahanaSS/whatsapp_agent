from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
import psycopg2.extras
import pytz

app = FastAPI(title="Kitchen Ops Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

IST = pytz.timezone("Asia/Kolkata")


# ── DB ─────────────────────────────────────────────────────────────────────────
def get_conn():
    conn = psycopg2.connect(
        host="localhost",
        database="business_proj",
        user="postgres",
        password="Soup#2004",
        options="-c timezone=Asia/Kolkata",
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    return conn


# ── Models ─────────────────────────────────────────────────────────────────────
class MenuItemUpdate(BaseModel):
    availability: bool

class MenuItemCreate(BaseModel):
    item_name:       str
    price:           float
    available_from:  str   # "HH:MM"
    available_until: str   # "HH:MM"


# ── Orders ─────────────────────────────────────────────────────────────────────
@app.get("/api/orders/today")
def get_orders_today():
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        SELECT
            o.order_id,
            o.customer_id,
            c.phone,
            o.order_details,
            o.total_amount,
            o.order_status,
            o.payment_status,
            o.created_at,
            o.eta_minutes
        FROM orders o
        LEFT JOIN customers c ON c.customer_id = o.customer_id
        WHERE o.created_at::date = CURRENT_DATE
        ORDER BY o.created_at DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return {"orders": [dict(r) for r in rows], "total": len(rows)}


@app.get("/api/orders/stats")
def get_order_stats():
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        SELECT
            COUNT(*)                                                    AS total_orders,
            COALESCE(SUM(total_amount), 0)                             AS total_revenue,
            COUNT(*) FILTER (WHERE payment_status = 'pending')         AS pending_payments,
            COUNT(*) FILTER (WHERE payment_status = 'refunded')        AS refunds,
            COUNT(*) FILTER (WHERE order_status  = 'confirmed')        AS active_orders,
            COUNT(*) FILTER (WHERE payment_status = 'paid')            AS delivered
        FROM orders
        WHERE created_at::date = CURRENT_DATE
    """)
    row = cur.fetchone()
    conn.close()
    return dict(row)


@app.get("/api/orders/hourly")
def get_hourly_breakdown():
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        SELECT
            EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Kolkata') AS hour,
            COUNT(*)                                                    AS order_count,
            COALESCE(SUM(total_amount), 0)                             AS revenue
        FROM orders
        WHERE created_at::date = CURRENT_DATE
        GROUP BY 1
        ORDER BY 1
    """)
    rows = cur.fetchall()
    conn.close()
    return {"hourly": [dict(r) for r in rows]}


# ── Complaints ─────────────────────────────────────────────────────────────────
@app.get("/api/complaints/today")
def get_complaints_today():
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        SELECT
            cr.id,
            cr.customer_id,
            cr.order_id,
            cr.complaint_type,
            cr.description,
            cr.status,
            cr.created_at,
            cr.resolved_at,
            CASE WHEN st.id IS NOT NULL THEN TRUE ELSE FALSE END AS escalated
        FROM complaint_records cr
        LEFT JOIN support_tickets st
            ON  st.order_id    = cr.order_id
            AND st.customer_id = cr.customer_id
            AND st.status      = 'OPEN'
        WHERE cr.created_at::date = CURRENT_DATE
        ORDER BY cr.created_at DESC
    """)
    rows = cur.fetchall()

    cur.execute("""
        SELECT COUNT(*) AS open_count FROM complaint_records
        WHERE status = 'OPEN' AND created_at::date = CURRENT_DATE
    """)
    open_count = cur.fetchone()["open_count"]

    cur.execute("""
        SELECT COUNT(*) AS escalated_count FROM support_tickets
        WHERE status = 'OPEN' AND created_at::date = CURRENT_DATE
    """)
    escalated_count = cur.fetchone()["escalated_count"]

    conn.close()
    return {
        "complaints":       [dict(r) for r in rows],
        "open_count":       open_count,
        "escalated_count":  escalated_count,
    }


# ── Menu ───────────────────────────────────────────────────────────────────────
@app.get("/api/menu")
def get_menu():
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        SELECT item_id, item_name, price, availability, available_from, available_until
        FROM menu
        ORDER BY available_from, item_id
    """)
    rows = cur.fetchall()
    conn.close()
    return {"items": [dict(r) for r in rows]}


@app.patch("/api/menu/{item_id}")
def update_menu_availability(item_id: int, body: MenuItemUpdate):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        "UPDATE menu SET availability = %s WHERE item_id = %s RETURNING item_id",
        (body.availability, item_id)
    )
    updated = cur.fetchone()
    conn.commit()
    conn.close()
    if not updated:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"item_id": item_id, "availability": body.availability}


@app.post("/api/menu")
def create_menu_item(body: MenuItemCreate):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO menu (item_name, price, availability, available_from, available_until)
        VALUES (%s, %s, TRUE, %s::time, %s::time)
        RETURNING item_id
    """, (body.item_name, body.price, body.available_from, body.available_until))
    item_id = cur.fetchone()["item_id"]
    conn.commit()
    conn.close()
    return {"item_id": item_id, "item_name": body.item_name}


@app.delete("/api/menu/{item_id}")
def delete_menu_item(item_id: int):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("DELETE FROM menu WHERE item_id = %s RETURNING item_id", (item_id,))
    deleted = cur.fetchone()
    conn.commit()
    conn.close()
    if not deleted:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"deleted": item_id}