"""The checkouts.json registry: owner/repo -> local checkout path."""

from __future__ import annotations

import json
import os

# --------------------------------------------------------------------------- checkouts.json registry

from shared import atomic_write_text, data_dir  # noqa: E402


def checkouts_path() -> str:
    return os.path.join(data_dir(), "checkouts.json")


def read_checkouts() -> dict:
    """{} for a missing, zero-byte, or non-JSON file — the registry is
    best-effort bookkeeping, not load-bearing state."""
    path = checkouts_path()
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
    except OSError:
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def rename_checkout(old: str, new: str) -> bool:
    """Re-key one registry entry (old -> new), keeping its path. False when old is missing or new
    is already registered, so nothing is overwritten."""
    current = read_checkouts()
    if old not in current or any(k.lower() == new.lower() for k in current):
        return False
    current[new] = current.pop(old)
    atomic_write_text(checkouts_path(), json.dumps(current))
    return True


def remove_checkout(slug: str) -> bool:
    """Unregister one repo (its clone on disk is untouched). False when it was not registered."""
    current = read_checkouts()
    if slug not in current:
        return False
    del current[slug]
    atomic_write_text(checkouts_path(), json.dumps(current))
    return True


def register_checkout(slug: str, path: str) -> None:
    """Atomically add slug -> path to the registry. Writes only the slug/path
    pair given — never os.environ, never .env content."""
    out_path = checkouts_path()
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    current = read_checkouts()
    current[slug] = path
    atomic_write_text(out_path, json.dumps(current))
