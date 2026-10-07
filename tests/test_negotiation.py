"""Independent vectors and audio failure boundaries for negotiation DSP."""
import binascii
import numpy as np
import pytest
from modem_lab.negotiation import (
    RATE, BIT, ENDPOINTS, V21, CI_SYNC, MENU_SYNC, FLAG, Negotiation,
    V21Transmitter, V21Receiver, V8Parser, HDLCParser, AnswerToneDetector,
    RequestDetector, fcs, menu_bytes, menu_bits, parse_menu, serial_bits,
    bis_bytes, bis_bits, parse_bis,
)


def feed(parser, bits):
    return [packet for bit in bits for packet in parser.feed(bit)]


def independent_fcs(data):
    # Independent nonreflected CCITT implementation in Python's standard
    # library, with bit reversal to obtain ISO3309's wire convention.
    reverse = lambda byte: int(f"{byte:08b}"[::-1], 2)
    checksum = binascii.crc_hqx(bytes(map(reverse, data)), 0xFFFF) ^ 0xFFFF
    return bytes((reverse(checksum >> 8), reverse(checksum & 255)))


def test_standard_v8_vectors_and_family_semantics():
    # V.8 (11/2000) Tables1,3,4: data call function b5=0,b6=1,b7=1;
    # category5; first extension b4=1 and V22/V22bis bitb1=1.
    assert V21 == {"caller": (1180, 980), "answerer": (1850, 1650)}
    assert CI_SYNC == tuple(map(int, "0000000001"))
    assert MENU_SYNC == tuple(map(int, "0000001111"))
    assert menu_bytes(("v22",)) == bytes.fromhex("c1 05 12")
    assert menu_bits(bytes.fromhex("c1 05 12")) == list(map(int,
        "1111111111" "0000001111" "0100000111" "0101000001" "0010010001"))
    fields = parse_menu(bytes.fromhex("c1 05 12"))
    assert fields["families"] == ["v22"] and not fields["rate_negotiated"]
    assert parse_menu(bytes.fromhex("c1 05 10"))["families"] == []


def test_v8_repetition_parser_uses_actual_received_boundaries():
    stream = list(map(int, "11111111110000001111010000011101010000010010010001"))
    decoded = feed(V8Parser(), stream * 3)
    assert len(decoded) == 2
    assert all(packet[1] == bytes.fromhex("c1 05 12") for packet in decoded)
    assert feed(V8Parser(), stream[:-1]) == []
    corrupted = stream.copy()
    corrupted[29] = 0  # Bad stop bit in the function octet.
    assert any(kind == "invalid" for kind, _, _ in feed(V8Parser(), corrupted + stream))


@pytest.mark.parametrize("data", [bytes.fromhex("01 11"), bytes.fromhex("c1 05 1a"), bytes.fromhex("c1 12"), bytes.fromhex("c1 05 12 05")])
def test_malformed_v8_menu_rejected(data):
    with pytest.raises(ValueError):
        parse_menu(data)


def test_standard_hdlc_crc_and_v8bis_parameter_vectors():
    assert fcs(b"123456789") == bytes.fromhex("6e 90")  # CRC-16/X25 check.
    for data in (b"123456789", bytes.fromhex("14"), bytes.fromhex("12 81 80 80 81 01 00 c6")):
        assert fcs(data) == independent_fcs(data)
    # V8bisTables3/4,5-1/5-2,6-1/6-2/6-3a/b/c; finaldelimiters7/8.
    assert bis_bytes("CL") == bytes.fromhex("12 81 80 80 81 01 00 c6")
    assert bis_bytes("MS", profile="qam2400") == bytes.fromhex("11 89 80 80 81 01 00 c2")
    assert bis_bytes("MS", profile="dqpsk1200") == bytes.fromhex("11 89 80 80 81 01 00 c4")
    assert bis_bytes("ACK(1)") == bytes.fromhex("14")
    assert parse_bis(bytes.fromhex("12 81 80 80 81 01 00 c6"))["profiles"] == ["qam2400", "dqpsk1200"]
    assert parse_bis(bytes.fromhex("11 89 80 80 81 01 00 c2"))["full_v8"]


def test_hdlc_stuffing_fcs_corruption_and_bounded_parser():
    data = bis_bytes("CL")
    parsed = feed(HDLCParser(), bis_bits(data))
    assert parsed[0][1] == data and parsed[0][2]["frame_check"] == "valid"
    damaged = bis_bits(data)
    damaged[50] ^= 1
    assert feed(HDLCParser(), damaged)[0][0] == "invalid"
    invalid_stuff = list(FLAG) * 2 + [1]*7 + [0] * 20 + list(FLAG)
    assert feed(HDLCParser(), invalid_stuff)[0][0] == "invalid"
    parser = HDLCParser()
    assert any(kind == "invalid" for kind, _, _ in feed(parser, list(FLAG) * 2 + [0]*1300))
    assert parser.payload is None


