"""Protected, staged publication for FID presets and report/metadata pairs."""
import hashlib
import os
from pathlib import Path
import shutil
import tempfile


def fingerprint(path):
    path = Path(path)
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError("Choose a file destination, not a folder.")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def output_paths(path, extension, sources=(), sidecar=True):
    path = Path(path).expanduser().resolve()
    if path.suffix.lower() != extension:
        raise ValueError(f"Choose a filename ending in {extension}.")
    paths = (path, path.with_suffix(path.suffix + ".json")) if sidecar else (path,)
    for target in paths:
        if any(p.suffix.lower() == ".raw" for p in target.parents):
            raise ValueError("Save outputs outside acquisition .raw folders.")
        for source in sources:
            source = Path(source).resolve()
            if target == source or source in target.parents or (target.exists() and source.exists() and os.path.samefile(target, source)):
                raise ValueError("Acquisition inputs cannot be overwritten.")
        if not target.parent.is_dir():
            raise ValueError("The output folder does not exist.")
    return paths


def publish(files, paths, expected):
    """Publish primary last; roll back both files if a publication step fails."""
    if len(files) != len(paths) or len(paths) != len(expected):
        raise ValueError("Invalid output transaction.")
    staged, backups, written = [], [], []
    try:
        for src, dest, before in zip(files, paths, expected):
            if fingerprint(dest) != before:
                raise FileExistsError("The destination changed while the operation was running. Choose the export again.")
            fd, name = tempfile.mkstemp(prefix=".fid-output-", dir=dest.parent)
            os.close(fd)
            staged.append(Path(name))
            shutil.copyfile(src, staged[-1])
            backup = None
            if before is not None:
                fd, name = tempfile.mkstemp(prefix=".fid-backup-", dir=dest.parent)
                os.close(fd)
                backup = Path(name)
                shutil.copyfile(dest, backup)
            backups.append(backup)
        for i in reversed(range(len(paths))):
            if fingerprint(paths[i]) != expected[i]:
                raise FileExistsError("The destination changed while the operation was running.")
            if expected[i] is None:
                # Windows rename refuses an existing destination and also works
                # on removable filesystems without hard-link support.
                if os.name == "nt":
                    os.rename(staged[i], paths[i])
                else:
                    os.link(staged[i], paths[i])
            else:
                os.replace(staged[i], paths[i])
            written.append(i)
    except Exception:
        for i in reversed(written):
            if backups[i] is None:
                paths[i].unlink(missing_ok=True)
            else:
                os.replace(backups[i], paths[i])
        raise
    finally:
        for path in staged + [p for p in backups if p is not None]:
            path.unlink(missing_ok=True)


def save_json(path, value, sources=(), overwrite=False):
    import json
    paths = output_paths(path, ".json", sources, sidecar=False)
    expected = tuple(fingerprint(p) for p in paths)
    if any(x is not None for x in expected) and not overwrite:
        raise FileExistsError("The preset already exists.")
    with tempfile.TemporaryDirectory(prefix="fid-preset-") as folder:
        source = Path(folder) / "preset.json"
        source.write_text(json.dumps(value, indent=2, allow_nan=False, ensure_ascii=False), encoding="utf-8")
        publish((source,), paths, expected)
