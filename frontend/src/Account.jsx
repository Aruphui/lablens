import { useState } from "react";
import { api } from "./api.js";
import { fmtDate } from "./lib.js";

export default function Account({ user, reportCount, onSignOut, onDeleted }) {
  const [confirming, setConfirming] = useState(false);
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const remove = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.deleteAccount(pw);
      onDeleted();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <section className="account">
      <h1>Account</h1>

      <div className="card profile">
        <span className="avatar" aria-hidden="true">{user.name.slice(0, 1).toUpperCase()}</span>
        <div>
          <strong>{user.name}</strong>
          <div className="muted">{user.email}</div>
          <div className="muted small">
            {reportCount} {reportCount === 1 ? "report" : "reports"} · member since {fmtDate(user.created_at.slice(0, 10))}
          </div>
        </div>
      </div>

      <button className="ghost block" onClick={onSignOut}>Sign out</button>

      <h3>Privacy</h3>
      <p className="muted">
        Only the test values read from your reports are stored. The report file itself is discarded after reading.
        Your data is visible only to your account.
      </p>

      <h3>Delete account</h3>
      {!confirming ? (
        <>
          <p className="muted">Permanently removes your account, every report and all trend history.</p>
          <button className="ghost danger" onClick={() => setConfirming(true)}>Delete my account…</button>
        </>
      ) : (
        <form onSubmit={remove} className="card danger-zone">
          <p>This cannot be undone. Enter your password to confirm.</p>
          <label className="field">
            <span>Password</span>
            <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" />
          </label>
          {error && <p className="error" role="alert">{error}</p>}
          <div className="btn-row">
            <button type="button" className="ghost" onClick={() => { setConfirming(false); setPw(""); setError(""); }}>Cancel</button>
            <button className="primary danger-fill" disabled={!pw || busy}>{busy ? "Deleting…" : "Delete everything"}</button>
          </div>
        </form>
      )}

      <p className="note">
        LabLens is for information only and is not medical advice. Talk to a doctor before acting on anything here.
      </p>
    </section>
  );
}
