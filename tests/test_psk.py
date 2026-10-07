"""Audio-only checks for experimental 1200 bit/s differential QPSK."""
import numpy as np
import pytest
from modem_lab.channel import PhoneLine
from modem_lab.dsp import RATE, encode
from modem_lab.engine import SessionConfig
from modem_lab.psk import Receiver, Transmitter


def exchange(payload, reply, block=960, snr=40, seed=103):
    tx = [Transmitter("caller", phase=.41), Transmitter("answerer", phase=4.7)]
    rx = [Receiver("caller"), Receiver("answerer")]
    tx[0].enqueue(payload)
    tx[1].enqueue(reply)
    line = PhoneLine(SessionConfig(snr_db=snr, seed=seed))
    total = 14400 + max(len(payload), len(reply)) * 400
    decoded = [[], []]
    events = [[], []]
    streams = [[], [], [], []]
    start = 0
    while start < total:
        # Readiness changes at a fixed sample, independent of processing blocks.
        n = min(block, total-start, 9600-start if start < 9600 else total-start)
        signals = [t.process(n, start >= 9600) for t in tx]
        received = line.process(*signals)
        for k, signal in enumerate(signals + received):
            streams[k].append(signal)
        for k, receiver in enumerate(rx):
            data, ev = receiver.process(received[k])
            decoded[k].extend(data)
            events[k].extend(ev)
        start += n
    return rx, decoded, events, [np.concatenate(s) for s in streams]


def test_long_ascii_simultaneous_exchange_through_default_phone_line():
    text = ("\x00\x7fUU00" + "".join(chr(i) for i in range(128))) * 3
    rx, decoded, _, _ = exchange(text, text[::-1])
    assert bytes(b for _, b in decoded[0]) == text[::-1].encode("ascii")
    assert bytes(b for _, b in decoded[1]) == text.encode("ascii")
    assert all(r.errors == 0 and r.state == "connected" for r in rx)


def test_arbitrary_partition_preserves_decode_samples_and_event_times():
    a = exchange("Hello 1200\r\n\x00\x7f", "Differential phase!", block=960)
    b = exchange("Hello 1200\r\n\x00\x7f", "Differential phase!", block=137)
    assert a[1] == b[1]
    assert a[2] == b[2]
    for x, y in zip(a[3], b[3]):
        np.testing.assert_allclose(x, y, atol=1e-11, rtol=0)


@pytest.mark.parametrize("endpoint,phase,offset", [("caller", .37, 37), ("answerer", 4.91, 79), ("caller", 2.71, 13)])
def test_receiver_finds_unknown_phase_and_symbol_alignment_from_audio(endpoint, phase, offset):
    tx = Transmitter(endpoint, phase=phase)
    tx.process(offset, False)
    rx = Receiver("answerer" if endpoint == "caller" else "caller")
    line = PhoneLine(SessionConfig(echo_attenuation_db=100))
    payload = "UU00\x00\x7f All symbols\r\n"
    tx.enqueue(payload)
    decoded = []
    position = 0
    total = 14400 + len(payload) * 400
    while position < total:
        n = min(223, total - position, 9600 - position if position < 9600 else total-position)
        x = tx.process(n, position >= 9600)
        received = line.process(x, np.zeros(n))[1] if endpoint == "caller" else line.process(np.zeros(n), x)[0]
        data, _ = rx.process(received)
        decoded.extend(b for _, b in data)
        position += n
    assert bytes(decoded).decode("ascii") == payload


def test_noise_degrades_audio_decoding():
    text = "0123456789UU@@\r\n"
    scores = {}
    for snr in (35, -15):
        score = 0
        for seed in (7, 18, 29):
            _, decoded, _, _ = exchange(text, text[::-1], snr=snr, seed=seed)
            for received, expected in zip(decoded, (text[::-1], text)):
                score += sum(b == e for (_, b), e in zip(received, expected.encode("ascii")))
        scores[snr] = score
    assert scores[35] == 6 * len(text)
    assert scores[-15] < scores[35] / 2


def test_diagnostics_bounded_real_decisions_and_carrier_loss():
    rx, _, _, _ = exchange("".join(chr(i) for i in range(128)), "test")
    diag = rx[1].diagnostics()
    assert diag["mode"] == "dqpsk"
    assert diag["symbol_samples"] == 80
    assert diag["carrier_hz"] == 1200
    assert diag["timing_locked"]
    assert len(diag["trace"]) == 320
    assert len(diag["symbols"]) == 160
    points = np.asarray(diag["symbols"])
    assert np.all(np.diff(points[:, 0]) >= 80)
    assert np.all(np.diff(points[:, 0]) % 80 == 0)
    np.testing.assert_allclose(np.hypot(points[:, 1], points[:, 2]), 1, atol=1e-12)
    assert set(points[:, 3]).issubset({0, 1, 2, 3})
    assert np.all((points[:, 4] >= 0) & (points[:, 4] <= 1))
    _, events = rx[1].process(np.zeros(6000))
    assert rx[1].state == "carrier_lost"
    assert any(detail == "carrier_lost" for _, _, detail in events)


def test_bad_stop_bit_is_discarded():
    tx, rx = Transmitter("caller"), Receiver("answerer")
    rx.process(tx.process(7200, False))
    bits = encode("A")
    bits[-1] = 0
    tx.bits.extend(bits)
    decoded, events = rx.process(tx.process(2400, True))
    assert decoded == []
    assert rx.errors == 1
    assert any(kind == "framing_error" for _, kind, _ in events)


def test_silent_audio_does_not_manufacture_symbols_or_bytes():
    rx = Receiver("caller")
    decoded, events = rx.process(np.zeros(RATE))
    assert decoded == []
    assert events == []
    assert rx.diagnostics()["symbols"] == []
    assert not rx.diagnostics()["timing_locked"]


def test_idle_telemetry_keeps_recent_data_visible_without_skipping_decoding():
    tx, rx = Transmitter("caller"), Receiver("answerer")
    rx.process(tx.process(7200, False))
    tx.enqueue("Symbols!")
    decoded, _ = rx.process(tx.process(4800, True))
    assert bytes(byte for _, byte in decoded) == b"Symbols!"
    rx.process(tx.process(48000 * 2, False))
    assert any(point[3] != 2 for point in rx.diagnostics()["symbols"])
    assert rx.diagnostics()["symbols"][-1][0] > rx.sample - 4800
