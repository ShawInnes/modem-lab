# Modem Lab — Build Specification

## Build instruction

Build a local interactive modem laboratory using this specification and the adjacent `modem-lab-mockup.html` as the visual reference. Implement the real 300-bit/s milestone first, then add recording/replay and receiver diagnostics. Treat higher-speed modem standards as separate future milestones. Deliver a working application, automated verification of core DSP behavior, and instructions to run it on macOS and Linux.

The HTML reference is an interactive visual prototype, not an existing modem implementation. Preserve its layout and interaction intent while replacing generated spectrogram artwork and simulated text forwarding with actual engine outputs. Its initial V.32bis selection, timing, power readings, and waveform shapes are illustrative. The first working app must default to Bell 103 at 300 bit/s and clearly label any illustrative profiles.

## Product goal

Recreate the experience of two dial-up modems establishing a connection and exchanging text. Make otherwise invisible behavior inspectable: who is transmitting, what each receiver hears, what each endpoint is doing, and why the connection succeeds or fails.

The user can start a call, hear modem tones, watch aligned spectrograms, type at either terminal, degrade the simulated phone line, and inspect a recorded exchange. This is a learning and nostalgia tool, initially running entirely on one computer without real telephone hardware or an SDR.

## Scope and fidelity

### Initial functional release

- Two independent Bell 103-style endpoints: caller and answerer.
- Genuine audio FSK modulation and demodulation, simultaneous bidirectional transmission, asynchronous character framing, and receiver-derived decoded text.
- A causal simulated telephone channel with noise, filtering, propagation delay, and self-echo.
- Explicit carrier detection and synchronization states driven by received signals. Document the implemented startup behavior and any simplification relative to original hardware.
- Live transmitted/received spectrograms, audio monitoring, terminal panes, and a timestamped event timeline.
- Recording and synchronized replay; recording/replay may ship as the second implementation milestone.

### Fidelity labels

Every profile declares `functional`, `illustrative`, or `experimental`. Functional means that real generated samples are decoded by receivers; it does not automatically mean complete standards compliance or hardware interoperability. State precisely which signaling, framing, and startup procedures are implemented.

An illustrative V.32bis walkthrough may retain the reference experience, but must display “Illustrative handshake — not a working V.32bis modem.” Never present scripted tones, predetermined state transitions, or direct text forwarding as successful real modulation/demodulation.

### Future milestones

V.22 at 1200 bit/s, V.22bis at 2400 bit/s, then potentially V.32/V.32bis. These require separate reviewed designs, standard-specific startup sequences and interoperability checks. V.34/V.90, error-control protocols, modem compression, physical phone interfaces, and BBS bridging are outside the initial release. Do not synthesize a generic QAM waveform and label it a compliant modem.

## UI reference and behavior

Use a restrained instrument-workbench appearance: neutral surfaces, clear typography, monospaced measurements and terminal text. Caller uses cyan/blue; answerer uses amber/orange. Maintain these identities in signal marks and labels. Support light/dark appearance and stack panels on narrow screens.

### Session toolbar

- Profile selector lists supported profiles with fidelity labels and supported speeds.
- Start call / pause replay / resume replay / hang up, with wording appropriate to the current session state. Pausing a simulation is distinct from hanging up a connection.
- Restart creates a new run using the current configuration and seed.
- Listen selector: muted, caller transmit, answerer transmit, combined line, caller receive, answerer receive. A user gesture enables browser audio.
- Playback speed for replay: 0.25×, 0.5×, 1×, 2×. Default audio is available at 1×; other speeds are muted with an explicit notice until resampling is implemented.
- Session modes: live, paused, replay. Display actual profile and negotiated rate rather than a fixed success value.

### Endpoint panels

Two panels share identical frequency and time scales and one inspection cursor. Each has:

- Endpoint name and caller/answerer identity.
- Signal selector: transmitted or received.
- Frequency axis in kHz, time axis in seconds, and a signal-power color legend in dBFS.
- Live endpoint state, carrier lock, and useful receiver diagnostics when implemented.
- Display-only sample timestamp and audio status available in a compact diagnostics area.

Show the same rolling time range on both panels; do not independently autoscale their color ranges. Use a configurable common default range, such as −90 to 0 dBFS. Avoid dBm unless a physical impedance/voltage calibration actually exists. Calculate and document the FFT normalization and distinguish relative visualization levels from calibrated measurements.

The spectra must originate from the selected engine sample stream. Received views include channel noise, distortion, remote transmission, and local echo as modeled. Switching views does not alter the simulation.

### Handshake and event inspector

