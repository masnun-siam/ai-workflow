"""No-repo work: runs in the notes vault, the vault's 05-Work folders, and making a repo for an idea.

A new product idea has no code repo yet, so its create-prd / dump / intake / custom session runs in
the notes vault (Settings) and files under 05-Work/<Project>/<Feature>. New run suggests that folder
(keyword match in the UI, or `suggest` here asks Claude), and once the PRD is approved
`create_repo` makes a local git repo for it, registered as local/<name> until it gets a GitHub
remote (ui_repos re-registers it then).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import dispatch
import ui_settings
from shared import run

WORK = "05-Work"
NO_REPO_COMMANDS = ("create-prd", "dump", "intake")  # plus the custom prompt
_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_FOLDER_RE = re.compile(r"05-Work(/[^/\x00]{1,120}){1,2}")
_STATUS_RE = re.compile(r"\*\*Status:\*\*\s*([A-Za-z ]+?)\s*(?:·|$)", re.M)


def vault() -> str:
    return ui_settings.vault_dir()


def valid_folder(folder) -> bool:
    """05-Work/<Project>[/<Feature>]: no '..', no hidden parts, nothing outside 05-Work."""
    if not isinstance(folder, str) or not _FOLDER_RE.fullmatch(folder):
        return False
    return all(p and p not in (".", "..") and not p.startswith(".") for p in folder.split("/"))


def folders(root=None) -> list:
    """[{project, feature, path}] for every 05-Work/<Project> and 05-Work/<Project>/<Feature> folder."""
    base = os.path.join(root or vault(), WORK)
    out = []
    try:
        projects = sorted(e.name for e in os.scandir(base) if e.is_dir() and not e.name.startswith("."))
    except OSError:
        return []
    for p in projects:
        out.append({"project": p, "feature": None, "path": f"{WORK}/{p}"})
        try:
            feats = sorted(
                e.name for e in os.scandir(os.path.join(base, p)) if e.is_dir() and not e.name.startswith(".")
            )
        except OSError:
            continue
        out += [{"project": p, "feature": f, "path": f"{WORK}/{p}/{f}"} for f in feats]
    return out


SUGGEST_PROMPT = """You file product ideas into an Obsidian vault laid out as 05-Work/<Project>/<Feature>.
Existing folders, one per line:
{folders}

The idea:
<<<
{text}
>>>

Pick the folder this idea belongs in. Reuse an existing project when the idea is clearly part of it;
otherwise propose a new project. Always name a feature folder (existing or new) for this idea.
Names are short Title Case, no slashes. Reply with only JSON, no prose:
{{"project": "...", "feature": "...", "new_project": true|false, "new_feature": true|false, "why": "one short sentence"}}"""


def parse_suggestion(raw: str):
    """The JSON object in Claude's reply, cleaned to {project, feature, new_project, new_feature, why}, or None."""
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else None
    except ValueError:
        return None
    if not isinstance(d, dict):
        return None
    clean = lambda v, n=80: re.sub(r"[/\\\x00]", " ", str(v or "")).strip()[:n]  # noqa: E731
    project, feature = clean(d.get("project")), clean(d.get("feature"))
    if not project or not feature or project.startswith(".") or feature.startswith("."):
        return None
    return {
        "project": project,
        "feature": feature,
        "new_project": d.get("new_project") is True,
        "new_feature": d.get("new_feature") is True,
        "why": clean(d.get("why"), 200),
    }


