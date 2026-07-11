/**
 * /settings/branding (handoff 0008, pillar C): the certifying official sets
 * the agency display name, two brand colors, and a logo.
 *
 * THE GUARDRAIL LIVES SERVER-SIDE: headway_api/branding.py refuses any brand
 * color under 4.5:1 (WCAG 2.1 AA) against either light app surface with a
 * plain-language 422 naming the surface and the measured ratio. This page
 * surfaces that refusal VERBATIM — the live preview shows what a color would
 * look like, but the server decides whether it ships. Client role checks
 * here are UX only; the API enforces certifying_official on every write.
 *
 * Brand colors restyle CHROME ONLY (header, links/accents in the light
 * theme). They never color a chart: the chart palette is validated
 * separately (CVD separation, chroma, surface contrast) and a brand hex has
 * passed none of those checks — see src/branding.ts.
 */

import { useEffect, useId, useState } from "react";
import type { FormEvent } from "react";
import {
  ApiError,
  brandingLogoUrl,
  getBranding,
  updateSetting,
  uploadLogo,
} from "../api/client";
import type { Branding } from "../api/types";
import { getCurrentBranding, setBranding } from "../branding";
import { canCertify, useSession } from "../auth/session";
import { copy } from "../copy";

const HEX_RE = /^#[0-9a-fA-F]{6}$/;

interface ColorFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  onSave: () => void;
  saving: boolean;
}

/**
 * One brand color: a native picker and a hex text field, kept in sync. The
 * picker needs a valid hex to render, so it falls back to black while the
 * text value is mid-edit; the text field is the source of truth.
 */
