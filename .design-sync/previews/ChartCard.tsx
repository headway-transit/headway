import { ChartCard, TimeSeriesChart } from 'web';

const uptPoints = [
  { x: Date.parse('2026-07-05'), xLabel: '2026-07-05', display: '142387', y: 142387 },
  { x: Date.parse('2026-07-06'), xLabel: '2026-07-06', display: '224318', y: 224318 },
  { x: Date.parse('2026-07-07'), xLabel: '2026-07-07', display: '229947', y: 229947 },
  { x: Date.parse('2026-07-08'), xLabel: '2026-07-08', display: '233512', y: 233512 },
  { x: Date.parse('2026-07-09'), xLabel: '2026-07-09', display: '236774', y: 236774 },
  { x: Date.parse('2026-07-10'), xLabel: '2026-07-10', display: '238100', y: 238100 },
];

/**
 * The dashboard's real usage: card frame (heading, description, keyboard
 * hint, chart/table toggle) around a single-series TimeSeriesChart, with the
 * accessible table twin listing every charted value verbatim.
 */
export const UptOverTime = () => (
  <ChartCard
    heading="Unlinked passenger trips over time"
    description="One point per reporting period, exactly as computed by the UPT calculation."
    hint="Use the left and right arrow keys to read each point; the table view lists every value."
    table={{
      caption: 'Unlinked passenger trips per reporting period, exactly as computed.',
      columns: ['Period', 'Value', 'Unit'],
      rows: uptPoints.map((p) => [
        p.xLabel,
        <span className="figure" key="v">{p.display}</span>,
        'unlinked passenger trips',
      ]),
    }}
  >
    <TimeSeriesChart
      series={[
        {
          id: 'upt',
          label: 'Unlinked Passenger Trips (UPT)',
          color: 'var(--series-1)',
          points: uptPoints,
        },
      ]}
      ariaLabel="Unlinked passenger trips over time"
      unit="unlinked passenger trips"
      yMax={250000}
    />
  </ChartCard>
);
