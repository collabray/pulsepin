import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";
import { api } from "../api/client.js";
import { useGeolocation } from "../state/useGeolocation.js";

// Leaflet's default marker icons reference image paths that don't survive
// a bundler; rebuild them from the unpkg CDN so markers render correctly
// without shipping the icon files ourselves.
const patientIcon = new L.Icon({
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
  iconSize: [25, 41],
  iconAnchor: [12, 41],
});

const ambulanceIcon = new L.DivIcon({
  html: `<div style="font-size:28px; transform: translate(-50%, -50%);">🚑</div>`,
  className: "",
  iconSize: [0, 0],
});

const hospitalIcon = new L.DivIcon({
  html: `<div style="font-size:26px; transform: translate(-50%, -50%);">🏥</div>`,
  className: "",
  iconSize: [0, 0],
});

function haversineKm(a, b) {
  if (!a || !b) return null;
  const R = 6371;
  const dLat = ((b.latitude - a.latitude) * Math.PI) / 180;
  const dLon = ((b.longitude - a.longitude) * Math.PI) / 180;
  const lat1 = (a.latitude * Math.PI) / 180;
  const lat2 = (b.latitude * Math.PI) / 180;
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

function AutoFitBounds({ points }) {
  const map = useMap();
  useEffect(() => {
    const valid = points.filter(Boolean);
    if (valid.length < 2) return;
    const bounds = L.latLngBounds(valid.map((p) => [p.latitude, p.longitude]));
    map.fitBounds(bounds, { padding: [40, 40] });
  }, [points, map]);
  return null;
}

const STATUS_LABELS = {
  pending_scoring: "Processing your request…",
  pending_reverse_call: "A dispatcher will call you shortly to confirm details.",
  pending_dispatcher_review: "A dispatcher is reviewing your request.",
  flagged_held: "Your request needs additional verification. A dispatcher will contact you.",
  confirmed_dispatched: "Ambulance dispatched — on the way.",
  rejected: "This request was not confirmed as an emergency.",
  cancelled: "This request was cancelled.",
  completed: "This request has been completed.",
};

export default function DispatchTracking() {
  const { dispatchId } = useParams();
  const [tracking, setTracking] = useState(null);
  const [error, setError] = useState("");
  const wsRef = useRef(null);
  const geo = useGeolocation();

  // Initial snapshot
  useEffect(() => {
    api.getTracking(dispatchId).then(setTracking).catch((e) => setError(e.message));
  }, [dispatchId]);

  // Live updates over WebSocket — same real-time pattern a rideshare app
  // uses to move the driver marker without polling.
  useEffect(() => {
    const token = api.authToken();
    const ws = new WebSocket(`${api.wsUrl()}/ws/patient/${dispatchId}?token=${token}`);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === "tracking_update") {
        setTracking((prev) => {
          if (!prev) return prev;
          if (msg.data.event === "ambulance_location") {
            return {
              ...prev,
              ambulance_location: {
                latitude: msg.data.lat,
                longitude: msg.data.lon,
                recorded_at: msg.data.recorded_at,
                heading_degrees: msg.data.heading_degrees,
                speed_kmh: msg.data.speed_kmh,
              },
            };
          }
          if (msg.data.event === "ambulance_assigned") {
            return {
              ...prev,
              assigned_ambulance_call_sign: msg.data.call_sign,
              estimated_arrival_at: msg.data.estimated_arrival_at,
            };
          }
          return prev;
        });
      }
    };
    ws.onerror = () => setError("Live tracking connection lost. Retrying…");

    return () => ws.close();
  }, [dispatchId]);

  // Stream the patient's own live location back to the server while a
  // dispatch is active — used for the GPS Telemetry Matching abuse signal
  // and to help a crew relocate a patient who has moved.
  useEffect(() => {
    geo.startWatching((pos) => {
      api
        .submitPatientGpsPing(dispatchId, {
          latitude: pos.latitude,
          longitude: pos.longitude,
          accuracy_meters: pos.accuracy,
          heading_degrees: pos.heading,
          speed_kmh: pos.speed != null ? pos.speed * 3.6 : null,
        })
        .catch(() => {});
    });
    return () => geo.stopWatching();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dispatchId]);

  if (error && !tracking) {
    return (
      <div className="screen">
        <div className="error-text">{error}</div>
      </div>
    );
  }
  if (!tracking) {
    return (
      <div className="screen" style={{ justifyContent: "center" }}>
        <p className="dim">Loading…</p>
      </div>
    );
  }

  const center = tracking.ambulance_location || tracking.patient_location || { latitude: -1.286389, longitude: 36.817223 };
  const etaKm = haversineKm(tracking.ambulance_location, tracking.patient_location);

  return (
    <div className="screen">
      <h1>Your ambulance</h1>
      <p className="subtitle">{STATUS_LABELS[tracking.status] || tracking.status}</p>

      <div className="map-wrap">
        <MapContainer center={[center.latitude, center.longitude]} zoom={13} style={{ height: "100%", width: "100%" }}>
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {tracking.patient_location && (
            <Marker
              position={[tracking.patient_location.latitude, tracking.patient_location.longitude]}
              icon={patientIcon}
            >
              <Popup>You</Popup>
            </Marker>
          )}
          {tracking.ambulance_location && (
            <Marker
              position={[tracking.ambulance_location.latitude, tracking.ambulance_location.longitude]}
              icon={ambulanceIcon}
            >
              <Popup>{tracking.assigned_ambulance_call_sign || "Ambulance"}</Popup>
            </Marker>
          )}
          {tracking.hospital_location && (
            <Marker
              position={[tracking.hospital_location.latitude, tracking.hospital_location.longitude]}
              icon={hospitalIcon}
            >
              <Popup>{tracking.hospital_name}</Popup>
            </Marker>
          )}
          {tracking.ambulance_location && tracking.patient_location && (
            <Polyline
              positions={[
                [tracking.ambulance_location.latitude, tracking.ambulance_location.longitude],
                [tracking.patient_location.latitude, tracking.patient_location.longitude],
              ]}
              pathOptions={{ color: "#3b82f6", dashArray: "6 6" }}
            />
          )}
          <AutoFitBounds points={[tracking.patient_location, tracking.ambulance_location, tracking.hospital_location]} />
        </MapContainer>
      </div>

      <div className="card">
        {tracking.assigned_ambulance_call_sign ? (
          <>
            <h2>{tracking.assigned_ambulance_call_sign}</h2>
            {etaKm != null && <p className="dim">~{etaKm.toFixed(1)} km away (straight-line)</p>}
            {tracking.ambulance_location?.speed_kmh != null && (
              <p className="dim">Current speed: {Math.round(tracking.ambulance_location.speed_kmh)} km/h</p>
            )}
          </>
        ) : (
          <p className="dim">Waiting for an ambulance to be assigned…</p>
        )}
      </div>

      <p className="dim">
        Distance shown is a straight-line estimate, not a routed ETA — turn-by-turn routing requires a
        road-network routing service, which is a documented next step (see LIMITATIONS.md).
      </p>
    </div>
  );
}
