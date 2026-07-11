import { SeverityStackedBar } from 'web';

const LEGEND = [
  { severity: 'blocking', label: 'Blocking', color: 'var(--chart-status-blocking)' },
  { severity: 'warning', label: 'Warning', color: 'var(--chart-status-warning)' },
  { severity: 'info', label: 'Info', color: 'var(--chart-status-info)' },
];

const seg = (severity: string, label: string, count: number) => ({
  severity,
  label,
  count,
  displayCount: count.toLocaleString('en-US'),
  color: `var(--chart-status-${severity})`,
});

/**
 * The dashboard's DQ card data shape: unresolved issue tallies by workflow
 * status (Open / Owned) and severity — 4 blocking, 8,824 warning, 1,157 info
 * across the queue. Status colors ride with icon + label in the legend.
 */
export const UnresolvedQueue = () => (
  <SeverityStackedBar
    bars={[
      {
        key: 'open',
        label: 'Open',
        segments: [
          seg('blocking', 'Blocking', 3),
          seg('warning', 'Warning', 5210),
          seg('info', 'Info', 704),
        ],
        displayTotal: '5,917',
      },
      {
        key: 'owned',
        label: 'Owned',
        segments: [
          seg('blocking', 'Blocking', 1),
          seg('warning', 'Warning', 3614),
          seg('info', 'Info', 453),
        ],
        displayTotal: '4,068',
      },
    ]}
    legend={LEGEND}
  />
);
