"""The educational handshake must require audio evidence, not a timer alone."""
import numpy as np
import pytest
from modem_lab.dsp import RATE, AMPLITUDE
from modem_lab.startup import CallSetup, DIAL_END, RING_END, PICKUP_END, ANSWER_END, TIMEOUT


def tone(frequency, start, count=960):
    return AMPLITUDE * np.sin(2 * np.pi * frequency * np.arange(start, start + count) / RATE)


def observe_tone(setup, frequency, start, frames=6):
    for sample in range(start, start + frames * 960, 960):
        setup.observe("caller", tone(frequency, sample), sample)


def test_telephone_stages_precede_modem_and_are_sample_clocked():
    setup = CallSetup("bell103")
    assert setup.advance(0, {})[0][2] == "dialing"
    assert setup.modes == {"caller": "dial", "answerer": "silent"}
    assert not any(setup.receiver_enabled.values())
    setup.advance(DIAL_END, {})
    assert setup.stages == {"caller": "ringing", "answerer": "ringing"}
    setup.advance(RING_END, {})
    assert setup.stages["answerer"] == "pickup"
    setup.advance(PICKUP_END, {})
    assert setup.stages["answerer"] == "answer_carrier"
    assert setup.modes["caller"] == "silent"
    assert setup.render("answerer", 960, PICKUP_END) is None


def test_bell_requires_answer_tone_before_caller_carrier():
    setup = CallSetup("bell103")
    setup.advance(RING_END, {})
    setup.advance(PICKUP_END, {})
    for sample in range(PICKUP_END, 5 * RATE, 960):
        setup.observe("caller", np.zeros(960), sample)
        setup.advance(sample, {"caller": "connected", "answerer": "connected"})
    assert setup.modes["caller"] == "silent"
    assert not setup.ready["caller"]
    # A wrong tone cannot start the originating modem either.
    observe_tone(setup, 1270, 5 * RATE)
    setup.advance(5 * RATE + 5760, {})
    assert setup.modes["caller"] == "silent"
    observe_tone(setup, 2225, 6 * RATE)
    setup.advance(6 * RATE + 5760, {})
    assert setup.modes["caller"] == "modem"
    assert setup.stages["caller"] == "training"


def test_dqpsk_answer_tone_cannot_enable_phase_decoder():
    setup = CallSetup("dqpsk1200")
    setup.advance(RING_END, {})
    setup.advance(PICKUP_END, {})
    observe_tone(setup, 2100, PICKUP_END)
    setup.advance(PICKUP_END + 5760, {})
    assert setup.stages["caller"] == "answer_tone_detected"
    assert not setup.receiver_enabled["caller"]
    assert setup.modes["caller"] == "silent"
    setup.advance(ANSWER_END, {})
    setup.advance(ANSWER_END + 4800, {})
    assert setup.modes["answerer"] == "modem"
    assert not setup.receiver_enabled["caller"]
    for sample in range(ANSWER_END, ANSWER_END + 9600, 960):
        setup.observe("caller", np.zeros(960), sample)
        setup.advance(sample, {})
    assert setup.receiver_enabled["caller"]
    assert setup.modes["caller"] == "silent"
    setup.advance(ANSWER_END + 10560, {"caller": "connected"})
    assert setup.modes["caller"] == "modem"
    assert not setup.ready["caller"]


def test_readiness_needs_local_acquisition_through_guard():
    setup = CallSetup("bell103")
    setup.advance(RING_END, {})
    setup.advance(PICKUP_END, {})
    observe_tone(setup, 2225, PICKUP_END)
    start = PICKUP_END + 5760
    setup.advance(start, {"caller": "connected", "answerer": "waiting_for_carrier"})
    setup.advance(start + int(1.4 * RATE), {"caller": "connected"})
    assert not setup.ready["caller"]
    setup.advance(start + int(1.5 * RATE), {"caller": "connected"})
    assert setup.ready["caller"]
    assert not setup.ready["answerer"]
    setup.advance(start + 2 * RATE, {"caller": "carrier_lost"})
    assert not setup.ready["caller"]
    setup.advance(start + 3 * RATE, {"caller": "connected"})
    assert not setup.ready["caller"]


@pytest.mark.parametrize("profile", ["bell103", "dqpsk1200"])
def test_silence_times_out_without_releasing_text(profile):
    setup = CallSetup(profile)
    for sample in range(0, TIMEOUT + 960, 960):
        setup.advance(sample, {})
        setup.observe("caller", np.zeros(960), sample)
    assert setup.stages == dict.fromkeys(("caller", "answerer"), "failed")
    assert setup.modes == dict.fromkeys(("caller", "answerer"), "silent")
    assert not any(setup.ready.values())
    assert not any(setup.receiver_enabled.values())


def test_tone_detector_is_independent_of_input_partition():
    count = RATE // 5
    signal = tone(2225, 0, count)
    results = []
    for chunk in (960, 137):
        setup = CallSetup("bell103")
        for sample in range(0, count, chunk):
            setup.observe("caller", signal[sample:sample + chunk], sample)
        results.append((setup._tone_seen, setup._tone_good, setup._tone_tail_start))
    assert results[0] == results[1]
    assert results[0][0]


def test_call_audio_render_has_identical_partitions():
    setup = CallSetup("bell103")
    for mode, start in (("dial", 0), ("ringback", DIAL_END), ("pickup", RING_END), ("answer_tone", PICKUP_END), ("silent", 0)):
        setup.modes["caller"] = mode
        full = setup.render("caller", 1920, start)
        chunks = [setup.render("caller", min(137, 1920 - offset), start + offset)
                  for offset in range(0, 1920, 137)]
        np.testing.assert_array_equal(full, np.concatenate(chunks))
        assert np.isfinite(full).all()


def test_completed_handshake_does_not_time_out_after_later_carrier_loss():
    setup = CallSetup("bell103")
    setup.advance(RING_END, {})
    setup.advance(PICKUP_END, {})
    observe_tone(setup, 2225, PICKUP_END)
    start = PICKUP_END + 5760
    connected = dict.fromkeys(("caller", "answerer"), "connected")
    setup.advance(start, connected)
    setup.advance(start + int(1.5 * RATE), connected)
    assert all(setup.ready.values())
    setup.advance(TIMEOUT + RATE, dict.fromkeys(connected, "carrier_lost"))
    assert not setup._failed
    assert not any(setup.ready.values())
    assert setup.stages == dict.fromkeys(connected, "training")
