"""UI settings: the named claude commands a run can be launched with (`claude`, `cc masum`, ...).

The plain `claude` command is built in: always first, never removable, but its label is the
user's to rename (stored as `claude_label`). Stored in <data_dir>/ui_settings.json. A command is exec'd directly (no shell): `cc` is only an
interactive-shell alias, so a leading `cc` is rewritten to the `cc-profile` script it points at.
"""

from __future__ import annotations

import copy
import json
import os
import re
import secrets
import shlex
import shutil

import dispatch
import repo_skills
import shared

DEFAULT_CMD = "claude"
DEFAULT_VAULT = os.path.join("~", "Documents", "notes")  # the `notes` vault /dump and /create-prd write to
MAX_COMMANDS = 20
SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
REVIEWER_RE = re.compile(r"^[A-Za-z0-9-]{1,39}$")  # a GitHub login, or copilot
CHANNEL_RE = re.compile(r"^[CGD][A-Z0-9]{8,12}$")  # a Slack channel id
SLACK_ID_RE = re.compile(r"^[UW][A-Z0-9]{8,12}$")  # a Slack member id
REVIEWER_ID_RE = re.compile(r"^r-[0-9a-f]{8}$")  # a saved reviewer, generated here
MAX_LISTED = 50  # entries in a saved list (Slack channels, reviewers)
GRIND_MODES = ("deep", "simple")  # simple: /pr-grind stops once the PR is approved
REVIEW_MODES = ("single", "loop")  # loop: /implement-issue re-reviews until a round finds nothing new
RUN_MODELS = ("opus", "sonnet", "haiku")  # aliases: they resolve to the latest model
RUN_EFFORTS = ("low", "medium", "high", "xhigh", "max")  # as dispatch_run
HARNESS_IDS = ("claude", "codex")  # the CLI an account runs; a command maps to one harness
MAX_MODELS = 20  # model names a Codex account lists
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}$")
HARNESSES = [  # read-only, sent with the settings; models: None means "from the account"
    {
        "id": "claude",
        "label": "Claude Code",
        "models": list(RUN_MODELS),
        "efforts": list(RUN_EFFORTS),
        "usage": True,
    },
    {"id": "codex", "label": "Codex", "models": None, "efforts": ["low", "medium", "high", "xhigh"], "usage": False},
]


def _path() -> str:
    return os.path.join(shared.data_dir(), "ui_settings.json")


def _stored() -> dict:
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def grind_mode() -> str:
    """deep (the default) or simple, for every /pr-grind loop; the skill reads it each round (`aiw grind-mode`)."""
    m = _stored().get("grind_mode")
    return m if m in GRIND_MODES else "deep"


def review_mode() -> str:
    """single (the default) or loop, for /implement-issue's local review (`aiw local-review`)."""
    m = _stored().get("review_mode")
    return m if m in REVIEW_MODES else "single"


def slack_channels(data=None) -> list:
    """The saved Slack channels list, [{id, name}]; malformed stored entries are skipped."""
    raw = (_stored() if data is None else data).get("slack_channels")
    return [
        {"id": c["id"], "name": c["name"]}
        for c in (raw if isinstance(raw, list) else [])
        if isinstance(c, dict)
        and isinstance(c.get("id"), str)
        and CHANNEL_RE.match(c["id"])
        and isinstance(c.get("name"), str)
    ]


def _clean_channels(chans) -> list:
    """Validate a sent slack_channels list; ValueError on the first bad entry."""
    if not isinstance(chans, list):
        raise ValueError("slack_channels must be a list")
    if len(chans) > MAX_LISTED:
        raise ValueError(f"at most {MAX_LISTED}")
    out, seen = [], set()
    for c in chans:
        cid = c.get("id") if isinstance(c, dict) else None
        cid = cid.strip() if isinstance(cid, str) else ""
        if not CHANNEL_RE.match(cid):
            raise ValueError("channel id must look like C0123ABCD")
        name = c.get("name")
        name = name.strip() if isinstance(name, str) else ""
        if not 1 <= len(name) <= 60:
            raise ValueError("channel name must be 1 to 60 characters")
        if cid in seen:
            raise ValueError(f"channel {cid} is already listed")
        seen.add(cid)
        out.append({"id": cid, "name": name})
    return out


