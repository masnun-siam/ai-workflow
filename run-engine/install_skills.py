"""`aiw install-skills --harness codex [--remove]`: link the plugin skills into Codex's ~/.agents/skills. Stdlib only.

Every link it makes is recorded in `<data_dir>/install_skills.json` ({"codex": [<link path>, ...]}) the moment it
is made. It only repoints or deletes recorded paths, and only while they are still symlinks: anything else at a
path (a user folder, a file, a link it did not make) is skipped and reported, never touched.
"""

from __future__ import annotations

import json
import os

import repo_skills
import shared

ACTIONS = ("linked", "repointed", "removed", "unchanged", "skipped")


def _record_path() -> str:
    return os.path.join(shared.data_dir(), "install_skills.json")


def _load(path: str) -> dict:
    """The whole record; missing is empty, corrupt is moved aside (with a warning) and treated as empty."""
    shared.backup_if_corrupt(path)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _link_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".agents", "skills")


def _not_symlink(p: str) -> str:
    return f"skipped {p}: no longer a symlink, left untouched"


def _install(rec: list, save) -> list:
    out = []
    names = repo_skills.names()
    for p in list(rec):
        name = os.path.basename(p)
        target = os.path.join(repo_skills._SKILLS_DIR, name)
        if not os.path.islink(p):
            if os.path.lexists(p):
                out.append(_not_symlink(p))
            rec.remove(p)  # aiw no longer owns it; a vanished link is recreated below
            save()
        elif name not in names:
            os.unlink(p)
            rec.remove(p)
            save()
            out.append(f"removed {name}")
        elif os.readlink(p) != target:
            os.unlink(p)
            os.symlink(target, p)
            out.append(f"repointed {name}")
        else:
            out.append(f"unchanged {name}")
    link_dir = _link_dir()
    for name in sorted(names):
        p = os.path.join(link_dir, name)
        if p in rec:
            continue
        if os.path.lexists(p):
            out.append(f"skipped {p}: already exists and was not created by aiw install-skills")
            continue
        os.makedirs(link_dir, exist_ok=True)
        os.symlink(os.path.join(repo_skills._SKILLS_DIR, name), p)
        rec.append(p)
        save()
        out.append(f"linked {name}")
    return out


def _remove(rec: list, save) -> list:
    out = []
    for p in list(rec):
        if os.path.islink(p):
            os.unlink(p)
            out.append(f"removed {os.path.basename(p)}")
        elif os.path.lexists(p):
            out.append(_not_symlink(p))
        rec.remove(p)
        save()
    return out


def run(harness: str, remove: bool) -> list:
    """Report lines, then the summary line. Raises OSError after the record holds what was made."""
    path = _record_path()
    with shared.json_lock(path):
        data = _load(path)
        rec = data.get(harness)
        rec = [p for p in rec if isinstance(p, str)] if isinstance(rec, list) else []

        def save():
            data[harness] = rec
            shared.write_json(path, data)

        if remove and not rec:
            return ["nothing recorded to remove"]
        out = (_remove if remove else _install)(rec, save)
    counts = {a: sum(line.startswith(a + " ") for line in out) for a in ACTIONS}
    return out + [", ".join(f"{n} {a}" for a, n in counts.items())]


def cmd_install_skills(args) -> None:
    try:
        lines = run(args.harness, args.remove)
    except OSError as e:
        shared.die(1, f"install-skills: {e}")
    print("\n".join(lines))


def register(sub, add) -> None:
    p = sub.add_parser("install-skills", help="link the plugin skills into another harness's skills folder (codex)")
    p.add_argument("--harness", required=True, choices=["codex"])
    p.add_argument("--remove", action="store_true", help="delete the links this command made")
    p.set_defaults(func=cmd_install_skills)
