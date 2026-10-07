"""Telephone prefix followed by independent audio-driven negotiation."""
import numpy as np
from .startup import CallSetup, PICKUP_END


class NegotiatedCallSetup:
    def __init__(self, config):
        from .negotiation import Negotiation
        self.phone = CallSetup(config.profile)
        self.negotiation = Negotiation(
            profile=config.profile, mode=config.call_setup_mode,
            capabilities={e: getattr(config, f"{e}_capabilities") for e in ("caller", "answerer")},
            v8bis={e: getattr(config, f"{e}_v8bis") for e in ("caller", "answerer")},
            bis_initiator=config.bis_initiator,
        )
        self.started = False
        self.stages = self.phone.stages
        self.modes = self.phone.modes
        self.receiver_enabled = self.phone.receiver_enabled
        self.ready = self.phone.ready
        self._received = {e: np.empty(0) for e in ("caller", "answerer")}
        self._received_start = dict.fromkeys(("caller", "answerer"), 0)

    def advance(self, sample, rx_states):
        if sample < PICKUP_END:
            return self.phone.advance(sample, rx_states)
        if not self.started:
            self.started = True
            self.stages = self.negotiation.stages
            self.modes = self.negotiation.modes
            self.receiver_enabled = self.negotiation.receiver_enabled
            self.ready = self.negotiation.ready
        return [(when + PICKUP_END, endpoint, stage, detail)
                for when, endpoint, stage, detail in self.negotiation.advance(sample - PICKUP_END, rx_states)]

    def render(self, endpoint, count, sample):
        if not self.started:
            return self.phone.render(endpoint, count, sample)
        return self.negotiation.render(endpoint, count, sample - PICKUP_END)

    def observe(self, endpoint, samples, sample):
        if self.started:
            # Observations reach the controller in fixed sample windows so
            # external process() chunk sizes cannot move protocol transitions.
            self._received[endpoint] = np.concatenate((self._received[endpoint], samples))
            while len(self._received[endpoint]) >= 960:
                self.negotiation.observe(endpoint, self._received[endpoint][:960], self._received_start[endpoint])
                self._received[endpoint] = self._received[endpoint][960:]
                self._received_start[endpoint] += 960

    def drain_messages(self):
        messages = []
        for message in self.negotiation.drain_messages():
            when = message["sample_index"]
            if message.get("negotiation", {}).get("direction") == "tx":
                # Decisions made while observing RX take effect on the next
                # fixed render boundary. Place TX markers on that boundary.
                when = ((when + 959) // 960) * 960
            messages.append({**message, "sample_index": when + PICKUP_END})
        return messages

    def telemetry(self):
        return self.negotiation.telemetry()
