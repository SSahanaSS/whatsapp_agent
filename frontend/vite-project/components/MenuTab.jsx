import { useState } from "react";
import { useFetch, apiPatch, apiPost, apiDelete } from "../hooks/useAPI";
import { SectionCard, Spinner, ErrorMsg } from "../ui";

function ToggleSwitch({ on, onChange }) {
  return (
    <button
      onClick={onChange}
      style={{
        width: 36, height: 20, borderRadius: 10, border: "none",
        background: on ? "#1D9E75" : "rgba(0,0,0,0.15)",
        cursor: "pointer", position: "relative", transition: "background 0.2s",
        flexShrink: 0,
      }}
    >
      <span style={{
        position: "absolute", top: 2,
        left: on ? 16 : 2, width: 16, height: 16,
        borderRadius: "50%", background: "#fff",
        transition: "left 0.2s", display: "block",
      }} />
    </button>
  );
}

export default function MenuTab() {
  const { data, loading, error, refetch } = useFetch("/api/menu");
  const [saving, setSaving] = useState(null);
  const [form, setForm] = useState({ item_name: "", price: "", available_from: "", available_until: "" });
  const [adding, setAdding] = useState(false);
  const [formError, setFormError] = useState("");

  async function handleToggle(item) {
    setSaving(item.item_id);
    try {
      await apiPatch(`/api/menu/${item.item_id}`, { availability: !item.availability });
      await refetch();
    } catch (e) {
      alert("Failed to update: " + e.message);
    } finally {
      setSaving(null);
    }
  }

  async function handleAdd() {
    setFormError("");
    if (!form.item_name.trim() || !form.price) { setFormError("Name and price are required."); return; }
    setAdding(true);
    try {
      await apiPost("/api/menu", {
        item_name: form.item_name.trim(),
        price: parseFloat(form.price),
        available_from: form.available_from || "00:00",
        available_until: form.available_until || "23:59",
      });
      setForm({ item_name: "", price: "", available_from: "", available_until: "" });
      await refetch();
    } catch (e) {
      setFormError(e.message);
    } finally {
      setAdding(false);
    }
  }

  async function handleDelete(item_id) {
    if (!confirm("Delete this item?")) return;
    setSaving(item_id);
    try {
      await apiDelete(`/api/menu/${item_id}`);
      await refetch();
    } catch (e) {
      alert("Delete failed: " + e.message);
    } finally {
      setSaving(null);
    }
  }

  const items = data?.items ?? [];
  const available = items.filter(i => i.availability);
  const unavailable = items.filter(i => !i.availability);

  const inputStyle = {
    padding: "7px 10px",
    background: "rgba(0,0,0,0.03)",
    border: "0.5px solid rgba(0,0,0,0.15)",
    borderRadius: 6,
    fontSize: 13,
    color: "inherit",
    fontFamily: "'DM Sans', sans-serif",
    outline: "none",
  };

  return (
    <div>
      <SectionCard
        title={`Menu  ·  ${available.length} available, ${unavailable.length} off`}
        action={<span style={{ fontSize: 11, fontFamily: "'IBM Plex Mono', monospace", color: "#aaa" }}>{items.length} items total</span>}
      >
        {loading ? <Spinner /> : error ? <ErrorMsg message={error} /> : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr" }}>
              {items.map((item, idx) => (
                <div key={item.item_id} style={{
                  display: "flex", alignItems: "center", gap: 12,
                  padding: "12px 16px",
                  borderBottom: idx < items.length - 2 ? "0.5px solid rgba(0,0,0,0.06)" : "none",
                  borderRight: idx % 2 === 0 ? "0.5px solid rgba(0,0,0,0.06)" : "none",
                  opacity: item.availability ? 1 : 0.5,
                  transition: "opacity 0.2s",
                }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {item.item_name}
                    </div>
                    <div style={{ fontSize: 11, color: "#aaa", fontFamily: "'IBM Plex Mono', monospace", marginTop: 2 }}>
                      {String(item.available_from).slice(0, 5)} – {String(item.available_until).slice(0, 5)}
                    </div>
                  </div>
                  <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, color: "#888", whiteSpace: "nowrap" }}>
                    ₹{Number(item.price).toFixed(0)}
                  </div>
                  <ToggleSwitch
                    on={item.availability}
                    onChange={() => saving !== item.item_id && handleToggle(item)}
                  />
                  <button
                    onClick={() => handleDelete(item.item_id)}
                    style={{ background: "none", border: "none", cursor: "pointer", color: "#ddd", fontSize: 16, lineHeight: 1, padding: "0 2px" }}
                    title="Delete"
                  >×</button>
                </div>
              ))}
            </div>

            {/* Add new item row */}
            <div style={{ padding: "12px 16px", borderTop: "0.5px solid rgba(0,0,0,0.08)", display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-start" }}>
              <input style={{ ...inputStyle, flex: 2, minWidth: 120 }} placeholder="Item name" value={form.item_name} onChange={e => setForm(f => ({ ...f, item_name: e.target.value }))} />
              <input style={{ ...inputStyle, width: 80 }} placeholder="₹ Price" value={form.price} onChange={e => setForm(f => ({ ...f, price: e.target.value }))} type="number" min="0" />
              <input style={{ ...inputStyle, width: 90 }} placeholder="From HH:MM" value={form.available_from} onChange={e => setForm(f => ({ ...f, available_from: e.target.value }))} />
              <input style={{ ...inputStyle, width: 90 }} placeholder="Until HH:MM" value={form.available_until} onChange={e => setForm(f => ({ ...f, available_until: e.target.value }))} />
              <button
                onClick={handleAdd}
                disabled={adding}
                style={{
                  padding: "7px 16px", background: "transparent",
                  border: "0.5px solid rgba(0,0,0,0.2)", borderRadius: 6,
                  fontSize: 12, cursor: adding ? "not-allowed" : "pointer",
                  fontFamily: "'IBM Plex Mono', monospace", color: "inherit", opacity: adding ? 0.5 : 1,
                }}
              >{adding ? "adding..." : "+ Add item"}</button>
              {formError && <div style={{ width: "100%", fontSize: 12, color: "#A32D2D" }}>{formError}</div>}
            </div>
          </>
        )}
      </SectionCard>
    </div>
  );
}