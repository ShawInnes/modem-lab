"""Causal symmetrical line with independent deterministic noise streams."""
import copy
import numpy as np
from scipy.signal import butter, sosfilt
from .dsp import RATE, AMPLITUDE


class Delay:
    def __init__(self, count):
        self.history = np.zeros(count)

    def process(self, samples):
        if not len(self.history):
            return samples.copy()
        combined = np.concatenate((self.history, samples))
        result = combined[:len(samples)].copy()
        self.history = combined[len(samples):].copy()
        return result


class PhoneLine:
    def __init__(self, config):
        self.remote = [Delay(round(config.delay_ms * RATE/1000)) for _ in range(2)]
        self.echo = [Delay(round(config.echo_delay_ms * RATE/1000)) for _ in range(2)]
        self.echo_gain = 10**(-config.echo_attenuation_db/20)
        self.noise_rms = AMPLITUDE / np.sqrt(2) * 10**(-config.snr_db/20)
        self.rngs = [np.random.default_rng(s) for s in np.random.SeedSequence(config.seed).spawn(2)]
        limits = {"telephone": (300, 3400), "narrow": (900, 2400)}
        self.sos = butter(4, limits[config.bandpass], btype="bandpass", fs=RATE, output="sos") if config.bandpass != "flat" else None
        self.history = [np.zeros((4, 2)) for _ in range(2)]
        self.config = config
        self.transition = None
        self.transition_remaining = 0
        self.noise_target = self.noise_rms

    def configure(self, config):
        # Preserve current delay and filter history; crossfade changed line paths.
        old = self.transition if self.transition_remaining == 480 else copy.deepcopy(self)
        old.transition = None
        old.transition_remaining = 0
        self.transition = old
        self.transition_remaining = 480
        self.noise_target = AMPLITUDE / np.sqrt(2) * 10**(-config.snr_db/20)
        for delays, milliseconds in ((self.remote, config.delay_ms), (self.echo, config.echo_delay_ms)):
            length = round(milliseconds * RATE/1000)
            for delay in delays:
                previous = delay.history
                delay.history = np.zeros(length)
                if length and len(previous):
                    n = min(length, len(previous))
                    delay.history[-n:] = previous[-n:]
        if config.bandpass != self.config.bandpass:
            limits = {"telephone": (300, 3400), "narrow": (900, 2400)}
            self.sos = butter(4, limits[config.bandpass], btype="bandpass", fs=RATE, output="sos") if config.bandpass != "flat" else None
            # Existing filter state has compatible SOS shape for the two presets.
            if self.config.bandpass == "flat":
                self.history = [np.zeros((4, 2)) for _ in range(2)]
        self.echo_gain = 10**(-config.echo_attenuation_db/20)
        self.config = config

    def _signal(self, caller, answerer):
        received = []
        for i, (remote, local) in enumerate(((answerer, caller), (caller, answerer))):
            x = self.remote[i].process(remote) + self.echo_gain * self.echo[i].process(local)
            if self.sos is not None:
                x, self.history[i] = sosfilt(self.sos, x, zi=self.history[i])
            received.append(x)
        return received

    def process(self, caller, answerer):
        received = self._signal(caller, answerer)
        count = len(caller)
        if self.transition is not None:
            previous = self.transition._signal(caller, answerer)
            gain = np.clip((480-self.transition_remaining+np.arange(count)+1)/480, 0, 1)
            noise = self.noise_rms + (self.noise_target-self.noise_rms)*gain
            received = [old*(1-gain)+new*gain for old, new in zip(previous, received)]
            self.transition_remaining -= count
            if self.transition_remaining <= 0:
                self.transition = None
                self.noise_rms = self.noise_target
        else:
            noise = self.noise_rms
        return [x + self.rngs[i].normal(0, 1, count)*noise for i, x in enumerate(received)]
