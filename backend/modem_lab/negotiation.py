"""Audio-evidenced experimental V.8 / restricted V.8bis negotiation.

Wire constants are from ITU-T V.8 (11/2000), tables 1, 3, 4 and
clauses 7/8; V.8bis (11/2000), tables 1-6 and transaction 2, clause 9.9.1.
The educational handoff uses the lab's configured experimental payload rate;
V.8 only negotiates the V.22/V.22bis *family*, never their individual rates.
"""
from collections import deque
import numpy as np
from scipy.signal import lfilter

RATE = 48000
BIT = 160
ENDPOINTS = ("caller", "answerer")
V21 = {"caller": (1180, 980), "answerer": (1850, 1650)}
CI_SYNC = (0,) * 9 + (1,)
MENU_SYNC = (0,) * 6 + (1,) * 4
FLAG = (0, 1, 1, 1, 1, 1, 1, 0)
DATA_FUNCTION = 0xC1
TE = RATE // 2
TRANSITION = 3600  # 75 ms minimum; the engine applies it on 20 ms boundaries.
TIMEOUT = 30 * RATE
BIS_TYPES = {"MS": 1, "CL": 2, "CLR": 3, "ACK(1)": 4,
             "ACK(2)": 5, "NAK(1)": 8, "NAK(2)": 9, "NAK(3)": 10, "NAK(4)": 11}


def octet_bits(value):
    return [(value >> i) & 1 for i in range(8)]


def serial_bits(data):
    return [bit for byte in data for bit in [0, *octet_bits(byte), 1]]


def menu_bytes(capabilities):
    # Table 4 modn1 bit b1 is the joint V.22bis / V.22 availability flag.
    return bytes((DATA_FUNCTION, 0x05, 0x12 if "v22" in capabilities else 0x10))


def menu_bits(data, ci=False):
    return [1] * 10 + list(CI_SYNC if ci else MENU_SYNC) + serial_bits(data)


def parse_menu(data, ci=False):
    if not data or len(data) > 32 or data[0] != DATA_FUNCTION:
        raise ValueError("Unsupported or missing data call function")
    current = None
    extension = 0
    families = []
    seen = set()
    for byte in data:
        if byte & 0x10:
            if current is None or byte & 0x28:
                raise ValueError("Malformed extension octet")
            if current == 5 and extension == 0 and byte & 2:
                families.append("v22")
            extension += 1
        else:
            current = byte & 15
            if current in seen:
                raise ValueError("Repeated information category")
            seen.add(current)
            extension = 0
    if ci and len(data) != 1:
        raise ValueError("CI must contain only its call function")
    if not ci and 5 not in seen:
        raise ValueError("Missing modulation category")
    return {"call_function": "data", "families": families,
            "rate_negotiated": False, "raw_hex": data.hex(" ")}


