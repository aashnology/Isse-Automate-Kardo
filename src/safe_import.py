"""
Path safety for MCP tools that take a file path as a parameter.

discover_workflows_from_import(file_path=...) used to hand a model-supplied
string straight to open(). An MCP client (or a prompt-injected one) could
pass "/etc/passwd", "../../.env", or a symlink pointing outside the project
to read arbitrary files the server process can see. This module is the one
place that decides whether a requested path is safe to open, so every
import tool routes through it instead of calling open() directly.

The policy: the file must resolve (symlinks included) to somewhere inside
one allowlisted directory, it must end in an allowed extension, and it must
be under a size cap. Anything else is rejected before open() is ever
called, with a message that names the problem but never echoes the
resolved path or file contents back to the caller.
"""

import os

DEFAULT_MAX_IMPORT_BYTES = 10 * 1024 * 1024  # 10 MiB -- generous for a CSV/JSON export


class UnsafeImportPath(ValueError):
    """Raised when a requested import path fails the allowlist check."""


def _import_root():
    # Resolved fresh on every call (not at import time) so tests can point
    # this at a temp directory via the IMPORT_DIR env var.
    root = os.environ.get(
        "IMPORT_DIR",
        os.path.join(os.path.dirname(__file__), "..", "data", "imports"),
    )
    os.makedirs(root, exist_ok=True)
    return os.path.realpath(root)


def resolve_import_path(requested_path: str, allowed_extensions: set[str],
                         max_bytes: int = DEFAULT_MAX_IMPORT_BYTES) -> str:
    """Return a real, safe-to-open path for `requested_path`, or raise
    UnsafeImportPath. `requested_path` may be a bare filename or a path;
    either way it's only ever resolved relative to the allowlisted import
    directory (IMPORT_DIR, default data/imports/), never relative to the
    server's cwd or the filesystem root -- an absolute path or a "../" is
    just another string to join under that root, not a way to leave it."""
    if not requested_path or not isinstance(requested_path, str):
        raise UnsafeImportPath("No file path provided.")

    root = _import_root()
    # Strip any leading drive/root so os.path.join can't be short-circuited
    # into treating an absolute-looking input as an absolute path.
    relative = requested_path.replace("\\", "/").lstrip("/")
    if os.name == "nt" and len(relative) > 1 and relative[1] == ":":
        relative = relative[2:].lstrip("/")
    candidate = os.path.realpath(os.path.join(root, relative))

    if os.path.commonpath([root, candidate]) != root:
        raise UnsafeImportPath("That path isn't inside the allowed import directory.")

    ext = os.path.splitext(candidate)[1].lower()
    if ext not in allowed_extensions:
        allowed = ", ".join(sorted(allowed_extensions))
        raise UnsafeImportPath(f"Unsupported file type '{ext or '(none)'}'. Allowed: {allowed}.")

    if not os.path.isfile(candidate):
        raise UnsafeImportPath("File not found in the import directory.")

    size = os.path.getsize(candidate)
    if size > max_bytes:
        raise UnsafeImportPath(f"File is too large ({size} bytes; limit is {max_bytes}).")

    return candidate
