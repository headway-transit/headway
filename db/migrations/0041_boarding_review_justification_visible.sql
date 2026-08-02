-- 0041: the required justification must be VISIBLE, not merely non-empty.
--
-- WHY
-- ---
-- Migration 0040 stated a guarantee in the schema: a boarding cannot be
-- classified without a written reason, because that reason travels into the
-- reported figure's receipt and is what lets an agency DEFEND a ridership
-- correction in a triennial review instead of merely asserting it.
--
-- An external adversarial review (2026-08-01, a different model family) broke
-- that guarantee. The 0040 CHECK reads:
--
--     length(btrim(justification)) > 0
--
-- PostgreSQL's one-argument btrim() removes the SPACE character only — not
-- tabs, not newlines, and not zero-width characters. The API's Python-side
-- guard used str.strip(), which removes tabs and newlines but treats U+200B
-- (zero-width space) as an ordinary printable character. So a justification
-- consisting solely of U+200B satisfied BOTH layers and landed a verdict with
-- an effectively blank reason — a receipt an auditor cannot read.
--
-- WHAT THIS DOES
-- --------------
-- Replaces the CHECK with one that strips the invisible codepoints as well as
-- ordinary whitespace, so "says something" means "a human can see something".
-- The API gained the matching guard (unicodedata categories Cf/Cc dropped
-- wholesale, so a future invisible codepoint cannot reopen the hole); this
-- migration is the layer that holds even for a writer that bypasses the API.
--
-- Existing rows: none can violate the new rule that did not already violate
-- the old one in spirit, but the constraint is added NOT VALID first and then
-- validated, so a pre-existing invisible-only note surfaces as a loud
-- validation failure rather than silently blocking the deploy.

ALTER TABLE dq.boarding_revenue_reviews
    DROP CONSTRAINT IF EXISTS boarding_review_justification_not_blank;

ALTER TABLE dq.boarding_revenue_reviews
    ADD CONSTRAINT boarding_review_justification_not_blank CHECK (
        justification IS NULL
        OR length(
            btrim(
                justification,
                -- space, tab, LF, CR, form feed, vertical tab
                E' \t\n\r\f\v'
                -- zero-width space / non-joiner / joiner, word joiner,
                -- zero-width no-break space (BOM), Mongolian vowel separator
                || E'​‌‍⁠﻿᠎'
                -- NBSP and friends: visually blank, not ASCII space
                || E'   '
            )
        ) > 0
    ) NOT VALID;

ALTER TABLE dq.boarding_revenue_reviews
    VALIDATE CONSTRAINT boarding_review_justification_not_blank;

COMMENT ON CONSTRAINT boarding_review_justification_not_blank
    ON dq.boarding_revenue_reviews IS
    'A classified boarding carries a reason a human can actually read: the '
    'note is trimmed of ordinary whitespace AND of zero-width/invisible '
    'characters before the non-empty test. Tightened by migration 0041 after '
    'an external review landed a verdict whose entire justification was a '
    'single zero-width space (handoff 0040).';
