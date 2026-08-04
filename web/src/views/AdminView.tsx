/**
 * /admin — the admin hub (handoff 0025, built from the first real agency
 * UAT: "Why isn't there an admin page where you can add and connect your
 * data sources, manage users, connect to SSO?").
 *
 * Four doors, a REAL single-sign-on screen, and one honest card:
 * - Users, Data sources, Settings — admin rooms under /admin/*.
 * - Branding — the existing /settings/branding room, linked.
 * - Single sign-on — was an honest card for weeks ("designed, ADR-0011, not
 *   built"). Handoff 0046 built it, so it is now a working configuration
 *   screen: provider settings, an encrypted show-once client secret, the
 *   group-to-role mappings, and a test action that proves the round trip
 *   before anyone depends on it. The honesty rule did not change — the
 *   status line states what is actually true right now, and the screen says
 *   plainly what turning it on changes on the sign-in page, where the
 *   button now really appears.
 * - Updates — an honest card, NO buttons that act: updating happens on
 *   the server by an administrator; the two commands are shown verbatim.
 *   A web session must never be able to replace the software it runs in.
 *
 * WRITTEN FOR A ZERO-SQL READER. Every field says where to find its value at
 * the provider, and every refusal from the server is shown verbatim at the
 * control that caused it — the difference between a working integration and
 * a support call is whether the person configuring it can act on what they
 * are told.
 *
 * Role gating here is UX only (the nav shows Admin to the certifying
 * official); the API enforces the role on every admin call.
 */

import {
  useCallback,
  useEffect,
  useId,
  useState,
  type FormEvent,
} from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  createSsoMapping,
  deleteSsoMapping,
  getSsoConfig,
  listSsoMappings,
  testSsoConfig,
  updateSsoConfig,
  type SsoConfig,
  type SsoRoleMapping,
  type SsoTestResult,
} from "../api/client";
import { canCertify, useSession } from "../auth/session";
import { copy } from "../copy";

const t = copy.admin;
const s = copy.admin.sso;

/**
 * The roles an IdP group may be mapped to. `certifying_official` is absent
 * on purpose and the screen says why (`certifyingOfficialNote`): signing a
 * federal submission is granted inside Headway, never by a group membership
 * Headway does not control. The server refuses it too, and so does the
 * database — this list is the first of three layers, not the only one.
 */
const MAPPABLE_ROLES = [
  "viewer",
  "auditor",
  "data_steward",
  "report_preparer",
] as const;

function ssoRoleLabel(role: string): string {
  return s.roleLabels[role] ?? role;
}

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

/** The live status line. Text states it — never colour alone (WCAG AA). */
function ssoStatusLabel(config: SsoConfig | null): string {
  const card = t.cards.sso;
  if (!config || !config.configured) return card.statusNotConfigured;
  if (config.disabled_by_environment) return card.statusDisabledByServer;
  return config.is_enabled ? card.statusOn : card.statusOff;
}

function errorText(err: unknown): string {
  return err instanceof ApiError ? err.message : String(err);
}

// ---------------------------------------------------------------------------
// The provider settings form
// ---------------------------------------------------------------------------

interface FormState {
  discovery_url: string;
  client_id: string;
  client_secret: string;
  redirect_uri: string;
  groups_claim: string;
  username_claim: string;
  clock_skew_seconds: string;
  ca_bundle_path: string;
  button_label: string;
  is_enabled: boolean;
}

function formFromConfig(config: SsoConfig): FormState {
  return {
    discovery_url: config.discovery_url ?? "",
    client_id: config.client_id ?? "",
    // Always blank: a stored secret is never served back, so there is
    // nothing to prefill and nothing to accidentally re-submit.
    client_secret: "",
    redirect_uri:
      config.redirect_uri ?? `${window.location.origin}/auth/callback`,
    groups_claim: config.groups_claim,
    username_claim: config.username_claim,
    clock_skew_seconds: String(config.clock_skew_seconds),
    ca_bundle_path: config.ca_bundle_path ?? "",
    button_label: config.button_label,
    is_enabled: config.is_enabled,
  };
}

