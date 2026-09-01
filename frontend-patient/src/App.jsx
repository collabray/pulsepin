import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { api } from "./api/client.js";
import { getPreference } from "./state/preferences.js";
import Disclaimer from "./pages/Disclaimer.jsx";
import Login from "./pages/Login.jsx";
import Triage from "./pages/Triage.jsx";
import Hospitals from "./pages/Hospitals.jsx";
import DispatchTracking from "./pages/DispatchTracking.jsx";

function RequireAuth({ children }) {
  if (!api.isAuthenticated()) return <Navigate to="/login" replace />;
  return children;
}

function RequireDisclaimer({ children }) {
  const [checked, setChecked] = useState(false);
  const [accepted, setAccepted] = useState(false);

  useEffect(() => {
    getPreference("pulsepin_disclaimer_accepted_at").then((v) => {
      setAccepted(!!v);
      setChecked(true);
    });
  }, []);

  if (!checked) return null;
  if (!accepted) return <Navigate to="/disclaimer" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/disclaimer" element={<Disclaimer onAccept={() => {}} />} />
      <Route
        path="/login"
        element={
          <RequireDisclaimer>
            <Login />
          </RequireDisclaimer>
        }
      />
      <Route
        path="/"
        element={
          <RequireDisclaimer>
            <RequireAuth>
              <Triage />
            </RequireAuth>
          </RequireDisclaimer>
        }
      />
      <Route
        path="/hospitals"
        element={
          <RequireDisclaimer>
            <RequireAuth>
              <Hospitals />
            </RequireAuth>
          </RequireDisclaimer>
        }
      />
      <Route
        path="/dispatch/:dispatchId"
        element={
          <RequireDisclaimer>
            <RequireAuth>
              <DispatchTracking />
            </RequireAuth>
          </RequireDisclaimer>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
