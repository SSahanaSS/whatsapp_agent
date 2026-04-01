import { useFetch } from "../hooks/useAPI";
import { Badge, MetricCard, Table, SectionCard, Spinner, ErrorMsg } from "../ui";

function formatTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata" });
}

export default function ComplaintsTab() {
  const { data, loading, error } = useFetch("/api/complaints/today", 20000);

  const columns = [
    { key: "id", label: "Ticket", mono: true, render: v => `#C${String(v).padStart(3, "0")}` },
    { key: "order_id", label: "Order", mono: true, render: v => `#${v}` },
    { key: "complaint_type", label: "Type", render: v => v?.replace(/_/g, " ") || "—" },
    { key: "description", label: "Description", render: v => v ? <span style={{ maxWidth: 200, display: "inline-block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={v}>{v}</span> : "—" },
    { key: "status", label: "Status", render: v => <Badge type={v === "RESOLVED" ? "green" : "red"}>{v?.toLowerCase()}</Badge> },
    { key: "escalated", label: "Escalated", render: v => v ? <Badge type="amber">yes</Badge> : <Badge type="gray">no</Badge> },
    { key: "created_at", label: "Logged", mono: true, muted: true, render: v => formatTime(v) },
    { key: "resolved_at", label: "Resolved", mono: true, muted: true, render: v => formatTime(v) },
  ];

  return (
    <div>
      {!loading && !error && data && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10, marginBottom: 16 }}>
          <MetricCard label="Total today" value={data.complaints?.length ?? 0} />
          <MetricCard label="Open" value={data.open_count} valueColor={data.open_count > 0 ? "#A32D2D" : undefined} />
          <MetricCard label="Escalated" value={data.escalated_count} valueColor={data.escalated_count > 0 ? "#854F0B" : undefined} />
        </div>
      )}
      <SectionCard
        title="Complaint tickets"
        action={<span style={{ fontSize: 11, fontFamily: "'IBM Plex Mono', monospace", color: "#aaa" }}>refreshes every 20s</span>}
      >
        {loading ? <Spinner /> : error ? <ErrorMsg message={error} /> : (
          <Table columns={columns} rows={data?.complaints ?? []} emptyMessage="No complaints today" />
        )}
      </SectionCard>
    </div>
  );
}