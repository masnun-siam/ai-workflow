"""`aiw peer-review` — the peer review loop: a validated verdict write and a pure decision.

A panel of single-lens reviewers (config `peer_review.lenses`, picked per run from the lenses the
artifact's kind offers) reads one artifact per round: a draft doc, or for `custom` a change
(Ask/Answer/Diff in one file). Each reviewer writes its verdict through `verdict`, which refuses a
finding that does not quote the artifact or name one of its headings, and a verdict for a stale
artifact or an old round. `next` opens rounds and decides: every selected lens blocks; a finding
that needs a product decision, or re-raises one the worker dismissed, goes to the user; a spent
round budget hands over to the user and never auto-approves.

Files, one directory per run (`new` makes it and never reuses one): `round-<n>/request.json` (the
artifact hash, the panel, and the worker's dispositions of the prior round's findings),
`round-<n>/<lens>.json`, and `round-<n>/decision.json` (the last decision `next` printed).
"""

from __future__ import annotations

import hashlib
import re

SEVERITIES = ("blocker", "major", "minor")
MAX_FINDINGS = 8
MIN_QUOTE_WORDS = 4  # a shorter quote ("the") matches almost any artifact and proves nothing
DISPOSITIONS = ("fixed", "dismissed", "decided")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def norm(text: str) -> str:
    """Whitespace and markdown emphasis ignored, so `**must**  retry` matches `must retry`."""
    return " ".join(re.sub(r"[*_`]", "", text or "").split()).casefold()


def headings(doc: str) -> set[str]:
    # ponytail: also matches ## lines inside fenced code; artifacts rarely fence headings
    return {norm(m) for m in re.findall(r"^#{2,3}\s+(.+?)\s*$", doc, re.M)}


def _check_reraise(f: dict, lens, prior: list, tag: str) -> list[str]:
    """A blocking finding says whether it re-raises one of its lens's prior findings; the engine never guesses."""
    if "reraises" not in f:
        return [f"{tag}: a {f['severity']} needs reraises: <prior id> or null"]
    mine = [p for p in prior if isinstance(p, dict) and p.get("lens") == lens]
    rer = f["reraises"]
    if rer is not None:
        target = next((p for p in mine if p.get("id") == rer), None) if isinstance(rer, str) else None
        if target is None:
            return [f"{tag}: reraises {rer!r} is not one of your findings from the prior round"]
        evidence = f.get("new_evidence")
        if target.get("disposition") == "decided" and not (isinstance(evidence, str) and evidence.strip()):
            return [f"{tag}: the user decided {rer}; not re-raisable without new_evidence"]
        return []
    quote = norm(f.get("quote") or "")
    same = [
        p.get("id") for p in mine if p.get("disposition") == "dismissed" and quote and norm(p.get("quote")) == quote
    ]
    if same and not (isinstance(f.get("distinct_because"), str) and f["distinct_because"].strip()):
        return [f"{tag}: same quote as dismissed {same[0]}: set reraises, or say how it differs in distinct_because"]
    return []


