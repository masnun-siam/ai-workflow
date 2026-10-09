"""Guided Flow records for the aiw ui: one JSON file per flow under <data_dir>/flows/.

A flow is one feature taken from a raw idea to dispatched runs (Dump -> PRD -> Issues -> Dispatch).
The browser owns the step logic (ui_static/flow.js); this module only stores what it hands over,
lists flows for the switcher, imports flows from sessions that ran before flows were stored, and
reads an Issues session's stream into per-issue progress rows.
"""

from __future__ import annotations

import calendar
import json
import os
import re
import secrets
import time

import ui_sessions
from shared import atomic_write_text, data_dir

_ID_RE = re.compile(r"f-[0-9]{14}-[0-9a-f]{6}")


class NotFound(Exception):
    pass
FIELDS = ("repo", "text", "folder", "prd", "issues", "sid", "dispatched")
MAX_TEXT = 20000
EMPTY_TTL = 86400  # a flow that never ran and holds no text is pruned a day after its last edit


def _dir() -> str:
    return os.path.join(data_dir(), "flows")


def _path(fid: str) -> str:
    if not isinstance(fid, str) or not _ID_RE.fullmatch(fid):
        raise NotFound(fid)
    return os.path.join(_dir(), fid + ".json")


def _now() -> float:
    return time.time()


def load(fid: str):
    try:
        with open(_path(fid), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, NotFound):
        return None
    return data if isinstance(data, dict) and data.get("id") == fid else None


def _save(flow: dict) -> dict:
    os.makedirs(_dir(), exist_ok=True)
    atomic_write_text(_path(flow["id"]), json.dumps(flow, indent=2))
    return flow


def _clean(body: dict) -> dict:
    """The editable fields of a request body, type-checked; unknown keys are ignored."""
    out = {}
    for k in FIELDS:
        if k not in body:
            continue
        v = body[k]
        if k == "dispatched":
            out[k] = v is True
        elif k == "issues":
            if not isinstance(v, list) or not all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in v):
                raise ValueError("issues must be a list of positive integers")
            out[k] = v[:100]
        else:
            if v is None:
                v = ""
            if not isinstance(v, str) or "\x00" in v or len(v) > MAX_TEXT:
                raise ValueError(f"{k} must be a string of at most {MAX_TEXT} characters")
            out[k] = v
    return out


def create(body: dict) -> dict:
    now = _now()
    fid = "f-" + time.strftime("%Y%m%d%H%M%S", time.gmtime(now)) + "-" + secrets.token_hex(3)
    flow = {"id": fid, "created": now, "updated": now, "archived": False, "sessions": [],
            "repo": "", "text": "", "folder": "", "prd": "", "issues": [], "sid": ""}
    flow.update(_clean(body))
    _attach(flow, flow["sid"])
    return _save(flow)


def _attach(flow: dict, sid: str) -> None:
    """Remember every session the flow ran, and mark the session as belonging to this flow."""
    if sid and sid not in flow["sessions"] and ui_sessions.load(sid) is not None:
        flow["sessions"].append(sid)
        ui_sessions.update(sid, flow_id=flow["id"])


def update(fid: str, body: dict) -> dict:
    flow = load(fid)
    if flow is None:
        raise NotFound(fid)
    flow.update(_clean(body))
    _attach(flow, flow["sid"])
    flow["updated"] = _now()
    return _save(flow)


def set_archived(fid: str, archived: bool) -> dict:
    flow = load(fid)
    if flow is None:
        raise NotFound(fid)
    flow["archived"] = archived
    return _save(flow)


def step(flow: dict) -> str:
    """Mirror of stepFromState in flow.js: the first step whose input is known but output isn't."""
    if flow.get("issues"):
        return "dispatch"
    if flow.get("prd"):
        return "issues"
    if flow.get("folder"):
        return "prd"
    return "dump"


def name(flow: dict) -> str:
    folder = (flow.get("folder") or flow.get("prd") or "").rstrip("/")
    if folder:
        last = folder.split("/")[-1]
        return folder.split("/")[-2] if last.lower().endswith(".md") and "/" in folder else last
    text = " ".join((flow.get("text") or "").split())
    return (text[:60] + "…") if len(text) > 60 else (text or "Untitled flow")


def _empty(flow: dict) -> bool:
    return not (flow["sessions"] or flow.get("text", "").strip() or flow.get("folder") or flow.get("prd") or flow.get("issues"))


def summary(flow: dict) -> dict:
    return {"id": flow["id"], "name": name(flow), "repo": flow.get("repo", ""), "step": step(flow),
            "updated": flow["updated"], "archived": flow.get("archived", False), "dispatched": flow.get("dispatched", False)}


