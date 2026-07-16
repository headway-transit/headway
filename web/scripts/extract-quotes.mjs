// Extracts the VERBATIM FTA manual quotes from
// services/calc/REGULATORY_TRACKER.md (every "## Verified …" section —
// "Verified definitions", S&S, MR-20, PMT, Sampling Manual, Demand Response)
// into src/regulatory/quotes.json, keyed by calc_name — AND, since handoff
// 0014, the ops-metric definitions from services/calc/OPS_DEFINITIONS.md
// under NAMESPACED "ops:<calc_name>" keys in the SAME artifact.
//
// The tracker is the NTD/Compliance Engineer's durable memory: every quote in
// it was verified against the published FTA NTD Policy Manual, with a page
// citation. This script COPIES those quotes character-for-character (the text
// between the double quotation marks is never edited, paraphrased, or
// generated) so the UI can show "the FTA rule inside the number"
// (handoff 0007, pillar 1). Wrapped source lines are re-joined with a single
// space — the only transformation applied.
//
// OPS NAMESPACING (handoff 0014, design point 5 — the design choice,
// documented): operations metrics (otp_v0, headway_adherence_v0) cite an
// INDUSTRY basis (TCQSM) or an explicitly Headway-owned definition, never an
// FTA manual — mixing them into the FTA calc_name namespace would let an ops
// figure masquerade as federally defined. They ship in the same quotes.json
// file, but under "ops:"-prefixed keys with their own shape
// ({verified: [{quote, citation}], headway_owned: [{name, version, summary,
// formula, reference}]}), because the CI drift gate regenerates and diffs
// exactly this one file (ci.yml "drift gates") — a parallel opsQuotes.json
// would sit OUTSIDE that gate and could drift silently. The prefix keeps the
// FTA namespace unmixed (src/regulatory/quotes.ts filters "ops:" keys out of
// the FTA lookup; src/regulatory/opsQuotes.ts is the only reader of the ops
// keys), and the loud-fallback discipline is identical: a missing section, an
// unmappable heading, or an ops calc without both its verified quote and its
// Headway-owned definitions is a hard extraction failure, never silence.
//
// The ONLY transformations applied to OPS_DEFINITIONS.md text:
//   - hard-wrapped lines re-joined with a single space (as for the tracker);
//   - "**" markdown emphasis pairs removed (styling, not content);
//   - CITATIONS ONLY (never quote text): the markdown "*…*" italics around
//     the manual title are dropped, "ibid." is expanded to the section's
//     already-named manual title, "\_" unescapes to "_", and the trailing
//     "Fetched and verified …" provenance sentence is cut (it documents the
//     verification, it is not part of the page citation).
//
// FAIL LOUDLY: the script exits non-zero (and therefore fails any build that
// runs it) if no "## Verified …" section is found, if one cannot be mapped
// to calc names, or if any calc_name in the tracker's table ends up with no
// quotes. Shipping silence instead of the rule is not an option.
//
// Run: npm run extract:quotes   (from web/)

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const trackerPath = join(
  here,
  "..",
  "..",
  "services",
  "calc",
  "REGULATORY_TRACKER.md",
);
const opsPath = join(here, "..", "..", "services", "calc", "OPS_DEFINITIONS.md");
const outPath = join(here, "..", "src", "regulatory", "quotes.json");

/**
 * Section-heading → calc_name mapping — the ONE list a quote section needs
 * an entry in (its sibling, the old isQuoteSection allowlist, converged into
 * the generic "## Verified" sweep below; 2026-07-13 hardening pass).
 *
 * The GENERIC parser comes first: a heading that names its calc(s) inline
 * ("calc upt_v0", the UPT section's convention) maps with ZERO configuration
 * — future "## Verified …" sections that follow it need no edit here. The
 * explicit mappings below cover today's headings that predate that
 * convention. A "## Verified" heading that matches neither is a hard error —
 * a new section is mapped deliberately, never guessed.
 */
