import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api.js";

// Sheet where the user confirms which test names are really the same test.
// The AI only suggests; nothing is renamed until a button here is pressed.
export default function TidyTests({ tests, suggestions, onClose, onChanged }) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const [picked, setPicked] = useState([]);
  const [into, setInto] = useState("");
  const closeRef = useRef(null);
  const closeFn = useRef(onClose);
  closeFn.current = onClose;

  const unitOf = useMemo(() => Object.fromEntries(tests.map((t) => [t.test_name, t.unit])), [tests]);
  const countOf = useMemo(() => Object.fromEntries(tests.map((t) => [t.test_name, t.n])), [tests]);

  useEffect(() => {
    const prev = document.activeElement;
    closeRef.current?.focus();
    document.body.classList.add("lock");
    const onKey = (e) => e.key === "Escape" && closeFn.current();
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.classList.remove("lock");
      window.removeEventListener("keydown", onKey);
      prev?.focus?.();
    };
  }, []);

  const run = async (label, fn, okMsg) => {
    setBusy(label);
    setError("");
    setDone("");
    try {
      const out = await fn();
      if (okMsg) setDone(typeof okMsg === "function" ? okMsg(out) : okMsg);
      await onChanged(out);
      return true;
    } catch (e) {
      setError(e.message);
      return false;
    } finally {
      setBusy("");
    }
  };

  const toggle = (name) => {
    const next = picked.includes(name) ? picked.filter((n) => n !== name) : [...picked, name];
    setPicked(next);
    setInto(next.length ? next.slice().sort((a, b) => (countOf[b] || 0) - (countOf[a] || 0))[0] : "");
  };

  const mixedUnits = new Set(picked.map((n) => (unitOf[n] || "").toLowerCase().replace(/\s/g, "")).filter(Boolean)).size > 1;

  const confirmUnits = () =>
    window.confirm("These tests use different units, so their values may not be comparable. Merge anyway?");

  return (
    <div className="sheet-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="sheet" role="dialog" aria-modal="true" aria-labelledby="tidy-title">
        <header className="sheet-head">
          <h2 id="tidy-title">Tidy test names</h2>
          <button ref={closeRef} className="ghost sm" onClick={onClose}>Close</button>
        </header>

        <div className="sheet-body">
          <p className="muted">
            The same test can be printed under different names (for example <em>TSH</em> and <em>Thyroid Stimulating Hormone</em>).
            Merging puts them on one trend line. Your original values are not changed, and LabLens will remember
            your choice for future reports.
          </p>

          {error && <p className="error" role="alert">{error}</p>}
          {done && <p className="okmsg" role="status">{done}</p>}

          <div className="sec-head">
            <h3>Suggested by AI {suggestions.length > 0 && <span className="count">{suggestions.length}</span>}</h3>
            <button
              className="ghost sm"
              disabled={!!busy}
              onClick={() => run("scan", () => api.scanSuggestions(), (s) => (s.length ? "" : "No duplicates found."))}
            >
              {busy === "scan" ? "Checking…" : "Check again"}
            </button>
          </div>

          {suggestions.length === 0 && <p className="muted">No suggestions right now.</p>}

          <ul className="sugg">
            {suggestions.map((s) => (
              <Suggestion
                key={s.id}
                s={s}
                unitOf={unitOf}
                busy={busy === "s" + s.id}
                disabled={!!busy}
                onMerge={(name) =>
                  (!s.unit_mismatch || confirmUnits()) &&
                  run("s" + s.id, () => api.acceptSuggestion(s.id, name), `Merged into “${name}”.`)
                }
                onReject={() => run("s" + s.id, () => api.dismissSuggestion(s.id), "Kept separate.")}
              />
            ))}
          </ul>

          <h3>Merge by hand</h3>
          <p className="muted small">Tick two or more tests that are the same, then choose the name to keep.</p>
          <ul className="pick">
            {tests.map((t) => (
              <li key={t.test_name}>
                <label>
                  <input type="checkbox" checked={picked.includes(t.test_name)} onChange={() => toggle(t.test_name)} />
                  <span className="pick-name">{t.test_name}</span>
                  <span className="muted small">{t.unit || "no unit"} · {t.n}×</span>
                </label>
              </li>
            ))}
          </ul>
        </div>

        {picked.length >= 2 && (
          <footer className="sheet-foot">
            <label className="field">
              <span>Keep this name</span>
              <input value={into} onChange={(e) => setInto(e.target.value)} list="tidy-names" maxLength={80} />
              <datalist id="tidy-names">{picked.map((n) => <option key={n} value={n} />)}</datalist>
            </label>
            {mixedUnits && <p className="warn small">Different units selected. Only merge if they measure the same thing in the same unit.</p>}
            <button
              className="primary"
              disabled={!!busy || !into.trim()}
              onClick={() =>
                (!mixedUnits || confirmUnits()) &&
                run("manual", () => api.mergeTests(picked, into.trim()), `Merged ${picked.length} tests into “${into.trim()}”.`).then((ok) => {
                  if (ok) {
                    setPicked([]);
                    setInto("");
                  }
                })
              }
            >
              {busy === "manual" ? "Merging…" : `Merge ${picked.length} tests`}
            </button>
          </footer>
        )}
      </div>
    </div>
  );
}

function Suggestion({ s, unitOf, busy, disabled, onMerge, onReject }) {
  const [name, setName] = useState(s.into);
  return (
    <li className="sg">
      <div className="chips">
        {s.names.map((n) => (
          <span className="chip" key={n}>{n}<small>{unitOf[n] || "no unit"}</small></span>
        ))}
      </div>
      {s.reason && <p className="muted small">{s.reason}</p>}
      {s.unit_mismatch && <p className="warn small">These were reported in different units. Check before merging.</p>}
      <label className="field">
        <span>Keep this name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} list={`sg-${s.id}`} maxLength={80} />
        <datalist id={`sg-${s.id}`}>{s.names.map((n) => <option key={n} value={n} />)}</datalist>
      </label>
      <div className="btn-row">
        <button className="ghost" disabled={disabled} onClick={onReject}>Not the same</button>
        <button className="primary" disabled={disabled || !name.trim()} onClick={() => onMerge(name.trim())}>
          {busy ? "Working…" : "Merge"}
        </button>
      </div>
    </li>
  );
}
