# Modem Lab — V.8 and V.8bis Negotiation Specification

## Status and goal

Specification for a future implementation; this document does not implement negotiation.

Make V.8 negotiation and an optional preceding V.8bis capabilities exchange audible, visible and understandable in the live workbench. The user should see each device announce its capabilities, watch the other device decode those announcements, and understand why a mode was selected or why negotiation failed. Build this incrementally with playable checkpoints.

Negotiation is separate from the selected modem's receiver training and payload transport. Completing V.8 must not immediately imply a working data connection.

## References and protocol boundaries

- Normative reference: [ITU-T V.8 — Procedures for starting sessions of data transmission over the public switched telephone network](https://www.itu.int/rec/T-REC-V.8/en). Choose and record the edition before implementation.
- Supporting signal descriptions: [RFC 4734, sections 2.2–2.3](https://www.rfc-editor.org/rfc/rfc4734.html#section-2.3). This is a useful summary, not a replacement for the V.8 state machine and encoding tables.
- Visual inspiration: [Oona Räisänen's annotated dial-up handshake](https://oona.windytan.com/posters/dialup-final.png).
- Normative reference for the optional preceding exchange: [ITU-T V.8bis (11/2000)](https://www.itu.int/rec/T-REC-V.8bis-200011-I). Review its transactions, message definitions and relationship to V.8 before implementation.

The poster combines multiple protocols and later modem training. Its initial capabilities-request/list/mode-select exchange is V.8bis. Include that exchange as an optional preceding stage, while keeping it distinct from V.8. Do not label CR, CL, MS or ACK as V.8 messages.

V.8bis is not a mandatory opening to every V.8 call. When used to select a modem-based operating mode, it can precede full V.8, a truncated V.8 procedure, or V.25 startup, as appropriate. Support both a V.8-only preset and a poster-inspired V.8bis-then-V.8 preset. Do not mechanically replay the entire V.8 sequence after V.8bis where the applicable procedure omits stages. See [RFC 4734, section 2.1](https://www.rfc-editor.org/rfc/rfc4734.html#section-2.1).

Historical Bell 103, V.22 and V.22bis startup remains distinct from this negotiation path. Offering a modern negotiation wrapper around an existing experimental profile does not make its payload modem standards compliant.

## Signal foundation

V.8 control messages use V.21 FSK at 300 bit/s, with the caller on the low channel and answerer on the high channel:

| Endpoint | Mark / binary 1 | Space / binary 0 |
| --- | --- | --- |
| Caller | 980 Hz | 1180 Hz |
| Answerer | 1650 Hz | 1850 Hz |

These are different from our Bell 103 tones. Reuse suitable framing and detector infrastructure, but provide a distinct V.21 configuration and independently validate it.

ANSam is a 2100 Hz answer tone with 15 Hz amplitude modulation. Detect its envelope as well as its tone frequency so an ordinary unmodulated answer tone cannot masquerade as V.8 support. Include the applicable phase-reversal behavior from the selected V.8 edition and document it.

Control messages carry structured binary fields, not printable terminal chat. Use the standard's synchronization, octet framing, repetition rules and message boundaries; CJ has its own termination encoding. Do not substitute JSON, ASCII capability names or a private packet format for the audio protocol.

## Negotiation flow

The baseline sequence is CI (call indicator), ANSam, CM (call menu), JM (joint menu), CJ (CM terminator), then handoff to the selected modem. CI support and alternative answering procedures must follow the chosen standard edition. The caller determines the operating mode from the exchanged information.

Implement this as independent endpoint state machines:

1. After telephone pickup, enter V.8 startup. Support the CI path and an explicitly documented answer-first variant where appropriate.
2. Caller recognizes ANSam from received audio before sending its menu.
3. Answerer accepts valid repeated CM messages, parses their fields and constructs JM using its own configuration and the received capabilities.
4. Caller validates repeated JM messages, determines a permitted common mode, finishes its menu transmission and sends CJ.
5. Answerer recognizes CJ. Each endpoint observes the required transition interval and enters the selected profile's training procedure.
6. Payload remains queued until that profile's own receiver is ready. Show negotiation completion and data readiness as separate events.

Before coding, extract exact timing, repetition counts, synchronization patterns, field encodings, menu semantics and transition conditions into reviewed constants and reference vectors from V.8. Do not derive timings from the poster's example trace. Keep advertised modulation families distinct from rates negotiated later during modem training.

The engine may schedule telephone exchange sounds and enforce timeouts. It must not tell a receiver that a remote menu, tone or terminator was received. All successful protocol transitions require actual received evidence.

## Capability model and selection

Configure each endpoint independently with V.8 enablement, available modulation families and preference policy. Start with data-modem operation and the subset of standard fields needed for it; validate mandatory fields and handle extensions according to the selected edition.

Keep three concepts separate:

- **Implemented:** the lab has a working payload implementation for the mode.
- **Advertised:** the endpoint offers it in this call's transmitted menu.
- **Selected:** the caller chooses it from valid received negotiation information.

Normal live calls must advertise only executable, enabled modes and supported protocol options. Do not advertise compression or error control merely because the poster shows them. Bell 103 must not be assigned an invented V.8 capability bit.

For an early negotiation-only demonstration, use clearly labeled reference menus that may include future modes such as V.34. Stop after showing the negotiation outcome and display “Negotiation complete — selected modem not implemented.” Do not generate fictitious successful training or decoded payload.

Validate whether and how the existing V.22-style and V.22bis-style profiles can be represented by the chosen V.8 fields before enabling handoff. Their simplified payload training remains visibly experimental. The future V.32 integration must also respect [9600_SPEC.md](9600_SPEC.md).

Expose valid overlapping-capability, asymmetric-capability and no-common-mode presets. Selection must depend on parsed received menus and local policy, not shared remote configuration. Explain the result in plain language, including why a preferred mode was unavailable.

## Optional V.8bis stage before modem startup

### User-visible transaction

Provide a capabilities-request demonstration resembling the poster: request remote capabilities, exchange capability lists, propose a common operating mode and acknowledge or reject it. Decode each step from audio and explain who initiated the transaction. Either endpoint can initiate V.8bis; transaction initiator/responder roles must not be conflated with telephone caller/answerer roles.

Use the following vocabulary in the inspector:

| Signal or message | User-facing meaning |
| --- | --- |
| CR | Request the other device's capabilities |
| CL | Send a capabilities list |
| CLR | Send a capabilities list and request one in return |
| MS | Propose/select an operating mode |
| ACK | Accept the transaction as defined by its acknowledgement type |
| NAK | Reject the transaction with its defined reason/type |
| MR / ES | Mode-request and escape signals used by the applicable transaction |

Choose a valid transaction from V.8bis rather than treating this table as a universal fixed sequence. Review role-dependent signal variants, acknowledgement variants, retries, collision handling and unsupported-peer behavior. Record precisely which transactions are implemented; do not advertise the entire protocol when only the capabilities-request path works.

### Audio and message processing

Implement the prescribed two-segment tone signals and distinct V.8bis message framing over half-duplex V.21. The transaction initiator uses the low channel and responder uses the high channel, independently of who placed the telephone call. Reuse V.21 DSP while keeping V.8 and V.8bis parsers separate.

V.8bis requires HDLC-style boundaries, bit stuffing and a frame check sequence. Verify their exact definitions against the selected edition, including field bitmaps, preambles, length limits and segmentation rules. Never parse a V.8bis message using V.8's octet framing or manufacture a valid receive event from transmitted configuration.

Bound parser memory and message sizes. Implement segmentation if required by the advertised subset; otherwise explicitly restrict that subset and handle unsupported frames according to the standard. The line simulator does not currently model network echo suppressors, so document that omission rather than claim the tone exchange proves their operation.

### Handoff to V.8

After a successful transaction, retain the selected operating mode and associated constraints. Enter the appropriate reviewed full or truncated V.8 path, or the documented legacy startup. Both endpoint transitions must follow actual protocol completion evidence and specified intervals.

Show V.8bis mode selection, subsequent V.8 result, payload training and final data rate as separate outcomes. Subsequent stages must respect the agreed constraints; expose an incompatible result as a failure rather than silently selecting a different mode. A selected modem still needs its own training before terminal traffic is allowed.

If a peer lacks V.8bis support, distinguish optional discovery failure from V.8 failure. Continue to V.8 only where the selected policy and standard permit it, with a visible “V.8bis unavailable — trying V.8” event. Never synthesize capabilities or acknowledgements on behalf of a silent peer.

## Workbench experience

Add a call-setup choice for the existing direct profile startup, V.8 only, and V.8bis followed by the appropriate V.8 procedure. Label this separately from the payload profile. Provide independent caller and answerer capability controls, with approachable presets and an optional detailed view. Allow asymmetric V.8bis support for fallback demonstrations.

Keep graphs and terminals adjacent, and preserve shared time navigation. During negotiation:

- Show each endpoint's current transmitted signal and actual receive state.
- Mark CI, ANSam, CM, JM and CJ on the aligned timeline; identify transmission and detection separately.
- When enabled, add V.8bis request, capability-list, mode-selection and acknowledgement markers before V.8. Label the protocol and transaction role on every marker.
- Selecting a marker reveals an explanation, raw received bytes in hexadecimal, parsed fields, validation status and repetition evidence.
- Display caller offer, received answerer menu and the resulting selection side by side.
- For V.8bis, show both decoded capability lists, the proposed mode, acceptance/rejection and the handoff path. Explain stages omitted by a truncated V.8 procedure.
- Distinguish “Waiting for answer,” “Receiving capabilities,” “Confirming selection,” “Training modem,” and “Ready for text.”
- Explain timeout or unsupported outcomes at the failed stage rather than reporting a generic carrier failure.

Provide concise descriptions such as “CM: caller advertises the modes it supports.” All plotted signals must come from generated or received audio. Inspector decoding must use receiver results, not a copy of the transmitter's menu.

The current spectrum resolution may not clearly separate ANSam's close sidebands. Evaluate a focused higher-resolution spectrum or envelope view, labeled with its time/frequency tradeoff, rather than promising distinct lines in the existing plot.

Auto chat waits for genuine payload readiness, then resumes its existing received-byte-driven replies. It must not send chat during negotiation. Restart clears parser, repetition and selection state; hangup cancels negotiation and queued activity. Audio monitoring remains available throughout.

## Failure behavior

- A plain answer tone must not establish ANSam detection.
- Partial, malformed, corrupted or inconsistent menu repetitions must not complete negotiation.
- Unsupported or incompatible menus must produce a bounded, explained failure or a documented standard fallback.
- Absence of CI, ANSam, CM, JM or CJ must not be resolved by silently advancing a success timer.
- Legacy fallback is a separate policy and must use the applicable legacy startup; do not invent a universal automatic fallback.
- Menu content and retained telemetry must be bounded. Unknown fields must not crash the session or become application instructions.
- Bad V.8bis frame checks, incomplete frames, invalid stuffing, rejected mode selections, collisions and missing acknowledgements must not complete a transaction.
- V.8bis-to-V.8 handoff must preserve agreed constraints and clear stale parser state without losing the required transition signals.

Define timeouts and restart behavior before implementation. Validate the operating envelope under filtering, noise, echo and propagation delay, and expose uncertainty rather than claiming arbitrary robustness.

## Playable checkpoints

1. **V.21 control channel:** independently verified FSK transmission and reception with actual decoded binary octets and tone diagnostics.
2. **ANSam and call indication:** audible generation, receiver discrimination, CI parsing and honest missing-signal failures.
3. **Visible menu exchange:** real CM/JM encoding, decoding and repetition validation, with a negotiation-only outcome and no fabricated payload connection.
4. **Selection and confirmation:** standard-compatible selection policy, CJ detection, transition intervals, mismatched presets and bounded failures.
5. **Executable modem handoff:** start an eligible implemented profile after negotiation, then release real terminal traffic and Auto chat only after its receiver training succeeds.
6. **V.8bis capabilities exchange:** add real request tones and capability-list frames, with decoded fields, frame-check results and independent transaction roles. Include valid mode selection and acceptance/rejection.
7. **Combined V.8bis and V.8 startup:** expose both protocol stages in one playable call, using the correct full or truncated V.8 handoff and explicit unsupported-peer behavior. Demonstrate the poster-inspired sequence without claiming all calls use it.
8. **Optional legacy handling:** documented fallback behavior and mixed V.8bis/V.8/legacy calls.

Each checkpoint must run in the live workbench and disclose incomplete stages. Recording and playback are outside scope.

## Verification and acceptance

- Check modulation, message encoding and field parsing against independent standard-derived vectors; a shared encoder/decoder round trip is insufficient.
- Verify received bits and messages with independent initial phase, fractional delay and arbitrary processing-block partitions.
- Demonstrate ANSam recognition and rejection of plain 2100 Hz, nearby tones and noisy false positives.
- Test repeated, inconsistent, truncated and malformed menus, missing CJ and all timeout paths.
- Verify advertised options and selection semantics against the chosen V.8 edition; test preferences and no-common-mode cases.
- Demonstrate simultaneous control signaling where required without confusing local echo with remote evidence.
- Confirm neither endpoint accesses the other's capability configuration, transmitted bytes or state to recognize protocol success.
- Verify negotiation outcomes in the UI match actual receiver events and that unsupported selected modes stop honestly.
- Confirm clean handoff preserves sample continuity, bounds stale detector state and avoids a second duplicated telephone setup or answer tone.
- Validate V.8bis signals, framing, stuffing, frame checks and field parsing against independent vectors, including malformed and segmented input where supported.
- Exercise V.8bis initiation by either endpoint, acknowledgement/rejection, transaction collisions and a peer with V.8bis disabled.
- Verify combined startup uses the reviewed handoff variant, honors prior mode constraints and never skips required received confirmation.
- Maintain real-time processing, bounded telemetry and responsive audio/plots throughout setup and subsequent Auto chat.

## Fidelity and integration

Initially label the features **experimental V.8 negotiation** and **experimental V.8bis capabilities exchange**. Record the implemented editions, message/transaction subsets, answering variants, handoff procedures, fallback policy, timing tolerances and omissions in FIDELITY.md. Hardware interoperability requires separate evidence.

Keep negotiation logic separate from per-profile training and decoding. Extend existing state/event transport with structured negotiation telemetry, preserving session/generation isolation and bounded event history. Store actual parsed fields and sample timestamps so the inspector can explain decisions consistently.

V.34/V.90 payload DSP, channel probing for those modes, in-call voice/data switching, compression, error-control protocols and physical phone interfaces are not part of this implementation plan. The initial V.8bis scope is pre-startup data-modem capability negotiation, not every operating mode covered by the standard.