function calcNamesForHeading(heading) {
  const named = [...heading.matchAll(/calc\s+([a-z0-9_]+)/gi)].map(
    (m) => m[1],
  );
  if (named.length > 0) return named;
  // Plural form: "(calcs a_v0 / b_v0 / c_v0, …)" — one section backing
  // several calc versions (first used by handoff 0020's day-type family).
  const plural = heading.match(/calcs\s+([a-z0-9_]+(?:\s*\/\s*[a-z0-9_]+)+)/i);
  if (plural) return plural[1].split("/").map((n) => n.trim());
  if (heading.includes("FTA NTD Policy Manual")) return ["vrm_v0", "vrh_v0"];
  // The S&S section backs the Safety & Security classifier (handoff 0010,
  // design point 2: services/calc sscls_v0) and the /safety UI's receipts.
  if (heading.startsWith("Verified — Safety & Security reporting")) {
    return ["sscls_v0"];
  }
  // The MR-20 section holds the verified Monthly VOMS quote (handoff 0009
  // added voms_v0 to the tracker table with its rule verified here, not in
  // a "Verified definitions" section).
  if (heading.startsWith("Verified — Monthly Ridership form MR-20")) {
    return ["voms_v0"];
  }
  // The PMT section backs pmt_v0 (handoff 0011): the p. 145 definition, the
  // p. 146 missing-trip rule, the pp. 151-152 validity/discard discipline
  // and the Exhibit 44 average-trip-length method its estimator implements.
  if (heading.startsWith("Verified — Passenger Miles Traveled")) {
    return ["pmt_v0"];
  }
  // The NTD Sampling Manual section backs sampling_v0 (handoff 0012): the
  // §41.01 eligibility quote, the §63.03 random/without-replacement rules,
  // and the §83.05(b) ratio-of-totals ban the /sampling UI's receipts show.
  if (heading.startsWith("Verified — NTD Sampling Manual")) {
    return ["sampling_v0"];
  }
  // The Demand Response section backs all five DR calcs (handoff 0013):
  // the p. 129 revenue-time + TX onboard-only rules, the p. 130 deadhead /
  // no-deadhead-TOS rules, the Exhibit 36 no-show row, the Exhibits 38+40
  // atypical-day-inclusion VOMS rule, and the pp. 143–144 UPT rules — the
  // quotes the DR-scoped receipts and their TOS callouts show.
  if (heading.startsWith("Verified — Demand Response / on-demand reporting")) {
    return ["dr_pmt_v0", "dr_upt_v0", "dr_voms_v0", "dr_vrh_v0", "dr_vrm_v0"];
  }
  return null;
}

function fail(message) {
  console.error(`extract-quotes: FAILED — ${message}`);
  process.exit(1);
}

const tracker = readFileSync(trackerPath, "utf8");
const lines = tracker.split("\n");

// Every calc_name in the tracker's table MUST end up with at least one quote.
const tableCalcNames = new Set();
for (const line of lines) {
  const m = /^\|\s*([a-z0-9_]+)\s*\|\s*\d+\.\d+\.\d+\s*\|/.exec(line);
  if (m) tableCalcNames.add(m[1]);
}
if (tableCalcNames.size === 0) {
  fail(`no calc rows found in the tracker table (${trackerPath})`);
}

// Slice the file into quote-bearing sections: every "## Verified …" section
// (the tracker's own convention — a heading starting "## Verified" carries
// verified quotes; verified against today's tracker, this sweeps exactly the
// seven quote sections and none of "## Divergence analysis", "## Mode
// scoping", or "## Open verification items"). This replaced a heading
// allowlist that had to be grown in lockstep with calcNamesForHeading; the
// mapping there is now the single per-section list, and it still fails hard
// on any swept heading it cannot map.
function isQuoteSection(line) {
  return line.startsWith("## Verified");
}
const sections = [];
let current = null;
for (const line of lines) {
  if (line.startsWith("## ")) {
    if (current) sections.push(current);
    current = isQuoteSection(line)
      ? { heading: line.slice(3).trim(), body: [] }
      : null;
    continue;
  }
  if (current) current.body.push(line);
}
if (current) sections.push(current);
if (sections.length === 0) {
  fail(`no "## Verified …" section found in ${trackerPath}`);
}

const quotesByCalc = {};

