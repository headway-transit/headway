/**
 * The Demand Response mode/TOS badge (handoff 0013, design point 5): every
 * figure scoped `mode:DR` or `mode:DR:tos:<tos>` carries a badge naming the
 * mode and the type of service in plain language — the TOS selects the
 * revenue rule, so a DR figure must never look like a fleet figure.
 *
 * Renders nothing for any other scope. Text-only tags (info tokens, an
 * AA-verified pair) — the meaning is in the words, never color alone.
 */

import { copy } from "../copy";
import { drTosLabel, parseDrScope } from "../regulatory/drRules";

export function DrScopeBadge({ scope }: { scope: string }) {
  const dr = parseDrScope(scope);
  if (!dr) return null;
  return (
    <span className="dr-badges">
      <span className="tag dr-scope">{copy.dr.modeBadge}</span>{" "}
      <span className="tag dr-scope">
        {dr.tos === null ? copy.dr.allTosBadge : drTosLabel(dr.tos)}
      </span>
    </span>
  );
}
