# Building with the Headway design system

Headway is a transit-data platform whose UI thesis is **radical provenance**: every number can prove itself. Designs built with these components must keep that true.

## The five Headway rules (non-negotiable)

1. **Figures are verbatim strings.** A metric value (`"12794.92"`) is never parsed, rounded, reformatted, or recomputed in UI code. Render the string the data gives you. Percent display uses string decimal-shifting, never float math.
2. **Simulated data is always flagged.** Any figure whose provenance includes simulated sources renders with `<SimulatedBadge />` beside it. Never omit it.
3. **Severity is never color alone.** Use the chip pattern: `<span className="chip severity blocking"><SeverityIcon severity="blocking" /> Blocking</span>` (severities: `blocking`, `warning`, `info`).
4. **Chart colors come only from validated tokens**: series lines use `var(--series-1)` … `var(--series-8)`; status encodings use `var(--chart-status-blocking|warning|info)`. Brand colors (`--brand-primary`, `--brand-accent`) paint chrome (headers, accents) and must NEVER encode data.
5. **Every displayed figure offers a path to provenance** — pair values with `<Receipt value={…} />` (the expandable proof panel) or a link to its lineage.

## Wrapping and setup

Components that render links (`Receipt`, `LineageGraph`, `Layout`) need a router context. Wrap your design root once:

```jsx
import { DesignSyncProvider, Receipt } from 'web';

export default () => (
  <DesignSyncProvider>
    <Receipt value={{ metric: 'vrm', value: '12794.92', unit: 'miles',
      period_start: '2026-07-09', period_end: '2026-07-11',
      calc_name: 'vrm_v0', calc_version: '0.2.0',
      certification_status: 'certified',
      detail: { coverage: '0.9263', total_groups: 2742, excluded_groups: 202,
                gap_threshold_seconds: 300, coverage_threshold: '0.90' } }} />
  </DesignSyncProvider>
);
```

Without it, those components throw ("Cannot destructure 'basename'") and render nothing.

## Styling idiom: CSS custom properties + a small class vocabulary

Style with the shipped tokens (defined in `styles.css`; dark mode redefines them under `[data-theme="dark"]`):

| Family | Tokens |
|---|---|
| Surfaces & text | `--color-bg`, `--color-surface`, `--color-text`, `--color-text-muted`, `--color-border` |
| Accent & brand chrome | `--color-accent`, `--color-accent-text`, `--brand-primary`, `--brand-accent` |
| Status backgrounds/text | `--color-danger-bg/-text`, `--color-warning-bg/-text`, `--color-info-bg/-text`, `--color-success-bg/-text` |
| Charts (data encoding) | `--series-1`…`--series-8`, `--chart-status-blocking/warning/info`, `--chart-grid`, `--chart-baseline` |
| Shape & focus | `--radius-1`, `--radius-2`, `--shadow-1`, `--focus-ring` |

Reusable classes (real, from the shipped CSS): `card` (surface + elevation), `alert` (attention block), `chip severity <sev>` (status chips), `detail-panel`, `coverage-meter`, `app-header`, `brand`. Compose layout with your own flex/grid inline styles or new classes using the tokens above — never hard-coded hex for anything the tokens cover.

## Where the truth lives

Read `styles.css` (tokens + all component styles via its import) before inventing styling. Each component's `components/<group>/<Name>/<Name>.prompt.md` shows its verified usage; the `.d.ts` beside it is the props contract. Charts: `TimeSeriesChart` (one y-axis ALWAYS — never dual-axis; two measures = two charts), `SeverityStackedBar`, wrapped in `ChartCard` (which supplies the accessible table twin — always provide `table`).

Accessibility floor is WCAG 2.1 AA and it is part of the brand: keyboard paths, visible focus (`--focus-ring`), labeled controls, and plain language a transit operations manager understands.
