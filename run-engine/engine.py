"""Pure pipeline engine for /run-issue.

No I/O, no network, no LLM — every function here is deterministic and directly
testable (see test_engine.py). route.py is the I/O half; keep it that way, because
the whole point of this module is that the relay, bounce and cap logic can be
asserted instead of trusted to a prompt.
"""

from __future__ import annotations

import re
from functools import lru_cache

# The status vocabulary a station envelope may use. Deliberately three, not four:
# there is no `blocked`. A station reports success, a defect it wants fixed, or a wall it
# cannot get past — and none of those is "stop and ask the human", because the pipeline has
# exactly three human gates and a station does not get to invent a fourth.
STATUSES = ("passed", "bounce", "escalate")

REQUIRED_FIELDS = ("issue", "station", "status", "attempt", "summary")


# --------------------------------------------------------------------------- globs
# Python's fnmatch has no FNM_PATHNAME, so `docs/*` would match `docs/a/b/c`.
# Path globs here must not let `*` cross a `/` — only `**` may.


def _split_commas(text: str) -> list[str]:
    """Split on commas at brace-depth 0, so {a,{b,c}} splits into a and {b,c}."""
    parts, depth, buf = [], 0, []
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def _translate(pattern: str) -> str:
    out: list[str] = []
    i, n = 0, len(pattern)
    while i < n:
        ch = pattern[i]
        if pattern.startswith("**/", i):
            # matches zero or more leading directories, so **/x also matches bare x
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif ch == "*":
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        elif ch == "[":
            j = i + 1
            if j < n and pattern[j] in "!^":
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j >= n:
                out.append(re.escape(ch))
                i += 1
            else:
                body = pattern[i + 1 : j]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append("[" + body + "]")
                i = j + 1
        elif ch == "{":
            depth, j = 1, i + 1
            while j < n and depth:
                if pattern[j] == "{":
                    depth += 1
                elif pattern[j] == "}":
                    depth -= 1
                j += 1
            if depth:
                out.append(re.escape(ch))
                i += 1
            else:
                inner = pattern[i + 1 : j - 1]
                out.append("(?:" + "|".join(_translate(p) for p in _split_commas(inner)) + ")")
                i = j
        else:
            out.append(re.escape(ch))
            i += 1
    return "".join(out)


@lru_cache(maxsize=512)
def _compiled(pattern: str):
    # Case-INSENSITIVE on purpose. Directory case is a stack convention, not a fact:
    # the same concept is app/Http/Middleware in Laravel, src/middleware in Next, and
    # lib/guards in Dart. These globs are risk heuristics, not a security boundary, and
    # a case-sensitive match here fails silently — the signal simply never fires and
    # the specialist it selects never runs.
    return re.compile(_translate(pattern) + r"\Z", re.IGNORECASE)


def glob_match(path: str, pattern: str) -> bool:
    """True when a repo-relative path matches a glob. `*` never crosses `/`; `**` does."""
    return _compiled(pattern).match(path) is not None


def matches_any(path: str, patterns) -> bool:
    return any(glob_match(path, p) for p in patterns or [])


# --------------------------------------------------------------------------- actions


class RouteAction:
    ADVANCE = "advance"
    BOUNCE = "bounce"
    ESCALATE = "escalate"
    DONE = "done"

    def __init__(self, kind: str, target: str | None = None, reason: str = ""):
        self.kind = kind
        self.target = target
        self.reason = reason

    def __str__(self) -> str:
        if self.kind in (RouteAction.ADVANCE, RouteAction.BOUNCE):
            return f"{self.kind}({self.target})"
        if self.kind == RouteAction.ESCALATE:
            return f"escalate: {self.reason}"
        return self.kind

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"RouteAction({self!s})"


# --------------------------------------------------------------------------- ledger