def validate(v, text: str, request: dict) -> list[str]:
    """Reasons to refuse this verdict; [] means it may be written."""
    if not isinstance(v, dict):
        return ["a verdict is a JSON object"]
    errs = []
    lenses, prior = request["lenses"], request.get("prior") or []
    if v.get("lens") not in lenses:
        errs.append(f"unknown lens {v.get('lens')!r}; the panel is {', '.join(lenses)}")
    if v.get("round") != request["round"]:
        errs.append(f"round {v.get('round')!r} is not the open round {request['round']}")
    if v.get("artifact_sha256") != request["artifact_sha256"]:
        errs.append("stale: artifact_sha256 is not the hash of the artifact this round reviews")
    findings = v.get("findings")
    if not isinstance(findings, list):
        return errs + ["findings must be a list"]
    if len(findings) > MAX_FINDINGS:
        errs.append(f"{len(findings)} findings; at most {MAX_FINDINGS}, most severe first")
    if v.get("verdict") not in ("approve", "changes"):
        errs.append("verdict must be approve or changes")
    body, heads = norm(text), headings(text)
    for i, f in enumerate(findings):
        tag = f"finding {i + 1}"
        if not isinstance(f, dict):
            errs.append(f"{tag}: not an object")
            continue
        if f.get("severity") not in SEVERITIES:
            errs.append(f"{tag}: severity must be one of {', '.join(SEVERITIES)}")
        if not isinstance(f.get("id"), str) or not f["id"]:
            errs.append(f"{tag}: needs an id")
        if not isinstance(f.get("needs_decision", False), bool):
            errs.append(f"{tag}: needs_decision must be true or false")
        quote, section = norm(f.get("quote") or ""), norm(f.get("section") or "")
        if quote and len(quote.split()) < MIN_QUOTE_WORDS:
            errs.append(f"{tag}: quote at least {MIN_QUOTE_WORDS} words, or use the section fallback")
        elif quote and quote not in body:
            errs.append(f"{tag}: quote not found in the artifact")
        elif not quote and section not in heads:
            errs.append(f"{tag}: without a quote, section must be one of the artifact's ##/### headings")
        if v.get("verdict") == "approve" and f.get("severity") in ("blocker", "major"):
            errs.append(f"{tag}: an approve verdict cannot carry a {f['severity']}")
        if f.get("severity") in ("blocker", "major"):
            errs += _check_reraise(f, v.get("lens"), prior, tag)
    return errs


def check_prior(prior, finding_ids: set) -> list[str]:
    """The worker's answer to every finding of the round being closed, so none is dropped.

    Keyed on (lens, id): reviewers pick their own ids, so two lenses can both say "f1".
    """
    if not isinstance(prior, list):
        return ["--prior must be a JSON list of {lens, id, disposition, reason}"]
    errs, seen = [], set()
    for p in prior:
        if not isinstance(p, dict) or p.get("disposition") not in DISPOSITIONS:
            errs.append(f"{p!r}: disposition must be one of {', '.join(DISPOSITIONS)}")
        elif not (isinstance(p.get("reason"), str) and p["reason"].strip()):
            errs.append(f"{p.get('id')!r}: needs a reason")
        else:
            seen.add((p.get("lens"), p.get("id")))
    errs += [f"no disposition for {lens} finding {i}" for lens, i in sorted(finding_ids - seen)]
    return errs


def decide(verdicts: dict, lenses: list, rnd: int, max_rounds: int, prior=()) -> dict:
    """done | revise | ask, from one complete round of verdicts. Pure. Every lens on the panel blocks."""
    missing = [lens for lens in lenses if lens not in verdicts]
    if missing:
        raise ValueError(f"round {rnd} is missing verdicts from: {', '.join(missing)}")
    # re-raising what the worker dismissed, or what the user already ruled on, is the user's call again
    settled = {(p.get("lens"), p.get("id")) for p in prior if p.get("disposition") in ("dismissed", "decided")}
    out = {"round": rnd, "blockers": [], "decisions": [], "disputes": [], "advisory": []}
    for lens in lenses:
        for f in verdicts[lens]["findings"]:
            f = {**f, "lens": lens}
            if f.get("needs_decision"):
                out["decisions"].append(f)
            elif f["severity"] == "minor":
                out["advisory"].append(f)
            elif (lens, f.get("reraises")) in settled:
                out["disputes"].append(f)
            else:
                out["blockers"].append(f)
    if out["decisions"] or out["disputes"]:
        return {**out, "action": "ask", "reason": "decision" if out["decisions"] else "dispute"}
    if out["blockers"]:
        if rnd >= max_rounds:
            return {**out, "action": "ask", "reason": "cap"}
        return {**out, "action": "revise", "reason": "blocking findings"}
    return {**out, "action": "done", "reason": "every lens approves"}


import fnmatch  # noqa: E402  (kept beside the I/O half, the top of this file is pure)
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from shared import data_dir, die, extract_json_object, load_config, read_json, write_json  # noqa: E402