for (const section of sections) {
  const calcNames = calcNamesForHeading(section.heading);
  if (!calcNames) {
    fail(
      `cannot map section "${section.heading}" to calc names — ` +
        "add an explicit mapping in scripts/extract-quotes.mjs",
    );
  }

  // The manual's name, from the section's first "Source: **…**" line (every
  // top-level section bolds its manual name — the tracker's convention; the
  // last unbolded holdout, the DR section, was bolded 2026-07-13 and the
  // fallback shape this used to accept retired with it). Sub-source lines
  // deeper in a section (the S&S addenda) are unbolded and deliberately not
  // matched: the section's manual name is the citation's.
  const bodyText = section.body.join("\n");
  const sourceMatch = /Source:\s+\*\*([^*]+)\*\*/.exec(bodyText);
  if (!sourceMatch) {
    fail(`section "${section.heading}" has no "Source: **…**" line`);
  }
  const manualName = sourceMatch[1].trim().replace(/\s+/g, " ");

  // Collect bullets, re-joining hard-wrapped continuation lines with one
  // space (the ONLY transformation ever applied to the tracker's text).
  const bullets = [];
  for (const line of section.body) {
    if (/^- /.test(line)) {
      bullets.push(line.slice(2).trim());
    } else if (bullets.length > 0 && /^\s+\S/.test(line)) {
      bullets[bullets.length - 1] += ` ${line.trim()}`;
    } else if (line.trim() === "") {
      // blank line ends the current bullet's continuation
      if (bullets.length > 0) bullets.push(null);
    }
  }

  const entries = [];
  for (const bullet of bullets) {
    if (bullet === null) continue;
    // Three labeled-bullet shapes exist in the tracker:
    //   **Label** (page reference): …quotes…        (Verified definitions)
    //   **Label(sub-refs) (p. N), note:** …         (implementation quotes —
    //     the label may carry parenthesized sub-refs like "§83.01(a)/(b)",
    //     so a "(p. N)"/"(pp. N)" group inside the bold head is preferred
    //     as the page reference over the first parenthesized group)
    //   **Label (page reference)[ — trailing note]:** …   (S&S sections)
    const head =
      /^\*\*(.+?)\*\*\s*\(([^)]+)\)/.exec(bullet) ??
      /^\*\*([^*]+?)\s*\((pp?\.\s?[^()]+)\)[^*]*\*\*/.exec(bullet) ??
      /^\*\*(.+?)\s*\(([^()]+)\)[^*]*\*\*/.exec(bullet);
    if (!head) continue; // not a labeled quote bullet
    const label = head[1];
    const pageRef = head[2]; // verbatim, e.g. "p. 128" or "pp. 147–148"
    // Tracker meta-commentary after "NOTE:" (verification-method lessons) is
    // ABOUT the manual's wording, not manual text — quoted words inside it
    // (e.g. a spelling that greps to zero hits) must never ship as verified
    // quotes, so the quotable text stops there.
    // TRAP (2026-07-13 review): this guard truncates at the FIRST "NOTE:" —
    // a future VERBATIM manual quote that itself contains "NOTE:" would be
    // silently cut short here. If the manual ever hands the tracker such a
    // quote, this guard needs a smarter boundary (e.g. only a "NOTE:" outside
    // the double quotation marks) before that bullet lands.
    const quotable = bullet.split("NOTE:")[0];
    // Every double-quoted segment in the bullet is a verbatim manual quote;
    // the inner text is copied EXACTLY — the only in-quote cleanup is
    // removing "**" pairs, which are the tracker's own markdown emphasis
    // (styling around the manual's words, not part of them).
    for (const m of quotable.matchAll(/"([^"]+)"/g)) {
      entries.push({
        quote: m[1].replaceAll("**", ""),
        citation: `${label} — ${manualName}, ${pageRef}`,
      });
    }
  }

  if (entries.length === 0) {
    fail(`section "${section.heading}" yielded no quotes — refusing to ship silence`);
  }

  for (const calcName of calcNames) {
    quotesByCalc[calcName] = (quotesByCalc[calcName] ?? []).concat(entries);
  }
}

// The loud gate: every calc named in the tracker table has at least 1 quote.
const missing = [...tableCalcNames].filter(
  (name) => !(quotesByCalc[name]?.length > 0),
);
if (missing.length > 0) {
  fail(
    `calc(s) named in the tracker table have no verified quotes: ` +
      `${missing.join(", ")} — a figure without its rule must not ship`,
  );
}

// ---------------------------------------------------------------------------
// OPS_DEFINITIONS.md (handoff 0014): the operations-metric analogue, under
// the same quote-or-own-it discipline. "## Verified — …" sections carry
// verbatim TCQSM quotes as markdown blockquotes (`> "…"`), each group
// followed by an em-dash citation paragraph; "## Headway operational
// definition — <name> <version>" sections are OUR definitions: extracted as
// name + version + first paragraph (the owner/lead-in sentence) + the first
// fenced formula block, and labeled as Headway-owned by the consumer — the
// receipt must never let them read as federal or industry rules.
// ---------------------------------------------------------------------------

