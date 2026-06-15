from __future__ import annotations

import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, TextIO


@contextmanager
def atomic_text_writer(
    path: str | Path, *, newline: str | None = None
) -> Iterator[TextIO]:
    """Write a current-state text artifact without exposing partial content."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=output.parent, prefix=f".{output.name}.", suffix=".tmp", text=True
    )
    temporary = Path(temporary_name)
    try:
        mode = stat.S_IMODE(output.stat().st_mode) if output.exists() else 0o644
        os.chmod(temporary, mode)
        with os.fdopen(descriptor, "w", newline=newline) as handle:
            yield handle
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
        directory_descriptor = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_text(content: str, path: str | Path) -> None:
    with atomic_text_writer(path) as handle:
        handle.write(content)
