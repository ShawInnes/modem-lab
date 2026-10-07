"""Bounded, sample-clock conversation driver; replies require actual received bytes."""
import random
import string
from .dsp import RATE


class AutoChat:
    def __init__(self, seed):
        self.enabled = False
        self.reset(seed)

    def reset(self, seed):
        self.rng = random.Random(seed)
        self.sequence = 0
        self.sender = 'caller'
        self.next_sample = 0
        self.waiting_for = None
        self.expected = b''
        self.received = bytearray()
        self.deadline = 0
        self.retry = False

    def set_enabled(self, enabled, sample):
        if not isinstance(enabled, bool):
            raise ValueError('Auto chat enabled must be boolean')
        self.enabled = enabled
        self.waiting_for = None
        self.received.clear()
        self.expected = b''
        self.next_sample = sample
        self.retry = False

    def status(self, engine):
        if not self.enabled:
            return 'Off'
        if not engine.active:
            return 'Waiting for a call'
        if not all(engine.ready.values()) or any(rx.state != 'connected' for rx in engine.rx.values()):
            return 'Waiting for handshake / carrier'
        if self.waiting_for:
            return f'Waiting for {self.waiting_for} to decode'
        return f'{self.sender.title()} next · about 1 message/s'

    def tick(self, engine):
        if not self.enabled or not engine.active:
            return
        if self.waiting_for:
            if engine.sample < self.deadline:
                return
            # A damaged packet causes a fresh attempt from the same sender,
            # rather than pretending the other device received it.
            self.waiting_for = None
            self.received.clear()
            self.retry = True
        if engine.sample < self.next_sample or not all(engine.ready.values()):
            return
        if any(rx.state != 'connected' for rx in engine.rx.values()):
            return
        # Manual traffic wins; no automated backlog builds during slow lines.
        if any(engine.pending[e] or engine.tx[e].bits for e in engine.pending):
            return
        seconds = engine.sample // RATE
        stamp = f'{seconds // 60:02d}:{seconds % 60:02d}'
        token = ''.join(self.rng.choice(string.ascii_letters + string.digits + '!?+=') for _ in range(4))
        word = 'try' if self.retry else ('hi' if self.sender == 'caller' else 'ok')
        text = f'{stamp} #{self.sequence % 256:02X} {"A" if self.sender == "caller" else "B"} {word} {token}\r\n'
        engine.enqueue_text(self.sender, text)
        self.expected = text.encode('ascii')
        self.waiting_for = 'answerer' if self.sender == 'caller' else 'caller'
        self.received.clear()
        self.sequence += 1
        self.next_sample = engine.sample + RATE
        self.deadline = engine.sample + 3 * RATE
        self.retry = False

    def observe(self, result):
        if not self.enabled or not self.waiting_for:
            return
        for item in result['decoded'][self.waiting_for]:
            self.received.append(item['byte'])
            del self.received[:-128]
            if self.received.endswith(self.expected):
                self.sender = self.waiting_for
                self.waiting_for = None
                self.received.clear()
                break
