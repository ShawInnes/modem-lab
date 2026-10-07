"""Reusable session core. Time advances only when process() is called."""
from dataclasses import dataclass, asdict
import math
import numpy as np
from .dsp import Transmitter, Receiver, encode, RATE
from .channel import PhoneLine

ENDPOINTS = ("caller", "answerer")


@dataclass(frozen=True)
class SessionConfig:
    snr_db: float = 40
    delay_ms: float = 20
    echo_attenuation_db: float = 30
    echo_delay_ms: float = 10
    bandpass: str = "telephone"
    seed: int = 103
    profile: str = "bell103"
    call_setup: bool = True

    def __post_init__(self):
        for key, low, high in (("snr_db", -20, 100), ("delay_ms", 0, 1000),
                               ("echo_delay_ms", 0, 1000), ("echo_attenuation_db", 0, 100)):
            value = getattr(self, key)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{key} must be between {low} and {high}")
        if not isinstance(self.call_setup, bool):
            raise ValueError("call_setup must be boolean")
        if self.profile not in ("bell103", "dqpsk1200", "qam2400"):
            raise ValueError("Unknown modem profile")
        if self.bandpass not in ("flat", "telephone", "narrow"):
            raise ValueError("Unknown line bandpass")
        if not isinstance(self.seed, int) or not 0 <= self.seed < 2**32:
            raise ValueError("Seed must be a 32-bit unsigned integer")


