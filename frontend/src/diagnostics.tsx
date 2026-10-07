import { useEffect, useRef, useState } from "react";
import type { Endpoint, ReceiverDiagnostics } from "./protocol";
type View = "symbols" | "eye";
const names: Record<Endpoint, string> = { caller: "Caller", answerer: "Answerer" };

function ReceiverView({ endpoint, diagnostics, view }: { endpoint: Endpoint; diagnostics?: ReceiverDiagnostics; view: View }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const mode = diagnostics?.mode ?? "fsk";
  const last = diagnostics?.symbols.at(-1);
  const explanation = view === "eye"
    ? mode === "fsk"
      ? "Mark-minus-space contrast, folded around received bit decisions. A wide opening at the center separates 0 from 1; noise and overlap close it."
      : mode === "qam16"
        ? "Carrier-corrected I amplitude, folded around received symbol decisions. Four levels (−3, −1, +1, +3) carry amplitude choices; the center is the sampling instant."
        : "Matched-filter magnitude, folded around symbol decisions. Dips reveal phase transitions; the center marks the receiver’s sampling instant. This is a timing envelope, not a binary eye."
    : mode === "fsk"
      ? "Space-tone energy across, mark-tone energy up. Above the diagonal favors bit 1; below it favors bit 0. The scale follows the received signal."
      : mode === "qam16"
        ? "Carrier- and gain-corrected I/Q keeps amplitude: 16 targets instead of four phase directions. The first two bits change quadrant; the last two pick a point within it. Target labels show those last two bits."
        : "Each point is the phase change between two received symbols. Four directions carry four dibits. Spread and rotation reveal noise and phase error. Idle points are sampled at 10 Hz so recent data remains visible.";

  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    function paint() {
      if (!element) return;
      const styles = getComputedStyle(document.documentElement);
      const ink = styles.getPropertyValue("--ink").trim(), dim = styles.getPropertyValue("--dim").trim();
      const edge = styles.getPropertyValue("--edge").trim(), paper = styles.getPropertyValue("--paper").trim();
      const color = styles.getPropertyValue(endpoint === "caller" ? "--a" : "--b").trim();
      const width = Math.max(220, element.clientWidth), height = 220, ratio = window.devicePixelRatio || 1;
      element.width = width * ratio; element.height = height * ratio;
      const ctx = element.getContext("2d");
      if (!ctx) return;
      ctx.scale(ratio, ratio); ctx.fillStyle = paper; ctx.fillRect(0, 0, width, height);
      ctx.font = "10px ui-monospace, monospace";
      const left = 40, right = width - 22, top = 18, bottom = height - 38;
      const w = right - left, h = bottom - top;
      const x = (value: number) => left + value * w, y = (value: number) => bottom - value * h;
      const line = (x1: number, y1: number, x2: number, y2: number, stroke = edge) => {
        ctx.strokeStyle = stroke; ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
      };
      if (view === "eye" || mode === "fsk") for (let i = 0; i <= 4; i++) { line(x(i / 4), top, x(i / 4), bottom); line(left, y(i / 4), right, y(i / 4)); }
      ctx.fillStyle = dim; ctx.textAlign = "center";
      const label = (text: string) => ctx.fillText(text, (left + right) / 2, height - 9);
      const points = diagnostics?.symbols ?? [];
      if (view === "eye") {
        label("−½ symbol     decision     +½ symbol");
        ctx.setLineDash([3, 4]); line(x(0.5), top, x(0.5), bottom, dim); ctx.setLineDash([]);
        ctx.textAlign = "right";
        ctx.fillText(mode === "qam16" ? "+4" : "+1", left - 7, top + 4);
        ctx.fillText(mode === "fsk" || mode === "qam16" ? "0" : "½", left - 7, y(0.5) + 4);
        ctx.fillText(mode === "qam16" ? "−4" : mode === "fsk" ? "−1" : "0", left - 7, bottom + 4);
        const period = diagnostics?.symbol_samples ?? 160, anchor = last?.[0];
        if (anchor !== undefined && period > 0) {
          let previousX: number | undefined, previousY: number | undefined;
          ctx.globalAlpha = 0.55;
          for (const [sample, value] of diagnostics?.trace ?? []) {
            if (!Number.isFinite(sample) || !Number.isFinite(value)) continue;
            const phase = (((sample - anchor + period / 2) % period) + period) % period / period;
            const amplitude = mode === "qam16" ? (Math.max(-4, Math.min(4, value)) + 4) / 8 : mode === "fsk" ? (Math.max(-1, Math.min(1, value)) + 1) / 2 : Math.max(0, Math.min(1, value));
            const px = x(phase), py = y(amplitude);
            if (previousX !== undefined && previousY !== undefined && px >= previousX && px - previousX < w / 2) line(previousX, previousY, px, py, color);
            previousX = px; previousY = py;
          }
          ctx.globalAlpha = 1;
        }
      } else if (mode === "fsk") {
        label("Space tone energy →");
        ctx.save(); ctx.translate(13, (top + bottom) / 2); ctx.rotate(-Math.PI / 2); ctx.fillText("Mark tone energy →", 0, 0); ctx.restore();
        ctx.setLineDash([4, 4]); line(left, bottom, right, top, dim); ctx.setLineDash([]);
        ctx.textAlign = "left"; ctx.fillText("bit 1 · mark", left + 7, top + 14);
        ctx.textAlign = "right"; ctx.fillText("bit 0 · space", right - 7, bottom - 8);
        const maximum = Math.max(0.0001, ...points.flatMap((p) => [p[1], p[2]])) * 1.12;
        points.forEach((p, index) => {
          if (!Number.isFinite(p[1]) || !Number.isFinite(p[2])) return;
          ctx.globalAlpha = 0.2 + 0.8 * (index + 1) / points.length; ctx.fillStyle = color;
          ctx.beginPath(); ctx.arc(x(p[1] / maximum), y(p[2] / maximum), index === points.length - 1 ? 4 : 2, 0, Math.PI * 2); ctx.fill();
        });
        ctx.globalAlpha = 1;
      } else if (mode === "qam16") {
        label("Carrier-corrected I (real) →");
        ctx.save(); ctx.translate(13, (top + bottom) / 2); ctx.rotate(-Math.PI / 2); ctx.fillText("Q (imaginary) →", 0, 0); ctx.restore();
        const scale = Math.min(w, h) / 8;
        const mx = (value: number) => (left + right) / 2 + value * scale;
        const my = (value: number) => (top + bottom) / 2 - value * scale;
        for (const value of [-4, -2, 0, 2, 4]) {
          line(mx(value), my(-4), mx(value), my(4));
          line(mx(-4), my(value), mx(4), my(value));
        }
        for (const [i, q, text] of diagnostics?.constellation ?? []) {
          ctx.strokeStyle = dim; ctx.beginPath(); ctx.arc(mx(i), my(q), 5, 0, Math.PI * 2); ctx.stroke();
          ctx.fillStyle = dim; ctx.textAlign = "center"; ctx.fillText(text, mx(i), my(q) + 15);
        }
        points.forEach((p, index) => {
          if (!Number.isFinite(p[1]) || !Number.isFinite(p[2])) return;
          ctx.globalAlpha = 0.2 + 0.8 * (index + 1) / points.length; ctx.fillStyle = color;
          ctx.beginPath(); ctx.arc(mx(Math.max(-4, Math.min(4, p[1]))), my(Math.max(-4, Math.min(4, p[2]))), index === points.length - 1 ? 4 : 2, 0, Math.PI * 2); ctx.fill();
        }); ctx.globalAlpha = 1;
      } else {
        label("Phase change · real component →");
        ctx.save(); ctx.translate(13, (top + bottom) / 2); ctx.rotate(-Math.PI / 2); ctx.fillText("Imaginary component →", 0, 0); ctx.restore();
        const scale = Math.min(w, h) / 2.8;
        const mx = (value: number) => (left + right) / 2 + value * scale, my = (value: number) => (top + bottom) / 2 - value * scale;
        for (let i = -1; i <= 1; i += 0.5) { line(mx(i), my(-1.4), mx(i), my(1.4)); line(mx(-1.4), my(i), mx(1.4), my(i)); }
        ctx.setLineDash([3, 4]); line(mx(-1.3), my(-1.3), mx(1.3), my(1.3), dim); line(mx(-1.3), my(1.3), mx(1.3), my(-1.3), dim); ctx.setLineDash([]);
        const refs: [number, number, string][] = [[1, 0, "01 · 0°"], [0, 1, "00 · 90°"], [-1, 0, "10 · 180°"], [0, -1, "11 · 270°"]];
        refs.forEach(([i, q, text]) => {
          ctx.strokeStyle = dim; ctx.beginPath(); ctx.arc(mx(i), my(q), 6, 0, Math.PI * 2); ctx.stroke();
          ctx.fillStyle = dim; ctx.textAlign = i < 0 ? "left" : i > 0 ? "right" : "center";
          ctx.fillText(text, mx(i), my(q) + (q < 0 ? 16 : -11));
        });
        points.forEach((p, index) => {
          if (!Number.isFinite(p[1]) || !Number.isFinite(p[2])) return;
          ctx.globalAlpha = 0.2 + 0.8 * (index + 1) / points.length; ctx.fillStyle = color;
          ctx.beginPath(); ctx.arc(mx(Math.max(-1.4, Math.min(1.4, p[1]))), my(Math.max(-1.4, Math.min(1.4, p[2]))), index === points.length - 1 ? 4 : 2, 0, Math.PI * 2); ctx.fill();
        }); ctx.globalAlpha = 1;
      }
      if (!last) { ctx.fillStyle = ink; ctx.textAlign = "center"; ctx.fillText("Waiting for received symbols", (left + right) / 2, (top + bottom) / 2 + 4); }
    }
    paint();
    const resize = new ResizeObserver(paint); resize.observe(element);
    const theme = new MutationObserver(paint); theme.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => { resize.disconnect(); theme.disconnect(); };
  }, [diagnostics, endpoint, view, mode, last]);

  return <section className={`panel receiver-card ${endpoint}`} aria-label={`${names[endpoint]} receiver diagnostics`}>
    <div className="panel-head"><div className="name"><span className="dot" /><h2>{names[endpoint]} receiver</h2></div><span className="small">{mode === "fsk" ? "One bit per symbol" : mode === "qam16" ? "Four bits per symbol" : "Two bits per symbol"}</span></div>
    <div className="diagnostic-plot"><canvas ref={canvas} role="img" aria-label={`${names[endpoint]} ${view === "eye" ? "receiver timing view" : mode === "fsk" ? "received tone energy symbols" : mode === "qam16" ? "received 16-QAM constellation" : "received differential phase constellation"}`} /></div>
    <p className="diagnostic-explanation">{explanation}</p>
    <div className="readout"><span className={diagnostics?.timing_locked ? "locked" : ""}>{diagnostics?.timing_locked ? "Sampling locked" : "No symbol timing lock"}</span>{diagnostics?.symbol_samples && <span>{(48000 / diagnostics.symbol_samples).toFixed(0)} symbols/s</span>}{last && <span>Latest {mode === "fsk" ? `bit ${last[3]}` : mode === "qam16" ? `quadbit ${last[3].toString(2).padStart(4, "0")}` : `dibit ${["00", "01", "11", "10"][last[3]] ?? "?"}`} · {(last[4] * 100).toFixed(0)}% confidence</span>}</div>
    <p className="diagnostic-note">{diagnostics?.timing_note || "Start the call to see decisions measured from incoming audio."}</p>
  </section>;
}

export function ReceiverDiagnosticsPanel({ diagnostics }: { diagnostics?: Record<Endpoint, ReceiverDiagnostics> }) {
  const [view, setView] = useState<View>("symbols");
  return <section className="receiver-diagnostics" aria-label="Receiver diagnostics">
    <div className="section-title"><h2>Inside the receivers</h2><label className="diagnostic-selector">View <select aria-label="Receiver diagnostic view" value={view} onChange={(e) => setView(e.target.value as View)}><option value="symbols">Symbol decisions</option><option value="eye">Timing / eye</option></select></label><span>Live measurements · brighter points are newer</span></div>
    <div className="pair">{(["caller", "answerer"] as Endpoint[]).map((endpoint) => <ReceiverView key={endpoint} endpoint={endpoint} diagnostics={diagnostics?.[endpoint]} view={view} />)}</div>
  </section>;
}
