# TotalChrom file format and integration notes

## Reading a type-1 RAW file

**Header.** The first four bytes spell `PENX`. A big-endian integer identifies a type-1 acquisition. The remaining headers include variable-length text, so the signal has no fixed byte offset. Walk the fields in order to obtain the channel, point count and recorded extrema.

**Signal.** A second point count immediately precedes the signed 32-bit big-endian detector readings. Both counts must agree, and the array minimum and maximum must match the header. These checks catch a misaligned read even when the bytes look like a plausible trace.

**Footer.** Immediately after the last reading, the instrument method stores the delay, sampling rate and the channel scale pairs. On the verified channel A runs, dividing raw counts by the product of the two scale values reproduces the signal in µV. At zero delay, sample number one falls at one sampling interval. Later audit and instrument records can remain unread.

[Reader implementation](../../gcviewer/parsers/totalchrom/raw.py) · [Structural tests](../../tests/fid_core/test_penx_reader.py)

## Evidence and field map

Evidence base: TotalChrom Workstation 6.3.2 on a Clarus 500 FID.

- **2026 runs:** 3 raw files with TotalChrom's own ASCII exports (.rax).
- **2025 runs:** 5 raw files, 4 result files (.rst) and 5 printed reports.
- **Methods and sequences:** 2 method files with their ASCII exports (.mtx), and 1 sequence file with its index file.

"Verified" means checked against TotalChrom's own output. "Inferred" means the data are consistent with the interpretation, but nothing has confirmed it independently.

## 1. Container encoding (all file types)

Every file starts with `PENX`, followed by a 32-bit file-type code:

| Code | File type |
|---|---|
| 1 | raw data |
| 2 | result |
| 3 | sequence |
| 19 | method |
| 22 | index |

Fields are read strictly in order; there is no table of offsets.

| Item | Encoding |
|---|---|
| integer | 32-bit big-endian, signed |
| text | 32-bit length, bytes, zero padding to a multiple of 4 |
| real | IEEE-754 double stored as two big-endian 32-bit words, **low word first** |
| timestamp | Unix time (UTC), packed local date, packed local time (3 words); only Unix time is used |

The two 32-hex-digit strings near the start are checksums. They are not plain MD5/SHA digests of the file (probably keyed) and are not verified here.

Timestamps were verified against the times printed on the reports: UTC−4 gives the same local times.

## 2. Raw file (.raw) layout

The reader consumes these records in order:

1. **File header:** type, 48, version (10019), three zeros, and two checksum strings.
2. **Data header:**
   - created by / computer / time, then modified by / computer / time;
   - text, int, int, text;
   - file-complete flag (3);
   - run-log count.
3. **A/D header:**
   - int, injection time, int, user;
   - sequence path, sequence row (0-based);
   - autosampler, int, vial;
   - run time (min), maximum counts, minimum counts, text, two reals;
   - **point count**, then two ints.
4. **Sequence row:**
   - channel, three ints;
   - study, sample name, sample number;
   - raw path, result base path, two texts;
   - **four method paths:** instrument, process, calibration, report format;
   - two texts;
   - eight reals (per-sample values);
   - a mixed tail of ints and texts.
