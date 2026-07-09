import { useEffect } from "react";
import type { ReactNode } from "react";
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { setUnauthorizedHandler } from "./api/client";
import { useSession } from "./auth/session";
import { Layout } from "./components/Layout";
import { DqView } from "./views/DqView";
import { LineageView } from "./views/LineageView";
import { LoginView } from "./views/LoginView";
import { MetricsView } from "./views/MetricsView";

function RequireAuth({ children }: { children: ReactNode }) {
  const session = useSession();
  const location = useLocation();
  if (!session) {
    return (
      <Navigate to="/login" replace state={{ from: location.pathname }} />
    );
  }
  return children;
}

/**
 * Routes only (router-agnostic so tests can mount it in a MemoryRouter).
 * The app shell registers the 401 handler: any authenticated call that comes
 * back 401 clears the session and lands the user on /login.
 */
export function AppRoutes() {
  const navigate = useNavigate();

  useEffect(() => {
    setUnauthorizedHandler(() => navigate("/login"));
    return () => setUnauthorizedHandler(null);
  }, [navigate]);

  return (
    <Routes>
      <Route path="/login" element={<LoginView />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Navigate to="/metrics" replace />} />
        <Route path="/metrics" element={<MetricsView />} />
        <Route path="/metrics/:id/lineage" element={<LineageView />} />
        <Route path="/dq" element={<DqView />} />
      </Route>
    </Routes>
  );
}
