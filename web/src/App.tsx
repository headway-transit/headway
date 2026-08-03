import { Suspense, lazy, useEffect } from "react";
import {
  Navigate,
  Outlet,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { setUnauthorizedHandler } from "./api/client";
import { landingPathFor, useSession } from "./auth/session";
import { Layout } from "./components/Layout";
import { AdminSettingsView } from "./views/AdminSettingsView";
import { AdminSourcesView } from "./views/AdminSourcesView";
import { AdminUsersView } from "./views/AdminUsersView";
import { AdminView } from "./views/AdminView";
import { AttestationsView } from "./views/AttestationsView";
import { BrandingView } from "./views/BrandingView";
import { CalcRunsView } from "./views/CalcRunsView";
import { CertificateView } from "./views/CertificateView";
import { CertificationsView } from "./views/CertificationsView";
import { CertifyView } from "./views/CertifyView";
import { CompareView } from "./views/CompareView";
import { DashboardView } from "./views/DashboardView";
import { DqView } from "./views/DqView";
import { RevenueReviewView } from "./views/RevenueReviewView";
import { LineageView } from "./views/LineageView";
import { LoginView } from "./views/LoginView";
import { MetricsView } from "./views/MetricsView";
import { MonthlyReportView } from "./views/MonthlyReportView";
import { PublicDataView } from "./views/PublicDataView";
import { ReviewView } from "./views/ReviewView";
import { SafetyView } from "./views/SafetyView";
import { SamplingView } from "./views/SamplingView";
import { SandboxView } from "./views/SandboxView";
import { SsoCallbackView } from "./views/SsoCallbackView";
import { TodayView } from "./views/TodayView";
import { Skeleton } from "./components/Skeleton";
import { copy } from "./copy";

/**
 * The living map (handoff 0024) is code-split: MapLibre GL JS (~800 kB
 * minified) loads only when /map is visited, so the /today first-paint
 * budget is untouched by the map's arrival.
 */
const MapView = lazy(() =>
  import("./views/MapView").then((m) => ({ default: m.MapView })),
);

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
 * "/" — the room a role calls home. /today for everyone who acts; /review
 * for a read-only role, whose question is "what was filed, and does it hold
 * up?" rather than "what should I do now?" (handoff 0047, design point 1).
 *
 * The choice itself lives in auth/session.ts, shared with the sign-in form
 * and the single-sign-on callback, so a role cannot land in one room by
 * password and another by identity provider.
 */
function LandingRedirect() {
  const session = useSession();
  return <Navigate to={landingPathFor(session)} replace />;
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
      {/* Where the identity provider sends the browser back (handoff 0046,
          docs/single-sign-on.md). Unauthenticated by necessity — turning the
          provider's answer into a session is the whole job of this route —
          and outside the Layout shell exactly like /login, because there is
          no nav to draw for someone who is not signed in yet. */}
      <Route path="/auth/callback" element={<SsoCallbackView />} />
      <Route element={<Layout />}>
        {/* UNAUTHENTICATED by design: certified figures are public record. */}
        <Route path="/public" element={<PublicDataView />} />
        <Route element={<RequireAuth />}>
          {/* /today is the post-login landing (handoff 0021, design point
              1) for every role that acts; a read-only role lands on /review
              instead (handoff 0047). The dashboard keeps its place in the
              nav either way. */}
          <Route path="/" element={<LandingRedirect />} />
          <Route path="/today" element={<TodayView />} />
          {/* The reviewer's room (handoff 0047): a worklist of
              certifications, and the landing surface for a read-only role.
              Open to any signed-in role, exactly like the reads it is made
              of (GET /certifications and GET /certifications/{id}) — the
              nav offers it to readers, which is UX, never security. */}
          <Route path="/review" element={<ReviewView />} />
          {/* The living map (handoff 0024, design point 1): any signed-in
              role, exactly like GET /ops/vehicles/latest + /geometry/*. */}
          <Route
            path="/map"
            element={
              <Suspense
                fallback={<Skeleton variant="lines" count={3} label={copy.map.loading} />}
              >
                <MapView />
              </Suspense>
            }
          />
          {/* Any authenticated role (handoff 0008, pillar B). */}
          <Route path="/dashboard" element={<DashboardView />} />
          <Route path="/metrics" element={<MetricsView />} />
          {/* The calculations room (handoff 0026): any signed-in role READS
              run history; starting a run is data_steward+ (UX only — the
              API enforces the role on POST /calc/runs). */}
          <Route path="/calc-runs" element={<CalcRunsView />} />
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
          {/* The revenue review queue (handoff 0040): the boardings
              Headway held out of the ridership figure because it
              refused to guess what they were. Readable by every
              signed-in role; the decision inside is role-gated. */}
          <Route path="/revenue-review" element={<RevenueReviewView />} />
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
          {/* The admin area (handoff 0025): hub + rooms. Certifying
              official only in the UI (sources also opens for stewards,
              matching GET /sources/status); the API enforces the role on
              every admin call — hiding a page is never security. */}
          <Route path="/admin" element={<AdminView />} />
          <Route path="/admin/users" element={<AdminUsersView />} />
          <Route path="/admin/sources" element={<AdminSourcesView />} />
          <Route path="/admin/settings" element={<AdminSettingsView />} />
        </Route>
      </Route>
    </Routes>
  );
}
