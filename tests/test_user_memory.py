import importlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

import user_memory


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Point the module at a throwaway file per test so tests can't
    interfere with each other or with a real data/user_memory.json."""
    monkeypatch.setattr(user_memory, "_STORE_PATH", str(tmp_path / "user_memory.json"))
    yield


def test_dismiss_then_is_dismissed():
    assert user_memory.is_dismissed("weekly_reporting") is False
    user_memory.dismiss_workflow("weekly_reporting", reason="I always review it myself")
    assert user_memory.is_dismissed("weekly_reporting") is True


def test_dismissal_persists_across_module_reload(tmp_path, monkeypatch):
    # Simulates "server restarted" / "new Alexa+ session, different process
    # in principle" -- the whole point of this module is that this survives.
    path = str(tmp_path / "user_memory.json")
    monkeypatch.setattr(user_memory, "_STORE_PATH", path)
    user_memory.dismiss_workflow("bug_triage")

    reloaded = importlib.reload(user_memory)
    monkeypatch.setattr(reloaded, "_STORE_PATH", path)
    assert reloaded.is_dismissed("bug_triage") is True


def test_restore_reverses_a_dismissal():
    user_memory.dismiss_workflow("onboarding_new_partner")
    result = user_memory.restore_workflow("onboarding_new_partner")
    assert result["status"] == "restored"
    assert user_memory.is_dismissed("onboarding_new_partner") is False


def test_restore_unknown_workflow_errors_cleanly():
    result = user_memory.restore_workflow("never_dismissed")
    assert "error" in result


def test_list_dismissed_includes_reason_and_timestamp():
    user_memory.dismiss_workflow("weekly_reporting", reason="handled manually")
    listed = user_memory.list_dismissed()
    assert len(listed) == 1
    assert listed[0]["workflow_name"] == "weekly_reporting"
    assert listed[0]["reason"] == "handled manually"
    assert "dismissed_at" in listed[0]


def test_a_failed_write_does_not_corrupt_prior_state(tmp_path, monkeypatch):
    path = str(tmp_path / "user_memory.json")
    monkeypatch.setattr(user_memory, "_STORE_PATH", path)
    user_memory.dismiss_workflow("bug_triage")

    # Simulate a write failure partway through _save -- prior good state on
    # disk must survive untouched, same guarantee as data_adapters/export.
    def broken_save(state):
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(user_memory, "_save", broken_save)
    with pytest.raises(OSError):
        user_memory.dismiss_workflow("weekly_reporting")

    monkeypatch.undo()
    monkeypatch.setattr(user_memory, "_STORE_PATH", path)
    assert user_memory.is_dismissed("bug_triage") is True
    assert user_memory.is_dismissed("weekly_reporting") is False
