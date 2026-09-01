import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client.js";

export default function Login() {
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [step, setStep] = useState("phone"); // "phone" | "code"
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  async function requestCode(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await api.requestOtp(phone);
      setStep("code");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function verifyCode(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await api.verifyOtp(phone, code);
      navigate("/");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="screen" style={{ justifyContent: "center" }}>
      <h1>PulsePin</h1>
      <p className="subtitle">Symptom triage, matched to the nearest hospital that can actually treat you.</p>

      {step === "phone" ? (
        <form onSubmit={requestCode} className="card">
          <h2>Enter your phone number</h2>
          <input
            type="tel"
            placeholder="+254712345678"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            required
          />
          {error && <div className="error-text">{error}</div>}
          <button className="primary" type="submit" disabled={loading}>
            {loading ? "Sending..." : "Send code"}
          </button>
        </form>
      ) : (
        <form onSubmit={verifyCode} className="card">
          <h2>Enter the code sent to {phone}</h2>
          <input
            type="text"
            inputMode="numeric"
            placeholder="6-digit code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
          />
          {error && <div className="error-text">{error}</div>}
          <button className="primary" type="submit" disabled={loading}>
            {loading ? "Verifying..." : "Verify"}
          </button>
        </form>
      )}
    </div>
  );
}
