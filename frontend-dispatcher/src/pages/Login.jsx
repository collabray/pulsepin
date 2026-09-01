import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client.js";

export default function Login() {
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [step, setStep] = useState("phone"); // phone -> code -> mfa
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
      const result = await api.verifyOtp(phone, code);
      if (result.token_type === "mfa_pending") {
        setStep("mfa");
      } else {
        navigate("/");
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function verifyMfa(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await api.verifyMfa(mfaCode);
      navigate("/");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="screen" style={{ justifyContent: "center" }}>
      <h1>PulsePin Dispatcher</h1>
      <p className="subtitle">Authorized hospital staff only. MFA required.</p>

      {step === "phone" && (
        <form onSubmit={requestCode} className="card">
          <h2>Phone number</h2>
          <input type="tel" placeholder="+254712345678" value={phone} onChange={(e) => setPhone(e.target.value)} required />
          {error && <div className="error-text">{error}</div>}
          <button className="primary" type="submit" disabled={loading}>
            {loading ? "Sending..." : "Send code"}
          </button>
        </form>
      )}

      {step === "code" && (
        <form onSubmit={verifyCode} className="card">
          <h2>Enter the code sent to {phone}</h2>
          <input inputMode="numeric" placeholder="6-digit code" value={code} onChange={(e) => setCode(e.target.value)} required />
          {error && <div className="error-text">{error}</div>}
          <button className="primary" type="submit" disabled={loading}>
            {loading ? "Verifying..." : "Continue"}
          </button>
        </form>
      )}

      {step === "mfa" && (
        <form onSubmit={verifyMfa} className="card">
          <h2>Enter your authenticator app code</h2>
          <input inputMode="numeric" placeholder="TOTP code" value={mfaCode} onChange={(e) => setMfaCode(e.target.value)} required />
          {error && <div className="error-text">{error}</div>}
          <button className="primary" type="submit" disabled={loading}>
            {loading ? "Verifying..." : "Sign in"}
          </button>
        </form>
      )}
    </div>
  );
}