- Display the actual profile-specific stages; do not impose the five-stage V.32bis prototype on Bell 103.
- Timestamp events with endpoint, event type, and concise explanation.
- Clicking a stage/event selects the corresponding replay time and moves both plot cursors.
- Timeline scrubbing pauses playback and changes inspection position. It must not mutate live modem state.
- Show who is sending, who is listening, and the receiver's current task.
- For Bell 103, plausible states include idle, waiting for carrier, acquiring timing, connected, carrier lost, and disconnected. Transmit and receive readiness can differ.
- Richer training/rate-negotiation stages appear only in profiles that implement or explicitly illustrate them.

### Phone-line controls

- SNR in dB, one-way delay in ms, echo attenuation in dB, line bandpass preset, and deterministic noise seed.
- Label direction-specific settings when the channel is asymmetric. Initial controls may apply symmetrically.
- Higher echo attenuation means weaker echo; make this clear beside the control.
- Apply changes at defined sample-block boundaries and record their timestamps. Avoid audio clicks for level changes with a short ramp; preserve channel/filter history where valid.
- SNR has a documented reference signal level, including behavior during silence. Noise must not vanish whenever a transmitter stops.
- Changing profile ends/restarts the session; it is not a silent in-place change.
- High noise may cause wrong characters or lost carrier. Do not fabricate perfect output in adverse conditions.

### Terminal panes

- One terminal per endpoint; local transmission and receiver-decoded text are visibly distinguished.
- Queue text before connection, show queued status, and actually transmit it after the link becomes ready. Provide a clear pending-text cancellation behavior on hangup.
- Enforce/document the initial encoding, preferably 7-bit ASCII in 8N1 frames with the high bit zero. Unsupported characters produce validation feedback.
- Sent text only appears in the remote receive log after its framed bits traverse modulation, channel, and demodulation.
- Show framing errors and carrier loss without claiming that every wrong byte can be detected. 8N1 provides no checksum.
- Start with plain terminal panes; use xterm.js only if terminal emulation/ANSI sequences become a requirement.

### Footer and diagnostics

Display sample rate, block duration, session mode, buffer health, and recorded duration. Distinguish audio underruns, server processing lag, and receiver decoding errors. UI display slowdown must not alter simulated line quality.

## Recommended stack

| Component | Technology | Responsibility |
| --- | --- | --- |
| DSP | Python, NumPy, SciPy | Stateful modulators, receivers, filters, channel, FFT |
| Local API | FastAPI, Uvicorn | Static UI, session control, WebSocket transport |
| Front end | TypeScript, Vite, React | Controls, session state, inspector, terminal panes |
| Spectrogram | Canvas 2D | Incremental raster drawing and cursor overlays |
| Browser audio | Web Audio API, AudioWorklet | Buffered PCM playback and playback position |
| Research | Jupyter, Matplotlib | Offline experiments using the same engine package |
| Verification | pytest; browser test tooling | DSP correctness, transport, UI/audio behavior |

Use native WebSockets initially. No database, Redis, message broker, WebRTC, cloud service, or authentication system is needed for the localhost single-user release. Keep the engine reusable without the web server. Consider Numba or compiled code only after profiling demonstrates a bottleneck. Physical audio through python-sounddevice is a later optional adapter.

## Engine architecture

### Core contract

Provide an offline-callable engine interface equivalent to:

```python
engine = SessionEngine(config)
engine.enqueue_text(endpoint="caller", text="Hello")
result = engine.process(block_frames=960)
# result: start sample, endpoint TX/RX arrays, decoded data, events
```

The core must not depend on wall-clock sleep, browser APIs, network connections, or sound devices. Advance by sample count. The live adapter paces processing; offline tests run faster than real time using the identical engine.

Each endpoint contains separate TX and RX state. Preserve oscillator phase, partial symbols/characters, timing recovery, filter history, detection thresholds, and any future adaptive state between blocks. Never initialize the modem separately for each block.

### Initial Bell 103 signal plan

- Caller transmit: mark/1 at 1270 Hz, space/0 at 1070 Hz.
- Answerer transmit: mark/1 at 2225 Hz, space/0 at 2025 Hz.
- Each receiver listens to the opposite endpoint's band.
- 300 bits/s; initial 8N1 framing, least significant data bit first; idle/stop = mark, start = space.
- At 48 kHz, 160 samples represent a bit. Preserve timing across arbitrary processing block boundaries.
- Use continuous phase between tone changes. Document transmit amplitude and filtering.
- Implement receiver timing acquisition and carrier detection; do not pass transmitter bit boundaries into the receiver as a hidden shortcut.
- Initial carrier acquisition may be a documented simplified Bell 103-style procedure. Hardware-compatible startup must be separately validated before being claimed.

Verify these details against primary protocol references during implementation and record the reference in the project documentation.

### Causal channel

Compute both transmit blocks from endpoint states, then apply the channel, then feed received blocks to the receivers. Never let the order of calling endpoint A/B create an implicit advantage or instantaneous feedback loop.

