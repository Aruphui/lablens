import { STATUS } from "./lib.js";

// A small bar showing the reference range as a band and the measured value as a marker.
export default function RangeStrip({ r }) {
  const { value, ref_low: lo, ref_high: hi, status } = r;
  if (lo == null && hi == null) return <span className="muted">no range given</span>;

  const low = lo ?? Math.min(0, value);
  const high = hi ?? Math.max(low * 2, value * 1.2, low + 1);
  const span = high - low || 1;
  let min = low - span * 0.6;
  let max = high + span * 0.6;
  if (low >= 0) min = Math.max(0, min);
  min = Math.min(min, value - span * 0.1);
  max = Math.max(max, value + span * 0.1);
  const pct = (v) => ((v - min) / (max - min)) * 100;

  const bandStart = lo == null ? 0 : pct(lo);
  const bandEnd = hi == null ? 100 : pct(hi);

  return (
    <div className="strip" role="img" aria-label={`${r.test_name}: ${value} (${STATUS[status].label})`}>
      <div className="band" style={{ left: `${bandStart}%`, width: `${bandEnd - bandStart}%` }} />
      <div className="marker" style={{ left: `${pct(value)}%`, background: STATUS[status].color }} />
    </div>
  );
}
