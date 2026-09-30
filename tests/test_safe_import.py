"""
Regression tests for the arbitrary-file-read fix: discover_workflows_from_import
used to open() a model-supplied path directly. safe_import.resolve_import_path
is the one gate every import path now goes through.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from safe_import import resolve_import_path, UnsafeImportPath


@pytest.fixture
def import_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("IMPORT_DIR", str(tmp_path))
    return tmp_path


def test_accepts_a_plain_file_in_the_import_directory(import_dir):
    (import_dir / "events.json").write_text("{}")
    resolved = resolve_import_path("events.json", {".json"})
    assert resolved == os.path.realpath(str(import_dir / "events.json"))


def test_rejects_path_traversal_out_of_the_import_directory(import_dir, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "secret.json"
    outside.write_text('{"leak": true}')
    with pytest.raises(UnsafeImportPath):
        resolve_import_path(f"../{outside.parent.name}/secret.json", {".json"})


def test_rejects_absolute_paths_outside_the_import_directory(import_dir):
    with pytest.raises(UnsafeImportPath):
        resolve_import_path("/etc/passwd", {".json"})


def test_rejects_symlink_that_escapes_the_import_directory(import_dir, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "secret.json"
    outside.write_text('{"leak": true}')
    link = import_dir / "innocuous.json"
    os.symlink(outside, link)
    with pytest.raises(UnsafeImportPath):
        resolve_import_path("innocuous.json", {".json"})


def test_rejects_disallowed_extension(import_dir):
    (import_dir / "script.py").write_text("import os")
    with pytest.raises(UnsafeImportPath):
        resolve_import_path("script.py", {".json"})


def test_rejects_oversized_file(import_dir):
    big = import_dir / "big.json"
    big.write_bytes(b"0" * 2000)
    with pytest.raises(UnsafeImportPath):
        resolve_import_path("big.json", {".json"}, max_bytes=1000)


def test_rejects_missing_file(import_dir):
    with pytest.raises(UnsafeImportPath):
        resolve_import_path("does-not-exist.json", {".json"})


def test_mcp_tool_rejects_traversal_and_does_not_leak_content(import_dir, tmp_path_factory, monkeypatch):
    """End-to-end: the actual MCP tool function, not just the helper."""
    import mcp_server

    outside = tmp_path_factory.mktemp("outside") / "secret.json"
    outside.write_text('{"top_secret": "do not leak this string"}')

    result = mcp_server.discover_workflows_from_import(
        "activitywatch", f"../{outside.parent.name}/secret.json"
    )
    assert "error" in result
    assert "do not leak this string" not in str(result)
    assert "top_secret" not in str(result)


def test_mcp_tool_still_works_for_a_legitimate_import(import_dir, monkeypatch):
    import importlib
    import mcp_server
    importlib.reload(mcp_server)  # pick up the IMPORT_DIR set by the fixture

    (import_dir / "aw_export.json").write_text("[]")
    result = mcp_server.discover_workflows_from_import("activitywatch", "aw_export.json")
    assert result["source"] == "activitywatch"
    assert result["events_imported"] == 0
