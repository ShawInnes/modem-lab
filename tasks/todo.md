# Modem Lab implementation plan

Deliver runnable checkpoints and let the user try each before the next increment.

## Checkpoint 1 — offline modem core
- [x] Verify Bell 103 frequencies against primary implementation references.
- [x] Implement independent continuous-phase TX and sample-only RX, 300 bit/s, ASCII 8N1.
- [x] Implement persistent causal delay, filtering, echo and seeded noise.
- [x] Implement sample-indexed states/events, queueing and cancellation.
- [x] Verify bidirectional payloads, arbitrary blocks/offsets, determinism, channel and noisy trials.
- [x] Deliver a command-line exchange and listenable WAV files with run/fidelity documentation.

## Checkpoint 2 — live workbench (current)
- [x] Python local API and bounded transport; React/TypeScript UI inspired by docs/mockup.html.
- [x] Real aligned spectra, terminal exchange, phone controls and browser audio.
- [x] Browser smoke tests and measured scheduling/backpressure/audio behavior.

## Checkpoint 3 — recording, inspector and replay
- [ ] Safe recording/export/import and synchronized seeking.
- [ ] Receiver diagnostics, lifecycle checks and performance measurements.

## Review
Checkpoint 1 complete. 25 automated tests pass (4.00 seconds), including a simultaneous exchange of 968/1006 characters. Clean CLI demo recovered both messages exactly; a −15 dB SNR demo produced wrong bytes and seven framing errors per endpoint. A 60-second idle run completed in 4.761 seconds (12.60× realtime) on the current macOS host, with six state events. Python source compilation and whitespace checks pass.

The offline demo remains available. Checkpoint 2 now delivers the live browser workbench; full recording/replay remains checkpoint 3. Higher-speed protocols require separate designs.

### Checkpoint 2 execution
- [x] Sample-boundary live configuration with short ramps and retained channel histories.
- [x] Dedicated paced worker; bounded separate control/data connections and generation filtering.
- [x] Continuous Hann FFT columns and documented common dBFS scale.
- [x] Workbench: queue-before-call, real terminal RX, actual states and aligned signal inspection.
- [x] Worklet: bounded resampling playback, source clock, underruns and hide/return behavior.
- [x] API/channel/protocol tests, browser verification, desktop/mobile inspection and run docs.

Checkpoint 2 verified: production frontend build passes; 40 Python tests pass in 5.37 seconds; three Chromium smoke tests pass in 5.1 seconds (real exchange/lifecycle,375 px/theme, audio startup/monitor switches/mute/hangup). Worklet VM tests pass at 44.1/48/96 kHz. CUA visual inspection confirmed actual spectra, paired received messages and native audio playing with zero underruns in the observed window. 600 seconds of engine+FFT offline stress completed in 52.619 seconds with peak RSS 102,629,376 bytes unchanged at 300 and 600 seconds, bounded 1920-sample overlap, six idle events.

Limits: no full session recording yet; old live events inspect only a rolling view; acoustic output alignment and a ten-minute realtime browser run remain unmeasured. Thread scheduling overruns and all presentation gaps are reported. A build-only source-map-js advisory remains under the registry's date cutoff; details in README. Pause for the user to try this interactive checkpoint.

## Shared graph navigation
- [x] Retain bounded five-minute spectra history and one common viewport.
- [x] Add shared time zoom, pan, scrubber and follow-live controls, plus wheel/drag/keyboard gestures on either plot.
- [x] Make event selection bring retained history into view without changing modem state.
- [x] Verify viewport/history boundaries and aligned browser interactions; build and refresh the workbench.

Shared navigation verified: seven viewport/history tests and an isolated browser test for aligned controls, wheel, drag, Home and Follow live pass. Production build passes; browser inspection confirms terminals and both graphs remain together. Retention is capped at five minutes; it does not include historic audio or replay.

## Live receiver diagnostics and 1200 bit/s phase mode
Recording/replay deferred by user request.
- [x] Add bounded sample-derived FSK energy, decision and timing views.
- [x] Add experimental differential QPSK at 1200 bit/s / 600 symbols/s, with explicit fidelity limits.
- [x] Integrate profile selection and paired educational receiver views.
- [x] Verify real decoding, arbitrary blocks, diagnostics, browser controls and production build.

Live diagnostics checkpoint verified: 53 Python tests pass, including audio-only bidirectional 1200 bit/s decoding with unknown carrier phase/sample alignment, arbitrary blocks, noise degradation and idle telemetry retention. Production build passes. Six browser tests pass (real Bell 103 and DQPSK exchanges, shared graph controls, educational diagnostics, mobile layout and native audio); after the final equal-axis/idle-retention refinement the two affected browser tests pass again. CLI phase-mode exchange recovered both messages with zero framing errors. Chrome inspection confirmed all four measured differential phase clusters and exact terminal text. Updated workbench is running on localhost:8000 in phase mode. Recording/playback remains explicitly deferred.

