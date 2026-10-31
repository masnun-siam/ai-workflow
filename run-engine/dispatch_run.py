"""Dispatch engine: an epic's child issues run as lanes, in dependency order, up to a cap. Stdlib only.

A lane goes queued -> implementing -> grinding -> merge_gate -> (awaiting_merge) -> followups -> closed,
with conflict_fix as a detour from the gate and skipped as a dead end (needs refine, or the user's skip).
Flags on a lane: `paused` (user, or `paused_by: "dispatch"` for the dispatch's Pause > Now), `held` (CI red, grind paused or ended: needs you), `needs_you` (the lane
session waits on a human or stopped), `limited_until` (Claude usage limit), `hold_merge` / `force_merge`.

`step(lane, facts, settings, now)` is pure: facts in, (lane patch, actions) out. Facts per lane, built by
the caller from the board snapshot, the grind index and the runner:

    {"issue_open": bool, "refined": bool, "blockers_open": [key],   # blockers still open on GitHub
     "pr": None | {"n", "url", "draft", "state": OPEN|MERGED|CLOSED, "ci": success|failure|pending|none,
                   "conflict": bool, "approved": bool, "sha": head commit | None},
     "grind": None | {"state": idle|running|paused|done, "reason": str, "due": str | None},  # due: a token
     "slack": bool,                                  # the repo has a grind channel; False skips grinding
     "solo": bool,                                   # the repo is the gh user's own: no approval needed
     "agent": working|idle|blocked|gone|None, "limited_until": float | None}

Actions: ("send", text), ("merge", pr_n), ("close",), ("continue",), ("notify", kind, text).
`tick(d, facts, runner, merge, now)` steps every lane, runs the actions, launches what is startable and
saves. The record lives at <data_dir>/dispatches/<id>.json; GitHub stays the truth for issues and PRs.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import time
import uuid

from shared import atomic_write_text, data_dir, run

ACTIVE = ("implementing", "grinding", "merge_gate", "conflict_fix", "awaiting_merge", "followups")
DEFAULTS = {
    "max": 2,
    "grind": "full",  # off | simple | full (pr-grind's deep)
    "ci": "wait",  # wait | defer (CI blocks only the merge) | ignore (CI never blocks)
    "auto_merge": False,
    "feature_branch": None,  # every lane's base when set; else the issue's own
    "base_branch": None,  # where the dispatch's work lands; empty = today's behaviour. Fixed at start
    "model": None,
    "effort": None,
    "account": None,  # a saved account label; None = the Settings default. Headless lanes only
}
_BRANCH = r"[A-Za-z0-9._/-]{1,100}"
GRIND_MODES = ("off", "simple", "full")
CI_MODES = ("wait", "defer", "ignore")
MERGE_RETRY_SECONDS = 300  # the board lags a merge; don't call gh pr merge twice in this window
IDLE_GRACE_SECONDS = 180  # a session that just ended may have a PR the board has not seen yet
LIMIT_BUFFER_SECONDS = 60
MAX_EVENTS = 500
CONTINUE = "Continue from where you were stopped."

END_ACTIONS = ("open-pr", "qa", "grind-pr")


# --------------------------------------------------------------------------- prompts


def implement_prompt(n: int, base, pr=None, ci="wait") -> str:
    notes = [f"PR #{pr} is already open for it: continue that PR on its branch, don't start over"] if pr else []
    notes += [f"base branch {base}: branch from it, open the PR into it"] if base else []
    if ci != "wait":
        notes.append(f"CI mode {ci}: mark the PR ready after local checks and review pass; do not wait for CI")
    return f"/ai-workflow:implement-issue {n}" + (f" ({'; '.join(notes)})" if notes else "")


LANE_GRIND = " -- dispatch lane: re-arm the headless way (write next-poll, end the turn; no Monitor, no ScheduleWakeup)"


SKIP_CI_REPLY = "Skip CI for now, complete the grind, then come back and fix the CI"


def grind_prompt(pr_url: str, channel=None, lane=True, ci="wait") -> str:
    """A lane's grind ends each round like a headless one: the engine types the next round into the lane."""
    ch = str(channel or "").strip()
    return (
        f"/ai-workflow:pr-grind {pr_url}"
        + (f" --channel {ch}" if ch.replace("_", "").isalnum() else "")
        + (LANE_GRIND + (" " + SKIP_CI_REPLY if ci != "wait" else "") if lane else "")
    )


