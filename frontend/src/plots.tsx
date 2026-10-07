import { useEffect, useRef, useState } from "react";
import { PhaseStore } from "./phase-state";
import type { Endpoint } from "./protocol";
import {
  PlotViewport,
  SignalStore,
  RATE,
  HISTORY_SECONDS,
  MIN_SPAN,
  MAX_SPAN,
} from "./plot-state";
export { PlotViewport, SignalStore } from "./plot-state";

const BINS = 171;
const colors = Array.from({ length: 256 }, (_, level) => {
  const q = level / 255;
  return [
    Math.round(12 + 243 * q ** 3),
    Math.round(22 + 207 * q ** 1.9),
    Math.round(31 + 170 * q ** 1.1),
  ];
});

export function PlotNavigation({
  store,
  viewport,
  onNavigate,
}: {
  store: SignalStore;
  viewport: PlotViewport;
  onNavigate: () => void;
}) {
  const [, update] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => update((value) => value + 1), 200);
    return () => clearInterval(timer);
  }, []);
  const range = viewport.range(store);
  const change = (action: () => void) => {
    action();
    onNavigate();
    update((value) => value + 1);
  };
  const zoom = (factor: number) =>
    change(() => {
      const live = viewport.end === null;
      viewport.zoom(factor, store, 1);
      if (live) viewport.followLive();
    });
  return (
    <div className="plot-navigation" aria-label="Shared graph navigation">
      <div className="plot-buttons">
        <button
          aria-label="Zoom in both graphs"
          disabled={viewport.span <= MIN_SPAN}
          onClick={() => zoom(0.5)}
        >
          +
        </button>
        <button
          aria-label="Zoom out both graphs"
          disabled={viewport.span >= MAX_SPAN}
          onClick={() => zoom(2)}
        >
          −
        </button>
        <button
          aria-label="Scroll both graphs backward"
          disabled={range.start <= store.earliest}
          onClick={() => change(() => viewport.pan(-viewport.span / 2, store))}
        >
          ←
        </button>
        <button
          aria-label="Scroll both graphs forward"
          disabled={range.end >= store.latest}
          onClick={() => change(() => viewport.pan(viewport.span / 2, store))}
        >
          →
        </button>
        <button
          aria-pressed={viewport.end === null}
          onClick={() => change(() => viewport.followLive())}
        >
          Follow live
        </button>
      </div>
      <output aria-label="Shared graph time range">
        {(range.start / RATE).toFixed(2)}–{(range.end / RATE).toFixed(2)} s ·{" "}
        {viewport.end === null ? "live" : "history"}
      </output>
      <input
        type="range"
        aria-label="Graph history position"
        min={store.earliest / RATE}
        max={Math.max(store.earliest, store.latest - viewport.span) / RATE}
        step="0.01"
        value={range.start / RATE}
        disabled={store.latest - viewport.span <= store.earliest}
        onChange={(event) =>
          change(() => viewport.seek(Number(event.target.value) * RATE, store))
        }
      />
      <small id="plot-navigation-help">
        Hover compares · click pins · wheel zooms · drag pans · last {HISTORY_SECONDS / 60} min
      </small>
    </div>
  );
}

