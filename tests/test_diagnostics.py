"""Receiver telemetry must describe actual decisions and stay bounded."""
import json
from dataclasses import replace
import numpy as np
import pytest
from modem_lab.engine import SessionConfig, SessionEngine
from modem_lab.runtime import Runtime


def test_fsk_diagnostics_are_audio_derived_and_bounded():
    engine = SessionEngine(SessionConfig(call_setup=False))
    engine.enqueue_text('caller', 'Understanding symbols! ' * 8)
    for _ in range(400):
        engine.process()
    data = engine.rx['answerer'].diagnostics()
    assert data['mode'] == 'fsk' and data['symbol_samples'] == 160
    assert len(data['trace']) == 320 and len(data['symbols']) == 160
    assert data['timing_locked']
    assert all(0 <= row[0] < engine.sample and -1 <= row[1] <= 1 for row in data['trace'])
    assert all(row[3] == int(row[2] >= row[1]) for row in data['symbols'])
    assert len(json.dumps(data)) < 40000
    silent = SessionEngine().rx['caller']
    silent.process(np.zeros(9600))
    assert not silent.diagnostics()['symbols']
    assert not silent.diagnostics()['timing_locked']


def test_profile_changes_require_restart_in_core():
    engine = SessionEngine()
    with pytest.raises(ValueError, match='profile'):
        engine.configure(replace(engine.config, profile='dqpsk1200'))
    with pytest.raises(ValueError, match='profile'):
        SessionConfig(profile='fake')


def test_runtime_profile_switch_resets_generation_and_pending_queue():
    runtime = Runtime()
    runtime.close()
    runtime.engine.enqueue_text('caller', 'old profile')
    generation = runtime.generation
    runtime.apply(dict(type='select_profile', version=1, command_id='switch', profile='dqpsk1200'))
    assert runtime.generation == generation + 1
    assert runtime.engine.config.profile == 'dqpsk1200'
    assert not runtime.active and not runtime.engine.pending['caller']
    messages = []
    while not runtime.control.empty():
        messages.append(runtime.control.get_nowait())
    assert any(m['type'] == 'ack' and m.get('ok') for m in messages)
    state = next(m for m in reversed(messages) if m['type'] == 'state')
    assert state['actual_profile'] == 'dqpsk1200'
    assert state['diagnostics']['caller']['mode'] == 'dqpsk'
    runtime.apply(dict(type='configure', version=1, command_id='line', config={'snr_db': 25}))
    assert runtime.config.profile == 'dqpsk1200'
