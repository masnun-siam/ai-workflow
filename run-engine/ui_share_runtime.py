"""Share runtime (FR-11, FR-12): owns the public share listener and the funnel for `aiw ui`.

Both exist only while a share is live. `ensure_up` brings them up, `sync` reconciles after a share action,
`tick` (once a minute) ends shares whose PRD stopped being eligible, `stop` runs on a clean exit. The
listener port and funnel port are recorded in `<data_dir>/share-runtime.json` so a restart serves the same
link. This module never reads a PRD itself and never logs or prints a token.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time

import dispatch
import shared
import ui_share_public
import ui_shares
import ui_tailscale
from shared import warn

_lock = threading.RLock()
_server = None  # PublicServer, bound; serving once `_thread` is set
_thread = None
_funnel = None  # funnel_up's result while the funnel is up
_reachable = False
_base = None
_ui_port = None  # the UI's requested tailnet port: funnel must never share it
_enabled = True


def configure(ui_https_port, tailscale_enabled: bool = True) -> None:
    global _ui_port, _enabled
    _ui_port, _enabled = ui_https_port, tailscale_enabled


def _record_path() -> str:
    return os.path.join(shared.data_dir(), "share-runtime.json")


def _read_record():
    try:
        with open(_record_path(), encoding="utf-8") as f:
            rec = json.load(f)
        return {"listener_port": int(rec["listener_port"]), "funnel_port": int(rec["funnel_port"])}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_record(listener_port: int, funnel_port: int) -> None:
    os.makedirs(shared.data_dir(), exist_ok=True)
    shared.atomic_write_text(_record_path(), json.dumps({"listener_port": listener_port, "funnel_port": funnel_port}))


def _delete_record() -> None:
    try:
        os.remove(_record_path())
    except OSError:
        pass


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) != 0


def _live() -> list:
    return [s for s in ui_shares.list_shares() if s["state"] == "live"]


def _close_listener() -> None:
    global _server, _thread
    server, thread, _server, _thread = _server, _thread, None, None
    if server is None:
        return
    if thread is not None:
        server.shutdown()
    server.server_close()


def _funnel_port(rec) -> int:
    return rec["funnel_port"] if rec else ui_tailscale.funnel_port(_ui_port)


def ensure_up() -> dict:
    """Listener + funnel up for the live shares. Raises ui_tailscale.FunnelError."""
    global _server, _thread, _funnel, _reachable, _base
    with _lock:
        if _server is not None and _funnel is not None:
            return _state()
        if not _enabled:
            raise ui_tailscale.FunnelError(
                "unavailable", "Public sharing needs Tailscale; aiw ui runs with --no-tailscale"
            )
        rec = _read_record()
        fport = _funnel_port(rec)
        if fport == _ui_port:
            msg = f"Funnel port {fport} is the UI's own tailnet port; not publishing the UI"
            warn("shares: " + msg)
            _reachable = False
            raise ui_tailscale.FunnelError("port_taken", msg)
        started = _server is None
        if started:
            want = rec["listener_port"] if rec and _port_free(rec["listener_port"]) else 0
            _server = ui_share_public.make_server(want)
        lport = _server.server_address[1]
        ours = (rec["listener_port"],) if rec and rec["listener_port"] != lport else ()
        try:
            res = ui_tailscale.funnel_up(lport, fport, ours)
        except ui_tailscale.FunnelError:
            _reachable = False
            if started:
                _close_listener()
            raise
        _funnel, _base, _reachable = res, res["base"], True
        _server.allowed_hosts = {res["host"].lower()}
        if _thread is None:  # serve only once the funnel is up: shutdown() would block on a loop never started
            _thread = threading.Thread(target=_server.serve_forever, daemon=True)
            _thread.start()
        _write_record(lport, fport)
        return _state()


def _state() -> dict:
    return {
        "base": _funnel["base"],
        "host": _funnel["host"],
        "https_port": _funnel["https_port"],
        "listener_port": _server.server_address[1],
    }


def _teardown(keep_record: bool = False) -> None:
    global _funnel, _reachable
    with _lock:
        rec = _read_record()
        if _funnel is not None:
            ui_tailscale.funnel_down(_funnel["https_port"])
        elif rec and not keep_record and _is_ours(rec):  # leftover of an unclean exit
            ui_tailscale.funnel_down(rec["funnel_port"])
        _funnel, _reachable = None, False
        _close_listener()
        if not keep_record:
            _delete_record()


def _is_ours(rec) -> bool:
    proxy = ui_tailscale.funnel_handler(rec["funnel_port"])
    return proxy is not None and proxy.rstrip("/") == f"http://127.0.0.1:{rec['listener_port']}"


def sync() -> None:
    """After a share action: live shares -> bring the funnel up (retry); none -> take everything down."""
    global _reachable
    with _lock:
        if _live():
            try:
                ensure_up()
            except ui_tailscale.FunnelError as e:
                _reachable = False
                warn(f"shares: not public: {e}")
        elif _funnel is not None or _server is not None or _read_record():
            _teardown()


def reachable() -> bool:
    return _reachable


def link(share: dict):
    """The public URL of a share, or None while the node's DNS name is unknown."""
    global _base
    with _lock:
        if _base is None:
            me = ui_tailscale.node()
            fport = _funnel_port(_read_record())
            if me is None or fport == _ui_port:
                return None
            _base = f"https://{me['dns']}:{fport}"
        return f"{_base}/s/{share['token']}"


def summary():
    """`shares: <n> live on <base>` while the funnel is up, else None. No token."""
    with _lock:
        return f"shares: {len(_live())} live on {_funnel['base']}" if _funnel is not None else None


def _refresh_all() -> list:
    """Refresh every live share, each isolated from the others' failures. Returns the shares ended."""
    ended = []
    checkouts = dispatch.read_checkouts()
    for share in _live():
        try:
            after = ui_shares.refresh(share["id"], checkouts.get(share["repo"]))
            if after is None or after["state"] != "live":
                ended.append(share["id"])
        except Exception as e:  # noqa: BLE001 - one bad share must not stop the others
            warn(f"share tick failed: {type(e).__name__}")
    return ended


def start() -> None:
    _refresh_all()
    sync()


def tick() -> None:
    global _reachable
    ended = _refresh_all()
    with _lock:
        if ended and not _live():
            sync()
        elif _funnel is not None and _server is not None:
            _reachable = ui_tailscale.funnel_reachable(_server.server_address[1], _funnel["https_port"])


def start_timer(interval: float = 60.0) -> threading.Thread:
    def loop():
        while True:
            try:
                tick()
            except Exception as e:  # noqa: BLE001 - keep the timer alive
                warn(f"share timer tick failed: {type(e).__name__}")
            time.sleep(interval)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t


def stop() -> None:
    """Clean exit: funnel off, listener closed; the record stays while shares are live. Never raises."""
    try:
        with _lock:
            _teardown(keep_record=bool(_live()))
    except Exception as e:  # noqa: BLE001 - runs while the server exits
        warn(f"shares: stop failed: {type(e).__name__}")