def list_all(include_archived: bool = False, now=None) -> list:
    """Flows newest-first. Empty never-run flows are hidden, and pruned once they're a day old."""
    import_once()
    now = now or _now()
    try:
        names = os.listdir(_dir())
    except FileNotFoundError:
        return []
    out = []
    for n in names:
        if not (n.endswith(".json") and _ID_RE.fullmatch(n[:-5])):
            continue
        f = load(n[:-5])
        if f is None:
            continue
        if _empty(f):
            if now - f["updated"] > EMPTY_TTL:
                try:
                    os.remove(_path(f["id"]))
                except OSError:
                    pass
            continue
        if include_archived or not f.get("archived"):
            out.append(f)
    return sorted(out, key=lambda f: f["updated"], reverse=True)


# --------------------------------------------------------------------------- import (once)

_NEXT_RE = re.compile(r"^[ \t]*[`*]*→ next: (\S+)[ \t]*(.*?)[`*]*[ \t]*$", re.M)


def _family(command: str) -> str:
    m = re.match(r"/(?:[\w.-]+:)?([\w-]+)", command or "")
    return m.group(1) if m else ""


def _args(command: str) -> str:
    return (command.split(None, 1) + [""])[1].strip()


def _final_text(sid: str) -> str:
    """The text of a session's last result event, or ''."""
    text = ""
    try:
        with open(os.path.join(ui_sessions.session_dir(sid), "stream.jsonl"), "rb") as f:
            for line in f:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict) and ev.get("type") == "result" and isinstance(ev.get("result"), str):
                    text = ev["result"]
    except (OSError, ValueError):
        pass
    return text


def _next(sid: str):
    m = _NEXT_RE.findall(_final_text(sid))
    return (_family(m[-1][0]) or m[-1][0].lstrip("/").split(":")[-1], m[-1][1].strip()) if m else None


def _issue_numbers(text: str) -> list:
    nums = re.findall(r"issues/(\d+)", text) if "/" in text else re.findall(r"\d+", text)
    return [int(n) for n in dict.fromkeys(nums)]


def import_once() -> None:
    """One flow per /dump session that ran before flows were stored; later /prd and /gh-issue
    sessions whose argument matches the flow's folder or PRD path join it. Runs once per data dir."""
    marker = os.path.join(_dir(), ".imported")
    if os.path.exists(marker):
        return
    os.makedirs(_dir(), exist_ok=True)
    recs = sorted((r for r in ui_sessions.list_sessions() if not r.get("flow_id")),
                  key=lambda r: r.get("started_at") or "")
    flows: list = []
    for r in recs:
        fam, sid, arg = _family(r.get("command", "")), r.get("id"), _args(r.get("command", ""))
        if r.get("status") != "done":
            continue
        nxt = _next(sid)
        if fam == "dump":
            f = create({"repo": r.get("repo") or "", "text": arg})
            f["sessions"].append(sid)
            if nxt and nxt[0] == "prd" and nxt[1]:
                f["folder"] = nxt[1]
            elif nxt and nxt[0] == "gh-issue" and nxt[1]:
                f["prd"] = nxt[1]
            flows.append(f)
        elif fam == "prd":
            f = next((f for f in reversed(flows) if f["folder"] and f["folder"].rstrip("/") == arg.rstrip("/")), None)
            if f is not None:
                f["sessions"].append(sid)
                if nxt and nxt[0] == "gh-issue" and nxt[1]:
                    f["prd"] = nxt[1]
        elif fam == "gh-issue":
            f = next((f for f in reversed(flows) if f["prd"] and f["prd"] == arg), None)
            if f is not None:
                f["sessions"].append(sid)
                if nxt and nxt[0] == "herdr-dispatch":
                    f["issues"] = _issue_numbers(nxt[1])
    for f in flows:
        ts = (ui_sessions.load(f["sessions"][-1]) or {}).get("ended_at")
        f["updated"] = _epoch(ts) or f["updated"]
        for sid in f["sessions"]:
            ui_sessions.update(sid, flow_id=f["id"])
        _save(f)
    with open(marker, "w", encoding="utf-8") as m:
        m.write(f"{len(flows)}\n")