Model remote propagation, bandpass filtering, deterministic additive noise, and delayed local echo. Delay/filter histories persist across blocks. Events generated from received samples influence subsequent transmission at a documented scheduling boundary. Record this control latency; reduce it if later profiles require finer timing.

Use a seeded RNG. Specify configuration, sample rate, seed, profile version and scheduled commands so an offline rerun reproduces the session.

## Realtime transport and scheduling

### Three separate rates

Initial values, to be measured and tuned:

- Engine: 48,000 samples/s, 960-sample blocks (20 ms).
- Transport: batches every 20–50 ms; small state events can be sent promptly.
- Rendering: requestAnimationFrame, independent of DSP cadence.
- Audio: browser device clock with an initial target buffer of 100–200 ms.
- Spectrogram: 2048-sample Hann window, 480-sample hop; retain overlap across blocks and use explicit window-center sample timestamps.

Run DSP in a dedicated worker process with bounded IPC queues; leave FastAPI's event loop responsive. A worker thread is acceptable for the first measured lightweight version if its behavior is documented. Do not put sustained DSP loops or blocking sleeps inside async WebSocket handlers. The backend live scheduler uses monotonic deadlines to avoid accumulating sleep drift.

### Message contract

Version the wire protocol. A control WebSocket carries JSON commands/events; a data WebSocket carries binary audio/spectral batches so visualization traffic does not queue ahead of controls. Associate both connections with one session ID and generation ID. A simpler single socket is acceptable only if measured latency and queue behavior meet acceptance criteria.

Example command:

```json
{"version":1,"type":"send_text","command_id":"c17","session_id":"s1","endpoint":"caller","text":"Hello"}
```

Example event:

```json
{"version":1,"type":"state_changed","session_id":"s1","generation":1,"sample_index":153600,"endpoint":"answerer","state":"connected"}
```

Binary records include message kind, protocol version, session generation, stream ID, sequence number, start sample, sample rate, frame/column count, data shape, and encoding. Specify byte order and sizes in the implemented protocol document. Use Float32 PCM initially and Float32 dB spectra or documented quantized levels. Browser decoding uses ArrayBuffer and typed arrays; timestamps large enough to exceed 32-bit counts must be represented safely.

Provide acknowledgments for commands, including actual application sample index and validation failures. Ignore stale-generation frames after restart. Validate frame lengths and bound command sizes.

### Audio and visual alignment

- The AudioWorklet consumes a ring buffer, independent of Canvas/React.
- Resample the engine stream to the actual AudioContext sample rate, preserving phase/history. Do not assume the device runs at 48 kHz.
- Report the source-sample position consumed for playback. Use that position to align spectrogram cursors and state inspection with audible output.
- When muted, use the session's simulation/replay position as the display clock.
- React updates controls and labels; high-frequency plot/audio buffers live outside React component state.
- Start audio after a user gesture; expose stopped/suspended/rebuffering states.
- Bound drift using buffer occupancy and pacing/credit between browser and producer. Document clock-rate mismatch handling.
- If the listener changes, switch monitored streams without restarting the modems. Preserve alignment and ramp gains to avoid clicks.

### Backpressure and lifecycle

Bound every queue and ring buffer. Coalesce optional display updates under load, retaining their sample timestamps and indicating any display gaps. Never drop engine input/output internally or make a slow browser corrupt the modem simulation. Record full samples server-side if display updates are omitted.

If audio underflows, output silence and report/rebuffer; never play uninitialized memory. If backlog exceeds the configured limit, explicitly pause/rebuffer or stop the live presentation. Never let latency grow indefinitely. Disconnect releases session resources after a documented grace period. Hidden-tab behavior must be explicit: default to pause/rebuffer presentation on return rather than silently building a backlog.

Bind the local service to loopback by default, check allowed WebSocket origins, and use localhost/HTTPS as required for browser audio features. Support one controlling browser initially; additional viewers are future work.

## Recording and replay

Record configuration, version/seed, command/event log and sample-indexed signal arrays. A simple session directory with JSON metadata/events and chunked NumPy arrays is sufficient. Provide a documented export/import format; do not require arbitrary Python object deserialization.

Replay renders recorded samples and events; it is not rerunning a live endpoint from an arbitrary middle position. Seeking updates both plots, event selection, terminal history, and audio position together. Flush pending playback on seek. No stale pre-seek audio is permitted.

Resuming simulation from a historic point is out of scope unless full engine checkpoints and deterministic command replay are implemented. Label replay and live modes clearly. Stop recording at a configured duration or size limit with an explicit notification.

## Suggested repository structure

