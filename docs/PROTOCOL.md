# Live protocol v1 and scheduling

The server binds to `127.0.0.1:8000`. It allows one controlling browser and one associated data connection. HTTP hosts are restricted to localhost; WebSocket Origin must be HTTP(S) localhost/127.0.0.1/::1 on port 8000 or the development UI port 5173. Origin is checked before creating any session. This is a local single-user service, without authentication or public hosting.

## Control

`/ws/control` creates a fresh session and returns `hello` with `version:1`, opaque `session_id` and `generation`. Use that ID for `/ws/data/{session_id}`. All control messages are JSON. Commands require `version:1` and a string `command_id` (at most 100 characters). Frames are limited to 16 KiB; commands queue at most 64 deep. Supported commands:

- `start`: run the current idle engine, preserving queued text.
- `restart`: discard the run, create a new engine from current controls, increment generation, and start.
- `hang_up`: stop processing, cancel pending text, flush presentation and emit disconnection events.
- `send_text`: `endpoint` caller/answerer plus ASCII `text`, at most 4096 queued characters per endpoint. After hangup this creates a fresh idle run, ready for `start`.
- `configure`: `config` object containing any of `snr_db`, `delay_ms`, `echo_attenuation_db`, `bandpass`, `seed`; Python also supports `echo_delay_ms`. Values pass `SessionConfig` validation. Seed changes are staged until restart; the state reports `actual_seed` separately.

`ack` echoes command ID, `ok`, generation and actual application `sample_index`; rejection adds `error`. Commands apply before a 960-sample block. `event` has endpoint, sample index, `event_type` and detail; decoded bytes appear only as receiver-generated `decoded_byte` events. `state` reports configuration, endpoint carrier/state/confidence/framing errors/queue count and processing metrics every 100 ms, also after commands. Confidence is relative tone separation, not a probability of correctness.

The worker retains 512 recent engine events and 128 commands; the UI retains 500 events, 8192 characters per terminal log and at most 30,000 spectral columns (five minutes at 100 Hz). Quantized spectral values use about 20.5 MB, plus browser object overhead; PCM is not retained for historic playback. These are rolling live views, not a recording. A slow control consumer that fills the 256-message output queue stops its session visibly, rather than silently losing terminal output. Control disconnect releases the worker immediately (no grace/reconnection of engine state); reload creates a fresh run.

## Binary data

Each binary WebSocket message is one batch with a 40-byte header. All multibyte fields use little endian. Stream order is **caller TX, answerer TX, caller RX, answerer RX**.

| Offset | Type | Field |
| --- | --- | --- |
| 0 | 4 bytes | ASCII `MLAB` |
| 4 | uint16 | protocol version, 1 |
| 6 | uint16 | kind, 1: combined PCM/spectral batch |
| 8 | uint32 | generation |
| 12 | uint32 | sequence, increasing per run |
| 16 | uint64 | PCM start sample |
| 24 | uint32 | sample rate, 48000 |
| 28 | uint32 | frames per PCM stream, normally 960 |
| 32 | uint32 | spectral columns per stream |
| 36 | uint32 | bins per spectral column, 171 |

Payload follows as four contiguous Float32 PCM arrays, then one uint64 center sample timestamp per spectral column, then quantized Uint8 spectra shaped `[4 streams, columns, 171 bins]`, in C order. Exact byte length is `40 + 16*frames + 8*columns + 4*columns*bins`. Decode uint64 timestamps through BigInt and reject anything outside JavaScript's safe integer range. Clients validate magic, version, shape and total length and discard stale-generation data.

Each successfully parsed packet must receive a text credit on the data socket: `{"type":"credit","generation":1,"sequence":17}`. At most eight uncredited batches can be in flight. If a consumer stops crediting for two seconds at this limit, data presentation disconnects. The worker queue holds eight batches, coalesces older display data when full and counts gaps, while modem processing continues unchanged. Socket sends also have a 250 ms timeout. The UI makes at most three automatic presentation reconnection attempts; audio flushes and re-buffers. Sequence discontinuities are visible in diagnostics. Recording and playback are deferred; no live samples are claimed to be recoverable here.

## Clocks, spectra and audio

A dedicated worker thread advances the engine in 20 ms blocks, paced against monotonic deadlines. DSP and FFT processing do not run inside async API handlers. If work misses a deadline it counts an overrun and resets the pacing deadline; no modem samples are omitted. API transport runs separately, and Canvas uses animation frames independent of engine timing. Initial measured processing is about 2–3 ms per block on the development macOS host, comfortably below 20 ms; a process worker remains an option if later DSP needs it.

Spectra use a 2048-sample symmetric Hann window, a 480-sample hop and retained overlap. Window centers are `window_start+1024`. Positive-frequency amplitude is `2*abs(rfft(x*window))/sum(window)`; DC is divided by two. Display levels are `20*log10(amplitude)` in dBFS, so a bin-centered unit-peak sine measures 0 dBFS. This is a digital amplitude display, not integrated spectral power or a calibrated dBm measurement. Quantization maps −90…0 dBFS onto 0…255 (about 0.353 dB steps). Both plots use this fixed scale and bins 0…170 (0…3984.375 Hz), with a 0…4 kHz axis.

