"""Low-level reader for PerkinElmer TotalChrom "PENX" container files.

Every TotalChrom file examined so far (.raw, .rst, .mth, .seq, .idx) uses the
same encoding. Fields are read strictly in order; there is no offset table.

* 32-bit integers: big-endian, signed.
* Text: a 32-bit length, then the bytes, zero-padded to a multiple of 4.
* 64-bit floats: IEEE-754 stored as two big-endian 32-bit words with the LOW
  word first ("word-swapped" doubles).
* Timestamps: three 32-bit words: Unix time (UTC), then a packed local date
  and a packed local time. Only the Unix time is used.

See FORMAT.md for how each rule was verified.
"""
from __future__ import annotations

import struct
from datetime import datetime, timezone

import numpy as np

MAGIC = b"PENX"


class PenxFormatError(ValueError):
    """The bytes do not match the expected TotalChrom layout."""


class PenxReader:
    """Sequential reader over a PENX byte buffer."""

    def __init__(self, buf: bytes, pos: int = 0) -> None:
        self.buf = buf
        self.pos = pos

    def _take(self, n: int) -> int:
        start = self.pos
        if n < 0 or start + n > len(self.buf):
            raise PenxFormatError(
                f"read of {n} bytes at offset {start:#x} runs past the end "
                f"of the data ({len(self.buf)} bytes)")
        self.pos = start + n
        return start

    def i32(self) -> int:
        return struct.unpack_from(">i", self.buf, self._take(4))[0]

    def u32(self) -> int:
        return struct.unpack_from(">I", self.buf, self._take(4))[0]

    def f64(self) -> float:
        lo, hi = struct.unpack_from(">II", self.buf, self._take(8))
        return struct.unpack(">d", struct.pack(">II", hi, lo))[0]

    def text(self, max_len: int = 65536) -> str:
        at = self.pos
        n = self.u32()
        if n > max_len:
            raise PenxFormatError(f"implausible text length {n} at offset {at:#x}")
        start = self._take(n + (-n % 4))
        return self.buf[start:start + n].decode("latin-1")

    def timestamp(self) -> datetime:
        unix = self.u32()
        self._take(8)  # packed local date/time words, redundant with the Unix time
        return datetime.fromtimestamp(unix, tz=timezone.utc)

    def i32_array(self, n: int) -> np.ndarray:
        if n < 0:
            raise PenxFormatError(f"negative array length {n} at offset {self.pos - 4:#x}")
        start = self._take(4 * n)
        arr = np.frombuffer(self.buf, dtype=">i4", count=n, offset=start).astype(np.int32)
        arr.flags.writeable = False
        return arr

    def skip(self, n: int) -> None:
        self._take(n)