class Ledger:
    """The run's state: who holds the baton, what has bounced, and the trace.

    This is the in-memory shape of run.json. `stations` lives here rather than in
    config so the engine is roster-agnostic — a mode (`--lean`) needs zero code
    change, and a resumed run can never silently swap rosters mid-flight.
    """

    def __init__(self, issue: int, stations: list[str], current_index: int = 0):
        self.issue = issue
        self.stations = list(stations)
        self.current_index = current_index
        # keyed "<from>-><to>", NOT by target alone: run-issue keeps the dev and
        # verify budgets deliberately separate, and a target-keyed counter would
        # merge them (a verifier->dev bounce would spend dev's own retry budget).
        self.bounce_counts: dict[str, int] = {}
        self.status = "running"
        self.trace: list[str] = []
        self.context: dict = {}
        self.classification: dict | None = None
        self.specialists: list[str] = []

    # -- baton ---------------------------------------------------------------

    def current_station(self) -> str:
        return self.stations[self.current_index]

    def index_of(self, station: str) -> int:
        try:
            return self.stations.index(station)
        except ValueError:
            raise ValueError(f"Unknown station: {station}") from None

    def advance_to(self, station: str) -> None:
        self.current_index = self.index_of(station)
        self.trace.append(f"advance->{station}")

    def bounce_key(self, frm: str, to: str) -> str:
        return f"{frm}->{to}"

    def bounce_count(self, frm: str, to: str) -> int:
        return self.bounce_counts.get(self.bounce_key(frm, to), 0)

    def record_bounce(self, frm: str, to: str) -> None:
        key = self.bounce_key(frm, to)
        self.bounce_counts[key] = self.bounce_counts.get(key, 0) + 1
        self.current_index = self.index_of(to)
        self.trace.append(f"bounce->{key}#{self.bounce_counts[key]}")

    def mark_done(self) -> None:
        self.status = "done"
        self.trace.append("done")

    def mark_escalated(self, reason: str) -> None:
        self.status = "escalated"
        self.trace.append(f"escalate: {reason}")

    # -- side-steps ----------------------------------------------------------
    # These record something for observability WITHOUT moving the baton. The
    # classifier and the specialist panel are not stations; keeping them out of
    # current_index is what preserves the one-envelope-per-station contract.

    def record_classification(self, classification: dict) -> None:
        self.classification = classification
        self.trace.append(
            "classify: {t} risk={s}({b}) blast={r} signals=[{g}]".format(
                t=classification.get("ticket_type", "?"),
                s=classification.get("risk_score", "?"),
                b=classification.get("risk_band", "?"),
                r=classification.get("blast_radius", "?"),
                g=",".join(classification.get("signals", [])),
            )
        )

    def record_specialists(self, names: list[str]) -> None:
        self.specialists = [n for n in names if isinstance(n, str)]
        self.trace.append("review-panel: [" + ",".join(self.specialists) + "]")

    # -- persistence ---------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "issue": self.issue,
            "stations": self.stations,
            "currentIndex": self.current_index,
            "bounceCounts": self.bounce_counts,
            "status": self.status,
            "trace": self.trace,
            "context": self.context,
            "classification": self.classification,
            "specialists": self.specialists,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Ledger":
        stations = [s for s in data.get("stations", []) if isinstance(s, str)]
        led = cls(int(data.get("issue", 0)), stations, int(data.get("currentIndex", 0)))
        led.status = data.get("status", "running")
        led.trace = [t for t in data.get("trace", []) if isinstance(t, str)]
        led.bounce_counts = {
            str(k): int(v) for k, v in (data.get("bounceCounts") or {}).items() if isinstance(v, int)
        }
        led.context = data.get("context") or {}
        led.classification = data.get("classification")
        led.specialists = [s for s in (data.get("specialists") or []) if isinstance(s, str)]
        return led


# --------------------------------------------------------------------------- router