/** The ops calcs whose figures the UI serves; each MUST end up complete. */
const OPS_CALCS = ["otp_v0", "headway_adherence_v0"];
const OPS_REFERENCE = "services/calc/OPS_DEFINITIONS.md";

/** Map an OPS_DEFINITIONS "## Verified — …" heading to calc names —
 *  explicit, like the tracker's mapping; an unmapped heading is a hard
 *  error, never a guess. */
function opsCalcsForVerifiedHeading(heading) {
  if (heading.includes("on-time performance window")) return ["otp_v0"];
  if (heading.includes("headway adherence")) return ["headway_adherence_v0"];
  return null;
}

const opsSource = readFileSync(opsPath, "utf8");
const opsLines = opsSource.split("\n");

// Slice into sections on "## " headings.
const opsSections = [];
let opsCurrent = null;
for (const line of opsLines) {
  if (line.startsWith("## ")) {
    if (opsCurrent) opsSections.push(opsCurrent);
    opsCurrent = { heading: line.slice(3).trim(), body: [] };
    continue;
  }
  if (opsCurrent) opsCurrent.body.push(line);
}
if (opsCurrent) opsSections.push(opsCurrent);
if (opsSections.length === 0) {
  fail(`no "## …" sections found in ${opsPath}`);
}

/**
 * The manual title from the section's FIRST full citation ("— *Title*
 * (publisher)"), remembered so a later "ibid." citation can name its manual
 * when displayed standalone on a receipt. Citation-only transformation.
 */
let opsManualTitle = null;

/** Normalize one citation paragraph (see the header's citation rules). */
function opsCitation(paragraph) {
  let text = paragraph.replace(/^—\s*/, "").replace(/\\_/g, "_");
  // Cut the verification-provenance sentence and anything after it — it
  // documents HOW the quote was verified, not WHERE the rule lives.
  const fetched = text.indexOf(" Fetched and verified");
  if (fetched >= 0) text = text.slice(0, fetched).trim();
  const titleMatch = /^\*([^*]+)\*\s*(\([^)]*\))?/.exec(text);
  if (titleMatch) {
    opsManualTitle = `${titleMatch[1]}${titleMatch[2] ? ` ${titleMatch[2]}` : ""}`;
    text = `${opsManualTitle}${text.slice(titleMatch[0].length)}`;
  } else if (/^ibid\.?/.test(text)) {
    if (!opsManualTitle) {
      fail(`"ibid." citation before any titled citation in ${opsPath}`);
    }
    text = text.replace(/^ibid\.?/, opsManualTitle);
  }
  return text.replaceAll("**", "").trim();
}

/** {verified: [...], headway_owned: [...]} per ops calc name. */
const opsByCalc = Object.fromEntries(
  OPS_CALCS.map((c) => [c, { verified: [], headway_owned: [] }]),
);

