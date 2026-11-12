from flowtype.hotkey.state import Action as A
from flowtype.hotkey.state import PushToTalk, State, Timing


def ptt():
    return PushToTalk(Timing(tap_max_s=0.25, double_gap_s=0.35, max_record_s=10))


def test_hold_records_and_stops_on_release():
    p = ptt()
    assert p.press(0.0) == [A.START]
    assert p.press(0.5) == []  # key auto-repeat
    assert p.release(1.2) == [A.STOP_HOLD]
    assert p.state is State.IDLE


def test_single_short_tap_is_ignored():
    p = ptt()
    p.press(0.0)
    assert p.release(0.1) == []
    assert p.tick(0.3) == []
    assert p.tick(0.5) == [A.CANCEL]
    assert p.state is State.IDLE


def test_double_tap_starts_hands_free_and_next_tap_stops():
    p = ptt()
    assert p.press(0.0) == [A.START]
    p.release(0.1)
    assert p.press(0.3) == []
    assert p.release(0.4) == [A.HANDSFREE_ON]
    assert p.tick(5.0) == []  # keeps recording with the key up
    assert p.press(6.0) == [A.STOP_HANDSFREE]
    assert p.release(6.1) == []
    assert p.state is State.IDLE


def test_escape_cancels_hands_free():
    p = ptt()
    p.press(0.0), p.release(0.1), p.press(0.2), p.release(0.3)
    assert p.other_key(1.0) == []  # typing other keys is fine in hands-free
    assert p.other_key(1.5, is_escape=True) == [A.CANCEL]


def test_used_as_a_modifier_cancels():
    p = ptt()
    p.press(0.0)
    assert p.other_key(0.4) == [A.CANCEL]  # Right Ctrl + C
    assert p.release(0.5) == []
    assert p.state is State.IDLE


def test_late_second_tap_is_a_fresh_press():
    p = ptt()
    p.press(0.0), p.release(0.1)
    assert p.press(0.6) == [A.CANCEL, A.START]


def test_max_duration_stops_recording():
    p = ptt()
    p.press(0.0)
    assert p.tick(10.5) == [A.STOP_HOLD]
    assert p.release(11.0) == []
    assert p.state is State.IDLE


def test_release_without_press_is_ignored():
    assert ptt().release(1.0) == []