class Router:
    """Given the ledger and a station's envelope, decide the next action.

    Pure and total: every status maps to exactly one action, and the cap is
    enforced here rather than by an orchestrator asked to keep a counter.
    """

    def __init__(self, bounce_cap: int = 2):
        self.bounce_cap = bounce_cap

    def next(self, ledger: Ledger, envelope: dict) -> RouteAction:
        status = envelope.get("status")
        if status == "passed":
            return self._on_passed(ledger)
        if status == "bounce":
            return self._on_bounce(ledger, envelope)
        if status == "escalate":
            return RouteAction(RouteAction.ESCALATE, reason=envelope.get("summary") or "station escalated")
        raise ValueError(f"Unknown status: {status!r}")

    def _on_passed(self, ledger: Ledger) -> RouteAction:
        if ledger.current_index >= len(ledger.stations) - 1:
            return RouteAction(RouteAction.DONE)
        return RouteAction(RouteAction.ADVANCE, target=ledger.stations[ledger.current_index + 1])

    def _on_bounce(self, ledger: Ledger, envelope: dict) -> RouteAction:
        bounce = envelope.get("bounce")
        if not isinstance(bounce, dict) or not isinstance(bounce.get("to"), str):
            raise ValueError('bounce status requires a string bounce.to')

        frm = envelope.get("station")
        target = bounce["to"]

        # A bounce to a station outside THIS run's roster is unroutable — it happens
        # whenever an agent prompt names a target the roster does not contain (a dev
        # bouncing `to: sdet` is correct in the full roster and impossible in --lean,
        # where the sdet never ran). Escalate with the roster spelled out rather than
        # blowing up on index_of().
        if target not in ledger.stations:
            return RouteAction(
                RouteAction.ESCALATE,
                target=target,
                reason=(
                    f"bounce target '{target}' is not in this run's roster ("
                    + " -> ".join(ledger.stations)
                    + ") — unroutable"
                ),
            )

        if ledger.bounce_count(frm, target) + 1 > self.bounce_cap:
            return RouteAction(
                RouteAction.ESCALATE,
                target=target,
                reason=f"bounce cap ({self.bounce_cap}) exceeded for {frm}->{target}",
            )

        return RouteAction(RouteAction.BOUNCE, target=target, reason=bounce.get("reason", ""))


# --------------------------------------------------------------------------- validator


