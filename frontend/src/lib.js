import { useEffect, useState } from "react";

export const STATUS = {
  NORMAL: { label: "Normal", color: "var(--ok)" },
  HIGH: { label: "High", color: "var(--bad)" },
  LOW: { label: "Low", color: "var(--warn)" },
  CRITICAL: { label: "Critical", color: "var(--crit)" },
  UNKNOWN: { label: "No range", color: "var(--muted)" },
};

export const isFlagged = (s) => s === "HIGH" || s === "LOW" || s === "CRITICAL";

export const fmtDate = (iso, opts = { day: "numeric", month: "short", year: "numeric" }) =>
  new Date(iso + "T00:00:00").toLocaleDateString("en-IN", opts);

export const fmtNum = (n) => (n == null ? "" : Number.isInteger(n) ? String(n) : String(+n.toFixed(2)));

export const fmtRange = (lo, hi) =>
  lo != null && hi != null ? `${fmtNum(lo)} – ${fmtNum(hi)}` : hi != null ? `< ${fmtNum(hi)}` : lo != null ? `> ${fmtNum(lo)}` : "—";

export const fmtVal = (r) => `${r.qualifier || ""}${fmtNum(r.value)}`;

// true while the viewport matches a media query (used to resize the chart on phones)
export function useMedia(query) {
  const get = () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(query).matches : false);
  const [match, setMatch] = useState(get);
  useEffect(() => {
    const m = window.matchMedia(query);
    const on = () => setMatch(m.matches);
    on();
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, [query]);
  return match;
}
