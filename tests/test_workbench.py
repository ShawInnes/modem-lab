"""Workbench contracts: calibrated displays, continuous DSP, and socket ownership."""
from dataclasses import replace
import queue
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from modem_lab import api
from modem_lab.channel import PhoneLine
from modem_lab.dsp import AMPLITUDE, RATE
from modem_lab.engine import SessionConfig, SessionEngine
from modem_lab.runtime import Runtime
from modem_lab.spectrum import BINS, HEADER, HOP, STREAMS, WINDOW, Spectrum

ORIGIN = {"origin": "http://localhost:8000"}


def streams(samples):
    return {name: samples.copy() for name in STREAMS}


def wait_until(predicate, seconds=3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    assert predicate(), "Workbench did not reach the expected state before deadline"


def command(kind, identifier, **values):
    return dict(type=kind, command_id=identifier, version=1, **values)


def ack(socket, identifier):
    for _ in range(100):
        message = socket.receive_json()
        if message["type"] == "ack" and message["command_id"] == identifier:
            return message
    pytest.fail(f"Missing acknowledgement for {identifier}")


def test_spectrum_calibrates_sine_and_dc_to_digital_amplitude():
    sine = 0.5 * np.sin(2 * np.pi * 50 * np.arange(WINDOW) / WINDOW)
    timestamps, spectra = Spectrum().process(streams(sine))
    assert timestamps.tolist() == [WINDOW // 2]
    expected = round((20 * np.log10(0.5) + 90) / 90 * 255)
    assert spectra.shape == (4, 1, BINS)
    assert spectra[:, 0, 50].tolist() == [expected] * 4
    _, dc = Spectrum().process(streams(np.full(WINDOW, 0.5)))
    assert dc[:, 0, 0].tolist() == [expected] * 4
    _, silent = Spectrum().process(streams(np.zeros(WINDOW)))
    assert not silent.any()


def test_spectrum_overlap_and_timestamps_are_independent_of_input_blocks():
    samples = np.random.default_rng(4).normal(size=WINDOW + HOP * 8 + 31)
    expected_times, expected_spectra = Spectrum().process(streams(samples))
    analyzer = Spectrum()
    pieces = [analyzer.process(streams(samples[start:start + 137])) for start in range(0, len(samples), 137)]
    np.testing.assert_array_equal(np.concatenate([p[0] for p in pieces]), expected_times)
    np.testing.assert_array_equal(np.concatenate([p[1] for p in pieces], axis=1), expected_spectra)
    assert expected_times.tolist() == [WINDOW // 2 + HOP * i for i in range(9)]
    assert analyzer.buffer.shape[1] < WINDOW


def test_binary_packet_layout_contains_four_pcm_streams_and_exact_spectra():
    result = SessionEngine().process(4800)
    packet = Spectrum().packet(result, generation=9, sequence=17)
    magic, version, kind, generation, sequence, start, rate, frames, columns, bins = HEADER.unpack_from(packet)
    assert (magic, version, kind, generation, sequence, start, rate, frames, bins) == (b"MLAB", 1, 1, 9, 17, 0, RATE, 4800, BINS)
    assert len(packet) == HEADER.size + 4 * frames * 4 + columns * 8 + 4 * columns * bins
    pcm = np.frombuffer(packet, dtype="<f4", count=4 * frames, offset=HEADER.size).reshape(4, frames)
    for row, name in zip(pcm, STREAMS):
        np.testing.assert_array_equal(row, result["streams"][name].astype("<f4"))
    times = np.frombuffer(packet, dtype="<u8", count=columns, offset=HEADER.size + 16 * frames)
    assert times.tolist() == [WINDOW // 2 + HOP * i for i in range(columns)]


def test_live_noise_change_ramps_without_restarting_random_streams():
    config = SessionConfig(bandpass="flat", snr_db=40, seed=25)
    line = PhoneLine(config)
    reference = PhoneLine(config)
    silence = np.zeros(960)
    line.process(silence, silence)
    reference.process(silence, silence)
    line.configure(replace(config, snr_db=10))
    observed = line.process(silence, silence)
    unmodified = reference.process(silence, silence)
    initial = AMPLITUDE / np.sqrt(2) * 10 ** (-40 / 20)
    target = AMPLITUDE / np.sqrt(2) * 10 ** (-10 / 20)
    ramp = initial + (target - initial) * np.minimum((np.arange(960) + 1) / 480, 1)
    for actual, baseline in zip(observed, unmodified):
        np.testing.assert_allclose(actual, baseline / initial * ramp, atol=1e-16)
    assert line.transition is None
    assert line.noise_rms == pytest.approx(target)


def test_live_configuration_preserves_history_and_block_determinism():
    config = SessionConfig(seed=81)
    changed = replace(config, snr_db=23, delay_ms=37, echo_delay_ms=17, bandpass="narrow")
    engines = [SessionEngine(config), SessionEngine(config)]
    for engine in engines:
        engine.enqueue_text("caller", "Changing the line during a transmission")
        engine.process(9600)
        engine.configure(changed)
    whole = engines[0].process(3840)
    chunks = [engines[1].process(n) for n in [137, 343, 73, 887, 960, 1440]]
    for name in STREAMS:
        np.testing.assert_allclose(whole["streams"][name], np.concatenate([part["streams"][name] for part in chunks]), atol=1e-11, rtol=0)
    assert engines[0].events == engines[1].events
    assert engines[0].sample == engines[1].sample == 13440
    assert engines[0].rx["answerer"].sample == 13440
    assert engines[0].commands[-1]["sample_index"] == 9600
    with pytest.raises(ValueError, match="seed"):
        engines[0].configure(replace(changed, seed=82))


def test_live_controls_require_a_control_boundary():
    engine = SessionEngine()
    engine.process(137)
    with pytest.raises(ValueError, match="boundary"):
        engine.configure(replace(engine.config, snr_db=15))


@pytest.mark.parametrize("origin", [None, "https://evil.example", "http://localhost:9000", "null", "http://localhost:bogus"])
def test_api_rejects_untrusted_and_malformed_origins(origin):
    headers = {} if origin is None else {"origin": origin}
    with TestClient(api.app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("/ws/control", headers=headers):
                pytest.fail("An untrusted origin received control")
        assert error.value.code == 1008


def test_api_enforces_one_controller_and_matching_data_session():
    with TestClient(api.app) as client:
        assert client.get("/api/health").json()["fidelity"] == "functional"
        with client.websocket_connect("/ws/control", headers=ORIGIN) as socket:
            hello = socket.receive_json()
            assert hello["type"] == "hello"
            with pytest.raises(WebSocketDisconnect) as error:
                with client.websocket_connect("/ws/control", headers=ORIGIN):
                    pytest.fail("A second controller was accepted")
            assert error.value.code == 1008
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect("/ws/data/wrong-session", headers=ORIGIN):
                    pytest.fail("A different session received PCM")
            with client.websocket_connect(f"/ws/data/{hello['session_id']}", headers=ORIGIN):
                with pytest.raises(WebSocketDisconnect):
                    with client.websocket_connect(f"/ws/data/{hello['session_id']}", headers=ORIGIN):
                        pytest.fail("A second data consumer was accepted")
        assert api.current is None


def test_api_prestart_queue_decodes_real_samples_and_streams_binary_with_credit():
    with TestClient(api.app) as client:
        with client.websocket_connect("/ws/control", headers=ORIGIN) as socket:
            hello = socket.receive_json()
            socket.send_json(command("send_text", "queued", endpoint="caller", text="Hi"))
            queued = ack(socket, "queued")
            assert queued["ok"] and queued["sample_index"] == 0
            with client.websocket_connect(f"/ws/data/{hello['session_id']}", headers=ORIGIN) as data:
                socket.send_json(command("start", "start"))
                assert ack(socket, "start")["ok"]
                last_sequence = -1
                # Continue crediting while DSP advances beyond carrier acquisition
                # and both ASCII frames; display transport must carry real PCM.
                for _ in range(230):
                    packet = data.receive_bytes()
                    fields = HEADER.unpack_from(packet)
                    generation, sequence, sample, frames, columns = fields[3], fields[4], fields[5], fields[7], fields[8]
                    assert generation == hello["generation"]
                    assert sequence > last_sequence
                    assert sample == sequence * 960
                    assert len(packet) == HEADER.size + 16 * frames + 8 * columns + 4 * columns * BINS
                    last_sequence = sequence
                    data.send_json(dict(type="credit", generation=generation, sequence=sequence))
                decoded = []
                for _ in range(100):
                    message = socket.receive_json()
                    if message["type"] == "event" and message["event_type"] == "decoded_byte" and message["endpoint"] == "answerer":
                        decoded.append(int(message["detail"]))
                        assert message["sample_index"] > 0
                        if len(decoded) == 2:
                            break
                assert bytes(decoded) == b"Hi"
            socket.send_json(command("hang_up", "stop"))
            assert ack(socket, "stop")["ok"]
            socket.send_json(command("send_text", "after-stop", endpoint="caller", text="new"))
            requeued = ack(socket, "after-stop")
            assert requeued["ok"] and requeued["sample_index"] == 0
            assert requeued["generation"] > hello["generation"]
            socket.send_json(command("restart", "restart"))
            restarted = ack(socket, "restart")
            assert restarted["ok"] and restarted["generation"] == requeued["generation"] + 1


def test_runtime_stalled_display_is_bounded_and_does_not_change_dsp():
    runtime = Runtime()
    try:
        runtime.data_connected = True
        runtime.commands.put(command("start", "start"))
        wait_until(lambda: runtime.sequence >= 16)
        runtime.commands.put(command("hang_up", "stop"))
        wait_until(lambda: not runtime.active)
        sample = runtime.engine.sample
        assert runtime.metrics["display_gaps"] > 0
        assert runtime.data.qsize() <= 8
        assert sample >= 16 * 960
        reference = SessionEngine(runtime.config)
        reference.process(sample)
        for endpoint in ("caller", "answerer"):
            # Oscillator phase and seeded channel history prove no samples were
            # skipped or regenerated while the visualization consumer stalled.
            assert runtime.engine.tx[endpoint].phase == reference.tx[endpoint].phase
        for actual, expected in zip(runtime.engine.line.remote, reference.line.remote):
            np.testing.assert_array_equal(actual.history, expected.history)
        for actual, expected in zip(runtime.engine.line.rngs, reference.line.rngs):
            assert actual.bit_generator.state == expected.bit_generator.state
    finally:
        runtime.close()
    assert not runtime.thread.is_alive()


def test_runtime_bounds_logs_and_reports_control_overload():
    runtime = Runtime()
    try:
        for i in range(600):
            runtime.engine._event(0, "line", "test", str(i))
        runtime.engine.commands.extend([{"type": "test"}] * 200)
        runtime.commands.put(command("start", "start"))
        wait_until(lambda: runtime.sequence >= 1)
        assert len(runtime.engine.events) <= 512
        assert len(runtime.engine.commands) <= 128
        while True:
            try:
                runtime.control.get_nowait()
            except queue.Empty:
                break
        for _ in range(runtime.control.maxsize + 1):
            runtime.emit(dict(type="event", detail="stalled"))
        assert runtime.stopped.is_set()
        assert runtime.control.get_nowait()["type"] == "error"
    finally:
        runtime.close()
