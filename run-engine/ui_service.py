"""`aiw service install|restart|uninstall|status`: run `aiw ui` as a macOS LaunchAgent. Stdlib only.

Why a launcher: macOS grants Full Disk Access to a binary's code identity. Homebrew's Python is
ad-hoc signed, so every `brew upgrade` gives it a new identity and silently drops the grant; a daemon
then reads repos under ~/Documents with `Operation not permitted` and cannot show the prompt. The
LaunchAgent's program is a tiny launcher compiled once into the data dir and never rebuilt, so the
grant you give it survives Homebrew, Python and Claude upgrades. It spawns (not execs) the server and
waits, so it stays the responsible process macOS checks for everything the server starts.
"""

from __future__ import annotations

import os
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile

from shared import data_dir, die

LABEL = "dev.aiw.ui"
ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))  # plugin root
FDA_PANE = "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"

# Generic on purpose: no paths compiled in, so the binary (and its grant) never needs rebuilding.
LAUNCHER_C = r"""
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <sys/wait.h>
extern char **environ;
static pid_t child;
static void fwd(int s) { if (child > 0) kill(child, s); }
int main(int argc, char **argv) {
  if (argc < 2) { fprintf(stderr, "usage: %s cmd [args...]\n", argv[0]); return 64; }
  signal(SIGTERM, fwd); signal(SIGINT, fwd); signal(SIGHUP, fwd);
  if (posix_spawn(&child, argv[1], NULL, NULL, argv + 1, environ) != 0) { perror("posix_spawn"); return 127; }
  int st;
  while (waitpid(child, &st, 0) < 0) {}
  return WIFEXITED(st) ? WEXITSTATUS(st) : 128 + WTERMSIG(st);
}
"""


def launcher_path() -> str:
    return os.path.join(data_dir(), "bin", "aiw-ui-launcher")


def plist_path() -> str:
    return os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")


def plist_dict(launcher: str, root: str, log: str) -> dict:
    """A login zsh, so the server sees your PATH (claude, gh, git) as in a terminal."""
    aiw = shlex.quote(os.path.join(root, "bin", "aiw"))
    return {
        "Label": LABEL,
        "ProgramArguments": [launcher, "/bin/zsh", "-lc", f"exec {aiw} ui"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Interactive",
        "StandardErrorPath": log,
        "StandardOutPath": "/dev/null",
    }


def build_launcher(path: str, run=subprocess.run) -> bool:
    """Compile the launcher once. False when it already exists: rebuilding would drop its grant."""
    if os.path.exists(path):
        return False
    cc = shutil.which("cc") or die(2, "no C compiler: run `xcode-select --install`, then retry")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "launcher.c")
        with open(src, "w") as f:
            f.write(LAUNCHER_C)
        p = run([cc, "-O2", "-o", path, src], capture_output=True, text=True)
        if p.returncode:
            die(2, f"compiling the launcher failed: {(p.stderr or p.stdout).strip()[:300]}")
    return True


def _launchctl(*args, check=False):
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=check)


def _target() -> str:
    return f"gui/{os.getuid()}"


def loaded() -> bool:
    return _launchctl("print", f"{_target()}/{LABEL}").returncode == 0


def cmd_install(args) -> None:
    if sys.platform != "darwin":
        die(2, "aiw service is macOS only; elsewhere run `aiw ui` under your own supervisor")
    launcher = launcher_path()
    built = build_launcher(launcher)
    log = os.path.join(data_dir(), "ui.err.log")
    os.makedirs(os.path.dirname(plist_path()), exist_ok=True)
    with open(plist_path(), "wb") as f:
        plistlib.dump(plist_dict(launcher, ROOT, log), f)
    if loaded():
        _launchctl("bootout", f"{_target()}/{LABEL}")
    p = _launchctl("bootstrap", _target(), plist_path())
    if p.returncode:
        die(3, f"launchctl bootstrap failed: {(p.stderr or p.stdout).strip()}")
    print(f"aiw ui runs as LaunchAgent {LABEL} (log: {log}).")
    print(f"{'Built' if built else 'Kept'} the launcher: {launcher}")
    print("One time: add that file in System Settings > Privacy & Security > Full Disk Access")
    print("(press Cmd-Shift-G in the file picker and paste the path), then run `aiw service restart`.")
    print("Stop any other `aiw ui` (e.g. `supervisorctl stop aiw-ui`) so they don't fight over the port.")
    if not args.no_open:
        subprocess.run(["open", FDA_PANE], check=False)


def cmd_restart(args) -> None:
    """The LaunchAgent if installed, else the older supervisord program."""
    if os.path.exists(plist_path()):
        p = _launchctl("kickstart", "-k", f"{_target()}/{LABEL}")
    else:
        p = subprocess.run(["supervisorctl", "restart", "aiw-ui"], capture_output=True, text=True)
    sys.stdout.write(p.stdout)
    sys.stderr.write(p.stderr)
    sys.exit(p.returncode)


def cmd_uninstall(args) -> None:
    if loaded():
        _launchctl("bootout", f"{_target()}/{LABEL}")
    if os.path.exists(plist_path()):
        os.remove(plist_path())
    print(f"Removed LaunchAgent {LABEL}. The launcher stays at {launcher_path()} so its grant is kept.")


def cmd_status(args) -> None:
    print(f"plist:    {plist_path()} ({'present' if os.path.exists(plist_path()) else 'missing'})")
    print(f"loaded:   {'yes' if loaded() else 'no'}")
    print(f"launcher: {launcher_path()} ({'present' if os.path.exists(launcher_path()) else 'missing'})")


def register(sub, _add) -> None:
    p = sub.add_parser("service", help="run `aiw ui` as a macOS LaunchAgent that keeps Full Disk Access")
    s = p.add_subparsers(dest="service_cmd", required=True)
    q = s.add_parser("install", help="build the launcher once, write and load the LaunchAgent")
    q.add_argument("--no-open", action="store_true", help="don't open the Full Disk Access settings pane")
    q.set_defaults(func=cmd_install)
    s.add_parser("restart", help="restart the server (LaunchAgent, else supervisord)").set_defaults(func=cmd_restart)
    s.add_parser("uninstall", help="unload and remove the LaunchAgent").set_defaults(func=cmd_uninstall)
    s.add_parser("status", help="show the LaunchAgent and launcher state").set_defaults(func=cmd_status)
