import { Receipt } from 'web';

/** A real certified figure: coverage, exclusions, and the FTA rule inside the number. */
export const CertifiedVrm = () => (
  <Receipt
    value={{
      metric: 'vrm', value: '12794.92', unit: 'miles',
      period_start: '2026-07-09', period_end: '2026-07-11',
      calc_name: 'vrm_v0', calc_version: '0.2.0',
      certification_status: 'certified', metric_value_id: 'b3ebdef6-demo',
      detail: {
        coverage: '0.9263', total_groups: 2742, excluded_groups: 202,
        clean_position_share: '0.8938', gap_threshold_seconds: 300,
        coverage_threshold: '0.90',
      },
    }}
  />
);

/** A factored UPT figure from simulated data — the badge and the FTA factor both visible. */
export const SimulatedUpt = () => (
  <Receipt
    value={{
      metric: 'upt', value: '238100', unit: 'unlinked_passenger_trips',
      period_start: '2026-07-09', period_end: '2026-07-10',
      calc_name: 'upt_v0', calc_version: '0.1.0',
      certification_status: 'uncertified', metric_value_id: 'bd22d723-demo',
      detail: {
        total_boardings_counted: 235725, operated_trips: 9123, missing_trips: 91,
        missing_share: '0.0100', factor_applied: '1.010075', missing_trip_threshold: '0.02',
        source_mix: { tides_simulated: 111568 },
      },
    }}
  />
);

/** Minimal detail: the receipt degrades honestly when a calc ships no coverage machinery. */
export const MinimalDetail = () => (
  <Receipt
    value={{
      metric: 'voms', value: '1204', unit: 'vehicles',
      period_start: '2026-07-01', period_end: '2026-08-01',
      calc_name: 'voms_v0', calc_version: '0.1.0',
      certification_status: 'uncertified',
      detail: { days_observed: 3, peak_day: '2026-07-10' },
    }}
  />
);
