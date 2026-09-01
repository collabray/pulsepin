import { Navigate, Route, Routes } from "react-router-dom";
import { api } from "./api/client.js";
import Login from "./pages/Login.jsx";
import Dashboard from "./pages/Dashboard.jsx";

function RequireAuth({ children }) {
  if (!api.isAuthenticated()) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <Dashboard />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
