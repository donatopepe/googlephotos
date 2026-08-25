"""Structured diagnostics and crash-safe runtime checkpointing."""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from getpass import getuser
from typing import Any
from urllib.parse import urlsplit, urlunsplit


_SENSITIVE_KEYS = {
    "password",
    "cookie",
    "cookies",
    "token",
    "authorization",
    "secret",
    "html",
    "content",
    "inner_html",
    "page_content",
    "dom_content",
}


def redact_url(url: str | None) -> str | None:
    if not url:
        return url
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _sanitize_text(value: str) -> str:
    value = re.sub(r"https?://[^\s?#]+(?:\?[^\s#]*)?(?:#[^\s]*)?", lambda match: str(redact_url(match.group(0))), value)
    return re.sub(
        r"(?i)(password|passwd|token|secret|authorization|cookie)=([^\s]+)",
        r"\1=[REDACTED]",
        value,
    )


def _sanitize(value: Any, key: str | None = None) -> Any:
    if key and key.lower() in _SENSITIVE_KEYS:
        return None
    if key and key.lower() == "url":
        return redact_url(str(value))
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, dict):
        sanitized_dict = {}
        for child_key, child_value in value.items():
            child_name = str(child_key)
            if child_name.lower() in _SENSITIVE_KEYS:
                continue
            sanitized_dict[child_name] = _sanitize(child_value, child_name)
        return sanitized_dict
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    return value


def process_context() -> dict[str, Any]:
    """Return safe process identity fields; never inspect credentials or page data."""
    return {
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "uid": os.getuid() if hasattr(os, "getuid") else None,
        "username": getuser(),
    }

class DiagnosticLog:
    def __init__(self, path: Path, *, run_id: str | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or uuid.uuid4().hex

    def event(self, phase: str, level: str = "INFO", **context: Any) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "phase": phase,
            "level": level,
        }
        for key, value in context.items():
            if key.lower() in _SENSITIVE_KEYS:
                continue
            if key == "url":
                value = redact_url(str(value))
            event[key] = _sanitize(value, key)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


class PendingActionStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, *, label: str, kind: str, scroll_top: int, **extra: Any) -> None:
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "label": label,
            "kind": kind,
            "scroll_top": scroll_top,
        }
        for key, value in extra.items():
            if key.lower() not in _SENSITIVE_KEYS:
                payload[key] = _sanitize(value, key)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or not isinstance(payload.get("label"), str):
            return None
        return payload

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


class CheckpointStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self, *, current_run_id: str | None = None) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("state") == "running" and (
            not payload.get("run_id")
            or (current_run_id is not None and payload.get("run_id") != current_run_id)
        ):
            payload = dict(payload)
            payload["state"] = "stale"
            payload["reason"] = (
                "legacy_running_without_run_identity"
                if not payload.get("run_id")
                else "run_identity_mismatch"
            )
            payload["resumable"] = False
        return payload

    def save(self, *, batch: int, photos: int, state: str, **extra: Any) -> None:
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "batch": batch,
            "photos": photos,
            "state": state,
        }
        for key, value in extra.items():
            if key.lower() not in _SENSITIVE_KEYS:
                payload[key] = _sanitize(value, key)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
