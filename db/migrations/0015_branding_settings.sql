-- 0015: agency branding settings (handoff 0008, pillar C). Like 0014, these
-- keys are SEEDED, never client-creatable — the settings surface exposes
-- exactly the branding knobs the product defines, so an unknown key stays a
-- 404 at the API.
--
-- THE GUARDRAIL (binding, handoff 0008): agencies set their own brand colors,
-- but colors that fail accessibility contrast are refused. On every change the
-- API computes the WCAG 2.1 contrast ratio server-side and refuses (a
-- plain-language 422 naming the failing surface and the measured ratio) any
-- color under 4.5:1 (WCAG 2.1 AA, SC 1.4.3) against either app surface:
-- the #ffffff page background (--color-bg) or the #f6f8fa raised card surface
-- (--color-surface), both cited from web/src/styles.css :root tokens. The
-- formula source and constants are documented in
-- services/api/headway_api/branding.py, verified against the published W3C
-- spec. You can brand it; you cannot brand it inaccessible.

INSERT INTO app.settings (setting_key, setting_value, value_type, description, updated_by) VALUES
('agency_display_name', 'Transit Agency', 'text', 'The agency''s display name, shown in the application header and on public pages. Plain text, shown exactly as entered. Default is a neutral placeholder until the agency sets its own.', 'migration-0015'),
('brand_color_primary', '#1a5fb4', 'text', 'The agency''s primary brand color, a six-digit ''#rrggbb'' hex value used by the app shell (headers, primary actions). GUARDRAIL: colors that fail accessibility contrast are refused — a new value must measure at least 4.5:1 (WCAG 2.1 AA) against both the #ffffff page background and the #f6f8fa card surface, computed server-side on every change. The default #1a5fb4 measures 6.29:1 and 5.91:1. Charts never use brand colors (their palette is validated separately).', 'migration-0015'),
('brand_color_accent', '#0b57d0', 'text', 'The agency''s accent brand color, a six-digit ''#rrggbb'' hex value used by the app shell (links, highlights). GUARDRAIL: colors that fail accessibility contrast are refused — a new value must measure at least 4.5:1 (WCAG 2.1 AA) against both the #ffffff page background and the #f6f8fa card surface, computed server-side on every change. The default #0b57d0 is the base design-token accent (web/src/styles.css) and measures 6.39:1 and 6.00:1.', 'migration-0015'),
('brand_logo_meta', 'unset', 'text', 'Maintained by Headway, not edited directly: the content type of the agency logo uploaded via POST /branding/logo (image/svg+xml or image/png), or ''unset'' when no logo has been uploaded. The logo bytes live in the object store at branding/logo.', 'migration-0015');
