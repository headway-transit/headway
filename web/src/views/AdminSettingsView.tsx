/**
 * /admin/settings — the calc policy knobs finally get their UI room
 * (handoff 0025, design point 4): every knob GET /settings serves, with
 * its CURRENT VALUE VERBATIM (values are strings end to end — a policy
 * number is never reformatted), its plain-language basis (the served
 * description carries the citation), who changed it last, and an edit
 * affordance under the API's existing authz (PUT /settings/{key},
 * certifying official only, audited old→new).
 *
 * The sandbox's "change it in Settings" language is now TRUE: the hint
 * links the sandbox for modeling first; applying happens here.
 *
 * Branding keys are managed in their own room (/settings/branding) and are
 * excluded here — stated on the page, never silently missing.
 */

import { useEffect, useId, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, listSettings, updateSetting } from "../api/client";
import type { Setting } from "../api/types";
import { canCertify, useSession } from "../auth/session";
import { Breadcrumbs } from "../components/Breadcrumbs";
import { Skeleton } from "../components/Skeleton";
import { copy } from "../copy";

const t = copy.admin.settings;

/** Keys owned by the Branding room (/settings/branding) — handled there. */
const BRANDING_MANAGED_PREFIXES = ["brand_"];
const BRANDING_MANAGED_KEYS = new Set(["agency_display_name"]);

function isBrandingKey(key: string): boolean {
  return (
    BRANDING_MANAGED_KEYS.has(key) ||
    BRANDING_MANAGED_PREFIXES.some((prefix) => key.startsWith(prefix))
  );
}

/** Workflow timestamp label (never a figure). */
function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
    hour12: false,
  });
}

function SettingRow({
  setting,
  onSaved,
}: {
  setting: Setting;
  onSaved: () => Promise<void>;
}) {
  const [draft, setDraft] = useState(setting.setting_value);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const inputId = useId();
  const descriptionId = useId();

  const save = () => {
    if (busy) return;
    setBusy(true);
    setMessage(null);
    setErrorMessage(null);
    void (async () => {
      try {
        const saved = await updateSetting(setting.setting_key, draft);
        await onSaved();
        setDraft(saved.setting_value);
        // The saved value quoted EXACTLY as the server stored it.
        setMessage(t.saved(saved.setting_key, saved.setting_value));
      } catch (err) {
        // Type refusals ("'x' is not a decimal number…") verbatim.
        setErrorMessage(err instanceof ApiError ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    })();
  };

  return (
    <section className="card admin-section admin-setting">
      <h2>
        <code>{setting.setting_key}</code>
      </h2>
      {/* The basis citation travels in the served description, verbatim. */}
      <p id={descriptionId}>{setting.description}</p>
      <p className="field-hint">
        {t.updatedBy(setting.updated_by, formatWhen(setting.updated_at))}
      </p>
      <div className="admin-setting-edit">
        <label htmlFor={inputId}>{t.valueLabel(setting.setting_key)}</label>
        <input
          id={inputId}
          type="text"
          inputMode={setting.value_type === "text" ? undefined : "decimal"}
          aria-describedby={descriptionId}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button type="button" aria-disabled={busy || undefined} onClick={save}>
          {t.save(setting.setting_key)}
        </button>
      </div>
      {errorMessage && (
        <p role="alert" className="alert">
          {errorMessage}
        </p>
      )}
      {message && (
        <p role="status" className="status">
          {message}
        </p>
      )}
    </section>
  );
}

export function AdminSettingsView() {
  const session = useSession();
  const [settings, setSettings] = useState<Setting[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = async () => {
    try {
      setSettings(await listSettings());
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : String(err));
    }
  };

  useEffect(() => {
    if (!canCertify(session)) return;
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!canCertify(session)) {
    return (
      <>
        <h1>{t.heading}</h1>
        <p>{copy.admin.notAllowed}</p>
      </>
    );
  }

  const knobs = (settings ?? []).filter(
    (s) => !isBrandingKey(s.setting_key),
  );

  return (
    <>
      <Breadcrumbs
        trail={[
          { label: copy.admin.heading, to: "/admin" },
          { label: t.heading },
        ]}
      />
      <h1>{t.heading}</h1>
      <p>{t.intro}</p>
      <p>
        {t.sandboxHint} <Link to="/sandbox">{t.sandboxLink}</Link>
      </p>
      <p className="field-hint">{t.brandingNote}</p>

      {loadError && (
        <div role="alert" className="alert">
          {loadError}
        </div>
      )}
      {!settings && !loadError && (
        <Skeleton variant="lines" count={4} label={copy.loading} />
      )}

      {settings &&
        knobs.map((setting) => (
          <SettingRow
            key={setting.setting_key}
            setting={setting}
            onSaved={refresh}
          />
        ))}
    </>
  );
}