def qa_prompt(epic: str, branch) -> str:
    return (
        f"Final QA for epic {epic}"
        + (f" on branch {branch}" if branch else "")
        + ": run /ai-workflow:verifier-locally "
        "against every child issue's acceptance criteria, then test the whole feature end to end in the running app "
        "with the browser tool. File each bug you find with /ai-workflow:create-tasks as a child issue of the epic."
    )


def conflict_prompt(pr: int, base) -> str:
    return (
        f"PR #{pr} conflicts with {base or 'its base'}. Merge origin/{base or '<base>'} into the branch, resolve the "
        "conflicts, re-run the checks, push and wait for CI to be green. Don't mark anything else or merge."
    )


def ci_fix_prompt(pr) -> str:
    return f"CI is red on PR #{pr}. Read the failing job's log, fix it locally, re-run the checks, push and wait for green."


def lane_base(lane: dict, settings: dict):
    """The base a lane branches from and opens its PR into: the feature branch, else the base branch, else the issue's own."""
    return settings.get("feature_branch") or settings.get("base_branch") or lane.get("base")


def followups_prompt(n: int, pr: int, base) -> str:
    tail = f" Close #{n} if it is still open." if base else ""
    return f"PR #{pr} for issue #{n} is merged. Run implement-issue's 'After the pull request is merged' steps for #{n}.{tail}"


def stage_prompt(lane: dict, settings: dict, pr_url=None):
    """What a fresh session for the lane's current stage is told; None when the stage needs no session."""
    base = lane_base(lane, settings)
    ci = settings.get("ci", "wait")
    return {
        "implementing": lambda: implement_prompt(lane["n"], base, lane.get("pr"), ci),
        "grinding": lambda: grind_prompt(pr_url or "", lane.get("channel"), ci=ci),
        "conflict_fix": lambda: conflict_prompt(lane.get("pr"), base),
        "followups": lambda: followups_prompt(lane["n"], lane.get("pr"), base),
    }.get(lane["stage"], lambda: None)()


# --------------------------------------------------------------------------- the lane machine


def key(repo: str, n: int) -> str:
    return f"{repo}#{n}"


def _grind_on(settings: dict, facts: dict) -> bool:
    return settings.get("grind", "full") != "off" and bool(facts.get("slack"))


def _gate(lane: dict, facts: dict, settings: dict):
    """None when the PR may merge, else why not."""
    pr, g = facts.get("pr") or {}, facts.get("grind") or {}
    mode = settings.get("ci", "wait")
    if mode == "wait" and pr.get("ci") != "success":
        return "CI is not green"
    if mode == "defer" and pr.get("ci") not in ("success", "none"):
        return "waiting for green CI (defer)"
    if not pr.get("approved") and not facts.get("solo"):  # nobody can approve a PR on your own repo
        return "no approving review"
    if _grind_on(settings, facts) and not (g.get("state") == "done" and "approved" in (g.get("reason") or "")):
        return "grind is not done"
    return None


