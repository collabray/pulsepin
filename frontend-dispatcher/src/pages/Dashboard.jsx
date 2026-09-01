import { useEffect, useRef, useState } from "react";
import { MapContainer, Marker, TileLayer, Popup } from "react-leaflet";
import L from "leaflet";
import { api } from "../api/client.js";

const patientIcon = new L.Icon({
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
  iconSize: [25, 41],
  iconAnchor: [12, 41],
});

function decodeJwtPayload(token) {
  try {
    const [, payload] = token.split(".");
    return JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
  } catch {
    return {};
  }
}

const TIER_COLORS = { high: "#22c55e", medium: "#f59e0b", low: "#ef4444" };

export default function Dashboard() {
  const [requests, setRequests] = useState([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState("");
  const wsRef = useRef(null);

  const token = api.authToken();
  const claims = token ? decodeJwtPayload(token) : {};
  const hospitalId = claims.hospital_id;

  useEffect(() => {
    if (!hospitalId) {
      setError("Your account isn't linked to a hospital. Contact a platform admin.");
      return;
    }
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/dispatcher/${hospitalId}?token=${token}`);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === "new_dispatch") {
        setRequests((prev) => [{ ...msg.data }, ...prev.filter((r) => r.id !== msg.data.id)]);
      }
      if (msg.type === "location_update") {
        setRequests((prev) =>
          prev.map((r) =>
            r.id === msg.data.dispatch_id ? { ...r, location: { lat: msg.data.lat, lon: msg.data.lon } } : r
          )
        );
      }
    };

    return () => ws.close();
  }, [hospitalId, token]);

  async function handleReverseCall(dispatchId, confirmed) {
    try {
      await api.submitReverseCallResult(dispatchId, { confirmed_emergency: confirmed });
      setRequests((prev) => prev.map((r) => (r.id === dispatchId ? { ...r, status: confirmed ? "confirmed" : "rejected" } : r)));
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleOutcome(dispatchId, confirmedReal) {
    try {
      await api.recordOutcome(dispatchId, { confirmed_real: confirmedReal });
      setRequests((prev) => prev.filter((r) => r.id !== dispatchId));
    } catch (e) {
      setError(e.message);
    }
  }

  const activeWithLocation = requests.filter((r) => r.location);
  const mapCenter = activeWithLocation[0]?.location
    ? [activeWithLocation[0].location.lat, activeWithLocation[0].location.lon]
    : [-1.286389, 36.817223];

  return (
    <div style={{ display: "flex", height: "100vh" }}>
      <div style={{ width: 420, overflowY: "auto", borderRight: "1px solid var(--color-border)", padding: 16 }}>
        <h1>Live requests</h1>
        <p className="dim">{connected ? "🟢 Connected" : "🔴 Reconnecting…"}</p>
        {error && <div className="error-text">{error}</div>}

        {requests.length === 0 && <p className="dim">No active requests.</p>}

        {requests.map((r) => (
          <div className="card" key={r.id}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <strong>{r.patient_phone}</strong>
              <span
                className="badge"
                style={{ background: `${TIER_COLORS[r.confidence_tier]}22`, color: TIER_COLORS[r.confidence_tier] }}
              >
                {r.confidence_tier} · {(r.confidence_score * 100).toFixed(0)}%
              </span>
            </div>
            <p className="dim">Status: {r.status}</p>
            {r.anomaly_flags?.length > 0 && (
              <p className="error-text">⚠ {r.anomaly_flags.join("; ")}</p>
            )}
            {r.status === "pending_reverse_call" && (
              <div className="question-row">
                <button className="danger" onClick={() => handleReverseCall(r.id, false)}>
                  Not an emergency
                </button>
                <button className="primary" onClick={() => handleReverseCall(r.id, true)}>
                  Confirmed — dispatch
                </button>
              </div>
            )}
            {(r.status === "confirmed" || r.status === "pending_dispatcher_review") && (
              <button
                className="ghost"
                style={{ width: "100%", marginTop: 8 }}
                onClick={() => handleOutcome(r.id, true)}
              >
                Mark resolved (real emergency)
              </button>
            )}
          </div>
        ))}
      </div>

      <div style={{ flex: 1 }}>
        <MapContainer center={mapCenter} zoom={12} style={{ height: "100%", width: "100%" }}>
          <TileLayer
            attribution='&copy; OpenStreetMap contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {activeWithLocation.map((r) => (
            <Marker key={r.id} position={[r.location.lat, r.location.lon]} icon={patientIcon}>
              <Popup>
                {r.patient_phone} — {r.confidence_tier}
              </Popup>
            </Marker>
          ))}
        </MapContainer>
      </div>
    </div>
  );
}
