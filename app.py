#!/usr/bin/env python3
"""Local Studio service for provider quotas, account login and the AMG65 display."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import selectors
import signal
import subprocess
import threading
import time

from renderer import select_activity, render_activity, render_overview, render_detail, render_text, apply_text_effect, render_mascot
from usage_adapter import UsageAdapter
from activity import ActivityCollector
from account_auth import AccountManager
from configuration import DEFAULTS, LIGHTING, settings_patch, lighting_request

BASE = Path(__file__).resolve().parent
PORT = 47866
CACHE_INTERVAL = 2
RECONNECT_INTERVAL = 15
SYNC_INTERVAL = 6 * 60 * 60
DEVICE_CODES = {
    'USB bağlantısı bekleniyor':'waiting',
    'LEOBOG AMG65 · USB bağlı':'ready',
    'Saat eşitlendi · USB hazır':'ready',
    'LED aktarımı etkin · USB onaylı':'streaming',
    'USB kontrolü yerel sürücüde':'native_control',
    'Önizleme modu · USB aktarımı kapalı':'no_device',
    'USB yanıtı kesildi. Kabloyu çıkarıp yeniden takın.':'fault_reconnect',
    'Yerel sürücü USB hatası bildirdi; kabloyu yeniden bağlayın.':'fault_reconnect',
    'USB hata kaydı okunamıyor; güvenli bağlantı için kayıt onarılmalı.':'fault_record',
}
OPERATION_CODES = {
    'Hazır':'ready',
    'Saat eşitleniyor…':'syncing',
    'Klavye saati Mac ile eşitlendi.':'synced',
    'LED aktarım tercihi kaydedildi.':'display_saved',
    'Ekran ayarları kaydedildi.':'settings_saved',
    'Aydınlatma uygulanıyor…':'lighting_applying',
    'Aydınlatma cihaz tarafından onaylandı.':'lighting_applied',
}


def iso_now():
    return datetime.now(timezone.utc).isoformat()


class Bridge:
    """Single writer; each request waits for the native helper's HID ACKs."""
    def __init__(self, binary):
        self.process = subprocess.Popen([str(binary), '--session'], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        text=True, bufsize=1)
        self.identity = None
        try:
            hello = self._read()
            self.identity = hello['registry_id']
        except Exception:
            self.close()
            raise

    def _read(self):
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            if not selector.select(5):
                raise OSError('USB köprüsü yanıt vermedi.')
        line = self.process.stdout.readline()
        if not line:
            raise OSError('USB köprüsü kapandı.')
        try:
            result = json.loads(line)
        except (ValueError,UnicodeDecodeError) as error:
            raise OSError('USB köprüsünden geçersiz yanıt.') from error
        if not isinstance(result,dict):
            raise OSError('USB köprüsünden geçersiz yanıt.')
        if not result.get('ok'):
            raise OSError(result.get('error', 'USB error'))
        return result

    def send(self, operation, **data):
        self.process.stdin.write(json.dumps(dict(op=operation, **data)) + '\n')
        self.process.stdin.flush()
        return self._read()

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
        if self.process.stdout:
            self.process.stdout.close()


