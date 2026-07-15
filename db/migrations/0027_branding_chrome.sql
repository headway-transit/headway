-- 0027: themed nav chrome — branding v2 (handoff 0017, design point 7).
--
-- Extends the audited branding surface (migration 0015, handoff 0008 pillar
-- C) from logo + two brand colors to nav-chrome theming: the app shell's
-- header background, the text/icon color that sits on it, and the active-
-- accent used for the current nav item on that same header. Like every
-- settings key these are SEEDED, never client-creatable; only the
-- certifying official may change them, and every change is audited old→new.
--
-- THE GUARDRAIL (binding, same math as 0015): the server computes WCAG 2.1
-- contrast ratios on every change and refuses (plain-language 422 naming the
-- failing pair and the measured ratio) any CHROME PAIR under 4.5:1 (WCAG 2.1
-- AA, SC 1.4.3). Chrome pairs are validated against EACH OTHER — the header
-- foreground on the header background, and the active accent on the header
-- background — because chrome colors sit on the agency's own header, not on
-- the app's light surfaces. The pairwise check runs against the values that
-- WOULD result from the change, so no sequence of single-key updates can
-- reach an unreadable header. Formula source and constants:
-- services/api/headway_api/branding.py (verified against the published W3C
-- spec). You can theme it; you cannot theme it inaccessible.
--
-- DEFAULT IS NEUTRAL HEADWAY: all three keys seed as 'unset'. The theme
-- applies ONLY when all three are set (GET /branding serves chrome=null
-- otherwise), and setting any key back to 'unset' returns the shell to the
-- neutral chrome. Per-mode (light/dark) variants remain the KNOWN STANDING
-- LIMITATION from handoff 0008 (one color set; a theme that fails in dark
-- mode simply does not apply there — stated by the frontend, never silent);
-- this migration does not attempt dark variants.

INSERT INTO app.settings (setting_key, setting_value, value_type, description, updated_by) VALUES
('brand_chrome_header_bg', 'unset', 'text', 'Themed chrome (branding v2): the app-shell header/nav background color as a six-digit ''#rrggbb'' hex value, or ''unset'' (the default) for the neutral Headway chrome. GUARDRAIL: the chrome theme is refused unless the header foreground measures at least 4.5:1 (WCAG 2.1 AA) against this background AND the active accent measures at least 4.5:1 against it, computed server-side on every change against the values that would result. The theme applies only when all three brand_chrome_* keys are set.', 'migration-0027'),
('brand_chrome_header_fg', 'unset', 'text', 'Themed chrome (branding v2): the text and icon color that sits on the themed header background, as a six-digit ''#rrggbb'' hex value, or ''unset'' (the default). GUARDRAIL: refused unless it measures at least 4.5:1 (WCAG 2.1 AA) against brand_chrome_header_bg, computed server-side on every change. The theme applies only when all three brand_chrome_* keys are set.', 'migration-0027'),
('brand_chrome_accent', 'unset', 'text', 'Themed chrome (branding v2): the active-accent color marking the current nav item on the themed header, as a six-digit ''#rrggbb'' hex value, or ''unset'' (the default). GUARDRAIL: refused unless it measures at least 4.5:1 (WCAG 2.1 AA) against brand_chrome_header_bg, computed server-side on every change (the accent carries the active item''s label). The theme applies only when all three brand_chrome_* keys are set.', 'migration-0027');