export function Spectrogram({
  store,
  stream,
  cursor,
  clock,
  viewport,
  onNavigate,
  onCursorChange,
  label,
}: {
  store: SignalStore;
  stream: number;
  cursor: number | null;
  clock: () => number;
  viewport: PlotViewport;
  onNavigate: () => void;
  onCursorChange?: (sample: number | null, pin?: boolean) => void;
  label: string;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const drag = useRef<{ x: number; end: number; span: number; moved: boolean } | null>(null);
  const sampleAt = (element: HTMLCanvasElement, clientX: number) => {
    const bounds = element.getBoundingClientRect();
    const fraction = Math.max(0, Math.min(1, (clientX - bounds.left - 36) / Math.max(1, bounds.width - 48)));
    return Math.min(store.latest, Math.round(viewport.range(store).start + fraction * viewport.span));
  };
  useEffect(() => {
    const c = canvas.current!;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      if (event.shiftKey || Math.abs(event.deltaX) > Math.abs(event.deltaY)) {
        const delta = event.deltaX || event.deltaY;
        viewport.pan(
          ((delta * viewport.span) / Math.max(1, c.clientWidth - 48)) *
            (event.deltaMode === 1 ? 16 : 1),
          store,
        );
      } else {
        const bounds = c.getBoundingClientRect();
        const anchor = Math.max(
          0,
          Math.min(
            1,
            (event.clientX - bounds.left - 36) / Math.max(1, bounds.width - 48),
          ),
        );
        viewport.zoom(
          Math.exp(
            Math.max(
              -1,
              Math.min(
                1,
                event.deltaY * (event.deltaMode === 1 ? 16 : 1) * 0.002,
              ),
            ),
          ),
          store,
          anchor,
        );
      }
      onNavigate();
    };
    c.addEventListener("wheel", wheel, { passive: false });
    return () => c.removeEventListener("wheel", wheel);
  }, [store, viewport, onNavigate]);

  useEffect(() => {
    let raf = 0,
      last = 0;
    const scratch = document.createElement("canvas");
    scratch.height = BINS;
    const s = scratch.getContext("2d")!;
    let cache = "";
    const draw = (now: number) => {
      raf = requestAnimationFrame(draw);
      if (now - last < (viewport.span > 60 * RATE ? 100 : 40)) return;
      last = now;
      const c = canvas.current;
      if (!c || c.clientWidth < 50) return;
      const ctx = c.getContext("2d")!;
      const width = c.clientWidth,
        height = 200,
        dpr = devicePixelRatio || 1;
      if (c.width !== Math.round(width * dpr) || c.height !== height * dpr) {
        c.width = Math.round(width * dpr);
        c.height = height * dpr;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const { start, end } = viewport.range(store);
      c.dataset.startSample = String(start);
      c.dataset.endSample = String(end);
      c.dataset.spanSamples = String(viewport.span);
      c.setAttribute(
        "aria-label",
        `${label} spectrogram, ${(start / RATE).toFixed(2)} to ${(end / RATE).toFixed(2)} seconds, zero to four kilohertz`,
      );
      const pixels = Math.max(1, Math.min(1200, Math.ceil(width - 48)));
      const changing = viewport.end === null || store.latest < end + 2048;
      const key = `${start}:${end}:${stream}:${pixels}:${changing ? store.revision : 0}`;
      if (cache !== key) {
        cache = key;
        scratch.width = pixels;
        const levels = new Uint8Array(pixels * BINS);
        // Binary search skips old columns when zoomed in near the live edge.
        let low = 0,
          high = store.columns.length;
        while (low < high) {
          const mid = (low + high) >>> 1;
          if (store.columns[mid].sample < start - 480) low = mid + 1;
          else high = mid;
        }
        for (let i = low; i < store.columns.length; i++) {
          const col = store.columns[i];
          if (col.sample > end + 480) break;
          const left = Math.max(
            0,
            Math.floor(((col.sample - 240 - start) / viewport.span) * pixels),
          );
          const right = Math.min(
            pixels,
            Math.max(
              left + 1,
              Math.ceil(((col.sample + 240 - start) / viewport.span) * pixels),
            ),
          );
          for (let b = 0; b < BINS; b++) {
            const row = (BINS - 1 - b) * pixels,
              level = col.data[stream][b];
            for (let x = left; x < right; x++)
              if (level > levels[row + x]) levels[row + x] = level;
          }
        }
        const im = s.createImageData(pixels, BINS);
        for (let i = 0; i < levels.length; i++) {
          const color = colors[levels[i]],
            n = i * 4;
          im.data[n] = color[0];
          im.data[n + 1] = color[1];
          im.data[n + 2] = color[2];
          im.data[n + 3] = 255;
        }
        s.putImageData(im, 0, 0);
      }
      ctx.clearRect(0, 0, width, height);
      const left = 36,
        top = 18,
        w = width - left - 12,
        h = 144;
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(scratch, left, top, w, h);
      ctx.font = "11px ui-monospace,monospace";
      ctx.fillStyle = getComputedStyle(c).getPropertyValue("--dim");
      ctx.strokeStyle = "rgba(160,180,195,.18)";
      ctx.fillText("kHz", 3, 11);
      for (let f = 0; f <= 4; f++) {
        const y = top + h - (f / 4) * h;
        ctx.fillText(String(f), 18, y + 4);
        ctx.beginPath();
        ctx.moveTo(left, y);
        ctx.lineTo(left + w, y);
        ctx.stroke();
      }
      for (let i = 0; i <= 4; i++) {
        const x = left + (i / 4) * w;
        ctx.fillText(
          ((start + (viewport.span * i) / 4) / RATE).toFixed(
            viewport.span < 3 * RATE ? 2 : 1,
          ),
          Math.min(x, width - 38),
          181,
        );
      }
      ctx.fillText("seconds", Math.max(left, width - 70), 198);
      const sample = cursor ?? clock(),
        x = left + ((sample - start) / viewport.span) * w;
      c.dataset.cursorSample = String(sample);
      c.dataset.cursorVisible = String(x >= left && x <= left + w);
      if (x >= left && x <= left + w) {
        ctx.strokeStyle = cursor === null ? "#a7bac7" : "#fff";
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(x, top);
        ctx.lineTo(x, top + h);
        ctx.stroke();
        ctx.setLineDash([]);
        if (cursor !== null) {
          const text = `${(sample / RATE).toFixed(3)} s`;
          const textWidth = ctx.measureText(text).width;
          const textX = Math.max(left, Math.min(x + 5, left + w - textWidth - 5));
          ctx.fillStyle = "rgba(8,16,22,.88)";
          ctx.fillRect(textX - 3, top + 3, textWidth + 6, 16);
          ctx.fillStyle = "#fff";
          ctx.fillText(text, textX, top + 15);
        }
      }
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [store, stream, cursor, clock, viewport, label]);

  return (
    <canvas
      ref={canvas}
      role="img"
      tabIndex={0}
      aria-label={`${label} spectrogram`}
      aria-describedby="plot-navigation-help"
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        event.currentTarget.setPointerCapture(event.pointerId);
        drag.current = {
          x: event.clientX,
          end: viewport.range(store).end,
          span: viewport.span,
          moved: false,
        };
      }}
      onPointerMove={(event) => {
        if (!drag.current) {
          onCursorChange?.(sampleAt(event.currentTarget, event.clientX), false);
          return;
        }
        if (!drag.current.moved && Math.abs(event.clientX - drag.current.x) < 4) return;
        drag.current.moved = true;
        event.currentTarget.dataset.dragging = "true";
        onCursorChange?.(null, false);
        viewport.seek(
          drag.current.end -
            drag.current.span -
            ((event.clientX - drag.current.x) * drag.current.span) /
              Math.max(1, event.currentTarget.clientWidth - 48),
          store,
        );
        onNavigate();
      }}
      onPointerUp={(event) => {
        if (drag.current && !drag.current.moved)
          onCursorChange?.(sampleAt(event.currentTarget, event.clientX), true);
        drag.current = null;
        delete event.currentTarget.dataset.dragging;
      }}
      onPointerLeave={() => { if (!drag.current) onCursorChange?.(null, false); }}
      onPointerCancel={(event) => {
        drag.current = null;
        delete event.currentTarget.dataset.dragging;
      }}
      onLostPointerCapture={(event) => {
        drag.current = null;
        delete event.currentTarget.dataset.dragging;
      }}
      onKeyDown={(event) => {
        if (
          !["ArrowLeft", "ArrowRight", "+", "=", "-", "Home", "End"].includes(
            event.key,
          )
        )
          return;
        event.preventDefault();
        if (event.key === "ArrowLeft" || event.key === "ArrowRight")
          viewport.pan(
            (viewport.span / 4) * (event.key === "ArrowLeft" ? -1 : 1),
            store,
          );
        else if (event.key === "Home") viewport.seek(store.earliest, store);
        else if (event.key === "End") viewport.followLive();
        else viewport.zoom(event.key === "-" ? 2 : 0.5, store);
        onNavigate();
      }}
    />
  );
}

/** Phase extents stop at the last received sample; message ticks are instants, not durations. */
export function PhaseAnnotations({
  store,
  viewport,
  phases,
  endpoint,
  stream,
  onSelectPhase,
  cursor = null,
  clock = () => store.latest,
}: {
  store: SignalStore;
  viewport: PlotViewport;
  phases: PhaseStore;
  endpoint: Endpoint;
  stream: number;
  onSelectPhase: (sample: number) => void;
  cursor?: number | null;
  clock?: () => number;
}) {
  const [, update] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => update((value) => value + 1), 100);
    return () => clearInterval(timer);
  }, []);
  const { start, end } = viewport.range(store);
  const percent = (sample: number) => ((sample - start) / viewport.span) * 100;
  const direction = stream < 2 ? "tx" : "rx";
  const intervals = phases.intervals(endpoint, store.latest).filter((phase) => phase.end > start && phase.sample < end && phase.end > phase.sample);
  const messages = phases.messages(endpoint, direction).filter((event) => event.sample_index >= start && event.sample_index <= Math.min(end, store.latest));
  const name = endpoint === "caller" ? "Caller" : "Answerer";
  const sample = cursor ?? clock();
  const active = phases.intervals(endpoint, store.latest).find((phase) => phase.sample <= sample &&
    (sample < phase.end || phase.end === store.latest && sample === phase.end));
  const lastMessage = phases.messages(endpoint, direction).filter((event) =>
    event.sample_index <= sample && event.sample_index >= (active?.sample ?? Infinity)).at(-1);
  const cursorVisible = sample >= start && sample <= Math.min(end, store.latest);
  return (
    <div className="phase-annotations" aria-label={`${name} handshake and negotiation timeline`} data-start-sample={start} data-end-sample={end}>
      <div className="phase-band" aria-label={`${name} call phases`}>
        {intervals.map((phase) => {
          const left = Math.max(start, phase.sample);
          const right = Math.min(end, phase.end);
          const timing = `${(phase.sample / RATE).toFixed(3)}–${(phase.end / RATE).toFixed(3)} s`;
          return (
            <button
              key={`${phase.sample}:${phase.label}`}
              className="phase-interval"
              data-phase={phase.label}
              data-sample={phase.sample}
              style={{ left: `${percent(left)}%`, width: `${((right - left) / viewport.span) * 100}%` }}
              title={`${phase.label} · ${timing}\n${phase.detail}`}
              aria-label={`${name} phase ${phase.label}, ${timing}. ${phase.detail}`}
              onClick={() => onSelectPhase(Math.max(store.earliest, phase.sample))}
            >{phase.label}</button>
          );
        })}
        {intervals.length === 0 && <span className="phase-empty">Call phases appear here</span>}
        {cursorVisible && <span className="phase-cursor" style={{ left: `${percent(sample)}%` }} />}
      </div>
      <div className="phase-band message-band" aria-label={`${name} ${direction === "tx" ? "transmitted" : "received"} negotiation messages`}>
        {messages.map((event, i) => {
          const message = event.negotiation!;
          const label = `${message.signal ?? "Signal"}${direction === "rx" ? " received" : ""}`;
          const next = messages[i + 1]?.sample_index ?? Math.min(end, store.latest);
          const width = Math.max(0, ((next - event.sample_index) / viewport.span) * 100);
          const description = `${message.protocol ?? "Negotiation"} ${label} at ${(event.sample_index / RATE).toFixed(3)} s · ${message.validation ?? "observed"}`;
          return (
            <button
              key={`${event.sample_index}:${message.signal}:${i}`}
              className="phase-message"
              style={{ left: `${percent(event.sample_index)}%`, width: `${width}%` }}
              data-sample={event.sample_index}
              data-signal={message.signal}
              title={`${description}\n${event.detail}`}
              aria-label={`${name} ${description}`}
              onClick={() => onSelectPhase(event.sample_index)}
            ><span>{label}</span></button>
          );
        })}
        {messages.length === 0 && <span className="phase-empty">{direction === "tx" ? "TX" : "RX"} negotiation markers</span>}
        {cursorVisible && <span className="phase-cursor" style={{ left: `${percent(sample)}%` }} />}
      </div>
      <output className="phase-caption" aria-label={`${name} phase at cursor`}>
        {(sample / RATE).toFixed(3)} s · {active?.label ?? "No recorded phase"}
        {lastMessage && ` · last ${direction.toUpperCase()} ${lastMessage.negotiation?.signal}`}
      </output>
    </div>
  );
}
