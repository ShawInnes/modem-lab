"""Actual call setup must precede and gate sample-derived data decoding."""
import numpy as np
import pytest
from modem_lab.engine import SessionConfig, SessionEngine
from modem_lab.dsp import RATE


@pytest.mark.parametrize('profile', ['bell103', 'dqpsk1200', 'qam2400'])
@pytest.mark.parametrize('delay', [0, 1000])
def test_call_setup_then_exact_duplex_exchange(profile, delay):
    engine = SessionEngine(SessionConfig(profile=profile, delay_ms=delay))
    engine.enqueue_text('caller', 'Hello from the caller!\r\n')
    engine.enqueue_text('answerer', 'Pickup, handshake, data.\r\n')
    decoded = {e: bytearray() for e in ('caller', 'answerer')}
    while engine.sample < RATE * 10:
        result = engine.process()
        for e in decoded:
            decoded[e].extend(item['byte'] for item in result['decoded'][e])
        if engine.sample <= RATE * 1.8:
            assert all(not value for value in decoded.values())
            assert not any(engine.ready.values())
        if profile in ('dqpsk1200', 'qam2400') and RATE * 2 < engine.sample < RATE * 3:
            assert engine.rx['caller'].state == 'waiting_for_carrier'
    assert decoded['caller'] == b'Pickup, handshake, data.\r\n'
    assert decoded['answerer'] == b'Hello from the caller!\r\n'
    assert all(engine.setup.ready.values())
    for e in decoded:
        events = [v for v in engine.events if v['endpoint'] == e]
        completion = next(v['sample_index'] for v in events if v['type'] == 'call_stage_changed' and v['detail'].startswith('connected:'))
        started = next(v['sample_index'] for v in events if v['type'] == 'transmit_started')
        assert started >= completion > RATE * 3


@pytest.mark.parametrize('profile', ['bell103', 'dqpsk1200', 'qam2400'])
def test_missing_remote_training_times_out_without_forwarding_text(profile):
    engine = SessionEngine(SessionConfig(profile=profile, snr_db=100, echo_attenuation_db=100))
    engine.enqueue_text('caller', 'must stay queued')
    engine.tx['answerer'].process = lambda count, ready: np.zeros(count)
    decoded = []
    for _ in range(760):
        result = engine.process()
        decoded.extend(result['decoded']['answerer'])
    assert engine.setup.stages['caller'] == 'failed'
    assert not any(engine.ready.values())
    assert decoded == []
    assert engine.pending['caller'] == ['must stay queued']
    assert not any(event['type'] == 'transmit_started' for event in engine.events)


def test_full_call_audio_and_events_ignore_processing_partition():
    def run(block):
        engine = SessionEngine(SessionConfig(profile='dqpsk1200'))
        engine.enqueue_text('caller', 'UU00\x7f\r\n')
        engine.enqueue_text('answerer', 'Reply!')
        outputs = {key: [] for key in ('caller_tx', 'answerer_tx', 'caller_rx', 'answerer_rx')}
        while engine.sample < RATE * 7:
            result = engine.process(min(block, RATE * 7 - engine.sample))
            for key in outputs:
                outputs[key].append(result['streams'][key])
        return engine, {key: np.concatenate(parts) for key, parts in outputs.items()}
    whole, a = run(960)
    split, b = run(137)
    assert whole.events == split.events
    for key in a:
        np.testing.assert_allclose(a[key], b[key], atol=1e-11, rtol=0)


def test_hangup_during_ringing_cancels_payload():
    engine = SessionEngine()
    engine.enqueue_text('caller', 'cancel this')
    engine.process(RATE)
    assert engine.setup.stages['caller'] == 'ringing'
    engine.hang_up()
    assert not engine.active and not engine.pending['caller']
    assert not any(engine.ready.values())
    assert engine.setup.stages['caller'] == 'disconnected'
    assert not any(event['type'] == 'transmit_started' for event in engine.events)
