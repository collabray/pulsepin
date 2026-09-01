const API_BASE = "/api/v1";

function getTokens() {
  return {
    access: localStorage.getItem("pulsepin_dispatcher_access_token"),
    refresh: localStorage.getItem("pulsepin_dispatcher_refresh_token"),
    preAuth: localStorage.getItem("pulsepin_dispatcher_pre_auth_token"),
  };
}

function setTokens(data) {
  if (data.token_type === "mfa_pending") {
    localStorage.setItem("pulsepin_dispatcher_pre_auth_token", data.access_token);
    return;
  }
  localStorage.setItem("pulsepin_dispatcher_access_token", data.access_token);
  localStorage.setItem("pulsepin_dispatcher_refresh_token", data.refresh_token);
  localStorage.removeItem("pulsepin_dispatcher_pre_auth_token");
}

function clearTokens() {
  localStorage.removeItem("pulsepin_dispatcher_access_token");
  localStorage.removeItem("pulsepin_dispatcher_refresh_token");
  localStorage.removeItem("pulsepin_dispatcher_pre_auth_token");
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
  requestOtp: (phone_number) =>
    request("/auth/otp/request", { method: "POST", body: { phone_number }, auth: false }),

  verifyOtp: async (phone_number, code) => {
    const data = await request("/auth/otp/verify", {
      method: "POST",
      body: { phone_number, code },
      auth: false,
    });
    setTokens(data);
    return data;
  },

  verifyMfa: async (code) => {
    const { preAuth } = getTokens();
    const data = await request(
      `/auth/mfa/verify?pre_auth_token=${encodeURIComponent(preAuth)}&code=${encodeURIComponent(code)}`,
      { method: "POST", auth: false }
    );
    setTokens(data);
    return data;
  },

  isAuthenticated: () => !!getTokens().access,
  isMfaPending: () => !!getTokens().preAuth && !getTokens().access,
  logout: clearTokens,

  listAuditLog: (actionPrefix) =>
    request(`/admin/audit-log${actionPrefix ? `?action_prefix=${actionPrefix}` : ""}`),

  submitReverseCallResult: (dispatchId, payload) =>
    request(`/dispatch/${dispatchId}/reverse-call-result`, { method: "POST", body: payload }),
  recordOutcome: (dispatchId, payload) =>
    request(`/dispatch/${dispatchId}/outcome`, { method: "POST", body: payload }),
  assignAmbulance: (dispatchId, payload) =>
    request(`/dispatch/${dispatchId}/assign-ambulance`, { method: "POST", body: payload }),
  submitAmbulanceLocation: (dispatchId, payload) =>
    request(`/dispatch/${dispatchId}/ambulance-location`, { method: "POST", body: payload }),

  toggleCapability: (hospitalId, payload) =>
    request(`/hospitals/${hospitalId}/capabilities`, { method: "PATCH", body: payload }),
  updateIcuBeds: (hospitalId, payload) =>
    request(`/hospitals/${hospitalId}/icu-beds`, { method: "PATCH", body: payload }),

  authToken: () => getTokens().access,
};
