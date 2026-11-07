"""Private, bounded activity metadata for AMG65 Studio. Never stores conversation text."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
import fcntl
import hashlib
import json
import math
import os
import re
import stat
import tempfile
import threading
import time

PROVIDERS = ("codex", "claude", "cursor")
TTL = {"unknown": 0, "queued": 30, "running": 120, "waiting_approval": 300,
       "waiting_input": 300, "completed": 45, "error": 90}
PRIORITY = {"unknown": 0, "completed": 1, "queued": 2, "running": 3,
            "error": 4, "waiting_input": 5, "waiting_approval": 6}
# These are localization keys, not model-generated descriptions.
SUMMARIES = {"unknown", "prompt_submitted", "working", "using_tool", "running_command",
             "reading_files", "editing_files", "searching", "approval_requested",
             "input_requested", "input_received", "completed", "tool_failed",
             "failed", "interrupted", "session_ended", "compacting"}
MAX_INPUT_BYTES = 256 * 1024
MAX_STATE_BYTES = 128 * 1024
MAX_SESSIONS = 64
MAX_TAIL_BYTES = 256 * 1024
MAX_FILES = 8
MAX_RECORDS_PER_FILE = 2048
MAX_DIRECTORY_ENTRIES = 2048
HISTORY_SECONDS = 600
TOOL_LABELS = {
    "Bash": "running_command", "Shell": "running_command", "exec_command": "running_command",
    "Read": "reading_files", "ReadFile": "reading_files", "read_file": "reading_files",
    "Edit": "editing_files", "Write": "editing_files", "apply_patch": "editing_files",
    "Grep": "searching", "Glob": "searching", "WebSearch": "searching", "web_search": "searching",
}
INPUT_TOOLS = {"AskUserQuestion", "request_user_input", "request_user_input_async"}


def default_state_dir() -> Path:
    return Path.home() / "Library/Application Support/AMG65 Studio/state"


def opaque(value: object) -> str:
    """Stable opaque identity; original IDs and filesystem paths never leave memory."""
    return hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()[:20]


def safe_identifier(value: object) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= 512 else None


def event_time(value: object) -> float | None:
    if not isinstance(value, str) or len(value) > 48:
        return None
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return date.timestamp() if date.tzinfo else None
    except (ValueError, OverflowError):
        return None


@dataclass(frozen=True)
class ActivityEvent:
    provider: str
    session_id: str
    turn_id: str
    state: str
    summary: str
    observed_at: float
    source: str
    event: str
    wait_token: str = ""
    clears_wait: bool = False

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.session_id}:{self.turn_id}"


def _event(provider, session, turn, state, summary, now, source, event,
           wait_token=None, clears_wait=False) -> ActivityEvent:
    return ActivityEvent(provider, opaque(provider + ":" + session), opaque(turn or session),
                         state, summary, now, source, event,
                         opaque(wait_token) if wait_token else "", clears_wait)


def normalize_hook(provider: str, payload: dict, now: float | None = None) -> ActivityEvent | None:
    """Map only documented event names and fixed labels; ignore all user content."""
    now = time.time() if now is None else now
    if provider not in PROVIDERS or not isinstance(payload, dict):
        return None
    session = safe_identifier(payload.get("conversation_id" if provider == "cursor" else "session_id"))
    if not session:
        return None
    turn = safe_identifier(payload.get("generation_id" if provider == "cursor" else "turn_id"))
    kind = payload.get("hook_event_name")
    if not isinstance(kind, str):
        return None
    # Subagent lifecycle events describe another worker, not the parent's completion.
    if kind in {"SubagentStart", "SubagentStop", "subagentStart", "subagentStop"}:
        return None
    tool = payload.get("tool_name")
    if not isinstance(tool, str): tool = None
    label = TOOL_LABELS.get(tool, "using_tool") if isinstance(tool, str) else "using_tool"
    token = safe_identifier(payload.get("tool_use_id"))
    state, summary, clears = None, None, False
    if provider in {"codex", "claude"}:
        if kind == "UserPromptSubmit": state, summary, clears = "queued", "prompt_submitted", True
        elif kind in {"PreModelRequest", "PostModelRequest"} and provider == "codex":
            state, summary, clears = "running", "working", True
            if kind == "PostModelRequest" and payload.get("status") == "failed":
                state, summary = "error", "failed"
        elif kind == "PreToolUse":
            state, summary = ("waiting_input", "input_requested") if tool in INPUT_TOOLS else ("running", label)
        elif kind == "PostToolUse": state, summary = "running", label
        elif kind == "PermissionRequest": state, summary = "waiting_approval", "approval_requested"
        elif kind == "PostToolUseFailure" and provider == "claude": state, summary = "error", "tool_failed"
        elif kind == "Stop": state, summary, clears = "completed", "completed", True
        elif kind == "StopFailure" and provider == "claude": state, summary, clears = "error", "failed", True
        elif kind == "Interrupt" and provider == "codex": state, summary, clears = "unknown", "interrupted", True
        elif kind == "SessionEnd": state, summary, clears = "unknown", "session_ended", True
        elif kind == "PreCompact": state, summary = "running", "compacting"
        elif kind == "Elicitation" and provider == "claude": state, summary = "waiting_input", "input_requested"
        elif kind == "ElicitationResult" and provider == "claude": state, summary, clears = "running", "input_received", True
        elif kind == "Notification" and provider == "claude":
            notification = payload.get("notification_type")
            if not isinstance(notification, str): return None
            if notification == "permission_prompt": state, summary = "waiting_approval", "approval_requested"
            elif notification in {"elicitation_dialog", "elicitation_url_dialog", "agent_needs_input", "quota_auto_resume_stale"}:
                state, summary = "waiting_input", "input_requested"
            elif notification in {"elicitation_complete", "elicitation_response"}:
                state, summary, clears = "running", "input_received", True
            # idle_prompt and agent_completed deliberately ignored: idle is not a
            # question, and agent_completed does not distinguish success/failure.
    else:
        if kind == "beforeSubmitPrompt": state, summary, clears = "queued", "prompt_submitted", True
        elif kind == "preToolUse": state, summary = "running", label
        elif kind == "postToolUse": state, summary = "running", label
        elif kind == "postToolUseFailure": state, summary = "error", "tool_failed"
        elif kind == "afterAgentResponse": state, summary = "running", "working"
        elif kind == "preCompact": state, summary = "running", "compacting"
        elif kind == "stop":
            status = payload.get("status")
            if status == "completed": state, summary, clears = "completed", "completed", True
            elif status == "error": state, summary, clears = "error", "failed", True
            elif status == "aborted": state, summary, clears = "unknown", "interrupted", True
        elif kind == "sessionEnd": state, summary, clears = "unknown", "session_ended", True
    if state is None:
        return None
    return _event(provider, session, turn, state, summary, now, "hook", kind, token, clears)


def normalize_codex_record(record: dict, session: str, now: float) -> ActivityEvent | None:
    """Best-effort versioned rollout metadata. Unknown record shapes stay unknown."""
    if not isinstance(record, dict): return None
    at = event_time(record.get("timestamp"))
    if at is None or at > now + 5 or at < now - HISTORY_SECONDS: return None
    payload = record.get("payload")
    if not isinstance(payload, dict): return None
    kind = payload.get("type")
    if not isinstance(kind, str): return None
    turn = safe_identifier(payload.get("turn_id"))
    state, summary, clears, token = None, None, False, None
    if record.get("type") == "event_msg":
        if kind == "task_started": state, summary, clears = "running", "working", True
        elif kind == "task_complete": state, summary, clears = "completed", "completed", True
        elif kind == "turn_aborted": state, summary, clears = "unknown", "interrupted", True
        elif kind == "item_completed":
            item = payload.get("item")
            if not isinstance(item, dict): return None
            item_type = item.get("type")
            if not isinstance(item_type, str): return None
            labels = {"Reasoning": "working", "CommandExecution": "running_command", "FileChange": "editing_files",
                      "WebSearch": "searching", "McpToolCall": "using_tool", "ContextCompaction": "compacting"}
            if item_type in labels: state, summary = "running", labels[item_type]
    elif record.get("type") == "response_item":
        # Only tool lifecycle metadata is observed, never arguments/output/reasoning.
        if kind in {"function_call", "custom_tool_call"}:
            name = payload.get("name")
            if not isinstance(name, str): return None
            state, summary = ("waiting_input", "input_requested") if name in INPUT_TOOLS else ("running", TOOL_LABELS.get(name, "using_tool"))
            token = safe_identifier(payload.get("call_id"))
        elif kind in {"function_call_output", "custom_tool_call_output"}:
            state, summary = "running", "using_tool"
            token = safe_identifier(payload.get("call_id"))
    if state is None: return None
    return _event("codex", session, turn, state, summary, at, "codex_log", str(kind), token, clears)


def _valid_event(row: object) -> ActivityEvent | None:
    if not isinstance(row, dict): return None
    try: event = ActivityEvent(**row)
    except (TypeError, ValueError): return None
    if not all(isinstance(value, str) for value in (event.provider, event.state, event.summary, event.source)): return None
    if event.provider not in PROVIDERS or event.state not in TTL or event.summary not in SUMMARIES: return None
    if event.source not in {"hook", "codex_log"}: return None
    if not isinstance(event.observed_at, (int, float)) or isinstance(event.observed_at, bool) or not math.isfinite(event.observed_at): return None
    if not all(isinstance(s, str) and re.fullmatch(r"[a-f0-9]{20}", s) for s in (event.session_id, event.turn_id)): return None
    if not isinstance(event.wait_token, str) or (event.wait_token and not re.fullmatch(r"[a-f0-9]{20}", event.wait_token)): return None
    if not isinstance(event.event, str) or not re.fullmatch(r"[A-Za-z_]{1,40}", event.event): return None
    if not isinstance(event.clears_wait, bool): return None
    return event


def _merge(events: dict[str, ActivityEvent], incoming: ActivityEvent) -> None:
    old = events.get(incoming.key)
    if old and old.observed_at > incoming.observed_at: return
    # Codex output records omit the tool name. Preserve an observed category only
    # for the exact matching tool call; a generic/different call must stay generic.
    if (old and old.state == incoming.state == "running" and incoming.summary == "using_tool"
            and incoming.event in {"function_call_output", "custom_tool_call_output"}
            and old.summary in {"running_command", "reading_files", "editing_files", "searching"}
            and old.wait_token and old.wait_token == incoming.wait_token):
        incoming = replace(incoming, summary=old.summary)
    # A tail discovered after a hook must not resurrect an already-ended turn.
    if any(event.key != incoming.key and event.provider == incoming.provider
           and event.session_id == incoming.session_id and event.observed_at >= incoming.observed_at
           and event.event in {"SessionEnd", "sessionEnd", "task_complete", "Stop"}
           for event in events.values()): return
    if old and old.state.startswith("waiting_") and incoming.state == "running" and not incoming.clears_wait:
        matching_result = incoming.event in {"PostToolUse", "postToolUse", "function_call_output", "custom_tool_call_output"}
        if not (matching_result and old.wait_token and old.wait_token == incoming.wait_token):
            if incoming.observed_at < old.observed_at + TTL[old.state]: return
    if incoming.event in {"SessionEnd", "sessionEnd", "task_complete", "Stop"}:
        for key, event in list(events.items()):
            if event.provider == incoming.provider and event.session_id == incoming.session_id and event.observed_at <= incoming.observed_at:
                del events[key]
    events[incoming.key] = incoming
    if len(events) > MAX_SESSIONS:
        for key in sorted(events, key=lambda key: events[key].observed_at)[:-MAX_SESSIONS]: del events[key]


class ActivityStore:
    """Atomic user-only journal of current metadata, not an event history."""
    def __init__(self, directory: Path | str | None = None):
        self.directory = Path(directory) if directory is not None else default_state_dir()
        self.path = self.directory / "activity.json"

    def _directory(self):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid(): raise OSError("Unsafe activity directory")
        os.chmod(self.directory, 0o700)

    def read(self) -> list[ActivityEvent]:
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > MAX_STATE_BYTES: return []
                data = json.loads(stream.read(MAX_STATE_BYTES + 1))
            if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("events"), list): return []
            return [event for row in data["events"][:MAX_SESSIONS] if (event := _valid_event(row))]
        except (OSError, ValueError, TypeError, RecursionError): return []

    @contextmanager
    def _lock(self):
        self._directory()
        fd = os.open(self.directory / "activity.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid(): raise OSError("Unsafe activity lock")
            os.fchmod(fd, 0o600)
            deadline = time.monotonic() + 0.15
            while True:
                try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); break
                except BlockingIOError:
                    if time.monotonic() >= deadline: raise TimeoutError("Activity lock busy")
                    time.sleep(0.01)
            yield
        finally: os.close(fd)

    def record(self, event: ActivityEvent) -> bool:
        if not _valid_event(asdict(event)): return False
        temp = None
        try:
            with self._lock():
                events = {e.key: e for e in self.read() if e.observed_at >= event.observed_at - HISTORY_SECONDS}
                _merge(events, event)
                data = json.dumps({"schema": 1, "events": [asdict(e) for e in events.values()]}, separators=(",", ":")).encode()
                if len(data) > MAX_STATE_BYTES: return False
                fd, temp = tempfile.mkstemp(prefix=".activity-", dir=self.directory)
                with os.fdopen(fd, "wb") as stream:
                    os.fchmod(stream.fileno(), 0o600); stream.write(data); stream.flush(); os.fsync(stream.fileno())
                os.replace(temp, self.path); temp = None
            return True
        except (OSError, ValueError): return False
        finally:
            if temp:
                try: os.unlink(temp)
                except OSError: pass


class CodexLogTail:
    """At most eight files / 2 MiB per poll, today+yesterday only, no recursive scan."""
    def __init__(self, codex_home: Path | str | None = None):
        self.home = Path(codex_home) if codex_home is not None else Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        self.offsets: dict[str, tuple[int, int, int]] = {}
        self.turns: dict[str, str] = {}
        self.skip_partial: set[str] = set()

    def files(self, now: float) -> list[Path]:
        found = []
        for day in (datetime.fromtimestamp(now), datetime.fromtimestamp(now) - timedelta(days=1)):
            directory = self.home / "sessions" / day.strftime("%Y/%m/%d")
            try:
                with os.scandir(directory) as entries:
                    for index, entry in enumerate(entries):
                        if index >= MAX_DIRECTORY_ENTRIES: break
                        if not entry.name.endswith(".jsonl") or not entry.is_file(follow_symlinks=False): continue
                        info = entry.stat(follow_symlinks=False)
                        if info.st_uid == os.getuid() and now - HISTORY_SECONDS <= info.st_mtime <= now + 5:
                            found.append((info.st_mtime, Path(entry.path)))
            except OSError: continue
        return [path for _, path in sorted(found, reverse=True)[:MAX_FILES]]

    def poll(self, now: float) -> list[ActivityEvent]:
        events = []
        paths = self.files(now)
        active = {str(path) for path in paths}
        self.offsets = {k: v for k, v in self.offsets.items() if k in active}
        self.turns = {k: v for k, v in self.turns.items() if k in active}
        self.skip_partial.intersection_update(active)
        for path in paths:
            key = str(path)
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid(): continue
                    old = self.offsets.get(key)
                    valid_old = old and old[:2] == (info.st_dev, info.st_ino) and old[2] <= info.st_size
                    start = old[2] if valid_old else max(0, info.st_size - MAX_TAIL_BYTES)
                    if not valid_old: self.turns.pop(key, None)
                    lost_prefix = not valid_old and start > 0
                    if info.st_size - start > MAX_TAIL_BYTES:
                        start = info.st_size - MAX_TAIL_BYTES; lost_prefix = True; self.turns.pop(key, None)
                    stream.seek(start); data = stream.read(MAX_TAIL_BYTES)
                    boundary = data.rfind(b"\n")
                    if boundary < 0:
                        # Drop oversized lines instead of retaining prompts in memory.
                        if len(data) == MAX_TAIL_BYTES:
                            self.offsets[key] = (info.st_dev, info.st_ino, start + len(data)); self.skip_partial.add(key)
                        continue
                    self.offsets[key] = (info.st_dev, info.st_ino, start + boundary + 1)
                    lines = data[:boundary].split(b"\n")
                    if lost_prefix or key in self.skip_partial:
                        lines = lines[1:]; self.skip_partial.discard(key)
                    match = re.search(r"([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})\.jsonl$", path.name)
                    session = match.group(1) if match else path.name
                    for line in lines[-MAX_RECORDS_PER_FILE:]:
                        if len(line) > MAX_INPUT_BYTES: continue
                        try: record = json.loads(line)
                        except (ValueError, RecursionError): continue
                        if not isinstance(record, dict): continue
                        payload = record.get("payload")
                        if not isinstance(payload, dict): continue
                        turn = safe_identifier(payload.get("turn_id"))
                        if turn: self.turns[key] = turn
                        # response_item has no turn_id; use an observed turn context.
                        if record.get("type") == "response_item" and key in self.turns:
                            payload = dict(payload); payload["turn_id"] = self.turns[key]
                            record = dict(record); record["payload"] = payload
                        if record.get("type") == "response_item" and key not in self.turns:
                            continue  # A bounded tail may begin mid-turn; no invented identity.
                        event = normalize_codex_record(record, session, now)
                        if event: events.append(event)
            except OSError: continue
        return events


class ActivityCollector:
    def __init__(self, state_dir: Path | str | None = None, codex_home: Path | str | None = None,
                 *, scan_codex: bool = True, clock=time.time):
        self.store = ActivityStore(state_dir)
        self.logs = CodexLogTail(codex_home) if scan_codex else None
        self.clock = clock
        self.events: dict[str, ActivityEvent] = {}
        self.lock = threading.Lock()
        self.last_scan = float("-inf")

    def snapshot(self) -> dict:
        with self.lock:
            now = self.clock()
            for event in self.store.read():
                if now - HISTORY_SECONDS <= event.observed_at <= now + 5: _merge(self.events, event)
            if self.logs and (now < self.last_scan or now - self.last_scan >= 2):
                self.last_scan = now
                for event in sorted(self.logs.poll(now), key=lambda e: e.observed_at): _merge(self.events, event)
            self.events = {k: v for k, v in self.events.items() if v.observed_at >= now - HISTORY_SECONDS}
            providers = []
            for provider in PROVIDERS:
                all_events = [e for e in self.events.values() if e.provider == provider]
                fresh = [e for e in all_events if e.state != "unknown" and e.observed_at + TTL[e.state] > now]
                latest = max(fresh, key=lambda e: (PRIORITY[e.state], e.observed_at), default=None)
                if not latest: latest = max(all_events, key=lambda e: e.observed_at, default=None)
                state = latest.state if latest and latest in fresh else "unknown"
                row = {"provider": provider, "state": state, "summary": latest.summary if state != "unknown" else "unknown",
                       "observed_at": latest.observed_at if latest else None,
                       "expires_at": latest.observed_at + TTL[latest.state] if latest else None,
                       "source": latest.source if latest else None, "session_id": latest.session_id if latest else None,
                       "active_count": len({e.session_id for e in fresh if e.state in {"queued", "running", "waiting_approval", "waiting_input"}}),
                       "stale": bool(latest and latest.state != "unknown" and state == "unknown")}
                providers.append(row)
            visible = [row for row in providers if row["state"] != "unknown"]
            selected = max(visible, key=lambda row: (PRIORITY[row["state"]], row["observed_at"]), default=None)
            return {"updated_at": now, "providers": providers, "selected": selected}
