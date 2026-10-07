import assert from "node:assert/strict";
import { test } from "node:test";
import { PhaseStore } from "../src/phase-state.ts";

function event(sample, detail, extra = {}) {
  return { type: "event", generation: 0, endpoint: "caller", event_type: "call_stage_changed", sample_index: sample, detail, ...extra };
}

test("phases use actual transition samples and never annotate unreceived future samples", () => {
  const store = new PhaseStore();
  store.append(event(100, "sending_cm: actual menu"));
  store.append(event(400, "training: acquisition"));
  assert.deepEqual(store.intervals("caller", 500).map(({ sample, end, label }) => [sample, end, label]), [[100, 400, "CM"], [400, 500, "Training"]]);
  store.append(event(600, "connected: received payload"));
  assert.equal(store.intervals("caller", 700).at(-1).label, "Data");
});

test("semantic retention keeps the phase active at history boundary and drops stale messages", () => {
  const store = new PhaseStore();
  store.append(event(50, "dialing: digits"));
  store.append(event(100, "ringing: tone"));
  store.append(event(80, "old CM", { event_type: "negotiation_message", negotiation: { direction: "tx", signal: "CM" } }));
  store.append(event(300, "training: carrier"));
  store.prune(200);
  assert.deepEqual(store.events.map((event) => event.sample_index), [100, 300]);
  assert.deepEqual(store.intervals("caller", 400).map(({ sample, end }) => [sample, end]), [[100, 300], [300, 400]]);
});

test("message markers belong to the endpoint and selected signal direction, not a fake interval", () => {
  const store = new PhaseStore();
  for (const [endpoint, direction, sample] of [["caller", "tx", 10], ["caller", "rx", 30], ["answerer", "tx", 20]])
    store.append(event(sample, "menu", { endpoint, event_type: "negotiation_message", negotiation: { direction, signal: "CM" } }));
  assert.deepEqual(store.messages("caller", "rx").map((event) => event.sample_index), [30]);
  assert.deepEqual(store.messages("caller", "tx").map((event) => event.sample_index), [10]);
  assert.equal(store.intervals("caller", 100).length, 0);
});

test("disconnect closes the previous phase; stale generations and decoded bytes are ignored", () => {
  const store = new PhaseStore();
  store.append(event(10, "connected: acquired"));
  store.append(event(100, "Cancelled pending characters", { event_type: "disconnected" }));
  store.append(event(50, "65", { event_type: "decoded_byte" }));
  store.append(event(70, "training: stale", { generation: 9 }));
  store.append(event(10, "connected: acquired"));
  assert.deepEqual(store.intervals("caller", 100).map(({ sample, end, label }) => [sample, end, label]), [[10, 100, "Data"], [100, 100, "Disconnected"]]);
  store.reset(10);
  assert.equal(store.events.length, 0);
  assert.equal(store.generation, 10);
});
