import { TimeSeriesChart } from 'web';

/**
 * Daily UPT, single series in slot 1 (the card title names it — no legend
 * box). Displays are the API strings verbatim; y is geometry only. yMax is
 * pinned to 250000: the component's autoscale clamps values above its top
 * nice tick (238100 > 200000), which would flatten the line.
 */
export const DailyUpt = () => (
  <TimeSeriesChart
    series={[
      {
        id: 'upt',
        label: 'Unlinked Passenger Trips (UPT)',
        color: 'var(--series-1)',
        points: [
          { x: Date.parse('2026-07-05'), xLabel: '2026-07-05', display: '142387', y: 142387 },
          { x: Date.parse('2026-07-06'), xLabel: '2026-07-06', display: '224318', y: 224318 },
          { x: Date.parse('2026-07-07'), xLabel: '2026-07-07', display: '229947', y: 229947 },
          { x: Date.parse('2026-07-08'), xLabel: '2026-07-08', display: '233512', y: 233512 },
          { x: Date.parse('2026-07-09'), xLabel: '2026-07-09', display: '236774', y: 236774 },
          { x: Date.parse('2026-07-10'), xLabel: '2026-07-10', display: '238100', y: 238100 },
        ],
      },
    ]}
    ariaLabel="Unlinked passenger trips over time"
    unit="unlinked passenger trips"
    yMax={250000}
  />
);

/**
 * Coverage over time, the dashboard's percent-scale usage: two series on the
 * validated slots, yMax 100, and the certifiability threshold as a dashed
 * reference line. VRM clears the 90% threshold; VRH sits below it — the
 * reference line earning its keep.
 */
export const CoverageWithThreshold = () => (
  <TimeSeriesChart
    series={[
      {
        id: 'vrm-coverage',
        label: 'VRM coverage',
        color: 'var(--series-1)',
        points: [
          { x: Date.parse('2026-07-07'), xLabel: '2026-07-07', display: '91.48%', y: 91.48 },
          { x: Date.parse('2026-07-08'), xLabel: '2026-07-08', display: '90.72%', y: 90.72 },
          { x: Date.parse('2026-07-09'), xLabel: '2026-07-09', display: '92.63%', y: 92.63 },
          { x: Date.parse('2026-07-10'), xLabel: '2026-07-10', display: '93.05%', y: 93.05 },
        ],
      },
      {
        id: 'vrh-coverage',
        label: 'VRH coverage',
        color: 'var(--series-2)',
        points: [
          { x: Date.parse('2026-07-07'), xLabel: '2026-07-07', display: '84.91%', y: 84.91 },
          { x: Date.parse('2026-07-08'), xLabel: '2026-07-08', display: '85.63%', y: 85.63 },
          { x: Date.parse('2026-07-09'), xLabel: '2026-07-09', display: '85.10%', y: 85.1 },
          { x: Date.parse('2026-07-10'), xLabel: '2026-07-10', display: '85.72%', y: 85.72 },
        ],
      },
    ]}
    ariaLabel="Data coverage over time"
    unit="%"
    yMax={100}
    referenceLine={{ y: 90, label: 'Coverage threshold (90%)' }}
  />
);
