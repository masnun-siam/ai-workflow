#!/usr/bin/env python3
"""`aiw` — the CLI behind the plugin's skills.

Invoked as `aiw` (plugin bin/). NOT as `route`: that is the macOS/BSD/net-tools network
command, and on a default macOS PATH /sbin shadows the plugin bin.

Usage:
  aiw ui ...           # workflow control UI server
  aiw service install|restart|uninstall|status  # run aiw ui as a macOS LaunchAgent
  aiw paths            # print resolved plugin/data paths as JSON
  aiw ask ...          # record a gate question for a headless run
  aiw ci status <pr-ref> [--watch]
  aiw threads list|resolve <pr-ref|node-id...>
  aiw grind-mode [--pr <url>]  # deep or simple: the PR's dispatch decides, else Settings; read by /pr-grind each round
  aiw dispatch ...     # run an epic's child issues as parallel lanes
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ask  # noqa: E402
import ci  # noqa: E402
import dispatch  # noqa: E402
import dispatch_cli  # noqa: E402
import threads  # noqa: E402
import ui_server  # noqa: E402
import ui_service  # noqa: E402
from shared import data_dir, die  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(HERE)


def cmd_paths(args):
    """Resolve every path the skills need, once."""
    dd = data_dir()
    out = {
        "plugin_root": PLUGIN_ROOT,
        "data_dir": dd,
        "pr_grind_dir": os.path.join(dd, "pr-grind"),
        "channels": os.path.join(dd, "channels.json"),
        "checkouts": dispatch.checkouts_path(),
    }
    os.makedirs(out["pr_grind_dir"], exist_ok=True)
    print(json.dumps(out, indent=2))


def cmd_grind_mode(args) -> None:
    print(dispatch_cli.grind_mode(args.pr))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="aiw", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add(name, help_text):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("run_dir")
        p.add_argument("--repo", help="repo/worktree root (default: cwd)")
        return p

    p_paths = sub.add_parser("paths", help="print resolved plugin/data paths as JSON")
    p_paths.set_defaults(func=cmd_paths)

    p_gm = sub.add_parser("grind-mode", help="print the grind mode: deep or simple")
    p_gm.add_argument("--pr", default=None, help="PR url: the mode of the dispatch that owns it")
    p_gm.set_defaults(func=cmd_grind_mode)

    # Each module owns its own argparse wiring.
    for module in (threads, ci, ui_server, ui_service, ask, dispatch_cli):
        module.register(sub, add)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except ValueError as exc:
        die(5, str(exc))


if __name__ == "__main__":
    main()