# Never sent to a reviewer, tracked or not: a committed .env is common.
DENY = (".env*", "*.pem", "*.key", "*.p12", "*.keystore", "*.sqlite*", "*.db", "credentials*.json", ".npmrc", ".pypirc")
DENY += ("id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*")  # ssh keys only: id_generator.ts is code
LOCKFILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "composer.lock",
    "poetry.lock",
    "Cargo.lock",
    "uv.lock",
}


def _policy() -> dict:
    return load_config(None)["peer_review"]


def _rounds(review_dir: str) -> int:
    try:
        names = os.listdir(review_dir)
    except FileNotFoundError:
        return 0
    return max((int(m.group(1)) for n in names if (m := re.fullmatch(r"round-(\d+)", n))), default=0)


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        die(3, f"cannot read the artifact: {exc}")


def offers() -> dict:
    """What the web UI needs to draw the lens picker: no lens is hardcoded in the frontend."""
    policy = _policy()
    return {
        "default": list(policy["default_lenses"]),
        "max_rounds": policy["max_rounds"],
        "kinds": {k: list(v["offer"]) for k, v in policy["kinds"].items()},
    }


def check_lenses(kind: str, picked: list) -> list[str]:
    """The picked lenses, deduplicated; ValueError names the offered set when one isn't offered."""
    kinds = _policy()["kinds"]
    if kind not in kinds:
        raise ValueError(f"{kind or 'this command'} has no peer review; one of {', '.join(kinds)}")
    offer = kinds[kind]["offer"]
    bad = [x for x in picked if x not in offer]
    if bad or not picked:
        raise ValueError(f"{kind} offers the lenses {', '.join(offer)}; got {', '.join(map(str, bad)) or 'none'}")
    return list(dict.fromkeys(picked))


def _lenses(raw: str | None, kind: str, policy: dict) -> list[str]:
    picked = [x.strip() for x in raw.split(",") if x.strip()] if raw else list(policy["default_lenses"])
    try:
        return check_lenses(kind, picked)
    except ValueError as exc:
        die(2, str(exc))


