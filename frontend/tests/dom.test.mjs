import test from 'node:test';
import assert from 'node:assert/strict';
import { html, raw, esc } from '../js/dom.js';

test('html`` escapes interpolated values', () => {
  const evil = '<img src=x onerror=alert(1)>"\'&';
  const out = html`<p>${evil}</p>`.__raw;
  assert.ok(!out.includes('<img'));
  assert.match(out, /&lt;img/);
});
test('raw() and nested templates are passed through; arrays are joined; nullish values vanish', () => {
  assert.equal(html`<ul>${['a', 'b'].map((x) => html`<li>${x}</li>`)}</ul>`.__raw, '<ul><li>a</li><li>b</li></ul>');
  assert.equal(html`${null}${undefined}${false}x${raw('<b>')}`.__raw, 'x<b>');
  assert.equal(esc(0), '0');
});