5. **Data:** point count (must equal the header's), followed by that many 32-bit integers.
6. **Footer, as far as read:**
   - **Instrument-method header:** users, computers and times; text; revision; int; method title; 131360; 1; notes.
   - **A/D box:** delay (min), two run-time reals, **sampling rate (Hz)**, int, A/D range (mV), four ints.
   - **Instrument configuration:** instrument name, two texts, seven ints, then the **unit scale pairs** for channels A and B.
   - Later sections (GC link parameters, an empty peak table, spectral data, audit log) are not needed and not read.

Self-checks that raise an error on mismatch:

- the point count equals the array length;
- the stored minimum and maximum equal those of the data.

A check that only warns: run time × rate equals the number of points (within one point).

The header length varies with the text fields (the data start at byte 1008 in the 2026 files and 1020 in the 2025 files). A test re-writes a text field longer and confirms that the data are still found.

**Inferred labels:**

- The fourth method path is the report format. It differs from the other three in the 2025 files.
- "study" and "sample name" are assigned by position; they hold identical values in 2025, so that data can't tell them apart.
- The eight per-sample reals (1, 1, 1, 1, 1, 1, 0, 100) are unlabeled.

## 3. Conventions

**Time.** Point *i* (0-based) is at `delay + (i + 1) / rate`, so the first point is at 0.08 s.
- *Verified:* the start and end times stored for all 11 TotalChrom peaks equal `(index + 1) / 12.5` exactly.
- *Untested:* the delay term. The delay is 0 in every file.

**Units.** µV = counts ÷ (scale × multiplier), using the channel's pair from the instrument configuration: (54.01791, 2.0) for channel A on this instrument.
- *Verified:* all 11 TotalChrom peak areas are reproduced to about 1e-15 relative error.
- *Inferred:* that the second number is a multiplier. Channel B stores (54.01791, 0.0), so channel B can't be used yet.

**Clipping.** The A/D ceiling is 107,374,178 counts = 993.88 mV, which is the "High Point" printed on the reports. Clipped plateaus jitter 2–4 counts below the ceiling (tolerance 16 counts). The report's "Low Point −44.50 mV" is only a 5% plotting margin below the data minimum.

The old `penx_parser.py` started reading at byte 0x400, so it dropped the first 1–4 points depending on the file. It also ran about 1,000 "points" into the footer.

## 4. TotalChrom's integration, in the [FID integrator](../../gcviewer/analysis/totalchrom_fid.py)

**Exact to floating-point precision, given TotalChrom's peak boundaries (11/11 peaks):**
- The baseline is a straight line from the peak's start point to its end point.
- Area = Σ(signal − baseline) × (1/rate) over start..end. Trapezoid and rectangle sums are identical here, because both end points sit on the baseline.
- Retention time = the top of a least-squares parabola through the peak's 5 highest points.
- Height = the parabola's top value minus the baseline at the retention time. The stored "apex counts" is that top value, rounded.
- For clipped peaks, TotalChrom uses the first point at the maximum for both time and height.
- "Raw Amount" = area ÷ 1,000,000, a default response factor. It is not a concentration.

**Peak detection** follows the manual's rules:
- **Start:** a rise between consecutive (bunched) points greater than NT starts a potential peak.
- **Start confirmed:** the running sum of point heights above the start point must exceed AT, while every step keeps rising by more than NT.
- **True start:** the lowest raw point up to 5 bunches before the potential start.
- **Top:** confirmed once the drops after it sum to more than 2/3 of AT.
- **End:** the second of two consecutive steps smaller than NT/2. A new confirmed rise before that is treated as a fused peak and split at the valley.

**Results with the stored settings** (bunching 1, NT 50, AT 100, detection off 0.011–1.931 min):

- **Peak list:** identical to TotalChrom in all 5 runs, including a 0.3 mV peak at 5.892 min.
- **Ends:** exact for 11/11 peaks.
- **Starts:** exact for 4/11; the others are 1–2 points early. Simple variations of the documented start rule don't fit all 11 cases, so this is still open.
- **Areas:** within 0.011% for every peak that has a .rst. The 5.892 min peak differs by −2.8% (−1.2% in height); there is no .rst for that run, so its boundaries can't be compared.

**Threshold units.** NT is compared with the rise between consecutive points, in µV.

AT is compared with a *sum of point heights* in µV, not with an area in µV·s. The manual describes AT in µV. The deciding evidence is the 5.892 min peak: with µV·s it could never pass (at most 73 µV·s before its rise stalls), yet TotalChrom reported it.

**Behavior worth knowing.** NT sets a minimum slope: a peak whose steepest rise is below NT per point is never detected. The end rule also cuts off tail area in proportion to NT. For Gaussians with σ = 0.7 s and 0.5 µV noise, the recovered fraction of the true area is:

| peak height | NT 50 µV | NT 10 µV | NT 5 µV |
|---|---|---|---|
| 0.5 mV | not detected | 0.956 | 0.983 |
| 1 mV | 0.833 | 0.982 | 0.991 |
| 2 mV | 0.943 | 0.991 | 0.997 |
| 5 mV | 0.981 | 0.997 | 0.999 |
| 15 mV | 0.995 | 0.999 | 1.000 |
| 30 mV | 0.998 | 1.000 | 1.000 |

Lower thresholds were only tested on this synthetic baseline. Real baseline wander may create false peaks at low NT.

**Not verified (no reference data):**
- fused peaks, drop lines and the valley-to-peak split;
- bunching factor > 1;
- NT/AT timed events.

**Not implemented:**
- the width-ratio criterion;
- exponential and tangent skims;
- negative peaks;
- split-peak and forced-baseline events;
- TotalChrom's adjustment when the signal dips below a baseline (only flagged, as `baseline-penetration`).

## 5. Result file (.rst): test-only decoding (`tests/reference.py`)

- **Peak table:** a peak count, then 236-byte records. Byte offsets within a record:

  | Offset | Field |
  |---|---|
  | 0x00 | start, apex, end indices |
  | 0x0C | the matching counts |
  | 0x18 | start, retention and end times (s) |
  | 0x30 | area (µV·s), height (µV) |
  | 0x8C | area fraction, raw amount, adjusted amount |
  | 0xBC | relative retention (to peak 1) |
  | 0xC4 | baseline intercept (counts) and slope (counts/s) |

  The table is located by finding a count followed by self-consistent records.
- **Integration block:** bunching factor (int), NT (int, µV), AT (real), width ratio, valley-to-peak ratio, and three skim ratios. It sits 104 bytes before the replot title string.
- **Timed events:** after the five user-program entries: a count, then 28-byte records of time (min), code and value. Observed codes: −4 = −P, +4 = +P.
- **Other contents:** copies of the instrument, processing and sample methods, the report-format path and printer name.

**Settings found in the 2025 result files:** bunching 1, NT 50, AT 100, width ratio 0.2, valley-to-peak 0.01, skim ratios 5/4/3, and −P at 0.01093 min / +P at 1.93141 min. The current `nicotine in cigs2.mth` differs: NT 1 and no timed events.

## 6. Open questions

1. TotalChrom's exact rule for the true peak start (it affects areas by ≤0.01% here, more for tiny peaks).
2. What the "2" in the unit scale pair means, and how channel B converts.
3. Whether the delay time shifts point times as assumed.
4. Timed-event codes other than ±P, and how BF and NT/AT events behave in TotalChrom.
5. Cluster behavior: drop lines versus valley baselines, how a shared valley point's area is split, and baseline-penetration handling. Checking these needs TotalChrom results for runs with fused peaks.
