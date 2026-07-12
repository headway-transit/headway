import { useEffect } from "react";
import {
  Navigate,
  Outlet,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { setUnauthorizedHandler } from "./api/client";
import { useSession } from "./auth/session";
import { Layout } from "./components/Layout";
import { BrandingView } from "./views/BrandingView";
import { CertifyView } from "./views/CertifyView";
import { DashboardView } from "./views/DashboardView";
import { DqView } from "./views/DqView";
import { LineageView } from "./views/LineageView";
import { LoginView } from "./views/LoginView";
import { MetricsView } from "./views/MetricsView";
import { MonthlyReportView } from "./views/MonthlyReportView";
import { PublicDataView } from "./views/PublicDataView";
import { SafetyView } from "./views/SafetyView";

function RequireAuth() {
  const session = useSession();
  const location = useLocation();
  if (!session) {
    return (
      <Navigate to="/login" replace state={{ from: location.pathname }} />
    );
  }
  return <Outlet />;
}

/**
 * Routes only (router-agnostic so tests can mount it in a MemoryRouter).
 * The app shell registers the 401 handler: any authenticated call that comes
 * back 401 clears the session and lands the user on /login.
 *
 * The Layout shell wraps BOTH the public and the authenticated routes:
 * /public renders for anyone (it fronts the one deliberately unauthenticated
 * endpoint — handoff 0006, design point 8), while everything else sits
 * behind RequireAuth. That client-side gate is UX only; the API enforces
 * authentication on every non-public endpoint.
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
      <Route element={<Layout />}>
        {/* UNAUTHENTICATED by design: certified figures are public record. */}
        <Route path="/public" element={<PublicDataView />} />
        <Route element={<RequireAuth />}>
          <Route path="/" element={<Navigate to="/metrics" replace />} />
          {/* Any authenticated role (handoff 0008, pillar B). */}
          <Route path="/dashboard" element={<DashboardView />} />
          <Route path="/metrics" element={<MetricsView />} />
          <Route path="/metrics/:id/lineage" element={<LineageView />} />
          <Route path="/reports/monthly" element={<MonthlyReportView />} />
          {/* Safety & Security (handoff 0010): any signed-in role reads;
              recording/correcting is data_steward+ (UX only — the API
              enforces the role on every safety write). */}
          <Route path="/safety" element={<SafetyView />} />
          <Route path="/dq" element={<DqView />} />
          {/* Role-gated in the UI (nav link + in-page notice); the API
              enforces certifying_official on POST /certifications. */}
          <Route path="/certify" element={<CertifyView />} />
          {/* Role-gated in the UI; the API enforces certifying_official on
              PUT /settings/* and POST /branding/logo (handoff 0008 C). */}
          <Route path="/settings/branding" element={<BrandingView />} />
        </Route>
      </Route>
    </Routes>
  );
}
