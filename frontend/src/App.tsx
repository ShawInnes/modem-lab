import { useCallback, useEffect, useRef, useState } from "react";
import { ReceiverDiagnosticsPanel } from "./diagnostics";
import { AudioMonitor } from "./audio";
import {
  decodePacket,
  type Config,
  type Endpoint,
  type LabEvent,
  type SessionState,
} from "./protocol";
import {
  SignalStore,
  Spectrogram,
  PlotViewport,
  PlotNavigation,
} from "./plots";
const emptyEndpoint = {
  state: "idle",
  carrier_lock: false,
  confidence: 0,
  framing_errors: 0,
  queued: 0,
};
const initial: SessionState = {
  type: "state",
  generation: 0,
  sample_index: 0,
  active: false,
  config: {
    snr_db: 30,
    delay_ms: 35,
    echo_attenuation_db: 18,
    bandpass: "telephone",
    seed: 1,
  },
  endpoints: { caller: emptyEndpoint, answerer: emptyEndpoint },
  metrics: { processing_ms: 0, overruns: 0, display_gaps: 0 },
};
const names: Record<Endpoint, string> = {
  caller: "Caller",
  answerer: "Answerer",
};
function char(byte: number) {
  if (byte === 10) return "\n";
  if (byte === 13) return "";
  if (byte === 9) return "\t";
  return byte >= 32 && byte < 127
    ? String.fromCharCode(byte)
    : `⟨${byte.toString(16).padStart(2, "0")}⟩`;
}
export default function App() {
  const [state, setState] = useState(initial),
    [connection, setConnection] = useState("Connecting"),
    [error, setError] = useState(""),
    [theme, setTheme] = useState(
      () => localStorage.getItem("modem-theme") || "dark",
    );
  const [events, setEvents] = useState<LabEvent[]>([]),
    [selected, setSelected] = useState<LabEvent | null>(null),
    [received, setReceived] = useState<Record<Endpoint, string>>({
      caller: "",
      answerer: "",
    }),
    [local, setLocal] = useState<Record<Endpoint, string>>({
      caller: "",
      answerer: "",
    }),
    [text, setText] = useState<Record<Endpoint, string>>({
      caller: "",
      answerer: "",
    }),
    [views, setViews] = useState({ caller: 0, answerer: 1 }),
    [listener, setListener] = useState(0),
    [hearSetup, setHearSetup] = useState(true),
    [autoChat, setAutoChat] = useState(false),
    [audioStatus, setAudioStatus] = useState({
      status: "muted",
      underruns: 0,
      bufferMs: 0,
      sourceSample: 0,
    }),
    [seed, setSeed] = useState(103),
    [lastApply, setLastApply] = useState("");
  const autoPending = useRef(false),
    autoActual = useRef(false),
    seedLoaded = useRef(false),
    active = useRef(false);
  const socket = useRef<WebSocket | null>(null),
    counter = useRef(0),
    generation = useRef(0),
    pending = useRef(
      new Map<string, { type: string; endpoint?: Endpoint; text?: string }>(),
    );
  const [store] = useState(() => new SignalStore()),
    [audio] = useState(() => new AudioMonitor()),
    [viewport] = useState(() => new PlotViewport()),
    [, updateNavigation] = useState(0);
  const onNavigate = useCallback(() => {
    setSelected(null);
    updateNavigation((value) => value + 1);
  }, []);
  const command = useCallback(
    (type: string, extra: Record<string, unknown> = {}) => {
      if (socket.current?.readyState !== WebSocket.OPEN) {
        setError(
          "The local server is disconnected. Reconnect before sending commands.",
        );
        return false;
      }
      if (pending.current.size >= 64) {
        setError(
          "Too many commands awaiting acknowledgment. Wait for the server or reconnect.",
        );
        return false;
      }
      if (type === "hang_up") {
        active.current = false;
        audio.stop();
      }
      const id = `c${++counter.current}`;
      pending.current.set(id, {
        type,
        endpoint: extra.endpoint as Endpoint | undefined,
        text: extra.text as string | undefined,
      });
      socket.current.send(
        JSON.stringify({ version: 1, command_id: id, type, ...extra }),
      );
      return true;
    },
    [audio],
  );
  const clock = useCallback(
    () =>
      audio.stats.status === "playing"
        ? audio.stats.sourceSample
        : store.latest,
    [audio, store],
  );
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("modem-theme", theme);
  }, [theme]);
  useEffect(() => {
    const origin = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}`;
    const control = new WebSocket(`${origin}/ws/control`);
    socket.current = control;
    let data: WebSocket | null = null;
    let disposed = false;
    let sessionId = "";
    let retries = 0;
    let retryTimer = 0;
    function reset(g: number) {
      generation.current = g;
      store.reset(g);
      viewport.reset();
      audio.reset(g);
      setSelected(null);
      setEvents([]);
      setReceived({ caller: "", answerer: "" });
      setLocal({ caller: "", answerer: "" });
    }
    function openData() {
      if (disposed || control.readyState !== WebSocket.OPEN) return;
      data = new WebSocket(
        `${origin}/ws/data/${encodeURIComponent(sessionId)}`,
      );
      const current = data;
      current.binaryType = "arraybuffer";
      current.onopen = () => {
        setConnection("Connected");
        if (retries) setError("");
      };
      current.onmessage = (e) => {
        try {
          const p = decodePacket(e.data);
          if (current.readyState === WebSocket.OPEN)
            current.send(
              JSON.stringify({
                type: "credit",
                generation: p.generation,
                sequence: p.sequence,
              }),
            );
          if (p.generation !== generation.current) return;
          store.push(p);
          if (active.current)
            audio.push(p.streams, p.startSample, p.generation);
        } catch (e) {
          setError(`Signal transport: ${String(e)}`);
        }
      };
      current.onclose = () => {
        if (!disposed && control.readyState === WebSocket.OPEN) {
          audio.stop();
          if (retries < 3) {
            setConnection("Rebuffering");
            setError(
              "Signal connection interrupted; reconnecting presentation. The modems continue.",
            );
            retryTimer = window.setTimeout(openData, 500 * ++retries);
          } else {
            setConnection("Signal disconnected");
            setError(
              "Signal reconnection failed. Reload to create a new session.",
            );
          }
        }
      };
    }
    control.onopen = () => {
      setConnection("Connected");
      setError("");
    };
    control.onmessage = (message) => {
      try {
        const m = JSON.parse(message.data);
        if (m.type === "hello") {
          reset(m.generation);
          sessionId = m.session_id;
          openData();
        } else if (m.type === "state") {
          if (m.generation < generation.current) return;
          if (m.generation > generation.current) reset(m.generation);
          active.current = m.active;
          autoActual.current = Boolean(m.auto_chat_enabled);
          if (!autoPending.current) setAutoChat(autoActual.current);
          setState(m);
          if (!seedLoaded.current) {
            setSeed(m.config.seed);
            seedLoaded.current = true;
          }
          if (!m.active) audio.stop();
        } else if (m.type === "ack") {
          const request = pending.current.get(m.command_id);
          pending.current.delete(m.command_id);
          if (request?.type === "auto_chat") {
            autoPending.current = false;
            if (!m.ok) setAutoChat(autoActual.current);
          }
          if (!m.ok) {
            setError(m.error || "Command rejected");
            return;
          }
          setError("");
          if (request?.type === "configure")
            setLastApply(`Applied at ${(m.sample_index / 48000).toFixed(3)} s`);
        } else if (m.type === "event") {
          if (m.generation < generation.current) return;
          if (m.generation > generation.current) reset(m.generation);
          setEvents((prev) => [...prev, m].slice(-500));
          if (m.endpoint === "caller" || m.endpoint === "answerer") {
            const e = m.endpoint as Endpoint;
            if (m.event_type === "decoded_byte") {
              const byte = Number(m.detail);
              if (Number.isInteger(byte) && byte >= 0 && byte < 256)
                setReceived((prev) => ({
                  ...prev,
                  [e]: (prev[e] + char(byte)).slice(-8192),
                }));
            } else if (
              [
                "text_queued",
                "transmit_started",
                "disconnected",
                "framing_error",
              ].includes(m.event_type)
            ) {
              const label =
                m.event_type === "text_queued"
                  ? "QUEUED"
                  : m.event_type === "transmit_started"
                    ? "TX STARTED"
                    : m.event_type === "disconnected"
                      ? "CANCELLED / DISCONNECTED"
                      : "FRAMING ERROR";
              setLocal((prev) => ({
                ...prev,
                [e]: (prev[e] + `${label} · ${m.detail}\n`).slice(-8192),
              }));
            }
          }
        } else if (m.type === "error") {
          setError(m.error || "The session stopped");
          audio.stop();
        }
      } catch (e) {
        setError(`Control transport: ${String(e)}`);
      }
    };
    control.onerror = () =>
      setError(
        "Cannot reach the local server. Check that the workbench server is running.",
      );
    control.onclose = () => {
      if (!disposed) {
        setConnection("Disconnected");
        audio.stop();
        setError("Connection closed. Reload to create a new session.");
      }
    };
    const timer = window.setInterval(
      () => setAudioStatus({ ...audio.stats }),
      250,
    );
    return () => {
      disposed = true;
      clearTimeout(retryTimer);
      clearInterval(timer);
      data?.close();
      control.close();
      audio.close();
    };
  }, [audio, store, viewport]);
  const configure = (patch: Partial<Config>) =>
    command("configure", { config: patch });
  const listen = async (value: number) => {
    try {
      if (value) await audio.enable();
      audio.setStream(value);
      setListener(value);
      setError("");
    } catch (e) {
      setError(`Audio could not start: ${String(e)}`);
    }
  };
  const submit = (endpoint: Endpoint) => {
    const value = text[endpoint];
    if (!value) return;
    if (/[^\x00-\x7f]/.test(value)) {
      setError(
        "Use 7-bit ASCII text. Accents and emoji cannot be transmitted by this profile.",
      );
      return;
    }
    if (value.length > 4096) {
      setError("Send at most 4,096 characters at a time.");
      return;
    }
    command("send_text", { endpoint, text: value });
    setText((prev) => ({ ...prev, [endpoint]: "" }));
  };
  return (
    <main className="workbench">
      <header>
        <div>
          <div className="eyebrow">SIGNAL WORKBENCH / LOCAL SESSION</div>
          <h1>Modem Lab</h1>
          <p>Two endpoints. One phone line. Every exchange visible.</p>
        </div>
        <div className="header-right">
          <span className={`badge ${state.active ? "live" : ""}`}>
            {state.active ? "LIVE" : "IDLE"} · {connection}
          </span>
          <button
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            aria-label={`Use ${theme === "dark" ? "light" : "dark"} appearance`}
          >
            {theme === "dark" ? "☀ Light" : "☾ Dark"}
          </button>
        </div>
      </header>
      <div className="toolbar">
        <label>
          Profile{" "}
          <select aria-label="Modem profile" value={state.actual_profile ?? "bell103"}
            disabled={connection !== "Connected"}
            onChange={(e) => command("select_profile", {profile: e.target.value})}>
            <option value="bell103">Bell 103 · 300 bit/s · functional FSK</option>
            <option value="dqpsk1200">1200 bit/s · 600 baud · experimental DQPSK</option>
            <option value="qam2400">V.22bis-style · 2400 bit/s · 600 baud · experimental 16-QAM</option>
          </select>
        </label>
        <button
          className="primary"
          disabled={connection !== "Connected" || state.active}
          onClick={() => {
            if (hearSetup && listener === 0) void listen(3);
            command("start");
          }}
        >
          ▶ Start call
        </button>
        <label className="hear-setup auto-chat"><input type="checkbox" aria-label="Auto chat"
          checked={autoChat} disabled={connection !== "Connected" || autoPending.current}
          onChange={(e) => {
            const enabled = e.target.checked;
            autoPending.current = true;
            setAutoChat(enabled);
            if (!command("auto_chat", { enabled })) {
              autoPending.current = false;
              setAutoChat(autoActual.current);
              return;
            }
            if (enabled && !state.active) {
              if (hearSetup && listener === 0) void listen(3);
              command("start");
            }
          }} /> Auto chat</label>
        <label className="hear-setup"><input type="checkbox" aria-label="Hear call setup" checked={hearSetup}
          onChange={(e) => setHearSetup(e.target.checked)} /> Hear call setup</label>
        <button
          disabled={connection !== "Connected" || !state.active}
          onClick={() => command("hang_up")}
        >
          Hang up
        </button>
        <button
          disabled={connection !== "Connected"}
          onClick={() => {
            if (hearSetup && listener === 0) void listen(3);
            command("configure", { config: { seed: Math.trunc(seed) } });
            command("restart");
          }}
        >
          ↻ Restart
        </button>
        <label>
          Listen{" "}
          <select
            aria-label="Listen to signal"
            value={listener}
            onChange={(e) => void listen(Number(e.target.value))}
          >
            {[
              "Muted",
              "Caller transmit",
              "Answerer transmit",
              "Combined line",
              "Caller receive",
              "Answerer receive",
            ].map((label, i) => (
              <option key={i} value={i}>
                {label}
              </option>
            ))}
          </select>
        </label>
        {listener !== 0 && (
          <button onClick={() => void listen(listener)}>
            Enable / resume audio
          </button>
        )}
      </div>
      <div className="fidelity">
        {state.actual_profile === "qam2400"
          ? "Experimental V.22bis-style 16-QAM · 4 bits/symbol · simplified shaping/handshake · hardware interoperability unverified"
          : state.actual_profile === "dqpsk1200"
          ? "Experimental V.22-style differential QPSK · 2 bits/symbol · simplified shaping/handshake · hardware interoperability unverified"
          : "Real FSK modulation and receiver decoding · answer-first carrier handshake · hardware interoperability unverified"}
        <span> · Changing profile starts a fresh session and clears queued text.</span>
      </div>
      <div className="call-progress" role="status" aria-label="Call progress">
        <strong>{!state.active ? "Call idle" : Object.values(state.endpoints).some((e) => e.call_stage === "failed") ? "Call failed" : Object.values(state.endpoints).every((e) => e.transmit_ready) ? "Call connected" : "Call setup"}</strong>
        {(["caller", "answerer"] as Endpoint[]).map((endpoint) => <span key={endpoint}>
          {names[endpoint]}: {state.active ? (state.endpoints[endpoint].call_stage ?? state.endpoints[endpoint].state).replaceAll("_", " ") : "ready to call"}
        </span>)}
        {autoChat && <span className="auto-chat-status" aria-label="Auto chat status">Auto chat: {state.auto_chat_enabled ? state.auto_chat_status : "Starting"}</span>}
        <small>Dial / ring / pickup sounds illustrate the phone exchange. Carrier replies and receiver lock come from received audio.</small>
      </div>
      {error && (
        <div className="notice" role="alert">
          {error}
        </div>
      )}
      <div className="body">
        <PlotNavigation
          store={store}
          viewport={viewport}
          onNavigate={onNavigate}
        />
        <div className="pair">
          {(["caller", "answerer"] as Endpoint[]).map((endpoint) => {
            const e = state.endpoints[endpoint];
            return (
              <section className={`panel ${endpoint}`} key={endpoint}>
                <div className="panel-head">
                  <div className="name">
                    <span className="dot" />
                    <h2>
                      {endpoint === "caller" ? "A" : "B"} / {names[endpoint]}
                    </h2>
                  </div>
                  <select
                    aria-label={`${names[endpoint]} signal view`}
                    value={views[endpoint]}
                    onChange={(event) =>
                      setViews((prev) => ({
                        ...prev,
                        [endpoint]: Number(event.target.value),
                      }))
                    }
                  >
                    <option value={endpoint === "caller" ? 0 : 1}>
                      Transmitted signal
                    </option>
                    <option value={endpoint === "caller" ? 2 : 3}>
                      Received signal
                    </option>
                  </select>
                </div>
                <div className="plot">
                  <Spectrogram
                    store={store}
                    stream={views[endpoint]}
                    cursor={selected?.sample_index ?? null}
                    clock={clock}
                    viewport={viewport}
                    onNavigate={onNavigate}
                    label={names[endpoint]}
                  />
                </div>
                <div className="readout">
                  <span className={e.carrier_lock ? "locked" : ""}>
                    {e.state.replaceAll("_", " ")}
                  </span>
                  <span>Carrier {e.carrier_lock ? "locked" : "unlocked"}</span>
                  <span>Confidence {e.confidence.toFixed(2)}</span>
                  <span>Framing errors {e.framing_errors}</span>
                </div>
              </section>
            );
          })}
        </div>
        <div className="pair terminal-pair">
          {(["caller", "answerer"] as Endpoint[]).map((endpoint) => (
            <section className={`panel terminal ${endpoint}`} key={endpoint}>
              <div className="panel-head">
                <div className="name">
                  <span className="dot" />
                  <h2>{names[endpoint]} terminal</h2>
                </div>
                <span className="small">
                  {state.endpoints[endpoint].queued} queued
                </span>
              </div>
              <div className="terminal-label">
                RX / decoded from received samples
              </div>
              <pre
                className="rx"
                tabIndex={0}
                aria-label={`${names[endpoint]} received text`}
              >
                {received[endpoint] || "Waiting for decoded text…"}
              </pre>
              <details>
                <summary>Local transmit log</summary>
                <pre className="tx">
                  {local[endpoint] || "No local text queued."}
                </pre>
              </details>
              <form
                className="entry"
                onSubmit={(e) => {
                  e.preventDefault();
                  submit(endpoint);
                }}
              >
                <input
                  aria-label={`Text from ${endpoint}`}
                  placeholder="7-bit ASCII text to send"
                  value={text[endpoint]}
                  onChange={(e) =>
                    setText((prev) => ({ ...prev, [endpoint]: e.target.value }))
                  }
                  maxLength={4096}
                />
                <button disabled={connection !== "Connected"}>
                  {state.active ? "Send" : "Queue"}
                </button>
              </form>
              <div className="terminal-hint">
                8N1 · 7-bit ASCII · queued before carrier lock · Hang up cancels
                pending text
              </div>
            </section>
          ))}
        </div>
        <ReceiverDiagnosticsPanel diagnostics={state.diagnostics} />
        <section className="panel inspector">
          <div className="panel-head">
            <h2>Carrier & event inspector</h2>
            <div className="legend">
              <span>−90 dBFS</span>
              <i />
              <span>0 dBFS</span>
            </div>
          </div>
          <div className="inspection">
            <div className="clock">
              {(
                (selected?.sample_index ??
                  (viewport.end === null
                    ? clock()
                    : viewport.range(store).end)) / 48000
              ).toFixed(2)}{" "}
              <small>s</small>
            </div>
            <div>
              <strong>
                {selected
                  ? `${names[selected.endpoint] || "Line"} · ${selected.event_type.replaceAll("_", " ")}`
                  : viewport.end === null
                    ? "Following the live sample clock"
                    : "Inspecting signal history"}
              </strong>
              <p>
                {selected
                  ? selected.detail
                  : "Zoom or pan either graph, or select an event. Both graphs stay aligned while the modems keep running."}
              </p>
              <p className="small">
                {selected && selected.sample_index < store.earliest
                  ? "This event is older than the retained five-minute signal history. "
                  : ""}
                Signal history inspection; receiver diagnostics below the terminals always show the live receiver.
              </p>
            </div>
            {selected && (
              <button
                onClick={() => {
                  viewport.followLive();
                  onNavigate();
                }}
              >
                Follow live
              </button>
            )}
          </div>
          <div className="event-list" aria-label="Session events">
            {events.length === 0 ? (
              <p className="empty">
                Queue a message, then start a call to see carrier acquisition
                and data events.
              </p>
            ) : (
              events
                .slice()
                .reverse()
                .map((event, i) => (
                  <button
                    key={`${event.sample_index}-${events.length - i}-${event.endpoint}`}
                    className={`event ${event.endpoint} ${selected === event ? "selected" : ""}`}
                    onClick={() => {
                      viewport.focus(event.sample_index, store);
                      updateNavigation((value) => value + 1);
                      setSelected(event);
                    }}
                  >
                    <time>{(event.sample_index / 48000).toFixed(3)} s</time>
                    <span>{names[event.endpoint] || "Line"}</span>
                    <span>{event.event_type.replaceAll("_", " ")}</span>
                    <span className="event-detail">
                      {event.event_type === "decoded_byte"
                        ? `byte ${event.detail} · ${char(Number(event.detail))}`
                        : event.detail}
                    </span>
                  </button>
                ))
            )}
          </div>
        </section>
        <section className="line-controls" aria-label="Phone line controls">
          <div className="section-title">
            <h2>Phone line</h2>
            <span>
              Symmetric · changes apply on the next sample block{" "}
              {lastApply && `· ${lastApply}`}
            </span>
          </div>
          <div className="controls">
            {(
              [
                {
                  key: "snr_db",
                  label: "Signal-to-noise ratio",
                  unit: "dB",
                  min: -20,
                  max: 60,
                  note: "Noise uses a fixed reference level, including silence.",
                },
                {
                  key: "delay_ms",
                  label: "One-way delay",
                  unit: "ms",
                  min: 0,
                  max: 250,
                  note: "Remote propagation in each direction.",
                },
                {
                  key: "echo_attenuation_db",
                  label: "Echo attenuation",
                  unit: "dB",
                  min: 0,
                  max: 60,
                  note: "Higher attenuation means weaker local echo.",
                },
              ] as const
            ).map((c) => (
              <label key={c.key}>
                {c.label}
                <output>
                  {state.config[c.key]} {c.unit}
                </output>
                <input
                  aria-label={c.label}
                  type="range"
                  min={c.min}
                  max={c.max}
                  value={state.config[c.key]}
                  onChange={(e) =>
                    configure({ [c.key]: Number(e.target.value) })
                  }
                />
                <small>{c.note}</small>
              </label>
            ))}
          </div>
          <div className="line-options">
            <label>
              Bandpass{" "}
              <select
                aria-label="Bandpass"
                value={state.config.bandpass}
                onChange={(e) => configure({ bandpass: e.target.value })}
              >
                <option value="telephone">Telephone · 300–3400 Hz</option>
                <option value="flat">No bandpass</option>
                <option value="narrow">Narrow · 900–2400 Hz</option>
              </select>
            </label>
            <label>
              Noise seed{" "}
              <input
                type="number"
                min="0"
                max="4294967295"
                value={seed}
                onChange={(e) =>
                  setSeed(
                    Math.max(
                      0,
                      Math.min(4294967295, Number(e.target.value) || 0),
                    ),
                  )
                }
              />
            </label>
            <span>
              Seed applies on Restart. Restart clears text and inspection
              history. Active seed: {state.actual_seed ?? state.config.seed}.
            </span>
          </div>
        </section>
      </div>
      <footer>
        <span>48,000 samples/s · 960 samples/block · 20 ms · LIVE engine</span>
        <span>
          Audio: {audioStatus.status} · buffer {audioStatus.bufferMs.toFixed(0)}{" "}
          ms · underruns {audioStatus.underruns}
        </span>
        <span>
          DSP {state.metrics.processing_ms.toFixed(1)} ms · overruns{" "}
          {state.metrics.overruns} · display gaps{" "}
          {state.metrics.display_gaps + store.gaps}
        </span>
        <span>
          Live experimentation · hidden tabs rebuffer audio on return
        </span>
        <span>
          Sample {state.sample_index.toLocaleString()} · generation{" "}
          {state.generation}
        </span>
      </footer>
    </main>
  );
}
