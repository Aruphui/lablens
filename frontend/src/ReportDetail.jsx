import { IconBack } from "./Icons.jsx";
import RangeStrip from "./RangeStrip.jsx";
import { STATUS, fmtDate, fmtRange, fmtVal, isFlagged } from "./lib.js";

const DOCTOR = {
  routine: "Mention at your next routine visit",
  soon: "See a doctor in the next few weeks",
  urgent: "See a doctor promptly",
};

export default function ReportDetail({ report, onDelete, onBack }) {
  const { summary, results } = report;
  const ex = summary.extraction;
  const flagged = results.filter((r) => isFlagged(r.status));
  const byName = Object.fromEntries((summary.findings || []).map((f) => [f.test, f]));
  const hasCritical = flagged.some((r) => r.status === "CRITICAL");

  return (
    <article className="detail">
      <button className="back-btn" onClick={onBack}><IconBack /> All reports</button>
      <header className="detail-head">
        <div>
          <h2>{fmtDate(report.report_date)}</h2>
          <p className="muted fname">{report.filename}</p>
        </div>
        <button
          className="ghost danger"
          onClick={() => window.confirm("Delete this report and its values?") && onDelete(report.id)}
        >
          Delete report
        </button>
      </header>

      {hasCritical && (
        <p className="alert" role="alert">
          One or more values are in a range that can need urgent attention. Contact a doctor or your local
          emergency service if you feel unwell.
        </p>
      )}

      {summary.overview && <p className="overview">{summary.overview}</p>}

      {ex && (ex.mode === "rules" || ex.dropped?.length > 0 || ex.refs_unverified?.length > 0) && (
        <div className="verify" role="note">
          {ex.mode === "rules" && (
            <p>The AI reader was unavailable, so these values were read by pattern matching. Compare them with your original report.</p>
          )}
          {ex.dropped?.length > 0 && (
            <p>Left out because they could not be confirmed in the document: {ex.dropped.join(", ")}.</p>
          )}
          {ex.refs_unverified?.length > 0 && (
            <p>Normal range could not be confirmed in the document for: {ex.refs_unverified.join(", ")}.</p>
          )}
        </div>
      )}

      {flagged.length > 0 && (
        <section>
          <h3>Needs attention ({flagged.length})</h3>
          <ul className="findings">
            {flagged.map((r) => {
              const f = byName[r.test_name];
              return (
                <li key={r.test_name} style={{ "--c": STATUS[r.status].color }}>
                  <div className="f-top">
                    <strong>{r.test_name}</strong>
                    <span className="pill" style={{ background: STATUS[r.status].color }}>
                      {STATUS[r.status].label}
                    </span>
                    <span className="f-val">
                      {fmtVal(r)} {r.unit} <span className="muted">(normal {fmtRange(r.ref_low, r.ref_high)})</span>
                    </span>
                  </div>
                  {f?.meaning && <p>{f.meaning}</p>}
                  {f?.steps?.length > 0 && (
                    <ul className="steps">
                      {f.steps.map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                  )}
                  {f && <p className="doctor">{DOCTOR[f.see_doctor]}</p>}
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <section>
        <h3>All results ({results.length})</h3>
        <div className="results" role="table">
          {results.map((r) => (
            <div className="res-row" role="row" key={r.test_name}>
              <span className="res-name" role="cell">{r.test_name}</span>
              <span className="res-val" role="cell">
                <strong>{fmtVal(r)}</strong> <span className="muted">{r.unit}</span>
              </span>
              <span className="res-strip" role="cell"><RangeStrip r={r} /></span>
              <span className="res-status" role="cell" style={{ color: STATUS[r.status].color }}>
                {STATUS[r.status].label}
              </span>
            </div>
          ))}
        </div>
      </section>

      <p className="note">
        LabLens is for information only and is not medical advice. AI can misread a report, so check the values
        above against your original and talk to a doctor before acting on anything here.
      </p>
    </article>
  );
}
