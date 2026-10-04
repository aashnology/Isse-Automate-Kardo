"""
Regression tests for the user_memory.py race-condition fix: dismiss_workflow
and restore_workflow's read-modify-write now happen inside a cross-process
file lock, _save uses a unique temp filename, and _load recovers from a
corrupt/partial JSON file instead of crashing every call.
"""
import json
import multiprocessing
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

import user_memory


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(user_memory, "_STORE_PATH", str(tmp_path / "user_memory.json"))
    yield


def _dismiss_in_subprocess(store_path, workflow_name, barrier):
    """Runs in a separate process -- a real second process racing the main
    one, the same shape of contention as the MCP server and Flask bridge
    both writing data/user_memory.json."""
    import sys as _sys
    _sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
    import user_memory as um
    um._STORE_PATH = store_path
    barrier.wait()
    um.dismiss_workflow(workflow_name, reason="from a concurrent process")


def test_concurrent_writers_from_separate_processes_dont_lose_updates(tmp_path):
    """Both processes' dismissals must survive -- a naive unlocked
    read-modify-write drops whichever write finishes 'last-loaded, not
    last-saved', since both processes load the same starting state."""
    store_path = str(tmp_path / "user_memory.json")
    barrier = multiprocessing.Barrier(3)

    procs = [
        multiprocessing.Process(target=_dismiss_in_subprocess, args=(store_path, f"workflow_{i}", barrier))
        for i in range(2)
    ]
    for p in procs:
        p.start()
    barrier.wait()
    for p in procs:
        p.join(timeout=15)
        assert p.exitcode == 0

    with open(store_path) as f:
        state = json.load(f)
    assert set(state["dismissed_workflows"].keys()) == {"workflow_0", "workflow_1"}


def test_corrupt_json_file_recovers_instead_of_crashing(tmp_path):
    path = str(tmp_path / "user_memory.json")
    with open(path, "w") as f:
        f.write("{not valid json::")
    user_memory._STORE_PATH = path

    # Must not raise -- a half-written file (e.g. from a crash) shouldn't
    # take down every subsequent call.
    assert user_memory.is_dismissed("anything") is False
    result = user_memory.dismiss_workflow("bug_triage")
    assert result["status"] == "dismissed"


def test_save_uses_a_unique_temp_file_not_a_fixed_name(tmp_path):
    path = str(tmp_path / "user_memory.json")
    user_memory._STORE_PATH = path
    user_memory.dismiss_workflow("bug_triage")
    # No leftover fixed ".tmp" file, and nothing but the real store and
    # (transiently, only during a write) a uniquely-named temp file remain.
    assert not os.path.exists(path + ".tmp")


def test_stale_lock_is_broken_instead_of_hanging_forever(tmp_path, monkeypatch):
    path = str(tmp_path / "user_memory.json")
    monkeypatch.setattr(user_memory, "_STORE_PATH", path)
    monkeypatch.setattr(user_memory, "_LOCK_STALE_SECONDS", 0.05)
    monkeypatch.setattr(user_memory, "_LOCK_TIMEOUT_SECONDS", 2)

    stale_lock_path = path + ".lock"
    with open(stale_lock_path, "w") as f:
        f.write("99999999")  # a pid that (almost certainly) doesn't exist
    old_time = time.time() - 10
    os.utime(stale_lock_path, (old_time, old_time))

    result = user_memory.dismiss_workflow("bug_triage")
    assert result["status"] == "dismissed"
