import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { setPreference } from "../state/preferences.js";

// Apple App Review Guideline 1.4.1 ("Physical Harm — Apps that provide
// services in highly regulated fields... such as... emergency services...
// must not provide inaccurate data") and Guideline 1.4.3 (apps
// facilitating emergency response must clearly communicate they are not
// a replacement for contacting local emergency services directly) are
// both manually checked by a human reviewer for any app that looks like
// it touches emergency dispatch. This screen exists specifically to pass
// that check honestly — it reflects what's actually true about this
// build (see LIMITATIONS.md: live dispatch is off by default pending
// legal review), not a canned disclaimer bolted on to get past review.
//
// PUBLISHING.md documents where else this same message needs to appear
// (App Store Connect review notes, Play Store listing description).

const PRIVACY_POLICY_URL = import.meta.env.VITE_PRIVACY_POLICY_URL || "/privacy-policy.html";
const TERMS_URL = import.meta.env.VITE_TERMS_URL || "/terms.html";

export default function Disclaimer({ onAccept }) {
  const [acknowledged, setAcknowledged] = useState(false);
  const navigate = useNavigate();

  async function handleContinue() {
    await setPreference("pulsepin_disclaimer_accepted_at", new Date().toISOString());
    onAccept();
    navigate("/login");
  }

  return (
    <div className="screen">
      <h1>Before you continue</h1>

      <div className="card">
        <h2>This is not a replacement for calling emergency services</h2>
        <p>
          PulsePin is a symptom-triage and hospital-routing tool. If you or someone near you is in
          immediate danger, <strong>call your local emergency number directly first.</strong> Do not
          rely on this app instead of, or before, doing that.
        </p>
      </div>

      <div className="card">
        <h2>What this app does</h2>
        <p className="dim">
          Asks a few questions about your symptoms and suggests possible conditions and an urgency
          level using a statistical model — not a doctor, and not a certified diagnostic device.
        </p>
        <p className="dim">
          Helps you find a nearby hospital that has the specific equipment and staff your condition
          may need, using your device's location (only after you grant permission).
        </p>
        <p className="dim">
          If you request an ambulance through the app, a human dispatcher reviews and confirms the
          request — it is not silently auto-approved.
        </p>
      </div>

      <div className="card">
        <h2>What this app collects</h2>
        <p className="dim">
          Your phone number, precise location (only while you're using location features or during
          an active dispatch), the symptoms you enter, and a device identifier used to detect abuse
          of the emergency-request system. Full details:{" "}
          <a href={PRIVACY_POLICY_URL} target="_blank" rel="noreferrer">
            Privacy Policy
          </a>{" "}
          &middot;{" "}
          <a href={TERMS_URL} target="_blank" rel="noreferrer">
            Terms of Service
          </a>
          .
        </p>
      </div>

      <label style={{ display: "flex", gap: 10, alignItems: "flex-start", margin: "12px 0" }}>
        <input
          type="checkbox"
          style={{ width: "auto", marginTop: 4 }}
          checked={acknowledged}
          onChange={(e) => setAcknowledged(e.target.checked)}
        />
        <span>
          I understand this app does not replace emergency services, and I agree to the Privacy
          Policy and Terms of Service.
        </span>
      </label>

      <button className="primary" disabled={!acknowledged} onClick={handleContinue}>
        Continue
      </button>
    </div>
  );
}
