import axios from 'axios';

// A published build has to name its API. Falling back to 127.0.0.1 would point every visitor at
// their own laptop, so the default only applies to `npm run dev` and a production bundle without
// VITE_API_BASE talks to the origin it was served from.
const RAW_BASE = import.meta.env.VITE_API_BASE
  || (import.meta.env.DEV ? 'http://127.0.0.1:8000' : '');
export const API_BASE = RAW_BASE.replace(/\/+$/, '');

// The session lives in sessionStorage, not localStorage: a cold-chain console is left open on a
// shared ward terminal, and a token that outlives the tab is somebody else's admin session.
const KEY = 'coldchain.session';

export function readSession() {
  try {
    return JSON.parse(sessionStorage.getItem(KEY));
  } catch {
    return null;
  }
}

export function writeSession(session) {
  if (session) sessionStorage.setItem(KEY, JSON.stringify(session));
  else sessionStorage.removeItem(KEY);
}

export const http = axios.create({ baseURL: API_BASE });

http.interceptors.request.use((cfg) => {
  const session = readSession();
  if (session?.token) cfg.headers.Authorization = `Bearer ${session.token}`;
  return cfg;
});

// Set by AuthProvider; a token the server no longer accepts must end the session rather than
// leave a page polling on it and showing an error forever.
let onExpired = () => {};
export function registerExpiredHandler(fn) {
  onExpired = fn;
}

http.interceptors.response.use(
  (r) => r,
  (err) => {
    const url = err.config?.url || '';
    // a wrong password is a 401 too, and must not be treated as an expired session
    if (err.response?.status === 401 && readSession() && !url.includes('/api/auth/login')) {
      writeSession(null);
      onExpired();
    }
    return Promise.reject(err);
  },
);

/** The server's own reason, in the operator's language.
 *
 * FastAPI sends a string for HTTPException and an array for pydantic validation errors, and the
 * 403 text ("pharmacist cannot do this") is the answer to "why is this button greyed out".
 */
export function errorMessage(e) {
  const detail = e.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const first = detail[0];
    return `${(first?.loc || []).slice(1).join('.') || 'request'}: ${first?.msg || 'invalid value'}`;
  }
  if (e.response) return `Rejected by the server (HTTP ${e.response.status})`;
  // naming the host is what separates a stale VITE_API_BASE from a backend that is merely asleep, and
  // the second half names the only fix: this value is baked into the bundle at build time, so editing
  // it on the hosting panel does nothing until the site is rebuilt.
  return `Cannot reach the API at ${API_BASE || window.location.origin}. `
    + 'If that is the wrong address, set VITE_API_BASE and rebuild.';
}

/** True when the failure was a permission or session answer from the server, not an outage. */
export function statusOf(e) {
  return e.response?.status;
}
