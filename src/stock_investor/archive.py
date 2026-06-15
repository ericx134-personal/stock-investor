from __future__ import annotations

import os
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