class SessionEngine:
    def __init__(self, config=None):
        self.config = config or SessionConfig()
        self.sample = 0
        tx_class, rx_class = Transmitter, Receiver
        if self.config.profile == "dqpsk1200":
            from .psk import Transmitter as tx_class, Receiver as rx_class
        if self.config.profile == "qam2400":
            from .qam import Transmitter as tx_class, Receiver as rx_class
        self.tx = {e: tx_class(e) for e in ENDPOINTS}
        self.rx = {e: rx_class(e) for e in ENDPOINTS}
        from .startup import CallSetup
        self.setup = CallSetup(self.config.profile) if self.config.call_setup else None
        self.line = PhoneLine(self.config)
        self.pending = {e: [] for e in ENDPOINTS}
        self.ready = {e: False for e in ENDPOINTS}
        self.active = True
        self.events = []
        self.commands = []
        for e in ENDPOINTS:
            self._event(0, e, "state_changed", "waiting_for_carrier")

    def _event(self, sample, endpoint, kind, detail):
        event = dict(sample_index=sample, endpoint=endpoint, type=kind, detail=detail)
        self.events.append(event)
        return event

    def enqueue_text(self, endpoint, text):
        if endpoint not in ENDPOINTS:
            raise ValueError("Endpoint must be caller or answerer")
        encode(text)
        if len(text) > 4096 or sum(map(len, self.pending[endpoint])) + len(self.tx[endpoint].bits)/10 + len(text) > 4096:
            raise ValueError("Text queue is limited to 4096 characters")
        if not self.active:
            raise ValueError("Session is disconnected; create a new engine")
        self.pending[endpoint].append(text)
        command = dict(type="send_text", sample_index=self.sample, endpoint=endpoint, text=text)
        self.commands.append(command)
        self._event(self.sample, endpoint, "text_queued", text)
        return command

    def configure(self, config):
        if self.sample % 960:
            raise ValueError("Live controls apply at a 960-sample boundary")
        if config.call_setup != self.config.call_setup:
            raise ValueError("Changing call setup requires a new session")
        if config.profile != self.config.profile:
            raise ValueError("Changing modem profile requires a new session")
        if config.seed != self.config.seed:
            raise ValueError("Changing noise seed requires a new session")
        self.line.configure(config)
        self.config = config
        command = dict(type="configure", sample_index=self.sample, config=asdict(config))
        self.commands.append(command)
        self._event(self.sample, "line", "configuration_changed", str(asdict(config)))
        return command

    def hang_up(self):
        for e in ENDPOINTS:
            count = sum(map(len, self.pending[e])) + math.ceil(len(self.tx[e].bits)/10)
            self.pending[e].clear()
            self.tx[e].bits.clear()
            self.rx[e].state = "disconnected"
            self.ready[e] = False
            if self.setup:
                self.setup.ready[e] = False
                self.setup.stages[e] = "disconnected"
                self.setup.modes[e] = "silent"
                self.setup.receiver_enabled[e] = False
            self._event(self.sample, e, "disconnected", f"Cancelled {count} pending characters")
        self.active = False
        self.commands.append(dict(type="hang_up", sample_index=self.sample))

    def process(self, block_frames=960):
        if not self.active:
            raise ValueError("Session is disconnected")
        if not isinstance(block_frames, int) or not 1 <= block_frames <= RATE:
            raise ValueError("Block size must be an integer from 1 to 48000")
        start = self.sample
        event_start = len(self.events)
        # Fixed 20 ms control boundaries make readiness independent of caller block sizes.
        streams = {f"{e}_{kind}": [] for e in ENDPOINTS for kind in ("tx", "rx")}
        decoded = {e: [] for e in ENDPOINTS}
        remaining = block_frames
        while remaining:
            if self.sample % 960 == 0:
                if self.setup:
                    for sample, endpoint, stage, detail in self.setup.advance(self.sample, {e: self.rx[e].state for e in ENDPOINTS}):
                        self._event(sample, endpoint, "call_stage_changed", f"{stage}: {detail}")
                for e in ENDPOINTS:
                    self.ready[e] = self.rx[e].state == "connected" and (self.setup is None or self.setup.ready[e])
                    if self.ready[e] and self.pending[e]:
                        text = "".join(self.pending[e])
                        self.tx[e].enqueue(text)
                        self.pending[e].clear()
                        self._event(self.sample, e, "transmit_started", text)
            segment_event_start = len(self.events)
            n = min(remaining, 960-self.sample % 960)
            transmitted = []
            for e in ENDPOINTS:
                setup_audio = self.setup.render(e, n, self.sample) if self.setup else None
                transmitted.append(self.tx[e].process(n, self.ready[e]) if setup_audio is None else setup_audio)
            received = self.line.process(*transmitted)
            for e, tx, rx in zip(ENDPOINTS, transmitted, received):
                streams[f"{e}_tx"].append(tx)
                streams[f"{e}_rx"].append(rx)
                if self.setup:
                    self.setup.observe(e, rx, self.sample)
                if self.setup is None or self.setup.receiver_enabled[e]:
                    data, events = self.rx[e].process(rx)
                else:
                    # Phone signaling is not data carrier. Keep absolute RX time
                    # without falsely acquiring the ringback or answer tone.
                    self.rx[e].sample += n
                    data, events = [], []
                for sample, byte in data:
                    decoded[e].append(dict(sample_index=sample, byte=byte))
                    self._event(sample, e, "decoded_byte", str(byte))
                for sample, kind, detail in events:
                    self._event(sample, e, kind, detail)
            self.events[segment_event_start:] = sorted(
                self.events[segment_event_start:], key=lambda event: (event["sample_index"], event["endpoint"])
            )
            self.sample += n
            remaining -= n
        return dict(start_sample=start, streams={k: np.concatenate(v) for k, v in streams.items()},
                    decoded=decoded, events=sorted(self.events[event_start:], key=lambda e: e["sample_index"]))

    def metadata(self):
        return dict(profile="Bell 103A2-style" if self.config.profile == "bell103" else "V.22bis-style 16-QAM" if self.config.profile == "qam2400" else "V.22-style DQPSK",
                    fidelity="functional" if self.config.profile == "bell103" else "experimental", profile_version=1,
                    sample_rate=RATE, config=asdict(self.config), commands=self.commands,
                    events=sorted(self.events, key=lambda e: e["sample_index"]))
