"""Auto chat uses sample time and real decoded bytes, with a bounded backlog."""
import pytest
from modem_lab.auto_chat import AutoChat
from modem_lab.dsp import RATE
from modem_lab.engine import SessionConfig, SessionEngine
from modem_lab.runtime import Runtime


@pytest.mark.parametrize('profile', ['bell103', 'dqpsk1200', 'qam2400'])
def test_actual_auto_conversation_varies_and_waits_for_handshake(profile):
    engine = SessionEngine(SessionConfig(profile=profile))
    chat = AutoChat('test conversation')
    chat.set_enabled(True, 0)
    received = {e: bytearray() for e in engine.rx}
    while chat.sequence < 8 and engine.sample < 20 * RATE:
        chat.tick(engine)
        result = engine.process()
        chat.observe(result)
        for e in received:
            received[e].extend(item['byte'] for item in result['decoded'][e])
        if engine.sample < 3 * RATE:
            assert chat.sequence == 0
    assert chat.sequence == 8
    chat.set_enabled(False, engine.sample)
    for _ in range(150):
        chat.tick(engine)
        result = engine.process()
        for e in received:
            received[e].extend(item['byte'] for item in result['decoded'][e])
    sends = [command for command in engine.commands if command['type'] == 'send_text']
    assert [v['endpoint'] for v in sends] == ['caller', 'answerer'] * 4
    assert all(b['sample_index'] - a['sample_index'] >= RATE for a, b in zip(sends, sends[1:]))
    assert len(set(v['text'] for v in sends)) == 8
    assert len(set(v['text'].split()[-1] for v in sends)) == 8
    assert all(len(v['text']) < 30 and v['text'].isascii() for v in sends)
    for e, other in [('caller', 'answerer'), ('answerer', 'caller')]:
        expected = ''.join(v['text'] for v in sends if v['endpoint'] == other).encode('ascii')
        assert received[e] == expected
    assert chat.sequence == 8


def test_no_received_bytes_retry_same_sender_without_backlog():
    engine = SessionEngine(SessionConfig(call_setup=False))
    engine.process(9600)
    chat = AutoChat('retry')
    chat.set_enabled(True, engine.sample)
    for _ in range(500):
        chat.tick(engine)
        # Deliberately do not deliver actual receiver results to the chat driver.
        engine.process()
        assert sum(len(v) for v in engine.pending['caller']) + len(engine.tx['caller'].bits) / 10 < 30
        assert len(chat.received) <= 128
    sends = [c for c in engine.commands if c['type'] == 'send_text']
    assert 3 <= len(sends) <= 4
    assert all(c['endpoint'] == 'caller' for c in sends)
    assert all(' try ' in c['text'] for c in sends[1:])


def test_manual_queue_and_carrier_loss_hold_auto_messages():
    engine = SessionEngine(SessionConfig(call_setup=False))
    engine.process(9600)
    chat = AutoChat('manual')
    chat.set_enabled(True, engine.sample)
    engine.enqueue_text('caller', 'manual text')
    chat.tick(engine)
    assert chat.sequence == 0
    engine.pending['caller'].clear()
    engine.rx['answerer'].state = 'carrier_lost'
    chat.tick(engine)
    assert chat.sequence == 0
    engine.rx['answerer'].state = 'connected'
    chat.tick(engine)
    assert chat.sequence == 1
    assert 'decode' in chat.status(engine)
    chat.observe({'decoded': {'caller': [], 'answerer': [{'byte': 0} for _ in range(1000)]}})
    assert len(chat.received) == 128
    assert chat.waiting_for == 'answerer'


def test_runtime_auto_toggle_restart_profile_and_hangup():
    runtime = Runtime()
    runtime.close()
    def apply(kind, **kwargs):
        runtime.apply(dict(type=kind, command_id=kind, version=1, **kwargs))
    apply('auto_chat', enabled=True)
    assert runtime.auto_chat.enabled
    apply('restart')
    assert runtime.auto_chat.enabled and runtime.auto_chat.sequence == 0
    apply('select_profile', profile='dqpsk1200')
    assert runtime.auto_chat.enabled and runtime.auto_chat.waiting_for is None
    apply('hang_up')
    assert not runtime.auto_chat.enabled
    apply('auto_chat', enabled='yes')
    assert not runtime.auto_chat.enabled
    messages = []
    while not runtime.control.empty():
        messages.append(runtime.control.get_nowait())
    assert messages[-1]['type'] == 'ack' and not messages[-1]['ok']
