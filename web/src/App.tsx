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
import { AttestationsView } from "./views/AttestationsView";
import { BrandingView } from "./views/BrandingView";
import { CertificateView } from "./views/CertificateView";
import { CertificationsView } from "./views/CertificationsView";
import { CertifyView } from "./views/CertifyView";
import { CompareView } from "./views/CompareView";
import { DashboardView } from "./views/DashboardView";
import { DqView } from "./views/DqView";
import { LineageView } from "./views/LineageView";
import { LoginView } from "./views/LoginView";
import { MetricsView } from "./views/MetricsView";
import { MonthlyReportView } from "./views/MonthlyReportView";
import { PublicDataView } from "./views/PublicDataView";
import { SafetyView } from "./views/SafetyView";
import { SamplingView } from "./views/SamplingView";
import { SandboxView } from "./views/SandboxView";
import { TodayView } from "./views/TodayView";

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
          {/* /today is the post-login landing (handoff 0021, design point
              1); the dashboard keeps its place in the nav. */}
          <Route path="/" element={<Navigate to="/today" replace />} />
          <Route path="/today" element={<TodayView />} />
          {/* Any authenticated role (handoff 0008, pillar B). */}
          <Route path="/dashboard" element={<DashboardView />} />
          <Route path="/metrics" element={<MetricsView />} />
          {/* Comparison surface (handoff 0017 #1): any signed-in role. */}
          <Route path="/compare" element={<CompareView />} />
          <Route path="/metrics/:id/lineage" element={<LineageView />} />
          <Route path="/reports/monthly" element={<MonthlyReportView />} />
          {/* Safety & Security (handoff 0010): any signed-in role reads;
              recording/correcting is data_steward+ (UX only — the API
              enforces the role on every safety write). */}
          <Route path="/safety" element={<SafetyView />} />
          {/* PMT sampling (handoff 0012): any signed-in role reads;
              planning/drawing/measuring/estimating is data_steward+ (UX
              only — the API enforces the role on every sampling write). */}
          <Route path="/sampling" element={<SamplingView />} />
          <Route path="/dq" element={<DqView />} />
          {/* Settings sandbox (handoff 0017 #6): a what-if PREVIEW surface
              that changes nothing — any signed-in role may model; the API
              enforces whatever role the preview run requires. */}
          <Route path="/sandbox" element={<SandboxView />} />
          {/* Statistician attestations (handoff 0019, design A): any
              signed-in role reads the record; recording one is gated in
              the UI and enforced by the API on POST /attestations. */}
          <Route path="/attestations" element={<AttestationsView />} />
          {/* The certifications index (handoff 0019 follow-up): every
              certification on record, list → certificate. Any signed-in
              role reads it, exactly like the API's GET /certifications. */}
          <Route path="/certifications" element={<CertificationsView />} />
          {/* Role-gated in the UI (nav link + in-page notice); the API
              enforces certifying_official on POST /certifications. */}
          <Route path="/certify" element={<CertifyView />} />
          {/* The certificate (handoff 0019, design 5): the stored record
              of one certification with its signature block and verify
              action. Any signed-in role may read it. */}
          <Route path="/certifications/:id" element={<CertificateView />} />
          {/* Role-gated in the UI; the API enforces certifying_official on
              PUT /settings/* and POST /branding/logo (handoff 0008 C). */}
          <Route path="/settings/branding" element={<BrandingView />} />
        </Route>
      </Route>
    </Routes>
  );
}
