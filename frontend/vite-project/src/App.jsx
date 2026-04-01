import { useState, useEffect } from "react";
import OrdersTab from "../components/OrdersTab";
import ComplaintsTab from "../components/ComplaintsTab";
import MenuTab from "../components/MenuTab";
import HourlyTab from "../components/HourlyTab";

const TABS = [
  { id: "orders",     label: "Orders" },
  { id: "complaints", label: "Complaints" },
  { id: "menu",       label: "Menu" },
  { id: "hourly",     label: "Hourly" },
];

function Clock() {
  const [time, setTime] = useState("");
  useEffect(() => {
    const update = () => setTime(new Date().toLocaleTimeString("en-IN", {
      hour: "2-digit", minute: "2-digit", second: "2-digit",
      hour12: false, timeZone: "Asia/Kolkata"
    }) + " IST");
    update();
    const id = setInterval(update, 1000);
    return () => clearInterval(id);
  }, []);
  return <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, color: "#aaa" }}>{time}</span>;
}

export default function App() {
  const [tab, setTab] = useState("orders");

  return (
    <>
      <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=DM+Sans:wght@400;500&display=swap" rel="stylesheet" />
      <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js" />

      <div style={{
        minHeight: "100vh",
        background: "#f9f8f6",
        fontFamily: "'DM Sans', sans-serif",
        color: "#1a1a18",
      }}>
        {/* Top bar */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "14px 28px",
          borderBottom: "0.5px solid rgba(0,0,0,0.1)",
          background: "#fff",
          position: "sticky", top: 0, zIndex: 10,
        }}>
          <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, fontWeight: 500, letterSpacing: "0.1em", textTransform: "uppercase", color: "#555" }}>
            Kitchen Ops
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
            <Clock />
            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#1D9E75", fontFamily: "'IBM Plex Mono', monospace" }}>
              <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#1D9E75", display: "inline-block", animation: "pulse 1.8s infinite" }} />
              live
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div style={{ padding: "16px 28px 0", display: "flex", gap: 4 }}>
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              style={{
                padding: "7px 18px",
                border: "0.5px solid",
                borderColor: tab === t.id ? "rgba(0,0,0,0.2)" : "rgba(0,0,0,0.1)",
                borderRadius: 8,
                background: tab === t.id ? "#fff" : "transparent",
                color: tab === t.id ? "#1a1a18" : "#888",
                fontSize: 13,
                cursor: "pointer",
                fontFamily: "'DM Sans', sans-serif",
                fontWeight: tab === t.id ? 500 : 400,
                transition: "all 0.15s",
              }}
            >{t.label}</button>
          ))}
        </div>

        {/* Content */}
        <div style={{ padding: "20px 28px 40px" }}>
          {tab === "orders"     && <OrdersTab />}
          {tab === "complaints" && <ComplaintsTab />}
          {tab === "menu"       && <MenuTab />}
          {tab === "hourly"     && <HourlyTab />}
        </div>
      </div>

      <style>{`
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        button { font-family: inherit; }
        input { font-family: inherit; }
      `}</style>
    </>
  );
}