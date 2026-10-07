# UI lessons

- Keep the signal graphs and terminal inputs adjacent near the top of the workbench so users can watch the audio signals while exchanging text. Put secondary inspection and line controls below the primary interaction.

- Prioritize live experimentation and receiver understanding. Recording and playback are explicitly outside the current user-requested scope.

- A Start call control must recreate call setup, pickup and an answer-first handshake. Carrier acquisition alone is not the dial-up connection experience; make simplifications explicit and hold payloads until received-signal evidence and guards permit transmission.

- Treat capability negotiation as an inspectable audio protocol before payload training. Keep V.8 family agreement, V.8bis mode selection and final data readiness separate; check each standard's capability bits rather than inferring them from profile names or a later modem's example poster.
