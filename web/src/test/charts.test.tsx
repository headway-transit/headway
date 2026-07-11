import { it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { TimeSeriesChart } from '../components/charts/TimeSeriesChart';

// Regression: the y-scale's top tick must cover the data maximum. Before the
// 2026-07-11 fix, niceTicks stopped below dataMax and py() clamped every
// larger point onto the top gridline — two distinct large values rendered at
// the identical y pixel (found by design-sync preview verification).
it('does not clamp distinct large values to the same y position', () => {
  const mk = (display: string, y: number, x: number) => ({ x, xLabel: `2026-07-0${x}`, display, y });
  const { container } = render(
    <TimeSeriesChart
      ariaLabel="regression"
      unit="unlinked passenger trips"
      series={[{ id: 'upt', label: 'UPT', color: 'var(--series-1)', points: [mk('190000', 190000, 1), mk('238100', 238100, 2), mk('245000', 245000, 3)] }]}
    />,
  );
  const d = container.querySelector('.chart-series-line')?.getAttribute('d') || '';
  const ys = [...d.matchAll(/[ML]\s*[\d.]+[ ,]([\d.]+)/g)].map((m) => m[1]);
  expect(ys.length).toBeGreaterThanOrEqual(3);
  expect(ys.at(-2)).not.toBe(ys.at(-1)); // 238100 and 245000 must not share a pixel
});