def step(lane: dict, facts: dict, settings: dict, now: float) -> tuple:
    stage = lane["stage"]
    if stage not in ACTIVE or lane.get("paused"):
        return {}, []
    pr = facts.get("pr") or {}
    agent = facts.get("agent")
    base = lane_base(lane, settings)
    ci = settings.get("ci", "wait")
    free = ci != "wait"  # defer / ignore: a lane does not wait for CI before the gate
    patch: dict = {}
    acts: list = []

    def to(s, why=None):
        patch.update(stage=s, needs_you=None, held=None, idle_since=None)
        if why:
            acts.append(("notify", s, why))

    # Claude usage limit: wait, then nudge once the reset has passed
    lim = facts.get("limited_until")
    if lim and lim > now:
        return ({"limited_until": lim} if lane.get("limited_until") != lim else {}), []
    if lane.get("limited_until"):
        patch["limited_until"] = None
        if now >= lane["limited_until"] + LIMIT_BUFFER_SECONDS:
            acts.append(("continue",))
        return patch, acts

    if stage != "followups" and pr.get("state") == "MERGED":  # merged here, or by a human at any stage
        to("followups")
        patch["pr"] = pr.get("n")
        acts.append(("send", followups_prompt(lane["n"], pr.get("n"), base)))
        return patch, acts

    if (
        agent == "gone"
        and stage in ("implementing", "grinding", "conflict_fix", "followups")
        and not (stage == "followups" and not facts.get("issue_open"))
    ):
        if lane.get("needs_you") != "the lane session is gone":
            patch["needs_you"] = "the lane session is gone"
            acts.append(("notify", "needs_you", "the lane session is gone: retry it"))
        return patch, acts

    if stage == "implementing":
        ready = pr.get("state") == "OPEN" and not pr.get("draft")
        if pr.get("state") == "OPEN" and pr.get("n") != lane.get("pr"):
            patch["pr"] = pr["n"]  # tracked as soon as it exists: a retry continues it instead of starting over
        if not free and ready and pr.get("ci") == "failure" and agent in ("idle", None):
            if lane.get("held") != "CI is red":
                patch.update(held="CI is red", needs_you=None, idle_since=None)
                acts.append(("notify", "held", f"CI is red on PR #{pr['n']}"))
            return patch, acts
        if lane.get("held"):  # CI re-ran, or the session is back on it
            patch["held"] = None
        if ready and (free or pr.get("ci") == "success"):
            if _grind_on(settings, facts):
                to("grinding")
                acts.append(("send", grind_prompt(pr["url"], facts.get("channel"), ci=ci)))
            else:
                to("merge_gate")
            return patch, acts
        return _waits(lane, agent, patch, acts, "stopped without a ready PR", now)

    if stage == "grinding":
        g = facts.get("grind") or {}
        if not _grind_on(settings, facts):  # switched off mid-run
            to("merge_gate")
        elif g.get("state") == "done":
            if "approved" in (g.get("reason") or ""):
                to("merge_gate")
            elif lane.get("held") != (why := f"grind ended: {g.get('reason') or '?'}"):
                patch["held"] = why
                acts.append(("notify", "held", why))
        elif g.get("state") == "paused":
            if lane.get("held") != (why := f"grind paused: {g.get('reason') or '?'}"):
                patch["held"] = why
                acts.append(("notify", "held", why))
        else:
            if lane.get("held"):
                patch["held"] = None
            if g.get("due") and g["due"] != lane.get("nudged") and agent in ("idle", None):
                patch["nudged"] = g["due"]
                acts.append(("send", grind_prompt(pr.get("url") or "", facts.get("channel"), ci=ci)))
            elif agent == "blocked" and not lane.get("needs_you"):
                patch["needs_you"] = "the grind waits on you"
                acts.append(("notify", "needs_you", patch["needs_you"]))
            elif agent != "blocked" and lane.get("needs_you"):
                patch["needs_you"] = None
        return patch, acts

    if stage in ("merge_gate", "awaiting_merge"):
        if pr.get("conflict"):
            to("conflict_fix")
            acts.append(("send", conflict_prompt(pr.get("n"), base)))
            return patch, acts
        if pr.get("ci") == "failure" and ci == "wait":
            if lane.get("held") != "CI is red":
                patch["held"] = "CI is red"
                acts.append(("notify", "held", f"CI is red on PR #{pr.get('n')}"))
            return patch, acts
        if lane.get("held"):
            patch["held"] = None
        if pr.get("ci") == "failure" and ci == "defer" and lane.get("ci_fixed") != pr.get("sha"):
            patch["ci_fixed"] = pr.get("sha")  # once per red head commit, like `nudged` for a grind round
            acts.append(("send", ci_fix_prompt(pr.get("n"))))
        why = None if lane.get("force_merge") else _gate(lane, facts, settings)
        if why:
            if stage == "awaiting_merge":
                to("merge_gate")
            patch["gate"] = why
            return patch, acts
        patch["gate"] = None
        if lane.get("force_merge") or (settings.get("auto_merge") and not lane.get("hold_merge")):
            if lane.get("merge_at") is None or now - lane["merge_at"] >= MERGE_RETRY_SECONDS:
                patch["merge_at"] = now
                acts.append(("merge", pr.get("n")))
        elif stage != "awaiting_merge":
            to("awaiting_merge", f"PR #{pr.get('n')} is ready to merge")
        return patch, acts

    if stage == "conflict_fix":
        if not pr.get("conflict") and (free or pr.get("ci") == "success") and agent in ("idle", None):
            to("merge_gate")
            return patch, acts
        if pr.get("conflict"):
            return _waits(lane, agent, patch, acts, "stopped with the conflict unresolved", now)
        return patch, acts

    # followups
    if not facts.get("issue_open") and agent in ("idle", "gone", None):
        to("closed")
        patch["ended_at"] = now
        acts.append(("close",))
        return patch, acts
    return _waits(lane, agent, patch, acts, "followups stopped with the issue still open", now)


