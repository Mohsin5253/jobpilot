"""UUIDv7 (RFC 9562): a 48-bit millisecond timestamp first, so new rows land at the right edge of the index instead of
scattering across it like random UUIDv4s. Python 3.13's uuid module has no uuid7, hence this small implementation."""

import os
import time
import uuid

_last = 0
_seq = 0


def uuid7() -> uuid.UUID:
    global _last, _seq
    ms = time.time_ns() // 1_000_000
    if ms <= _last:  # same millisecond (or clock went back): keep order with a counter in rand_a
        _seq = (_seq + 1) & 0xFFF
        ms = _last
    else:
        _seq = int.from_bytes(os.urandom(2), "big") & 0x3FF
        _last = ms
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (ms << 80) | (0x7 << 76) | (_seq << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)