The AudioWorklet has a 500 ms source ring, starts after 120 ms buffering and reports consumed source-sample position about every 20 ms. Linear interpolation retains its fractional source cursor across blocks and supports device rates different from 48 kHz. A 5 ms gain ramp softens monitor changes, resets and underruns; gaps/overflow flush the old ring and explicitly rebuffer. Long-term clock mismatch is handled by rebuffering at bounded underflow/overflow, without modifying simulation samples. Resampling is an initial linear adapter, not a high-quality bandlimited converter.

The plot cursor follows the consumed source position while audio is playing, and simulation position when muted. Both graphs use one shared time viewport, defaulting to a 12-second live view. Time zoom spans 0.5 seconds to five minutes. Wheel zoom is anchored at the pointer; drag/Shift-wheel, buttons, keyboard and a shared history slider pan the same window for both endpoints. Historic views stay fixed while the engine runs, then clamp to the earliest retained data if their samples expire. Follow live returns to the moving edge. Selecting an event centers the retained signal view and places the shared inspection cursor; older events outside retention are explicitly identified. Broad time views take the maximum quantized amplitude per display pixel to preserve brief signals. This is visual history inspection, without replay audio or reconstruction of historic terminal state. Physical sound-output latency and the spec's <50 ms acoustic alignment target have not been measured.

Hidden/suspended tabs discard incoming audio presentation, keep the engine running, and flush/rebuffer on return. Muting stops audio backlog while plots continue. Audio startup requires a user gesture; selecting a listener or the resume button provides it. No microphone permission is required. Audio underruns, server overruns, display gaps and receiver framing errors have separate counters.

## Live receiver telemetry and profile selection

`state` adds `actual_profile` and optional `diagnostics` keyed by endpoint. Each receiver snapshot contains its mode, nominal `symbol_samples`, current `sample_index`, `timing_locked`, explanatory `timing_note`, bounded trace pairs `[sample,value]` and symbol rows `[sample,i,q,decision,confidence]`. FSK i/q are space/mark energies; phase mode i/q are normalized differential symbol coordinates. Telemetry is sent with state at 10 Hz and never controls decoding. It remains live when the spectral history viewport is paused.

`select_profile` with `profile` equal to `bell103`, `dqpsk1200` or `qam2400` atomically resets the engine/generation and signal history, cancels queued text and preserves the active/idle setting. Profile and seed changes made through `configure` during an active run are staged until restart; live channel changes retain the actual profile and noise seed. Unknown profiles are rejected.

Phase telemetry retains every symbol during character framing and non-idle choices. Repeated idle dibit 11 is sampled at 10 Hz so recent data remains visible for inspection; the decoder still processes all 600 symbols/s. Both I/Q axes share the same visual scale.

## Call lifecycle

Configuration includes boolean `call_setup` (default true). Endpoint state adds `call_stage` and `transmit_ready`. During startup the visible endpoint `state` follows telephone/handshake stages while `carrier_lock` still represents the actual audio receiver. Sample-indexed `call_stage_changed` events describe dialing, ringing, pickup, answer signal, training, settling, completion or failure. Completion is independent per endpoint and requires its own received-signal acquisition. Disabled data receivers advance their absolute sample counters without feeding telephone tones into the decoder; carrier detectors inspect the actual received streams. Changing `call_setup` after processing starts requires restart. Binary PCM still includes the illustrative telephone sounds and real modem training through the existing causal channel.

## Auto chat

Control command `auto_chat` requires boolean `enabled`. State adds `auto_chat_enabled` and `auto_chat_status`. The browser starts a call when enabling from idle; the command itself only changes the conversation driver. Enabling is allowed before handshake. The bounded server driver checks both endpoints' actual readiness, yields to manual queues, and calls the same `enqueue_text` path as manual traffic. It waits for exact expected bytes from the opposite audio receiver before alternating sender. Generated lines carry sample-clock elapsed time, an 8-bit hexadecimal sequence tag, and a four-character random token seeded independently of line noise.

Sends are separated by at least 48,000 samples, and only one automated message may be outstanding. After 144,000 samples without a complete decoded line, the same sender retries a fresh line. The receive accumulator is capped at 128 bytes; manual data remains in its normal queues. Restart/profile change reset conversation state with fresh token randomness while preserving enablement; hangup disables it. Disabling does not cancel text already transmitted or queued. All generated text and received bytes use existing events, so terminal output is never directly forwarded by the conversation driver.

## 16-QAM diagnostics

Profile `qam2400` adds diagnostics mode `qam16`. Symbol coordinates are carrier/gain-corrected lattice units (targets ±1/±3), not normalized to unit radius. `decision` is the actual four wire bits as an integer 0–15. Optional `constellation` contains 16 `[i,q,lastTwoBitsLabel]` target rows. The first dibit is differential quadrant change, so a static point cannot be labeled with a complete quadbit. The trace is corrected real I, rather than phase-mode magnitude. The same 600 symbols/s, sample clock, bounded telemetry, queues and live binary transport apply.
