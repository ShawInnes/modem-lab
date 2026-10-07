from dataclasses import replace
import numpy as np
import pytest
from scipy.signal import sosfreqz

from modem_lab.channel import Delay, PhoneLine
from modem_lab.dsp import AMPLITUDE, BIT, RATE, Receiver, Transmitter, encode
from modem_lab.engine import ENDPOINTS, SessionConfig, SessionEngine


def run_exchange(caller, answerer, *, config=None, block=960):
    engine = SessionEngine(replace(config or SessionConfig(), call_setup=False))
    engine.enqueue_text("caller", caller)
    engine.enqueue_text("answerer", answerer)
    streams = {f"{endpoint}_{kind}": [] for endpoint in ENDPOINTS for kind in ("tx", "rx")}
    decoded = {endpoint: [] for endpoint in ENDPOINTS}
    duration = 9600 + max(len(caller), len(answerer)) * BIT * 10
    while engine.sample < duration:
        result = engine.process(min(block, duration - engine.sample))
        for key, samples in result["streams"].items():
            streams[key].append(samples)
        for endpoint in ENDPOINTS:
            decoded[endpoint].extend(item["byte"] for item in result["decoded"][endpoint])
    return engine, {key: np.concatenate(parts) for key, parts in streams.items()}, decoded


def test_long_varied_ascii_is_decoded_simultaneously():
    caller = ("UUUUUUUU" + "\x00\x7f" * 8 + "".join(chr(i) for i in range(32, 127)) + "\r\n") * 8
    answerer = "@@@@@@@@" + "0123456789" * 3 + caller[::-1]
    engine, _, decoded = run_exchange(caller, answerer)
    assert bytes(decoded["answerer"]).decode("ascii") == caller
    assert bytes(decoded["caller"]).decode("ascii") == answerer
    for endpoint in ENDPOINTS:
        states = [event["detail"] for event in engine.events if event["endpoint"] == endpoint and event["type"] == "state_changed"]
        assert states[:3] == ["waiting_for_carrier", "acquiring_timing", "connected"]


def test_block_boundaries_preserve_samples_decode_and_event_times():
    a, a_samples, a_decoded = run_exchange("Hello\r\nUU00", "Reply\x00\x7f", block=960)
    b, b_samples, b_decoded = run_exchange("Hello\r\nUU00", "Reply\x00\x7f", block=137)
    assert a_decoded == b_decoded
    for key in a_samples:
        np.testing.assert_allclose(a_samples[key], b_samples[key], atol=1e-11, rtol=0)
    order = lambda engine: sorted(engine.events, key=lambda e: (e["sample_index"], e["endpoint"], e["type"]))
    assert order(a) == order(b)


def test_identical_seed_reproduces_samples_and_events():
    a, a_samples, a_decoded = run_exchange("Determinism", "Seeded line", config=SessionConfig(seed=91))
    b, b_samples, b_decoded = run_exchange("Determinism", "Seeded line", config=SessionConfig(seed=91))
    assert a.events == b.events
    assert a_decoded == b_decoded
    for key in a_samples:
        np.testing.assert_array_equal(a_samples[key], b_samples[key])


@pytest.mark.parametrize("endpoint,phase,offset", [("caller", 0.37, 37), ("answerer", 4.91, 119), ("caller", 2.71, 153)])
def test_receiver_decodes_samples_with_unknown_phase_and_alignment(endpoint, phase, offset):
    transmitter = Transmitter(endpoint, phase=phase)
    # Start observing partway through the mark carrier. The receiver is never
    # given oscillator state, frame boundaries, queued text, or TX readiness.
    transmitter.process(offset, False)
    receiver = Receiver("answerer" if endpoint == "caller" else "caller")
    carrier = transmitter.process(7200, False)
    payload = "UU00\x00\x7f ASCII\r\n"
    transmitter.enqueue(payload)
    samples = np.concatenate((carrier, transmitter.process(len(payload) * 1600 + 1600, True)))
    decoded = []
    for start in range(0, len(samples), 223):
        data, _ = receiver.process(samples[start:start + 223])
        decoded.extend(byte for _, byte in data)
    assert bytes(decoded).decode("ascii") == payload


def test_delay_is_causal_across_blocks():
    delay = Delay(7)
    impulse = np.zeros(20)
    impulse[0] = 1
    result = np.concatenate([delay.process(impulse[:3]), delay.process(impulse[3:9]), delay.process(impulse[9:])])
    assert np.flatnonzero(result).tolist() == [7]
    assert result[7] == 1


def test_phone_line_impulse_propagation_and_echo_delays():
    config = SessionConfig(bandpass="flat", delay_ms=3, echo_delay_ms=5, echo_attenuation_db=20, snr_db=100)
    line = PhoneLine(config)
    impulse = np.zeros(400)
    impulse[0] = 1
    caller_rx, answerer_rx = line.process(impulse, np.zeros(400))
    assert np.argmax(np.abs(answerer_rx)) == 144
    assert np.argmax(np.abs(caller_rx)) == 240
    assert answerer_rx[144] == pytest.approx(1, abs=1e-5)
    assert caller_rx[240] == pytest.approx(0.1, abs=1e-5)
    assert np.max(np.abs(answerer_rx[:144])) < 1e-5


