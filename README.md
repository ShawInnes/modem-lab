# Modem Lab

A local laboratory for hearing and inspecting two audio modems. The **interactive workbench** offers simultaneous Bell 103A2-style 300-bit/s FSK, experimental 1200-bit/s DQPSK and 2400-bit/s 16-QAM, with receiver symbol/timing diagnostics, real transmitted/received spectrograms, independent receiver-decoded terminals, phone-line controls and browser audio. Remote text comes from received audio samples.

The visual reference is [docs/mockup.html](docs/mockup.html); its V.32bis handshake and plots are illustrative. Recording/playback is deferred by user preference. See [the implementation plan](tasks/todo.md), [the full specification](docs/SPEC.md), [negotiation design](docs/NEGOTIATION_SPEC.md) and [live protocol notes](docs/PROTOCOL.md).

## Start the interactive workbench

Prerequisites: Python 3.11+, [uv](https://docs.astral.sh/uv/getting-started/installation/) and Node.js 20.19+ or 22.12+. From the repository root:

```sh
uv sync --extra dev
npm ci --prefix frontend
npm run build --prefix frontend
uv run modem-lab-web
```

Open **http://127.0.0.1:8000** in a current browser. Queue messages at either terminal, click **Start call**, and watch carrier acquisition and decoded RX text. Choose **Combined line** under Listen to hear both modem bands, or monitor a single TX/RX stream. Sound starts after a user gesture; use **Enable / resume audio** if the browser suspended it.

Switch each plot between transmitted and received signals, change the line controls while sending text, and click a timestamped event to position both inspection cursors. Both graphs share zoom and pan: use +/−, scroll backward/forward, or drag the history slider. Wheel over either graph to zoom at the pointer; drag horizontally or use Shift-wheel to pan. Focus a graph and use arrow keys to pan, +/− to zoom, Home for the earliest retained signal, or End to follow live. **Follow live** returns both graphs to current signals. The last five minutes of received spectra are retained in memory; older samples expire, and restart/reload clears the history. Audio and the live modem keep running during graph inspection. SNR can go down to −20 dB to exercise receiver corruption. This is live inspection; the engine continues, and recording and playback are outside the current live-lab scope. Hang up cancels pending text. Restart creates a fresh run with current settings and the chosen noise seed.

One browser controls a session. Close its tab before opening another controller; reload starts a new run. Hiding the tab discards audio presentation and re-buffers on return while the engine continues. The footer separates audio underruns, DSP overruns, display gaps and receiver errors.

### Watch capability negotiation

Choose **V.8 · menu negotiation** or **V.8bis → V.8 · capabilities then menus** under **Call setup**, then enable **Auto chat** or start a call. Enabling negotiation from Bell 103 selects the experimental 2400-bit/s payload mode. V.8 agrees the V.22/V.22bis family; its menu does not select the 1200/2400 data rate. The V.8bis transaction can select one of those modes before the full V.8 exchange.

Open **Device capabilities and examples** before calling to disable a device's supported family, try a peer without V.8bis, or choose which device initiates the capability request. The negotiation inspector distinguishes sent and audio-decoded messages; select a marker to inspect raw octets, parsed fields and validation while both graphs align to its time. Terminal traffic waits for negotiation and the actual payload receiver's training.

The V.8bis demonstration implements the post-pickup CRd → CL → MS → ACK(1) transaction with a full V.8 handoff. It is a restricted experimental subset, distinct from the poster's automatic-answer CRe/ESr opening. If the answerer initiates this transaction, it becomes the modem caller after mode selection, so the payload frequency roles swap. See [fidelity notes](docs/FIDELITY.md) for timing and interoperability limits.

For frontend development, keep the backend running and run `npm run dev --prefix frontend` in another terminal; Vite proxies the two WebSockets to port 8000. Production frontend edits need a new build; files are served directly from `frontend/dist`. If port 8000 is occupied, stop the previous service first.

## Offline demo on macOS or Linux

Prerequisites: Python 3.11+ and [uv](https://docs.astral.sh/uv/getting-started/installation/). The offline demo does not require Node.js, audio hardware or any external service.

```sh
uv sync --extra dev
uv run modem-lab
```

The demo queues messages before carrier acquisition, exchanges them in both directions, prints receiver-decoded bytes and writes audio to `runs/demo/`. Open `combined.wav` in any audio player. `caller_rx.wav` and `answerer_rx.wav` let you hear the filtered, delayed, noisy signals each receiver actually hears; the two `*_tx.wav` files contain transmitted tones. WAV files contain 48 kHz Float32 PCM.

Try your own exchange:

```sh
uv run modem-lab --caller 'Hello from A' --answerer 'Hello from B' --delay 80 --snr 30 --echo 20 --seed 42 --output runs/my-call
```

Try a poor line:

```sh
uv run modem-lab --snr -10 --output runs/noisy-call
```

Lower SNR means more noise. Higher echo attenuation means weaker echo. A corrupted exchange exits with status 1 and prints the actual recovered bytes; a successful exchange exits with status 0. ASCII only; unsupported characters and invalid controls receive validation feedback. The offline export is capped at 60 seconds, with queues capped at 4096 characters per endpoint.

For Python without uv:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
modem-lab
```

## Verify

```sh
uv run pytest -q
node frontend/tests/audio-worklet.cjs
# Requires Node.js 22.18+ for native TypeScript test imports:
node --test frontend/tests/plot-state.mjs
# With the server running (first install Chromium once):
cd frontend
npx playwright install chromium
npm test
```

The Python tests cover the engine, live configuration, spectra, transport and bounded queues. Browser smoke tests cover exchange, lifecycle, audio startup/monitoring and mobile layout. Worklet tests cover 44.1/48/96 kHz device-rate conversion, stale samples, gaps and underrun silence. Engine tests cover audio-only decoding with unknown phase/start offset, simultaneous payloads, arbitrary block boundaries, repeatability, delay/filter behavior, noise and framing errors. The engine is reusable offline:

```python
from modem_lab import SessionConfig, SessionEngine

engine = SessionEngine(SessionConfig(seed=103))
engine.enqueue_text(endpoint="caller", text="Hello")
result = engine.process(block_frames=960)
# result: start_sample, four TX/RX streams, received bytes and events
```

`process()` advances simulation time by samples without sleeping. Calling it faster runs the same engine faster. Create a new engine to restart; `hang_up()` cancels pending text and ends the session.

## Output and fidelity

[docs/FIDELITY.md](docs/FIDELITY.md) describes startup simplifications, detection, units and the channel. Functional means generated audio is decoded; hardware interoperability has not been verified. No V.32bis implementation is included.

`session.json` stores profile/version, sample rate, configuration/seed, sample-indexed commands/events and recovered bytes. `signals.npz` stores the four full Float64 sample arrays, readable with `numpy.load(path, allow_pickle=False)`. These are bounded demo artifacts; import and synchronized playback are outside the current live-lab scope.

If installation cannot reach the package index, restore network access or use a local package cache. The first SciPy import can take longer while macOS checks downloaded libraries. No sound during the CLI run is expected: open its exported WAV file to listen. Noise WAV exports clip to ±1 for playback; the NPZ arrays preserve unclipped engine samples.

## Current verification results

On the development macOS host, 40 Python tests and three browser smoke tests passed, including a simultaneous 968/1006-character exchange. A clean demo recovered both messages exactly with zero framing errors; a −15 dB SNR run produced corrupted bytes and framing errors. A 60-second idle session processed in 4.761 seconds (12.60× realtime) with six state events. This measures offline engine throughput; browser latency, Linux execution and hardware interoperability remain unmeasured.

Live pipeline stress check: 600 seconds of engine + FFT processing completed offline in 52.619 seconds, with identical peak resident memory at 300 and 600 seconds (102,629,376 bytes) and a 1920-sample retained FFT buffer. This is a bounded offline pipeline check, not a measured ten-minute browser session. Acoustic cursor alignment and Linux/browser hardware coverage remain unmeasured.

Build tooling audit: the configured registry date cutoff currently leaves Vite → PostCSS → source-map-js 1.2.1 with advisory GHSA-68fv-2mgg-jv7q (indexed source-map parsing denial of service). The patch 1.2.2 is unavailable under that policy. The workbench serves prebuilt assets without source maps; this dependency is build tooling, and no user-uploaded source maps are accepted. Upgrade when the registry makes the patch available.

## Understanding receiver symbols

Receiver diagnostics are below the paired terminals. Choose **Symbol decisions** or **Timing / eye**. These views come from the receiver's filtered audio and actual decisions; the transmitter's text and timing are never used to construct them. FSK plots space energy horizontally and mark energy vertically: clusters near either axis indicate clear binary choices; points near the diagonal are ambiguous. Its timing trace is `(mark−space)/(mark+space)`; the eye folds that trace around an actual receiver decision. The clock is nominal 300 bit/s, reacquired at each character start.

The experimental **1200 bit/s / 600 baud DQPSK** profile packs two bits into each phase change. Its differential constellation compares consecutive received symbols, removing the arbitrary absolute carrier phase. The ideal phase changes are 0°→01, 90°→00, 180°→10, 270°→11. Noise and line filtering spread points around those choices. This is an educational V.22-style mode, with simplified acquisition and shaping; it is not a claim of V.22 hardware interoperability. Changing profile starts a fresh session, clears pending text and signal history, and preserves whether the call was running. Line controls continue to apply live.

Try sending varied text in both directions, then reduce SNR and watch decision confidence, symbol spread and framing errors together. Receiver diagnostics always show the live receiver, even when spectrograms inspect earlier history. See [fidelity details](docs/FIDELITY.md) for exact implementation limits.

Try the faster offline core with `uv run modem-lab --profile dqpsk1200`.

## Dial, pickup and connect

**Start call** now runs dialing → ringback → pickup → answer tone/carrier → training → settling → connected. Leave **Hear call setup** checked to enable the combined-line monitor with that click. Both terminal queues wait for receiver evidence and settling; text is still decoded from generated audio. The compact Call progress strip and timestamped events explain the stages. Bell 103 normally connects in about four seconds; the experimental 1200 mode takes about five. Hang up cancels setup and pending text; Restart starts a fresh call. A missing remote signal times out after 15 seconds.

Telephone sounds are illustrative; modem replies and receive acquisition are driven by received samples. The V.22-style handshake remains simplified. See [FIDELITY.md](docs/FIDELITY.md) for durations and differences from historical hardware. Offline DSP-only comparisons can use `SessionConfig(call_setup=False)`; live and default engine sessions include call setup.

## Auto chat

Check **Auto chat** to start a call (if idle) and let both devices take turns. The caller sends a short greeting; the answerer responds only after its receiver actually decodes the complete line. Messages contain the elapsed call timestamp, a sequence tag and a fresh random ASCII token, so the symbol patterns change continuously. A clean line sends about one message per second total, alternating directions. Slower lines and manual traffic delay the next message; no automated backlog accumulates. A line that is not decoded within three seconds prompts a new attempt from the same sender.

Uncheck Auto chat to stop generating messages; the current message finishes. Hang up disables Auto chat and cancels queues. Restart or a profile change keeps an enabled Auto chat running after the new handshake. Leave **Hear call setup** checked when enabling it from idle to hear the whole call, or use Listen to mute/select a stream. Scheduling follows the server's sample clock, so graph navigation does not pause the conversation.

## 2400 bit/s: 16 amplitude-and-phase choices

Select **V.22bis-style · 2400 bit/s · 600 baud · experimental 16-QAM**. Auto chat continues after the fresh pickup and handshake. It carries four bits per symbol at the same 600-symbol/s pace as the 1200 mode. The receiver's 16-point plot now shows both amplitude and phase; target labels are the last two bits, and the latest quadbit readout shows all four. Switch to **Timing / eye** for the four I-amplitude levels. Try reducing SNR to see how closely spaced points become harder to distinguish.

This profile uses the V.22bis differential quadrant and within-quadrant mapping but simplified shaping, calibration and startup; full rate negotiation, scrambling and adaptive equalization remain future work. See [fidelity/design review](docs/FIDELITY.md). The offline core can be exercised with `uv run modem-lab --profile qam2400`.