function ColorField({ label, value, onChange, onSave, saving }: ColorFieldProps) {
  const pickerId = useId();
  const hexId = useId();
  const hintId = useId();
  return (
    <div>
      <div className="color-field">
        <div>
          <label htmlFor={pickerId}>{label}</label>
          <input
            id={pickerId}
            type="color"
            value={HEX_RE.test(value) ? value.toLowerCase() : "#000000"}
            onChange={(e) => onChange(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor={hexId}>{copy.branding.colorHexLabel(label)}</label>
          <input
            id={hexId}
            type="text"
            value={value}
            aria-describedby={hintId}
            onChange={(e) => onChange(e.target.value)}
          />
        </div>
        <button type="button" onClick={onSave} disabled={saving}>
          {copy.branding.saveColor(label)}
        </button>
      </div>
      <p className="branding-hint" id={hintId}>
        {copy.branding.colorHint}
      </p>
    </div>
  );
}

export function BrandingView() {
  const session = useSession();
  const mayEdit = canCertify(session); // UX only; the API enforces the role

  const [loadError, setLoadError] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [primary, setPrimary] = useState("#1a5fb4");
  const [accent, setAccent] = useState("#0b57d0");
  const [hasLogo, setHasLogo] = useState(false);
  const [logoFile, setLogoFile] = useState<File | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const nameId = useId();
  const nameHintId = useId();
  const logoId = useId();
  const logoHintId = useId();

  useEffect(() => {
    getBranding().then(
      (branding) => {
        setDisplayName(branding.display_name);
        setPrimary(branding.primary);
        setAccent(branding.accent);
        setHasLogo(branding.has_logo);
        setBranding(branding); // keep the shell in sync
      },
      () => setLoadError(copy.branding.loadError),
    );
  }, []);

  /** Push a saved change into the app-shell branding store immediately. */
  const publish = (patch: Partial<Branding>) => {
    const base = getCurrentBranding() ?? {
      display_name: displayName,
      primary,
      accent,
      has_logo: hasLogo,
    };
    setBranding({ ...base, ...patch });
  };

  const run = async (action: () => Promise<void>) => {
    setError(null);
    setStatusMessage(null);
    setSaving(true);
    try {
      await action();
    } catch (err) {
      // The server's plain-language refusal ("That color doesn't have
      // enough contrast…"), shown VERBATIM — never rewritten or softened.
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const saveDisplayName = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      const saved = await updateSetting("agency_display_name", displayName);
      publish({ display_name: saved.setting_value });
      setStatusMessage(copy.branding.displayNameSaved(saved.setting_value));
    });
  };

  const saveColor = (key: "brand_color_primary" | "brand_color_accent") => {
    const label =
      key === "brand_color_primary"
        ? copy.branding.primaryLabel
        : copy.branding.accentLabel;
    const value = key === "brand_color_primary" ? primary : accent;
    void run(async () => {
      const saved = await updateSetting(key, value);
      publish(
        key === "brand_color_primary"
          ? { primary: saved.setting_value }
          : { accent: saved.setting_value },
      );
      setStatusMessage(copy.branding.colorSaved(label, saved.setting_value));
    });
  };

  const submitLogo = (event: FormEvent) => {
    event.preventDefault();
    if (!logoFile) {
      setError(copy.branding.chooseFileFirst);
      setStatusMessage(null);
      return;
    }
    void run(async () => {
      const uploaded = await uploadLogo(logoFile);
      setHasLogo(true);
      publish({ has_logo: true });
      setStatusMessage(
        copy.branding.logoUploaded(uploaded.bytes.toLocaleString("en-US")),
      );
    });
  };

  if (!mayEdit) {
    return (
      <>
        <h1>{copy.branding.heading}</h1>
        <p>{copy.branding.notAllowed}</p>
      </>
    );
  }

  return (
    <>
      <h1>{copy.branding.heading}</h1>
      <p>{copy.branding.intro}</p>

      {loadError && (
        <div role="alert" className="alert">
          {loadError}
        </div>
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {statusMessage && (
        <div role="status" className="status">
          {statusMessage}
        </div>
      )}

      <div className="branding-form">
        <section className="card branding-section">
          <h2>{copy.branding.displayNameHeading}</h2>
          <form onSubmit={saveDisplayName}>
            <label htmlFor={nameId}>{copy.branding.displayNameLabel}</label>
            <p className="branding-hint" id={nameHintId}>
              {copy.branding.displayNameHint}
            </p>
            <input
              id={nameId}
              type="text"
              value={displayName}
              aria-describedby={nameHintId}
              onChange={(e) => setDisplayName(e.target.value)}
            />
            <button type="submit" disabled={saving}>
              {copy.branding.saveDisplayName}
            </button>
          </form>
        </section>

        <section className="card branding-section">
          <h2>{copy.branding.previewHeading}</h2>
          <p className="branding-hint">{copy.branding.previewIntro}</p>

          <ColorField
            label={copy.branding.primaryLabel}
            value={primary}
            onChange={setPrimary}
            onSave={() => saveColor("brand_color_primary")}
            saving={saving}
          />
          <ColorField
            label={copy.branding.accentLabel}
            value={accent}
            onChange={setAccent}
            onSave={() => saveColor("brand_color_accent")}
            saving={saving}
          />

          {/* The preview renders on the LIGHT surfaces (#ffffff / #f6f8fa) —
              exactly the surfaces the server validates a color against. */}
          <div className="branding-preview">
            <div
              className="preview-header"
              style={{ borderTop: `3px solid ${HEX_RE.test(primary) ? primary : "#000000"}` }}
            >
              {hasLogo && (
                <img
                  className="preview-logo"
                  src={brandingLogoUrl()}
                  alt={copy.branding.logoAlt(displayName || copy.appName)}
                />
              )}
              <span
                className="preview-name"
                style={{ color: HEX_RE.test(primary) ? primary : "#1f2328" }}
              >
                {displayName || copy.appName}
              </span>
              <span
                style={{
                  color: HEX_RE.test(accent) ? accent : "#0b57d0",
                  textDecoration: "underline",
                }}
              >
                {copy.branding.previewSampleLink}
              </span>
              <span
                style={{
                  background: HEX_RE.test(accent) ? accent : "#0b57d0",
                  color: "#ffffff",
                  padding: "0.25rem 0.75rem",
                  borderRadius: "6px",
                }}
              >
                {copy.branding.previewSampleButton}
              </span>
            </div>
            <p className="preview-note">{copy.branding.previewChartNote}</p>
          </div>
        </section>

        <section className="card branding-section">
          <h2>{copy.branding.logoHeading}</h2>
          <p className="branding-hint" id={logoHintId}>
            {copy.branding.logoHint}
          </p>
          <p>{hasLogo ? copy.branding.logoPresent : copy.branding.logoNone}</p>
          <form onSubmit={submitLogo}>
            <label htmlFor={logoId}>{copy.branding.logoLabel}</label>
            <input
              id={logoId}
              type="file"
              accept="image/svg+xml,image/png"
              aria-describedby={logoHintId}
              onChange={(e) => setLogoFile(e.target.files?.[0] ?? null)}
            />
            <button type="submit" disabled={saving}>
              {copy.branding.uploadLogo}
            </button>
          </form>
        </section>
      </div>
    </>
  );
}