@pytest.mark.parametrize("role", ["caller", "answerer"])
@pytest.mark.parametrize("delay", [0, 1.37, 17.23])
def test_v21_audio_independent_phase_fractional_delay_and_partitions(role, delay):
    tx = V21Transmitter(role, phase=1.793)
    tx.set_pattern(menu_bits(bytes.fromhex("c1 05 12")), repeat=True)
    raw = tx.process(RATE)
    shifted = np.interp(np.arange(len(raw))-delay, np.arange(len(raw)), raw, left=0)
    decoded = []
    for block in (960, 137):
        rx, parser = V21Receiver(role), V8Parser()
        packets = []
        for start in range(0, len(raw), block):
            for _, bit in rx.process(shifted[start:start+block], start):
                packets.extend(parser.feed(bit))
        decoded.append(packets)
        assert len(packets) >= 3
        assert all(data == bytes.fromhex("c1 05 12") for kind, data, _ in packets if kind == "MENU")
    assert decoded[0] == decoded[1]


@pytest.mark.parametrize("frequency,depth,expected", [(2100, .2, True), (2100, 0, False), (2000, .2, False), (2025, .2, False), (2120, .2, False), (2175, .2, False), (2100, .03, False)])
def test_ansam_detector_rejects_plain_and_nearby_answer_tones(frequency, depth, expected):
    times = np.arange(RATE)/RATE
    signal = .32*(1+depth*np.sin(2*np.pi*15*times))*np.sin(2*np.pi*frequency*times+1.23)
    detector = AnswerToneDetector()
    for start in range(0, RATE, 137):
        detector.process(signal[start:start+137], start)
    assert detector.detected == expected


def test_ansam_phase_reversals_and_noise_not_false_positive():
    times = np.arange(RATE)/RATE
    reverse = 1 - 2*((np.arange(RATE)//21600)%2)
    signal = .32*(1+.2*np.sin(2*np.pi*15*times))*np.sin(2*np.pi*2100*times)*reverse
    detector = AnswerToneDetector()
    noise = AnswerToneDetector()
    rng = np.random.default_rng(973)
    for start in range(0, RATE, 960):
        detector.process(signal[start:start+960], start)
        noise.process(rng.normal(0,.15,960), start)
    assert detector.detected and not noise.detected


def test_crd_requires_both_ordered_segments():
    n = Negotiation("qam2400", "v8bis")
    n.advance(0, {})
    n.advance(RATE//5, {})
    tone = n.render("caller", RATE//2, RATE//5)
    detector = RequestDetector()
    for start in range(0, len(tone), 137):
        detector.process(tone[start:start+137], start)
    assert detector.detected
    for bad in (tone[:19200], tone[19200:], tone[::-1]):
        detector = RequestDetector()
        detector.process(bad, 0)
        assert not detector.detected


def test_no_received_audio_never_selects_or_releases_payload():
    n = Negotiation("qam2400")
    for sample in range(0, 31*RATE, 960):
        n.advance(sample, dict.fromkeys(ENDPOINTS, "connected"))
        for e in ENDPOINTS:
            n.render(e, 960, sample)
            n.observe(e, np.zeros(960), sample)
    assert not any(n.ready.values()) and not any(n.selected.values())
    assert set(n.stages.values()) == {"failed"}


def test_local_transmit_echo_cannot_negotiate_with_a_missing_peer():
    n = Negotiation("qam2400")
    for sample in range(0, 31*RATE, 960):
        n.advance(sample, dict.fromkeys(ENDPOINTS, "waiting_for_carrier"))
        for e in ENDPOINTS:
            own_audio = n.render(e, 960, sample)
            n.observe(e, own_audio, sample)
    assert not any(n.selected.values())
    assert not any(n.ready.values())
    assert not any(message["negotiation"]["signal"] in ("CM", "JM", "CJ")
                   and message["negotiation"]["direction"] == "rx" for message in n.messages)


def test_missing_actual_cj_never_completes_answerer_negotiation():
    n = Negotiation("qam2400")
    for sample in range(0, 31*RATE, 960):
        n.advance(sample, dict.fromkeys(ENDPOINTS, "waiting_for_carrier"))
        audio = {e: n.render(e, 960, sample) for e in ENDPOINTS}
        if n.phase["caller"] in ("cj", "transition", "training"):
            audio["caller"] = np.zeros(960)
        for e in ENDPOINTS:
            remote = audio["answerer" if e == "caller" else "caller"]
            n.observe(e, np.zeros(960) if remote is None else remote, sample)
    assert n.selected["answerer"] is None
    assert n.stages["answerer"] == "failed"
    assert not any(n.ready.values())


def test_crd_segments_with_long_gap_are_not_a_request():
    times = np.arange(19200)/RATE
    dual = .16*(np.sin(2*np.pi*1375*times)+np.sin(2*np.pi*2002*times))
    times = np.arange(4800)/RATE
    single = .32*np.sin(2*np.pi*1900*times)
    signal = np.concatenate((dual, np.zeros(4800), single))
    detector = RequestDetector()
    detector.process(signal, 0)
    assert not detector.detected
