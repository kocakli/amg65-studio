"""Independent, nonblocking quota polling through Studio's bundled native helper.

Only normalized measurements and opaque account fingerprints are cached. Provider
credentials remain in their original app/CLI stores and never reach this module.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import signal
import tempfile
import threading
import time
import copy
import re
import stat
import subprocess
from typing import Any

PROVIDERS = ("claude", "cursor", "codex")
LABELS = {"claude": "Claude", "cursor": "Cursor", "codex": "Codex"}
DEFAULT_HELPER = Path(__file__).resolve().parent / "bin/amg65-usage"
DEFAULT_CACHE = Path.home() / "Library/Application Support/AMG65 Studio/state/usage.json"
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
                    max_age: float = 900, source: str = "studio-direct") -> dict:
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


ERROR_CODES = frozenset(('auth_required','relogin_required','keychain_locked','network_error',
                         'rate_limited','invalid_response','unavailable','timeout','helper_unavailable','fetch_failed','no_usage','access_denied','credentials_unreadable','invalid_credentials'))
RETAINABLE_ERRORS = frozenset(('network_error','rate_limited','timeout'))


def _error_code(row):
    error = row.get('error') if isinstance(row, dict) else None
    code = error.get('code') if isinstance(error, dict) else error
    return code if isinstance(code,str) and code in ERROR_CODES else ('fetch_failed' if error else None)


def _safe_entry(provider, row, now):
    """Whitelist helper output before persistence; discard identities and secrets."""
    row = row if isinstance(row, dict) else {}
    normalized = normalize_usage(provider, row, now=now)
    result = {'provider':provider}
    fingerprint = row.get('accountFingerprint')
    if isinstance(fingerprint,str) and re.fullmatch(r'[a-f0-9]{64}',fingerprint):
        result['accountFingerprint']=fingerprint
    if isinstance(row.get('usage'),dict):
        usage={'updatedAt':normalized['updated_at']}
        extras=[]
        labels={}
        for window in normalized['windows']:
            value=window['remaining_percent']
            item={'usedPercent':None if value is None else 100-value,'resetsAt':window['resets_at']}
            slot=window['id']
            if slot.startswith('extra:'):
                extras.append({'id':slot[6:64],'title':window['label'],'window':item,'usageKnown':value is not None})
            else:
                usage[slot]=item
                labels[slot]=window['label']
        if extras: usage['extraRateWindows']=extras[:12]
        if row['usage'].get('dataConfidence') == 'lastknown': usage['dataConfidence']='lastknown'
        result.update(usage=usage,rateWindowLabels=labels)
    code=_error_code(row)
    if code: result['error']={'code':code}
    return result


class UsageAdapter:
    """Refresh every five minutes on one daemon thread; USB never waits on HTTPS."""

    def __init__(self, cache_path=DEFAULT_CACHE, helper_path=DEFAULT_HELPER,
                 max_age=900, timeout=25, refresh_interval=300, autostart=True):
        for value in (max_age,timeout,refresh_interval):
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value <= 0:
                raise ValueError('Timing values must be positive finite numbers')
        self.cache_path=Path(cache_path)
        self.helper_path=Path(helper_path)
        self.max_age=max_age; self.timeout=timeout; self.refresh_interval=refresh_interval
        self.autostart=autostart
        self._lock=threading.RLock()
        self._thread=None; self._process=None; self._closed=False
        self._next_refresh=0.0; self._last_attempt=None
        document=_read_json(self.cache_path,private=True)
        entries=document.get('entries',[]) if isinstance(document,dict) else []
        now=datetime.now(timezone.utc)
        self._entries={}
        if isinstance(entries,list):
            for row in entries[:len(PROVIDERS)]:
                if isinstance(row,dict) and row.get('provider') in PROVIDERS:
                    provider=row['provider']
                    self._entries[provider]=_safe_entry(provider,row,now)

    @property
    def refreshing(self):
        return self._thread is not None and self._thread.is_alive()

    def request_refresh(self, force=False):
        with self._lock:
            now=time.monotonic()
            if self._closed or self.refreshing or (not force and now < self._next_refresh):
                return False
            # Coalesce repeated clicks and bound retries even when authentication fails.
            if force and self._next_refresh-now > self.refresh_interval-10:
                return False
            self._next_refresh=now+self.refresh_interval
            self._last_attempt=_iso(datetime.now(timezone.utc))
            self._thread=threading.Thread(target=self._refresh,name='Studio quota refresh',daemon=True)
            self._thread.start()
            return True

    def _fetch_all(self):
        """The helper handles credentials internally and emits quota data only."""
        with tempfile.TemporaryFile() as output:
            try:
                process=subprocess.Popen([str(self.helper_path),'--provider','all'],stdout=output,
                    stderr=subprocess.DEVNULL,start_new_session=True)
                with self._lock:
                    self._process=process
                    closed=self._closed
                if closed:
                    process.terminate()
                try:
                    process.wait(timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL)
                    process.wait()
                    return [{'provider':p,'error':{'code':'timeout'}} for p in PROVIDERS]
                if os.fstat(output.fileno()).st_size > MAX_FILE_BYTES:
                    raise ValueError('Bounded helper response exceeded')
                output.seek(0)
                data=json.load(output)
                if not isinstance(data,list): raise ValueError('Expected provider array')
                return data[:len(PROVIDERS)]
            except (OSError,ValueError,UnicodeDecodeError):
                return [{'provider':p,'error':{'code':'helper_unavailable'}} for p in PROVIDERS]
            finally:
                with self._lock: self._process=None

    def _refresh(self):
        rows=self._fetch_all()
        self._merge(rows,datetime.now(timezone.utc))

    def _merge(self,rows,now):
        with self._lock:
            for provider in PROVIDERS:
                raw=next((r for r in rows if isinstance(r,dict) and r.get('provider')==provider),{})
                row=_safe_entry(provider,raw,now)
                old=self._entries.get(provider,{})
                fingerprint=row.get('accountFingerprint')
                if (_error_code(row) in RETAINABLE_ERRORS and fingerprint and
                    fingerprint == old.get('accountFingerprint') and isinstance(old.get('usage'),dict)):
                    row=copy.deepcopy(old)
                    row['usage']['dataConfidence']='lastknown'
                    row['error']={'code':_error_code(raw)}
                self._entries[provider]=row
            if not self._closed:
                self._persist()

    def _persist(self):
        # The containing service directory is private. Replace, never follow, a cache symlink.
        try:
            self.cache_path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            fd,path=tempfile.mkstemp(prefix='.usage-',dir=self.cache_path.parent)
            try:
                with os.fdopen(fd,'w') as stream:
                    json.dump({'version':1,'entries':list(self._entries.values())},stream)
                    stream.flush(); os.fsync(stream.fileno())
                os.replace(path,self.cache_path)
            finally:
                try: os.unlink(path)
                except FileNotFoundError: pass
        except OSError:
            # In-memory readings remain usable when the cache cannot be saved.
            pass

    def snapshot(self, refresh=False, *, now=None):
        now=now or datetime.now(timezone.utc)
        if refresh or self.autostart: self.request_refresh(force=refresh)
        with self._lock:
            providers=[]
            for provider in PROVIDERS:
                row=self._entries.get(provider,{})
                result=normalize_usage(provider,row,now=now,max_age=self.max_age)
                code=_error_code(row)
                if code: result['error']=code
                providers.append(result)
            return {'generated_at':_iso(now),'providers':providers,
                    'usage_refresh':{'running':self.refreshing,'last_attempt':self._last_attempt,
                                     'interval_seconds':self.refresh_interval}}

    def close(self):
        with self._lock:
            self._closed=True
            process=self._process
        if process is not None and process.poll() is None:
            try: process.terminate()
            except ProcessLookupError: pass


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh',action='store_true',help='Fetch directly using Studio’s own helper')
    parser.add_argument('--cache',type=Path,default=DEFAULT_CACHE)
    args=parser.parse_args()
    adapter=UsageAdapter(cache_path=args.cache,autostart=False)
    if args.refresh:
        adapter.request_refresh(force=True)
        adapter._thread.join(adapter.timeout+2)
    print(json.dumps(adapter.snapshot(),indent=2,ensure_ascii=False))
    adapter.close()


if __name__ == '__main__': main()
