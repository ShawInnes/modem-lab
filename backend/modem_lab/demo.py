"""Run a full-duplex exchange offline and export listenable sample streams."""
import argparse
import json
from pathlib import Path
from time import perf_counter
import numpy as np
from scipy.io.wavfile import write
from .engine import SessionConfig, SessionEngine
from .dsp import RATE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["bell103", "dqpsk1200", "qam2400"], default="bell103")
    parser.add_argument("--caller", default="Hello from the caller!\r\n")
    parser.add_argument("--answerer", default="Hello from the answerer!\r\n")
    parser.add_argument("--snr", type=float, default=40, help="dB relative to the fixed transmit RMS")
    parser.add_argument("--delay", type=float, default=20, help="one-way propagation milliseconds")
    parser.add_argument("--echo", type=float, default=30, help="echo attenuation dB; higher means weaker")
    parser.add_argument("--seed", type=int, default=103)
    parser.add_argument("--bandpass", choices=["flat", "telephone", "narrow"], default="telephone")
    parser.add_argument("--output", type=Path, default=Path("runs/demo"))
    args = parser.parse_args()
    try:
        engine = SessionEngine(SessionConfig(snr_db=args.snr, delay_ms=args.delay,
                               echo_attenuation_db=args.echo, seed=args.seed, bandpass=args.bandpass, profile=args.profile))
        engine.enqueue_text("caller", args.caller)
        engine.enqueue_text("answerer", args.answerer)
        # Bound export memory while allowing sufficient time for framing and acquisition.
        seconds = max(len(args.caller), len(args.answerer))/({"bell103": 30, "dqpsk1200": 120, "qam2400": 240}[args.profile]) + 9 + 2*args.delay/1000
        if seconds > 60:
            raise ValueError("Demo export is limited to 60 seconds; use shorter messages")
    except ValueError as exc:
        parser.error(str(exc))
    streams = {f"{e}_{kind}": [] for e in ("caller", "answerer") for kind in ("tx", "rx")}
    recovered = {e: bytearray() for e in ("caller", "answerer")}
    started = perf_counter()
    for _ in range(int(np.ceil(seconds * RATE/960))):
        block = engine.process()
        for key, values in block["streams"].items():
            streams[key].append(values)
        for endpoint, data in block["decoded"].items():
            recovered[endpoint].extend(item["byte"] for item in data)
    elapsed = perf_counter()-started
    args.output.mkdir(parents=True, exist_ok=True)
    arrays = {k: np.concatenate(v) for k, v in streams.items()}
    for key, values in arrays.items():
        write(args.output / f"{key}.wav", RATE, np.clip(values, -1, 1).astype(np.float32))
    combined = (arrays["caller_tx"] + arrays["answerer_tx"])/2
    write(args.output / "combined.wav", RATE, combined.astype(np.float32))
    np.savez_compressed(args.output / "signals.npz", **arrays)
    metadata = engine.metadata()
    metadata["duration_seconds"] = engine.sample/RATE
    metadata["processing_seconds"] = elapsed
    metadata["recovered_bytes"] = {e: list(data) for e, data in recovered.items()}
    (args.output / "session.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print("V.22bis-style · experimental 16-QAM · 2400 bit/s · 600 baud · ASCII 8N1" if args.profile == "qam2400" else "V.22-style · experimental DQPSK · 1200 bit/s · 600 baud · ASCII 8N1" if args.profile == "dqpsk1200" else "Bell 103A2-style · functional FSK · 300 bit/s · ASCII 8N1")
    print("Simplified carrier startup; hardware interoperability has not been verified.")
    for e, data in recovered.items():
        print(f"{e.title()} received: {bytes(data)!r} ({engine.rx[e].errors} framing errors)")
    exact = recovered["caller"] == args.answerer.encode("ascii") and recovered["answerer"] == args.caller.encode("ascii")
    print(f"Exchange: {'exact' if exact else 'corrupted or incomplete'}")
    print(f"Processed {engine.sample/RATE:.2f}s audio in {elapsed:.3f}s ({engine.sample/RATE/elapsed:.1f}× realtime)")
    print(f"Audio and event log: {args.output.resolve()}")
    return 0 if exact else 1


if __name__ == "__main__":
    raise SystemExit(main())
