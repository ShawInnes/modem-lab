"""Sample-clock educational call setup; deliberately not a V.22 protocol emulator.

Telephone dialing, ringing and pickup are illustrative sounds. Modem startup
uses received audio evidence and actual receiver acquisition, with no access to
opposite transmitter bits, phase or clock. Durations are expressed in samples.
"""
import numpy as np
from .dsp import RATE, AMPLITUDE

ENDPOINTS = ("caller", "answerer")
BOUNDARY = 960
DIAL_END = int(.6 * RATE)
RING_END = int(1.8 * RATE)
PICKUP_END = int(1.84 * RATE)
ANSWER_END = PICKUP_END + 2 * RATE
TIMEOUT = 15 * RATE


class CallSetup:
    def __init__(self, profile):
        if profile not in ("bell103", "dqpsk1200", "qam2400"):
            raise ValueError("Unknown modem profile")
        self.profile = profile
        self.stages = {"caller": "dialing", "answerer": "waiting_for_call"}
        self.modes = {"caller": "dial", "answerer": "silent"}
        self.receiver_enabled = dict.fromkeys(ENDPOINTS, False)
        self.ready = dict.fromkeys(ENDPOINTS, False)
        self._initial = True
        self._tone_seen = False
        self._tone_good = 0
        self._tone_bad = 0
        self._tone_absent_since = None
        self._tone_tail = np.empty(0)
        self._tone_tail_start = 0
        self._connected_since = dict.fromkeys(ENDPOINTS, None)
        self._failed = False
        self._completed = False

    def _stage(self, events, sample, endpoint, stage, detail):
        if self.stages[endpoint] != stage:
            self.stages[endpoint] = stage
            events.append((sample, endpoint, stage, detail))

    def advance(self, sample, rx_states):
        """Apply startup transitions on the engine's fixed 20 ms boundaries."""
        events = []
        if self._initial:
            self._initial = False
            for endpoint in ENDPOINTS:
                events.append((sample, endpoint, self.stages[endpoint],
                               "Illustrative telephone call setup; modem acquisition follows received audio"))
        if self._failed:
            return events
        if sample >= TIMEOUT and not self._completed:
            self._failed = True
            for endpoint in ENDPOINTS:
                self.modes[endpoint] = "silent"
                self.receiver_enabled[endpoint] = False
                self.ready[endpoint] = False
                self._stage(events, sample, endpoint, "failed", "Call setup timed out without both receivers acquiring carrier")
            return events
        if sample < DIAL_END:
            return events
        if sample < RING_END:
            self.modes["caller"] = "ringback"
            self._stage(events, sample, "caller", "ringing", "Waiting for the answering modem to pick up")
            self._stage(events, sample, "answerer", "ringing", "Incoming call")
            return events
        if sample < PICKUP_END:
            self.modes.update(caller="silent", answerer="pickup")
            self._stage(events, sample, "caller", "waiting_for_answer", "Remote telephone picked up")
            self._stage(events, sample, "answerer", "pickup", "Illustrative receiver pickup click")
            return events
        if self.profile == "bell103":
            self.modes["answerer"] = "modem"
            self.receiver_enabled.update(caller=True, answerer=True)
            if self.stages["answerer"] == "pickup":
                self._stage(events, sample, "answerer", "answer_carrier", "Sending 2225 Hz answer mark; waiting for caller carrier")
            if self._tone_seen:
                self.modes["caller"] = "modem"
                if self.stages["caller"] == "waiting_for_answer":
                    self._stage(events, sample, "caller", "training", "Received answer mark; sending 1270 Hz caller mark")
        else:
            if sample < ANSWER_END:
                self.modes["answerer"] = "answer_tone"
                self._stage(events, sample, "answerer", "answer_tone", "Sending 2100 Hz answer tone for two seconds")
                if self._tone_seen:
                    self._stage(events, sample, "caller", "answer_tone_detected", "Received 2100 Hz answer tone; waiting for training")
                return events
            if sample < ANSWER_END + int(.08 * RATE):
                self.modes["answerer"] = "silent"
                self._stage(events, sample, "answerer", "quiet_gap", "Short quiet interval before differential phase training")
                return events
            self.modes["answerer"] = "modem"
            self.receiver_enabled["answerer"] = True
            if self.stages["answerer"] == "quiet_gap":
                self._stage(events, sample, "answerer", "training", "Sending 16-QAM idle symbols; waiting for caller gain and clock acquisition" if self.profile == "qam2400" else "Sending differential phase idle symbols; waiting for caller training")
            if self._tone_seen and self._tone_absent_since is not None and sample - self._tone_absent_since >= int(.15 * RATE):
                self.receiver_enabled["caller"] = True
                if self.stages["caller"] == "answer_tone_detected":
                    self._stage(events, sample, "caller", "acquiring_training", "Answer tone ended; acquiring carrier, gain and clock from received 16-QAM" if self.profile == "qam2400" else "Answer tone ended; acquiring clock from received phase symbols")
                if rx_states.get("caller") == "connected":
                    self.modes["caller"] = "modem"
                    if self.stages["caller"] == "acquiring_training":
                        self._stage(events, sample, "caller", "training", "Received 16-QAM training; sending caller 16-QAM training" if self.profile == "qam2400" else "Received phase training; sending caller phase training")
        # Each endpoint uses only its own audio receiver and local transmit
        # stage. No endpoint gets the opposite receiver's private state.
        guard = int((1.5 if self.profile == "bell103" else .8) * RATE)
        for endpoint in ENDPOINTS:
            acquired = (self.receiver_enabled[endpoint]
                        and self.modes[endpoint] == "modem"
                        and rx_states.get(endpoint) == "connected")
            if acquired:
                if self._connected_since[endpoint] is None:
                    self._connected_since[endpoint] = sample
                    self._stage(events, sample, endpoint, "settling", "Audio receiver acquired; settling before queued text")
                if sample - self._connected_since[endpoint] >= guard:
                    self.ready[endpoint] = True
                    self._stage(events, sample, endpoint, "connected", "Handshake complete; queued text can transmit")
            else:
                self._connected_since[endpoint] = None
                self.ready[endpoint] = False
                if self.stages[endpoint] in ("settling", "connected"):
                    self._stage(events, sample, endpoint, "training", "Carrier acquisition lost; waiting for received modem signal")
        if all(self.ready.values()):
            self._completed = True
        return events

    def observe(self, endpoint, samples, start_sample):
        """Detect the remote answer tone from contiguous received samples only."""
        if endpoint != "caller" or self._failed:
            return
        samples = np.asarray(samples)
        if not len(self._tone_tail):
            self._tone_tail_start = start_sample
        elif self._tone_tail_start + len(self._tone_tail) != start_sample:
            self._tone_tail = np.empty(0)
            self._tone_tail_start = start_sample
            self._tone_good = self._tone_bad = 0
        self._tone_tail = np.concatenate((self._tone_tail, samples))
        frequency = 2225 if self.profile == "bell103" else 2100
        while len(self._tone_tail) >= BOUNDARY:
            chunk = self._tone_tail[:BOUNDARY]
            indices = np.arange(self._tone_tail_start, self._tone_tail_start + BOUNDARY)
            powers = [abs(np.mean(chunk * np.exp(-2j * np.pi * f * indices / RATE)))**2
                      for f in (frequency, frequency - 150, frequency + 150)]
            present = powers[0] > .006 and powers[0] > 3 * max(powers[1:])
            end = self._tone_tail_start + BOUNDARY
            if present:
                self._tone_good += BOUNDARY
                self._tone_bad = 0
                self._tone_absent_since = None
                if self._tone_good >= int(.1 * RATE):
                    self._tone_seen = True
            else:
                self._tone_good = 0
                self._tone_bad += BOUNDARY
                if self._tone_absent_since is None:
                    self._tone_absent_since = end - BOUNDARY
            self._tone_tail = self._tone_tail[BOUNDARY:]
            self._tone_tail_start = end

    def render(self, endpoint, count, start_sample):
        """Return illustrative call audio, silence, or None for real modem DSP."""
        mode = self.modes[endpoint]
        if mode == "modem":
            return None
        samples = np.arange(start_sample, start_sample + count)
        if mode == "silent":
            return np.zeros(count)
        if mode == "answer_tone":
            return AMPLITUDE * np.sin(2 * np.pi * 2100 * samples / RATE)
        if mode == "pickup":
            elapsed = samples - RING_END
            return .18 * np.exp(-elapsed / (RATE * .007)) * np.sin(2 * np.pi * 1200 * elapsed / RATE)
        if mode == "dial":
            # Three short, illustrative DTMF bursts, with smooth 5 ms edges.
            local = samples % int(.2 * RATE)
            duration = int(.12 * RATE)
            envelope = np.clip(np.minimum(local, duration - local) / (RATE * .005), 0, 1)
            return .16 * envelope * (np.sin(2 * np.pi * 697 * samples / RATE) + np.sin(2 * np.pi * 1209 * samples / RATE))
        local = samples - DIAL_END
        duration = RING_END - DIAL_END
        envelope = np.clip(np.minimum(local, duration - local) / (RATE * .01), 0, 1)
        return .12 * envelope * (np.sin(2 * np.pi * 440 * samples / RATE) + np.sin(2 * np.pi * 480 * samples / RATE))
