import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client.js";
import { useGeolocation } from "../state/useGeolocation.js";

async function geocodeAddress(query) {
  // OpenStreetMap's free Nominatim geocoder — no API key required. This is
  // the fallback path for when the person denies (or their device lacks)
  // GPS permission; it is deliberately a *manual, explicit* fallback, not
  // a silent guess, because a wrong silent guess about someone's location
  // in a medical-emergency app would be actively dangerous. Nominatim's
  // usage policy caps free public-instance traffic — production deployments
  // at scale should run a self-hosted Nominatim instance or a paid
  // geocoding provider instead. See LIMITATIONS.md.
  const url = `https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(query)}`;
  const res = await fetch(url, { headers: { "Accept-Language": "en" } });
  if (!res.ok) throw new Error("Address lookup failed.");
  const results = await res.json();
  if (!results.length) throw new Error("No matching address found.");
  return { latitude: parseFloat(results[0].lat), longitude: parseFloat(results[0].lon) };
}

export default function Hospitals() {
  const { state } = useLocation();
  const navigate = useNavigate();
  const condition = state?.condition || "Common Cold";
  const urgency = state?.urgency || "clinic_visit";

  const geo = useGeolocation();
  const [coords, setCoords] = useState(null);
  const [manualAddress, setManualAddress] = useState("");
  const [facilities, setFacilities] = useState(null);
  const [error, setError] = useState("");
  const [loadingFacilities, setLoadingFacilities] = useState(false);
  const [dispatching, setDispatching] = useState(false);

  useEffect(() => {
    geo.requestOnce();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (geo.status === "granted" && geo.position) {
      setCoords({ latitude: geo.position.latitude, longitude: geo.position.longitude });
    }
  }, [geo.status, geo.position]);

  useEffect(() => {
    if (!coords) return;
    setLoadingFacilities(true);
    setError("");
    api
      .nearbyFacilities(coords.latitude, coords.longitude, condition)
      .then(setFacilities)
      .catch((e) => setError(e.message))
      .finally(() => setLoadingFacilities(false));
  }, [coords, condition]);

  async function useManualAddress(e) {
    e.preventDefault();
    setError("");
    try {
      const result = await geocodeAddress(manualAddress);
      setCoords(result);
    } catch (err) {
      setError(err.message);
    }
  }

  async function requestAmbulance(hospitalId) {
    if (!coords) return;
    setDispatching(true);
    setError("");
    try {
      const dispatch = await api.triggerDispatch({
        latitude: coords.latitude,
        longitude: coords.longitude,
        target_hospital_id: hospitalId,
        used_silent_override: false,
        device_fingerprint: await api.deviceFingerprint(),
        gps_accuracy_meters: geo.position?.accuracy ?? null,
        device_gps_latitude: geo.position?.latitude ?? null,
        device_gps_longitude: geo.position?.longitude ?? null,
      });
      navigate(`/dispatch/${dispatch.id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setDispatching(false);
    }
  }

  return (
    <div className="screen">
      <h1>Nearby care</h1>
      <p className="subtitle">
        For: <strong>{condition}</strong> ·{" "}
        <span className={`badge ${urgency}`}>{urgency.replace("_", " ")}</span>
      </p>

      {(geo.status === "idle" || geo.status === "requesting") && (
        <div className="card">
          <p>PulsePin needs your location to find the nearest hospital that can actually treat you.</p>
          <button className="primary" onClick={geo.requestOnce} disabled={geo.status === "requesting"}>
            {geo.status === "requesting" ? "Waiting for permission…" : "Share my location"}
          </button>
        </div>
      )}

      {(geo.status === "denied" || geo.status === "unavailable") && !coords && (
        <div className="card">
          <p className="error-text">
            {geo.status === "denied"
              ? "Location permission was denied."
              : "Location isn't available on this device."}
          </p>
          <p className="dim">You can still search by typing your address instead:</p>
          <form onSubmit={useManualAddress}>
            <input
              placeholder="e.g. Kenyatta Avenue, Nairobi"
              value={manualAddress}
              onChange={(e) => setManualAddress(e.target.value)}
              required
            />
            <button className="primary" type="submit">
              Find nearby care
            </button>
          </form>
          <button className="ghost" style={{ marginTop: 8, width: "100%" }} onClick={geo.requestOnce}>
            Try location permission again
          </button>
        </div>
      )}

      {coords && (
        <div className="card">
          <p className="dim">
            Searching near {coords.latitude.toFixed(4)}, {coords.longitude.toFixed(4)}
            {geo.position?.accuracy ? ` (±${Math.round(geo.position.accuracy)}m)` : ""}
          </p>
        </div>
      )}

      {error && <div className="error-text">{error}</div>}
      {loadingFacilities && <p className="dim">Searching nearby facilities…</p>}

      {facilities?.map((f) => (
        <div className="card" key={f.hospital_id}>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <h2>{f.name}</h2>
            {f.is_verified_partner && <span className="badge self_care">Verified</span>}
          </div>
          <p className="dim">{f.address}</p>
          <p className="dim">{f.distance_km.toFixed(1)} km away</p>
          {f.capability_data_is_stale && (
            <p className="error-text">⚠ Capability data may be outdated — call ahead if possible.</p>
          )}
          <p className="dim">
            Matches {f.capability_match_count} of {f.matched_capabilities.length + f.missing_capabilities.length}{" "}
            required capabilities.
          </p>
          {urgency === "emergency" && (
            <button
              className="danger"
              style={{ width: "100%", marginTop: 8 }}
              onClick={() => requestAmbulance(f.hospital_id)}
              disabled={dispatching}
            >
              {dispatching ? "Requesting…" : "Request ambulance to this hospital"}
            </button>
          )}
        </div>
      ))}

      {facilities?.length === 0 && !loadingFacilities && (
        <p className="dim">No matching facilities found within range. Try widening your search radius.</p>
      )}
    </div>
  );
}
