import { useRef, useState } from "react";
import { api } from "./api.js";

export default function UploadPanel({ onDone }) {
  const input = useRef(null);
  const camera = useRef(null);
  const [file, setFile] = useState(null);
  const [date, setDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [over, setOver] = useState(false);

  const pick = (f) => {
    if (f) {
      setFile(f);
      setError("");
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const report = await api.upload(file, date);
      setFile(null);
      setDate("");
      onDone(report);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="upload">
      <h1>Understand your lab report</h1>
      <p className="lede">
        Upload a blood test or other lab report. You'll get a plain-language read of anything outside the normal
        range, what to do next, and a running history of each test.
      </p>

      <form onSubmit={submit}>
        <div
          className={"drop" + (over ? " over" : "") + (file ? " has-file" : "")}
          onClick={() => input.current?.click()}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setOver(false);
            pick(e.dataTransfer.files?.[0]);
          }}
          role="button"
          tabIndex={0}
        >
          <input
            ref={input}
            type="file"
            accept=".pdf,.png,.jpg,.jpeg,.webp"
            hidden
            onChange={(e) => pick(e.target.files?.[0])}
          />
          {file ? (
            <>
              <strong className="fname">{file.name}</strong>
              <span className="muted">{(file.size / 1024).toFixed(0)} KB. Tap to choose a different file.</span>
            </>
          ) : (
            <>
              <strong>Tap to choose a report<span className="hide-mobile">, or drop it here</span></strong>
              <span className="muted">PDF, PNG, JPG or WEBP, up to 10 MB</span>
            </>
          )}
        </div>

        <input ref={camera} type="file" accept="image/*" capture="environment" hidden onChange={(e) => pick(e.target.files?.[0])} />
        <button type="button" className="ghost block camera-btn" onClick={() => camera.current?.click()}>
          Take a photo of a printed report
        </button>

        <div className="row">
          <label className="field">
            <span>Test date (optional)</span>
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} max={new Date().toISOString().slice(0, 10)} />
            <small className="muted">Leave blank to read it from the report.</small>
          </label>
          <button className="primary grow-mobile" disabled={!file || busy}>
            {busy ? "Reading your report…" : "Analyze report"}
          </button>
        </div>

        {busy && <p className="muted" aria-live="polite">This can take up to a minute on the free model.</p>}
        {error && <p className="error" role="alert">{error}</p>}
      </form>

      <p className="note">
        Only the extracted test values are saved. The file itself is discarded after reading.
      </p>
    </section>
  );
}
