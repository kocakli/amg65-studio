#!/usr/bin/env python3
"""Passive activity hook receiver and additive config builder. No network or decisions."""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import select
import shlex
import sys
import time

from activity import ActivityStore, MAX_INPUT_BYTES, PROVIDERS, normalize_hook

# Cursor permission hooks intentionally excluded: some require a permission
# response. This observer must never approve, deny, or modify another agent's work.
HOOK_EVENTS = {
    "codex": ("UserPromptSubmit", "PreModelRequest", "PostModelRequest", "PreToolUse", "PermissionRequest", "PostToolUse", "PreCompact", "Stop", "Interrupt", "SessionEnd"),
    "claude": ("UserPromptSubmit", "PreToolUse", "PermissionRequest", "PostToolUse", "PostToolUseFailure", "PreCompact", "Notification", "Elicitation", "ElicitationResult", "Stop", "StopFailure", "SessionEnd"),
    "cursor": ("postToolUse", "postToolUseFailure", "afterAgentResponse", "preCompact", "stop", "sessionEnd"),
}


def read_payload(fd: int, timeout: float = 0.5) -> dict | None:
    """Bound time and bytes even if a caller leaves stdin open or sends huge JSON."""
    deadline = time.monotonic() + timeout
    chunks = bytearray()
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], max(0, deadline - time.monotonic()))
        if not ready: return None
        chunk = os.read(fd, min(65536, MAX_INPUT_BYTES + 1 - len(chunks)))
        if not chunk:
            try: payload = json.loads(chunks)
            except (ValueError, RecursionError): return None
            return payload if isinstance(payload, dict) else None
        chunks.extend(chunk)
        if len(chunks) > MAX_INPUT_BYTES: return None
    return None


def build_hook_config(provider: str, existing: dict, python_executable: str | Path,
                      hook_script: str | Path, state_dir: str | Path,
                      *, supported_events: set[str] | None = None) -> dict:
    """Pure additive, idempotent merge. Caller owns capability check/backup/write.

    supported_events must be the independently verified capability set for the
    installed host. There is deliberately no assumed version compatibility.
    """
    if provider not in PROVIDERS or not isinstance(existing, dict):
        raise ValueError("Unsupported provider or configuration")
    if supported_events is None:
        raise ValueError("Verify the installed host's supported hooks before configuration")
    if not all(isinstance(value, str) for value in supported_events):
        raise ValueError("Invalid supported events")
    executable, script, state = map(Path, (python_executable, hook_script, state_dir))
    if not all(path.is_absolute() for path in (executable, script, state)):
        raise ValueError("Hook paths must be absolute")
    # shlex quoting preserves spaces, quotes, $, backticks and Unicode literally.
    command = shlex.join([str(executable), str(script), "receive", "--provider", provider, "--state-dir", str(state)])
    result = copy.deepcopy(existing)
    if provider == "cursor":
        if "version" in result and result["version"] != 1:
            raise ValueError("Unsupported Cursor hook configuration version")
        result["version"] = 1
    hooks = result.setdefault("hooks", {})
    if not isinstance(hooks, dict): raise ValueError("Existing hooks are not an object")
    for event in HOOK_EVENTS[provider]:
        if event not in supported_events: continue
        current = hooks.setdefault(event, [])
        if not isinstance(current, list) or not all(isinstance(item, dict) for item in current):
            raise ValueError("Existing event hook list is malformed")
        handler = {"type": "command", "command": command, "timeout": 2}
        entry = handler if provider == "cursor" else {"hooks": [handler]}
        # No failClosed, permission decisions, followup messages, input rewrites,
        # prompt/context output, async reordering, or global setting changes.
        if entry not in current: current.append(entry)
    return result


def remove_hook_config(provider: str, existing: dict, python_executable: str | Path,
                       hook_script: str | Path, state_dir: str | Path) -> dict:
    """Remove only byte-for-byte matching entries created by this integration."""
    generated = build_hook_config(provider, {}, python_executable, hook_script, state_dir,
                                  supported_events=set(HOOK_EVENTS[provider]))
    result = copy.deepcopy(existing)
    hooks = result.get("hooks")
    if not isinstance(hooks, dict): return result
    for event, owned_entries in generated["hooks"].items():
        if not isinstance(hooks.get(event), list): continue
        hooks[event] = [entry for entry in hooks[event] if entry not in owned_entries]
        if not hooks[event]: del hooks[event]
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    receiver = sub.add_parser("receive")
    receiver.add_argument("--provider", required=True, choices=PROVIDERS)
    receiver.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    # A dedicated account sign-in is not an agent job, even on older hosts that
    # still dispatch a lifecycle hook before honoring disableAllHooks.
    if os.environ.get("AMG65_STUDIO_AUTH_FLOW") == "1":
        sys.stdout.write("{}\n")
        return 0
    # Capture receipt time before reading; payloads never get to supply timestamps.
    now = time.time()
    try:
        payload = read_payload(sys.stdin.fileno())
        if payload is not None:
            event = normalize_hook(args.provider, payload, now)
            if event is not None: ActivityStore(args.state_dir).record(event)
    except (OSError, ValueError, TypeError, RecursionError):
        pass  # Observation failure never changes agent permission or completion.
    sys.stdout.write("{}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
