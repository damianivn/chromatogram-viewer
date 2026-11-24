# TotalChrom GC-FID raw file format

This is the layout used by the reader for type-1 PENX acquisitions. The reference files came from TotalChrom Workstation 6.3.2 and a Clarus 500 FID. The checks used three runs with vendor ASCII exports and five runs with printed reports, four of which also had result files.

## Header

The first four bytes spell `PENX`. The next four encode the file type as a big-endian signed integer (`1` for raw data). Integers occupy four bytes. Text fields start with a byte count and end with padding to a four-byte boundary. Doubles consist of two big-endian 32-bit words with the low word first.

Read the file header, data header, A/D header and sequence row in order. Together they provide the acquisition status, channel, run duration, point count and detector extrema. Sample names and method paths vary in length, which moves the start of the signal. In two sets of reference files the signal began at byte 1008 and byte 1020, respectively.

## Signal

A second point count immediately precedes the array of signed 32-bit big-endian detector readings. The reader checks that the counts agree, reads exactly that many points and compares the observed minimum and maximum with the A/D header. These checks help distinguish a correctly aligned trace from plausible-looking values read a few bytes too early or late.

## Footer and units

The embedded instrument method follows the final reading. Its A/D settings give the acquisition delay in minutes and the sampling rate in hertz. The instrument configuration gives a pair of scale values for each channel. For zero-based point index `i`, the reader uses:

```text
time in seconds = 60 * delay_minutes + (i + 1) / rate_hz
signal in microvolts = detector_counts / (channel_scale * channel_multiplier)
```

At 12.5 Hz with zero delay, the first reading is at 0.08 s. All reference runs had zero delay, so the nonzero-delay term remains unverified. The channel A reference scale pair was (54.01791, 2.0). The observed channel B pair had a zero multiplier and could not establish a conversion. Later audit records are outside the scope of the reader.

## Checks against vendor results

With TotalChrom's stored start and end points, a straight baseline between the endpoints reproduced all 11 reference peak areas to floating-point precision. Automatic integration can choose slightly different boundaries. In those 11 peaks, all end points matched, four starts matched, and seven starts fell one or two readings early. A separate small peak with only a printed report differed in area by 2.8%.

The [reader](../gcviewer/parsers/totalchrom/raw.py) gives the field order. The [structural tests](../tests/fid_core/test_penx_reader.py) exercise the parser with synthetic records.