def reviewers(data=None) -> list:
    """The saved reviewers list, [{id, name, slack_id, github_login}]; malformed stored entries are skipped."""
    raw = (_stored() if data is None else data).get("reviewers")
    keys = ("id", "name", "slack_id", "github_login")
    return [
        {k: r[k] for k in keys}
        for r in (raw if isinstance(raw, list) else [])
        if isinstance(r, dict) and all(isinstance(r.get(k), str) for k in keys) and REVIEWER_ID_RE.match(r["id"])
    ]


def _known(raw, ids: set) -> list:
    """The listed ids of a stored id list, in order ([] when it is not a list)."""
    return [i for i in raw if isinstance(i, str) and i in ids] if isinstance(raw, list) else []


def active_reviewers(data=None) -> list:
    """The global active set: ids of saved reviewers every repo without an override follows."""
    data = _stored() if data is None else data
    return _known(data.get("active_reviewers"), {r["id"] for r in reviewers(data)})


def _clean_reviewers(revs) -> list:
    """Validate a sent reviewers list, keeping sent ids and generating the missing ones; ValueError on a bad entry."""
    if not isinstance(revs, list):
        raise ValueError("reviewers must be a list")
    if len(revs) > MAX_LISTED:
        raise ValueError(f"at most {MAX_LISTED}")
    out, slack_ids, logins = [], set(), set()
    for r in revs:
        if not isinstance(r, dict):
            raise ValueError("a reviewer must be an object")
        name, sid, login = (
            r.get(k).strip() if isinstance(r.get(k), str) else "" for k in ("name", "slack_id", "github_login")
        )
        if not 1 <= len(name) <= 60:
            raise ValueError("reviewer name must be 1 to 60 characters")
        if not sid and not login:
            raise ValueError("add a Slack id or a GitHub login")
        if sid and not SLACK_ID_RE.match(sid):
            raise ValueError("Slack id must look like U0123ABCD")
        if login and not REVIEWER_RE.match(login):
            raise ValueError("not a GitHub login")
        if sid in slack_ids:
            raise ValueError(f"Slack id {sid} is already listed")
        if login.lower() in logins:
            raise ValueError(f"login {login.lower()} is already listed")
        slack_ids |= {sid} - {""}
        logins |= {login.lower()} - {""}
        rid = r.get("id")
        if rid is not None and not (isinstance(rid, str) and REVIEWER_ID_RE.match(rid)):
            raise ValueError("reviewer id must be r-<8 hex>")
        out.append({"id": rid, "name": name, "slack_id": sid, "github_login": login})
    sent = [r["id"] for r in out if r["id"]]
    if len(sent) != len(set(sent)):
        raise ValueError("duplicate reviewer id")
    taken = set(sent)
    for r in out:
        while not r["id"]:
            rid = "r-" + secrets.token_hex(4)
            if rid not in taken:
                r["id"] = rid
                taken.add(rid)
    return out


def _clean_ids(raw, ids: set, err: str) -> list:
    """Validate a sent list of reviewer ids (ValueError(err) when it is not one); deduped, order kept."""
    if not isinstance(raw, list) or not all(isinstance(i, str) for i in raw):
        raise ValueError(err)
    for i in raw:
        if i not in ids:
            raise ValueError(f"unknown reviewer id {i}")
    return list(dict.fromkeys(raw))


def use_jev() -> bool:
    """The one global Use jev switch (default on); read from the file on every call."""
    v = _stored().get("use_jev")
    return v if isinstance(v, bool) else True


def check_run(model, effort, cmd=None) -> None:
    """ValueError unless model / effort are None or one of the allowed values. On a Codex account cmd any
    non-empty text is accepted: what Codex does not offer falls back with a note (harness_codex). No cmd (the
    saved run_model/run_effort): Claude's lists."""
    if cmd and harness_of(cmd) == "codex":
        for name, v in (("model", model), ("effort", effort)):
            if v is not None and not (isinstance(v, str) and v and "\x00" not in v):
                raise ValueError(f"{name} must be a non-empty string")
        return
    if model is not None and model not in RUN_MODELS:
        raise ValueError(f"model must be one of {', '.join(RUN_MODELS)}")
    if effort is not None and effort not in RUN_EFFORTS:
        raise ValueError(f"effort must be one of {', '.join(RUN_EFFORTS)}")


def run_model():
    """The last-used model for a run (None: Claude's default)."""
    m = _stored().get("run_model")
    return m if m in RUN_MODELS else None


def run_effort():
    """The last-used effort for a run (None: Claude's default)."""
    e = _stored().get("run_effort")
    return e if e in RUN_EFFORTS else None


