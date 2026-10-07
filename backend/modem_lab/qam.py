"""Experimental V.22bis-style 2400 bit/s, 600 baud differential 16-QAM.

The first dibit changes quadrant per V.22bis Table 1; the second selects
Figure 2's (1,1), (3,1), (1,3), (3,3) point, rotated with that quadrant.
Rectangular pulses, raw 8N1 and an idle-derived nominal symbol clock replace
standard shaping, scrambling, equalization and interoperable startup.
The receiver observes only audio; no transmitter clock or phase is shared.
"""
from collections import deque
import numpy as np
from scipy.signal import lfilter
from .dsp import RATE, AMPLITUDE, encode

SYMBOL = 80
CARRIERS = {"caller": 1200, "answerer": 2400}
DIBITS = ((0, 0), (0, 1), (1, 0), (1, 1))
STEPS = (1, 0, 2, 3)
INNER = np.array([1+1j, 3+1j, 1+3j, 3+3j])
POINTS = np.array([point * (1j ** quadrant) for quadrant in range(4) for point in INNER])
SCALE = AMPLITUDE / np.sqrt(18)


class Transmitter:
    def __init__(self, endpoint, phase=0.0):
        self.carrier = CARRIERS[endpoint]
        self.phase = phase
        self.quadrant = 0
        self.bits = deque()
        self.remaining = 0
        self.point = INNER[3]

    def enqueue(self, text):
        self.bits.extend(encode(text))

    def process(self, count, ready):
        output = np.empty(count)
        offset = 0
        step = 2*np.pi*self.carrier/RATE
        while offset < count:
            if not self.remaining:
                bits = tuple(self.bits.popleft() if ready and self.bits else 1 for _ in range(4))
                self.quadrant = (self.quadrant + STEPS[DIBITS.index(bits[:2])]) % 4
                self.point = INNER[DIBITS.index(bits[2:])] * (1j ** self.quadrant)
                self.remaining = SYMBOL
            n = min(count-offset, self.remaining)
            output[offset:offset+n] = SCALE * np.real(self.point * np.exp(1j*(self.phase + step*np.arange(n))))
            self.phase = (self.phase + step*n) % (2*np.pi)
            self.remaining -= n
            offset += n
        return output


class Receiver:
    def __init__(self, endpoint):
        self.carrier = CARRIERS["answerer" if endpoint == "caller" else "caller"]
        self.sample = 0
        self.history = np.zeros(SYMBOL-1, complex)
        self.state = "waiting_for_carrier"
        self.good = self.bad = 0
        self.errors = 0
        self.confidence = 0.0
        self.clock_energy = np.zeros(SYMBOL)
        self.clock_counts = np.zeros(SYMBOL)
        self.clock_fourth = np.zeros(SYMBOL, complex)
        self.clock = None
        self.gain = 1+0j
        self.previous_quadrant = None
        self.previous_bit = 1
        self.frame = None
        self.byte = 0
        self.trace = deque(maxlen=320)
        self.symbols = deque(maxlen=160)
        self.last_bits = "1111"

    def _bit(self, bit, now, decoded, events):
        if self.frame is None:
            if self.previous_bit == 1 and bit == 0:
                self.frame, self.byte = 0, 0
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
        indices = np.arange(self.sample, self.sample+len(samples))
        mixed = samples*np.exp(-2j*np.pi*self.carrier*indices/RATE)
        averaged, self.history = lfilter(np.ones(SYMBOL)/SYMBOL, [1.0], mixed, zi=self.history)
        decoded, events = [], []
        for now, value in zip(indices, averaged):
            now = int(now)
            power = float(abs(value)**2)
            present = power > .0025
            self.good = self.good+1 if present else 0
            self.bad = 0 if present else self.bad+1
            old = self.state
            if self.state in ("waiting_for_carrier", "carrier_lost", "acquiring_timing"):
                if present:
                    phase = now % SYMBOL
                    self.clock_energy[phase] += power
                    self.clock_counts[phase] += 1
                    self.clock_fourth[phase] += value**4
                if self.good >= 2400:
                    self.state = "acquiring_timing"
                if self.good >= 4800:
                    self.clock = int(np.argmax(self.clock_energy/np.maximum(1, self.clock_counts)))
                    magnitude = np.sqrt(self.clock_energy[self.clock]/self.clock_counts[self.clock]/18)
                    rotation = np.angle(self.clock_fourth[self.clock]/(INNER[3]**4))/4
                    self.gain = magnitude*np.exp(1j*rotation)
                    self.previous_quadrant = None
                    self.previous_bit = 1
                    self.state = "connected"
            if self.state in ("connected", "acquiring_timing") and self.bad >= 2400:
                self.state = "carrier_lost"
                self.clock = None
                self.frame = None
                self.previous_quadrant = None
                self.clock_energy.fill(0)
                self.clock_counts.fill(0)
                self.clock_fourth.fill(0)
            if old != self.state:
                events.append((now, "state_changed", self.state))
            if self.clock is not None and now % SYMBOL == self.clock and self.state == "connected":
                corrected = value/self.gain
                distances = abs(corrected-POINTS)
                point = int(np.argmin(distances))
                quadrant, inner = divmod(point, 4)
                self.confidence = float(np.clip(1-distances[point], 0, 1))
                if self.previous_quadrant is not None:
                    change = (quadrant-self.previous_quadrant) % 4
                    first = STEPS.index(change)
                    bits = DIBITS[first]+DIBITS[inner]
                    decision = first*4+inner
                    self.last_bits = ''.join(map(str, bits))
                    if self.frame is not None or decision != 15 or now % (SYMBOL*60) == self.clock:
                        self.symbols.append([now, float(corrected.real), float(corrected.imag), decision, self.confidence])
                    for bit in bits:
                        self._bit(bit, now, decoded, events)
                self.previous_quadrant = quadrant
            if now % 8 == 0:
                self.trace.append([now, float((value/self.gain).real) if self.clock is not None else 0.0])
        self.sample += len(samples)
        return decoded, events

    def diagnostics(self):
        return {"mode": "qam16", "symbol_samples": SYMBOL, "carrier_hz": self.carrier,
                "sample_index": self.sample, "trace": list(self.trace), "symbols": list(self.symbols),
                "timing_locked": self.state == "connected", "last_bits": self.last_bits,
                "constellation": [[float(p.real), float(p.imag), ''.join(map(str, DIBITS[k%4]))] for k, p in enumerate(POINTS)],
                "bit_labels": [''.join(map(str, a+b)) for a in DIBITS for b in DIBITS],
                "timing_note": "Audio-derived idle timing, gain and carrier phase; fixed nominal 600 baud thereafter. Four bits per symbol: two change quadrant, two select position within it. Amplitude is retained. No adaptive equalizer."}
