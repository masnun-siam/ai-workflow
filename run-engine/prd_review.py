"""`aiw prd-review` — the PRD peer review loop: a validated verdict write and a pure decision.

A panel of single-lens reviewers (config `prd_review.lenses`) reads one PRD per round. Each
writes its verdict through `verdict`, which refuses a finding that does not quote the PRD or name
one of its headings, and a verdict for a stale PRD or an old round. `next` opens rounds and
decides: only a `blocking` lens blocks; a finding that needs a product decision goes to the user;
a spent round budget hands over to the user and never auto-approves.

Files, one directory per review: `round-<n>/request.json` (the PRD hash and the worker's
dispositions of the prior round's findings) and `round-<n>/<lens>.json`.
"""

from __future__ import annotations

import hashlib
import re

SEVERITIES = ("blocker", "major", "minor")
MAX_FINDINGS = 8
MIN_QUOTE_WORDS = 4  # a shorter quote ("the") matches almost any PRD and proves nothing
DISPOSITIONS = ("fixed", "dismissed", "decided")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def norm(text: str) -> str:
    """Whitespace and markdown emphasis ignored, so `**must**  retry` matches `must retry`."""
    return " ".join(re.sub(r"[*_`]", "", text or "").split()).casefold()


def headings(prd: str) -> set[str]:
    # ponytail: also matches ## lines inside fenced code; PRDs rarely fence headings
    return {norm(m) for m in re.findall(r"^#{2,3}\s+(.+?)\s*$", prd, re.M)}


def validate(v, prd: str, request: dict, lenses: dict) -> list[str]:
    """Reasons to refuse this verdict; [] means it may be written."""
    if not isinstance(v, dict):
        return ["a verdict is a JSON object"]
    errs = []
    if v.get("lens") not in lenses:
        errs.append(f"unknown lens {v.get('lens')!r}; the panel is {', '.join(lenses)}")
    if v.get("round") != request["round"]:
        errs.append(f"round {v.get('round')!r} is not the open round {request['round']}")
    if v.get("prd_sha256") != request["prd_sha256"]:
        errs.append("stale: prd_sha256 is not the hash of the PRD this round reviews")
    findings = v.get("findings")
    if not isinstance(findings, list):
        return errs + ["findings must be a list"]
    if len(findings) > MAX_FINDINGS:
        errs.append(f"{len(findings)} findings; at most {MAX_FINDINGS}, most severe first")
    if v.get("verdict") not in ("approve", "changes"):
        errs.append("verdict must be approve or changes")
    body, heads = norm(prd), headings(prd)
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
            errs.append(f"{tag}: quote not found in the PRD")
        elif not quote and section not in heads:
            errs.append(f"{tag}: without a quote, section must be one of the PRD's ##/### headings")
        if v.get("verdict") == "approve" and f.get("severity") in ("blocker", "major"):
            errs.append(f"{tag}: an approve verdict cannot carry a {f['severity']}")
    return errs


def check_prior(prior, finding_ids: set) -> list[str]:
    """The worker's answer to every finding of the round being closed, so none is dropped."""
    if not isinstance(prior, list):
        return ["--prior must be a JSON list of {id, disposition, reason}"]
    errs, seen = [], set()
    for p in prior:
        if not isinstance(p, dict) or p.get("disposition") not in DISPOSITIONS:
            errs.append(f"{p!r}: disposition must be one of {', '.join(DISPOSITIONS)}")
        elif not (isinstance(p.get("reason"), str) and p["reason"].strip()):
            errs.append(f"{p.get('id')!r}: needs a reason")
        else:
            seen.add(p.get("id"))
    errs += [f"no disposition for finding {i}" for i in sorted(finding_ids - seen)]
    return errs


def decide(verdicts: dict, lenses: dict, rnd: int, max_rounds: int) -> dict:
    """done | revise | ask, from one complete round of verdicts. Pure."""
    missing = [lens for lens in lenses if lens not in verdicts]
    if missing:
        raise ValueError(f"round {rnd} is missing verdicts from: {', '.join(missing)}")
    out = {"round": rnd, "blockers": [], "decisions": [], "advisory_blockers": [], "advisory": []}
    for lens, cfg in lenses.items():
        for f in verdicts[lens]["findings"]:
            f = {**f, "lens": lens}
            if f.get("needs_decision"):
                out["decisions"].append(f)
            elif cfg.get("blocking"):
                if f["severity"] in ("blocker", "major"):
                    out["blockers"].append(f)
            elif f["severity"] == "blocker":
                out["advisory_blockers"].append(f)
            else:
                out["advisory"].append(f)
    if out["decisions"]:
        return {**out, "action": "ask", "reason": "decision"}
    if out["blockers"]:
        if rnd >= max_rounds:
            return {**out, "action": "ask", "reason": "cap"}
        return {**out, "action": "revise", "reason": "blocking findings"}
    return {**out, "action": "done", "reason": "the blocking lens approves"}