@pytest.mark.parametrize("preset,passband", [("telephone", [1070, 1270, 2025, 2225]), ("narrow", [1070, 1270, 2025, 2225])])
def test_bandpass_response_matches_filtered_impulse(preset, passband):
    line = PhoneLine(SessionConfig(bandpass=preset, delay_ms=0, snr_db=100, echo_attenuation_db=100))
    impulse = np.zeros(8192)
    impulse[0] = 1
    _, received = line.process(impulse, np.zeros_like(impulse))
    frequencies = np.fft.rfftfreq(len(impulse), 1 / RATE)
    _, theoretical = sosfreqz(line.sos, worN=frequencies, fs=RATE)
    measured = np.abs(np.fft.rfft(received))
    np.testing.assert_allclose(measured, np.abs(theoretical), atol=0.001, rtol=0)
    for frequency in passband:
        assert measured[np.argmin(abs(frequencies - frequency))] > 0.7
    assert measured[np.argmin(abs(frequencies - 50))] < 0.01
    assert measured[np.argmin(abs(frequencies - 10000))] < 0.02


def test_noise_remains_during_silence_and_directions_are_independent():
    config = SessionConfig(snr_db=12, bandpass="flat")
    line = PhoneLine(config)
    caller, answerer = line.process(np.zeros(RATE), np.zeros(RATE))
    expected = AMPLITUDE / np.sqrt(2) * 10 ** (-12 / 20)
    assert np.std(caller) == pytest.approx(expected, rel=0.03)
    assert np.std(answerer) == pytest.approx(expected, rel=0.03)
    assert abs(np.corrcoef(caller, answerer)[0, 1]) < 0.03


def test_increased_noise_worsens_aggregate_decoding():
    payload = "0123456789UU@@\r\n"
    scores = {}
    for snr in (35, -15):
        correct = 0
        for seed in (7, 18, 29):
            _, _, decoded = run_exchange(payload, payload[::-1], config=SessionConfig(snr_db=snr, seed=seed))
            for endpoint, expected in (("answerer", payload), ("caller", payload[::-1])):
                correct += sum(a == b for a, b in zip(decoded[endpoint], expected.encode("ascii")))
        scores[snr] = correct
    assert scores[35] == 6 * len(payload)
    assert scores[-15] < scores[35] * 0.5


def test_framing_error_discards_bad_stop_bit():
    transmitter = Transmitter("caller", phase=0.81)
    receiver = Receiver("answerer")
    receiver.process(transmitter.process(7200, False))
    bad_frame = encode("A")
    bad_frame[-1] = 0
    transmitter.bits.extend(bad_frame)
    data, events = receiver.process(transmitter.process(2400, True))
    assert data == []
    assert receiver.errors == 1
    assert any(kind == "framing_error" for _, kind, _ in events)


def test_carrier_loss_is_derived_from_silence():
    receiver = Receiver("answerer")
    transmitter = Transmitter("caller")
    receiver.process(transmitter.process(7200, False))
    assert receiver.state == "connected"
    _, events = receiver.process(np.zeros(4000))
    assert receiver.state == "carrier_lost"
    assert any(detail == "carrier_lost" for _, _, detail in events)


@pytest.mark.parametrize("text", ["café", "🙂", b"bytes", None])
def test_unsupported_text_is_rejected(text):
    with pytest.raises(ValueError, match="ASCII"):
        SessionEngine().enqueue_text("caller", text)


@pytest.mark.parametrize("kwargs", [{"snr_db": float("nan")}, {"delay_ms": -1}, {"echo_delay_ms": 1001}, {"seed": -1}, {"bandpass": "unknown"}])
def test_invalid_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        SessionConfig(**kwargs)


def test_preconnection_queue_and_hangup_cancellation():
    engine = SessionEngine()
    engine.enqueue_text("caller", "queued")
    first = engine.process(960)
    assert first["decoded"] == {"caller": [], "answerer": []}
    assert engine.pending["caller"] == ["queued"]
    engine.hang_up()
    assert not engine.pending["caller"]
    assert not engine.tx["caller"].bits
    assert all(receiver.state == "disconnected" for receiver in engine.rx.values())
    assert any("6 pending" in event["detail"] for event in engine.events if event["type"] == "disconnected")
    with pytest.raises(ValueError, match="disconnected"):
        engine.process()
    with pytest.raises(ValueError, match="disconnected"):
        engine.enqueue_text("caller", "new")


def test_command_and_block_bounds():
    engine = SessionEngine()
    with pytest.raises(ValueError):
        engine.enqueue_text("invalid", "hello")
    with pytest.raises(ValueError, match="4096"):
        engine.enqueue_text("caller", "x" * 4097)
    for size in (0, -1, RATE + 1, 0.5):
        with pytest.raises(ValueError, match="Block size"):
            engine.process(size)
