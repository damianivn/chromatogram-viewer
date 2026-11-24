"""
Export a TotalChrom / TurboMass sample list (.SPL) to Excel or CSV.

Usage (from the repository root):
    python export_spl.py path\\to\\run.SPL
    python export_spl.py run.SPL -o samples.xlsx
    python export_spl.py run.SPL --folder D:\\data\\raw -o out.csv
"""

import argparse
import sys
from pathlib import Path

from gcviewer.reports.sample_list import export_spl
from gcviewer.parsers.spl import is_spl_file


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Export a .SPL sample list to Excel or CSV.")
    p.add_argument("spl", help="Path to the .SPL sample list file")
    p.add_argument("-o", "--output", help="Output file (.xlsx or .csv)")
    p.add_argument("--folder", help="Data folder to match .raw directories")
    p.add_argument("-f", "--format", choices=("xlsx", "csv"),
                   help="Output format (default: from file extension)")
    args = p.parse_args(argv)

    spl_path = Path(args.spl)
    if not spl_path.is_file():
        print(f"Error: file not found: {spl_path}", file=sys.stderr)
        return 1
    if not is_spl_file(spl_path):
        print(f"Error: not a Jet DB sample list: {spl_path}", file=sys.stderr)
        return 1

    if args.output:
        out_path = Path(args.output)
    else:
        out_path = spl_path.with_suffix(".xlsx")

    try:
        meta, rows, written = export_spl(
            spl_path, out_path, data_folder=args.folder, fmt=args.format)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    matched = sum(1 for r in rows if r.get("raw_match"))
    print(f"Wrote {written}")
    print(f"  {meta['row_count']} samples ({meta['source_rows']} DB rows)")
    if args.folder:
        print(f"  {matched} matched .raw in {args.folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