def fcs(data):
    """ISO 3309 reflected CRC-16/X-25, low octet first on the wire."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0x8408 if crc & 1 else 0)
    return (crc ^ 0xFFFF).to_bytes(2, "little")


def bis_bytes(kind, capabilities=("v22",), profile=None):
    # Revision 1 subset: full V.8, no shortened V.8 or segmentation;
    # transparent data, analogue PSTN, V.22 / V.22bis only.
    header = 0x10 | BIS_TYPES[kind]
    if kind.startswith(("ACK", "NAK")):
        return bytes((header,))
    id_options = 0x89 if kind == "MS" else 0x81  # V.8 + request ACK(1).
    modes = 0
    if "v22" in capabilities:
        modes = 2 if profile == "qam2400" else 4 if profile == "dqpsk1200" else 6
    # I: NPar1, SPar1. S: NPar1, SPar1(data), Data NPar2 three octets.
    return bytes((header, id_options, 0x80, 0x80, 0x81, 0x01, 0, 0xC0 | modes))


def bis_bits(data):
    stuffed, ones = [], 0
    for byte in data + fcs(data):
        for bit in octet_bits(byte):
            stuffed.append(bit)
            ones = ones + 1 if bit else 0
            if ones == 5:
                stuffed.append(0)
                ones = 0
    return [1] * 30 + list(FLAG) * 2 + stuffed + list(FLAG)


def parse_bis(data):
    if not data or len(data) > 128:
        raise ValueError("Invalid V.8bis information length")
    kind = next((k for k, v in BIS_TYPES.items() if v == data[0] & 15), None)
    if kind is None or data[0] >> 4 != 1:
        raise ValueError("Unsupported V.8bis type or revision")
    if kind.startswith(("ACK", "NAK")):
        if len(data) != 1:
            raise ValueError("ACK/NAK has no parameter field")
        return {"message": kind, "revision": 1, "families": [], "profiles": []}
    if len(data) != 8 or data[2:5] != bytes((0x80, 0x80, 0x81)) or data[5:7] != bytes((1, 0)) or data[7] & 0xC0 != 0xC0:
        raise ValueError("Unsupported parameter tree; unsegmented transparent-data subset only")
    if not data[1] & 0x80 or data[1] & 0x76:
        raise ValueError("Unsupported identification options")
    profiles = [p for mask, p in ((2, "qam2400"), (4, "dqpsk1200")) if data[7] & mask]
    if data[7] & 0x39:
        raise ValueError("Unsupported advertised modem mode")
    return {"message": kind, "revision": 1, "families": ["v22"] if profiles else [],
            "profiles": profiles, "full_v8": bool(data[1] & 1), "ack_requested": bool(data[1] & 8)}


class V21Transmitter:
    def __init__(self, role, phase=0.0):
        self.tones = V21[role]
        self.phase = phase
        self.bits = deque()
        self.remaining = 0
        self.bit = 1
        self.pattern = None
        self.sent = 0

    def set_pattern(self, bits, repeat=False, finish_octet=False):
        # A CM/JM change can finish the current serial octet before CJ.
        prefix = []
        if finish_octet and self.pattern:
            position = self.sent % len(self.pattern)
            if position >= 20:
                missing = (10 - (position - 20) % 10) % 10
                prefix = list(self.bits)[:missing]
        self.bits = deque(prefix + list(bits))
        self.pattern = tuple(bits) if repeat else None
        self.sent = 0
        if not finish_octet:
            self.remaining = 0

    @property
    def done(self):
        return not self.bits and not self.remaining and self.pattern is None

    def process(self, count):
        out = np.zeros(count)
        offset = 0
        while offset < count:
            if not self.remaining:
                if not self.bits and self.pattern:
                    self.bits.extend(self.pattern)
                if not self.bits:
                    break
                self.bit = self.bits.popleft()
                self.sent += 1
                self.remaining = BIT
            n = min(self.remaining, count - offset)
            step = 2 * np.pi * self.tones[self.bit] / RATE
            out[offset:offset+n] = .32 * np.sin(self.phase + step * np.arange(n))
            self.phase = (self.phase + n * step) % (2 * np.pi)
            self.remaining -= n
            offset += n
        return out


class V21Receiver:
    """Independent noncoherent tone energies and recovered bit clock.

    No TX timing input. A mark-to-space edge starts the nominal 300 Hz clock;
    later edges recenter the clock within a small tolerance. RX bits, not
    transmitted octets, feed both distinct protocol parsers.
    """
    def __init__(self, remote_role):
        self.tones = V21[remote_role]
        self.history = [np.zeros(BIT - 1, complex) for _ in range(2)]
        self.sample = 0
        self.previous = 1
        self.mark_run = 0
        self.clock = None
        self.absent = 0

    def process(self, samples, start):
        indices = np.arange(start, start + len(samples))
        powers = []
        for j, frequency in enumerate(self.tones):
            mixed = samples * np.exp(-2j * np.pi * frequency * indices / RATE)
            average, self.history[j] = lfilter(np.ones(BIT) / BIT, [1], mixed, zi=self.history[j])
            powers.append(abs(average) ** 2)
        out = []
        for i, (space, mark) in enumerate(zip(*powers)):
            now = start + i
            present = max(space, mark) > .0015
            self.absent = 0 if present else self.absent + 1
            if self.absent > BIT * 3:
                self.clock = None
                self.mark_run = 0
                self.previous = 1
            if not present:
                continue
            decision = int(mark >= space)
            if decision != self.previous:
                if self.clock is None and self.previous and self.mark_run >= BIT:
                    self.clock = now + BIT // 2
                # Once acquired, keep the nominal clock. Filters can move an
                # edge by several samples; sampling at window center tolerates
                # this without accumulating a data-dependent phase error.
                self.mark_run = 0
            if decision:
                self.mark_run += 1
            if self.clock is not None and now >= self.clock:
                out.append((now, decision))
                self.clock += BIT
            self.previous = decision
        self.sample = start + len(samples)
        return out


class V8Parser:
    def __init__(self):
        self.tail = deque(maxlen=20)
        self.payload = None
        self.kind = None
        self.bits = deque(maxlen=30)
        self.cj_latched = False

    def feed(self, bit):
        self.tail.append(bit)
        self.bits.append(bit)
        if self.payload is not None:
            self.payload.append(bit)
            if len(self.payload) > 340:
                self.payload = None
        result = []
        for ci, sync in ((True, CI_SYNC), (False, MENU_SYNC)):
            # Clock acquisition occurs at the first zero, so the initial
            # ten marks may not be available. Subsequent headers are full.
            header = tuple(self.tail)
            if len(header) >= 10 and header[-10:] == sync and (len(header) == 10 or header[:-10] == (1,) * 10):
                if self.payload is not None:
                    raw = self.payload[:-20]
                    if raw and len(raw) % 10 == 0:
                        try:
                            data = bytes(sum(raw[k+j+1] << j for j in range(8)) for k in range(0, len(raw), 10))
                            if any(raw[k] or raw[k+9] != 1 for k in range(0, len(raw), 10)):
                                raise ValueError("Bad start or stop bit")
                            fields = parse_menu(data, self.kind == "CI")
                            result.append((self.kind, data, fields))
                        except ValueError as exc:
                            result.append(("invalid", b"", {"reason": str(exc)}))
                self.payload = []
                self.kind = "CI" if ci else "MENU"
        if tuple(self.bits) == tuple(serial_bits(bytes(3))) and not self.cj_latched:
            self.cj_latched = True
            result.append(("CJ", bytes(3), {"octets": 3}))
        return result


class HDLCParser:
    def __init__(self):
        self.tail = deque(maxlen=8)
        self.payload = None
        self.opening_flags = 0

    def feed(self, bit):
        self.tail.append(bit)
        if self.payload is not None:
            self.payload.append(bit)
            if len(self.payload) > 1200:
                self.payload = None
                return [("invalid", b"", {"reason": "Oversize HDLC frame"})]
        if tuple(self.tail) != FLAG:
            return []
        raw = self.payload[:-8] if self.payload is not None else []
        self.payload = []
        if not raw:
            self.opening_flags = min(6, self.opening_flags + 1)
            return []
        flags = self.opening_flags
        self.opening_flags = 1
        try:
            if not 2 <= flags <= 5:
                raise ValueError("V.8bis requires two to five opening HDLC flags")
            bits, ones = [], 0
            for bit in raw:
                if ones == 5:
                    if bit:
                        raise ValueError("Invalid HDLC bit stuffing")
                    ones = 0
                    continue
                bits.append(bit)
                ones = ones + 1 if bit else 0
            if ones == 5:
                raise ValueError("Missing final HDLC stuffed zero")
            if len(bits) % 8 or len(bits) < 24:
                raise ValueError("Incomplete HDLC octets")
            data = bytes(sum(bits[k+j] << j for j in range(8)) for k in range(0, len(bits), 8))
            if fcs(data[:-2]) != data[-2:]:
                raise ValueError("Bad V.8bis frame check sequence")
            fields = parse_bis(data[:-2])
            fields["frame_check"] = "valid"
            return [(fields["message"], data[:-2], fields)]
        except ValueError as exc:
            return [("invalid", b"", {"reason": str(exc)})]


class AnswerToneDetector:
    """15 Hz envelope evidence, independent of carrier phase and phase reversals."""
    def __init__(self):
        self.tail = np.empty(0)
        self.start = 0
        self.envelopes = deque(maxlen=48)
        self.detected = False
        self.modulation_depth = 0.0

    def process(self, samples, start):
        if not len(self.tail):
            self.start = start
        self.tail = np.concatenate((self.tail, samples))
        while len(self.tail) >= 320:
            chunk = self.tail[:320]
            indices = np.arange(self.start, self.start + 320)
            carrier = np.mean(chunk * np.exp(-2j * np.pi * 2100 * indices / RATE))
            amplitude = 2 * abs(carrier)
            adjacent = max(2*abs(np.mean(chunk*np.exp(-2j*np.pi*f*indices/RATE))) for f in (2025, 2175))
            self.envelopes.append((self.start + 160, amplitude, np.angle(carrier), adjacent))
            self.tail = self.tail[320:]
            self.start += 320
            if len(self.envelopes) < 40:
                continue
            times, values, phases, adjacent = np.array(self.envelopes).T
            mean = np.mean(values)
            design = np.column_stack((np.ones(len(times)), np.sin(2*np.pi*15*times/RATE), np.cos(2*np.pi*15*times/RATE)))
            fit = np.linalg.lstsq(design, values, rcond=None)[0]
            depth = np.hypot(fit[1], fit[2]) / (mean + 1e-12)
            residual = np.sqrt(np.mean((values - design @ fit) ** 2)) / (mean + 1e-12)
            self.modulation_depth = float(depth)
            # Doubling phase makes 180-degree reversals invisible. A median
            # phase increment rejects adjacent carriers without confusing the
            # occasional reversal-window transient with frequency drift.
            frequency_error = np.median(np.angle(np.exp(2j*np.diff(phases)))) * RATE / (4*np.pi*320)
            if mean > .09 and mean > 1.1*np.mean(adjacent) and .12 < depth < .29 and residual < .18 and abs(frequency_error) < 3:
                self.detected = True
        return self.detected


class RequestDetector:
    """V.8bis initiating CRd: 1375+2002 Hz for 400 ms, then 1900 for 100 ms."""
    def __init__(self):
        self.tail = np.empty(0)
        self.start = 0
        self.dual = self.single = 0
        self.segment = False
        self.detected = False
        self.gap = 0

    def process(self, samples, start):
        if not len(self.tail):
            self.start = start
        self.tail = np.concatenate((self.tail, samples))
        while len(self.tail) >= 480:
            chunk = self.tail[:480]
            indices = np.arange(self.start, self.start + 480)
            powers = [abs(np.mean(chunk*np.exp(-2j*np.pi*f*indices/RATE)))**2 for f in (1375, 2002, 1900)]
            if powers[0] > .003 and powers[1] > .003 and min(powers[:2]) > powers[2] * 2:
                self.dual += 480
                if self.dual >= int(.36*RATE):
                    self.segment = True
                self.single = 0
                self.gap = 0
            elif self.segment and powers[2] > .008 and powers[2] > max(powers[:2])*2:
                self.single += 480
                self.gap = 0
                if self.single >= int(.08*RATE):
                    self.detected = True
            else:
                self.gap += 480
                if self.gap > 960:
                    self.segment = False
                    self.dual = 0
                if not self.segment:
                    self.dual = 0
                self.single = 0
            self.tail = self.tail[480:]
            self.start += 480
        return self.detected


class Negotiation:
    def __init__(self, profile, mode="v8", capabilities=None, v8bis=None, bis_initiator="caller"):
        if profile not in ("dqpsk1200", "qam2400") or mode not in ("v8", "v8bis"):
            raise ValueError("Negotiation requires an executable phase/QAM profile")
        self.profile, self.mode = profile, mode
        if bis_initiator not in ENDPOINTS:
            raise ValueError("Unknown V.8bis initiator")
        self.bis_initiator = bis_initiator
        self.payload_roles = {e: ("caller" if e == bis_initiator else "answerer") if mode == "v8bis" else e for e in ENDPOINTS}
        self.capabilities = capabilities or {e: ("v22",) for e in ENDPOINTS}
        self.v8bis = v8bis or dict.fromkeys(ENDPOINTS, True)
        if any(set(self.capabilities[e]) - {"v22"} for e in ENDPOINTS):
            raise ValueError("Only executable V.22/V.22bis family may be advertised")
        self.stages = dict.fromkeys(ENDPOINTS, "negotiation_start")
        self.modes = dict.fromkeys(ENDPOINTS, "silent")
        self.receiver_enabled = dict.fromkeys(ENDPOINTS, False)
        self.ready = dict.fromkeys(ENDPOINTS, False)
        self.selected = dict.fromkeys(ENDPOINTS, None)
        self.messages = deque(maxlen=128)
        self.tx = {e: V21Transmitter(self.payload_roles[e]) for e in ENDPOINTS}
        self.rx = {e: V21Receiver("answerer" if self.payload_roles[e] == "caller" else "caller") for e in ENDPOINTS}
        self.parser = {e: V8Parser() for e in ENDPOINTS}
        self.hdlc = {e: HDLCParser() for e in ENDPOINTS}
        self.tone = AnswerToneDetector()
        self.request = RequestDetector()
        self.phase = dict.fromkeys(ENDPOINTS, "initial")
        self.since = dict.fromkeys(ENDPOINTS, 0)
        self.connected_since = dict.fromkeys(ENDPOINTS, None)
        self.repetitions = dict.fromkeys(ENDPOINTS, 0)
        self.last_menu = dict.fromkeys(ENDPOINTS, None)
        self.received = dict.fromkeys(ENDPOINTS, None)
        self.received_fields = dict.fromkeys(ENDPOINTS, None)
        self.rx_signal = dict.fromkeys(ENDPOINTS, "waiting")
        self.tx_signal = dict.fromkeys(ENDPOINTS, "silence")
        self.outcome = "in_progress"
        self.protocol = "V.8bis" if mode == "v8bis" else "V.8"
        self._started = False
        self._events = []
        self._v8_start = dict.fromkeys(ENDPOINTS, 0)
        self._bis_selected = dict.fromkeys(ENDPOINTS, None)
        self._agreed = dict.fromkeys(ENDPOINTS, False)
        self._trained = dict.fromkeys(ENDPOINTS, False)

    def _stage(self, endpoint, sample, stage, detail):
        if self.stages[endpoint] != stage:
            self.stages[endpoint] = stage
            self._events.append((sample, endpoint, stage, detail))

    def _message(self, endpoint, sample, protocol, signal, direction, data=b"", fields=None, validation="valid", reason=""):
        self.messages.append({"sample_index": int(sample), "endpoint": endpoint,
                              "detail": reason or f"{protocol} {signal} {'received' if direction == 'rx' else 'transmitted'}",
                              "negotiation": {"protocol": protocol, "signal": signal, "direction": direction,
                                              "raw_hex": data.hex(" "), "fields": fields or {},
                                              "validation": validation, "repetitions": self.repetitions[endpoint], "reason": reason}})

    def _send(self, endpoint, sample, signal, data, bis=False, repeat=False, finish=False):
        self.tx[endpoint].set_pattern(bis_bits(data) if bis else serial_bits(data) if signal == "CJ" else menu_bits(data, signal == "CI"), repeat, finish)
        self.modes[endpoint] = "v21"
        self.tx_signal[endpoint] = signal
        self._message(endpoint, sample, "V.8bis" if bis else "V.8", signal, "tx", data)

    def _v8(self, endpoint, sample):
        self.protocol = "V.8"
        if not self._bis_selected[endpoint]:
            # Optional discovery failed: normal V.8 uses telephone call roles.
            self.payload_roles[endpoint] = endpoint
        self._v8_start[endpoint] = sample
        self.since[endpoint] = sample
        self.parser[endpoint] = V8Parser()
        self.hdlc[endpoint] = HDLCParser()
        self.tx[endpoint] = V21Transmitter(self.payload_roles[endpoint])
        self.rx[endpoint] = V21Receiver("answerer" if self.payload_roles[endpoint] == "caller" else "caller")
        self.phase[endpoint] = "v8_wait"
        self.modes[endpoint] = "silent"
        self.tx_signal[endpoint] = "silence"
        self._stage(endpoint, sample, "waiting_for_ansam" if self.payload_roles[endpoint] == "caller" else "v8_answer_wait", "V.8 full menu exchange; payload training remains separate")

    def _fail(self, endpoint, sample, reason):
        self.phase[endpoint] = "failed"
        self.modes[endpoint] = "silent"
        self.tx_signal[endpoint] = "silence"
        self.ready[endpoint] = False
        self.receiver_enabled[endpoint] = False
        self.outcome = "failed"
        self._stage(endpoint, sample, "failed", reason)
        self._message(endpoint, sample, self.protocol, "failure", "rx", validation="failed", reason=reason)

    def advance(self, sample, rx_states):
        if not self._started:
            self._started = True
            for e in ENDPOINTS:
                if self.mode == "v8bis" and self.v8bis[e]:
                    self.phase[e] = "bis_initial"
                    self._stage(e, sample, "v8bis_discovery", "Restricted V.8bis transaction 2 after telephone connection")
                else:
                    self._v8(e, sample)
        for e in ENDPOINTS:
            phase = self.phase[e]
            elapsed = sample - self.since[e]
            if phase == "failed":
                continue
            if sample > TIMEOUT and not self._trained[e]:
                self._fail(e, sample, f"Timed out waiting for received evidence in {self.stages[e]}")
                continue
            if phase == "bis_initial" and e == self.bis_initiator and sample >= RATE//5:
                self.phase[e] = "bis_request"
                self.since[e] = sample
                self.modes[e] = "crd"
                self.tx_signal[e] = "CRd"
                self._message(e, sample, "V.8bis", "CRd", "tx")
            elif phase == "bis_request" and elapsed >= RATE//2:
                self.phase[e] = "bis_wait_cl"
                self.modes[e] = "silent"
                self.tx_signal[e] = "silence"
                self.since[e] = sample
            elif phase in ("bis_initial", "bis_wait_cl") and elapsed >= 5*RATE:
                self._message(e, sample, "V.8bis", "fallback", "rx", reason="V.8bis unavailable — trying V.8; no capabilities synthesized")
                self._v8(e, sample)
            elif phase == "bis_send_cl" and self.tx[e].done:
                self.phase[e] = "bis_wait_ms"
                self.modes[e] = "silent"
                self.tx_signal[e] = "silence"
                self.since[e] = sample
            elif phase == "bis_send_ms" and self.tx[e].done:
                self.phase[e] = "bis_wait_ack"
                self.modes[e] = "silent"
                self.tx_signal[e] = "silence"
                self.since[e] = sample
            elif phase == "bis_send_ack" and self.tx[e].done:
                self._v8(e, sample)
            elif phase == "bis_send_nak" and self.tx[e].done:
                self._fail(e, sample, "V.8bis rejected unsupported mode or invalid frame")
            elif phase in ("bis_wait_ms", "bis_wait_ack") and elapsed >= 5*RATE:
                self._fail(e, sample, "V.8bis transaction timed out without a valid response")
            elif phase == "v8_wait":
                if self.payload_roles[e] == "answerer" and sample - self._v8_start[e] >= (RATE//5 if self._bis_selected[e] else int(1.4*RATE)):
                    self.phase[e] = "ansam"
                    self.modes[e] = "ansam"
                    self.tx_signal[e] = "ANSam"
                    self.since[e] = sample
                    self._stage(e, sample, "sending_ansam", "2100 Hz answer tone, 15 Hz amplitude modulation, 450 ms phase reversals")
                    self._message(e, sample, "V.8", "ANSam", "tx")
                elif self.payload_roles[e] == "caller" and sample - self._v8_start[e] >= RATE:
                    self._send(e, sample, "CI", bytes((DATA_FUNCTION,)), repeat=True)
                    self.phase[e] = "ci"
                    self.since[e] = sample
            elif phase == "ci" and elapsed >= int(.3*RATE):
                self.modes[e] = "silent"
                self.tx_signal[e] = "silence"
                self.phase[e] = "ci_off"
                self.since[e] = sample
            elif phase == "ci_off" and elapsed >= RATE//2:
                self._send(e, sample, "CI", bytes((DATA_FUNCTION,)), repeat=True)
                self.phase[e] = "ci"
                self.since[e] = sample
            elif phase == "te" and elapsed >= TE:
                self._send(e, sample, "CM", menu_bytes(self.capabilities[e]), repeat=True)
                self.phase[e] = "cm"
                self._stage(e, sample, "sending_cm", "CM advertises the executable V.22/V.22bis family")
            elif phase == "ansam" and elapsed >= 5*RATE:
                self._fail(e, sample, "ANSam timed out without two identical received CM sequences; legacy fallback disabled")
            elif phase == "cj" and self.tx[e].done:
                self.modes[e] = "silent"
                self.tx_signal[e] = "silence"
                self.phase[e] = "transition"
                self.since[e] = sample
            elif phase == "transition" and elapsed >= TRANSITION:
                if not self._agreed[e]:
                    self._fail(e, sample, "No common executable modem family")
                else:
                    self.selected[e] = self.profile
                    self.receiver_enabled[e] = True
                    self.modes[e] = "modem"
                    self.tx_signal[e] = "payload_training"
                    self.phase[e] = "training"
                    self._stage(e, sample, "training", "V.22 family agreed; configured experimental payload rate training now begins")
            elif phase == "training":
                if rx_states.get(e) == "connected":
                    if self.connected_since[e] is None:
                        self.connected_since[e] = sample
                    if sample - self.connected_since[e] >= int(.8*RATE):
                        self.ready[e] = True
                        self._trained[e] = True
                        self.tx_signal[e] = "payload"
                        self._stage(e, sample, "connected", "Actual payload receiver acquired; ready for terminal text")
                else:
                    self.connected_since[e] = None
                    self.ready[e] = False
                    self.tx_signal[e] = "payload_training"
                    self._stage(e, sample, "training", "Payload carrier lost; waiting for actual receiver reacquisition")
        if all(self.ready.values()):
            self.outcome = "connected"
        events, self._events = self._events, []
        return events

    def observe(self, endpoint, samples, start_sample):
        phase = self.phase[endpoint]
        if phase in ("failed", "training", "transition", "cj"):
            return
        end = start_sample + len(samples)
        caller = self.payload_roles[endpoint] == "caller"
        discovery = phase in ("bis_initial", "bis_request", "bis_wait_cl")
        detected = (caller or (discovery and endpoint == "caller")) and phase in ("bis_initial", "bis_request", "bis_wait_cl", "v8_wait", "ci", "ci_off") and self.tone.process(samples, start_sample)
        if discovery and detected:
            self._message(endpoint, end, "V.8bis", "fallback", "rx", reason="V.8bis unavailable — received ANSam, trying full V.8")
            self._v8(endpoint, end)
            phase = "v8_wait"
            caller = self.payload_roles[endpoint] == "caller"
        if caller and phase in ("v8_wait", "ci", "ci_off") and detected:
            self.phase[endpoint] = "te"
            self.modes[endpoint] = "silent"
            self.tx_signal[endpoint] = "silence"
            self.since[endpoint] = end
            self.rx_signal[endpoint] = "ANSam"
            self._stage(endpoint, end, "ansam_detected", "Received 2100 Hz with measured 15 Hz envelope; observing Te before CM")
            self._message(endpoint, end, "V.8", "ANSam", "rx", fields={"measured_modulation_depth": self.tone.modulation_depth})
        if endpoint != self.bis_initiator and phase == "bis_initial" and self.request.process(samples, start_sample):
            self._message(endpoint, end, "V.8bis", "CRd", "rx", fields={"segments": ["1375+2002 Hz", "1900 Hz"]})
            self._send(endpoint, end, "CL", bis_bytes("CL", self.capabilities[endpoint]), bis=True)
            self.phase[endpoint] = "bis_send_cl"
            self.since[endpoint] = end
        for now, bit in self.rx[endpoint].process(samples, start_sample):
            if self.phase[endpoint].startswith("bis"):
                packets = self.hdlc[endpoint].feed(bit)
                for kind, data, fields in packets:
                    self._bis_received(endpoint, now, kind, data, fields)
            else:
                for kind, data, fields in self.parser[endpoint].feed(bit):
                    self._menu_received(endpoint, now, kind, data, fields)

    def _menu_received(self, e, now, kind, data, fields):
        if kind == "invalid":
            self.repetitions[e] = 0
            self._message(e, now, "V.8", "menu", "rx", validation="invalid", reason=fields["reason"])
            return
        signal = kind if kind != "MENU" else "JM" if self.payload_roles[e] == "caller" else "CM"
        self.rx_signal[e] = signal
        if signal == "CI":
            self._message(e, now, "V.8", signal, "rx", data, fields)
            return
        if signal == "CJ":
            if self.phase[e] == "jm":
                self._message(e, now, "V.8", signal, "rx", data, fields)
                self.phase[e] = "transition"
                self.modes[e] = "silent"
                self.tx_signal[e] = "silence"
                self.since[e] = now
                self._stage(e, now, "negotiation_complete", "Three zero octets received; 75 ms transition before modem training")
            return
        previous = self.received[e]
        self.repetitions[e] = self.repetitions[e] + 1 if previous == data else 1
        self.received[e] = data
        self.received_fields[e] = fields
        self.last_menu[e] = (data, fields)
        self._message(e, now, "V.8", signal, "rx", data, fields)
        if self.repetitions[e] < 2:
            return
        if self.payload_roles[e] == "answerer" and self.phase[e] == "ansam":
            common = set(fields["families"]) & set(self.capabilities[e])
            joint = menu_bytes(common)
            self._agreed[e] = "v22" in common
            self.last_menu[e] = (joint, parse_menu(joint))
            self._send(e, now, "JM", joint, repeat=True)
            self.phase[e] = "jm"
            self._stage(e, now, "sending_jm", "Two identical CM menus received; JM reports their intersection with local capabilities")
        elif self.payload_roles[e] == "caller" and self.phase[e] == "cm":
            if set(fields["families"]) - set(self.capabilities[e]):
                self._fail(e, now, "JM selected a family absent from the caller offer")
                return
            self._send(e, now, "CJ", bytes(3), finish=True)
            self._agreed[e] = "v22" in fields["families"]
            self.phase[e] = "cj"
            self._stage(e, now, "sending_cj", "Two identical JM menus received; confirming with three framed zero octets")

    def _bis_received(self, e, now, kind, data, fields):
        self.rx_signal[e] = kind
        if kind == "invalid":
            self._message(e, now, "V.8bis", "frame", "rx", validation="invalid", reason=fields["reason"])
            self._send(e, now, "NAK(1)", bis_bytes("NAK(1)"), bis=True)
            self.phase[e] = "bis_send_nak"
            return
        self._message(e, now, "V.8bis", kind, "rx", data, fields)
        self.received[e] = data
        self.received_fields[e] = fields
        if e == self.bis_initiator and self.phase[e] == "bis_wait_cl" and kind == "CL":
            if self.profile not in fields["profiles"] or "v22" not in self.capabilities[e] or not fields["full_v8"]:
                self._fail(e, now, "No common requested V.8bis mode with full V.8 handoff")
                return
            self._bis_selected[e] = self.profile
            self._send(e, now, "MS", bis_bytes("MS", self.capabilities[e], self.profile), bis=True)
            self.phase[e] = "bis_send_ms"
            self._stage(e, now, "v8bis_selecting", "Actual CL decoded; MS requests configured mode, full V.8 and ACK(1)")
        elif e != self.bis_initiator and self.phase[e] == "bis_wait_ms" and kind == "MS":
            accepted = fields["profiles"] == [self.profile] and "v22" in self.capabilities[e] and fields["full_v8"] and fields["ack_requested"]
            if accepted:
                self._bis_selected[e] = self.profile
            response = "ACK(1)" if accepted else "NAK(3)"
            self._send(e, now, response, bis_bytes(response), bis=True)
            self.phase[e] = "bis_send_ack" if accepted else "bis_send_nak"
            self._stage(e, now, "v8bis_accepted" if accepted else "v8bis_rejected", "Received mode select validated against local enabled mode")
        elif e == self.bis_initiator and self.phase[e] == "bis_wait_ack":
            if kind == "ACK(1)":
                self._v8(e, now)
                self._stage(e, now, "v8bis_complete", "Received ACK(1); full V.8 follows as requested by the MS information field")
            elif kind.startswith("NAK"):
                self._fail(e, now, "Remote V.8bis peer rejected mode selection")

    def render(self, endpoint, count, start_sample):
        mode = self.modes[endpoint]
        if mode == "modem":
            return None
        if mode == "v21":
            return self.tx[endpoint].process(count)
        samples = np.arange(start_sample, start_sample + count)
        if mode == "ansam":
            relative = samples - self.since[endpoint]
            reverse = 1 - 2 * ((relative // 21600) % 2)
            return .32 * (1 + .2*np.sin(2*np.pi*15*relative/RATE))*reverse*np.sin(2*np.pi*2100*relative/RATE)
        if mode == "crd":
            relative = samples - self.since[endpoint]
            return np.where(relative < 19200,
                            .16*(np.sin(2*np.pi*1375*relative/RATE)+np.sin(2*np.pi*2002*relative/RATE)),
                            .32*np.sin(2*np.pi*1900*relative/RATE)) * (relative < 24000)
        return np.zeros(count)

    def telemetry(self):
        endpoints = {}
        for e in ENDPOINTS:
            received = self.received_fields[e].get("families", []) if self.received_fields[e] else []
            endpoints[e] = {"stage": self.stages[e], "modem_role": self.payload_roles[e], "tx_signal": self.tx_signal[e], "rx_state": self.rx_signal[e],
                            "offered": list(self.capabilities[e]), "received": received,
                            "menu_hex": self.received[e].hex(" ") if self.received[e] else "",
                            "repetitions": self.repetitions[e], "validation": "valid" if self.received[e] else "waiting",
                            "selected_family": "v22" if self.selected[e] else None,
                            "selected_profile": self.selected[e], "selected": self.selected[e], "v8bis_selected_profile": self._bis_selected[e]}
        return {"protocol": self.protocol, "stage": self.stages["caller"], "endpoints": endpoints,
                "selected_profile": self.selected["caller"], "selected_family": "v22" if self.selected["caller"] else None,
                "outcome": self.outcome, "rate_policy": "configured experimental payload rate; V.8 negotiates only its family"}

    def drain_messages(self):
        result = list(self.messages)
        self.messages.clear()
        return result
