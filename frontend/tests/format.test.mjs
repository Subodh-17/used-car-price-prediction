import test from 'node:test';
import assert from 'node:assert/strict';
import { formatINR, formatINRCompact, formatSignedINR, formatPercent } from '../js/format.js';

test('formatINR uses Indian digit grouping', () => {
  assert.equal(formatINR(85000), '₹85,000');
  assert.equal(formatINR(345000), '₹3,45,000');
  assert.equal(formatINR(1250000), '₹12,50,000');
  assert.equal(formatINR(12500000), '₹1,25,00,000');
});
test('formatINR rounds to whole rupees and rejects non-finite values', () => {
  assert.equal(formatINR(550000.4), '₹5,50,000');
  for (const bad of [NaN, Infinity, -Infinity, '5', null, undefined]) assert.throws(() => formatINR(bad), TypeError);
});
test('lakh source value 5.5 must be 550000 rupees before formatting (unit conversion is a backend concern)', () => {
  assert.equal(formatINR(5.5 * 100000), '₹5,50,000');
});
test('compact axis labels', () => {
  assert.equal(formatINRCompact(85000), '₹85K');
  assert.equal(formatINRCompact(350000), '₹3.5L');
  assert.equal(formatINRCompact(12500000), '₹1.25Cr');
  assert.equal(formatINRCompact(0), '₹0');
  assert.equal(formatINRCompact(NaN), '–');
});
test('signed effects and percentages', () => {
  assert.equal(formatSignedINR(120000), '+₹1,20,000');
  assert.equal(formatSignedINR(-35000), '−₹35,000');
  assert.equal(formatPercent(0.8123), '81.2%');
});
