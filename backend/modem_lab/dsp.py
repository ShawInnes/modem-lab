"""Continuous-phase FSK and a receiver with no transmitter timing input."""
from collections import deque
import numpy as np
from scipy.signal import lfilter

RATE = 48_000
BIT = 160
TONES = {"caller": (1070, 1270), "answerer": (2025, 2225)}
AMPLITUDE = 0.4


def encode(text):
    if not isinstance(text, str) or not text.isascii():
        raise ValueError("Only 7-bit ASCII text is supported (8N1, high bit zero).")
    return [bit for byte in text.encode("ascii")
            for bit in [0, *[(byte >> i) & 1 for i in range(8)], 1]]


class Transmitter:
    def __init__(self, endpoint, phase=0.0):
        self.tones = TONES[endpoint]
        self.phase = phase
        self.bits = deque()
        self.remaining = 0
        self.bit = 1

    def enqueue(self, text):
        self.bits.extend(encode(text))

    def process(self, count, ready):
        output = np.empty(count)
        offset = 0
        while offset < count:
            if not self.remaining:
                self.bit = self.bits.popleft() if ready and self.bits else 1
                self.remaining = BIT
            n = min(self.remaining, count - offset)
            step = 2 * np.pi * self.tones[self.bit] / RATE
            output[offset:offset+n] = AMPLITUDE * np.sin(self.phase + step * np.arange(n))
            self.phase = (self.phase + step * n) % (2 * np.pi)
            self.remaining -= n
            offset += n
        return output


class Receiver:
    def __init__(self, endpoint):
        self.tones = TONES["answerer" if endpoint == "caller" else "caller"]
        self.sample = 0
        self.history = [np.zeros(BIT-1, complex), np.zeros(BIT-1, complex)]
        self.state = "waiting_for_carrier"
        self.good = self.bad = 0
        self.previous = 1
        self.frame = None
        self.next_decision = 0
        self.byte = 0
        self.errors = 0
        self.confidence = 0.0
        self.trace = deque(maxlen=320)
        self.symbols = deque(maxlen=160)

    def process(self, samples):
        indices = np.arange(self.sample, self.sample + len(samples))
        energies = []
        for i, frequency in enumerate(self.tones):
            mixed = samples * np.exp(-2j * np.pi * frequency * indices / RATE)
            averaged, self.history[i] = lfilter(np.ones(BIT)/BIT, [1.0], mixed, zi=self.history[i])
            energies.append(np.abs(averaged)**2)
        events, decoded = [], []
        for i, (space, mark) in enumerate(zip(*energies)):
            now = self.sample + i
            strongest = max(space, mark)
            confidence = abs(mark-space) / (mark+space+1e-12)
            self.confidence = float(confidence)
            if now % 10 == 0:
                self.trace.append([now, float((mark-space)/(mark+space+1e-12))])
            present = strongest > 0.004
            self.good = self.good + 1 if present else 0
            self.bad = 0 if present else self.bad + 1
            old = self.state
            if self.state in ("waiting_for_carrier", "carrier_lost") and self.good >= 2400:
                self.state = "acquiring_timing"
            elif self.state == "acquiring_timing" and self.good >= 4800:
                self.state = "connected"
            if self.state in ("connected", "acquiring_timing") and self.bad >= 2400:
                self.state = "carrier_lost"
                self.frame = None
            if old != self.state:
                events.append((now, "state_changed", self.state))
            decision = int(mark >= space)
            if self.state == "connected":
                if self.frame is None and self.previous == 1 and decision == 0:
                    # A one-bit trailing detector adds roughly half a bit of delay.
                    # Validate the start, then sample data every 160 samples.
                    self.frame = -1
                    self.next_decision = now + BIT//2
                    self.byte = 0
                elif self.frame is not None and now >= self.next_decision:
                    self.symbols.append([now, float(space), float(mark), decision, float(confidence)])
                    if self.frame == -1:
                        if decision:
                            self.frame = None
                        else:
                            self.frame = 0
                            self.next_decision += BIT
                    elif self.frame < 8:
                        self.byte |= decision << self.frame
                        self.frame += 1
                        self.next_decision += BIT
                    else:
                        if decision:
                            decoded.append((now, self.byte))
                        else:
                            self.errors += 1
                            events.append((now, "framing_error", "Stop bit was space; byte discarded"))
                        self.frame = None
            self.previous = decision
        self.sample += len(samples)
        return decoded, events

    def diagnostics(self):
        return dict(mode="fsk", symbol_samples=BIT, sample_index=self.sample,
                    trace=list(self.trace), symbols=list(self.symbols),
                    timing_locked=self.state == "connected" and bool(self.symbols),
                    timing_note="Start-edge timing; fixed 300 bit/s clock. No adaptive clock-rate recovery.")
