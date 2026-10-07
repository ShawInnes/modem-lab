import { useEffect, useRef, useState } from "react";
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
        Wheel zooms · drag pans · last {HISTORY_SECONDS / 60} min
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
  label,
}: {
  store: SignalStore;
  stream: number;
  cursor: number | null;
  clock: () => number;
  viewport: PlotViewport;
  onNavigate: () => void;
  label: string;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const drag = useRef<{ x: number; end: number; span: number } | null>(null);
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
      if (x >= left && x <= left + w) {
        ctx.strokeStyle = cursor === null ? "#a7bac7" : "#fff";
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(x, top);
        ctx.lineTo(x, top + h);
        ctx.stroke();
        ctx.setLineDash([]);
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
        };
        event.currentTarget.dataset.dragging = "true";
      }}
      onPointerMove={(event) => {
        if (!drag.current) return;
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
        drag.current = null;
        delete event.currentTarget.dataset.dragging;
      }}
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
