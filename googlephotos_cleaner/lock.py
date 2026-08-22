"""PID lock protecting persistent browser profiles."""

from __future__ import annotations

import json
import os
from pathlib import Path


class ProfileLockedError(RuntimeError):
    """Raised when another live process owns the browser profile."""


class ProfileLock:
    def __init__(self, path: Path, *, pid: int | None = None) -> None:
        self.path = Path(path)
        self.pid = pid or os.getpid()
        self.acquired = False

    @staticmethod
    def _is_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                owner = json.loads(self.path.read_text(encoding="utf-8"))
                owner_pid = int(owner.get("pid", 0))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                owner_pid = 0
            if self._is_alive(owner_pid):
                raise ProfileLockedError(
                    f"Browser profile already in use by pid {owner_pid}"
                )
            self.path.unlink(missing_ok=True)

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except FileExistsError as exc:
            raise ProfileLockedError("Browser profile lock appeared concurrently") from exc
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump({"pid": self.pid}, stream)
                stream.write("\n")
        except Exception:
            self.path.unlink(missing_ok=True)
            raise
        self.acquired = True

    def release(self) -> None:
        if self.acquired:
            self.path.unlink(missing_ok=True)
            self.acquired = False

    def __enter__(self) -> "ProfileLock":
        self.acquire()
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.release()
