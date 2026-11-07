"""User-initiated provider CLI login; no CodexBar or password collection.

The official provider CLI owns OAuth, browser callbacks and credential writes.
Only fixed sign-in commands run, in a private directory, with bounded PTY output.
Raw output and authorization-code input are never returned by snapshot or logged.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import errno
import fcntl
import os
from pathlib import Path
import pty
import re
import select
import signal
import struct
import subprocess
import termios
import threading
import time
from urllib.parse import parse_qs, urlsplit

PROVIDERS = ('claude', 'codex', 'cursor')
ACTIVE = {'starting', 'awaiting_browser', 'awaiting_code', 'awaiting_confirmation'}
LOGIN_SECONDS = 300
MAX_OUTPUT = 1024 * 1024
TAIL_BYTES = 32 * 1024
CLAUDE_CLIENT_ID = '9d1c250a-e61b-44d9-88ed-5944d1962f5e'
ERROR_CODES = frozenset(('cli_unavailable', 'login_failed', 'login_timeout',
                         'login_interaction_required', 'invalid_authorization_url',
                         'output_limit', 'code_rejected', 'launch_failed'))
ANSI = re.compile(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]')
URL_PATTERN = re.compile(r'https://[^\s\x00-\x1f<>"\']+')
AUTH_CODE = re.compile(r'[A-Za-z0-9_-]{16,1024}(?:#[A-Za-z0-9_-]{16,256})?\Z')


def auth_url_allowed(provider, value):
    """Accept a provider authorization screen, never arbitrary CLI-emitted URLs."""
    if not isinstance(value, str) or len(value) > 8192 or any(ord(c) < 32 for c in value):
        return False
    try:
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.fragment:
            return False
        query = parse_qs(parsed.query)
        if any(key in query for key in ('access_token', 'refresh_token', 'id_token', 'code_verifier')):
            return False
        if provider == 'claude':
            if parsed.hostname not in ('claude.ai', 'claude.com', 'platform.claude.com', 'console.anthropic.com'):
                return False
            if parsed.path == '/login':
                targets=query.get('returnTo', [])
                if len(targets)!=1:
                    return False
                target=targets[0]
                if not target.startswith('/oauth/authorize?'):
                    return False
                nested=urlsplit(target)
                if nested.fragment or nested.scheme or nested.netloc:
                    return False
                query = parse_qs(nested.query)
            elif parsed.path != '/oauth/authorize':
                return False
            if any(key in query for key in ('access_token', 'refresh_token', 'id_token', 'code_verifier')):
                return False
            return (query.get('client_id') == [CLAUDE_CLIENT_ID]
                    and query.get('response_type') == ['code']
                    and bool(query.get('state')) and bool(query.get('code_challenge'))
                    and query.get('code_challenge_method') == ['S256'])
        if provider == 'codex':
            return (parsed.hostname in ('auth.openai.com', 'chatgpt.com')
                    and parsed.path in ('/codex/device', '/device', '/activate', '/oauth/authorize'))
    except (ValueError, UnicodeError):
        return False
    return False


def inspect_output(provider, output):
    """Project transient output into a finite set of public login states."""
    plain = ANSI.sub('', output).replace('\r', '\n')
    lower = plain.lower()
    url = None
    for match in URL_PATTERN.finditer(output):
        candidate = match.group().rstrip('.,;)]}')
        if auth_url_allowed(provider, candidate):
            url = candidate
    code = None
    if provider == 'codex':
        match = re.search(r'\b([A-Z0-9]{4}-[A-Z0-9]{4})\b', plain)
        if match:
            code = match.group(1)
    interaction = None
    if any(marker in lower for marker in ('do you trust', 'trust the files in this folder')):
        interaction = 'workspace_trust'
    elif any(marker in lower for marker in ('choose the text style', 'choose your preferred text style')):
        interaction = 'appearance'
    return {
        'auth_url': url,
        'user_code': code,
        'input_required': provider == 'claude' and ('paste code' in lower or 'enter the code' in lower),
        'complete': any(marker in lower for marker in ('successfully logged in', 'login successful', 'logged in successfully')),
        'press_enter': bool(re.search(r'press\s+enter\s+to\s+open', lower)),
        'blocked_prompt': interaction is not None,
        'interaction': interaction,
        'confirmation_ready': bool(re.search(r'[❯>]\s*1[.)]\s*Yes,\s*(?:proceed|I trust this folder)(?:\s|$)', plain, re.I)),
        'code_rejected': any(marker in lower for marker in ('invalid authorization code', 'invalid oauth code', 'invalid_grant')),
    }


def locate_binary(provider, home=None):
    """Use fixed install locations; the HTTP caller cannot supply an executable."""
    home = Path(home) if home else Path.home()
    candidates = []
    if provider == 'claude':
        versions = home/'.local/share/claude/versions'
        if versions.is_dir():
            numeric = []
            for item in versions.iterdir():
                if re.fullmatch(r'\d+\.\d+\.\d+', item.name):
                    numeric.append((tuple(map(int, item.name.split('.'))), item))
            candidates.extend(item for _, item in sorted(numeric, reverse=True))
        candidates += [home/'.local/bin/claude', Path('/opt/homebrew/bin/claude'), Path('/usr/local/bin/claude')]
    elif provider == 'codex':
        suffix = 'ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'
        candidates = [Path('/Applications')/suffix, home/'Applications'/suffix,
                      Path('/Applications/Codex.app/Contents/Resources/codex'),
                      Path('/opt/homebrew/bin/codex'), Path('/usr/local/bin/codex')]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    return None


def login_arguments(provider, executable):
    if provider == 'claude':
        # /login works on the installed2.0.35 CLI, which predates `auth login`.
        # Inline settings select the subscription path. No project/user hooks or
        # MCP server configuration is loaded for this dedicated login process.
        # mcp-config is variadic; a following option must end it before /login.
        return [str(executable), '--mcp-config', '{"mcpServers":{}}',
                '--settings', '{"forceLoginMethod":"claudeai","disableAllHooks":true}',
                '--setting-sources', 'project', '--strict-mcp-config', '/login']
    if provider == 'codex':
        return [str(executable), 'login', '--device-auth']
    raise ValueError('Unsupported login provider')


@dataclass
class _Session:
    provider: str
    phase: str = 'idle'
    auth_url: str | None = None
    user_code: str | None = None
    input_required: bool = False
    error: str | None = None
    expires_at: str | None = None
    generation: int = 0
    cancel: threading.Event = field(default_factory=threading.Event)
    master: int | None = None
    thread: threading.Thread | None = None
    interaction: str | None = None
    input_revision: int = 0
    process: subprocess.Popen | None = None
    confirmation_ready: bool = False

    def public(self):
        return {key: getattr(self, key) for key in
                ('provider', 'phase', 'auth_url', 'user_code', 'input_required', 'error', 'expires_at', 'interaction')} | {
                    'method': 'provider_app' if self.provider == 'cursor' else 'provider_cli',
                    'actions': ['trust_login_workspace'] if self.phase=='awaiting_confirmation' and self.confirmation_ready else []}


class AccountManager:
    def __init__(self, state_dir=None):
        self.state_dir = Path(state_dir) if state_dir else Path.home()/'Library/Application Support/AMG65 Studio/state'
        self._lock = threading.RLock()
        self._sessions = {provider: _Session(provider) for provider in PROVIDERS}
        self._closed = False

    def snapshot(self):
        with self._lock:
            cursor=self._sessions['cursor']
            if cursor.phase in ACTIVE and cursor.expires_at and datetime.now(timezone.utc)>=datetime.fromisoformat(cursor.expires_at.replace('Z','+00:00')):
                cursor.phase='error'; cursor.error='login_timeout'
            return {'accounts': [self._sessions[provider].public() for provider in PROVIDERS]}

    @staticmethod
    def _provider(provider):
        if not isinstance(provider, str) or provider not in PROVIDERS:
            raise ValueError('Unknown provider')
        return provider

    def start(self, provider):
        provider = self._provider(provider)
        with self._lock:
            if self._closed:
                raise ValueError('Account manager is closed')
            previous = self._sessions[provider]
            if previous.phase in ACTIVE or (previous.thread is not None and previous.thread.is_alive()):
                raise ValueError('Sign-in is already in progress')
            session = _Session(provider, phase='starting', generation=previous.generation + 1)
            session.expires_at = datetime.fromtimestamp(time.time()+LOGIN_SECONDS, timezone.utc).isoformat().replace('+00:00', 'Z')
            self._sessions[provider] = session
            if provider == 'cursor':
                session.phase = 'awaiting_browser'
                # Native UI opens the verified Cursor app, whose local session is
                # the quota source. A website-only login would not renew that store.
                return session.public()
            session.thread = threading.Thread(target=self._run, args=(session,), name=f'studio-{provider}-login', daemon=True)
            session.thread.start()
            return session.public()

    def submit(self, provider, code):
        provider = self._provider(provider)
        if code=='trust_login_workspace':
            with self._lock:
                session=self._sessions[provider]
                if provider!='claude' or session.phase!='awaiting_confirmation' or session.interaction!='workspace_trust' or not session.confirmation_ready or session.master is None:
                    raise ValueError('No workspace confirmation is being requested')
                try:
                    os.write(session.master,b'\r')
                except OSError as error:
                    raise ValueError('The login process has closed') from error
                session.phase='starting'; session.interaction=None; session.confirmation_ready=False
                session.input_revision+=1
                return session.public()
        if not isinstance(code, str) or AUTH_CODE.fullmatch(code) is None:
            raise ValueError('Paste only the authorization code from the provider')
        with self._lock:
            session = self._sessions[provider]
            if provider != 'claude' or session.phase != 'awaiting_code' or not session.input_required or session.master is None:
                raise ValueError('No authorization code is being requested')
            try:
                os.write(session.master, code.encode('ascii') + b'\r')
            except OSError as error:
                raise ValueError('The login process has closed') from error
            session.input_required = False
            session.phase = 'awaiting_browser'
            session.error = None
            session.input_revision += 1
            return session.public()

    def cancel(self, provider):
        provider = self._provider(provider)
        with self._lock:
            session = self._sessions[provider]
            session.cancel.set()
            session.phase = 'cancelled'
            session.auth_url = session.user_code = session.error = None
            session.input_required = False
            return session.public()

    def close(self):
        with self._lock:
            self._closed = True
            sessions=list(self._sessions.values())
            for session in sessions:
                session.cancel.set()
                session.phase='cancelled'
                session.auth_url=session.user_code=None
                session.input_required=False
        # Joining outside the state lock lets workers finish their owned CLI and
        # close/reap its process group. No parent/provider editor is signalled.
        deadline=time.monotonic()+5
        for session in sessions:
            if session.thread is not None and session.thread is not threading.current_thread():
                session.thread.join(timeout=max(0,deadline-time.monotonic()))
        for session in sessions:
            process=session.process
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid,signal.SIGKILL)
                    process.wait(timeout=0.5)
                except (OSError,subprocess.TimeoutExpired):
                    pass

    def _set(self, session, _revision=None, **values):
        with self._lock:
            if self._sessions[session.provider] is not session or session.cancel.is_set():
                return
            if _revision is not None and session.input_revision != _revision:
                return
            for key, value in values.items():
                setattr(session, key, value)

    def _finish(self, session, phase, error=None):
        self._set(session, phase=phase, error=error, auth_url=None, user_code=None, input_required=False)

    @staticmethod
    def _terminate(process):
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
        except OSError:
            pass

    def _run(self, session):
        process = None
        master = slave = None
        try:
            executable = locate_binary(session.provider)
            if executable is None:
                self._finish(session, 'error', 'cli_unavailable')
                return
            directory = self.state_dir/'auth-work'
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if directory.is_symlink() or directory.stat().st_uid != os.getuid():
                raise OSError('Invalid login working directory')
            directory.chmod(0o700)
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 50, 2000, 0, 0))
            environment = dict(os.environ)
            environment.update({'TERM': 'xterm-256color', 'NO_COLOR': '1', 'BROWSER': '/usr/bin/true',
                                'AMG65_STUDIO_AUTH_FLOW':'1'})
            # Login uses official default provider stores. Inference credentials and
            # wrappers must not override the user's requested subscription login.
            for key in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_OAUTH_TOKEN',
                        'OPENAI_API_KEY', 'CODEX_ACCESS_TOKEN', 'CLAUDECODE'):
                environment.pop(key, None)
            if session.cancel.is_set():
                return
            process = subprocess.Popen(login_arguments(session.provider, executable), stdin=slave, stdout=slave,
                                       stderr=slave, cwd=directory, env=environment, start_new_session=True,
                                       close_fds=True)
            # Retain the exact child handle for bounded shutdown/reaping, even if
            # cancellation arrived while Popen was creating it.
            with self._lock:
                session.process=process
            os.close(slave); slave = None
            self._set(session, master=master)
            started = time.monotonic()
            total = 0
            tail = ''
            enter_sent = False
            saw_url = False
            revision = session.input_revision
            while not session.cancel.is_set():
                with self._lock:
                    if revision != session.input_revision:
                        revision=session.input_revision
                        tail=''
                if time.monotonic()-started >= LOGIN_SECONDS:
                    self._finish(session, 'error', 'login_timeout')
                    return
                ready, _, _ = select.select([master], [], [], 0.2)
                if ready:
                    try:
                        chunk = os.read(master, 8192)
                    except OSError as error:
                        if error.errno == errno.EIO:
                            chunk = b''
                        else:
                            raise
                    if chunk:
                        total += len(chunk)
                        if total > MAX_OUTPUT:
                            self._finish(session, 'error', 'output_limit')
                            return
                        tail = (tail + chunk.decode('utf-8', errors='replace'))[-TAIL_BYTES:]
                        event = inspect_output(session.provider, tail)
                        if event['complete']:
                            # Let the official CLI finish its own credential write.
                            session.cancel.wait(0.35)
                            self._terminate(process)
                            self._finish(session, 'complete')
                            return
                        if event['blocked_prompt'] and not saw_url:
                            if event['interaction']!='workspace_trust':
                                self._set(session,interaction=event['interaction'])
                                self._finish(session,'error','login_interaction_required')
                                return
                            self._set(session, _revision=revision, interaction=event['interaction'],
                                      phase='awaiting_confirmation',confirmation_ready=event['confirmation_ready'])
                        if event['auth_url']:
                            saw_url = True
                            self._set(session, auth_url=event['auth_url'], phase='awaiting_browser')
                        if event['user_code']:
                            self._set(session, user_code=event['user_code'])
                        if event['input_required'] and saw_url:
                            self._set(session, _revision=revision, input_required=True, phase='awaiting_code')
                        if event['code_rejected']:
                            self._finish(session, 'error', 'code_rejected')
                            return
                        if event['press_enter'] and not enter_sent:
                            os.write(master, b'\r')
                            enter_sent = True
                if process.poll() is not None:
                    self._finish(session, 'complete' if process.returncode == 0 and saw_url else 'error',
                                 None if process.returncode == 0 and saw_url else 'login_failed')
                    return
        except (OSError, ValueError, subprocess.SubprocessError):
            self._finish(session, 'error', 'launch_failed')
        finally:
            self._terminate(process)
            self._set(session, master=None)
            for descriptor in (master, slave):
                if descriptor is not None:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
