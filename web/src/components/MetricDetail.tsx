/**
 * Renders a figure's calculation detail as plain-language sentences.
 * All translation logic lives in src/detail.ts (wording only — every number
 * shown is the API's value verbatim; unknown keys are shown, never hidden).
 */

import { copy } from "../copy";
import { detailLines } from "../detail";
import type { Detail } from "../detail";

interface MetricDetailPanelProps {
  detail: Detail;
  /** Accessible name for the list, e.g. "Calculation details for UPT, …". */
  label: string;
}

export function MetricDetailPanel({ detail, label }: MetricDetailPanelProps) {
  const lines = detailLines(detail);
  if (lines.length === 0) {
    return <p className="detail-panel">{copy.metrics.detailEmpty}</p>;
  }
  return (
    <ul className="detail-panel" aria-label={label}>
      {lines.map((line) => (
        <li key={line}>{line}</li>
      ))}
    </ul>
  );
}
