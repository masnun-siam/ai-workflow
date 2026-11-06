"""The product registry: <data_dir>/products.json maps a Documentation Repo's owner/name to its
checkout path. A product is that docs repo plus the code repos its .blubird/repos.json lists; the
code repos are read from the map on every call and never stored here."""

from __future__ import annotations

import json
import os

import dispatch
import ui_repos
from shared import atomic_write_text, backup_if_corrupt, data_dir, json_lock

_KEYS = ("name", "role", "repo", "path")


def _path() -> str:
    return os.path.join(data_dir(), "products.json")


def _read() -> dict:
    """{} for a missing, empty or corrupt file; never raises."""
    try:
        with open(_path(), encoding="utf-8") as fh:
            data = json.loads(fh.read() or "{}")
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(docs_repo: str, path: str) -> None:
    with json_lock(_path()):
        backup_if_corrupt(_path())
        current = _read()
        for k in [k for k in current if k.lower() == docs_repo.lower()]:
            del current[k]  # one row per docs repo, whatever case it was stored in
        current[docs_repo] = path
        atomic_write_text(_path(), json.dumps(current))


def read_map(path: str) -> list:
    """The `repos` list of <path>/.blubird/repos.json; ValueError naming the problem otherwise."""
    f = os.path.join(path, ".blubird", "repos.json")
    try:
        with open(f, encoding="utf-8") as fh:
            raw = fh.read()
    except OSError:
        raise ValueError(f"no .blubird/repos.json in {path}") from None
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise ValueError(f"repos.json is not valid JSON: {e}") from None
    if not isinstance(data, dict):
        raise ValueError("repos.json must be a JSON object")
    repos = data.get("repos")
    if not isinstance(repos, list) or not repos:
        raise ValueError("repos.json must have a non-empty `repos` list")
    for i, e in enumerate(repos):
        if not isinstance(e, dict):
            raise ValueError(f"repos.json entry {i} is not an object")
        for k in _KEYS:
            if not isinstance(e.get(k), str) or not e[k]:
                raise ValueError(f"repos.json entry {i} has no string `{k}`")
        if not ui_repos._SLUG_RE.match(e["repo"]):
            raise ValueError(f"repos.json entry {i}: repo {e['repo']!r} is not owner/name")
    return repos


def _resolve(docs_path: str, entry: dict) -> str:
    return os.path.realpath(os.path.join(docs_path, entry["path"]))


def _cloned(path: str) -> bool:
    return os.path.exists(os.path.join(path, ".git"))  # dir or worktree file; no git subprocess


def _registered_at(slug: str, checkouts: dict):
    return next((p for k, p in checkouts.items() if k.lower() == slug.lower()), None)


def register(path) -> dict:
    """Register a docs repo checkout as a product, and it plus every cloned code repo of its map
    as checkouts. Nothing is written when the map is bad or a code repo is registered elsewhere."""
    if not isinstance(path, str):
        raise ValueError("path must be a string")
    top = ui_repos.validate_repo(path.strip())
    slug = ui_repos.origin_slug(top)
    if not slug:
        raise ValueError(f"{top} has no GitHub origin")
    entries = read_map(top)
    todo, checkouts = [], dispatch.read_checkouts()
    for e in entries:
        resolved = _resolve(top, e)
        if resolved == top or not _cloned(resolved):
            continue  # the docs repo's own "." entry, or a repo not cloned yet
        old = _registered_at(e["repo"], checkouts)
        if isinstance(old, str) and os.path.realpath(old) != resolved:
            raise ValueError(f"{e['repo']} is already registered at {old}, the map points at {resolved}")
        todo.append((e["repo"], resolved))
    ui_repos.register(slug, top)
    for repo, resolved in todo:
        ui_repos.register(repo, resolved)  # ValueError when the clone's origin is not the map's repo
    _save(slug, top)
    return next(p for p in list_products() if p["docs_repo"].lower() == slug.lower())


def list_products() -> list:
    """[{docs_repo, path, repos:[{name, role, repo, path, cloned, conflict?}], error?}] from disk.
    File reads and os.path.exists only: this runs on every poll tick."""
    out = []
    for docs_repo, path in sorted(_read().items()):
        if not isinstance(path, str):
            continue
        try:
            entries = read_map(path)
        except ValueError as e:
            out.append({"docs_repo": docs_repo, "path": path, "repos": [], "error": str(e)})
            continue
        rows = []
        for e in entries:
            resolved = _resolve(path, e)
            rows.append({**{k: e[k] for k in ("name", "role", "repo")}, "path": resolved, "cloned": _cloned(resolved)})
        out.append({"docs_repo": docs_repo, "path": path, "repos": rows})
    owners: dict = {}  # repo slug (lower) -> docs repos that list it; a docs repo lists itself
    for p in out:
        for s in {p["docs_repo"].lower(), *(r["repo"].lower() for r in p["repos"])}:
            owners.setdefault(s, []).append(p["docs_repo"])
    for p in out:
        for r in p["repos"]:
            other = [d for d in owners.get(r["repo"].lower(), []) if d != p["docs_repo"]]
            if other:
                r["conflict"] = other[0]
    return out


def product_of(slug: str):
    """The product whose docs repo or any listed repo is `slug` (any case), or None."""
    want = slug.lower() if isinstance(slug, str) else None
    for p in list_products():
        if "error" not in p and (p["docs_repo"].lower() == want or any(r["repo"].lower() == want for r in p["repos"])):
            return p
    return None


def mapped(path) -> bool:
    """True when the checkout carries a blubird map (repos.json or docs-repo). Never raises."""
    try:
        return any(os.path.exists(os.path.join(path, ".blubird", f)) for f in ("repos.json", "docs-repo"))
    except (OSError, TypeError, ValueError):
        return False


def sync() -> None:
    """Register every cloned code repo of every product that is not yet a checkout, so a clone
    made after the product was registered is picked up. Called by the poll loop; never raises."""
    try:
        products = list_products()
        known = {k.lower() for k in dispatch.read_checkouts()}
    except Exception:  # noqa: BLE001 - the poll loop must keep running
        return
    for p in products:
        if "error" in p:
            continue
        for r in p["repos"]:
            if r["cloned"] and r["repo"].lower() not in known:
                try:
                    ui_repos.register(r["repo"], r["path"])
                    known.add(r["repo"].lower())
                except (ValueError, OSError):
                    continue
