import { useFetch } from "../hooks/useAPI";
import { Badge, MetricCard, Table, SectionCard, Spinner, ErrorMsg } from "../ui";

function orderStatusBadge(s) {
  const map = { delivered: "green", confirmed: "blue", replaced: "amber", cancelled: "red", pending: "gray" };
  return <Badge type={map[s] || "gray"}>{s}</Badge>;
}

function payStatusBadge(s) {
  const map = { paid: "green", pending: "amber", refunded: "blue" };
  return <Badge type={map[s] || "gray"}>{s}</Badge>;
}

function fmt(val) {
  if (val === null || val === undefined) return "—";
  return val;
}

function formatTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata" });
}

export default function OrdersTab() {
  const { data: stats, loading: sl, error: se } = useFetch("/api/orders/stats", 30000);
  const { data: orders, loading: ol, error: oe } = useFetch("/api/orders/today", 30000);

  const columns = [
    { key: "order_id", label: "Order ID", mono: true, render: v => `#${v}` },
    { key: "phone", label: "Customer", render: (v) => v || "—" },
    { key: "total_amount", label: "Amount", mono: true, render: v => `₹${Number(v).toFixed(0)}` },
    { key: "order_status", label: "Status", render: v => orderStatusBadge(v) },
    { key: "payment_status", label: "Payment", render: v => payStatusBadge(v) },
    { key: "eta_minutes", label: "ETA", mono: true, muted: true, render: v => v ? `${v} min` : "—" },
    { key: "created_at", label: "Time", mono: true, muted: true, render: v => formatTime(v) },
  ];

  return (
    <div>
      {sl ? <Spinner /> : se ? <ErrorMsg message={se} /> : stats && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 10, marginBottom: 16 }}>
          <MetricCard label="Orders today" value={stats.total_orders} sub={`${stats.active_orders} active`} />
          <MetricCard label="Revenue" value={`₹${Number(stats.total_revenue).toFixed(0)}`} valueColor="#BA7517" sub={stats.total_orders ? `avg ₹${Math.round(stats.total_revenue / stats.total_orders)}` : ""} />
          <MetricCard label="Pending payments" value={stats.pending_payments} valueColor={stats.pending_payments > 0 ? "#854F0B" : undefined} />
          <MetricCard label="Refunds" value={stats.refunds} valueColor={stats.refunds > 0 ? "#A32D2D" : undefined} />
        </div>
      )}

      <SectionCard
        title="Today's orders"
        action={<span style={{ fontSize: 11, fontFamily: "'IBM Plex Mono', monospace", color: "#aaa" }}>{orders?.total ?? 0} orders · refreshes every 30s</span>}
      >
        {ol ? <Spinner /> : oe ? <ErrorMsg message={oe} /> : (
          <Table columns={columns} rows={orders?.orders ?? []} emptyMessage="No orders yet today" />
        )}
      </SectionCard>
    </div>
  );
}