```text
backend/modem_lab/
  engine/          # endpoints, profiles, framing, state machines
  dsp/             # oscillators, detectors, filters, spectrum
  channel/         # causal line model
  recording/       # export, import, replay
  transport/       # message schemas and binary framing
  api/             # FastAPI lifecycle and sessions
frontend/src/
  components/      # workbench, endpoint panels, inspector, terminals
  audio/           # worklet, ring buffer, resampling adapter
  plots/           # spectrogram raster and overlays
  transport/       # protocol decoding and commands
notebooks/         # optional DSP experiments
tests/             # engine, framing, channel, transport
docs/              # protocol and fidelity notes
```

## Implementation milestones

1. **Offline modem core:** bidirectional Bell 103 FSK, receiver-derived decoding, framing, seeded channel, sample-based event log. Demonstrate encoded audio and recovered text without a UI.
2. **Live workbench:** real spectra, WebSocket transport, browser sound, controls, accurate endpoint states and text exchange. Preserve the reference visual structure.
3. **Inspector and replay:** record/import, synchronized seek, event inspection, queue/underrun indicators and robust lifecycle.
4. **Deeper receiver diagnostics:** optional symbol decisions, timing lock, error experiments and notebooks using the shared core.
5. **Higher-speed profiles:** separate proposals and tests; illustrative walkthroughs may precede functional implementations if visibly labeled.

Complete and verify each milestone before adding the next protocol family. A full V.32bis implementation is not required to satisfy the initial scope.

## Acceptance criteria

### Signal correctness

- In a clean channel, recover a long known ASCII payload exactly in both directions simultaneously, including repeated characters and varied bit patterns.
- Decode from samples alone with unknown receiver start offset; randomize initial carrier phase and bit alignment.
- Confirm results remain equivalent when processing is divided into different block sizes. No discontinuity at block boundaries.
- Verify configured propagation/echo delay with impulses and verify line filter behavior against its documented response.
- Identical configuration, seed and sample-timestamped inputs reproduce output samples/events on the supported numerical environment.
- Reject unsupported text; report framing errors when present and distinguish them from silently wrong data bits.
- Increasing noise over multiple seeded trials produces statistically worse decoding performance; do not require every individual noisy trial to worsen monotonically.

### UI and transport

- Both plots show actual selected streams with aligned axes, common scale and sample timestamps.
- Send text in both directions while controls remain responsive; remote text appears only after receiver decoding.
- Queued preconnection text is actually sent on connection or explicitly cancelled on hangup.
- Clicking an event/dragging the replay cursor aligns spectra, terminal history and state details.
- During playback, cursor-to-audio alignment targets less than 50 ms on a documented reference machine; measure it rather than infer it from network arrival times.
- Run a 10-minute session without unbounded memory growth or increasing latency. Expose processing overruns and audio underruns.
- Test audio startup, mute/unmute, listener changes, AudioContext suspension, device sample-rate mismatch, tab hiding, disconnect/reconnect and restart with stale frames.
- Inject a stalled renderer/slow data connection: the engine remains deterministic and queues stay bounded; the UI reports presentation gaps/rebuffering.
- Core flow is keyboard accessible and readable at desktop and 375-pixel mobile widths. Color is accompanied by labels.

### Delivery

- Provide a README with prerequisites, one clear local start sequence, supported platforms, and troubleshooting.
- Include the standalone reference HTML in documentation and explain how implemented UI differs, if necessary.
- Document profile fidelity, startup simplifications, units/calibration, channel model and wire protocol.
- Include meaningful automated DSP/protocol tests and a browser smoke test covering connection, text exchange, profile labels and replay.
- Report measured performance and remaining limitations. Do not describe an illustrative profile as interoperable.

## Primary references

- GNU Radio FSK example: https://wiki.gnuradio.org/index.php/Simulation_example%3A_FSK
- Minimodem, an independent FSK implementation useful for comparison: https://github.com/kamalmostafa/minimodem
- ITU V-series catalogue and standard documents: https://www.itu.int/rec/T-REC-V/en
- SciPy ShortTimeFFT: https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.ShortTimeFFT.html
- FastAPI WebSockets: https://fastapi.tiangolo.com/advanced/websockets/
- AudioWorklet: https://developer.mozilla.org/en-US/docs/Web/API/AudioWorklet
- Browser binary WebSocket reception: https://developer.mozilla.org/en-US/docs/Web/API/WebSocket/binaryType

## Suggested prompt for the building agent

> Read SPEC.md and inspect modem-lab-mockup.html. Build Modem Lab according to the milestones, beginning with the real Bell 103 300-bit/s engine and then the live browser workbench. Preserve the mockup's visual intent, implement actual sample-derived spectra and decoding, and clearly distinguish illustrative profiles. Use the acceptance criteria to verify correctness. Continue through recording/replay, provide local run instructions, and document fidelity and performance limitations. Do not substitute direct text forwarding or scripted success states for modem processing.

