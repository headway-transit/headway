/**
 * The dashboard Mode selector (handoff 0041, design points 1–4).
 *
 * It sits in the same control deck as the Audience lens and "Group trends
 * by" — one honest place, nothing behind a fly-out (a fly-out hides state)
 * and nothing in a separate sub-menu (a sub-menu splits the navigation).
 *
 * - **Data-driven:** the options come from `modeOptions(rows)` — the
 *   distinct `mode:*` scopes that actually carry persisted figures — plus
 *   "All modes (agency)" as the default. Nothing here knows the name of a
 *   single mode.
 * - **Shape follows count:** a segmented `aria-pressed` group up to
 *   MODE_SEGMENT_MAX modes (the existing filter-bar pattern), a listbox
 *   dropdown above it (react-aria-components `Select`, so keyboard and
 *   screen-reader semantics come from the library, not from hand-rolled
 *   ARIA).
 * - **The scope receipt:** the persisted scope string is shown verbatim in
 *   monospace beneath the control. What you selected and what the rows were
 *   filtered on are the same string, on screen, always.
 */

import {
  Button,
  Label,
  ListBox,
  ListBoxItem,
  Popover,
  Select,
  SelectValue,
} from "react-aria-components";
import { copy } from "../copy";
import { Disclosure } from "./Disclosure";
import {
  AGENCY_SCOPE,
  MODE_SEGMENT_MAX,
  isAgencyScope,
} from "../reports/modes";
import type { ModeOption } from "../reports/modes";

export interface ModeBarProps {
  /** Mode scopes with persisted figures — never a hardcoded catalogue. */
  options: ModeOption[];
  /** The selected scope string (the filter itself). */
  scope: string;
  onScope: (scope: string) => void;
}

export function ModeBar({ options, scope, onScope }: ModeBarProps) {
  const t = copy.dashboard.mode;
  const all: ModeOption[] = [
    { scope: AGENCY_SCOPE, label: t.allModes },
    ...options,
  ];
  const selected = all.find((o) => o.scope === scope) ?? all[0];
  const useDropdown = options.length > MODE_SEGMENT_MAX;

  return (
    <section aria-label={t.rowLabel} className="mode-bar">
      <div className="chart-filters">
        {useDropdown ? (
          <Select
            className="mode-select"
            selectedKey={scope}
            onSelectionChange={(key) => onScope(String(key))}
          >
            <Label className="filter-bar-label">{t.rowLabel}</Label>
            <Button className="mode-select-button">
              <SelectValue />
              <span aria-hidden="true" className="mode-select-arrow">
                ▾
              </span>
            </Button>
            <Popover className="mode-popover">
              <ListBox className="mode-listbox">
                {all.map((option) => (
                  <ListBoxItem
                    key={option.scope}
                    id={option.scope}
                    className="mode-option"
                    textValue={option.label}
                  >
                    <span className="mode-option-label">{option.label}</span>
                    <span className="mode-option-scope">{option.scope}</span>
                  </ListBoxItem>
                ))}
              </ListBox>
            </Popover>
          </Select>
        ) : (
          <div className="filter-bar seg" role="group" aria-label={t.rowLabel}>
            <span className="filter-bar-label">{t.rowLabel}:</span>
            {all.map((option) => (
              <button
                key={option.scope}
                type="button"
                aria-pressed={scope === option.scope}
                onClick={() => onScope(option.scope)}
              >
                {option.label}
              </button>
            ))}
          </div>
        )}
      </div>
      {/* HANDOFF 0044, OUTPUT 5 — what stays visible here, and why.
          The scope receipt, "this is not a total this page added up", and
          "only modes that already have figures are listed" are ADMISSIONS:
          each states what these figures are NOT. None of them may fold.
          Only `intro` — an explanation of how the control behaves — moves
          into the disclosure, verbatim and unshortened. */}
      <p className="mode-scope-receipt">
        <span className="mono">{t.scopeReceipt(selected.scope)}</span>
      </p>
      <p className="admission">
        {isAgencyScope(scope)
          ? t.agencyNote
          : t.selectedNote(selected.label, selected.scope)}
      </p>
      <p className="admission">{t.dataDrivenNote}</p>
      <Disclosure label={copy.disclosure.how}>
        <p>{t.intro}</p>
      </Disclosure>
    </section>
  );
}
