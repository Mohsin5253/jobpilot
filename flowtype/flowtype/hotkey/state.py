"""The push-to-talk state machine, kept free of any keyboard library so it can be tested with plain timestamps.

- Hold the key: recording runs while it's down and stops when it comes up.
- Double-tap: hands-free. Recording runs until the key is tapped again (Esc cancels).
- A single short tap does nothing, and the key used as a modifier (Right Ctrl + C) cancels the recording.

Recording starts the moment the key goes down, before we know whether it's a hold or the first of two taps, so no
speech is lost either way."""

from dataclasses import dataclass
from enum import Enum


class Action(Enum):
    START = "start"  # begin recording
    CANCEL = "cancel"  # throw the recording away
    STOP_HOLD = "stop_hold"  # finish and transcribe (push-to-talk)
    STOP_HANDSFREE = "stop_handsfree"  # finish and transcribe (hands-free)
    HANDSFREE_ON = "handsfree_on"  # tell the user hands-free is on


class State(Enum):
    IDLE = "idle"
    PRESSED = "pressed"  # down, not yet known whether it's a hold or a tap
    TAP_UP = "tap_up"  # one short tap; waiting to see if a second follows
    SECOND_DOWN = "second_down"  # the second tap of a double-tap is down
    HANDSFREE = "handsfree"
    WAIT_RELEASE = "wait_release"  # stopped; ignore the key until it comes up


@dataclass
class Timing:
    tap_max_s: float = 0.25
    double_gap_s: float = 0.35
    max_record_s: float = 120.0


class PushToTalk:
    def __init__(self, timing: Timing | None = None):
        self.t = timing or Timing()
        self.state = State.IDLE
        self.down = False
        self._pressed_at = 0.0
        self._up_at = 0.0
        self._started_at = 0.0

    def press(self, now: float) -> list[Action]:
        if self.down:  # auto-repeat while held
            return []
        self.down = True
        if self.state is State.IDLE:
            self.state, self._pressed_at, self._started_at = State.PRESSED, now, now
            return [Action.START]
        if self.state is State.TAP_UP:
            if now - self._up_at <= self.t.double_gap_s:
                self.state = State.SECOND_DOWN
                return []
            # Too late to be a double-tap: the first tap is dropped and this is a fresh press.
            self.state, self._pressed_at, self._started_at = State.PRESSED, now, now
            return [Action.CANCEL, Action.START]
        if self.state is State.HANDSFREE:
            self.state = State.WAIT_RELEASE
            return [Action.STOP_HANDSFREE]
        return []

    def release(self, now: float) -> list[Action]:
        if not self.down:
            return []
        self.down = False
        if self.state is State.PRESSED:
            if now - self._pressed_at < self.t.tap_max_s:
                self.state, self._up_at = State.TAP_UP, now
                return []
            self.state = State.IDLE
            return [Action.STOP_HOLD]
        if self.state is State.SECOND_DOWN:
            self.state = State.HANDSFREE
            return [Action.HANDSFREE_ON]
        if self.state is State.WAIT_RELEASE:
            self.state = State.IDLE
        return []

    def other_key(self, now: float, is_escape: bool = False) -> list[Action]:
        """Any other key. While the hotkey is held (or between the taps) it's a shortcut, not dictation."""
        if self.state in (State.PRESSED, State.TAP_UP, State.SECOND_DOWN):
            self.state = State.WAIT_RELEASE if self.down else State.IDLE
            return [Action.CANCEL]
        if self.state is State.HANDSFREE and is_escape:
            self.state = State.IDLE
            return [Action.CANCEL]
        return []

    def tick(self, now: float) -> list[Action]:
        if self.state is State.TAP_UP and now - self._up_at > self.t.double_gap_s:
            self.state = State.IDLE  # a lone short tap
            return [Action.CANCEL]
        if self.state in (State.PRESSED, State.HANDSFREE) and now - self._started_at > self.t.max_record_s:
            hold = self.state is State.PRESSED
            self.state = State.WAIT_RELEASE if self.down else State.IDLE
            return [Action.STOP_HOLD if hold else Action.STOP_HANDSFREE]
        return []
