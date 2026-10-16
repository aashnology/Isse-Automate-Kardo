"""Optional bridge to Aspen, the separate desktop companion (github.com/aashnology/Woof).

Aspen is not part of this repository. Hexi only starts or stops a copy the user
already has, and only after the user says yes. ASPEN_HOME must point at that
checkout; with it unset Hexi simply reports that Aspen isn't installed.
The bridge never builds a command from request data: the arguments are fixed.
"""
import os
import subprocess
import sys

_proc = None


def _home():
    home = os.environ.get("ASPEN_HOME", "").strip()
    if home and os.path.isfile(os.path.join(home, "main.py")):
        return os.path.abspath(home)
    return None


def _python():
    return os.environ.get("ASPEN_PYTHON", "").strip() or sys.executable


def installed():
    return _home() is not None


def call():
    """Start Aspen. Returns a state string: started, already_running, not_installed or error."""
    global _proc
    home = _home()
    if home is None:
        return "not_installed"
    if _proc is not None and _proc.poll() is None:
        return "already_running"
    try:
        _proc = subprocess.Popen(
            [_python(), "main.py"], cwd=home,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError:
        _proc = None
        return "error"
    return "started"


def stop():
    """Ask a running Aspen to quit using his own --stop flag."""
    global _proc
    home = _home()
    if home is None:
        return "not_installed"
    try:
        subprocess.run([_python(), "main.py", "--stop"], cwd=home, timeout=10,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return "error"
    _proc = None
    return "stopped"
