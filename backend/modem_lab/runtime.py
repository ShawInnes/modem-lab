"""One controlling browser; paced DSP runs outside the API event loop."""
from dataclasses import asdict, replace
import queue
import threading
import time
import uuid
from .engine import SessionConfig, SessionEngine, ENDPOINTS
from .spectrum import Spectrum
from .auto_chat import AutoChat


class Runtime:
    def __init__(self):
        self.session_id = uuid.uuid4().hex
        self.generation = 1
        self.auto_chat = AutoChat(f"{self.session_id}:1")
        self.config = SessionConfig()
        self.engine = SessionEngine(self.config)
        self.active = False
        self.spectrum = Spectrum()
        self.commands = queue.Queue(64)
        self.control = queue.Queue(256)
        self.data = queue.Queue(8)
        self.stopped = threading.Event()
        self.sequence = 0
        self.metrics = dict(processing_ms=0.0, overruns=0, display_gaps=0)
        self.data_connected = False
        self.thread = threading.Thread(target=self.run, name="modem-dsp", daemon=True)
        self.thread.start()

    def emit(self, message):
        message.update(version=1, session_id=self.session_id, generation=self.generation)
        try:
            self.control.put_nowait(message)
        except queue.Full:
            # Never silently lose decoded text. Stop the session and make overload visible.
            self.stopped.set()
            while not self.control.empty():
                self.control.get_nowait()
            self.control.put_nowait(dict(type="error", error="Control consumer stalled; session stopped",
                                         generation=self.generation, version=1))

    def events(self, events):
        for event in events:
            self.emit(dict(type="event", sample_index=event["sample_index"], endpoint=event["endpoint"],
                           event_type=event["type"], detail=event["detail"]))

    def state(self):
        self.emit(dict(type="state", sample_index=self.engine.sample, active=self.active,
                       auto_chat_enabled=self.auto_chat.enabled,
                       auto_chat_status=self.auto_chat.status(self.engine),
                       config=asdict(self.config), actual_seed=self.engine.config.seed,
                       actual_profile=self.engine.config.profile,
                       diagnostics={e: self.engine.rx[e].diagnostics() for e in ENDPOINTS},
                       endpoints={e: dict(state=(self.engine.setup.stages[e] if self.engine.setup and self.active and not self.engine.setup.ready[e]
                                                 else self.engine.rx[e].state) if self.active or self.engine.sample or not self.engine.active else "idle",
                                          call_stage=self.engine.setup.stages[e] if self.engine.setup else "direct_carrier",
                                          transmit_ready=self.engine.ready[e],
                                          carrier_lock=self.engine.rx[e].state == "connected",
                                          confidence=self.engine.rx[e].confidence,
                                          framing_errors=self.engine.rx[e].errors,
                                          queued=sum(map(len, self.engine.pending[e])) + (len(self.engine.tx[e].bits)+9)//10)
                                  for e in ENDPOINTS}, metrics=self.metrics.copy()))

    def reset(self):
        self.generation += 1
        self.auto_chat.reset(f"{self.session_id}:{self.generation}")
        self.engine = SessionEngine(self.config)
        self.spectrum = Spectrum()
        self.sequence = 0
        while not self.data.empty():
            self.data.get_nowait()
        self.events(self.engine.events)

    def apply(self, command):
        identifier = command.get("command_id")
        try:
            if command.get("version") != 1 or not isinstance(identifier, str) or len(identifier) > 100:
                raise ValueError("Invalid command version or command_id")
            kind = command.get("type")
            before = len(self.engine.events)
            if kind in ("start", "restart"):
                if kind == "restart" or not self.engine.active:
                    self.reset()
                    before = len(self.engine.events)
                self.active = True
            elif kind == "select_profile":
                config = replace(self.config, profile=command.get("profile"))
                if config.profile != self.engine.config.profile:
                    self.config = config
                    self.reset()
                    before = len(self.engine.events)
            elif kind == "auto_chat":
                self.auto_chat.set_enabled(command.get("enabled"), self.engine.sample)
            elif kind == "hang_up":
                self.auto_chat.set_enabled(False, self.engine.sample)
                if self.engine.active:
                    self.engine.hang_up()
                self.active = False
                while not self.data.empty():
                    self.data.get_nowait()
            elif kind == "send_text":
                if not self.engine.active:
                    self.reset()
                    before = len(self.engine.events)
                self.engine.enqueue_text(command.get("endpoint"), command.get("text"))
            elif kind == "configure":
                values = command.get("config")
                if not isinstance(values, dict):
                    raise ValueError("Configuration must be an object")
                config = SessionConfig(**{**asdict(self.config), **values})
                if not self.engine.active:
                    self.config = config
                elif self.engine.sample == 0:
                    pending = self.engine.pending
                    self.config = config
                    self.engine = SessionEngine(config)
                    self.engine.pending = pending
                    before = len(self.engine.events)
                else:
                    self.engine.configure(replace(config, seed=self.engine.config.seed, profile=self.engine.config.profile, call_setup=self.engine.config.call_setup))
                    self.config = config
            else:
                raise ValueError("Unknown command type")
            self.events(self.engine.events[before:])
            self.emit(dict(type="ack", command_id=identifier, ok=True, sample_index=self.engine.sample))
            self.state()
        except (ValueError, TypeError, OverflowError) as exc:
            self.emit(dict(type="ack", command_id=identifier, ok=False, sample_index=self.engine.sample, error=str(exc)))

    def run(self):
        deadline = time.monotonic()
        self.state()
        while not self.stopped.is_set():
            for _ in range(64):
                try:
                    self.apply(self.commands.get_nowait())
                except queue.Empty:
                    break
            if self.active:
                started = time.monotonic()
                before = len(self.engine.events)
                self.auto_chat.tick(self.engine)
                result = self.engine.process(960)
                self.auto_chat.observe(result)
                packet = self.spectrum.packet(result, self.generation, self.sequence)
                self.sequence += 1
                self.events(self.engine.events[before:])
                if self.data_connected:
                    if self.data.full():
                        self.data.get_nowait()
                        self.metrics["display_gaps"] += 1
                    self.data.put_nowait(packet)
                self.metrics["processing_ms"] = (time.monotonic()-started)*1000
                if self.sequence % 5 == 0:
                    self.state()
                # Live presentation retains only bounded logs. Offline engine remains unchanged.
                del self.engine.events[:-512]
                del self.engine.commands[:-128]
                deadline += 0.02
                if time.monotonic() > deadline:
                    self.metrics["overruns"] += 1
                    deadline = time.monotonic()
            else:
                deadline = time.monotonic()+0.02
            self.stopped.wait(max(0, deadline-time.monotonic()))

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=2)
