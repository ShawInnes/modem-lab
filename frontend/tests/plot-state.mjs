import assert from "node:assert/strict";
import { test } from "node:test";
import {
  HISTORY_SECONDS,
  PlotViewport,
  RATE,
  SignalStore,
} from "../src/plot-state.ts";

function storeAt(seconds, earliest = 0) {
  const store = new SignalStore();
  store.latest = seconds * RATE;
  store.columns = [{ sample: earliest * RATE, data: [new Uint8Array([1])] }];
  return store;
}

function packet(sequence, startSeconds, timestamps, generation = 0) {
  return {
    generation,
    sequence,
    startSample: startSeconds * RATE,
    sampleRate: RATE,
    frames: RATE,
    columns: timestamps.length,
    bins: 1,
    streams: [],
    timestamps: timestamps.map((seconds) => seconds * RATE),
    spectra: [new Uint8Array(timestamps.map(() => 123))],
  };
}

test("live range follows incoming samples and reserves the initial twelve seconds", () => {
  const viewport = new PlotViewport();
  const store = new SignalStore();
  assert.equal(viewport.end, null);
  assert.equal(viewport.span, 12 * RATE);
  assert.deepEqual(viewport.range(store), { start: 0, end: 12 * RATE });
  store.latest = 20 * RATE;
  assert.deepEqual(viewport.range(store), { start: 8 * RATE, end: 20 * RATE });
  store.latest += RATE;
  assert.deepEqual(viewport.range(store), { start: 9 * RATE, end: 21 * RATE });
});

test("zoom preserves a chosen time anchor and clamps span to useful limits", () => {
  const store = storeAt(120);
  const viewport = new PlotViewport();
  viewport.seek(40 * RATE, store);
  const before = viewport.range(store);
  viewport.zoom(0.5, store, 0.25);
  const after = viewport.range(store);
  assert.equal(viewport.span, 6 * RATE);
  assert.equal(
    before.start + 0.25 * (before.end - before.start),
    after.start + 0.25 * (after.end - after.start),
  );
  viewport.zoom(0.00001, store);
  assert.equal(viewport.span, 0.5 * RATE);
  viewport.zoom(1e9, store);
  assert.equal(viewport.span, HISTORY_SECONDS * RATE);
  assert.ok(viewport.range(store).start >= 0);
});

test("backward panning pauses live movement until Live is selected", () => {
  const store = storeAt(120);
  const viewport = new PlotViewport();
  viewport.pan(-10 * RATE, store);
  assert.notEqual(viewport.end, null);
  const history = viewport.range(store);
  assert.deepEqual(history, { start: 98 * RATE, end: 110 * RATE });
  store.latest += 20 * RATE;
  assert.deepEqual(viewport.range(store), history);
  viewport.pan(1e9, store);
  assert.notEqual(viewport.end, null);
  assert.equal(viewport.range(store).end, store.latest);
  store.latest += RATE;
  assert.equal(viewport.range(store).end, 140 * RATE);
  viewport.followLive();
  assert.equal(viewport.end, null);
  assert.equal(viewport.range(store).end, store.latest);
});

test("seek, event focus and expired history stay inside retained samples", () => {
  const store = storeAt(420, 330);
  const viewport = new PlotViewport();
  viewport.seek(0, store);
  assert.equal(viewport.range(store).start, 330 * RATE);
  viewport.seek(340 * RATE, store);
  assert.equal(viewport.range(store).start, 340 * RATE);
  store.latest = 450 * RATE;
  store.columns[0].sample = 350 * RATE;
  assert.equal(viewport.range(store).start, 350 * RATE);
  viewport.focus(400 * RATE, store);
  const range = viewport.range(store);
  assert.notEqual(viewport.end, null);
  assert.ok(range.start <= 400 * RATE && range.end >= 400 * RATE);
  viewport.focus(0, store);
  assert.equal(viewport.range(store).start, store.earliest);
});

test("reset restores the default live viewport and invalidates rendering", () => {
  const viewport = new PlotViewport();
  const store = storeAt(120);
  viewport.zoom(0.5, store);
  viewport.pan(-RATE, store);
  const revision = viewport.revision;
  viewport.reset();
  assert.equal(viewport.span, 12 * RATE);
  assert.equal(viewport.end, null);
  assert.ok(viewport.revision > revision);
});

test("signal store retains five minutes, preserves gaps and ignores old generations", () => {
  const store = new SignalStore();
  assert.equal(HISTORY_SECONDS, 300);
  assert.equal(store.earliest, 0);
  store.push(packet(1, 0, [0, 0.5]));
  store.push(packet(3, 300, [300, 300.5]));
  assert.equal(store.gaps, 1);
  assert.equal(store.latest, 301 * RATE);
  assert.equal(store.earliest, 300 * RATE);
  const revision = store.revision;
  store.push(packet(4, 301, [301], 99));
  assert.equal(store.revision, revision);
  store.reset(99);
  assert.equal(store.generation, 99);
  assert.equal(store.latest, 0);
  assert.equal(store.earliest, 0);
  assert.equal(store.sequence, null);
  assert.equal(store.gaps, 0);
  assert.deepEqual(store.columns, []);
});

test("retention is time based and does not discard dense columns at the old pixel limit", () => {
  const store = new SignalStore();
  const timestamps = Array.from({ length: 1500 }, (_, i) => i / 1500);
  store.push(packet(1, 0, timestamps));
  assert.equal(store.columns.length, 1500);
  assert.equal(store.columns[1499].data[0][0], 123);
});
