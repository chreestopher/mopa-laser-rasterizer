import test from 'node:test';
import assert from 'node:assert/strict';
import {buildPaletteImport} from '../serverless_web/lightburn-palette-model.js';
const snapshot = {units: {units: 'in/min', distance_units: 'mm'}, library: {name: 'Test', entries: [
  {material: 'Steel', description: 'Blue & <bright>', guid: 'entry-1', cut: {kind: 'normal', mode: 'scan', params: {speed: 60, max_power: 30, min_power: 0, frequency: 200000, q_pulse_width: 120, interval: 0.05, cross_hatch: false}, sub_layers: [{mode: 'cut', enabled: false, params: {speed: 120, max_power: 10}}]}},
  {material: 'Brass', description: 'Blue & <bright>', cut: {kind: 'normal', mode: 'cut', params: {speed: 30, max_power: 20, novel_field: 42}}},
]}};
test('selected entries convert independent units and retain Hz/ns, zero, disabled sublayers and provenance', () => {
  const result = buildPaletteImport(snapshot, [0], 'New palette');
  assert.equal(result.entries[0].settings.speed, 25.4);
  assert.equal(result.entries[0].settings.interval, 0.05);
  assert.equal(result.entries[0].settings.frequency, 200000);
  assert.equal(result.entries[0].settings.QPulseWidth, 120);
  assert.equal(result.entries[0].settings.minPower, 0);
  assert.match(result.xml, /SubLayer type="Cut"/);
  assert.match(result.xml, /doOutput Value="0"/);
  assert.match(result.xml, /Blue &amp; &lt;bright&gt;/);
  assert.match(result.xml, /entry-1/);
  assert.equal(result.entries.length, 1);
});
test('multiple source materials create one palette group and unique descriptions; unsupported fields are explicit', () => {
  const result = buildPaletteImport(snapshot, [0, 1], 'Mixed palette');
  assert.equal((result.xml.match(/<Material /g) || []).length, 1);
  assert.notEqual(result.entries[0].description, result.entries[1].description);
  assert.ok(result.warnings.some(w => w.includes('novel_field')));
  assert.match(result.xml, /Brass/);
});
test('rejects empty/invalid selections and unknown units without inventing values', () => {
  for (const indices of [[], [9], [0, 0]]) assert.throws(() => buildPaletteImport(snapshot, indices, 'Palette'));
  assert.throws(() => buildPaletteImport({...snapshot, units: {units: 'furlongs', distance_units: 'mm'}}, [0], 'Palette'));
  assert.throws(() => buildPaletteImport(snapshot, [0], ''));
});


test('swatch defaults match names exactly, preserve unassigned entries and reject duplicate assignments', async () => {
  const {defaultSwatchAssignments, paletteSwatchMapping} = await import('../serverless_web/lightburn-palette-model.js');
  const entries = [{description: ' blue '}, {description: 'Custom'}, {description: 'BLUE'}];
  const palette = [{name: 'Blue', hex: '#0000FF'}, {name: 'Red', hex: '#FF0000'}];
  assert.deepEqual(defaultSwatchAssignments(entries, palette), ['#0000FF', '', '']);
  assert.deepEqual(paletteSwatchMapping(entries, ['#0000FF', '#FF0000', ''], palette), {'#0000FF': ' blue ', '#FF0000': 'Custom'});
  assert.deepEqual(paletteSwatchMapping(entries, ['', '', ''], palette), {});
  assert.throws(() => paletteSwatchMapping(entries, ['#0000FF', '#0000FF', ''], palette), /already assigned/);
  assert.throws(() => paletteSwatchMapping(entries, ['#123456', '', ''], palette), /official swatch/);
});