def _waits(lane, agent, patch, acts, idle_why, now):
    """A blocked session needs the user at once; an idle one only after IDLE_GRACE_SECONDS, so the board
    can catch up with what it just did (a PR marked ready, an issue closed)."""
    if agent == "idle":
        since = lane.get("idle_since") or now
        if lane.get("idle_since") is None:
            patch["idle_since"] = now
    elif lane.get("idle_since") is not None:
        patch["idle_since"] = None
    idle_long = agent == "idle" and now - since >= IDLE_GRACE_SECONDS
    why = "waiting on you" if agent == "blocked" else idle_why if idle_long else None
    if why != lane.get("needs_you"):
        patch["needs_you"] = why
        if why:
            acts.append(("notify", "needs_you", why))
    return patch, acts


# --------------------------------------------------------------------------- scheduling


def startable(d: dict, facts: dict) -> list:
    """Queued lanes whose blockers are all closed and done, by issue number, up to the free slots."""
    if d["state"] != "running":
        return []
    lanes = d["lanes"]
    now = time.time()
    if any((x.get("limited_until") or 0) > now for x in lanes.values()):
        return []
    free = d["settings"]["max"] - sum(1 for x in lanes.values() if x["stage"] in ACTIVE)
    out = []
    for k, x in sorted(lanes.items(), key=lambda kv: (kv[1]["n"], kv[0])):
        if free <= 0:
            break
        if x["stage"] != "queued" or x.get("paused"):
            continue
        if any(lanes.get(b, {}).get("stage", "closed") != "closed" for b in x.get("deps", [])):
            continue
        if k not in facts:  # never launch on a guess: wait for the repo's first fresh poll
            continue
        if any(b not in lanes for b in facts[k].get("blockers_open", [])):
            continue  # a blocker outside this dispatch is still open
        out.append(k)
        free -= 1
    return out


def sync_lanes(d: dict, children: list) -> list:
    """Add new epic children as lanes; a 'needs refine' lane is queued once refined. Returns added keys.
    children: [{"repo", "n", "title", "refined", "deps": [key], "base"}]."""
    added = []
    was_done = d.get("state") == "done"
    added_work = False
    for c in children:
        k = key(c["repo"], c["n"])
        x = d["lanes"].get(k)
        if x is None:
            d["lanes"][k] = {
                "repo": c["repo"],
                "n": c["n"],
                "title": c.get("title", ""),
                "deps": list(c.get("deps", [])),
                "base": c.get("base"),
                "stage": "queued" if c.get("refined") else "skipped",
                "skip_reason": None if c.get("refined") else "needs refine",
                "handle": None,
                "pr": None,
            }
            added.append(k)
        else:
            # a re-read lists only blockers still open: keep the ones already known, or the graph loses its shape
            x["deps"] = sorted(set(x["deps"]) | set(c.get("deps", [])))
            if x["stage"] == "skipped" and x.get("skip_reason") == "needs refine" and c.get("refined"):
                x.update(stage="queued", skip_reason=None)
                added_work = True
    if was_done and (added or added_work):  # QA filed new children: pause until the user refines them and resumes
        d.update(state="paused", ended_at=None)
        event(d, None, "paused", "new issues joined: refine them, then resume")
    return added


def plan(children: list) -> dict:
    """Preview: waves (lanes that can run together), warnings. No side effects."""
    lanes = {key(c["repo"], c["n"]): c for c in children}
    warnings = [f"{k}: needs refine" for k, c in lanes.items() if not c.get("refined")]
    left = {k for k, c in lanes.items() if c.get("refined")}
    done: set = set()
    waves = []
    while left:
        wave = sorted(
            (k for k in left if all(b in done or b not in lanes for b in lanes[k].get("deps", []))),
            key=lambda k: (lanes[k]["n"], k),
        )
        if not wave:
            warnings.append("dependency cycle or blocked by an unrefined issue: " + ", ".join(sorted(left)))
            break
        waves.append(wave)
        done |= set(wave)
        left -= set(wave)
    return {"waves": waves, "warnings": warnings}


# --------------------------------------------------------------------------- store


def _dir() -> str:
    p = os.path.join(data_dir(), "dispatches")
    os.makedirs(p, exist_ok=True)
    return p