def make_dir(kind: str, name: str) -> str:
    """One review dir per run: FileExistsError rather than reuse."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise ValueError(f"{name!r}: letters, digits, '.', '_' and '-' only")
    path = os.path.join(data_dir(), "peer-review", kind, name)
    os.makedirs(path)
    return path


def status(review_dir: str) -> str:
    """The post-check a session shows: read from round state, never from the dir existing."""
    n = _rounds(review_dir)
    if n == 0:
        return "not run"
    try:
        with open(os.path.join(review_dir, f"round-{n}", "decision.json"), encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return "unfinished"
    if d.get("action") == "done":
        return "approved"
    if d.get("reason") == "cap":
        return "stopped at cap"
    return "unfinished"


def _open(review_dir: str, rnd: int, path: str, text: str, prior, max_rounds: int, kind: str, lenses: list) -> None:
    write_json(
        os.path.join(review_dir, f"round-{rnd}", "request.json"),
        {
            "round": rnd,
            "kind": kind,
            "rubric": _policy()["kinds"][kind]["rubric"],
            "artifact_path": os.path.abspath(path),
            "artifact_sha256": sha(text),
            "max_rounds": max_rounds,
            "lenses": lenses,
            "prior": prior,
        },
    )
    print(json.dumps({"action": "review", "round": rnd, "lenses": lenses, "dir": os.path.abspath(review_dir)}))


def cmd_new(args) -> None:
    policy = _policy()
    if args.kind not in policy["kinds"]:
        die(2, f"unknown kind {args.kind!r}; one of {', '.join(policy['kinds'])}")
    if args.id:
        name = args.id
    else:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", args.slug or "").strip("-.") or "run"
        name = f"{slug}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    try:
        print(make_dir(args.kind, name))
    except ValueError as exc:
        die(2, f"--id {exc}")
    except FileExistsError as exc:
        die(1, f"{exc.filename} already exists: one review dir per run, never reused")


def cmd_next(args) -> None:
    policy = _policy()
    text = _read(args.artifact)
    prior = read_json(args.prior) if args.prior else []
    n = _rounds(args.review_dir)
    if n == 0:
        if args.kind not in policy["kinds"]:
            die(2, f"--kind is required for round 1; one of {', '.join(policy['kinds'])}")
        lenses = _lenses(args.lenses, args.kind, policy)
        _open(
            args.review_dir, 1, args.artifact, text, prior, args.max_rounds or policy["max_rounds"], args.kind, lenses
        )
        return
    rd = os.path.join(args.review_dir, f"round-{n}")
    req = read_json(os.path.join(rd, "request.json"))
    verdicts = {
        lens: read_json(os.path.join(rd, f"{lens}.json"))
        for lens in req["lenses"]
        if os.path.isfile(os.path.join(rd, f"{lens}.json"))
    }
    missing = [lens for lens in req["lenses"] if lens not in verdicts]
    if missing:
        print(json.dumps({"action": "wait", "round": n, "missing": missing}))
        return
    max_rounds = req["max_rounds"] + (1 if args.more else 0)
    d = decide(verdicts, req["lenses"], n, req["max_rounds"], req.get("prior") or [])
    if sha(text) != req["artifact_sha256"] and (n < max_rounds):
        quotes = {(lens, f["id"]): f.get("quote", "") for lens, v in verdicts.items() for f in v["findings"]}
        if quotes and not args.prior:
            die(2, f"round {n} had findings; pass --prior <dispositions.json> so the next round sees them")
        errs = check_prior(prior, set(quotes))
        if errs:
            die(5, "--prior refused:\n- " + "\n- ".join(errs))
        # the quote rides along so the next round's verdict check can spot a silent re-raise
        prior = [{**p, "quote": quotes.get((p.get("lens"), p.get("id")), "")} for p in prior]
        _open(args.review_dir, n + 1, args.artifact, text, prior, max_rounds, req["kind"], req["lenses"])
        return
    write_json(os.path.join(rd, "decision.json"), d)
    print(json.dumps(d))


def cmd_verdict(args) -> None:
    n = _rounds(args.review_dir)
    if n == 0:
        die(3, "no review round is open: run `aiw peer-review next` first")
    rd = os.path.join(args.review_dir, f"round-{n}")
    req = read_json(os.path.join(rd, "request.json"))
    # `-`: the reviewer pipes its own verdict in, so the artifact's author never transcribes it.
    v = extract_json_object(sys.stdin.read()) if args.file == "-" else read_json(args.file)
    if isinstance(v, dict) and v.get("lens") != args.lens:
        die(5, f"the file is lens {v.get('lens')!r}, not --lens {args.lens}")
    errs = validate(v, _read(req["artifact_path"]), req)
    if errs:
        die(5, "verdict refused:\n- " + "\n- ".join(errs))
    write_json(os.path.join(rd, f"{args.lens}.json"), v)
    print(f"round {n}: {args.lens} {v['verdict']}, {len(v['findings'])} finding(s)")


def _git(cwd: str, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=True, errors="replace")


def _drop_reason(path: str, binary: bool) -> str | None:
    name = os.path.basename(path)
    if "secret" in name.lower() or any(fnmatch.fnmatch(name, p) for p in DENY):
        return "secret-like"
    if name in LOCKFILES:
        return "lockfile"
    if binary:
        return "binary"
    return None


def _is_binary(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return b"\0" in fh.read(8000)
    except OSError:
        return True


def _cap(body: str, max_lines: int) -> str:
    lines = body.splitlines()
    if len(lines) <= max_lines:
        return body
    names, cut = [], None
    for i, line in enumerate(lines):
        if line.startswith("diff --git a/"):
            rest = line[len("diff --git ") :]
            name = rest[2 : 2 + (len(rest) - 5) // 2]  # "a/<p> b/<p>": no renames, so both halves match
            if i >= max_lines:
                names.append(name)
            else:
                cut = name
    partial = f"partial: {cut}; " if cut else ""
    note = f"truncated at {max_lines} lines: {partial}omitted: {', '.join(names) or 'none'}"
    return "\n".join(lines[:max_lines] + [note]) + "\n"


def cmd_diff(args) -> None:
    cwd = os.path.abspath(args.repo)
    r = _git(cwd, "rev-parse", "--verify", "--quiet", f"{args.since}^{{commit}}")
    if r.returncode != 0:
        if args.since in ("@{u}", "@{upstream}"):
            die(1, "this branch has no upstream: pass --since <sha>, or diff uncommitted changes with --since HEAD")
        die(1, f"--since {args.since!r} is not a commit")
    base = r.stdout.strip()
    dropped: dict[str, list[str]] = {}
    tracked = []
    num = _git(cwd, "diff", "--numstat", "-z", "--no-renames", base, "--")
    for entry in filter(None, num.stdout.split("\0")):
        added, _, path = entry.split("\t", 2)
        why = _drop_reason(path, added == "-")
        (dropped.setdefault(why, []) if why else tracked).append(path)
    untracked = []
    for path in filter(None, _git(cwd, "ls-files", "--others", "--exclude-standard", "-z").stdout.split("\0")):
        why = _drop_reason(path, _is_binary(os.path.join(cwd, path)))
        (dropped.setdefault(why, []) if why else untracked).append(path)
    # ponytail: one argv entry per kept path; past ARG_MAX (tens of thousands of files), switch to :(exclude) pathspecs
    body = _git(cwd, "diff", "--no-renames", base, "--", *tracked).stdout if tracked else ""
    for path in untracked:
        body += _git(cwd, "diff", "--no-index", "--", "/dev/null", path).stdout
    head = [f"# diff since {base}"] + [f"dropped ({why}): {', '.join(sorted(p))}" for why, p in sorted(dropped.items())]
    sys.stdout.write("\n".join(head) + "\n\n" + _cap(body, args.max_lines or _policy()["diff_max_lines"]))


def register(sub, add) -> None:
    p = sub.add_parser("peer-review", help="the peer review loop")
    ops = p.add_subparsers(dest="op", required=True)
    q = ops.add_parser("new", help="make a fresh review dir for one run and print it")
    q.add_argument("kind")
    q.add_argument("--slug", help="a readable prefix; the dir is <slug>-<UTC stamp>")
    q.add_argument("--id", help="the exact dir name (the web UI passes its session id)")
    q.set_defaults(func=cmd_new)
    q = ops.add_parser("next", help="open the next round, or decide the open one (JSON on stdout)")
    q.add_argument("review_dir")
    q.add_argument("--artifact", required=True, help="the file under review")
    q.add_argument("--kind", help="round 1 only: prd, intake, dump, gh-issue or custom")
    q.add_argument("--lenses", help="round 1 only: comma-separated lenses (default from config)")
    q.add_argument("--prior", help="JSON list of {lens, id, disposition, reason} for the last round's findings")
    q.add_argument("--max-rounds", type=int, help="round budget for a new review (default from config)")
    q.add_argument("--more", action="store_true", help="the user chose one more round past the budget")
    q.set_defaults(func=cmd_next)
    q = ops.add_parser("verdict", help="validate and record one lens's verdict for the open round")
    q.add_argument("review_dir")
    q.add_argument("--lens", required=True)
    q.add_argument("--file", required=True, help="the verdict JSON, or - for stdin")
    q.set_defaults(func=cmd_verdict)
    q = ops.add_parser("diff", help="the change since a commit, minus secrets, binaries and lockfiles, capped")
    q.add_argument("--since", required=True, help="a commit, or @{u}; HEAD means uncommitted changes only")
    q.add_argument("--repo", default=".")
    q.add_argument("--max-lines", type=int, help="cap (default peer_review.diff_max_lines)")
    q.set_defaults(func=cmd_diff)