def validate_envelope(envelope: dict, ledger: Ledger, config: dict) -> list[str]:
    """Enforce the handoff contract. Returns human-readable errors; [] means valid.

    This is where "typed relay, not telephone" is actually enforced — route.py
    exits 5 on any error here, so the orchestrator cannot advance a station that
    handed back something malformed.
    """
    errors: list[str] = []

    for field in REQUIRED_FIELDS:
        if field not in envelope:
            errors.append(f"missing required field: {field}")

    status = envelope.get("status")
    if status is not None and status not in STATUSES:
        errors.append(f"invalid status: {status!r}")

    issue = envelope.get("issue")
    if issue is not None and (not isinstance(issue, int) or isinstance(issue, bool) or issue < 1):
        errors.append("issue must be a positive integer")

    attempt = envelope.get("attempt")
    if attempt is not None and (not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1):
        errors.append("attempt must be a positive integer")

    station = envelope.get("station")
    if isinstance(station, str) and ledger.stations and station not in ledger.stations:
        errors.append(
            f"station {station!r} is not in this run's roster (" + " -> ".join(ledger.stations) + ")"
        )

    if status == "bounce":
        bounce = envelope.get("bounce")
        if not isinstance(bounce, dict) or "to" not in bounce or "reason" not in bounce:
            errors.append('status "bounce" requires bounce.to and bounce.reason')
        elif not isinstance(bounce["to"], str) or not isinstance(bounce["reason"], str):
            errors.append("bounce.to and bounce.reason must be strings")

    # Evidence gate: a station that claims success must record what it actually ran.
    # Cooperative, not fabrication-proof (a pasted command is byte-identical to a real
    # one) — see H1/H2 in run-issue.md. It catches an omitted pass, not a determined
    # fabricator. Exempt: any non-passed envelope (reporting a defect needs no proof of
    # work) and an orchestrator-authored skip.
    required = config.get("evidence_required_stations") or []
    if status == "passed" and isinstance(station, str) and station in required:
        evidence = envelope.get("evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        if not evidence.get("skipped"):
            commands = evidence.get("commands")
            if not isinstance(commands, list) or not commands:
                errors.append(
                    f'station "{station}" reported passed with no evidence.commands[] — '
                    "record the real commands you ran (cmd + exit + a one-line excerpt), "
                    'or set evidence.skipped for a station that was never dispatched'
                )

    return errors


# --------------------------------------------------------------------------- classifier


def _int(value, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def classify(changed_files: list[str], meta: dict, config: dict) -> dict:
    """Score a diff into {ticket_type, risk_score, risk_band, blast_radius, signals}.

    Every glob, weight and threshold comes from config — retuning is a config edit,
    never a code change.
    """
    cfg = config.get("classification") or {}
    signal_globs = cfg.get("signals") or {}
    severity = cfg.get("signal_severity") or {}
    weights = cfg.get("risk_weights") or {}
    bands = cfg.get("bands") or {}
    labels = [l for l in (meta.get("labels") or []) if isinstance(l, str)]

    signals = sorted(
        name for name, globs in signal_globs.items() if any(matches_any(f, globs) for f in changed_files)
    )

    # Blast radius. A missing graph is reported as "unknown" and scored as the WIDE
    # case, not silently as d1 — gitnexus is best-effort in this pipeline, and
    # defaulting an absent depth to 0 would park every PR in the `low` band and make
    # the whole classifier dead weight on any repo without an index.
    depth = meta.get("upstream_depth")
    d1_max = _int((cfg.get("blast_radius") or {}).get("d1_max_depth"), 1)
    if not isinstance(depth, int) or isinstance(depth, bool):
        blast = "unknown"
    else:
        blast = "d1" if depth <= d1_max else "d2"

    br_weights = weights.get("blast_radius") or {}
    score = _int(br_weights.get(blast), _int(br_weights.get("d2"), 25))

    fc = weights.get("file_count") or {}
    score += min(len(changed_files) * _int(fc.get("per_file"), 2), _int(fc.get("cap"), 20))

    loc_cfg = weights.get("loc") or {}
    score += min(
        (_int(meta.get("loc_changed")) // 100) * _int(loc_cfg.get("per_100"), 3),
        _int(loc_cfg.get("cap"), 15),
    )

    if any(matches_any(f, cfg.get("migration_globs") or []) for f in changed_files):
        score += _int(weights.get("migration_present"), 15)

    score += min(
        sum(_int(severity.get(s)) for s in signals),
        _int(weights.get("signal_severity_cap"), 40),
    )
    score = max(0, min(100, score))

    band = "low"
    if score >= _int(bands.get("high"), 60):
        band = "high"
    elif score >= _int(bands.get("medium"), 30):
        band = "medium"

    ticket_type = cfg.get("type_default", "feature")
    for rule in cfg.get("type_rules") or []:
        paths_all = rule.get("paths_all")
        paths_any = rule.get("paths_any")
        labels_any = rule.get("labels_any")
        if paths_all and changed_files and all(matches_any(f, paths_all) for f in changed_files):
            ticket_type = rule["type"]
            break
        if paths_any and any(matches_any(f, paths_any) for f in changed_files):
            ticket_type = rule["type"]
            break
        if labels_any and any(l in labels_any for l in labels):
            ticket_type = rule["type"]
            break

    return {
        "artifact": "classification",
        "ticket_type": ticket_type,
        "risk_score": score,
        "risk_band": band,
        "blast_radius": blast,
        "signals": signals,
        "file_count": len(changed_files),
    }


# --------------------------------------------------------------------------- review policy


def resolve_review_panel(classification: dict, policy: dict) -> list[str]:
    """Map a classification onto the ordered, deduplicated, MINIMUM specialist set.

    The generalist reviewer is never in the output — it is unconditional and
    orchestrator-owned, so an empty result means "generalist only".
    """
    fired: dict[str, bool] = {}

    def fire(names):
        if isinstance(names, list):
            for n in names:
                if isinstance(n, str):
                    fired[n] = True

    for signal in classification.get("signals") or []:
        fire((policy.get("signals") or {}).get(signal))
    fire((policy.get("risk_band") or {}).get(classification.get("risk_band")))
    fire((policy.get("ticket_type") or {}).get(classification.get("ticket_type")))

    generalist = policy.get("generalist")
    order = [s for s in (policy.get("order") or []) if isinstance(s, str)]

    out = [s for s in order if fired.pop(s, False) and s != generalist]
    out.extend(s for s in fired if s != generalist)  # defensive: fired but unordered
    return out
