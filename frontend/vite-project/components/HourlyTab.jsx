import { useEffect, useRef } from "react";
import { useFetch } from "../hooks/useAPI";
import { SectionCard, Spinner, ErrorMsg } from "../ui";

function HourlyChart({ id, labels, data, label, color, yPrefix = "" }) {
  const ref = useRef(null);
  const chartRef = useRef(null);

  useEffect(() => {
    if (!ref.current || !data) return;

    if (chartRef.current) chartRef.current.destroy();

    chartRef.current = new window.Chart(ref.current, {
      type: id === "revenue" ? "line" : "bar",
      data: {
        labels,
        datasets: [{
          label,
          data,
          backgroundColor: id === "revenue" ? color + "22" : color,
          borderColor: color,
          borderWidth: id === "revenue" ? 2 : 0,
          borderRadius: id === "revenue" ? 0 : 4,
          fill: id === "revenue",
          tension: 0.35,
          pointRadius: 3,
          pointBackgroundColor: color,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { display: false }, ticks: { font: { size: 11, family: "'IBM Plex Mono', monospace" } } },
          y: {
            grid: { color: "rgba(0,0,0,0.05)" },
            ticks: {
              font: { size: 11, family: "'IBM Plex Mono', monospace" },
              callback: v => yPrefix + v,
            },
          },
        },
      },
    });
    return () => chartRef.current?.destroy();
  }, [data, labels]);

  return (
    <div style={{ padding: 16, height: 220, position: "relative" }}>
      <canvas ref={ref} id={id} />
    </div>
  );
}

export default function HourlyTab() {
  const { data, loading, error } = useFetch("/api/orders/hourly", 60000);

  if (loading) return <Spinner />;
  if (error) return <ErrorMsg message={error} />;

  const allHours = Array.from({ length: 18 }, (_, i) => i + 6); // 6am–11pm
  const byHour = {};
  (data?.hourly ?? []).forEach(h => { byHour[Math.floor(Number(h.hour))] = h; });

  const labels = allHours.map(h => `${String(h).padStart(2, "0")}:00`);
  const orderCounts = allHours.map(h => Number(byHour[h]?.order_count ?? 0));
  const revenues = allHours.map(h => Math.round(Number(byHour[h]?.revenue ?? 0)));

  const peakHour = allHours[orderCounts.indexOf(Math.max(...orderCounts))];
  const totalOrders = orderCounts.reduce((a, b) => a + b, 0);
  const totalRevenue = revenues.reduce((a, b) => a + b, 0);

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0,1fr))", gap: 10, marginBottom: 16 }}>
        <div style={{ background: "rgba(0,0,0,0.03)", borderRadius: 8, padding: "14px 16px" }}>
          <div style={{ fontSize: 11, color: "#aaa", fontFamily: "'IBM Plex Mono', monospace", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>Peak hour</div>
          <div style={{ fontSize: 22, fontWeight: 500, fontFamily: "'IBM Plex Mono', monospace" }}>{String(peakHour).padStart(2,"0")}:00</div>
        </div>
        <div style={{ background: "rgba(0,0,0,0.03)", borderRadius: 8, padding: "14px 16px" }}>
          <div style={{ fontSize: 11, color: "#aaa", fontFamily: "'IBM Plex Mono', monospace", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>Total orders</div>
          <div style={{ fontSize: 22, fontWeight: 500, fontFamily: "'IBM Plex Mono', monospace" }}>{totalOrders}</div>
        </div>
        <div style={{ background: "rgba(0,0,0,0.03)", borderRadius: 8, padding: "14px 16px" }}>
          <div style={{ fontSize: 11, color: "#aaa", fontFamily: "'IBM Plex Mono', monospace", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>Total revenue</div>
          <div style={{ fontSize: 22, fontWeight: 500, fontFamily: "'IBM Plex Mono', monospace", color: "#BA7517" }}>₹{totalRevenue.toLocaleString("en-IN")}</div>
        </div>
      </div>

      <SectionCard title="Orders by hour" action={<span style={{ fontSize: 11, fontFamily: "'IBM Plex Mono', monospace", color: "#aaa" }}>refreshes every 60s</span>}>
        <HourlyChart id="orders" labels={labels} data={orderCounts} label="Orders" color="#185FA5" />
      </SectionCard>

      <SectionCard title="Revenue by hour">
        <HourlyChart id="revenue" labels={labels} data={revenues} label="Revenue" color="#BA7517" yPrefix="₹" />
      </SectionCard>
    </div>
  );
}