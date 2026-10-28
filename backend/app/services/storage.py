"""Local file storage for evidence images and reports.

Files are addressed by an opaque storage key (relative path). Keys are never
returned by the public API; files are served through ID-based endpoints.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from app.config import get_settings


class LocalStorage:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents and p != self.root:
            raise ValueError("invalid storage key")
        return p

    def save(self, key: str, data: bytes) -> str:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return key

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def path(self, key: str) -> Path:
        return self._path(key)

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def usage(self) -> dict:
        total = 0
        files = 0
        for f in self.root.rglob("*"):
            if f.is_file():
                files += 1
                total += f.stat().st_size
        disk = shutil.disk_usage(self.root)
        return {"files": files, "bytes": total, "disk_free_bytes": disk.free, "writable": _writable(self.root)}


def _writable(root: Path) -> bool:
    probe = root / ".write_probe"
    try:
        probe.write_bytes(b"ok")
        probe.unlink()
        return True
    except OSError:
        return False


_storage: LocalStorage | None = None


def get_storage() -> LocalStorage:
    global _storage
    if _storage is None:
        _storage = LocalStorage(get_settings().storage_dir)
    return _storage


def set_storage(s: LocalStorage | None) -> None:
    global _storage
    _storage = s
