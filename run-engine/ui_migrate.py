"""One-time cleanup of the old engine data on the first `aiw ui` start (FR-8)."""

from __future__ import annotations

import os
import shutil

from shared import warn

MARKER = "migrated-dev-workflow"
OLD = (
    "runs",
    "pipelines",
    "flows",
    "maintree",
    "locks",
    "gh-status.json",
    "titles.json",
    "grind_requests.json",
    "grind_notified.json",
)


def clear_old_data(data_dir: str) -> list:
    """Remove the old engine paths once, logging each; later calls do nothing. Returns the removed paths."""
    marker = os.path.join(data_dir, MARKER)
    if os.path.exists(marker):
        return []
    removed = []
    for name in OLD:
        p = os.path.join(data_dir, name)
        try:
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p, ignore_errors=True)
            elif os.path.lexists(p):
                os.remove(p)
            else:
                continue
        except OSError as e:
            warn(f"could not remove old engine data {p}: {e}")
            continue
        removed.append(p)
        print(f"removed old engine data: {p}", flush=True)
    os.makedirs(data_dir, exist_ok=True)
    open(marker, "w").close()
    return removed
