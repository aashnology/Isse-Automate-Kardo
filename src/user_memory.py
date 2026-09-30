"""
The one piece of state in this project that's meant to outlive a single
Alexa+ session: if you tell it "stop suggesting automation for X," that has
to still be true the next time you talk to it -- tomorrow, next week, after
the server restarts. Everything else in this project (a proposal_id from
propose_automation, for instance) is deliberately short-lived and in-memory,
because it's answering "did you confirm *this specific* proposal," which
has no meaning after the process restarts. A dismissal is different: it's a
standing preference, not a transaction, so it's the one thing here backed
by a file on disk rather than a dict in memory.

Storage is a single JSON file (data/user_memory.json) rather than a real
database, on purpose -- this project has exactly one user per deployment
(there's no multi-tenant auth story here), so a file is the honest amount
of infrastructure for what this actually needs, not a database bolted on
to look more "production" than the rest of the project claims to be.

That single file is shared by two live processes in this project's own
deployment (the MCP server and the Flask/Hexi bridge both import this
module), so every read-modify-write below happens inside a real
cross-process lock -- not just a threading.Lock, which wouldn't stop the
other process from racing in. The lock is a plain lockfile created with
O_CREAT|O_EXCL, which is atomic on both POSIX and Windows, so this doesn't
need a third-party dependency to be correct.
"""

import json
import os
import tempfile
import time
from datetime import datetime, timezone

_STORE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "user_memory.json")
_LOCK_STALE_SECONDS = 30  # a lock older than this means its owner crashed; break it rather than hang forever
_LOCK_TIMEOUT_SECONDS = 10
_LOCK_POLL_SECONDS = 0.05

MAX_WORKFLOW_NAME_LEN = 200
MAX_REASON_LEN = 500


class _FileLock:
    """A minimal cross-process lock. Not reentrant, not fair, not meant for
    high contention -- this project has one user per deployment, so the
    only real contention is the MCP server and the web bridge occasionally
    landing on the same millisecond.

    The lock path is derived from _STORE_PATH at acquire time (not cached
    at import time) so tests that monkeypatch _STORE_PATH to a temp file
    get an isolated lock file too, instead of all sharing one real
    data/user_memory.json.lock."""

    def __enter__(self):
        self._lock_path = _STORE_PATH + ".lock"
        deadline = time.time() + _LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fd = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self._lock_path) > _LOCK_STALE_SECONDS:
                        os.remove(self._lock_path)  # previous holder crashed without cleaning up
                        continue
                except FileNotFoundError:
                    continue  # the lock was released between our check and now -- retry immediately
                if time.time() > deadline:
                    raise TimeoutError("Timed out waiting for user_memory's file lock.")
                time.sleep(_LOCK_POLL_SECONDS)

    def __exit__(self, *exc_info):
        try:
            os.remove(self._lock_path)
        except FileNotFoundError:
            pass


def _load():
    if not os.path.exists(_STORE_PATH):
        return {"dismissed_workflows": {}}
    try:
        with open(_STORE_PATH) as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        # A crash mid-write (before the atomic os.replace in _save) is the
        # only way this file should ever be unreadable, since _save never
        # leaves a partial file at _STORE_PATH itself. Treat it as empty
        # rather than taking the whole server down on every call.
        return {"dismissed_workflows": {}}
    if not isinstance(state, dict) or not isinstance(state.get("dismissed_workflows"), dict):
        return {"dismissed_workflows": {}}
    return state


def _save(state):
    os.makedirs(os.path.dirname(_STORE_PATH), exist_ok=True)
    # A unique temp name (not a fixed ".tmp" suffix) so two processes
    # writing at once can't stomp on each other's in-progress temp file --
    # the lock below already serializes the read-modify-write, but this
    # keeps _save itself safe to call independently too.
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(_STORE_PATH), prefix=".user_memory_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp_path, _STORE_PATH)  # atomic -- a failed write can't corrupt prior state
    except Exception:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass
        raise


def dismiss_workflow(workflow_name: str, reason: str = "") -> dict:
    """Record that automation shouldn't be suggested for this workflow again,
    until explicitly restored. Persists across restarts and sessions."""
    workflow_name = str(workflow_name)[:MAX_WORKFLOW_NAME_LEN]
    reason = str(reason)[:MAX_REASON_LEN]
    with _FileLock():
        state = _load()
        state["dismissed_workflows"][workflow_name] = {
            "reason": reason,
            "dismissed_at": datetime.now(timezone.utc).isoformat(),
        }
        _save(state)
    return {"workflow_name": workflow_name, "status": "dismissed", "reason": reason}


def restore_workflow(workflow_name: str) -> dict:
    with _FileLock():
        state = _load()
        if workflow_name not in state["dismissed_workflows"]:
            return {"error": f"'{workflow_name}' isn't currently dismissed."}
        del state["dismissed_workflows"][workflow_name]
        _save(state)
    return {"workflow_name": workflow_name, "status": "restored"}


def is_dismissed(workflow_name: str) -> bool:
    return workflow_name in _load()["dismissed_workflows"]


def list_dismissed() -> list:
    state = _load()
    return [
        {"workflow_name": name, **info}
        for name, info in state["dismissed_workflows"].items()
    ]
