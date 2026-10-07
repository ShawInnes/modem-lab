import type { Packet } from "./protocol";

export const RATE = 48_000;
export const HISTORY_SECONDS = 300;
export const MIN_SPAN = RATE / 2;
export const MAX_SPAN = HISTORY_SECONDS * RATE;

export class SignalStore {
  generation = 0;
  latest = 0;
  revision = 0;
  sequence: number | null = null;
  gaps = 0;
  columns: { sample: number; data: Uint8Array[] }[] = [];

  get earliest() {
    return this.latest <= MAX_SPAN
      ? 0
      : (this.columns[0]?.sample ?? this.latest);
  }

  reset(generation: number) {
    this.generation = generation;
    this.latest = 0;
    this.columns = [];
    this.sequence = null;
    this.gaps = 0;
    this.revision++;
  }

  push(p: Packet) {
    if (p.generation !== this.generation) return;
    if (this.sequence !== null && p.sequence !== this.sequence + 1) this.gaps++;
    this.sequence = p.sequence;
    this.latest = p.startSample + p.frames;
    for (let i = 0; i < p.columns; i++) {
      this.columns.push({
        sample: p.timestamps[i],
        data: p.spectra.map((s) => s.slice(i * p.bins, (i + 1) * p.bins)),
      });
    }
    let expired = 0;
    while (
      expired < this.columns.length &&
      this.columns[expired].sample < this.latest - MAX_SPAN
    )
      expired++;
    expired = Math.max(expired, this.columns.length - HISTORY_SECONDS * 100);
    if (expired > 0) this.columns.splice(0, expired);
    this.revision++;
  }
}

/** One time viewport is shared by both plots. Navigation never changes engine time. */
export class PlotViewport {
  span = 12 * RATE;
  end: number | null = null;
  revision = 0;

  range(store: SignalStore) {
    const earliest = store.earliest;
    const latest = Math.max(store.latest, earliest + this.span);
    const end = Math.max(
      earliest + this.span,
      Math.min(latest, this.end ?? latest),
    );
    return { start: end - this.span, end };
  }

  zoom(factor: number, store: SignalStore, anchor = 0.5) {
    if (!Number.isFinite(factor) || factor <= 0) return;
    const old = this.range(store);
    const point = old.start + this.span * Math.max(0, Math.min(1, anchor));
    this.span = Math.max(MIN_SPAN, Math.min(MAX_SPAN, this.span * factor));
    this.end = point + this.span * (1 - Math.max(0, Math.min(1, anchor)));
    this.end = this.range(store).end;
    this.revision++;
  }

  pan(deltaSamples: number, store: SignalStore) {
    if (!Number.isFinite(deltaSamples)) return;
    this.end = this.range(store).end + deltaSamples;
    this.end = this.range(store).end;
    this.revision++;
  }

  seek(startSamples: number, store: SignalStore) {
    if (!Number.isFinite(startSamples)) return;
    this.end = startSamples + this.span;
    this.end = this.range(store).end;
    this.revision++;
  }

  focus(sample: number, store: SignalStore) {
    this.seek(sample - this.span / 2, store);
  }

  followLive() {
    this.end = null;
    this.revision++;
  }

  reset() {
    this.span = 12 * RATE;
    this.followLive();
  }
}
