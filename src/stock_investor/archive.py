from __future__ import annotations

import os
import json
import shutil
import tarfile
import tempfile
from datetime import date
from pathlib import Path


EXCLUDED_NAMES = {".refresh.lock", "service.env"}
EXCLUDED_DIRECTORIES = {"archives", "logs"}


def _require_private(path: Path) -> None:
    if "private" not in {part.lower() for part in path.parts}:
        raise ValueError("archive source must be under a private directory")


def _archive_members(source: Path) -> list[Path]:
    return sorted(
        path
        for path in source.rglob("*")
        if path.is_file()
        and path.name not in EXCLUDED_NAMES
        and not path.name.endswith(".tmp")
        and not EXCLUDED_DIRECTORIES.intersection(path.relative_to(source).parts)
    )


def archive_private_artifacts(
    source_dir: str | Path,
    archive_dir: str | Path | None = None,
    *,
    keep_days: int = 30,
    as_of: date | None = None,
) -> dict:
    """Create one replaceable daily archive and prune only expired archives."""
    source = Path(source_dir)
    _require_private(source)
    if keep_days < 1:
        raise ValueError("keep_days must be at least 1")
    archives = Path(archive_dir) if archive_dir else source / "archives"
    archives.mkdir(parents=True, exist_ok=True)
    archive_date = as_of or date.today()
    output = archives / f"stock-investor-private-{archive_date.isoformat()}.tar.gz"
    members = _archive_members(source)

    descriptor, temporary_name = tempfile.mkstemp(
        dir=archives, prefix=f".{output.name}.", suffix=".tmp"
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with tarfile.open(temporary, "w:gz") as bundle:
            for member in members:
                bundle.add(member, arcname=member.relative_to(source))
        os.replace(temporary, output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    cutoff = archive_date.toordinal() - keep_days + 1
    removed = []
    for candidate in archives.glob("stock-investor-private-*.tar.gz"):
        try:
            candidate_date = date.fromisoformat(
                candidate.name.removeprefix("stock-investor-private-").removesuffix(
                    ".tar.gz"
                )
            )
        except ValueError:
            continue
        if candidate_date.toordinal() < cutoff:
            candidate.unlink()
            removed.append(candidate.name)

    return {
        "archive": str(output),
        "files": len(members),
        "bytes": output.stat().st_size,
        "removed_archives": sorted(removed),
        "keep_days": keep_days,
    }


def verify_private_archive(path: str | Path) -> dict:
    """Safely restore an archive in isolation and validate its private artifacts."""
    archive = Path(path)
    with tempfile.TemporaryDirectory() as directory:
        restored = Path(directory)
        with tarfile.open(archive) as bundle:
            members = bundle.getmembers()
            for member in members:
                member_path = Path(member.name)
                if (
                    member_path.is_absolute()
                    or ".." in member_path.parts
                    or member.issym()
                    or member.islnk()
                    or member.name in EXCLUDED_NAMES
                    or EXCLUDED_DIRECTORIES.intersection(member_path.parts)
                ):
                    raise ValueError(f"unsafe or excluded archive member: {member.name}")
                if not member.isfile():
                    continue
                source = bundle.extractfile(member)
                if source is None:
                    raise ValueError(f"archive member is unreadable: {member.name}")
                target = restored / member_path
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("wb") as output:
                    shutil.copyfileobj(source, output)

        required = {
            "refresh-manifest.json",
            "dashboard-v3.html",
            "wave-direction-forecasts.jsonl",
        }
        restored_names = {
            str(item.relative_to(restored)) for item in restored.rglob("*") if item.is_file()
        }
        missing_required = sorted(required - restored_names)
        if missing_required:
            raise ValueError(f"archive missing required artifacts: {missing_required}")

        manifest = json.loads((restored / "refresh-manifest.json").read_text())
        missing_declared = sorted(
            artifact
            for artifact in manifest.get("artifacts", {}).values()
            if Path(artifact).name not in {Path(name).name for name in restored_names}
        )
        if missing_declared:
            raise ValueError(f"archive missing manifest artifacts: {missing_declared}")

        json_files = 0
        jsonl_records = 0
        for item in restored.rglob("*"):
            if item.suffix == ".json":
                json.loads(item.read_text())
                json_files += 1
            elif item.suffix == ".jsonl":
                for line in item.read_text().splitlines():
                    if line.strip():
                        json.loads(line)
                        jsonl_records += 1

    return {
        "archive": str(archive),
        "files": len(restored_names),
        "json_files": json_files,
        "jsonl_records": jsonl_records,
        "status": "VERIFIED",
    }
