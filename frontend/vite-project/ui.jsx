export function Badge({ type = "gray", children }) {
  const styles = {
    green:  { background: "#EAF3DE", color: "#3B6D11" },
    amber:  { background: "#FAEEDA", color: "#854F0B" },
    red:    { background: "#FCEBEB", color: "#A32D2D" },
    blue:   { background: "#E6F1FB", color: "#185FA5" },
    gray:   { background: "#F1EFE8", color: "#5F5E5A" },
  };
  return (
    <span style={{
      ...styles[type],
      display: "inline-block",
      padding: "2px 10px",
      borderRadius: 20,
      fontSize: 11,
      fontFamily: "'IBM Plex Mono', monospace",
      fontWeight: 500,
      textTransform: "capitalize",
      whiteSpace: "nowrap",
    }}>{children}</span>
  );
}

export function MetricCard({ label, value, sub, valueColor }) {
  return (
    <div style={{
      background: "var(--color-bg-secondary, #f5f5f3)",
      borderRadius: 8,
      padding: "14px 16px",
    }}>
      <div style={{ fontSize: 11, color: "#888", fontFamily: "'IBM Plex Mono', monospace", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 6 }}>
        {label}
      </div>
      <div style={{ fontSize: 26, fontWeight: 500, fontFamily: "'IBM Plex Mono', monospace", color: valueColor || "inherit" }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 11, color: "#aaa", marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

export function Table({ columns, rows, emptyMessage = "No data" }) {
  if (!rows || rows.length === 0) {
    return (
      <div style={{ padding: 32, textAlign: "center", fontSize: 13, color: "#aaa", fontFamily: "'IBM Plex Mono', monospace" }}>
        {emptyMessage}
      </div>
    );
  }
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
      <thead>
        <tr>
          {columns.map(c => (
            <th key={c.key} style={{
              textAlign: "left", padding: "10px 16px",
              fontSize: 11, fontFamily: "'IBM Plex Mono', monospace",
              letterSpacing: "0.06em", color: "#999", fontWeight: 400,
              borderBottom: "0.5px solid rgba(0,0,0,0.08)", textTransform: "uppercase",
            }}>{c.label}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr key={i} style={{ cursor: "default" }}
            onMouseEnter={e => e.currentTarget.style.background = "rgba(0,0,0,0.02)"}
            onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
            {columns.map(c => (
              <td key={c.key} style={{
                padding: "11px 16px",
                borderBottom: i < rows.length - 1 ? "0.5px solid rgba(0,0,0,0.06)" : "none",
                fontFamily: c.mono ? "'IBM Plex Mono', monospace" : "inherit",
                color: c.muted ? "#999" : "inherit",
              }}>
                {c.render ? c.render(row[c.key], row) : row[c.key]}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function SectionCard({ title, action, children }) {
  return (
    <div style={{
      background: "#fff",
      border: "0.5px solid rgba(0,0,0,0.1)",
      borderRadius: 12,
      overflow: "hidden",
      marginBottom: 16,
    }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "12px 16px",
        borderBottom: "0.5px solid rgba(0,0,0,0.08)",
      }}>
        <span style={{ fontSize: 12, fontWeight: 500, fontFamily: "'IBM Plex Mono', monospace", textTransform: "uppercase", letterSpacing: "0.07em", color: "#888" }}>
          {title}
        </span>
        {action}
      </div>
      {children}
    </div>
  );
}

export function Spinner() {
  return (
    <div style={{ padding: 32, textAlign: "center", fontSize: 12, fontFamily: "'IBM Plex Mono', monospace", color: "#bbb" }}>
      loading...
    </div>
  );
}

export function ErrorMsg({ message }) {
  return (
    <div style={{ padding: 16, color: "#A32D2D", fontSize: 13, fontFamily: "'IBM Plex Mono', monospace", background: "#FCEBEB", borderRadius: 8, margin: 16 }}>
      Error: {message}
    </div>
  );
}