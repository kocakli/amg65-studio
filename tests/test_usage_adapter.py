"""Schema/age/privacy checks for the independent Studio engine (no network or credentials)."""

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
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache=Path(self.temp.name)/"usage.json"
        self.adapter=UsageAdapter(cache_path=self.cache,autostart=False)
        self.addCleanup(self.adapter.close)

    def row(self, fingerprint='a'*64, error=None):
        row=payload()
        row['accountFingerprint']=fingerprint
        if error:
            row.pop('usage')
            row['error']={'code':error}
        return row

    def test_private_cache_has_no_identity_and_no_credentials(self):
        row=self.row()
        row.update(email='user@example.com',accessToken='SECRET')
        row['usage']['accountEmail']='user@example.com'
        self.adapter._merge([row],NOW)
        stored=self.cache.read_text()
        self.assertNotIn('SECRET',stored)
        self.assertNotIn('user@example.com',stored)
        self.assertEqual(self.cache.stat().st_mode & 0o777,0o600)
        visible=json.dumps(self.adapter.snapshot(now=NOW))
        self.assertNotIn('a'*64,visible)
        self.assertEqual(self.adapter.snapshot(now=NOW)['providers'][0]['remaining_percent'],80)

    def test_snapshot_never_blocks_on_fetch(self):
        import threading
        entered=threading.Event(); release=threading.Event()
        def fetch():
            entered.set(); release.wait(2)
            return [self.row()]
        with patch.object(self.adapter,'_fetch_all',side_effect=fetch):
            result=self.adapter.snapshot(refresh=True,now=NOW)
            self.assertTrue(entered.wait(1))
            self.assertIsNone(result['providers'][0]['remaining_percent'])
            self.assertFalse(self.adapter.request_refresh(force=True))
            release.set(); self.adapter._thread.join(2)
            self.assertEqual(self.adapter.snapshot(now=NOW)['providers'][0]['remaining_percent'],80)

    def test_same_account_network_failure_preserves_measured_time_as_stale(self):
        self.adapter._merge([self.row()],NOW)
        self.adapter._merge([self.row(error='network_error')],NOW)
        row=self.adapter.snapshot(now=NOW)['providers'][0]
        self.assertEqual(row['remaining_percent'],80)
        self.assertTrue(row['stale'])
        self.assertEqual(row['updated_at'],'2026-11-07T08:29:00Z')
        self.assertEqual(row['error'],'network_error')

    def test_different_or_missing_identity_never_reuses_previous_account(self):
        for fingerprint in ('b'*64,None):
            self.adapter._merge([self.row()],NOW)
            self.adapter._merge([self.row(fingerprint,error='network_error')],NOW)
            self.assertIsNone(self.adapter.snapshot(now=NOW)['providers'][0]['remaining_percent'])

    def test_auth_failure_clears_previous_measurement(self):
        self.adapter._merge([self.row()],NOW)
        self.adapter._merge([self.row(error='relogin_required')],NOW)
        row=self.adapter.snapshot(now=NOW)['providers'][0]
        self.assertIsNone(row['remaining_percent'])
        self.assertEqual(row['error'],'relogin_required')

    def test_cache_reloaded_without_codexbar_or_network(self):
        self.adapter._merge([self.row()],NOW)
        loaded=UsageAdapter(cache_path=self.cache,autostart=False)
        with patch.object(loaded,'_fetch_all',side_effect=AssertionError('No network')):
            self.assertEqual(loaded.snapshot(now=NOW)['providers'][0]['remaining_percent'],80)
        loaded.close()

    def test_nonprivate_symlink_corrupt_cache_rejected(self):
        self.cache.write_text(json.dumps({'entries':[self.row()]})); self.cache.chmod(0o644)
        self.assertIsNone(UsageAdapter(cache_path=self.cache,autostart=False).snapshot(now=NOW)['providers'][0]['remaining_percent'])
        self.cache.unlink()
        target=self.cache.with_name('target.json'); target.write_text(json.dumps({'entries':[self.row()]})); target.chmod(0o600)
        self.cache.symlink_to(target)
        self.assertIsNone(UsageAdapter(cache_path=self.cache,autostart=False).snapshot(now=NOW)['providers'][0]['remaining_percent'])
        self.cache.unlink(); self.cache.write_text('{broken'); self.cache.chmod(0o600)
        self.assertIsNone(UsageAdapter(cache_path=self.cache,autostart=False).snapshot(now=NOW)['providers'][0]['remaining_percent'])

    def test_malformed_error_is_bounded_to_safe_code(self):
        self.adapter._merge([{'provider':'claude','error':{'code':{'token':'SECRET'}}}],NOW)
        self.assertNotIn('SECRET',json.dumps(self.adapter.snapshot(now=NOW)))

    def test_validates_configuration(self):
        for kwargs in ({'max_age':0},{'timeout':-1},{'max_age':float('nan')},{'refresh_interval':True}):
            with self.assertRaises(ValueError): UsageAdapter(**kwargs)


if __name__ == '__main__': unittest.main()
