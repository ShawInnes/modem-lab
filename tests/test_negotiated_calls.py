"""Negotiated calls must carry real payload only after audio confirmations."""
from dataclasses import replace
import numpy as np
import pytest
from modem_lab.dsp import RATE
from modem_lab.engine import SessionConfig, SessionEngine


def run_call(config, seconds=22, block=960):
    engine = SessionEngine(config)
    engine.enqueue_text("caller", "Menus then real data!\r\n")
    engine.enqueue_text("answerer", "Confirmed from audio.\r\n")
    received = {e: bytearray() for e in ("caller", "answerer")}
    while engine.sample < RATE * seconds:
        result = engine.process(min(block, RATE * seconds - engine.sample))
        for e in received:
            received[e].extend(item["byte"] for item in result["decoded"][e])
        if all(engine.ready.values()) and all(not engine.pending[e] and not engine.tx[e].bits for e in received):
            # Last symbols must pass the line and character receiver.
            for _ in range(65):
                tail = engine.process()
                for e in received:
                    received[e].extend(item["byte"] for item in tail["decoded"][e])
            break
    return engine, received


@pytest.mark.parametrize("mode", ["v8", "v8bis"])
@pytest.mark.parametrize("profile", ["dqpsk1200", "qam2400"])
def test_negotiated_call_exact_duplex_payload(mode, profile):
    engine, received = run_call(SessionConfig(profile=profile, call_setup_mode=mode))
    assert received["caller"] == b"Confirmed from audio.\r\n"
    assert received["answerer"] == b"Menus then real data!\r\n"
    assert all(engine.ready.values())
    messages = [event for event in engine.events if event.get("negotiation")]
    for endpoint, signal in [("answerer", "CM"), ("caller", "JM"), ("answerer", "CJ")]:
        assert any(e["endpoint"] == endpoint and e["negotiation"]["signal"] == signal
                   and e["negotiation"]["direction"] == "rx" for e in messages)
    if mode == "v8bis":
        for signal in ("CL", "MS", "ACK(1)"):
            assert any(e["negotiation"]["signal"] == signal and e["negotiation"]["direction"] == "rx" for e in messages)
    last_confirmation = max(e["sample_index"] for e in messages if e["negotiation"]["signal"] == "CJ")
    assert min(e["sample_index"] for e in engine.events if e["type"] == "transmit_started") > last_confirmation


@pytest.mark.parametrize("mode", ["v8", "v8bis"])
def test_no_common_capabilities_never_releases_text(mode):
    engine, received = run_call(SessionConfig(profile="qam2400", call_setup_mode=mode,
                                              answerer_capabilities=()), seconds=22)
    assert not any(received.values())
    assert not any(engine.ready.values())
    assert not any(e["type"] == "transmit_started" for e in engine.events)
    assert engine.pending["caller"]
    assert "failed" in engine.setup.stages.values()


def test_answerer_initiated_bis_changes_modem_roles_and_carries_payload():
    engine, received = run_call(SessionConfig(profile="qam2400", call_setup_mode="v8bis", bis_initiator="answerer"))
    assert received["caller"] == b"Confirmed from audio.\r\n"
    assert received["answerer"] == b"Menus then real data!\r\n"
    assert engine._payload_roles == {"caller": "answerer", "answerer": "caller"}
    assert any(event.get("negotiation", {}).get("signal") == "MS" and event["endpoint"] == "answerer"
               and event["negotiation"]["direction"] == "tx" for event in engine.events)


@pytest.mark.parametrize("unsupported", ["caller", "answerer"])
def test_unsupported_bis_peer_falls_back_to_real_v8(unsupported):
    config = replace(SessionConfig(profile="qam2400", call_setup_mode="v8bis"), **{f"{unsupported}_v8bis": False})
    engine, received = run_call(config)
    assert received["caller"] == b"Confirmed from audio.\r\n"
    assert received["answerer"] == b"Menus then real data!\r\n"
    assert not any(event.get("negotiation", {}).get("signal") == "ACK(1)" for event in engine.events)


@pytest.mark.parametrize("mode", ["v8", "v8bis"])
def test_negotiation_with_long_propagation_delay(mode):
    engine, received = run_call(SessionConfig(profile="qam2400", call_setup_mode=mode, delay_ms=1000))
    assert received["caller"] == b"Confirmed from audio.\r\n"
    assert received["answerer"] == b"Menus then real data!\r\n"
    assert all(engine.ready.values())


def test_negotiation_config_is_validated_and_requires_new_call():
    with pytest.raises(ValueError, match="1200 or 2400"):
        SessionConfig(call_setup_mode="v8")
    for bad in ("v34", ["v34"], ["v22", "v22"], None):
        with pytest.raises(ValueError, match="Capabilities"):
            SessionConfig(caller_capabilities=bad)
    engine = SessionEngine(SessionConfig(profile="qam2400"))
    with pytest.raises(ValueError, match="new session"):
        engine.configure(replace(engine.config, call_setup_mode="v8"))


def test_hangup_during_negotiation_stops_payload_and_stages():
    engine = SessionEngine(SessionConfig(profile="qam2400", call_setup_mode="v8bis"))
    engine.enqueue_text("caller", "cancel me")
    for _ in range(3):
        engine.process(RATE)
    engine.hang_up()
    assert all(stage == "disconnected" for stage in engine.setup.stages.values())
    assert not any(engine.ready.values()) and not any(engine.pending.values())


def test_call_waveforms_and_events_are_block_independent():
    def collect(block):
        engine = SessionEngine(SessionConfig(profile="qam2400", call_setup_mode="v8"))
        engine.enqueue_text("caller", "split blocks")
        streams = {key: [] for key in ("caller_tx", "answerer_tx", "caller_rx", "answerer_rx")}
        while engine.sample < RATE * 12:
            result = engine.process(min(block, RATE * 12 - engine.sample))
            for key in streams:
                streams[key].append(result["streams"][key])
        return engine.events, {key: np.concatenate(parts) for key, parts in streams.items()}
    a, first = collect(960)
    b, second = collect(137)
    assert a == b
    for key in first:
        np.testing.assert_allclose(first[key], second[key], atol=1e-10, rtol=0)
