/**
 * /admin — the admin hub (handoff 0025, built from the first real agency
 * UAT: "Why isn't there an admin page where you can add and connect your
 * data sources, manage users, connect to SSO?").
 *
 * Five doors and two HONEST cards:
 * - Users, Data sources, Settings — admin rooms under /admin/*.
 * - Branding — the existing /settings/branding room, linked (its route
 *   keeps working; the old nav entry moved here).
 * - Single sign-on — an honest card, NO toggles: SSO is designed
 *   (ADR-0011: native OIDC — Entra ID, Google, Okta — plus local
 *   accounts) and not yet available. Nothing pretends.
 * - Updates — an honest card, NO buttons that act: updating happens on
 *   the server by an administrator; the two commands are shown verbatim.
 *   A web session must never be able to replace the software it runs in.
 *
 * Role gating here is UX only (the nav shows Admin to the certifying
 * official); the API enforces the role on every admin call.
 */

import { Link } from "react-router-dom";
import { canCertify, useSession } from "../auth/session";
import { copy } from "../copy";

const t = copy.admin;

function DoorCard({
  title,
  description,
  to,
  link,
}: {
  title: string;
  description: string;
  to: string;
  link: string;
}) {
  return (
    <section className="card admin-card">
      <h2>{title}</h2>
      <p>{description}</p>
      <p>
        <Link to={to}>{link}</Link>
      </p>
    </section>
  );
}

export function AdminView() {
  const session = useSession();
  if (!canCertify(session)) {
    return (
      <>
        <h1>{t.heading}</h1>
        <p>{t.notAllowed}</p>
      </>
    );
  }

  return (
    <>
      <h1>{t.heading}</h1>
      <p>{t.intro}</p>
      <div className="admin-cards">
        <DoorCard
          title={t.cards.users.title}
          description={t.cards.users.description}
          to="/admin/users"
          link={t.cards.users.link}
        />
        <DoorCard
          title={t.cards.sources.title}
          description={t.cards.sources.description}
          to="/admin/sources"
          link={t.cards.sources.link}
        />
        <DoorCard
          title={t.cards.branding.title}
          description={t.cards.branding.description}
          to="/settings/branding"
          link={t.cards.branding.link}
        />
        <DoorCard
          title={t.cards.settings.title}
          description={t.cards.settings.description}
          to="/admin/settings"
          link={t.cards.settings.link}
        />

        {/* The honest SSO card (binding): status + what exists today +
            the ADR citation. No toggle, no setup affordance. */}
        <section className="card admin-card">
          <h2>{t.cards.sso.title}</h2>
          <p className="admin-card-status">{t.cards.sso.status}</p>
          {t.cards.sso.body.map((paragraph) => (
            <p key={paragraph.slice(0, 24)}>{paragraph}</p>
          ))}
        </section>

        {/* The honest Updates card: how updating really happens (on the
            server, by an administrator), the commands verbatim, and why
            there is deliberately no update button in a browser. */}
        <section className="card admin-card">
          <h2>{t.cards.updates.title}</h2>
          <p className="admin-card-status">{t.cards.updates.status}</p>
          {t.cards.updates.body.map((paragraph) => (
            <p key={paragraph.slice(0, 24)}>{paragraph}</p>
          ))}
          <p className="admin-command-label">
            {t.cards.updates.commandSourceLabel}
          </p>
          <pre className="admin-command">
            <code>{t.cards.updates.commandSource}</code>
          </pre>
          <p className="admin-command-label">
            {t.cards.updates.commandReleaseLabel}
          </p>
          <pre className="admin-command">
            <code>{t.cards.updates.commandRelease}</code>
          </pre>
          <p>{t.cards.updates.whyNoButton}</p>
        </section>
      </div>
    </>
  );
}