function ProviderSettingsForm({
  config,
  onSaved,
}: {
  config: SsoConfig;
  onSaved: () => Promise<void>;
}) {
  const [form, setForm] = useState<FormState>(() => formFromConfig(config));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const ids = {
    discovery: useId(),
    discoveryHint: useId(),
    clientId: useId(),
    clientIdHint: useId(),
    secret: useId(),
    secretHint: useId(),
    redirect: useId(),
    redirectHint: useId(),
    groups: useId(),
    groupsHint: useId(),
    username: useId(),
    usernameHint: useId(),
    skew: useId(),
    skewHint: useId(),
    caBundle: useId(),
    caBundleHint: useId(),
    buttonLabel: useId(),
    buttonLabelHint: useId(),
    enabled: useId(),
    enabledHint: useId(),
  };

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((previous) => ({ ...previous, [key]: value }));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setMessage(null);
    setErrorMessage(null);
    void (async () => {
      try {
        await updateSsoConfig({
          discovery_url: form.discovery_url.trim(),
          client_id: form.client_id.trim(),
          // Blank means KEEP the stored secret — the server treats null that
          // way, so an admin can edit the group claim without re-entering a
          // credential they were shown once.
          client_secret: form.client_secret === "" ? null : form.client_secret,
          redirect_uri: form.redirect_uri.trim(),
          groups_claim: form.groups_claim.trim(),
          username_claim: form.username_claim.trim(),
          clock_skew_seconds: Number(form.clock_skew_seconds),
          ca_bundle_path:
            form.ca_bundle_path.trim() === "" ? null : form.ca_bundle_path.trim(),
          button_label: form.button_label.trim(),
          is_enabled: form.is_enabled,
        });
        await onSaved();
        setForm((previous) => ({ ...previous, client_secret: "" }));
        setMessage(s.saved);
      } catch (err) {
        // Server refusals verbatim: the http:// refusal, the missing CA
        // file, the "cannot turn it on without a secret" 422, the 503 when
        // there is nowhere safe to keep a secret.
        setErrorMessage(errorText(err));
      } finally {
        setBusy(false);
      }
    })();
  };

  return (
    <form className="admin-create-form" onSubmit={submit}>
      <h3>{s.settingsHeading}</h3>
      {errorMessage && (
        <div role="alert" className="alert">
          {errorMessage}
        </div>
      )}
      {message && (
        <div role="status" className="status">
          {message}
        </div>
      )}

      <div>
        <label htmlFor={ids.discovery}>{s.discoveryLabel}</label>
        <p className="field-hint" id={ids.discoveryHint}>
          {s.discoveryHint}
        </p>
        <input
          id={ids.discovery}
          type="url"
          autoComplete="off"
          aria-describedby={ids.discoveryHint}
          value={form.discovery_url}
          onChange={(e) => set("discovery_url", e.target.value)}
        />
      </div>

      <div>
        <label htmlFor={ids.clientId}>{s.clientIdLabel}</label>
        <p className="field-hint" id={ids.clientIdHint}>
          {s.clientIdHint}
        </p>
        <input
          id={ids.clientId}
          type="text"
          autoComplete="off"
          aria-describedby={ids.clientIdHint}
          value={form.client_id}
          onChange={(e) => set("client_id", e.target.value)}
        />
      </div>

      <div>
        <label htmlFor={ids.secret}>{s.clientSecretLabel}</label>
        <p className="field-hint" id={ids.secretHint}>
          {config.client_secret_set
            ? s.clientSecretHintSet
            : s.clientSecretHintUnset}
        </p>
        {!config.secret_storage_available && (
          <p role="alert" className="alert">
            {s.clientSecretUnavailable}
          </p>
        )}
        <input
          id={ids.secret}
          type="password"
          autoComplete="new-password"
          aria-describedby={ids.secretHint}
          placeholder={
            config.client_secret_set ? s.clientSecretPlaceholderSet : undefined
          }
          value={form.client_secret}
          onChange={(e) => set("client_secret", e.target.value)}
        />
      </div>

      <div>
        <label htmlFor={ids.redirect}>{s.redirectLabel}</label>
        <p className="field-hint" id={ids.redirectHint}>
          {s.redirectHint}
        </p>
        <input
          id={ids.redirect}
          type="url"
          autoComplete="off"
          aria-describedby={ids.redirectHint}
          value={form.redirect_uri}
          onChange={(e) => set("redirect_uri", e.target.value)}
        />
      </div>

      <div>
        <label htmlFor={ids.groups}>{s.groupsClaimLabel}</label>
        <p className="field-hint" id={ids.groupsHint}>
          {s.groupsClaimHint}
        </p>
        <input
          id={ids.groups}
          type="text"
          autoComplete="off"
          aria-describedby={ids.groupsHint}
          value={form.groups_claim}
          onChange={(e) => set("groups_claim", e.target.value)}
        />
      </div>

      <div>
        <label htmlFor={ids.username}>{s.usernameClaimLabel}</label>
        <p className="field-hint" id={ids.usernameHint}>
          {s.usernameClaimHint}
        </p>
        <input
          id={ids.username}
          type="text"
          autoComplete="off"
          aria-describedby={ids.usernameHint}
          value={form.username_claim}
          onChange={(e) => set("username_claim", e.target.value)}
        />
      </div>

      <div>
        <label htmlFor={ids.skew}>{s.skewLabel}</label>
        <p className="field-hint" id={ids.skewHint}>
          {s.skewHint}
        </p>
        <input
          id={ids.skew}
          type="number"
          inputMode="numeric"
          min={0}
          max={600}
          aria-describedby={ids.skewHint}
          value={form.clock_skew_seconds}
          onChange={(e) => set("clock_skew_seconds", e.target.value)}
        />
      </div>

      <div>
        <label htmlFor={ids.caBundle}>{s.caBundleLabel}</label>
        <p className="field-hint" id={ids.caBundleHint}>
          {s.caBundleHint}
        </p>
        <input
          id={ids.caBundle}
          type="text"
          autoComplete="off"
          aria-describedby={ids.caBundleHint}
          value={form.ca_bundle_path}
          onChange={(e) => set("ca_bundle_path", e.target.value)}
        />
      </div>

      <div>
        <label htmlFor={ids.buttonLabel}>{s.buttonLabelLabel}</label>
        <p className="field-hint" id={ids.buttonLabelHint}>
          {s.buttonLabelHint}
        </p>
        <input
          id={ids.buttonLabel}
          type="text"
          autoComplete="off"
          aria-describedby={ids.buttonLabelHint}
          value={form.button_label}
          onChange={(e) => set("button_label", e.target.value)}
        />
      </div>

      <div>
        <p className="field-hint" id={ids.enabledHint}>
          {s.enabledHint}
        </p>
        <input
          id={ids.enabled}
          type="checkbox"
          aria-describedby={ids.enabledHint}
          checked={form.is_enabled}
          onChange={(e) => set("is_enabled", e.target.checked)}
        />{" "}
        <label htmlFor={ids.enabled}>{s.enabledLabel}</label>
      </div>

      <button type="submit" aria-disabled={busy || undefined}>
        {s.save}
      </button>
    </form>
  );
}