for (const section of opsSections) {
  if (section.heading.startsWith("Verified — ")) {
    const calcs = opsCalcsForVerifiedHeading(section.heading);
    if (!calcs) {
      fail(
        `cannot map OPS_DEFINITIONS section "${section.heading}" to calc ` +
          "names — add an explicit mapping in scripts/extract-quotes.mjs",
      );
    }
    // Walk the body: consecutive "> " lines form one blockquote; pending
    // blockquotes flush against the next "— …" citation paragraph (two
    // quotes may share one citation, as on p. 5-92).
    const entries = [];
    let pendingQuotes = [];
    let quoteLines = [];
    let citationLines = [];
    const flushQuote = () => {
      if (quoteLines.length === 0) return;
      const joined = quoteLines.join(" ").replace(/\s+/g, " ").trim();
      const m = /^"([\s\S]+)"$/.exec(joined);
      if (!m) {
        fail(
          `blockquote in "${section.heading}" is not a double-quoted ` +
            `verbatim quote: ${joined.slice(0, 80)}…`,
        );
      }
      pendingQuotes.push(m[1]);
      quoteLines = [];
    };
    const flushCitation = () => {
      if (citationLines.length === 0) return;
      const citation = opsCitation(
        citationLines.join(" ").replace(/\s+/g, " ").trim(),
      );
      for (const quote of pendingQuotes) entries.push({ quote, citation });
      pendingQuotes = [];
      citationLines = [];
    };
    for (const line of section.body) {
      if (line.startsWith(">")) {
        quoteLines.push(line.replace(/^>\s?/, "").trim());
      } else if (line.trim() === "") {
        flushQuote();
        flushCitation();
      } else if (line.startsWith("— ") || citationLines.length > 0) {
        flushQuote();
        citationLines.push(line.trim());
      }
    }
    flushQuote();
    flushCitation();
    if (entries.length === 0) {
      fail(
        `OPS_DEFINITIONS section "${section.heading}" yielded no quotes — ` +
          "refusing to ship silence",
      );
    }
    for (const calc of calcs) opsByCalc[calc].verified.push(...entries);
  } else if (section.heading.startsWith("Headway operational definition — ")) {
    const nameMatch = /—\s+([a-z0-9_]+)\s+(\d+\.\d+\.\d+)/.exec(
      section.heading,
    );
    if (!nameMatch) {
      fail(
        `cannot parse name/version from OPS_DEFINITIONS heading ` +
          `"${section.heading}"`,
      );
    }
    const [, name, version] = nameMatch;
    // First paragraph (the owner / lead-in sentence), wrap-joined.
    const paragraphLines = [];
    let inFence = false;
    const formulaLines = [];
    let formulaDone = false;
    let paragraphDone = false;
    for (const line of section.body) {
      if (line.startsWith("```")) {
        if (inFence) formulaDone = true;
        inFence = !inFence && !formulaDone;
        paragraphDone = true;
        continue;
      }
      if (inFence) {
        formulaLines.push(line);
        continue;
      }
      if (!paragraphDone) {
        if (line.trim() === "") {
          if (paragraphLines.length > 0) paragraphDone = true;
        } else {
          paragraphLines.push(line.trim());
        }
      }
    }
    const definition = {
      name,
      version,
      summary: paragraphLines.join(" ").replaceAll("**", "").trim(),
      formula: formulaLines.length > 0 ? formulaLines.join("\n") : null,
      reference: OPS_REFERENCE,
    };
    if (definition.summary.length === 0) {
      fail(`Headway-owned section "${section.heading}" has no lead paragraph`);
    }
    // The passage derivation underlies EVERY ops figure (its version rides
    // in each figure's detail.derivation), so it attaches to all ops calcs;
    // a calc's own section attaches to that calc alone.
    const targets = OPS_CALCS.includes(name) ? [name] : OPS_CALCS;
    for (const calc of targets) opsByCalc[calc].headway_owned.push(definition);
  }
  // Other sections ("Prediction data — …", the file preamble) carry no
  // quotes and no owned definitions for the UI — deliberately skipped.
}

// The loud ops gate: each ops calc must carry at least one verified quote,
// its OWN Headway-owned definition, and the shared derivation definition.
for (const calc of OPS_CALCS) {
  const bundle = opsByCalc[calc];
  if (bundle.verified.length === 0) {
    fail(
      `ops calc "${calc}" has no verified industry quote in ${opsPath} — ` +
        "an ops figure must never ship without its basis",
    );
  }
  if (!bundle.headway_owned.some((d) => d.name === calc)) {
    fail(`ops calc "${calc}" has no Headway-owned definition in ${opsPath}`);
  }
  if (!bundle.headway_owned.some((d) => d.name === "derive_stop_passages")) {
    fail(
      `ops calc "${calc}" is missing the derive_stop_passages definition — ` +
        "the derivation behind every ops figure must ship with it",
    );
  }
  // The calc's own definition leads; the shared derivation follows.
  bundle.headway_owned.sort((a, b) =>
    a.name === calc ? -1 : b.name === calc ? 1 : 0,
  );
  quotesByCalc[`ops:${calc}`] = bundle;
}

const sorted = Object.fromEntries(
  Object.keys(quotesByCalc)
    .sort()
    .map((k) => [k, quotesByCalc[k]]),
);

mkdirSync(dirname(outPath), { recursive: true });
writeFileSync(outPath, `${JSON.stringify(sorted, null, 2)}\n`);

const counts = Object.entries(sorted)
  .map(([k, v]) =>
    Array.isArray(v)
      ? `${k}: ${v.length}`
      : `${k}: ${v.verified.length} verified + ${v.headway_owned.length} owned`,
  )
  .join(", ");
console.log(`extract-quotes: wrote ${outPath} (${counts})`);