def _path(did: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{12}", did or ""):
        raise ValueError(f"bad dispatch id: {did!r}")
    return os.path.join(_dir(), did + ".json")


def issues_title(keys: list) -> str:
    nums = sorted(int(k.rsplit("#", 1)[1]) for k in keys)
    t = "Small changes: " + ", ".join(f"#{n}" for n in nums[:3])
    return t + f" +{len(nums) - 3} more" if len(nums) > 3 else t


def _no_feature_branch(s: dict) -> None:
    if s.get("feature_branch") is not None:
        raise ValueError("an issue-list dispatch has no feature branch")


class Conflict(Exception):
    """A picked issue is already a lane of a live dispatch (HTTP 409). `id`: that dispatch."""

    def __init__(self, message, id=None):
        super().__init__(message)
        self.id = id


@contextlib.contextmanager
def store_locked():
    """Store-wide lock: the ownership check and the save of an issue-list dispatch are one step."""
    with open(os.path.join(_dir(), ".store.lock"), "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def owner_of(k: str):
    """Id of the dispatch not done or cancelled that has a lane `k`, else None."""
    for d in list_all():
        if d["state"] not in ("done", "cancelled") and k in d["lanes"]:
            return d["id"]
    return None


def create(epic, runner: str, settings: dict, children: list, workspace=None, title: str = "", issues=None) -> dict:
    if runner not in ("herdr", "headless"):
        raise ValueError("runner must be herdr or headless")
    s = check_settings({**DEFAULTS, **(settings or {})})
    if issues:
        _no_feature_branch(s)
        epic = None
        issues = sorted(issues, key=lambda k: int(k.rsplit("#", 1)[1]))
        title = title or issues_title(issues)
    d = {
        "id": uuid.uuid4().hex[:12],
        "epic": epic,
        "title": title,
        "runner": runner,
        "workspace": workspace,
        "settings": s,
        "state": "running",
        "lanes": {},
        "events": [],
        "created_at": time.time(),
        "ended_at": None,
    }
    if issues:
        d["issues"] = issues
    sync_lanes(d, children)
    event(d, None, "started", f"{len(d['lanes'])} lanes")
    if not issues:
        save(d)
        return d
    with store_locked():
        for k in d["lanes"]:
            owner = owner_of(k)
            if owner:
                raise Conflict(f"{k} is already a lane of dispatch {owner}", id=owner)
        save(d)
    return d


def check_settings(s: dict) -> dict:
    if s.get("grind") not in GRIND_MODES:
        raise ValueError(f"grind must be one of {GRIND_MODES}")
    if s.get("ci") not in CI_MODES:
        raise ValueError(f"ci must be one of {CI_MODES}")
    if not isinstance(s.get("max"), int) or isinstance(s["max"], bool) or not 1 <= s["max"] <= 10:
        raise ValueError("max must be an integer from 1 to 10")
    s["auto_merge"] = bool(s.get("auto_merge"))
    unknown = set(s) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown settings: {sorted(unknown)}")
    if s.get("model") is not None and not re.fullmatch(r"[A-Za-z0-9][\w.\[\]-]{0,60}", str(s["model"])):
        raise ValueError("model is not a model name")
    if s.get("effort") not in (None, "low", "medium", "high", "xhigh", "max"):
        raise ValueError("effort must be low, medium, high, xhigh or max")
    acc = s.get("account")
    if acc is not None and not (isinstance(acc, str) and 1 <= len(acc) <= 40):
        raise ValueError("account must be a saved account label")
    fb = s.get("feature_branch")
    if fb is not None and not re.fullmatch(_BRANCH, fb):
        raise ValueError("feature_branch is not a valid branch name")
    bb = s.get("base_branch")
    if bb is not None and not (isinstance(bb, str) and re.fullmatch(_BRANCH, bb)):
        raise ValueError("base_branch is not a valid branch name")
    if bb is not None and bb == fb:
        raise ValueError("base_branch must differ from feature_branch")
    return s


@contextlib.contextmanager
def locked(did: str):
    """Cross-process lock on one dispatch: the server's tick and the CLI both write its file. Not re-entrant."""
    with open(_path(did)[:-5] + ".lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def save(d: dict) -> None:
    atomic_write_text(_path(d["id"]), json.dumps(d, indent=1))


def load(did: str) -> dict:
    try:
        with open(_path(did), encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        raise ValueError(f"no dispatch {did}") from None
    d["settings"] = {**DEFAULTS, **d.get("settings", {})}  # records saved before a key existed read its default
    return d


def active_lane(repo: str, n=None, pr=None):
    """(dispatch id, lane) of a running or paused dispatch's live lane for issue `n` or PR `pr`, else None.
    The grind autostart and the pr-grind re-entry leave such PRs to the dispatch."""
    for d in list_all():
        if d["state"] not in ("running", "paused"):
            continue
        for x in d["lanes"].values():
            if (
                x["repo"].lower() == repo.lower()
                and x["stage"] in ACTIVE
                and ((n is not None and x["n"] == n) or (pr is not None and x.get("pr") == pr))
            ):
                return d["id"], x
    return None


def list_all() -> list:
    out = []
    for name in sorted(os.listdir(_dir())):
        if name.endswith(".json"):
            try:
                out.append(load(name[:-5]))
            except (OSError, ValueError):
                continue
    return sorted(out, key=lambda d: d["created_at"], reverse=True)


def event(d: dict, lane_key, kind: str, text: str) -> dict:
    e = {"at": time.time(), "lane": lane_key, "kind": kind, "text": text}
    d["events"] = (d.get("events") or [])[-(MAX_EVENTS - 1) :] + [e]
    return e


def set_settings(did: str, **kv) -> dict:
    """Live edit; takes effect at the next tick."""
    if "base_branch" in kv:
        raise ValueError("base_branch is fixed at start")
    with locked(did):
        d = load(did)
        d["settings"] = check_settings({**d["settings"], **kv})
        if d.get("issues"):
            _no_feature_branch(d["settings"])
        event(d, None, "settings", ", ".join(f"{k}={v}" for k, v in kv.items()))
        save(d)
        return d


def _issues(n: int) -> str:
    return f"{n} issue" + ("" if n == 1 else "s")


def _stop_lanes(d: dict) -> int:
    """Pause > Now: pause every active lane the user has not paused and close its session. Returns how many."""
    lanes = [x for x in d["lanes"].values() if x["stage"] in ACTIVE and not x.get("paused")]
    for x in lanes:
        x.update(paused=True, paused_by="dispatch")
        if x.get("handle"):
            x.setdefault("outbox", []).append(["close", None])
    return len(lanes)


def _restart_lanes(d: dict) -> int:
    """Resume: the lanes Pause > Now stopped get a fresh session in their stage; a lane the user paused stays paused."""
    lanes = [x for x in d["lanes"].values() if x.get("paused_by") == "dispatch"]
    for x in lanes:
        x.update(paused=False, paused_by=None, restart=True)
    return len(lanes)


def set_state(did: str, state: str, now: bool = False) -> dict:
    """now: on paused, also stop the sessions of the running lanes (the tick runs their outbox)."""
    if state not in ("running", "paused", "cancelled"):
        raise ValueError("state must be running, paused or cancelled")
    with locked(did):
        d = load(did)
        d["state"] = state
        if state == "cancelled":
            d["ended_at"] = time.time()
        text = f"dispatch {state}"
        if state == "paused" and now and (n := _stop_lanes(d)):
            text = f"dispatch paused now: {_issues(n)} stopped"
        elif state == "running" and (n := _restart_lanes(d)):
            text = f"dispatch running: {_issues(n)} restarted"
        event(d, None, state, text)
        save(d)
        return d


LANE_ACTIONS = ("pause", "resume", "retry", "skip", "merge", "hold", "unhold", "send")


def lane_action(did: str, k: str, action: str, text=None) -> dict:
    """The user's action on a lane. Session effects (close, send) go through the lane's outbox: the tick runs them."""
    with locked(did):
        d = load(did)
        apply_lane_action(d, k, action, text)
        save(d)
        return d


def apply_lane_action(d: dict, k: str, action: str, text=None) -> None:
    """lane_action on a loaded record; the caller holds `locked(d["id"])` and saves."""
    x = d["lanes"].get(k)
    if x is None:
        raise ValueError(f"no lane {k}")
    if action == "pause":
        x["paused"] = True
    elif action == "resume":
        x["paused"] = False
        if x.pop("paused_by", None):  # Pause > Now closed its session
            x["restart"] = True
    elif action == "skip":
        if x["stage"] in ACTIVE and x.get("handle"):
            x.setdefault("outbox", []).append(["close", None])
        x.update(stage="skipped", skip_reason="skipped by you", paused_by=None)
    elif action == "retry":  # clear held/needs; a fresh session for the lane's stage at the next tick
        red = x.get("held") == "CI is red"
        x.update(held=None, needs_you=None, paused=False, paused_by=None)
        if x["stage"] == "skipped" or (x["stage"] == "implementing" and not x.get("pr")):
            if x.get("handle"):
                x.setdefault("outbox", []).append(["close", None])
            x.update(stage="queued", skip_reason=None, handle=None)
        elif red and x.get("handle"):  # a retry of red CI means: fix it, in the session that wrote the PR
            x.setdefault("outbox", []).append(["send", ci_fix_prompt(x.get("pr"))])
        elif x["stage"] in ACTIVE:
            x["restart"] = True
    elif action == "merge":
        x["force_merge"] = True
    elif action in ("hold", "unhold"):
        x["hold_merge"] = action == "hold"
    elif action == "send":
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            raise ValueError("send needs a message of 1 to 2000 characters")
        if not x.get("handle"):
            raise ValueError(f"lane {k} has no session to send to")
        x.setdefault("outbox", []).append(["send", text.strip()])
    else:
        raise ValueError(f"action must be one of {LANE_ACTIONS}")
    event(d, k, "lane", action)


def request_end(did: str, action: str) -> dict:
    """An end-of-dispatch action, run by the next tick: open-pr (feature branch -> base branch, else the default branch, per repo),
    qa (a final QA session), grind-pr (grind the PRs open-pr opened). Never automatic."""
    if action not in END_ACTIONS:
        raise ValueError(f"end action must be one of {END_ACTIONS}")
    with locked(did):
        d = load(did)
        if d.get("issues"):
            raise ValueError(f"{action} needs an epic: not available for a list of issues")
        if action == "open-pr" and not d["settings"].get("feature_branch"):
            raise ValueError("open-pr needs a feature branch")
        if action == "grind-pr" and not d.get("final_prs"):
            raise ValueError("grind-pr needs the PR from open-pr first")
        d.setdefault("end_requests", []).append(action)
        event(d, None, "end", f"requested {action}")
        save(d)
        return d


def dispatch_repo(d: dict) -> str:
    """The dispatch's repo: the epic's, else the repo of its listed issues (all in one repo)."""
    return (d["epic"] or d["issues"][0]).partition("#")[0]


def _repos(d: dict) -> list:
    return sorted({x["repo"] for x in d["lanes"].values()})


def run_end(d: dict, action: str, runner, gh) -> str:
    """One end action; returns what happened. gh(argv) -> CompletedProcess."""
    epic_repo, _, epic_n = d["epic"].partition("#")
    fb = d["settings"].get("feature_branch")
    if action == "open-pr":
        out = []
        for repo in _repos(d):
            base = (
                d["settings"].get("base_branch")
                or gh(
                    ["repo", "view", repo, "--json", "defaultBranchRef", "-q", ".defaultBranchRef.name"]
                ).stdout.strip()
            )
            p = gh(
                [
                    "pr",
                    "create",
                    "-R",
                    repo,
                    "--base",
                    base or "master",
                    "--head",
                    fb,
                    "--title",
                    f"Epic #{epic_n}: merge {fb}",
                    "--body",
                    f"Every child of {d['epic']} is merged into `{fb}`.",
                ]
            )
            if p.returncode != 0:
                raise RuntimeError(f"gh pr create on {repo} failed: {(p.stderr or p.stdout).strip()[:200]}")
            url = p.stdout.strip().splitlines()[-1]
            d.setdefault("final_prs", {})[repo] = url
            out.append(url)
        return "opened " + ", ".join(out)
    if action == "qa":
        lane = {"repo": epic_repo, "n": int(epic_n), "label": f"qa-{epic_n}"}
        d["qa"] = runner.start(lane, qa_prompt(d["epic"], fb), d)
        return "QA session started"
    for repo, url in (d.get("final_prs") or {}).items():
        d.setdefault("final_grinds", {})[repo] = runner.start(
            {"repo": repo, "n": int(url.rstrip("/").split("/")[-1]), "label": f"grind-{repo.split('/')[-1]}"},
            grind_prompt(url, lane=False),
            d,
        )
    return "grind started on " + ", ".join((d.get("final_prs") or {}).values())


# --------------------------------------------------------------------------- tick


def gh_merge(repo: str, pr: int):
    """(ok, error). Merge commit, per the dispatch's merge rule."""
    p = run(["gh", "pr", "merge", str(pr), "-R", repo, "--merge"], timeout=120)
    return p.returncode == 0, (p.stderr or p.stdout or "").strip()[:300]


def _gh(argv):
    return run(["gh", *argv], timeout=120)


def tick(d: dict, facts: dict, runner, merge=gh_merge, now=None, notify=None, gh=_gh) -> list:
    """Step every lane, run its actions, launch the startable ones, run end requests. Returns the new events.
    The caller holds `locked(d["id"])` around load + tick."""
    now = now or time.time()
    new: list = []

    def ev(k, kind, text):
        new.append(event(d, k, kind, text))
        if notify and kind in ("needs_you", "held", "awaiting_merge", "finished", "warning"):
            notify(d, k, kind, text)

    def send(x, text):
        """Prompt the lane's session; a lane whose session was closed (before the merge) gets a fresh one."""
        if x.get("handle"):
            runner.send(x["handle"], text)
        else:
            x["handle"] = runner.start(x, text, d)
            x.setdefault("handles", []).append(x["handle"])

    for k, x in d["lanes"].items():
        outbox = x.pop("outbox", None) or []
        for kind, text in outbox:
            try:
                if kind == "send":
                    send(x, text)
                elif x.get("handle"):
                    runner.close(x["handle"])
                    x["handle"] = None
            except Exception as e:  # noqa: BLE001
                x["needs_you"] = f"{kind} failed: {e}"
                ev(k, "needs_you", x["needs_you"])
        if d["state"] in ("cancelled", "done"):
            continue
        f = facts.get(k) or {}
        if x.pop("restart", None):
            try:
                if x.get("handle"):
                    runner.close(x["handle"])
                text = stage_prompt(x, d["settings"], (f.get("pr") or {}).get("url"))
                x["handle"] = runner.start(x, text, d) if text else None
                if x["handle"]:
                    x.setdefault("handles", []).append(x["handle"])
                ev(k, "lane", f"restarted in {x['stage']}")
            except Exception as e:  # noqa: BLE001
                x["needs_you"] = f"restart failed: {e}"
                ev(k, "needs_you", x["needs_you"])
            continue
        if k not in facts:  # no fresh facts for this lane (repo not polled yet): never move on a guess
            continue
        if any(kind == "send" for kind, _ in outbox):  # the facts predate that prompt: an idle agent is stale
            continue
        patch, acts = step(x, f, d["settings"], now)
        old = x["stage"]
        x.update(patch)
        if x["stage"] != old:
            ev(k, "stage", f"{old} -> {x['stage']}")
        for a in acts:
            try:
                if a[0] == "send":
                    send(x, a[1])
                elif a[0] == "continue":
                    runner.send(x["handle"], CONTINUE)
                elif a[0] == "close":
                    if x.get("handle"):
                        runner.close(x["handle"])
                elif a[0] == "merge":
                    ok, err = merge(x["repo"], a[1])
                    x["force_merge"] = False
                    if ok:
                        ev(k, "merged", f"merged PR #{a[1]}")
                        ci_now = (f.get("pr") or {}).get("ci")
                        if d["settings"].get("ci") == "ignore" and ci_now in ("failure", "pending"):
                            ev(k, "warning", "merged with red CI" if ci_now == "failure" else "merged with CI pending")
                    elif "conflict" in err.lower():  # the board had not seen the conflict yet: fix it in the lane
                        base = lane_base(x, d["settings"])
                        x.update(stage="conflict_fix", merge_at=None)
                        send(x, conflict_prompt(a[1], base))
                        ev(k, "stage", "merge_gate -> conflict_fix (GitHub refused the merge: conflicts)")
                    else:
                        x["held"] = f"merge failed: {err}"
                        ev(k, "held", x["held"])
                elif a[0] == "notify":
                    ev(k, a[1], a[2])
            except Exception as e:  # noqa: BLE001 - one lane's failure never stops the others
                x["needs_you"] = f"{a[0]} failed: {e}"
                ev(k, "needs_you", x["needs_you"])
    for action in d.pop("end_requests", None) or []:
        try:
            ev(None, "end", run_end(d, action, runner, gh))
        except Exception as e:  # noqa: BLE001
            ev(None, "needs_you", f"{action} failed: {e}")
    for k in startable(d, facts):
        x = d["lanes"][k]
        base = lane_base(x, d["settings"])
        try:
            x["handle"] = runner.start(x, implement_prompt(x["n"], base, ci=d["settings"].get("ci", "wait")), d)
            x.setdefault("handles", []).append(x["handle"])
            x.update(stage="implementing", started_at=now, needs_you=None)
            ev(k, "stage", "queued -> implementing")
        except Exception as e:  # noqa: BLE001
            x.update(stage="skipped", skip_reason=f"start failed: {e}")
            ev(k, "needs_you", f"start failed: {e}")
    if d["state"] == "running" and d["lanes"] and all(x["stage"] in ("closed", "skipped") for x in d["lanes"].values()):
        d.update(state="done", ended_at=now)
        ev(None, "finished", "every lane is closed or skipped")
    save(d)
    return new
