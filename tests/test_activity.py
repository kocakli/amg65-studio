import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from activity import (ActivityCollector, ActivityStore, CodexLogTail, MAX_INPUT_BYTES,
                      MAX_SESSIONS, MAX_TAIL_BYTES, TTL, normalize_codex_record, normalize_hook)
from activity_hooks import HOOK_EVENTS, build_hook_config, read_payload, remove_hook_config

ROOT = Path(__file__).resolve().parents[1]
NOW = 1794038400.0


def hook(provider="codex", event="PreToolUse", now=NOW, **values):
    base = {"session_id": "private-session-id", "conversation_id": "private-session-id",
            "turn_id": "private-turn-id", "generation_id": "private-turn-id",
            "hook_event_name": event, "tool_name": "Bash"}
    base.update(values)
    return normalize_hook(provider, base, now)


def record(kind, at=NOW, **values):
    payload = {"type": kind, "turn_id": "private-turn-id"}; payload.update(values)
    return {"timestamp": datetime.fromtimestamp(at, timezone.utc).isoformat(), "type": "event_msg", "payload": payload}


class ActivityHooksTests(unittest.TestCase):
    def test_documented_approval_only(self):
        for provider in ("codex", "claude"):
            self.assertEqual(hook(provider, "PermissionRequest").state, "waiting_approval")
        self.assertIsNone(hook("cursor", "PermissionRequest"))
        self.assertIsNone(hook("cursor", "beforeShellExecution"))

    def test_explicit_input_and_result(self):
        self.assertEqual(hook("claude", "Elicitation").state, "waiting_input")
        self.assertEqual(hook("claude", "PreToolUse", tool_name="AskUserQuestion").state, "waiting_input")
        self.assertEqual(hook("codex", "PreToolUse", tool_name="request_user_input_async").state, "waiting_input")
        self.assertTrue(hook("claude", "ElicitationResult").clears_wait)

    def test_idle_and_background_completion_are_not_questions_or_success(self):
        for notification in ("idle_prompt", "agent_completed", "auth_success", "plugin_notification"):
            self.assertIsNone(hook("claude", "Notification", notification_type=notification))
        self.assertEqual(hook("claude", "Notification", notification_type="agent_needs_input").state, "waiting_input")

    def test_cursor_terminal_status_is_explicit(self):
        for status, state in (("completed", "completed"), ("error", "error"), ("aborted", "unknown")):
            self.assertEqual(hook("cursor", "stop", status=status).state, state)
        self.assertIsNone(hook("cursor", "stop", status="invented"))
        self.assertEqual(hook("cursor", "afterAgentResponse").state, "running")

    def test_subagents_do_not_complete_parent(self):
        for provider in ("claude", "codex", "cursor"):
            self.assertIsNone(hook(provider, "SubagentStop"))
            self.assertIsNone(hook(provider, "subagentStop"))

    def test_no_arbitrary_text_survives(self):
        secret = "SECRET /private/home prompt token command filename"
        event = hook("claude", tool_name=secret, tool_input={"command": secret}, prompt=secret,
                     message=secret, cwd=secret, error=secret, user_email=secret)
        self.assertNotIn(secret, json.dumps(event.__dict__))
        self.assertEqual(event.summary, "using_tool")
        self.assertNotIn("private-session-id", json.dumps(event.__dict__))
        self.assertEqual(len(event.session_id), 20)

    def test_invalid_shapes_are_ignored_without_exception(self):
        for payload in (None, [], "string", {}, {"session_id": {}}, {"session_id": "x", "hook_event_name": []}):
            self.assertIsNone(normalize_hook("codex", payload, NOW))
        self.assertEqual(hook(tool_name={"unexpected": "dict"}).summary, "using_tool")
        self.assertIsNone(hook("claude", "Notification", notification_type={"bad": "shape"}))
        self.assertIsNone(normalize_hook("unknown", {}, NOW))

    def test_configuration_is_additive_idempotent_and_reversible(self):
        for provider in HOOK_EVENTS:
            event_name = HOOK_EVENTS[provider][0]
            original = {"hooks": {event_name: [{"command": "existing-user-command"}]}, "other": {"key": True}}
            snapshot = copy.deepcopy(original)
            args = (provider, original, "/usr/bin/python3", "/App's path/$x/`literal`/activity_hooks.py", "/data path/state")
            merged = build_hook_config(*args, supported_events=set(HOOK_EVENTS[provider]))
            self.assertEqual(original, snapshot)
            self.assertEqual(merged["hooks"][event_name][0], original["hooks"][event_name][0])
            twice = build_hook_config(provider, merged, *args[2:], supported_events=set(HOOK_EVENTS[provider]))
            self.assertEqual(merged, twice)
            removed = remove_hook_config(provider, merged, *args[2:])
            if provider == "cursor": removed.pop("version")
            self.assertEqual(original, removed)
            import shlex
            entry = merged["hooks"][event_name][-1]
            handler = entry if provider == "cursor" else entry["hooks"][0]
            words = shlex.split(handler["command"])
            self.assertEqual(words[1], args[3])
            self.assertEqual(words[-1], args[4])

    def test_no_assumed_hook_support_or_permission_decisions(self):
        args = ("codex", {}, "/python", "/hook.py", "/state")
        with self.assertRaises(ValueError): build_hook_config(*args)
        self.assertEqual(build_hook_config(*args, supported_events=set()), {"hooks": {}})
        for provider in HOOK_EVENTS:
            result = build_hook_config(provider, {}, "/python", "/hook.py", "/state", supported_events=set(HOOK_EVENTS[provider]))
            encoded = json.dumps(result)
            for forbidden in ("permissionDecision", "followup_message", "failClosed", "updatedInput", "async"):
                self.assertNotIn(forbidden, encoded)
        self.assertNotIn("preToolUse", HOOK_EVENTS["cursor"])
        self.assertNotIn("beforeSubmitPrompt", HOOK_EVENTS["cursor"])

    def test_malformed_config_refuses_without_modification(self):
        for config in ({"hooks": []}, {"hooks": {"Stop": "bad"}}):
            original = copy.deepcopy(config)
            with self.assertRaises(ValueError):
                build_hook_config("codex", config, "/python", "/hook", "/state", supported_events={"Stop"})
            self.assertEqual(config, original)

    def test_receiver_returns_empty_decision_and_sanitized_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = {"session_id": "session", "hook_event_name": "PermissionRequest", "prompt": "DO NOT STORE ME"}
            proc = subprocess.run([sys.executable, str(ROOT / "activity_hooks.py"), "receive", "--provider", "claude", "--state-dir", tmp],
                                  input=json.dumps(payload), capture_output=True, text=True, timeout=3)
            self.assertEqual(proc.returncode, 0); self.assertEqual(json.loads(proc.stdout), {})
            self.assertEqual(proc.stderr, "")
            content = (Path(tmp) / "activity.json").read_text()
            self.assertNotIn("DO NOT STORE ME", content)
            self.assertIn("waiting_approval", content)

    def test_sign_in_process_never_becomes_agent_activity(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload={"session_id":"login","hook_event_name":"UserPromptSubmit"}
            proc=subprocess.run([sys.executable,str(ROOT/"activity_hooks.py"),"receive","--provider","claude","--state-dir",tmp],
                                input=json.dumps(payload),capture_output=True,text=True,timeout=3,
                                env=dict(os.environ,AMG65_STUDIO_AUTH_FLOW="1"))
            self.assertEqual(proc.returncode,0)
            self.assertEqual(proc.stdout,"{}\n")
            self.assertEqual(list(Path(tmp).iterdir()),[])

    def test_receiver_invalid_json_never_changes_agent_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([sys.executable, str(ROOT / "activity_hooks.py"), "receive", "--provider", "cursor", "--state-dir", tmp],
                                  input="{broken", capture_output=True, text=True, timeout=3)
            self.assertEqual(proc.returncode, 0); self.assertEqual(proc.stdout, "{}\n")
            self.assertFalse((Path(tmp) / "activity.json").exists())

    def test_input_time_limit_even_with_open_pipe(self):
        read, write = os.pipe()
        try:
            start = time.monotonic()
            self.assertIsNone(read_payload(read, timeout=0.03))
            self.assertLess(time.monotonic() - start, 0.2)
        finally: os.close(read); os.close(write)

    def test_input_size_limit(self):
        read, write = os.pipe()
        def writer():
            try:
                with os.fdopen(write, "wb") as stream: stream.write(b"x" * (MAX_INPUT_BYTES + 2))
            except BrokenPipeError: pass
        thread = threading.Thread(target=writer); thread.start()
        try: self.assertIsNone(read_payload(read))
        finally: os.close(read); thread.join(1)


class ActivityStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.path = Path(self.temp.name) / "state"
        self.store = ActivityStore(self.path)
        self.now = NOW
        self.collector = ActivityCollector(self.path, scan_codex=False, clock=lambda: self.now)
    def tearDown(self): self.temp.cleanup()

    def test_permissions_atomic_state_and_no_history(self):
        self.assertTrue(self.store.record(hook()))
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.store.path.stat().st_mode), 0o600)
        self.assertEqual(len(self.store.read()), 1)
        self.store.record(hook(now=NOW + 1))
        self.assertEqual(len(self.store.read()), 1)
        self.assertFalse(list(self.path.glob(".activity-*")))

    def test_matching_tool_result_preserves_observed_category_without_guessing_other_calls(self):
        def tool_event(kind,at,call_id,name=None):
            payload={'type':kind,'turn_id':'private-turn-id','call_id':call_id}
            if name:payload['name']=name
            return normalize_codex_record({'timestamp':datetime.fromtimestamp(at,timezone.utc).isoformat(),
                                           'type':'response_item','payload':payload},'private-session-id',at)
        self.store.record(tool_event('function_call',NOW,'call-a','read_file'))
        self.store.record(tool_event('function_call_output',NOW+1,'call-a'))
        self.assertEqual(self.store.read()[0].summary,'reading_files')
        self.store.record(tool_event('function_call_output',NOW+2,'call-other'))
        self.assertEqual(self.store.read()[0].summary,'using_tool')

    def test_expiry_unknown_and_no_selected(self):
        self.store.record(hook())
        self.assertEqual(self.collector.snapshot()["selected"]["state"], "running")
        self.now += TTL["running"]
        snapshot = self.collector.snapshot()
        self.assertIsNone(snapshot["selected"])
        row = snapshot["providers"][0]
        self.assertEqual(row["state"], "unknown"); self.assertTrue(row["stale"])

    def test_priority_waiting_and_other_provider(self):
        self.store.record(hook())
        self.store.record(hook("claude", "PermissionRequest"))
        self.assertEqual(self.collector.snapshot()["selected"]["provider"], "claude")

    def test_unrelated_tool_does_not_clear_wait(self):
        self.store.record(hook("claude", "PermissionRequest", tool_use_id="approval-tool"))
        self.store.record(hook("claude", "PostToolUse", now=NOW + 1, tool_use_id="unrelated-tool"))
        self.assertEqual(self.collector.snapshot()["selected"]["state"], "waiting_approval")
        self.store.record(hook("claude", "PostToolUse", now=NOW + 2, tool_use_id="approval-tool"))
        self.assertEqual(self.collector.snapshot()["selected"]["state"], "running")

    def test_model_resume_and_completion_clear_wait(self):
        self.store.record(hook(event="PermissionRequest"))
        self.store.record(hook(event="PreModelRequest", now=NOW + 1))
        self.assertEqual(self.collector.snapshot()["selected"]["state"], "running")
        self.store.record(hook(event="Stop", now=NOW + 2))
        self.assertEqual(self.collector.snapshot()["selected"]["state"], "completed")

    def test_session_end_clears_all_turns(self):
        self.store.record(hook())
        self.store.record(hook(event="SessionEnd", now=NOW + 1, turn_id=None))
        self.assertIsNone(self.collector.snapshot()["selected"])

    def test_out_of_order_rejected(self):
        self.store.record(hook(event="Stop", now=NOW))
        self.store.record(hook(now=NOW - 1))
        self.assertEqual(self.collector.snapshot()["selected"]["state"], "completed")

    def test_old_other_turn_does_not_resurrect_after_completion(self):
        self.store.record(hook(event="Stop", now=NOW))
        self.store.record(hook(now=NOW - 1, turn_id="earlier-turn"))
        self.assertEqual(self.collector.snapshot()["selected"]["state"], "completed")

    def test_malformed_event_field_types_fail_closed(self):
        self.store.record(hook())
        data = json.loads(self.store.path.read_text())
        data["events"][0]["state"] = {"unexpected": "object"}
        self.store.path.write_text(json.dumps(data))
        self.assertEqual(self.store.read(), [])

    def test_concurrent_sessions_count(self):
        self.store.record(hook(session_id="one")); self.store.record(hook(session_id="two"))
        self.assertEqual(self.collector.snapshot()["selected"]["active_count"], 2)

    def test_journal_capacity(self):
        for i in range(MAX_SESSIONS + 3): self.store.record(hook(session_id=str(i), now=NOW + i / 100))
        self.assertEqual(len(self.store.read()), MAX_SESSIONS)

    def test_symlink_state_and_lock_refused(self):
        outside = Path(self.temp.name) / "outside"; outside.write_text("preserve")
        self.path.mkdir(); self.store.path.symlink_to(outside)
        self.assertEqual(self.store.read(), [])
        # atomic replacement replaces the link, never the target.
        self.assertTrue(self.store.record(hook()))
        self.assertEqual(outside.read_text(), "preserve")
        (self.path / "activity.lock").unlink(); (self.path / "activity.lock").symlink_to(outside)
        self.assertFalse(self.store.record(hook()))
        self.assertEqual(outside.read_text(), "preserve")

    def test_invalid_journal_rows_and_future_events_ignored(self):
        self.store.record(hook(now=NOW + 500))
        self.assertIsNone(self.collector.snapshot()["selected"])
        self.store.path.write_text('{"schema":1,"events":[{"provider":"bad"},null]}')
        self.assertEqual(self.store.read(), [])


class CodexTailTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.home = Path(self.temp.name)
        self.dir = self.home / "sessions" / datetime.fromtimestamp(NOW).strftime("%Y/%m/%d")
        self.dir.mkdir(parents=True)
        self.path = self.dir / "rollout-11111111-1111-1111-1111-111111111111.jsonl"
        self.tail = CodexLogTail(self.home)
    def tearDown(self): self.temp.cleanup()
    def write(self, data, mode="wb"):
        with self.path.open(mode) as stream: stream.write(data)
        os.utime(self.path, (NOW, NOW))
    def line(self, row): return (json.dumps(row) + "\n").encode()

    def test_explicit_start_complete_and_ignore_message_text(self):
        for kind, state in (("task_started", "running"), ("task_complete", "completed")):
            event = normalize_codex_record(record(kind, last_agent_message="SECRET"), "session", NOW)
            self.assertEqual(event.state, state); self.assertNotIn("SECRET", str(event))
        self.assertIsNone(normalize_codex_record(record("agent_message", message="Need approval?"), "session", NOW))

    def test_future_ancient_invalid_and_unknown_schemas(self):
        for row in (record("task_started", NOW + 10), record("task_started", NOW - 700),
                    {"timestamp": "bad", "payload": {}}, [], record("approval_looking_but_undocumented")):
            self.assertIsNone(normalize_codex_record(row, "session", NOW))
        self.assertIsNone(normalize_codex_record(record([]), "session", NOW))
        self.assertIsNone(normalize_codex_record(record("item_completed", item={"type": {}}), "session", NOW))

    def test_incremental_no_replay_and_truncate(self):
        self.write(self.line(record("task_started")))
        self.assertEqual(len(self.tail.poll(NOW)), 1)
        self.assertEqual(self.tail.poll(NOW), [])
        self.write(self.line(record("task_complete", NOW + 1)), "ab")
        self.assertEqual(self.tail.poll(NOW + 1)[0].state, "completed")
        self.write(self.line(record("task_started", NOW + 2)))
        self.assertEqual(self.tail.poll(NOW + 2)[0].state, "running")

    def test_partial_lines_only_processed_after_newline(self):
        data = self.line(record("task_started")); split = len(data) // 2
        self.write(data[:split]); self.assertEqual(self.tail.poll(NOW), [])
        self.write(data[split:], "ab"); self.assertEqual(len(self.tail.poll(NOW)), 1)

    def test_large_line_is_skipped_tail_is_bounded(self):
        self.write(b"x" * (MAX_TAIL_BYTES + 100) + b"\n" + self.line(record("task_complete")))
        events = self.tail.poll(NOW)
        self.assertEqual(len(events), 1); self.assertEqual(events[0].state, "completed")

    def test_oversized_stream_across_polls_does_not_parse_line_suffix(self):
        self.write(b"x" * MAX_TAIL_BYTES)
        self.assertEqual(self.tail.poll(NOW), [])
        self.write(self.line(record("task_started")) + self.line(record("task_complete")), "ab")
        events = self.tail.poll(NOW)
        self.assertEqual([e.state for e in events], ["completed"])

    def test_symlink_log_not_read(self):
        outside = self.home / "outside.jsonl"; outside.write_bytes(self.line(record("task_started")))
        os.utime(outside, (NOW, NOW)); self.path.symlink_to(outside)
        self.assertEqual(self.tail.poll(NOW), [])

    def test_tool_context_and_explicit_input_call_id(self):
        start = record("task_started")
        call = {"timestamp": start["timestamp"], "type": "response_item", "payload":
                {"type": "function_call", "name": "request_user_input", "call_id": "private-call", "arguments": "SECRET"}}
        self.write(self.line(start) + self.line(call))
        events = self.tail.poll(NOW)
        self.assertEqual(events[-1].state, "waiting_input")
        self.assertEqual(events[0].turn_id, events[1].turn_id)
        self.assertNotIn("SECRET", str(events))
        self.assertNotIn("private-call", str(events))

    def test_response_item_without_turn_context_is_not_invented(self):
        row = {"timestamp": record("x")["timestamp"], "type": "response_item", "payload": {"type": "function_call", "name": "exec_command"}}
        self.write(self.line(row)); self.assertEqual(self.tail.poll(NOW), [])

    def test_collector_reads_real_source_class_without_writing_log(self):
        original = self.line(record("task_started"))
        self.write(original)
        collector = ActivityCollector(self.home / "state", self.home, clock=lambda: NOW)
        snapshot = collector.snapshot()
        self.assertEqual(snapshot["selected"]["source"], "codex_log")
        self.assertEqual(snapshot["selected"]["state"], "running")
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse((self.home / "state").exists())


if __name__ == "__main__": unittest.main()
