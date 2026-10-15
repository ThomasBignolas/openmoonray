"""Extract a pinned source archive into a short, explicit build directory."""
from pathlib import Path, PurePosixPath
import sys
import zipfile

archive, destination = sys.argv[1:]
root = Path(destination).resolve()
root.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(archive) as source:
    for member in source.infolist():
        path = PurePosixPath(member.filename)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Unsafe archive member: {member.filename}")
        relative = Path(*path.parts[1:])
        if not relative.parts:
            continue
        target = (root / relative).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"Archive member escapes destination: {member.filename}")
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read(member))
