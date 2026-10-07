# Bell 103A2-style FSK fidelity

## Profile and references

**Functional**, 300 bits/s, 48,000 samples/s, continuous-phase binary FSK. Caller: space 1070 Hz, mark 1270 Hz. Answerer: space 2025 Hz, mark 2225 Hz. Each receiver listens to the opposite band.

The primary source is AT&T *Bell System Practices, Section 591-014-100, Data Set 103A Identification and Operation*, January 1967:
https://bitsavers.org/communications/westernElectric/modems/591-014-100_Data_Set_103A_Identification_and_Operation_Jan67.pdf

Table A on page 2 specifies these frequencies for **103A2**; 103A1 used reversed mark/space assignments. Page 1 describes simultaneous transmission/reception up to 300 baud. Pages 6–7 describe historical carrier startup and guard intervals. [Minimodem](https://github.com/kamalmostafa/minimodem) is an independent comparison implementation; comparison against it is future validation, not a current interoperability claim.

## Implemented signaling and framing

Each character is an asynchronous 8N1 frame: space start bit, eight least-significant-first data bits (ASCII high bit zero), mark stop bit. One bit lasts 160 samples. Idle continuously transmits mark. TX sine amplitude is 0.4 peak (about −7.96 dBFS peak; −10.97 dBFS RMS), without a transmit shaping filter. Tone changes retain phase. Initial carrier phase is zero in sessions; independent receiver tests randomize phases and waveform offsets.

The receiver mixes the input against both local tone oscillators and measures their complex moving-average energies over a trailing one-bit window. Oscillators are independent of transmitter phase. A mark-to-space transition locates an asynchronous frame; a half-bit-delayed check validates the start, then decisions follow every bit interval. A fresh start transition reacquires character timing. The receiver uses the known nominal 300-bit/s clock; adaptive recovery of clock-rate mismatch is not implemented. `acquiring_timing` represents detector settling; character timing is acquired on each start transition, not on idle mark alone.

Carrier evidence is a strongest-tone energy above 0.004 for 50 ms; 100 ms of sustained evidence establishes receive readiness. Loss of evidence for 50 ms reports carrier loss and discards an incomplete frame. Acquisition and loss follow received samples, not predetermined elapsed-call stages. A bad stop bit raises a framing error and discards that byte. Correct stop bits can accompany undetected wrong data, including bytes with the high bit set. Receive results are therefore raw byte values, not sanitized ASCII.

## Startup and scheduling simplifications

Normal sessions now begin with 0.6 seconds of illustrative DTMF dialing, 1.2 seconds of ringback and a 40 ms pickup click. These sounds model the telephone exchange, not modem data or actual ring-current detection. Browser **Hear call setup** enables combined-line audio on Start call; listening can be disabled or changed separately.

Bell startup is answer-first: the answerer starts its real 2225 Hz mark at 1.84 seconds. The caller remains silent until a received-audio detector confirms that tone for 100 ms, then starts its real 1270 Hz mark. Each endpoint independently waits for its own receiver acquisition and a continuous 1.5-second settling interval before releasing queued text. This is simplified startup: the historical 103 SF guard was before the answer carrier, and the original telephone/control interfaces are not emulated.

The phase profile sends an actual 2100 Hz answer tone for two seconds, followed by 80 ms quiet and real differential phase idle training. The caller must observe the answer tone and at least 150 ms of its absence before enabling its phase decoder, preventing the answer tone from being mistaken for data carrier. Its audio-derived training acquisition starts the caller response. Each receiver then observes a continuous 0.8-second settling interval before payloads. This is a V.22-inspired educational sequence, not the standard scrambled-ones handshake or an interoperability claim (V.22 §6.3 defines additional detection and wait timings).

A retained 20 ms correlator confirms answer tones from received samples, comparing target energy against nearby frequencies. The phase and FSK receivers use only received audio to acquire their clocks/carriers. Guards reset on lost acquisition. Failure to complete initial setup within 15 seconds silences both transmitters and reports `failed`; text stays queued until restart or hangup cancellation. Hang up interrupts every setup stage. After initial connection, carrier loss follows normal receive acquisition rather than the initial timeout. `SessionConfig(call_setup=False)` is an explicitly documented direct-carrier DSP bench mode used by isolated modulation tests.

All call transitions run at fixed 960-sample/20-ms control boundaries. Events generated from received samples influence subsequent transmission; no caller is told the other transmitter's text, phase or timing. Guard completion enables queued transmission at the next boundary. Character transmission begins at the next bit/symbol boundary. Processing requests are split internally at fixed control boundaries so caller block sizes cannot alter readiness scheduling.

Both TX streams are computed before the causal channel and independent RX processing. Receivers have no knowledge of remote payloads, transmit queues or bit boundaries. Reconnection uses fresh carrier evidence. A frame underway may finish its current symbol after carrier loss; queued data remains until readiness returns or hangup cancels it.

## Channel, units and reproducibility

Each direction sums the delayed remote signal with attenuated delayed local echo. Echo delay is independently configurable in Python (10 ms default); CLI echo control changes attenuation. Delay lines retain complete histories across blocks and permit zero delay.

The sum passes through a fourth-order Butterworth bandpass: `telephone` 300–3400 Hz, `narrow` 900–2400 Hz, or `flat` with no filter. Band edges are the Butterworth −3 dB cutoff frequencies. Filter startup history is zero. White Gaussian noise is added after this filter, representing receiver-side noise. Noise power uses the fixed RMS of a 0.4-peak sine (0.4/√2), regardless of activity; it persists during silence. SNR is referenced to the unfiltered remote transmitter, so filtering changes effective receiver SNR. Echo attenuation is an amplitude gain of 10^(−dB/20). All controls apply symmetrically. Offline configurations remain fixed; live configuration updates apply at 20 ms sample boundaries. Gain/noise and line-path changes use a 10 ms crossfade; compatible delay/filter histories and noise generators persist. Changing the seed applies on restart.

The two noise generators are independently derived from one seed. Configuration, commands at the same absolute sample indices and profile version reproduce arrays/events on the pinned supported numerical environment. Different block partitions agree within floating-point tolerance; bit decisions and event timestamps are tested for equivalence. Cross-platform bitwise numerical identity is not claimed. No dBm calibration exists.

The live workbench now implements sample-derived spectra, binary transport and buffered browser audio; see [PROTOCOL.md](PROTOCOL.md) for normalization, timing, queue bounds and audio behavior. Recording and playback have been deferred by user request; development prioritizes live receiver diagnostics.

## Experimental 1200 bit/s phase mode design

Reference: [ITU-T V.22 (11/1988)](https://www.itu.int/rec/T-REC-V.22/en), sections 2.1, 2.4 and 2.5. V.22 uses 1200/2400 Hz carriers, 600 symbols/s and two bits per phase change at 1200 bit/s. Table 1 (Modes i–iv) maps dibits 00/01/11/10 to +90°/0°/+270°/+180°. Baud counts symbols, not bits.

The lab's `dqpsk1200` profile is **experimental**, using these carriers and differential mapping with ASCII 8N1. It intentionally simplifies pulse shaping and startup. V.22 requires 75% root-raised-cosine shaping, a scrambler, fully defined startup sequences, rate adaptation and additional interface behavior. Those requirements and real modem interoperability remain unverified; this profile must not be described as compliant V.22.

Both diagnostics panels contain bounded receiver telemetry: at most 320 trace samples and 160 actual symbol decisions per endpoint. FSK records tone energies and the signed energy contrast; DQPSK records differential I/Q. Sample indices are receiver input sample indices, including detector delay. Confidence is a detector metric, not a measured bit-error probability. Eye plots are visualizations of the measured trace folded using the nominal symbol interval and the last decision timestamp.

The phase receiver mixes against its own nominal carrier and integrates over 80 samples. During initial carrier acquisition it chooses the sample phase with greatest mean matched-filter energy, then samples at that fixed phase every 80 samples. Timing traces show matched-filter magnitude normalized by nominal received carrier amplitude, rather than a binary eye. No adaptive clock tracking or carrier-frequency offset recovery is implemented; live delay changes can therefore corrupt a phase-mode exchange until restart reacquires timing.

## Experimental V.22bis-style 2400 bit/s design and review

Primary reference: [ITU-T V.22bis (11/1988)](https://www.itu.int/rec/T-REC-V.22bis-198811-I), §2.5, Table 1 and Figure 2. The diagram was visually checked against the official PDF. It uses 1200/2400 Hz carriers and 600 symbols/s at 2400 bit/s, with four bits per symbol. The first two wire bits change the previous quadrant: 00→+90°, 01→0°, 10→180°, 11→270°. The final two bits select a point in the new quadrant. In quadrant 1, 00=(1,1), 01=(3,1), 10=(1,3), 11=(3,3); rotate these coordinates by 90° for successive quadrants. This was also checked against the [SpanDSP author's constellation](https://github.com/freeswitch/spandsp/blob/master/src/v22bis_tx.c).

The separate `qam2400` profile is **experimental**. TX groups the real ASCII 8N1 stream into four-bit symbols and sends this specific differential-quadrant constellation. Character framing can span symbols: two 10-bit characters occupy five symbols. Idle supplies binary ones; leftover symbol slots are filled with ones. Rectangular symbols last 80 samples. Coordinates are scaled by `0.4/sqrt(18)` so the largest constellation radius has the same 0.4 peak amplitude as the earlier modes; smaller points carry less power. Line SNR still uses the fixed original carrier reference, so actual data power depends on the transmitted point.

The receiver independently mixes its nominal carrier, integrates over 80 samples, and accumulates idle energy by sample phase. After 100 ms of sustained carrier evidence it chooses the strongest timing phase, derives gain from the known outer idle radius, and carrier rotation from the fourth moment of the received idle symbols. Rotation remains ambiguous by whole quadrants, which cancel in differential quadrant decoding. Each sampled point is sliced against the 16 actual lattice targets; differential quadrant and point position reconstruct four bits, which feed the same sample-derived character framing. All four bits are observed at that symbol's decision timestamp. No transmitter clock, phase, queue or remote text enters this receiver.

Diagnostics expose carrier/gain-corrected I/Q in lattice units, preserving amplitude. Static target labels represent the last two bits only: the first two depend on the preceding quadrant. The latest quadbit readout shows all four actually decoded bits. The timing trace is the corrected real I component, with four target levels −3, −1, +1 and +3; it is folded around the receiver's sampling phase. Idle diagnostic points are decimated to 10 Hz so recent data remains visible.

Call setup retains dialing, ringback, pickup, the 2100 Hz answer tone, quiet gap and received-audio-gated training, then independent 0.8-second settling intervals. It calibrates directly from 16-QAM idle. This is **not the full V.22bis handshake**: §6.3 requires initial 1200-bit/s signaling, the 00/11 rate-request pattern, scrambled training, defined rate-change timing and fallback negotiation. These are not yet implemented. Standard 75% root-raised-cosine shaping, scrambling, adaptive/compromise equalization, frequency-offset and clock-rate tracking, guard-tone options and hardware interoperability also remain unverified. A gain/phase change or heavy band limiting can corrupt data until Restart reacquires calibration.

Design review: differential quadrant coding removes whole-quadrant ambiguity while preserving all amplitude levels; gain is learned from received idle audio, not shared TX state. Fixed-boundary scheduling, independent receivers, bounded diagnostics and real Auto chat decoding remain unchanged. Tests verify actual PCM mapping for all 16 wire quadbits, long full-duplex ASCII, unknown initial phase/alignment, fractional-symbol delays, noise degradation, carrier loss, framing rejection and block-partition equivalence.
