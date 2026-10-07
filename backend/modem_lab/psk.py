"""Experimental V.22-style differential QPSK, not an interoperable V.22 modem.

1200 bit/s uses 600 symbols/s on 1200/2400 Hz carriers. Dibits (in wire
order) 00, 01, 11, 10 change phase by +90, 0, +270, +180 degrees respectively.
Rectangular pulses, nominal fixed symbol rate, a sample-derived acquisition
clock and raw 8N1 replace V.22 pulse shaping, scrambler and startup procedures.
No transmitter state or clock is supplied to the receiver.
"""
from collections import deque
import numpy as np
from scipy.signal import lfilter
from .dsp import RATE, AMPLITUDE, encode

SYMBOL = 80
CARRIERS = {"caller": 1200, "answerer": 2400}
DIBITS = ((0, 0), (0, 1), (1, 1), (1, 0))
PHASES = np.array([np.pi / 2, 0, -np.pi / 2, np.pi])


class Transmitter:
    def __init__(self, endpoint, phase=0.0):
        self.carrier = CARRIERS[endpoint]
        self.phase = phase
        self.bits = deque()
        self.remaining = 0

    def enqueue(self, text):
        self.bits.extend(encode(text))

    def process(self, count, ready):
        output = np.empty(count)
        offset = 0
        step = 2 * np.pi * self.carrier / RATE
        while offset < count:
            if not self.remaining:
                pair = tuple(self.bits.popleft() if ready and self.bits else 1 for _ in range(2))
                self.phase = (self.phase + PHASES[DIBITS.index(pair)]) % (2 * np.pi)
                self.remaining = SYMBOL
            n = min(count - offset, self.remaining)
            output[offset:offset+n] = AMPLITUDE * np.sin(self.phase + step * np.arange(n))
            self.phase = (self.phase + step * n) % (2 * np.pi)
            self.remaining -= n
            offset += n
        return output


class Receiver:
    def __init__(self, endpoint):
        self.carrier = CARRIERS["answerer" if endpoint == "caller" else "caller"]
        self.sample = 0
        self.history = np.zeros(SYMBOL - 1, complex)
        self.state = "waiting_for_carrier"
        self.good = self.bad = 0
        self.errors = 0
        self.confidence = 0.0
        self.clock_energy = np.zeros(SYMBOL)
        self.clock_counts = np.zeros(SYMBOL)
        self.clock = None
        self.previous_symbol = None
        self.previous_bit = 1
        self.frame = None
        self.byte = 0
        self.trace = deque(maxlen=320)
        self.symbols = deque(maxlen=160)

    def _bit(self, bit, now, decoded, events):
        if self.frame is None:
            if self.previous_bit == 1 and bit == 0:
                self.frame = 0
                self.byte = 0
        elif self.frame < 8:
            self.byte |= bit << self.frame
            self.frame += 1
        else:
            if bit:
                decoded.append((now, self.byte))
            else:
                self.errors += 1
                events.append((now, "framing_error", "Stop bit was zero; byte discarded"))
            self.frame = None
        self.previous_bit = bit

    def process(self, samples):
        indices = np.arange(self.sample, self.sample + len(samples))
        mixed = samples * np.exp(-2j * np.pi * self.carrier * indices / RATE)
        averaged, self.history = lfilter(np.ones(SYMBOL) / SYMBOL, [1.0], mixed, zi=self.history)
        decoded, events = [], []
        for now, value in zip(indices, averaged):
            now = int(now)
            power = float(abs(value) ** 2)
            present = power > 0.003
            self.good = self.good + 1 if present else 0
            self.bad = 0 if present else self.bad + 1
            old = self.state
            if self.state in ("waiting_for_carrier", "carrier_lost"):
                if present:
                    phase = now % SYMBOL
                    self.clock_energy[phase] += power
                    self.clock_counts[phase] += 1
                if self.good >= 2400:
                    self.state = "acquiring_timing"
            elif self.state == "acquiring_timing":
                phase = now % SYMBOL
                self.clock_energy[phase] += power
                self.clock_counts[phase] += 1
                if self.good >= 4800:
                    self.clock = int(np.argmax(self.clock_energy / np.maximum(1, self.clock_counts)))
                    self.previous_symbol = None
                    self.previous_bit = 1
                    self.state = "connected"
            if self.state in ("connected", "acquiring_timing") and self.bad >= 2400:
                self.state = "carrier_lost"
                self.clock = None
                self.frame = None
                self.clock_energy.fill(0)
                self.clock_counts.fill(0)
                self.previous_symbol = None
            if old != self.state:
                events.append((now, "state_changed", self.state))
            if self.clock is not None and now % SYMBOL == self.clock and self.state == "connected":
                if self.previous_symbol is not None:
                    difference = value * np.conj(self.previous_symbol)
                    difference /= max(abs(difference), 1e-12)
                    errors = np.abs(np.angle(difference * np.exp(-1j * PHASES)))
                    decision = int(np.argmin(errors))
                    self.confidence = float(max(0, 1 - errors[decision] / (np.pi / 4)))
                    # Preserve recent data decisions for inspection; idle repeats are
                    # sampled at 10 Hz while decoding still examines every symbol.
                    if self.frame is not None or decision != 2 or now % (SYMBOL * 60) == self.clock:
                        self.symbols.append([now, float(difference.real), float(difference.imag), decision, self.confidence])
                    for j, bit in enumerate(DIBITS[decision]):
                        self._bit(bit, now - SYMBOL // 2 if j == 0 else now, decoded, events)
                self.previous_symbol = value
            if now % 8 == 0:
                # Matched-filter magnitude exposes transition dips and clock alignment.
                self.trace.append([now, float(abs(value) / (AMPLITUDE / 2))])
        self.sample += len(samples)
        return decoded, events

    def diagnostics(self):
        return {"mode": "dqpsk", "symbol_samples": SYMBOL, "carrier_hz": self.carrier,
                "sample_index": self.sample, "trace": list(self.trace), "symbols": list(self.symbols),
                "timing_locked": self.state == "connected",
                "timing_note": "Audio-derived initial clock; fixed nominal 600 baud after acquisition. Differential I/Q removes absolute carrier phase. Decision indices: 0=00 (+90°), 1=01 (0°), 2=11 (−90°), 3=10 (180°)."}
