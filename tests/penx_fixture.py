"""Structurally valid synthetic PENX type-1 bytes, not vendor validation data.

Writes the documented field sequence independently of the reader. No private
acquisition bytes/metadata are embedded. Offsets support corruption tests.
"""
import struct

import numpy as np


def penx_bytes(counts=None, *, sample_name="Synthetic FID fixture", rate=12.5,
               delay=0., channel="A", scale=(54.01791, 2.), complete=3,
               version=10019, runtime=None, header_count=None):
    counts = np.asarray(counts if counts is not None else 400000 + np.arange(1200) * 10, dtype=np.int32)
    output = bytearray(b"PENX")
    offsets = {}
    def mark(key):
        offsets[key] = len(output)
    def integer(value=0):
        output.extend(struct.pack(">i", value))
    def real(value=0.):
        hi, lo = struct.unpack(">II", struct.pack(">d", value))
        output.extend(struct.pack(">II", lo, hi))
    def text(value=""):
        value = value.encode("latin-1")
        integer(len(value)); output.extend(value + bytes(-len(value) % 4))
    def timestamp():
        integer(1700000000); integer(); integer()
    integer(1); integer(48); integer(version)
    for _ in range(3): integer()
    text("0" * 32); text("1" * 32)
    for _ in range(2):
        text("synthetic"); text("fixture-host"); timestamp()
    text(); integer(); integer(); text(); integer(complete); integer()
    integer(); timestamp(); integer(); text("fixture operator")
    text("fixture.seq"); integer(); text("fixture autosampler"); integer(); integer(1)
    mark("runtime"); real(len(counts) / 60 / rate if runtime is None else runtime)
    integer(int(counts.max()) if len(counts) else 0); integer(int(counts.min()) if len(counts) else 0)
    text(); real(); real()
    mark("header_count"); integer(len(counts) if header_count is None else header_count)
    integer(); integer(); text(channel)
    for _ in range(3): integer()
    text("Synthetic study"); text(sample_name); text("001")
    text("fixture.raw"); text("fixture.rst"); text(); text()
    for name in ("instrument.mth", "process.mth", "calibration.mth", "report.rpt"): text(name)
    text(); text()
    for _ in range(8): real(1.)
    integer(); text(); integer(); text(); text(); integer()
    text(); text(); text(); integer()
    for _ in range(11): text()
    mark("array_count"); integer(len(counts)); mark("data")
    output.extend(counts.astype(">i4").tobytes())
    for _ in range(2): text("synthetic"); text("fixture-host"); timestamp()
    text(); integer(1); integer(); text("Synthetic instrument method"); integer(131360); integer(1); text()
    mark("delay"); real(delay); real(1.); real(1.); mark("rate"); real(rate)
    integer(); integer(1000)
    for _ in range(4): integer()
    text("Synthetic FID"); text(); text()
    for _ in range(7): integer()
    mark("scale"); real(scale[0]); real(scale[1]); real(54.01791); real(0.)
    output.extend(b"Ignored synthetic footer" + struct.pack(">i", 2000000000) * 32)
    return bytes(output), offsets


def synthetic_penx(path, **kwargs):
    data, _ = penx_bytes(**kwargs)
    path.write_bytes(data)
    return path
