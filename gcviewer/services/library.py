"""UI-independent sample discovery. Listing never parses chromatogram signals."""
from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import sys


@dataclass(frozen=True)
class LibraryEntry:
    key: str
    name: str
    path: str
    kind: str
    status: str
    available: bool
    index: int = 0
    description: str = ""
    method: str = ""
    vial: str = ""
    sample_type: str = ""
    list_metadata: dict = field(default_factory=dict)


def entry_key(folder, kind, source_list, row_identity):
    identity = json.dumps([str(folder), kind, source_list, row_identity], ensure_ascii=False)
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def discover_library(folder, kind, spl_path=None):
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError("Choose an existing folder containing the acquisition files/directories.")
    if folder.suffix.lower() == ".raw":
        raise ValueError("Choose the parent folder containing .raw acquisitions, not a single acquisition.")
    if kind not in ("ms", "fid"):
        raise ValueError("Choose GC-MS or GC-FID.")
    if spl_path and kind != "ms":
        raise ValueError("PE .SPL lists are supported here for GC-MS. Clear the list to browse GC-FID files.")
    raw_paths = sorted((p for p in folder.iterdir() if p.suffix.lower() == ".raw"), key=lambda p: p.name.casefold())
    if spl_path:
        from gcviewer.parsers.spl import parse_spl, match_rows_to_raw, spl_raw_name
        source_list = str(Path(spl_path).expanduser().resolve())
        metadata, rows = parse_spl(source_list)
        match_rows_to_raw(rows, str(folder), finder_fn=lambda _: [p.name for p in raw_paths if p.is_dir()])
        actual_names = {p.name.casefold(): p.name for p in raw_paths if p.is_dir()}
        entries = []
        for row in rows:
            source_name = row.get("source_file_name")
            literal_name = source_name or row["file_name"]
            literal_match = actual_names.get((literal_name + ".raw").casefold())
            matched = literal_match if source_name else row.get("raw_match")
            match_kind = "Exact name (case-insensitive)" if matched else "No match"
            if literal_match:
                match_kind = "Original SPL filename (case-insensitive)"
            aliases = []
            if not matched and not source_name:
                target = row["file_name"].casefold().replace("-", "_")
                aliases = [p.name for p in raw_paths if p.is_dir() and p.stem.casefold().replace("-", "_") == target]
                if len(aliases) == 1:
                    matched, match_kind = aliases[0], "Unique PE dash/underscore alias"
                elif aliases:
                    match_kind = "Ambiguous PE name aliases"
            path = folder / (matched or (literal_name + ".raw" if source_name else spl_raw_name(row)))
            used_alias = bool(aliases)
            status = ("Found · name alias" if used_alias else "Found") if matched else ("Ambiguous filename" if aliases else "Missing acquisition")
            entries.append(LibraryEntry(
                key=entry_key(folder, kind, source_list, row["source_index"]), name=literal_name,
                path=str(path), kind=kind, status=status, available=bool(matched),
                index=row["index"], description=row["description"], method=row["method"], vial=row["vial"],
                sample_type=row["sample_type"], list_metadata={"list": metadata, "row": dict(row, raw_match=matched),
                    "matching": {"rule": match_kind, "matched_filename": matched, "alias_candidates": aliases}}))
        return {"folder": str(folder), "kind": kind, "source_list": source_list,
                "folder_acquisitions": len(raw_paths), "list_warnings": metadata.get("warnings", []),
                "entries": [asdict(e) for e in entries]}
    entries = []
    for index, path in enumerate(raw_paths, 1):
        if kind == "ms":
            available = path.is_dir()
            status = "Found" if available else "GC-MS requires a directory"
        else:
            from gcviewer.parsers.totalchrom.discovery import is_penx_file
            available = is_penx_file(path)
            status = "Found" if available else ("GC-FID requires a file" if path.is_dir() else "Unsupported PENX header")
        entries.append(LibraryEntry(entry_key(folder, kind, "", path.name), path.name, str(path), kind,
                                    status, available, index=index))
    return {"folder": str(folder), "kind": kind, "source_list": "", "folder_acquisitions": len(raw_paths),
            "list_warnings": [], "entries": [asdict(e) for e in entries]}


def read_library(directory):
    result = json.loads((Path(directory) / "library.json").read_text(encoding="utf-8"))
    if "error" in result:
        raise ValueError(result["error"])
    return result, [LibraryEntry(**row) for row in result["entries"]]


def main(args):
    kind, folder, source_list, output = args
    try:
        result = discover_library(folder, kind, source_list or None)
        code = 0
    except Exception as exc:
        result, code = {"error": f"{type(exc).__name__}: {exc}"}, 1
    (Path(output) / "library.json").write_text(json.dumps(result, ensure_ascii=False, default=str), encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