## Audible call setup and sample-driven handshake
- [x] Add dialing/ringback, pickup, answer-first carriers and phase-mode answer tone/training.
- [x] Require received-signal evidence and guard intervals before queued payload transmission; show timeout/failure.
- [x] Show live call progress beside the controls without moving graphs/terminals.
- [x] Verify samples, independent response gates, block determinism, interrupted setup and browser lifecycle.

Call lifecycle verified: 70 Python tests and seven browser tests pass. Both real profiles exchange queued text after pickup/handshake, including 1000 ms line delay; missing remote training times out without forwarding queued text. Whole-call audio and event times remain identical for 960- and 137-sample blocks. Browser tests confirm audible start, ordered visible stages, deferred queued data, restart and interruption, mobile layout, both profiles and existing diagnostics/graphs. CLI phase call recovered both messages with zero framing errors. Native Chrome inspection observed the 2100 Hz answer stage and exact post-handshake payload, with playing audio and zero underruns in the inspected interval; the workbench is left idle and ready for a fresh call. Telephone sounds and phase startup remain explicitly simplified.

## Live Auto chat
- [x] Add bounded sample-clock conversation scheduling through actual modem queues and received bytes.
- [x] Add an Auto chat toggle, varied ASCII messages and timestamps, with about one message per second.
- [x] Hold during handshake/carrier loss, preserve on restart/profile switch and stop on hangup/disable.
- [x] Verify real exchanges, cadence, noise/timeouts, queue bounds and browser controls.

Auto chat verified: 75 Python tests pass. Both real modulation profiles carry eight alternating auto messages exactly, at least one second apart; handshake/carrier/manual traffic gate scheduling, damaged or absent receive completion causes bounded retries, and toggle/restart/profile/hangup behavior is covered. Seven existing browser checks passed; the new Auto chat check passes after correcting asynchronous toggle feedback, including real changing lines, audio, stop, restart and hangup. Production build passes. Native Chrome inspection confirms timestamped random-token messages in both receive terminals and playing audio with zero underruns in the observed interval. Live lab is left running with Auto chat enabled in 1200 bit/s mode.

## Experimental V.22bis-style 2400 bit/s
- [x] Verify standard differential quadrant and within-quadrant 16-QAM mapping.
- [x] Build actual 2400-bit/s sample-only receiver with amplitude, carrier and timing acquisition.
- [x] Integrate call setup, profile selection, Auto chat and 16-point receiver/eye explanations.
- [x] Verify long duplex payloads, unknown phase/alignment, channel/noise, partition equivalence and browser lifecycle.

2400 checkpoint verified: 91 Python tests and nine browser tests pass; production frontend build passes. Official V.22bis Table 1 and Figure 2 were visually checked for differential quadrant and within-quadrant mapping. Independent PCM integration verifies all 16 wire quadbits; long full-duplex ASCII, unknown carrier phase and symbol offset, fractional delays, framing rejection, silence/carrier loss, noise degradation, complete call lifecycle and bounded Auto chat pass. CLI recovered both 2400 messages exactly with zero framing errors. Native Chrome inspection confirms two live 16-point amplitude-preserving constellations, actual quadbit decisions and four-level timing view; the app is left running 2400 Auto chat. Standard shaping/scrambling/equalization, full1200-to2400 negotiation/fallback and hardwareinterop are explicitly outside the implemented experimental fidelity.
# V.8 and V.8bis live negotiation

- [x] Review standard encodings and separate V.8bis transactions from V.8 menus.
- [x] Implement independent audio control channels, answer-tone detection and negotiation state machines.
- [x] Integrate negotiated startup and payload handoff with the live engine.
- [x] Add capability controls and inspectable transmitted/received negotiation messages.
- [x] Verify clean calls, incompatible capabilities, corruption/timeouts and processing-block independence.
- [x] Build and exercise the browser workbench; document fidelity and playable checkpoints.

Negotiation checkpoint verified: 132 Python tests pass, including 27 independent wire/audio/parser checks and 14 integrated calls. All 13 browser tests pass (nine prior workbench checks and four negotiation checks). Both payload rates recover exact duplex text after V.8 or V.8bis/full-V.8; either V.8bis initiator works with correct modem-role and carrier remapping; 1000 ms propagation, asymmetric V.8bis fallback, no-common failures and 137/960-sample partition equivalence pass. ANSam rejects plain/nearby tones and tested noise; damaged HDLC frames and missing CJ cannot establish remote agreement; self-echo-only probes do not connect. Production build, compile and diff checks pass. Native Chrome inspection confirms decoded CL bytes/fields, subsequent CM/JM/CJ, ready payload receivers and actual changing Auto chat text.

Implemented fidelity is a restricted transparent-data capability subset with V.8bis post-pickup transaction 2 and full V.8. The poster's automatic-answer CRe/ESr path, shortened V.8, other transactions/collisions, segmentation, legacy V.25 fallback and complete payload rate training remain later extensions. Control scheduling is 20 ms; interoperability is unverified. See docs/FIDELITY.md and docs/NEGOTIATION_SPEC.md.
