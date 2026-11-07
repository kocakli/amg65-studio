"""Schema/age/privacy checks for the CodexBar bridge (no network or credentials)."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from usage_adapter import UsageAdapter, normalize_usage

NOW = datetime(2026, 11, 7, 8, 30, tzinfo=timezone.utc)


def payload(used=20, updated="2026-11-07T08:29:00Z", reset="2026-11-07T12:00:00Z"):
    return {"provider": "claude", "usage": {"updatedAt": updated,
            "primary": {"usedPercent": used, "windowMinutes": 300, "resetsAt": reset}}}


class NormalizeTests(unittest.TestCase):
    def test_measured_zero_is_full_remaining(self):
        result = normalize_usage("claude", payload(0), now=NOW)
        self.assertEqual(result["remaining_percent"], 100)
        self.assertFalse(result["stale"])

    def test_missing_nan_negative_and_boolean_are_unknown(self):
        for value in (None, float("nan"), float("inf"), -1, True, "20"):
            with self.subTest(value=value):
                result = normalize_usage("claude", payload(value), now=NOW)
                self.assertIsNone(result["remaining_percent"])

    def test_over_quota_clamps_display_remaining(self):
        self.assertEqual(normalize_usage("claude", payload(125), now=NOW)["remaining_percent"], 0)

    def test_old_timestamp_never_becomes_read_time(self):
        result = normalize_usage("claude", payload(updated="2026-11-07T07:00:00Z"), now=NOW)
        self.assertTrue(result["stale"])
        self.assertEqual(result["updated_at"], "2026-11-07T07:00:00Z")

    def test_reset_passed_marks_stale(self):
        result = normalize_usage("claude", payload(reset="2026-11-07T08:00:00Z"), now=NOW)
        self.assertTrue(result["stale"])

    def test_unknown_naive_and_future_measurements_stale(self):
        for updated in (None, "2026-11-07T08:29:00", "2026-11-07T09:29:00Z"):
            self.assertTrue(normalize_usage("claude", payload(updated=updated), now=NOW)["stale"])

    def test_normalizes_timezone_and_preserves_reset(self):
        result = normalize_usage("claude", payload(updated="2026-11-07T17:29:00+09:00"), now=NOW)
        self.assertEqual(result["updated_at"], "2026-11-07T08:29:00Z")
        self.assertEqual(result["windows"][0]["resets_at"], "2026-11-07T12:00:00Z")

    def test_synthetic_claude_session_is_not_free_quota(self):
        row = payload(0)
        row["usage"]["primary"]["isSyntheticPlaceholder"] = True
        row["usage"]["secondary"] = {"usedPercent": 35, "windowMinutes": 10080}
        result = normalize_usage("claude", row, now=NOW)
        self.assertEqual(result["remaining_percent"], 65)
        self.assertEqual(result["remaining_label"], "7d")
        self.assertEqual(len(result["windows"]), 1)

    def test_independent_windows_not_aggregated(self):
        row = payload(20)
        row["usage"]["secondary"] = {"usedPercent": 90, "windowMinutes": 10080}
        result = normalize_usage("claude", row, now=NOW)
        self.assertEqual(result["remaining_percent"], 80)
        self.assertEqual(result["windows"][1]["remaining_percent"], 10)

    def test_expired_primary_does_not_hide_fresh_secondary(self):
        row = payload(reset="2026-11-07T08:00:00Z")
        row["usage"]["secondary"] = {"usedPercent": 10, "windowMinutes": 10080,
                                      "resetsAt": "2026-11-14T08:00:00Z"}
        result = normalize_usage("claude", row, now=NOW)
        self.assertEqual(result["remaining_percent"], 90)
        self.assertTrue(result["windows"][0]["stale"])

    def test_unknown_named_quota_and_code_review_not_primary(self):
        row = {"usage": {"updatedAt": "2026-11-07T08:29:00Z",
                         "tertiary": {"usedPercent": 0}, "extraRateWindows": [
                             {"id": "grok", "title": "Grok", "usageKnown": False,
                              "window": {"usedPercent": 100, "windowMinutes": 10080}}]}}
        result = normalize_usage("cursor", row, now=NOW)
        self.assertIsNone(result["remaining_percent"])
        self.assertIsNone(result["windows"][1]["remaining_percent"])

    def test_error_does_not_expose_provider_message_or_identity(self):
        row = {"error": {"message": "secret-cookie=abc user@example.com"}}
        result = normalize_usage("claude", row, now=NOW)
        self.assertEqual(result["error"], "fetch_failed")
        self.assertNotIn("secret", json.dumps(result))
        row = payload()
        row["usage"]["accountEmail"] = "user@example.com"
        self.assertNotIn("user@example.com", json.dumps(normalize_usage("claude", row, now=NOW)))


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / "usage.json"
        self.adapter = UsageAdapter(cache_path=self.cache, history_dir=None)

    def write_cache(self, entries):
        self.cache.write_text(json.dumps({"entries": entries}))
        self.cache.chmod(0o600)

    def test_cache_is_default_and_never_launches_cli(self):
        self.write_cache([payload()])
        with patch.object(self.adapter, "_fetch", side_effect=AssertionError("No subprocess")):
            snapshot = self.adapter.snapshot(now=NOW)
        self.assertEqual(snapshot["providers"][0]["remaining_percent"], 80)
        self.assertEqual(snapshot["providers"][0]["source"], "codexbar-cache")
        self.assertIsNone(snapshot["providers"][1]["remaining_percent"])

    def test_nonprivate_symlink_and_corrupt_cache_unavailable(self):
        self.write_cache([payload()])
        self.cache.chmod(0o644)
        self.assertIsNone(self.adapter.snapshot(now=NOW)["providers"][0]["remaining_percent"])
        self.cache.unlink()
        target = self.root / "target.json"
        target.write_text(json.dumps({"entries": [payload()]}))
        target.chmod(0o600)
        self.cache.symlink_to(target)
        self.assertIsNone(self.adapter.snapshot(now=NOW)["providers"][0]["remaining_percent"])
        self.cache.unlink()
        self.cache.write_text("{broken")
        self.cache.chmod(0o600)
        self.assertIsNone(self.adapter.snapshot(now=NOW)["providers"][0]["remaining_percent"])

    def test_failed_refresh_preserves_but_marks_last_known(self):
        self.write_cache([payload()])
        with patch.object(self.adapter, "_fetch", side_effect=lambda provider, now:
                          normalize_usage(provider, {"error": {}}, now=now)):
            snapshot = self.adapter.snapshot(refresh=True, now=NOW)
        result = snapshot["providers"][0]
        self.assertEqual(result["remaining_percent"], 80)
        self.assertTrue(result["stale"])
        self.assertTrue(result["windows"][0]["stale"])
        self.assertEqual(result["updated_at"], "2026-11-07T08:29:00Z")

    def test_history_preserves_each_window_measurement(self):
        history = {"preferredAccountKey": "preferred", "accounts": {"preferred": [
            {"name": "session", "windowMinutes": 300, "entries": [
                {"capturedAt": "2026-10-30T07:00:00Z", "resetsAt": "2026-10-30T12:00:00Z", "usedPercent": 1}]},
            {"name": "weekly", "windowMinutes": 10080, "entries": [
                {"capturedAt": "2026-11-07T08:29:00Z", "resetsAt": "2026-11-12T12:00:00Z", "usedPercent": 10}]}]}}
        (self.root / "claude.json").write_text(json.dumps(history))
        adapter = UsageAdapter(cache_path=self.cache, history_dir=self.root)
        result = adapter.snapshot(now=NOW)["providers"][0]
        self.assertEqual(result["remaining_label"], "7d")
        self.assertTrue(result["stale"])
        self.assertEqual(result["error"], "history_only")
        session = next(w for w in result["windows"] if w["id"] == "primary")
        self.assertEqual(session["updated_at"], "2026-10-30T07:00:00Z")
        self.assertTrue(session["stale"])
        self.assertNotIn("preferred", json.dumps(result))

    def test_history_never_guesses_account(self):
        (self.root / "claude.json").write_text(json.dumps({"accounts": {"somebody": []}}))
        result = UsageAdapter(cache_path=self.cache, history_dir=self.root).snapshot(now=NOW)
        self.assertIsNone(result["providers"][0]["remaining_percent"])

    def test_validates_configuration(self):
        for kwargs in ({"max_age": 0}, {"timeout": -1}, {"max_age": float("nan")}):
            with self.assertRaises(ValueError):
                UsageAdapter(**kwargs)


if __name__ == "__main__":
    unittest.main()
