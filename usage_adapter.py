"""Read CodexBar quotas without handling provider credentials.

The normal path only reads CodexBar's opt-in, identity-free CLI usage cache.
An explicit ``snapshot(refresh=True)`` uses the installed signed CLI. No settings
or CodexBar files are written. Unknown quota is always None, never zero.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import signal
import stat
import subprocess
from typing import Any

PROVIDERS = ("claude", "cursor", "codex")
LABELS = {"claude": "Claude", "cursor": "Cursor", "codex": "Codex"}
DEFAULT_CLI = Path("/Applications/CodexBar.app/Contents/Helpers/CodexBarCLI")
DEFAULT_CACHE = Path.home() / "Library/Application Support/CodexBar/CLIUsageCache/usage.json"
DEFAULT_HISTORY = Path.home() / "Library/Application Support/com.steipete.codexbar/history"
MAX_FILE_BYTES = 8 * 1024 * 1024


def _date(value: Any) -> datetime | None:
    """Only ISO dates: the documented cache/CLI uses ISO, not Apple's epoch."""
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (ValueError, OverflowError):
        return None


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def _remaining(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return round(max(0.0, 100.0 - value), 2)


def _read_json(path: Path, *, private: bool = False) -> Any:
    """Bounded read of a regular same-user file; never open symlinks/FIFOs."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                return None
            if private and stat.S_IMODE(info.st_mode) != 0o600:
                return None
            if info.st_size > MAX_FILE_BYTES:
                return None
            raw = stream.read(MAX_FILE_BYTES + 1)
            return json.loads(raw) if len(raw) <= MAX_FILE_BYTES else None
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _label(slot: str, window: dict, labels: dict) -> str:
    label = labels.get(slot) or window.get("title")
    if isinstance(label, str) and 0 < len(label) <= 40:
        return label
    minutes = window.get("windowMinutes")
    if minutes == 300:
        return "5h"
    if minutes == 10080:
        return "7d"
    if minutes == 1440:
        return "24h"
    if isinstance(minutes, (int, float)) and not isinstance(minutes, bool) and math.isfinite(minutes) and minutes > 0:
        return f"{minutes / 60:g}h" if minutes % 60 == 0 else f"{minutes:g}m"
    return {"primary": "Primary", "secondary": "Secondary", "tertiary": "Other"}.get(slot, slot)


def _unavailable(provider: str, error: str, source: str) -> dict:
    return {
        "id": provider, "label": LABELS[provider], "remaining_percent": None,
        "remaining_label": None, "windows": [], "updated_at": None,
        "stale": True, "error": error, "source": source,
    }


def normalize_usage(provider: str, payload: dict, *, now: datetime | None = None,
                    max_age: float = 900, source: str = "codexbar-cli") -> dict:
    """Normalize one CLI/cache entry; retain window identity and measured time.

    ``remaining_percent`` is the first available primary/secondary window,
    never a sum or minimum across unlike limits. Render ``remaining_label``
    beside it; all independent quota windows remain available in ``windows``.
    """
    if provider not in PROVIDERS:
        raise ValueError("Unsupported provider")
    now = now or datetime.now(timezone.utc)
    payload = payload if isinstance(payload, dict) else {}
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return _unavailable(provider, "fetch_failed" if payload.get("error") else "no_usage", source)
    updated = _date(usage.get("updatedAt"))
    age = (now - updated).total_seconds() if updated else None
    stale = age is None or age < -60 or age > max_age
    confidence = usage.get("dataConfidence")
    if isinstance(confidence, str) and any(x in confidence.lower() for x in ("stale", "lastknown", "cached")):
        stale = True
    labels = payload.get("rateWindowLabels") or {}
    if not isinstance(labels, dict):
        labels = {}
    result = _unavailable(provider, "no_usage", source)
    windows = []
    candidates = [(slot, usage.get(slot), True) for slot in ("primary", "secondary", "tertiary")]
    extras = usage.get("extraRateWindows")
    if isinstance(extras, list):
        for extra in extras:
            if not isinstance(extra, dict) or not isinstance(extra.get("id"), str):
                continue
            win = extra.get("window")
            if isinstance(win, dict):
                win = dict(win, title=extra.get("title"))
                candidates.append(("extra:" + extra["id"], win, extra.get("usageKnown") is not False))
    for slot, win, known in candidates:
        if not isinstance(win, dict):
            continue
        if win.get("isSyntheticPlaceholder") is True:
            continue
        remaining = _remaining(win.get("usedPercent")) if known else None
        reset = _date(win.get("resetsAt"))
        windows.append({
            "id": slot, "label": _label(slot, win, labels),
            "remaining_percent": remaining, "resets_at": _iso(reset),
            "updated_at": _iso(updated),
            "stale": stale or (reset is not None and reset <= now),
        })
    selectable = [w for w in windows if w["id"] in ("primary", "secondary") and w["remaining_percent"] is not None]
    selected = next((w for w in selectable if not w["stale"]), next(iter(selectable), None))
    result.update(windows=windows, updated_at=_iso(updated))
    if selected:
        result.update(remaining_percent=selected["remaining_percent"], remaining_label=selected["label"],
                      stale=selected["stale"], error=None)
    return result


class UsageAdapter:
    """Identity-free local cache adapter, with explicit optional CLI refresh."""

    def __init__(self, cache_path: Path | str = DEFAULT_CACHE,
                 cli_path: Path | str = DEFAULT_CLI,
                 history_dir: Path | str | None = DEFAULT_HISTORY,
                 max_age: float = 900, timeout: float = 25):
        if not math.isfinite(max_age) or max_age <= 0 or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("max_age and timeout must be positive finite numbers")
        self.cache_path = Path(cache_path)
        self.cli_path = Path(cli_path)
        self.history_dir = Path(history_dir) if history_dir is not None else None
        self.max_age = max_age
        self.timeout = timeout

    def _history(self, provider: str, now: datetime) -> dict | None:
        """Best-effort history fallback; requires CodexBar's preferred account.

        Histories are change-point records, so an unchanged value can have an
        old capture time. Never substitute file mtime or call it freshly read.
        """
        if not self.history_dir or provider == "cursor":
            return None
        document = _read_json(self.history_dir / f"{provider}.json")
        if not isinstance(document, dict):
            return None
        accounts = document.get("accounts")
        key = document.get("preferredAccountKey")
        if not isinstance(accounts, dict) or not isinstance(key, str):
            return None
        stored_windows = accounts.get(key)
        if not isinstance(stored_windows, list):
            return None
        windows = []
        for stored in stored_windows:
            if not isinstance(stored, dict) or stored.get("name") not in ("session", "weekly"):
                continue
            entries = stored.get("entries")
            if not isinstance(entries, list):
                continue
            dated = [(date, e) for e in entries if isinstance(e, dict)
                     if (date := _date(e.get("capturedAt"))) is not None]
            if not dated:
                continue
            captured, entry = max(dated, key=lambda row: row[0])
            slot = "primary" if stored["name"] == "session" else "secondary"
            normalized = normalize_usage(provider, {"usage": {
                "updatedAt": _iso(captured), slot: {
                    "usedPercent": entry.get("usedPercent"), "resetsAt": entry.get("resetsAt"),
                    "windowMinutes": stored.get("windowMinutes")}}},
                now=now, max_age=self.max_age, source="codexbar-history")
            windows.extend(normalized["windows"])
        windows.sort(key=lambda w: (w["stale"], w["id"] != "primary"))
        selected = next((w for w in windows if w["remaining_percent"] is not None), None)
        if not selected:
            return None
        result = _unavailable(provider, "history_only", "codexbar-history")
        result.update(windows=windows, remaining_percent=selected["remaining_percent"],
                      remaining_label=selected["label"], updated_at=selected["updated_at"], stale=True)
        # A change-point history is not evidence that the current app fetch
        # succeeded, even when its most recent entry is within max_age.
        for win in result["windows"]:
            win["stale"] = True
        return result

    def _fetch(self, provider: str, now: datetime) -> dict:
        command = [str(self.cli_path), "usage", "--provider", provider, "--format", "json",
                   "--json-only", "--no-credits", "--web-timeout", str(max(1, int(self.timeout - 5))) ]
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       text=True, start_new_session=True)
            try:
                output, _ = process.communicate(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                return _unavailable(provider, "timeout", "codexbar-cli")
            if len(output) > MAX_FILE_BYTES:
                return _unavailable(provider, "invalid_response", "codexbar-cli")
            payload = json.loads(output)
            rows = payload if isinstance(payload, list) else [payload]
            row = next((r for r in rows if isinstance(r, dict) and r.get("provider") == provider), {})
            return normalize_usage(provider, row, now=now, max_age=self.max_age)
        except (OSError, ValueError, UnicodeDecodeError):
            return _unavailable(provider, "cli_unavailable", "codexbar-cli")

    def snapshot(self, refresh: bool = False, *, now: datetime | None = None) -> dict:
        """Return only quota figures. ``refresh=False`` makes no network calls."""
        now = now or datetime.now(timezone.utc)
        document = _read_json(self.cache_path, private=True)
        entries = document.get("entries", []) if isinstance(document, dict) else []
        if not isinstance(entries, list):
            entries = []
        providers = {}
        for provider in PROVIDERS:
            row = next((r for r in entries if isinstance(r, dict) and r.get("provider") == provider), None)
            if row is not None:
                providers[provider] = normalize_usage(provider, row, now=now,
                                                       max_age=self.max_age, source="codexbar-cache")
            else:
                providers[provider] = (self._history(provider, now) or
                                       _unavailable(provider, "cache_unavailable", "codexbar-cache"))
        if refresh:
            with ThreadPoolExecutor(max_workers=len(PROVIDERS)) as pool:
                fresh = list(pool.map(lambda provider: self._fetch(provider, now), PROVIDERS))
            for row in fresh:
                previous = providers[row["id"]]
                if row["remaining_percent"] is not None or previous["remaining_percent"] is None:
                    providers[row["id"]] = row
                else:
                    previous["error"] = row["error"]
                    previous["stale"] = True
                    for win in previous["windows"]:
                        win["stale"] = True
        return {"generated_at": _iso(now), "providers": [providers[p] for p in PROVIDERS]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Fetch via installed CodexBar CLI")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--max-age", type=float, default=900)
    parser.add_argument("--no-history", action="store_true", help="Disable stale history fallback")
    args = parser.parse_args()
    adapter = UsageAdapter(cache_path=args.cache, max_age=args.max_age,
                           history_dir=None if args.no_history else DEFAULT_HISTORY)
    print(json.dumps(adapter.snapshot(refresh=args.refresh), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
