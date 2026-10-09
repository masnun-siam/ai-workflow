"""Serve `aiw ui` on the owner's tailnet through `tailscale serve` (tailnet-only; never funnel).

The UI keeps listening on 127.0.0.1; `tailscale serve` terminates TLS and proxies to it. The UI
can start agents, so only the node owner may use it: requests that arrive under the tailnet
name must carry the `Tailscale-User-Login` header serve adds, equal to the owner's login.
A serve port that already has a handler is never overwritten. Stdlib only.
"""

from __future__ import annotations

import json
import shutil
import subprocess

from shared import warn

HTTPS_PORTS = (443, 8443, 10000)  # the only ports tailscale serve terminates TLS on
DEFAULT_HTTPS_PORT = 443  # a clean https://<node>.<tailnet>.ts.net; an occupied port is never overwritten


def _run(args: list[str], timeout: int = 15):
    return subprocess.run(["tailscale", *args], capture_output=True, text=True, timeout=timeout)


def _json(args: list[str]):
    proc = _run(args)
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return None


def node():
    """{"dns", "login"} of this running node, or None when tailscale is missing, stopped or logged out."""
    if not shutil.which("tailscale"):
        return None
    try:
        st = _json(["status", "--json"])
    except (OSError, subprocess.SubprocessError):
        return None
    if not isinstance(st, dict) or st.get("BackendState") != "Running":
        return None
    me = st.get("Self") or {}
    dns = str(me.get("DNSName") or "").rstrip(".")
    login = ((st.get("User") or {}).get(str(me.get("UserID"))) or {}).get("LoginName")
    return {"dns": dns, "login": login} if dns and login else None


def hosts(dns: str, https_port: int) -> set[str]:
    """Host header values the proxy presents: bare on 443, with the port otherwise."""
    return {dns} if https_port == 443 else {f"{dns}:{https_port}"}


def up(local_port: int, https_port: int = DEFAULT_HTTPS_PORT):
    """Start serving 127.0.0.1:<local_port> on the tailnet. Returns
    {"url", "hosts", "login", "https_port"}, or None (with a printed reason) if it cannot."""
    if https_port not in HTTPS_PORTS:
        warn(f"tailscale: --tailscale-port must be one of {', '.join(map(str, HTTPS_PORTS))}; not serving")
        return None
    me = node()
    if me is None:
        return None
    try:
        current = _json(["serve", "status", "--json"]) or {}
        taken = (current.get("Web") or {}).get(f"{me['dns']}:{https_port}")
        proc = None
        if taken:
            target = next(iter((taken.get("Handlers") or {}).values()), {}).get("Proxy", "something else")
            if target.rstrip("/") == f"http://127.0.0.1:{local_port}":
                # left by an earlier aiw ui on this port that exited without cleaning up (kill, crash, closed
                # terminal): it already points here, so adopt it instead of refusing and serving a 403
                target = None
        if taken and target:
            warn(f"tailscale: https port {https_port} already serves {target}; not overwriting "
                 f"(pass --tailscale-port to use another, or --no-tailscale)")
            return None
        if not taken:
            proc = _run(["serve", "--bg", f"--https={https_port}", f"http://127.0.0.1:{local_port}"])
    except (OSError, subprocess.SubprocessError) as exc:
        warn(f"tailscale: could not run serve ({type(exc).__name__}); not serving")
        return None
    if proc is not None and proc.returncode != 0:
        warn(f"tailscale: serve failed: {(proc.stderr or proc.stdout or '').strip()[:200]}")
        return None
    suffix = "" if https_port == 443 else f":{https_port}"
    return {"url": f"https://{me['dns']}{suffix}", "hosts": hosts(me["dns"], https_port),
            "login": me["login"], "https_port": https_port}


def down(https_port: int) -> None:
    """Remove the handler `up` added. Never raises: this runs while the server is exiting."""
    try:
        _run(["serve", f"--https={https_port}", "off"])
    except (OSError, subprocess.SubprocessError) as exc:
        warn(f"tailscale: could not remove the serve handler on {https_port} ({type(exc).__name__}); "
             f"run `tailscale serve --https={https_port} off`")
