import { Capacitor } from "@capacitor/core";
import { Device } from "@capacitor/device";

// On web, a relative path works because the app is served from the same
// origin as the API (via the nginx/Traefik proxy in this repo's compose
// setup). On a native iOS/Android build there IS no "same origin" — the
// app loads from an app-local scheme (capacitor://localhost), so a
// relative path silently resolves to nothing and every request 404s.
// VITE_API_BASE_URL must be set to your real, deployed HTTPS backend URL
// at build time for native builds (see .env.production.example and
// PUBLISHING.md "Point the app at a real backend").
const API_BASE = Capacitor.isNativePlatform()
  ? `${import.meta.env.VITE_API_BASE_URL || ""}/api/v1`
  : "/api/v1";

if (Capacitor.isNativePlatform() && !import.meta.env.VITE_API_BASE_URL) {
  // Fail loudly in dev rather than shipping a build that silently can't
  // reach any backend — this is exactly the kind of bug that only shows
  // up after TestFlight/Play internal-testing install, wasting a review
  // cycle.
  console.error(
    "VITE_API_BASE_URL is not set. Native builds need an absolute backend URL " +
      "— see .env.production.example and PUBLISHING.md."
  );
}

let cachedFingerprint = null;

async function resolveDeviceFingerprint() {
  if (cachedFingerprint) return cachedFingerprint;

  if (Capacitor.isNativePlatform()) {
    // Capacitor's Device.getId() returns a platform-appropriate stable
    // identifier (identifierForVendor on iOS, a generated install ID on
    // Android — neither is the IMEI, which no modern mobile OS exposes to
    // apps for privacy reasons regardless of platform; see LIMITATIONS.md).
    // This is meaningfully more tamper-resistant than a web localStorage
    // value, since it isn't cleared by clearing site data.
    try {
      const { identifier } = await Device.getId();
      cachedFingerprint = identifier;
      return cachedFingerprint;
    } catch {
      // fall through to the localStorage fallback below
    }
  }

  const key = "pulsepin_device_fingerprint";
  let fp = localStorage.getItem(key);
  if (!fp) {
    fp = crypto.randomUUID();
    localStorage.setItem(key, fp);
  }
  cachedFingerprint = fp;
  return fp;
}

function getTokens() {
  return {
    access: localStorage.getItem("pulsepin_access_token"),
    refresh: localStorage.getItem("pulsepin_refresh_token"),
  };
}

function setTokens({ access_token, refresh_token }) {
  if (access_token) localStorage.setItem("pulsepin_access_token", access_token);
  if (refresh_token) localStorage.setItem("pulsepin_refresh_token", refresh_token);
}

function clearTokens() {
  localStorage.removeItem("pulsepin_access_token");
  localStorage.removeItem("pulsepin_refresh_token");
}

async function request(path, { method = "GET", body, auth = true, headers = {} } = {}) {
  const finalHeaders = { "Content-Type": "application/json", ...headers };
  if (auth) {
    const { access } = getTokens();
    if (access) finalHeaders["Authorization"] = `Bearer ${access}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: finalHeaders,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401 && auth) {
    clearTokens();
    window.location.href = "/login";
    throw new Error("Session expired.");
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }

  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  // --- Auth ---
  requestOtp: (phone_number) =>
    request("/auth/otp/request", { method: "POST", body: { phone_number }, auth: false }),

  verifyOtp: async (phone_number, code) => {
    const device_fingerprint = await resolveDeviceFingerprint();
    const data = await request("/auth/otp/verify", {
      method: "POST",
      body: { phone_number, code, device_fingerprint },
      auth: false,
    });
    setTokens(data);
    return data;
  },

  logout: () => clearTokens(),
  isAuthenticated: () => !!getTokens().access,

  // --- Triage ---
  startTriage: (initial_symptoms = {}) =>
    request("/triage/sessions", { method: "POST", body: { initial_symptoms } }),
  answerTriage: (sessionId, symptom, value) =>
    request(`/triage/sessions/${sessionId}/answer`, { method: "POST", body: { symptom, value } }),
  getTriageSession: (sessionId) => request(`/triage/sessions/${sessionId}`),

  // --- Hospitals ---
  nearbyFacilities: (latitude, longitude, condition, radius_km = 50) =>
    request("/hospitals/nearby", { method: "POST", body: { latitude, longitude, condition, radius_km } }),

  // --- Dispatch ---
  acceptDispatchTerms: () => request("/users/me/accept-dispatch-terms", { method: "PATCH" }),
  triggerDispatch: (payload) => request("/dispatch", { method: "POST", body: payload }),
  submitReverseCallResult: (dispatchId, payload) =>
    request(`/dispatch/${dispatchId}/reverse-call-result`, { method: "POST", body: payload }),
  submitPatientGpsPing: (dispatchId, payload) =>
    request(`/dispatch/${dispatchId}/gps-ping`, { method: "POST", body: payload }),
  getTracking: (dispatchId) => request(`/dispatch/${dispatchId}/tracking`),

  deviceFingerprint: resolveDeviceFingerprint,
  authToken: () => getTokens().access,

  wsUrl: () => {
    if (Capacitor.isNativePlatform()) {
      const base = import.meta.env.VITE_API_BASE_URL || "";
      return base.replace(/^http/, "ws");
    }
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}`;
  },
};
