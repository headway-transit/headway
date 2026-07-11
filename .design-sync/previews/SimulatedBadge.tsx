import { SimulatedBadge } from 'web';

/** The badge as it rides a figure computed from simulated test data. */
export const Standalone = () => <SimulatedBadge />;

/** In context: beside a metric value, the way the metrics table renders it. */
export const BesideAFigure = () => (
  <p style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0 }}>
    <strong>238,100</strong> unlinked passenger trips <SimulatedBadge />
  </p>
);
