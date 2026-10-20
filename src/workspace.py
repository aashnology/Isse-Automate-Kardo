"""
A workspace is one analysed dataset: events labelled with discovered
workflows, plus the radar and discovery objects built over them.

Why it exists: /api/import used to analyse a file and throw the result away,
while propose / debug / confirm kept reading the built-in sample. Now an import
is persisted under a content-hash id, and every tool takes an optional
dataset_id, so the same propose -> confirm -> diagnose path runs on whatever
data the user brought. State lives on disk, not in a process global, so the
web server and the MCP server (separate processes) see the same datasets and
concurrent users never overwrite each other.
"""

import hashlib
import json
import math
import os
import re
import tempfile
import threading
from collections import OrderedDict

from friction_radar import FrictionRadar
from synthetic_data import load_activity_events
from workflow_discovery import WorkflowDiscovery

SAMPLE_ID = "sample"
_ID_RE = re.compile(r"^[a-f0-9]{16}$")
MAX_EVENTS = 50_000
MAX_STORED = 50
MAX_ACTIVITY_LEN = 60
IMPORT_THRESHOLD = 0.6
SAMPLE_THRESHOLD = 0.75

_LOCK = threading.Lock()
_CACHE = OrderedDict()  # (id, mtime) -> Workspace
_CACHE_MAX = 16
_VOLATILE = OrderedDict()  # imports that could not be written to disk (this process only)


class UnknownDataset(KeyError):
    pass


def workspace_dir():
    return os.environ.get("HEXI_WORKSPACE_DIR") or os.path.join(
        os.path.dirname(__file__), "..", "data", "workspaces")


def normalize_activity(name):
    s = re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")
    return s[:MAX_ACTIVITY_LEN]


class Workspace:
    def __init__(self, ws_id, label, source, events, outcome_known, threshold, created_at=None):
        self.id = ws_id
        self.label = label
        self.source = source
        self.events = events
        self.outcome_known = outcome_known
        self.threshold = threshold
        self.created_at = created_at
        self.radar = FrictionRadar(events)
        self.discovery = WorkflowDiscovery(events, similarity_threshold=threshold,
                                           run_id_field="workflow_run_id")

    def workflow_names(self):
        return sorted({e["workflow_name"] for e in self.events})

    def summary(self):
        runs = {e["workflow_run_id"] for e in self.events}
        return {
            "dataset_id": self.id, "label": self.label, "source": self.source,
            "events": len(self.events), "runs": len(runs),
            "workflows": self.workflow_names(), "outcome_known": self.outcome_known,
        }


def _clean_events(raw, run_id_field=None):
    cleaned = []
    for e in raw[:MAX_EVENTS]:
        try:
            activity = normalize_activity(e["activity"])
            duration = float(e["duration_minutes"])
            ts = e["timestamp"]
        except (KeyError, TypeError, ValueError):
            continue
        if not activity or not isinstance(ts, str) or not math.isfinite(duration) or duration < 0:
            continue
        item = {"timestamp": ts, "activity": activity, "duration_minutes": round(min(duration, 1440.0), 3)}
        if run_id_field and run_id_field in e:
            item[run_id_field] = e[run_id_field]
        cleaned.append(item)
    return cleaned


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _cluster_name(sequence, taken):
    steps = [_slug(s) for s in sequence if _slug(s)] or ["workflow"]
    first, last = steps[0][:24], steps[-1][:24]
    base = f"{first}_to_{last}" if first != last else f"{first}_loop"
    name, i = base, 2
    while name in taken:
        name, i = f"{base}_{i}", i + 1
    taken.add(name)
    return name


def build_workspace(raw_events, label, source, run_id_field=None, persist=True):
    """Cluster raw events into workflows and wrap them as a Workspace.
    Raises ValueError when nothing usable is left."""
    cleaned = _clean_events(raw_events, run_id_field)
    if not cleaned:
        raise ValueError("No usable events (each needs a timestamp, an activity and a duration).")

    if run_id_field:
        wd = WorkflowDiscovery(cleaned, similarity_threshold=IMPORT_THRESHOLD, run_id_field=run_id_field)
    else:
        wd = WorkflowDiscovery.from_raw_events(cleaned, similarity_threshold=IMPORT_THRESHOLD)

    clusters = wd.discover()
    kept = [c for c in clusters if c["run_count"] >= 2] or clusters
    if not kept:
        raise ValueError("No repeating pattern found in that data.")

    taken, labelled, n = set(), [], 0
    for c in kept:
        name = _cluster_name(c["canonical_sequence"], taken)
        for rid in c["run_ids"]:
            n += 1
            for e in wd.runs[rid]:
                labelled.append({
                    "timestamp": e["timestamp"], "activity": e["activity"],
                    "duration_minutes": e["duration_minutes"],
                    "workflow_run_id": f"{name}-{n}", "workflow_name": name, "outcome": "ok",
                })

    digest = hashlib.sha256(json.dumps(
        [(e["timestamp"], e["activity"], e["duration_minutes"], e["workflow_name"]) for e in labelled],
        separators=(",", ":")).encode()).hexdigest()[:16]
    ws = Workspace(digest, label, source, labelled, outcome_known=False, threshold=IMPORT_THRESHOLD)
    if persist:
        try:
            _save(ws)
        except OSError:
            # Read-only or unwritable data directory: the import still works in
            # this process. The MCP server cannot see it, and the web server
            # falls back to calling the functions directly.
            with _LOCK:
                _VOLATILE[ws.id] = ws
                while len(_VOLATILE) > _CACHE_MAX:
                    _VOLATILE.popitem(last=False)
    return ws


def _save(ws):
    d = workspace_dir()
    os.makedirs(d, exist_ok=True)
    payload = {"id": ws.id, "label": ws.label, "source": ws.source, "outcome_known": ws.outcome_known,
               "threshold": ws.threshold, "events": ws.events}
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    os.replace(tmp, os.path.join(d, f"{ws.id}.json"))
    _prune(d)


def _prune(d):
    files = [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".json")]
    files.sort(key=os.path.getmtime, reverse=True)
    for old in files[MAX_STORED:]:
        try:
            os.remove(old)
        except OSError:
            pass


_SAMPLE = None


def get_workspace(ws_id=None):
    """The sample for None/'sample'; otherwise the persisted import with that id."""
    global _SAMPLE
    if not ws_id or ws_id == SAMPLE_ID:
        with _LOCK:
            if _SAMPLE is None:
                _SAMPLE = Workspace(SAMPLE_ID, "Built-in sample", "synthetic",
                                    load_activity_events(), outcome_known=True, threshold=SAMPLE_THRESHOLD)
            return _SAMPLE
    if not isinstance(ws_id, str) or not _ID_RE.match(ws_id):
        raise UnknownDataset(f"'{str(ws_id)[:20]}' is not a valid dataset id.")
    with _LOCK:
        if ws_id in _VOLATILE:
            return _VOLATILE[ws_id]
    path = os.path.join(workspace_dir(), f"{ws_id}.json")
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        raise UnknownDataset(f"No dataset '{ws_id}'. Import your data again.") from None
    key = (ws_id, mtime)
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    with open(path) as f:
        data = json.load(f)
    ws = Workspace(data["id"], data["label"], data["source"], data["events"],
                   data.get("outcome_known", False), data.get("threshold", IMPORT_THRESHOLD))
    with _LOCK:
        _CACHE[key] = ws
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return ws
