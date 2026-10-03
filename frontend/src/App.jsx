import { useCallback, useEffect, useState } from "react";
import Account from "./Account.jsx";
import Auth from "./Auth.jsx";
import { IconAccount, IconReports, IconTrends, IconUpload } from "./Icons.jsx";
import ReportDetail from "./ReportDetail.jsx";
import Trends from "./Trends.jsx";
import UploadPanel from "./UploadPanel.jsx";
import { api, hasToken, setUnauthorizedHandler } from "./api.js";
import { fmtDate } from "./lib.js";

const TABS = [
  ["upload", "New report", IconUpload],
  ["reports", "Reports", IconReports],
  ["trends", "Trends", IconTrends],
  ["account", "Account", IconAccount],
];

export default function App() {
  const [user, setUser] = useState(undefined); // undefined = checking, null = signed out
  const [notice, setNotice] = useState("");

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser(null);
      setNotice("Your session ended. Please sign in again.");
    });
    if (!hasToken()) return setUser(null);
    api.me().then(setUser).catch(() => setUser(null));
  }, []);

  if (user === undefined) return <p className="boot muted" role="status">Loading…</p>;
  if (user === null) return <Auth notice={notice} onSignedIn={(u) => { setNotice(""); setUser(u); }} />;
  return (
    <Shell
      user={user}
      onSignOut={() => { api.logout(); setNotice(""); setUser(null); }}
    />
  );
}

function Shell({ user, onSignOut }) {
  const [tab, setTab] = useState("upload");
  const [reports, setReports] = useState([]);
  const [selected, setSelected] = useState(null);
  const [version, setVersion] = useState(0);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setReports(await api.listReports());
      setVersion((v) => v + 1);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [tab, selected?.id]);

  const open = async (id) => {
    setError("");
    try {
      setSelected(await api.getReport(id));
    } catch (e) {
      setError(e.message);
    }
  };

  const go = (key) => {
    setError("");
    // on phones the Reports tab always opens the list; on wider screens the open report stays selected
    if (key === "reports" && (key === tab || window.matchMedia("(max-width: 800px)").matches)) setSelected(null);
    setTab(key);
  };

  const onUploaded = async (report) => {
    await refresh();
    setSelected(report);
    setTab("reports");
  };

  const onDelete = async (id) => {
    try {
      await api.deleteReport(id);
      setSelected(null);
      refresh();
    } catch (e) {
      setError(e.message);
    }
  };

  // test names changed (merge): reload the list and the open report so old names disappear
  const onTestsChanged = async () => {
    await refresh();
    if (selected) {
      try {
        setSelected(await api.getReport(selected.id));
      } catch {
        setSelected(null);
      }
    }
  };

  return (
    <>
      <header className="top">
        <div className="top-in">
          <span className="brand">LabLens</span>
          <nav aria-label="Main" className="nav">
            {TABS.map(([key, label, Icon]) => (
              <button key={key} className={tab === key ? "tab on" : "tab"} onClick={() => go(key)} aria-current={tab === key ? "page" : undefined}>
                <Icon />
                <span>{label}</span>
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main>
        {error && <p className="error" role="alert">{error}</p>}

        {tab === "upload" && <UploadPanel onDone={onUploaded} />}

        {tab === "reports" && (
          <div className={selected ? "split has-sel" : "split"}>
            <aside aria-label="Your reports" className="list-pane">
              <h1 className="mobile-title">Reports</h1>
              {reports.length === 0 ? (
                <div className="empty-mini">
                  <p className="muted">No reports yet. Upload one to get started.</p>
                  <button className="primary" onClick={() => go("upload")}>Upload a report</button>
                </div>
              ) : (
                <ul className="rlist">
                  {reports.map((r) => (
                    <li key={r.id}>
                      <button className={selected?.id === r.id ? "ritem on" : "ritem"} onClick={() => open(r.id)}>
                        <strong>{fmtDate(r.report_date)}</strong>
                        <span className="muted">{r.filename}</span>
                        <span className={r.flagged ? "flag has" : "flag"}>
                          {r.flagged ? `${r.flagged} of ${r.total} need attention` : `All ${r.total} normal`}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </aside>
            <div className="detail-pane">
              {selected ? (
                <ReportDetail report={selected} onDelete={onDelete} onBack={() => setSelected(null)} />
              ) : (
                <p className="muted pad hide-mobile">Select a report to see the full review.</p>
              )}
            </div>
          </div>
        )}

        {tab === "trends" && <Trends refreshKey={version} onChanged={onTestsChanged} goUpload={() => go("upload")} />}

        {tab === "account" && (
          <Account user={user} reportCount={reports.length} onSignOut={onSignOut} onDeleted={onSignOut} />
        )}
      </main>
    </>
  );
}
