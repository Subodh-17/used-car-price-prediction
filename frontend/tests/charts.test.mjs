import test from 'node:test';
import assert from 'node:assert/strict';
import { niceTicks, barChart, hBarChart, lineChart, scatterChart } from '../js/charts.js';

test('niceTicks start at 0 and cover the max', () => {
  const t = niceTicks(87); assert.equal(t[0], 0); assert.ok(t.at(-1) >= 87);
  assert.deepEqual(niceTicks(0), [0, 1]);
});
test('charts render labelled SVG, escape text, and return empty string for empty data', () => {
  assert.equal(barChart({ labels: [], values: [], label: 'x' }), '');
  const svg = barChart({ labels: ['<b>'], values: [3], label: 'A <chart>' });
  assert.match(svg, /^<svg/); assert.ok(!svg.includes('<b>')); assert.match(svg, /aria-label="A &lt;chart&gt;"/);
  assert.match(hBarChart({ items: [{ label: 'Maruti', value: 5 }], label: 'brands' }), /Maruti/);
  assert.match(lineChart({ points: [{ x: 1, y: 2, lo: 1, hi: 3 }, { x: 2, y: 3, lo: 2, hi: 4 }], label: 'l' }), /class="band"/);
  assert.match(scatterChart({ points: [{ x: 1, y: 1 }], identity: true, label: 's' }), /class="identity"/);
});
test('no NaN coordinates for degenerate single-point input', () => {
  assert.ok(!lineChart({ points: [{ x: 5, y: 10 }], label: 'l' }).includes('NaN'));
  assert.ok(!scatterChart({ points: [{ x: 0, y: 0 }], label: 's' }).includes('NaN'));
});

import { kmLabel } from '../js/pages/analytics.js';
test('kilometre bucket labels are human readable', () => {
  assert.equal(kmLabel('(-1, 10000]'), '0–10k');
  assert.equal(kmLabel('(25000, 50000]'), '25–50k');
  assert.equal(kmLabel('(150000, 250000]'), '150k+');
});