def suggest(text: str, claude_cmd=None, timeout=90):
    """(status, body): ask Claude (Haiku, the default account) where an idea belongs."""
    if not isinstance(text, str) or not text.strip():
        return 400, {"error": "text is required"}
    listing = "\n".join(f["path"] for f in folders()) or "(none yet)"
    prompt = SUGGEST_PROMPT.format(folders=listing, text=text.strip()[:4000])
    try:
        exe = ui_settings.argv(claude_cmd or ui_settings.default_cmd())
        p = subprocess.run(
            [*exe, "-p", "--model", "haiku", "--output-format", "text", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=vault() if os.path.isdir(vault()) else None,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        return 502, {"error": f"could not ask Claude: {e}"}
    got = parse_suggestion(p.stdout)
    if p.returncode != 0 or not got:
        return 502, {"error": ((p.stderr or "").strip().splitlines() or ["Claude gave no usable suggestion"])[-1]}
    return 200, got


def prd_info(folder: str, root=None):
    """{exists, status, title, path} of <folder>/PRD.md in the vault; status is the header's Status."""
    if not valid_folder(folder):
        raise ValueError("folder must be 05-Work/<Project>/<Feature>")
    path = os.path.join(root or vault(), folder, "PRD.md")
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return {"exists": False, "status": None, "title": None, "folder": folder}
    m = _STATUS_RE.search(text)
    t = re.search(r"^#\s+(?:PRD\s*[—-]\s*)?(.+)$", text, re.M)
    return {
        "exists": True,
        "status": m.group(1).strip() if m else None,
        "title": t.group(1).strip() if t else None,
        "folder": folder,
    }


def _strip_frontmatter(text: str) -> str:
    return re.sub(r"\A---\n.*?\n---\n", "", text, count=1, flags=re.S)


def readme_from_prd(prd: str, name: str) -> str:
    """README: the PRD's title and its Overview (or first section), pointing at the PRD."""
    body = _strip_frontmatter(prd)
    t = re.search(r"^#\s+(?:PRD\s*[—-]\s*)?(.+)$", body, re.M)
    title = t.group(1).strip() if t else name
    sec = re.search(r"^##\s+Overview\s*\n(.*?)(?=^##\s|\Z)", body, re.M | re.S) or re.search(
        r"^##\s+[^\n]+\n(.*?)(?=^##\s|\Z)", body, re.M | re.S
    )
    summary = sec.group(1).strip() if sec else ""
    return f"# {title}\n\n{summary}\n\nThe product requirements live in [docs/prds/](docs/prds/).\n".replace(
        "\n\n\n", "\n\n"
    )


def slugify(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-") or "prd"


def create_repo(parent: str, name: str, prd_folder=None, root=None) -> dict:
    """mkdir parent/name, git init, add docs/prds/<slug>.md and a README from the vault PRD (or a bare
    README), register it as local/<name>. Nothing is committed or pushed. ValueError on bad input."""
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name) or name in (".", ".."):
        raise ValueError("name: letters, digits, '.', '_' and '-' only")
    parent = os.path.expanduser(parent.strip()) if isinstance(parent, str) else parent  # "~/Projects" works when typed
    if not isinstance(parent, str) or not os.path.isabs(parent) or not os.path.isdir(parent):
        raise ValueError("parent must be an existing absolute folder (e.g. ~/Projects)")
    if prd_folder is not None and not valid_folder(prd_folder):
        raise ValueError("prd_folder must be 05-Work/<Project>/<Feature>")
    slug = f"local/{name}"
    if any(k.lower() == slug.lower() for k in dispatch.read_checkouts()):
        raise ValueError(f"{slug} is already registered")
    path = os.path.join(os.path.realpath(parent), name)
    if os.path.exists(path):
        raise ValueError(f"{path} already exists")
    prd = None
    if prd_folder:
        try:
            with open(os.path.join(root or vault(), prd_folder, "PRD.md"), encoding="utf-8") as fh:
                prd = fh.read()
        except OSError as e:
            raise ValueError(f"no PRD.md in {prd_folder}") from e
    os.makedirs(path)
    try:
        r = run(["git", "init", "-q", "-b", "main", path], timeout=30)  # never raises: a missing git is a 400
        if r.returncode != 0:
            raise ValueError(f"git init failed: {(r.stderr or '').strip()}")
        files = ["README.md"]
        if prd is not None:
            rel = f"docs/prds/{slugify(prd_folder.rsplit('/', 1)[-1])}.md"
            os.makedirs(os.path.join(path, "docs", "prds"))
            with open(os.path.join(path, rel), "w", encoding="utf-8") as fh:
                fh.write(_strip_frontmatter(prd))
            files.append(rel)
        with open(os.path.join(path, "README.md"), "w", encoding="utf-8") as fh:
            fh.write(readme_from_prd(prd, name) if prd is not None else f"# {name}\n")
        dispatch.register_checkout(slug, path)
    except BaseException:
        shutil.rmtree(path, ignore_errors=True)  # nothing half-made stays behind
        raise
    return {"slug": slug, "path": path, "files": files}