def vault_dir() -> str:
    """Absolute path of the Obsidian vault Flow reads notes from (read-only)."""
    return os.path.expanduser(_stored().get("vault_dir") or DEFAULT_VAULT)


def _repo(d) -> dict:
    d = d if isinstance(d, dict) else {}
    ch = d.get("slack_channel")
    return {
        "auto_grind": d.get("auto_grind") is True,
        "slack_channel": ch if isinstance(ch, str) else "",
        "reviewers": rv if isinstance(rv := d.get("reviewers"), list) and all(isinstance(i, str) for i in rv) else None,
    }


def _migrate_auto_grind(data: dict) -> bool:
    """Drop the legacy global auto_grind, seeding it onto every registered repo; True if it changed data."""
    if "auto_grind" not in data:
        return False
    legacy = data.pop("auto_grind") is True
    repos = data["repos"] = dict(data.get("repos") or {})
    for slug in dispatch.read_checkouts():
        repos.setdefault(slug, {"auto_grind": legacy})
    return True


def _channels_json() -> dict:
    """channels.json as a dict ({} when it is missing, corrupt or not an object)."""
    try:
        with open(os.path.join(shared.data_dir(), "channels.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _seed_reviewers(data: dict) -> dict:
    """Seed slack_channels, reviewers and active_reviewers from the old settings (FR-9) and drop each
    repo's old `reviewer`. Built from the stored dict and channels.json only, so it needs no lock."""
    cj = _channels_json()
    mapped = cj.get("channels") if isinstance(cj.get("channels"), dict) else {}
    raw = data.get("repos")
    repos = {k: v for k, v in (raw if isinstance(raw, dict) else {}).items() if isinstance(v, dict)}
    chans, revs, taken = [], [], set()

    def add_channel(cid):
        cid = cid.strip() if isinstance(cid, str) else ""
        if CHANNEL_RE.match(cid) and len(chans) < MAX_LISTED and all(c["id"] != cid for c in chans):
            chans.append({"id": cid, "name": cid})

    def add_reviewer(name, sid, login) -> str:
        rid = "r-" + secrets.token_hex(4)
        while rid in taken:
            rid = "r-" + secrets.token_hex(4)
        taken.add(rid)
        revs.append({"id": rid, "name": name, "slack_id": sid, "github_login": login})
        return rid

    for r in repos.values():  # repos' picks first, so they always make the list
        add_channel(r.get("slack_channel"))
    for cid in mapped.values():
        add_channel(cid)
    bot, label = cj.get("bot_uid"), cj.get("bot_label")
    label = label.strip()[:60] if isinstance(label, str) else ""  # stripped: every save re-validates the name
    active = [add_reviewer(label or "Review bot", bot, "")] if isinstance(bot, str) and SLACK_ID_RE.match(bot) else []
    for slug, r in repos.items():
        login = r.pop("reviewer", None)
        login = login.strip() if isinstance(login, str) else ""
        rid = None
        if REVIEWER_RE.match(login):
            rid = next((x["id"] for x in revs if x["github_login"].lower() == login.lower()), None)
            if rid is None and len(revs) < MAX_LISTED:
                rid = add_reviewer(login, "", login)
        ch = r.get("slack_channel")
        has_channel = (isinstance(ch, str) and ch.strip()) or mapped.get(slug)
        r["reviewers"] = [rid] if rid and not has_channel else None
    data["slack_channels"], data["reviewers"], data["active_reviewers"] = chans, revs, active
    return data


def _write(data: dict) -> None:
    try:
        shared.atomic_write_text(_path(), json.dumps(data, indent=2))
    except OSError:  # ponytail: read-only data dir; seeded ids may differ between loads until a write works
        pass


def _migrate(data: dict, persist: bool = True) -> dict:
    """Run the one-time migrations on the stored settings. persist=False writes nothing and takes no lock
    (validate() runs inside save()'s lock, which is not re-entrant; save() writes the result)."""
    changed = _migrate_auto_grind(data)
    if "reviewers" in data or not persist:
        if "reviewers" not in data:
            _seed_reviewers(data)
        elif changed and persist:
            _write(data)  # ponytail: unlocked; the legacy migration is idempotent, so a race rewrites the same result
        return data
    with shared.json_lock(_path()):  # re-check under the lock, so two racing first loads give one set of ids
        try:
            with open(_path(), encoding="utf-8") as f:
                fresh = json.load(f)
        except FileNotFoundError:
            fresh = {}
        except (OSError, ValueError):
            return data  # corrupt: never overwrite it here; save() moves it aside
        if not isinstance(fresh, dict):
            return data
        if "reviewers" in fresh:  # another process migrated
            return fresh
        _migrate_auto_grind(fresh)
        _write(_seed_reviewers(fresh))
    return fresh


def repo_settings(slug: str) -> dict:
    """Per-repo settings with defaults, plus its issues' grinding switches."""
    d = _migrate(_stored())
    return {
        **_repo((d.get("repos") or {}).get(slug)),
        "issue_grind": _issue_grind().get(str(slug).lower(), {}),
    }


def _issue_grind_path() -> str:
    # its own file: save() rewrites ui_settings.json from the Settings form, which never sends these
    return os.path.join(shared.data_dir(), "issue_grind.json")


def _issue_grind() -> dict:
    """{owner/repo lowercased: {issue: bool}}: issues whose grinding was switched in the UI."""
    try:
        with open(_issue_grind_path(), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        k: {int(n): v for n, v in m.items() if str(n).isdigit() and isinstance(v, bool)}
        for k, m in raw.items()
        if isinstance(m, dict)
    }


def set_issue_grind(slug: str, issue: int, on: bool) -> dict:
    """Switch one issue's grinding; the other issues keep following the repo's auto_grind."""
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        raise ValueError("repo must be owner/repo")
    if type(issue) is not int or issue < 1 or type(on) is not bool:
        raise ValueError("issue must be a number and on must be true or false")
    path = _issue_grind_path()
    with shared.json_lock(path):
        shared.backup_if_corrupt(path)
        all_ = _issue_grind()
        all_.setdefault(slug.lower(), {})[issue] = on
        shared.atomic_write_text(path, json.dumps(all_, indent=2))
    return all_[slug.lower()]


def load(persist: bool = True) -> dict:
    data = _migrate(_stored(), persist)
    stored_repos = data.get("repos") if isinstance(data.get("repos"), dict) else {}
    registered = dispatch.read_checkouts()
    slugs = [*registered, *(k for k in stored_repos if k not in registered)]
    alias = data.get("claude_label")
    alias = alias if isinstance(alias, str) and alias.strip() else DEFAULT_CMD
    cmds = [{"label": alias, "cmd": DEFAULT_CMD, "builtin": True, "harness": "claude"}]
    cmds += [
        _account(c)
        for c in data.get("commands") or []
        if isinstance(c, dict)
        and isinstance(c.get("label"), str)
        and isinstance(c.get("cmd"), str)
        and c["label"] != alias
    ]
    default = data.get("default")
    listed = {c["id"] for c in slack_channels(data)}
    repos = {k: _repo(stored_repos.get(k)) for k in slugs}
    rids = {r["id"] for r in reviewers(data)}
    for r in repos.values():
        r["channel_invalid"] = bool(r["slack_channel"]) and r["slack_channel"] not in listed  # read-only, never stored
        if r["reviewers"] is not None:
            r["reviewers"] = _known(r["reviewers"], rids)
    return {
        "commands": cmds,
        "default": default if any(c["label"] == default for c in cmds) else alias,
        "repos": repos,
        "slack_channels": slack_channels(data),
        "reviewers": reviewers(data),
        "active_reviewers": active_reviewers(data),
        "vault_dir": vault_dir(),
        "grind_mode": grind_mode(),
        "review_mode": review_mode(),
        "use_jev": use_jev(),
        "jev_installed": shutil.which("jev") is not None,  # read-only: validate() never stores it
        "personal_plugin": repo_skills.personal_plugin_installed(),  # read-only, like jev_installed
        "run_model": run_model(),
        "run_effort": run_effort(),
        "harnesses": copy.deepcopy(HARNESSES),  # read-only: validate() never stores it
    }


def _account(c: dict) -> dict:
    """A stored account as loaded: no or an unknown harness is claude; a Codex one lists its models."""
    harness = c.get("harness") if c.get("harness") in HARNESS_IDS else "claude"
    acc = {"label": c["label"], "cmd": c["cmd"], "harness": harness}
    if harness == "codex":
        models = c.get("models")
        ok = [m for m in models if isinstance(m, str) and MODEL_RE.match(m)] if isinstance(models, list) else []
        acc["models"] = ok[:MAX_MODELS]  # hand-edited junk is dropped, so a partial save still validates
    return acc


def _clean_models(models) -> list:
    """Validate a Codex account's model names; ValueError when any is bad."""
    if (
        not isinstance(models, list)
        or len(models) > MAX_MODELS
        or not all(isinstance(m, str) and MODEL_RE.match(m) for m in models)
    ):
        raise ValueError(f"models must be a list of at most {MAX_MODELS} model names")
    return models


def argv(cmd: str) -> list:
    """Absolute argv prefix for a command string; ValueError if it is empty or not on PATH."""
    if not isinstance(cmd, str) or "\x00" in cmd:
        raise ValueError("command must be a string")
    try:
        toks = shlex.split(cmd)
    except ValueError as e:
        raise ValueError(f"cannot parse command: {e}") from None
    if not toks:
        raise ValueError("command must not be empty")
    if toks[0] == "cc":
        toks[0] = "cc-profile"
    exe = shutil.which(toks[0])
    if exe is None:
        raise ValueError(f"{toks[0]!r} not found on PATH")
    return [exe, *toks[1:]]


def validate(body) -> dict:
    """Return the cleaned settings dict, or raise ValueError."""
    full = isinstance(body, dict) and "commands" in body  # Settings > Accounts: commands must be unique
    if isinstance(body, dict) and "commands" not in body:  # a partial save (a board's per-repo PUT) keeps the rest
        cur = load(persist=False)
        body = {"commands": cur["commands"], "default": cur["default"], **body}
    if not isinstance(body, dict) or not isinstance(body.get("commands"), list):
        raise ValueError("commands must be a list")
    if len(body["commands"]) > MAX_COMMANDS:
        raise ValueError(f"at most {MAX_COMMANDS} commands")
    builtin = [c for c in body["commands"] if isinstance(c, dict) and c.get("builtin") is True]
    if len(builtin) > 1:
        raise ValueError("only one built-in command")
    alias = builtin[0].get("label") if builtin else DEFAULT_CMD
    if not isinstance(alias, str) or not alias.strip() or len(alias) > 40:
        raise ValueError("label must be a non-empty string of at most 40 characters")
    alias = alias.strip()
    cmds, seen, used = [], {alias}, {DEFAULT_CMD}
    for c in body["commands"]:
        if isinstance(c, dict) and c.get("builtin") is True:
            if "harness" in c and c["harness"] not in HARNESS_IDS:
                raise ValueError("harness must be claude or codex")
            if c.get("harness", "claude") != "claude":
                raise ValueError("the built-in account is always claude")
            continue  # its command is always `claude`; only the label is editable
        label = c.get("label") if isinstance(c, dict) else None
        cmd = c.get("cmd") if isinstance(c, dict) else None
        if not isinstance(label, str) or not label.strip() or len(label) > 40:
            raise ValueError("label must be a non-empty string of at most 40 characters")
        label = label.strip()
        if label in seen:
            raise ValueError(f"duplicate label: {label!r}")
        seen.add(label)
        if not isinstance(cmd, str) or len(cmd) > 200:
            raise ValueError("cmd must be a string of at most 200 characters")
        argv(cmd)
        harness = c.get("harness", "claude")
        if harness not in HARNESS_IDS:
            raise ValueError("harness must be claude or codex")
        cmd = cmd.strip()
        if full and cmd in used:
            raise ValueError("each account needs its own command")
        used.add(cmd)
        acc = {"label": label, "cmd": cmd, "harness": harness}
        if harness == "codex":
            acc["models"] = _clean_models(c.get("models", []))
        cmds.append(acc)
    default = body.get("default")
    if default is not None and default not in seen:
        raise ValueError("default must be one of the labels")
    vault = body.get("vault_dir", _stored().get("vault_dir"))  # a save that omits it keeps the stored one
    if vault is not None:
        if not isinstance(vault, str) or "\x00" in vault or len(vault) > 500:
            raise ValueError("vault_dir must be a path of at most 500 characters")
        vault = vault.strip() or None
        if vault and not os.path.isabs(os.path.expanduser(vault)):
            raise ValueError("vault_dir must be an absolute path (or start with ~)")
    mode = body.get("grind_mode", grind_mode())  # a save that omits it keeps the stored one
    if mode not in GRIND_MODES:
        raise ValueError("grind_mode must be deep or simple")
    rmode = body.get("review_mode", review_mode())  # a save that omits it keeps the stored one
    if rmode not in REVIEW_MODES:
        raise ValueError("review_mode must be single or loop")
    jev = body.get("use_jev", use_jev())  # a save that omits it keeps the stored one
    if type(jev) is not bool:
        raise ValueError("use_jev must be true or false")
    run_m, run_e = body.get("run_model", run_model()), body.get("run_effort", run_effort())
    check_run(run_m, run_e)
    stored = _migrate(_stored(), persist=False)  # a pre-upgrade file: the seeded lists are the stored ones
    old_ids = {c["id"] for c in slack_channels(stored)}
    chans = _clean_channels(body.get("slack_channels", slack_channels(stored)))  # omitted: keep the stored one
    ids = {c["id"] for c in chans}
    revs = _clean_reviewers(body.get("reviewers", reviewers(stored)))  # a save that omits it keeps the stored one
    rids = {r["id"] for r in revs}
    if "active_reviewers" in body:
        active = _clean_ids(body["active_reviewers"], rids, "active_reviewers must be a list of ids")
    else:  # kept, minus the reviewers this save removes
        active = _known(stored.get("active_reviewers"), rids)
    sent = body.get("repos", {})
    if not isinstance(sent, dict):
        raise ValueError("repos must be an object")
    kept = {}
    for slug, r in (stored.get("repos") or {}).items():
        if SLUG_RE.match(str(slug)):
            kept[slug] = r
        else:
            shared.warn(f"ui_settings: dropped stored repo with invalid slug {slug!r}")
    repos = {**kept, **sent}  # an entry replaces that repo's; the others stay
    clean_repos = {}
    for slug, r in repos.items():
        if not SLUG_RE.match(str(slug)) or not isinstance(r, dict):
            raise ValueError("repos must map owner/repo to an object")
        ch = r.get("slack_channel", "")
        if not isinstance(ch, str) or len(ch) > 100:
            raise ValueError("slack_channel must be a string of at most 100 characters")
        if slug in sent and "reviewers" in r:
            rv_ids = (
                None
                if r["reviewers"] is None
                else _clean_ids(r["reviewers"], rids, "reviewers must be a list of ids or null")
            )
        else:  # the Repositories table omits it: keep the stored override, minus removed reviewers
            rv_ids = _repo(kept.get(slug))["reviewers"]
            rv_ids = None if rv_ids is None else _known(rv_ids, rids)
        ch = ch.strip()
        if ch and ch not in ids:
            if ch in old_ids:
                raise ValueError(f"channel {ch} is used by {slug}")
            if ch != (kept.get(slug) or {}).get("slack_channel"):  # an unchanged legacy value stays
                raise ValueError(f"slack_channel {ch} is not a listed channel")
        clean_repos[slug] = {
            "auto_grind": r.get("auto_grind") is True,
            "slack_channel": ch,
            "reviewers": rv_ids,
        }
    return {
        "claude_label": alias,
        "commands": cmds,
        "default": None if default == alias else default,
        "repos": clean_repos,
        "slack_channels": chans,
        "reviewers": revs,
        "active_reviewers": active,
        "vault_dir": vault,
        "grind_mode": mode,
        "review_mode": rmode,
        "use_jev": jev,
        "run_model": run_m,
        "run_effort": run_e,
    }


def save(body) -> dict:
    with shared.json_lock(_path()):
        shared.backup_if_corrupt(_path())
        shared.atomic_write_text(_path(), json.dumps(validate(body), indent=2))
    return load()


def default_cmd() -> str:
    s = load()
    return next((c["cmd"] for c in s["commands"] if c["label"] == s["default"]), DEFAULT_CMD)


def harness_of(cmd: str) -> str:
    """The harness of the account whose command is cmd; claude when no account holds it."""
    acc = next((c for c in load(persist=False)["commands"] if c["cmd"] == cmd), {})
    return acc.get("harness", "claude")


def models_of(cmd: str) -> list:
    """A Codex account's model names; [] for a Claude account or an unknown command."""
    acc = next((c for c in load(persist=False)["commands"] if c["cmd"] == cmd), {})
    return list(acc.get("models") or []) if acc.get("harness") == "codex" else []


def check_login(cmd: str) -> dict:
    """The account's harness checks its login; {"ok": bool, "message": str}. Never raises."""
    import harness  # noqa: PLC0415 - harness imports this module

    try:
        ad = harness.for_cmd(cmd)
    except ValueError as e:  # a harness with no adapter yet (codex before #878)
        return {"ok": False, "message": str(e)}
    return ad.check_login(cmd)


def config_dir(cmd: str) -> str:
    """Claude config dir an account command runs under (cc-profile <p> -> ~/.claude-profiles/<p>)."""
    toks = shlex.split(cmd)
    if toks[:1] in (["cc"], ["cc-profile"]) and len(toks) > 1:
        return os.path.expanduser(f"~/.claude-profiles/{toks[1]}")
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
