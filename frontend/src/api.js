const TOKEN_KEY = "lablens_token";
const LEGACY_KEY = "lablens_uid"; // random id used before accounts existed

const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  del: (k) => { try { localStorage.removeItem(k); } catch { /* ignore */ } },
};

let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };
export const hasToken = () => !!store.get(TOKEN_KEY);
export const clearToken = () => store.del(TOKEN_KEY);

async function req(path, opts = {}) {
  const token = store.get(TOKEN_KEY);
  const res = await fetch("/api" + path, {
    ...opts,
    headers: { ...(opts.headers || {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!res.ok) {
    let msg;
    try {
      const body = await res.json();
      msg = body.detail;
      if (Array.isArray(msg)) msg = msg.map((m) => m.msg).join(". "); // FastAPI validation errors
    } catch {
      /* ignore */
    }
    // a stale or rejected token anywhere except the sign-in form means "sign in again"
    if (res.status === 401 && token && !path.startsWith("/auth/login") && !path.startsWith("/auth/delete")) {
      clearToken();
      onUnauthorized();
    }
    throw new Error(typeof msg === "string" ? msg : `Request failed (${res.status})`);
  }
  return res.json();
}

const post = (path, body) =>
  req(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });

async function startSession(path, body) {
  const legacy = store.get(LEGACY_KEY);
  const out = await post(path, { ...body, legacy_uid: legacy || undefined });
  store.set(TOKEN_KEY, out.token);
  if (legacy) store.del(LEGACY_KEY); // its reports now belong to the account
  return out.user;
}

export const api = {
  register: (name, email, password) => startSession("/auth/register", { name, email, password }),
  login: (email, password) => startSession("/auth/login", { email, password }),
  me: () => req("/auth/me"),
  deleteAccount: (password) => post("/auth/delete", { password }),
  logout: () => clearToken(),

  listReports: () => req("/reports"),
  getReport: (id) => req(`/reports/${id}`),
  deleteReport: (id) => req(`/reports/${id}`, { method: "DELETE" }),
  upload: (file, date) => {
    const f = new FormData();
    f.append("file", file);
    if (date) f.append("report_date", date);
    return req("/reports", { method: "POST", body: f });
  },

  tests: () => req("/tests"),
  trend: (test) => req(`/trends?test=${encodeURIComponent(test)}`),

  suggestions: () => req("/tests/suggestions"),
  scanSuggestions: () => post("/tests/suggestions/scan"),
  acceptSuggestion: (id, into) => post(`/tests/suggestions/${id}/accept`, { into }),
  dismissSuggestion: (id) => post(`/tests/suggestions/${id}/dismiss`),
  mergeTests: (names, into) => post("/tests/merge", { names, into }),
};