import json  # noqa: E402  (kept beside the I/O half, the top of this file is pure)
import os  # noqa: E402

from shared import die, load_config, read_json, write_json  # noqa: E402


def _policy() -> dict:
    return load_config(None)["prd_review"]


def _rounds(review_dir: str) -> int:
    try:
        names = os.listdir(review_dir)
    except FileNotFoundError:
        return 0
    return max((int(m.group(1)) for n in names if (m := re.fullmatch(r"round-(\d+)", n))), default=0)


def _read_prd(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        die(3, f"cannot read the PRD: {exc}")


def _open(review_dir: str, rnd: int, prd_path: str, text: str, prior, max_rounds: int, lenses: dict) -> None:
    write_json(
        os.path.join(review_dir, f"round-{rnd}", "request.json"),
        {
            "round": rnd,
            "prd_path": os.path.abspath(prd_path),
            "prd_sha256": sha(text),
            "max_rounds": max_rounds,
            "lenses": list(lenses),
            "prior": prior,
        },
    )
    print(json.dumps({"action": "review", "round": rnd, "lenses": list(lenses), "dir": os.path.abspath(review_dir)}))


def cmd_next(args) -> None:
    policy = _policy()
    lenses = policy["lenses"]
    text = _read_prd(args.prd)
    prior = read_json(args.prior) if args.prior else []
    n = _rounds(args.review_dir)
    if n == 0:
        _open(args.review_dir, 1, args.prd, text, prior, args.max_rounds or policy["max_rounds"], lenses)
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
    d = decide(verdicts, {k: lenses.get(k, {}) for k in req["lenses"]}, n, req["max_rounds"])
    if sha(text) != req["prd_sha256"] and (n < max_rounds):
        ids = {f["id"] for v in verdicts.values() for f in v["findings"]}
        if ids and not args.prior:
            die(2, f"round {n} had findings; pass --prior <dispositions.json> so the next round sees them")
        errs = check_prior(prior, ids)
        if errs:
            die(5, "--prior refused:\n- " + "\n- ".join(errs))
        _open(args.review_dir, n + 1, args.prd, text, prior, max_rounds, lenses)
        return
    print(json.dumps(d))


def cmd_verdict(args) -> None:
    n = _rounds(args.review_dir)
    if n == 0:
        die(3, "no review round is open: run `aiw prd-review next` first")
    rd = os.path.join(args.review_dir, f"round-{n}")
    req = read_json(os.path.join(rd, "request.json"))
    v = read_json(args.file)
    lenses = {k: {} for k in req["lenses"]}
    if isinstance(v, dict) and v.get("lens") != args.lens:
        die(5, f"the file is lens {v.get('lens')!r}, not --lens {args.lens}")
    errs = validate(v, _read_prd(req["prd_path"]), req, lenses)
    if errs:
        die(5, "verdict refused:\n- " + "\n- ".join(errs))
    write_json(os.path.join(rd, f"{args.lens}.json"), v)
    print(f"round {n}: {args.lens} {v['verdict']}, {len(v['findings'])} finding(s)")


def register(sub, add) -> None:
    p = sub.add_parser("prd-review", help="the PRD peer review loop")
    ops = p.add_subparsers(dest="op", required=True)
    q = ops.add_parser("next", help="open the next round, or decide the open one (JSON on stdout)")
    q.add_argument("review_dir")
    q.add_argument("--prd", required=True, help="the PRD under review")
    q.add_argument("--prior", help="JSON list of {id, disposition, reason} for the last round's findings")
    q.add_argument("--max-rounds", type=int, help="round budget for a new review (default from config)")
    q.add_argument("--more", action="store_true", help="the user chose one more round past the budget")
    q.set_defaults(func=cmd_next)
    q = ops.add_parser("verdict", help="validate and record one lens's verdict for the open round")
    q.add_argument("review_dir")
    q.add_argument("--lens", required=True)
    q.add_argument("--file", required=True, help="the verdict JSON")
    q.set_defaults(func=cmd_verdict)
