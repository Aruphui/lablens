import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import TidyTests from "./TidyTests.jsx";
import { api } from "./api.js";
import { STATUS, fmtDate, fmtNum, fmtRange, useMedia } from "./lib.js";

const DAY = 86400000;

function Dot({ cx, cy, payload }) {
  if (cx == null || cy == null) return null;
  return <circle cx={cx} cy={cy} r={5} fill={STATUS[payload.status].color} stroke="#fff" strokeWidth={2} />;
}

export default function Trends({ refreshKey, onChanged, goUpload }) {
  const [tests, setTests] = useState([]);
  const [test, setTest] = useState("");
  const [points, setPoints] = useState([]);
  const [sugg, setSugg] = useState([]);
  const [error, setError] = useState("");
  const [tidy, setTidy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const phone = useMedia("(max-width: 600px)");

  const loadMeta = useCallback(async () => {
    try {
      const [t, s] = await Promise.all([api.tests(), api.suggestions()]);
      setTests(t);
      setSugg(s);
      setError("");
      setTest((cur) => (t.some((x) => x.test_name === cur) ? cur : (t.find((x) => x.test_name === "Glucose (Fasting)") || t[0])?.test_name || ""));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    loadMeta();
  }, [loadMeta, refreshKey]);

  useEffect(() => {
    if (!test) return setPoints([]);
    api.trend(test).then(setPoints).catch((e) => setError(e.message));
  }, [test, refreshKey]);

  // after a merge: refresh everything and follow the test to its new name
  const afterChange = async (out) => {
    if (out?.into) setTest(out.into);
    await loadMeta();
    await onChanged?.();
  };

  const data = useMemo(() => points.map((p) => ({ ...p, t: new Date(p.date + "T00:00:00").getTime() })), [points]);
  const last = data[data.length - 1];
  const first = data[0];

  if (!loaded) return <p className="muted pad" role="status">Loading…</p>;
  if (error && !tests.length) return <p className="error" role="alert">{error}</p>;
  if (!tests.length) {
    return (
      <section className="empty">
        <h2>No history yet</h2>
        <p className="muted">Upload a report and each test will appear here as a line over time.</p>
        <button className="primary" onClick={goUpload}>Upload a report</button>
      </section>
    );
  }

  const lo = last?.ref_low;
  const hi = last?.ref_high;
  const values = data.map((d) => d.value);
  const yMin = Math.min(...values, lo ?? Infinity);
  const yMax = Math.max(...values, hi ?? -Infinity);
  const pad = (yMax - yMin || yMax || 1) * 0.15;
  // round the axis to tidy numbers so ticks read 5, 10, 15 instead of 13.02
  const rawStep = (yMax + pad - Math.max(0, yMin - pad)) / 4 || 1;
  const mag = 10 ** Math.floor(Math.log10(rawStep));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((x) => x >= rawStep) || 10 * mag;
  const axisLo = Math.max(0, Math.floor((yMin - pad) / step) * step);
  const axisHi = Math.ceil((yMax + pad) / step) * step;
  const ticks = Array.from({ length: Math.round((axisHi - axisLo) / step) + 1 }, (_, i) => +(axisLo + i * step).toFixed(6));
  const changePct = first && last && first.value && data.length > 1 ? ((last.value - first.value) / first.value) * 100 : null;

  return (
    <section className="trends">
      <h1 className="mobile-title">Trends</h1>

      {sugg.length > 0 && (
        <button className="banner" onClick={() => setTidy(true)}>
          <span>
            <strong>{sugg.length} possible {sugg.length === 1 ? "duplicate" : "duplicates"}</strong>
            <small>The same test may appear under two names. Review to combine them.</small>
          </span>
          <span aria-hidden="true">›</span>
        </button>
      )}

      <div className="trend-head">
        <label className="field grow">
          <span>Test</span>
          <select value={test} onChange={(e) => setTest(e.target.value)}>
            {tests.map((t) => (
              <option key={t.test_name} value={t.test_name}>
                {t.test_name} ({t.n})
              </option>
            ))}
          </select>
        </label>
        <button className="ghost" onClick={() => setTidy(true)}>
          Tidy names{sugg.length > 0 && <span className="count">{sugg.length}</span>}
        </button>
      </div>

      {error && <p className="error" role="alert">{error}</p>}

      {last && (
        <dl className="stats">
          <div><dt>Latest</dt><dd style={{ color: STATUS[last.status].color }}>{fmtNum(last.value)} <small>{last.unit}</small></dd></div>
          <div><dt>Normal range</dt><dd>{fmtRange(lo, hi)}</dd></div>
          <div><dt>Since first</dt><dd>{changePct == null ? "—" : `${changePct > 0 ? "+" : ""}${changePct.toFixed(1)}%`}</dd></div>
        </dl>
      )}

      <div className="chart" aria-label={`${test} over time`}>
        <ResponsiveContainer width="100%" height={phone ? 260 : 360}>
          <LineChart data={data} margin={{ top: 12, right: phone ? 12 : 24, bottom: 8, left: 0 }}>
            <CartesianGrid stroke="var(--line)" vertical={false} />
            {(lo != null || hi != null) && (
              <ReferenceArea y1={lo ?? 0} y2={hi ?? yMax + pad} fill="var(--ok)" fillOpacity={0.12} ifOverflow="extendDomain" />
            )}
            {lo != null && hi == null && <ReferenceLine y={lo} stroke="var(--ok)" strokeDasharray="4 4" />}
            <XAxis
              dataKey="t" type="number" scale="time"
              domain={[(min) => min - 15 * DAY, (max) => max + 15 * DAY]}
              tickFormatter={(t) => new Date(t).toLocaleDateString("en-IN", { month: "short", year: "2-digit" })}
              stroke="var(--muted)" tickMargin={8} tick={{ fontSize: phone ? 12 : 14 }} tickCount={phone ? 4 : 6} minTickGap={24}
            />
            <YAxis
              domain={[axisLo, axisHi]} ticks={ticks} tickFormatter={(v) => fmtNum(v)}
              stroke="var(--muted)" width={phone ? 40 : 48} tick={{ fontSize: phone ? 12 : 14 }}
            />
            <Tooltip
              labelFormatter={(t) => fmtDate(new Date(t).toISOString().slice(0, 10))}
              formatter={(v, _n, item) => [`${fmtNum(v)} ${item.payload.unit}  (${STATUS[item.payload.status].label})`, test]}
            />
            <Line type="monotone" dataKey="value" stroke="var(--accent)" strokeWidth={2} dot={<Dot />} activeDot={{ r: 7 }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="note">The shaded band is the normal range printed on your most recent report. Ranges can differ between labs.</p>

      {tidy && (
        <TidyTests tests={tests} suggestions={sugg} onClose={() => setTidy(false)} onChanged={afterChange} />
      )}
    </section>
  );
}
