import { useState } from "react";
import { api } from "./api.js";

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/;

export default function Auth({ onSignedIn, notice }) {
  const [mode, setMode] = useState("login"); // login | register
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const register = mode === "register";

  const switchMode = (m) => {
    setMode(m);
    setError("");
  };

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    if (register && !name.trim()) return setError("Enter your name.");
    if (!EMAIL.test(email.trim())) return setError("Enter a valid email address.");
    if (register && password.length < 8) return setError("Use at least 8 characters for your password.");
    if (!password) return setError("Enter your password.");
    setBusy(true);
    try {
      const user = register ? await api.register(name.trim(), email.trim(), password) : await api.login(email.trim(), password);
      onSignedIn(user);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <div className="auth-wrap">
      <div className="auth-card">
        <span className="brand dark">LabLens</span>
        <h1>{register ? "Create your account" : "Welcome back"}</h1>
        <p className="muted">
          {register
            ? "Keep every lab report and trend in one private place."
            : "Sign in to see your reports and trends."}
        </p>

        <div className="seg" role="tablist" aria-label="Sign in or create account">
          <button type="button" role="tab" aria-selected={!register} className={!register ? "on" : ""} onClick={() => switchMode("login")}>
            Sign in
          </button>
          <button type="button" role="tab" aria-selected={register} className={register ? "on" : ""} onClick={() => switchMode("register")}>
            Create account
          </button>
        </div>

        {notice && !error && <p className="verify" role="status">{notice}</p>}

        <form onSubmit={submit} noValidate>
          {register && (
            <label className="field">
              <span>Your name</span>
              <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" maxLength={60} />
            </label>
          )}
          <label className="field">
            <span>Email</span>
            <input
              type="email" inputMode="email" value={email} onChange={(e) => setEmail(e.target.value)}
              autoComplete="email" autoCapitalize="none" autoCorrect="off" spellCheck={false}
            />
          </label>
          <label className="field">
            <span>Password</span>
            <div className="pw">
              <input
                type={show ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)}
                autoComplete={register ? "new-password" : "current-password"} maxLength={128}
              />
              <button type="button" className="ghost sm" onClick={() => setShow((s) => !s)} aria-pressed={show}>
                {show ? "Hide" : "Show"}
              </button>
            </div>
            {register && <small className="muted">At least 8 characters.</small>}
          </label>

          {error && <p className="error" role="alert">{error}</p>}

          <button className="primary block" disabled={busy}>
            {busy ? "Please wait…" : register ? "Create account" : "Sign in"}
          </button>
        </form>

        <p className="note">
          {register ? "Already registered? " : "New here? "}
          <button type="button" className="link" onClick={() => switchMode(register ? "login" : "register")}>
            {register ? "Sign in" : "Create an account"}
          </button>
        </p>
      </div>
    </div>
  );
}