// ---------------------------------------------------------------------------
// "Test this configuration"
// ---------------------------------------------------------------------------

function TestConfiguration() {
  const [result, setResult] = useState<SsoTestResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const run = () => {
    if (busy) return;
    setBusy(true);
    setErrorMessage(null);
    void (async () => {
      try {
        setResult(await testSsoConfig());
      } catch (err) {
        setErrorMessage(errorText(err));
      } finally {
        setBusy(false);
      }
    })();
  };

  return (
    <div>
      <h3>{s.testHeading}</h3>
      <p className="field-hint">{s.testIntro}</p>
      <button type="button" onClick={run} aria-disabled={busy || undefined}>
        {busy ? s.testing : s.test}
      </button>
      {errorMessage && (
        <div role="alert" className="alert">
          {errorMessage}
        </div>
      )}
      {result && (
        <>
          <div
            role="status"
            className={result.ok ? "status" : "alert"}
          >
            {result.ok ? s.testPassed : s.testFailed}
          </div>
          <div className="table-wrap">
            <table>
              <tbody>
                {result.steps.map((step) => (
                  <tr key={step.step}>
                    {/* Text, not colour alone — a step's verdict has to be
                        readable to someone who cannot see the difference. */}
                    <th scope="row">{step.step}</th>
                    <td>{step.ok ? s.stepOk : s.stepFailed}</td>
                    <td>{step.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Group -> role mappings
// ---------------------------------------------------------------------------

function MappingsPanel({
  mappings,
  onChanged,
}: {
  mappings: SsoRoleMapping[];
  onChanged: () => Promise<void>;
}) {
  const [claimValue, setClaimValue] = useState("");
  const [role, setRole] = useState<string>("viewer");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const claimId = useId();
  const claimHintId = useId();
  const claimExampleId = useId();
  const roleId = useId();
  const roleHintId = useId();
  const noteId = useId();
  const noteHintId = useId();

  const add = (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setMessage(null);
    setErrorMessage(null);
    void (async () => {
      try {
        const created = await createSsoMapping({
          claim_value: claimValue,
          headway_role: role,
          note: note.trim() === "" ? null : note.trim(),
        });
        await onChanged();
        setMessage(
          s.mappingAdded(created.claim_value, ssoRoleLabel(created.headway_role)),
        );
        setClaimValue("");
        setNote("");
      } catch (err) {
        // Includes the plain-language refusal of certifying_official, which
        // explains WHY rather than just saying no.
        setErrorMessage(errorText(err));
      } finally {
        setBusy(false);
      }
    })();
  };

  const remove = (mapping: SsoRoleMapping) => {
    if (busy) return;
    setBusy(true);
    setMessage(null);
    setErrorMessage(null);
    void (async () => {
      try {
        await deleteSsoMapping(mapping.mapping_id);
        await onChanged();
        setMessage(s.mappingRemoved(mapping.claim_value));
      } catch (err) {
        setErrorMessage(errorText(err));
      } finally {
        setBusy(false);
      }
    })();
  };

  return (
    <div>
      <h3>{s.mappingsHeading}</h3>
      <p className="field-hint">{s.mappingsIntro}</p>
      {errorMessage && (
        <div role="alert" className="alert">
          {errorMessage}
        </div>
      )}
      {message && (
        <div role="status" className="status">
          {message}
        </div>
      )}

      {mappings.length === 0 ? (
        <p className="banner">{s.mappingsEmpty}</p>
      ) : (
        <div className="table-wrap">
          <table className="admin-users-table">
            <thead>
              <tr>
                <th scope="col">{s.mappingsTable.claim}</th>
                <th scope="col">{s.mappingsTable.role}</th>
                <th scope="col">{s.mappingsTable.note}</th>
                <th scope="col">{s.mappingsTable.addedBy}</th>
                <th scope="col">{s.mappingsTable.actions}</th>
              </tr>
            </thead>
            <tbody>
              {mappings.map((mapping) => (
                <tr key={mapping.mapping_id}>
                  <td>{mapping.claim_value}</td>
                  <td>{ssoRoleLabel(mapping.headway_role)}</td>
                  <td>{mapping.note ?? ""}</td>
                  <td>{mapping.created_by}</td>
                  <td>
                    <button
                      type="button"
                      aria-label={s.removeMappingLabel(mapping.claim_value)}
                      aria-disabled={busy || undefined}
                      onClick={() => remove(mapping)}
                    >
                      {s.removeMapping}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <form className="admin-create-form" onSubmit={add}>
        <h4>{s.addMappingHeading}</h4>
        <div>
          <label htmlFor={claimId}>{s.claimValueLabel}</label>
          <p className="field-hint" id={claimHintId}>
            {s.claimValueHint}
          </p>
          {/* The example is shown as an example and says so. Headway has no
              built-in group name and requires no naming convention — an
              agency maps the groups its directory already has. */}
          <p className="field-hint" id={claimExampleId}>
            {s.claimValueExample}
          </p>
          <input
            id={claimId}
            type="text"
            autoComplete="off"
            placeholder={s.claimValuePlaceholder}
            aria-describedby={`${claimHintId} ${claimExampleId}`}
            value={claimValue}
            onChange={(e) => setClaimValue(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor={roleId}>{s.mappingRoleLabel}</label>
          <p className="field-hint" id={roleHintId}>
            {s.mappingRoleHint}
          </p>
          <select
            id={roleId}
            aria-describedby={roleHintId}
            value={role}
            onChange={(e) => setRole(e.target.value)}
          >
            {MAPPABLE_ROLES.map((r) => (
              <option key={r} value={r}>
                {ssoRoleLabel(r)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={noteId}>{s.noteLabel}</label>
          <p className="field-hint" id={noteHintId}>
            {s.noteHint}
          </p>
          <input
            id={noteId}
            type="text"
            autoComplete="off"
            aria-describedby={noteHintId}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>
        <button type="submit" aria-disabled={busy || undefined}>
          {s.addMapping}
        </button>
      </form>

      {/* Why one role is missing from the list above. Saying nothing would
          read as an oversight and invite someone to look for a way round. */}
      <p className="field-hint">{s.certifyingOfficialNote}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// The whole single-sign-on section
// ---------------------------------------------------------------------------

function SsoSection({
  config,
  mappings,
  loadError,
  onChanged,
}: {
  config: SsoConfig | null;
  mappings: SsoRoleMapping[];
  loadError: string | null;
  onChanged: () => Promise<void>;
}) {
  return (
    <section className="card admin-section" id="sso-settings">
      <h2>{s.heading}</h2>
      <p>{s.intro}</p>
      {/* The break-glass promise, stated where it matters: turning SSO on
          never takes the local sign-in away. */}
      <p className="field-hint">{t.cards.sso.localAlwaysWorks}</p>
      {loadError && (
        <div role="alert" className="alert">
          {loadError}
        </div>
      )}
      {config && (
        <>
          <ProviderSettingsForm config={config} onSaved={onChanged} />
          <TestConfiguration />
          <MappingsPanel mappings={mappings} onChanged={onChanged} />
          {/* Honest to the last: the sign-in screen offers this button as
              soon as single sign-on is on, so this line says what turning it
              on actually changes for staff — including the half that does
              not change, which is that Headway passwords keep working. */}
          <p className="field-hint">{s.loginButtonLive}</p>
        </>
      )}
    </section>
  );
}

export function AdminView() {
  const session = useSession();
  const [config, setConfig] = useState<SsoConfig | null>(null);
  const [mappings, setMappings] = useState<SsoRoleMapping[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showSso, setShowSso] = useState(false);
  const allowed = canCertify(session);

  const refresh = useCallback(async () => {
    // Always re-read from the server after a change — never client-adjust.
    try {
      const [nextConfig, nextMappings] = await Promise.all([
        getSsoConfig(),
        listSsoMappings(),
      ]);
      setConfig(nextConfig);
      setMappings(nextMappings);
      setLoadError(null);
    } catch (err) {
      setLoadError(`${s.loadError} ${errorText(err)}`);
    }
  }, []);

  useEffect(() => {
    if (!allowed) return;
    void refresh();
  }, [allowed, refresh]);

  if (!allowed) {
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
        {/* Block names (task #34): the door that replaces a shell command. */}
        <DoorCard
          title={t.blockLabels.title}
          description={t.blockLabels.description}
          to="/admin/block-labels"
          link={t.blockLabels.link}
        />

        {/* Single sign-on: a real card now (handoff 0046). The status line
            is the LIVE state, read from the server — not a claim. */}
        <section className="card admin-card">
          <h2>{t.cards.sso.title}</h2>
          <p className="admin-card-status">{ssoStatusLabel(config)}</p>
          <p>{t.cards.sso.description}</p>
          <p className="field-hint">{t.cards.sso.localAlwaysWorks}</p>
          <p>
            <button
              type="button"
              aria-expanded={showSso}
              aria-controls="sso-settings"
              onClick={() => setShowSso((open) => !open)}
            >
              {showSso ? t.cards.sso.hide : t.cards.sso.configure}
            </button>
          </p>
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

      {showSso && (
        <SsoSection
          config={config}
          mappings={mappings}
          loadError={loadError}
          onChanged={refresh}
        />
      )}
    </>
  );
}