class Application:
    def __init__(self, state_dir, no_device=False):
        self.state_dir = Path(state_dir)
        self.no_device = no_device
        self.adapter = UsageAdapter(cache_path=self.state_dir / "usage.json")
        self.activity = ActivityCollector(self.state_dir)
        self.accounts = AccountManager(self.state_dir)
        self._completed_logins = {}
        self.lock = threading.RLock()
        self.quit = threading.Event()
        self.commands = queue.Queue(maxsize=8)
        self.bridge = None
        self.blocked_identity = None
        self.blocked_state_invalid = False
        self.read_blocked_identity()
        self.display = True
        self.settings = dict(DEFAULTS, lighting=dict(LIGHTING))
        self.native_until = 0.0
        try:
            saved = json.loads((self.state_dir / 'settings.json').read_text())
            if not isinstance(saved,dict):
                raise ValueError('Invalid saved settings')
            self.display = saved.get('enabled', True) is True
            self.settings.update(settings_patch({k:v for k,v in saved.items() if k in DEFAULTS or k=='claude_mascot'}))
            if 'lighting' in saved:
                self.settings['lighting']=lighting_request(saved['lighting'])
        except (OSError, ValueError):
            pass
        self.state = self.adapter.snapshot()
        self.state.update(device={'connected': False, 'code':'waiting', 'message': 'USB bağlantısı bekleniyor', 'last_sync': None},
                          running=self.display, matrix={'pixels':render_overview(self.state,self.settings['brightness'],claude_green_gain=self.settings['claude_green_gain']),
                                                       'view':'overview','claude_green_gain':self.settings['claude_green_gain']},
                          settings=copy.deepcopy(self.settings), hardware_owner='dashboard',
                          product={'id':'amg65-studio','version':'0.3.0'},
                          operation={'pending':False,'code':'ready','message':'Hazır'})

    def read_blocked_identity(self):
        try:
            blocked = json.loads((self.state_dir/'usb-blocked.json').read_text())
            value = blocked.get('registry_id') if isinstance(blocked,dict) else None
            if type(value) is int and 0<value<2**64:
                self.blocked_identity = value
                self.blocked_state_invalid = False
            else:
                self.blocked_state_invalid = True
        except FileNotFoundError:
            self.blocked_state_invalid = False
        except (OSError, ValueError):
            self.blocked_state_invalid = True

    def save_blocked_identity(self):
        temporary=self.state_dir/'usb-blocked.tmp'
        temporary.write_text(json.dumps({'registry_id':self.blocked_identity}))
        temporary.chmod(0o600)
        temporary.replace(self.state_dir/'usb-blocked.json')

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def account_snapshot(self):
        result=self.accounts.snapshot()
        providers={row['id']:row for row in self.snapshot().get('providers',[])}
        for row in result.get('accounts',[]):
            usage=providers.get(row.get('provider'),{})
            row['usage']={key:usage.get(key) for key in ('remaining_percent','remaining_label','stale','error','updated_at')}
            provider=row.get('provider'); marker=row.get('expires_at')
            with self.lock:
                completed=row.get('phase')=='complete' and self._completed_logins.get(provider,object())!=marker
                if completed: self._completed_logins[provider]=marker
            if completed: self.adapter.request_refresh(force=True)
        return result

    def request(self, command, **params):
        try:
            self.commands.put_nowait((command, params))
        except queue.Full:
            raise ValueError('İşlem sürüyor; birkaç saniye sonra tekrar deneyin.')

    def operation(self, message, pending=False, ok=True):
        with self.lock:
            self.state['operation']={'message':message,'code':OPERATION_CODES.get(message,'error'),
                                     'pending':pending,'ok':ok,'updated_at':iso_now()}

    def save_settings(self):
        temporary=self.state_dir/'settings.tmp'
        temporary.write_text(json.dumps(dict(self.settings,enabled=self.display)))
        temporary.chmod(0o600)
        temporary.replace(self.state_dir/'settings.json')
        with self.lock:
            self.state['settings']=copy.deepcopy(self.settings)
            self.state['running']=self.display

    def release_to_native(self, tick):
        self.read_blocked_identity()
        if self.blocked_identity is not None or self.blocked_state_invalid:
            raise ValueError('USB yeniden bağlanmadan kontrol devredilemiyor.')
        if self.bridge:
            self.bridge.send('stop')
            self.bridge.close()
            self.bridge=None
        self.native_until=tick+45
        with self.lock:
            self.state['hardware_owner']='native'
        self.device_status(connected=False,message='USB kontrolü yerel sürücüde')

    def device_status(self, **values):
        if 'message' in values:
            values['code']=DEVICE_CODES.get(values['message'],'transport_error')
        with self.lock:
            self.state['device'].update(values)

    def sync(self):
        if not self.bridge:
            raise ValueError('Saat eşitlemek için AMG65 USB bağlantısı gerekli.')
        result = self.bridge.send('time')
        self.device_status(last_sync=result['synced_at'], timezone=result['timezone'],
                           message='Saat eşitlendi · USB hazır')
        logging.info('RTC synchronized: %s (%s)', result['synced_at'], result['timezone'])

    def disconnect(self, error):
        message = str(error)
        if self.bridge:
            # A missed ACK requires a new USB attachment, never blind repeated writes.
            self.blocked_identity = self.bridge.identity
            self.save_blocked_identity()
            self.bridge.close()
            self.bridge = None
        self.device_status(connected=False, message=message)
        logging.warning('USB: %s', message)

    def connect(self):
        if self.no_device:
            self.device_status(connected=False, message='Önizleme modu · USB aktarımı kapalı')
            return
        # A native app may have failed and exited without completing its handoff.
        self.read_blocked_identity()
        if self.blocked_state_invalid:
            self.device_status(connected=False,message='USB hata kaydı okunamıyor; güvenli bağlantı için kayıt onarılmalı.')
            return
        candidate = Bridge(BASE / 'bin/amg65-hid')
        if candidate.identity == self.blocked_identity:
            candidate.close()
            self.device_status(message='USB yanıtı kesildi. Kabloyu çıkarıp yeniden takın.')
            return
        self.blocked_identity = None
        (self.state_dir/'usb-blocked.json').unlink(missing_ok=True)
        self.bridge = candidate
        self.device_status(connected=True, message='LEOBOG AMG65 · USB bağlı')
        self.sync()

    def run(self):
        next_cache = next_connect = next_sync = 0.0
        last_pixels = None
        animation_step = 0
        started = time.monotonic()
        while not self.quit.is_set():
            tick = time.monotonic()
            if tick >= next_cache:
                try:
                    snapshot = self.adapter.snapshot()
                    snapshot["activity"] = self.activity.snapshot()
                    with self.lock:
                        self.state.update(snapshot)
                except Exception:
                    logging.exception('Usage cache read failed')
                next_cache = tick + CACHE_INTERVAL
            try:
                if self.native_until and tick>=self.native_until:
                    self.native_until=0
                    with self.lock: self.state['hardware_owner']='dashboard'
                    next_connect=0
                while True:
                    try:
                        command, params = self.commands.get_nowait()
                    except queue.Empty:
                        break
                    if command == 'refresh':
                        self.adapter.request_refresh(force=True)
                        next_cache = 0
                    elif command == 'control':
                        if params['owner']=='native':
                            self.release_to_native(tick)
                        else:
                            if params.get('faulted_registry_id') is not None:
                                self.blocked_identity=params['faulted_registry_id']
                                self.save_blocked_identity()
                                self.device_status(connected=False,message='Yerel sürücü USB hatası bildirdi; kabloyu yeniden bağlayın.')
                            self.native_until=0
                            with self.lock: self.state['hardware_owner']='dashboard'
                            next_connect=0
                    elif command == 'sync-time':
                        self.operation('Saat eşitleniyor…',pending=True)
                        self.sync()
                        self.operation('Klavye saati Mac ile eşitlendi.')
                        next_sync = tick + SYNC_INTERVAL
                        last_pixels = None
                    elif command == 'display':
                        self.display = params['enabled']
                        if not self.display and self.bridge:
                            self.bridge.send('stop')
                        self.save_settings()
                        self.operation('LED aktarım tercihi kaydedildi.')
                        last_pixels = None
                    elif command == 'settings':
                        self.settings.update(params['settings'])
                        self.save_settings()
                        self.operation('Ekran ayarları kaydedildi.')
                        last_pixels=None
                    elif command == 'lighting':
                        if not self.bridge:
                            raise ValueError('Aydınlatma için USB kontrolü panelde olmalı.')
                        self.operation('Aydınlatma uygulanıyor…',pending=True)
                        self.bridge.send('lighting',**params['lighting'])
                        self.settings['lighting']=params['lighting']
                        self.save_settings()
                        self.operation('Aydınlatma cihaz tarafından onaylandı.')
                        last_pixels=None
                if self.bridge is None and not self.native_until and tick >= next_connect:
                    next_connect=tick+RECONNECT_INTERVAL
                    self.connect()
                    next_sync=tick+SYNC_INTERVAL
                    last_pixels=None
                if self.bridge and tick >= next_sync:
                    self.sync()
                    next_sync = tick + SYNC_INTERVAL
                    last_pixels = None
                snapshot = self.snapshot()
                # Overview for 12 seconds, then each provider for four seconds.
                phase = int(tick - started) % 24
                mode=self.settings['display_mode']
                brightness=self.settings['brightness']
                green_gain=self.settings['claude_green_gain']
                tracked=self.settings.get('tracked_provider','all')
                # Advance one visual step per rendered/acknowledged iteration.
                # A slow USB frame must not jump over the falling-letter phases.
                animation_elapsed=animation_step/2
                activity=select_activity(snapshot.get('activity'),tick-started,provider=tracked) if self.settings.get('activity_enabled',True) else None
                mascot=bool(activity and self.settings.get('mascot_enabled',False))
                if activity:
                    pixels=(render_mascot if mascot else render_activity)(activity,snapshot,brightness,animation_elapsed,claude_green_gain=green_gain)
                    view='activity'
                    with self.lock: self.state['activity']['selected']=activity
                elif tracked!='all':
                    provider=next((row for row in snapshot['providers'] if row['id']==tracked),{'id':tracked})
                    pixels=render_detail(provider,brightness,claude_green_gain=green_gain)
                    view=tracked
                elif mode=='text':
                    pixels=render_text(self.settings['text'],self.settings['text_color'],brightness,animation_elapsed,
                                       marquee=self.settings.get('text_effect')=='scroll')
                    view='text'
                elif mode=='overview' or phase < 12:
                    pixels = render_overview(snapshot,brightness,claude_green_gain=green_gain)
                    view = 'overview'
                else:
                    provider = snapshot['providers'][(phase - 12) // 4]
                    pixels = render_detail(provider,brightness,claude_green_gain=green_gain)
                    view = provider['id']
                if not mascot and (not activity or activity['state'] in ('running','queued','completed')) and not (view=='text' and self.settings.get('text_effect')=='scroll'):
                    pixels=apply_text_effect(pixels,self.settings.get('text_effect','none'),brightness,animation_elapsed,
                                             left=7 if activity else 0)
                with self.lock:
                    self.state['matrix'] = {'pixels':pixels, 'view':view,'claude_green_gain':green_gain,
                                            'activity':{key:activity.get(key) for key in ('provider','state','summary')} if activity else None}
                if self.display and self.bridge and pixels != last_pixels:
                    result = self.bridge.send('frame', pixels=pixels)
                    self.device_status(connected=True, message='LED aktarımı etkin · USB onaylı',
                                       acknowledged_packets=result['acknowledged_packets'], last_frame=iso_now())
                    last_pixels = pixels
                animation_step += 1
            except (OSError, ValueError, KeyError) as exc:
                self.operation(str(exc),ok=False)
                if isinstance(exc,OSError): self.disconnect(exc)
                next_connect = tick + RECONNECT_INTERVAL
            self.quit.wait(0.5)
        if self.bridge:
            try:
                self.bridge.send('stop')
            except (OSError, ValueError):
                pass
            self.bridge.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def allowed(self):
        return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}

    def reply(self, code, content, content_type='application/json; charset=utf-8'):
        if not isinstance(content, bytes):
            content = json.dumps(content, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if not self.allowed():
            return self.reply(403, {'error':'Invalid host'})
        if self.path == '/':
            return self.reply(200, (BASE/'dashboard.html').read_bytes(), 'text/html; charset=utf-8')
        if self.path == '/api/status':
            return self.reply(200, self.server.application.snapshot())
        if self.path == '/api/accounts':
            return self.reply(200, self.server.application.account_snapshot())
        if self.path == '/favicon.ico':
            return self.reply(204, b'')
        self.reply(404, {'error':'Not found'})

    def do_POST(self):
        origin = self.headers.get('Origin')
        allowed_origins = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
        if not self.allowed() or origin not in allowed_origins:
            return self.reply(403, {'error':'Same-origin requests only','code':'forbidden'})
        if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
            return self.reply(415, {'error':'JSON required','code':'invalid_request'})
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 <= length <= 4096:
                return self.reply(413, {'error':'Request too large','code':'invalid_request'})
            payload = json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(payload, dict):
                raise ValueError('Invalid request')
            if self.path in ('/api/accounts/start','/api/accounts/submit','/api/accounts/cancel'):
                action=self.path.rsplit('/',1)[-1]
                expected={'provider','code'} if action=='submit' else {'provider'}
                if set(payload)!=expected or payload.get('provider') not in ('claude','codex','cursor'):
                    raise ValueError('Invalid account request')
                manager=self.server.application.accounts
                if action=='submit': manager.submit(payload['provider'],payload['code'])
                elif action=='start': manager.start(payload['provider'])
                else: manager.cancel(payload['provider'])
                return self.reply(202, {'ok':True})
            elif self.path == '/api/display':
                if type(payload.get('enabled')) is not bool:
                    raise ValueError('enabled must be boolean')
                self.server.application.request('display', enabled=payload['enabled'])
            elif self.path == '/api/settings':
                self.server.application.request('settings',settings=settings_patch(payload))
            elif self.path == '/api/lighting':
                self.server.application.request('lighting',lighting=lighting_request(payload))
            elif self.path == '/api/control':
                if set(payload)-{'owner','faulted_registry_id'} or payload.get('owner') not in ('native','dashboard'):
                    raise ValueError('Invalid hardware owner')
                fault=payload.get('faulted_registry_id')
                if fault is not None and (type(fault) is not int or not 0<fault<2**64 or payload['owner']!='dashboard'):
                    raise ValueError('Invalid failed USB attachment')
                self.server.application.request('control',owner=payload['owner'],faulted_registry_id=fault)
            elif self.path in ('/api/refresh','/api/sync-time'):
                self.server.application.request(self.path.rsplit('/',1)[-1])
            else:
                return self.reply(404, {'error':'Not found'})
            self.reply(202, {'ok':True, 'message':'İstek alındı; durum ekranda güncelleniyor.'})
        except (ValueError, UnicodeDecodeError) as error:
            self.reply(400, {'error':str(error),'code':'invalid_request'})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state-dir', type=Path, default=Path.home()/'Library/Application Support/AMG65 Studio/state')
    parser.add_argument('--port', type=int, default=PORT)
    parser.add_argument('--no-device', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    args.state_dir.mkdir(parents=True, exist_ok=True)
    lockfile = (args.state_dir/'instance.lock').open('a')
    try:
        fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('AMG65 Studio already running.')
    handler = RotatingFileHandler(args.state_dir/'bridge.log', maxBytes=512*1024, backupCount=2)
    logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(levelname)s %(message)s')
    app = Application(args.state_dir, args.no_device)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.daemon_threads = True
    server.application = app
    worker = threading.Thread(target=app.run, name='AMG65 USB')
    web = threading.Thread(target=server.serve_forever, daemon=True, name='AMG65 dashboard')
    for sig in (signal.SIGTERM,signal.SIGINT):
        signal.signal(sig, lambda *_: app.quit.set())
    worker.start(); web.start()
    logging.info('AMG65 Studio started on loopback port %s', args.port)
    try:
        while not app.quit.wait(0.5):
            if not worker.is_alive():
                raise RuntimeError('USB worker stopped')
    finally:
        app.quit.set()
        worker.join()
        app.adapter.close()
        app.accounts.close()
        server.shutdown(); server.server_close()
        lockfile.close()


if __name__ == '__main__':
    main()