def _epoch(ts) -> float | None:
    if not isinstance(ts, str):
        return None
    try:
        return float(calendar.timegm(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")))
    except ValueError:
        return None


# --------------------------------------------------------------------------- issue progress

_TITLE_RE = re.compile(r"""gh issue create\b[^\n]*?--title[ =](?:"((?:[^"\\]|\\.)*)"|'([^']*)')""")
_EDIT_RE = re.compile(r"gh issue edit\s+#?(\d+)")
_URL_RE = re.compile(r"github\.com/[^/\s]+/[^/\s]+/issues/(\d+)")


def _result_text(block: dict) -> str:
    c = block.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(x.get("text", "") for x in c if isinstance(x, dict) and isinstance(x.get("text"), str))
    return ""


def issue_progress(lines) -> dict:
    """Per-issue rows from an Issues session's raw stream-json lines.

    States: creating -> created -> checking -> checked | fixing -> fixed; failed if a create errors.
    `reading` is true until the first `gh issue create` starts.
    """
    rows: list = []
    pending: dict = {}  # tool_use id -> ("create", [row, ...]) | ("check", row|None) | ("edit", row)
    reading = True

    def by_number(n):
        return next((r for r in rows if r["number"] == n), None)

    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
        content = msg.get("content") if isinstance(msg.get("content"), list) else []
        if ev.get("type") == "assistant":
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_use":
                    continue
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                cmd = inp.get("command") if isinstance(inp.get("command"), str) else ""
                if b.get("name") == "Bash" and "gh issue create" in cmd:
                    reading = False
                    new = [{"number": None, "title": (t[0] or t[1]).replace('\\"', '"'), "state": "creating"}
                           for t in _TITLE_RE.findall(cmd)] or [{"number": None, "title": "", "state": "creating"}]
                    rows.extend(new)
                    pending[b.get("id")] = ("create", new)
                elif b.get("name") == "Bash" and _EDIT_RE.search(cmd):
                    r = by_number(int(_EDIT_RE.search(cmd).group(1)))
                    if r:
                        r["state"] = "fixing"
                        pending[b.get("id")] = ("edit", r)
                elif b.get("name") in ("Agent", "Task") and "factcheck" in json.dumps(inp).lower():
                    ns = [int(n) for n in re.findall(r"(?:#|issues/)(\d+)", json.dumps(inp))]
                    r = next((by_number(n) for n in ns if by_number(n)), None) \
                        or next((x for x in rows if x["state"] == "created"), None)
                    if r:
                        r["state"] = "checking"
                    pending[b.get("id")] = ("check", r)
        elif ev.get("type") == "user":
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_result" or b.get("tool_use_id") not in pending:
                    continue
                kind, target = pending.pop(b.get("tool_use_id"))
                text, err = _result_text(b), b.get("is_error") is True
                if kind == "create":
                    nums = [int(n) for n in _URL_RE.findall(text)]
                    for i, r in enumerate(target):
                        if i < len(nums):
                            r["number"], r["state"] = nums[i], "created"
                        else:
                            r["state"] = "failed" if err or nums else r["state"]
                elif kind == "check" and target:
                    target["state"] = "fixing" if "ISSUES FOUND" in text.upper() else "checked"
                elif kind == "edit":
                    target["state"] = "failed" if err else "fixed"
    return {"reading": reading, "rows": rows}


def issues_for(fid: str):
    """Progress rows of the flow's latest Issues session; None when the flow doesn't exist."""
    flow = load(fid)
    if flow is None:
        return None
    sid = next((x for x in reversed(flow["sessions"])
                if _family((ui_sessions.load(x) or {}).get("command", "")) == "gh-issue"), None)
    return progress_for(sid) if sid else {"reading": True, "rows": []}


def progress_for(sid: str) -> dict:
    try:
        with open(os.path.join(ui_sessions.session_dir(sid), "stream.jsonl"), "rb") as f:
            return issue_progress(f)
    except (OSError, ValueError):
        return {"reading": True, "rows": []}


# --------------------------------------------------------------------------- notes (read-only)

MAX_NOTE = 2 * 1024 * 1024


def read_note(rel) -> dict:
    """A markdown note inside the configured vault. Read-only; paths escaping the vault are refused."""
    import ui_settings
    from urllib.parse import quote

    if not isinstance(rel, str) or not rel.strip() or "\x00" in rel or os.path.isabs(rel):
        raise ValueError("path must be a vault-relative path")
    rel = rel.strip()
    rel = rel[2:] if rel.startswith("./") else rel
    if not rel.lower().endswith(".md"):
        rel += ".md" if not os.path.splitext(rel)[1] else ""
    if not rel.lower().endswith(".md"):
        raise ValueError("only .md notes can be read")
    root = os.path.realpath(ui_settings.vault_dir())
    full = os.path.realpath(os.path.join(root, rel))
    if not full.startswith(root + os.sep):
        raise ValueError("path is outside the notes vault")
    try:
        if os.path.getsize(full) > MAX_NOTE:
            raise ValueError("note is too large to show")
        with open(full, encoding="utf-8", errors="replace") as f:
            text = f.read()
        mtime = os.path.getmtime(full)
    except FileNotFoundError:
        raise NotFound(rel) from None
    except IsADirectoryError:
        raise ValueError("path is a folder, not a note") from None
    vault = os.path.basename(root)
    return {"path": rel, "text": text, "mtime": mtime,
            "url": f"obsidian://open?vault={quote(vault)}&file={quote(rel[:-3])}"}
