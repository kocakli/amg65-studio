#!/usr/bin/env python3
"""Prepare a private official Claude CLI for sign-in, without global installation.

Pins are from Anthropic's signed 2.1.311 manifest, verified against release key
31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE. The binary is not redistributed in Git.
Changing a pin requires rechecking the official signed manifest and capabilities.
"""
import hashlib
import os
from pathlib import Path
import platform
import stat
import subprocess
import tempfile
import time
import urllib.request

VERSION = '2.1.311'
ORIGIN = 'https://downloads.claude.ai/claude-code-releases'
TEAM_ID = 'Q6L2SF6YDW'
IDENTIFIER = 'com.anthropic.claude-code'
RELEASES = {
    'arm64': (276185504, '85d8c08707fcfd1e78ffa0204eefbc6ec9e4fe22f375fb2767ef85d957ed3161'),
    'x86_64': (287420928, 'd34e1cb82015b050471a97574aa6ea6f698ecf3a97a61c980961f43ad9f838f5'),
}
DESTINATION = Path(__file__).resolve().parents[1]/'bin/claude-auth'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, newurl):
        raise RuntimeError('Unexpected redirect from the official Claude release host')


def validate(path, architecture):
    """Verify bytes and vendor signature before executing any downloaded code."""
    metadata = path.lstat()
    size, checksum = RELEASES[architecture]
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o022:
        raise RuntimeError('Claude helper must be an owned, non-writable-by-others regular file')
    if metadata.st_size != size:
        raise RuntimeError('Claude helper size does not match the pinned release')
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024*1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != checksum:
        raise RuntimeError('Claude helper checksum does not match the pinned release')
    requirement = ('=anchor apple generic and certificate leaf[subject.OU] = "'+TEAM_ID+
                   '" and identifier "'+IDENTIFIER+'"')
    subprocess.run(['/usr/bin/codesign', '--verify', '--strict', '-R'+requirement, str(path)],
                   check=True, capture_output=True, timeout=20)
    environment = dict(os.environ)
    environment.update({'DISABLE_UPDATES':'1', 'DISABLE_AUTOUPDATER':'1', 'AMG65_STUDIO_AUTH_FLOW':'1'})
    version = subprocess.run([str(path), '--version'], check=True, capture_output=True,
                             text=True, timeout=15, env=environment)
    if version.stdout.strip() != VERSION+' (Claude Code)':
        raise RuntimeError('Unexpected Claude helper version')
    help_result = subprocess.run([str(path), 'auth', 'login', '--help'], check=True,
                                capture_output=True, text=True, timeout=15, env=environment)
    if 'Usage: claude auth login [options]' not in help_result.stdout or '--claudeai' not in help_result.stdout:
        raise RuntimeError('Claude helper does not support the required dedicated login command')


def prepare(destination=DESTINATION):
    architecture = platform.machine()
    if platform.system() != 'Darwin' or architecture not in RELEASES:
        raise RuntimeError('The private sign-in helper supports macOS arm64 and x86_64')
    destination = Path(destination).absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    parent_stat = destination.parent.lstat()
    if not stat.S_ISDIR(parent_stat.st_mode) or parent_stat.st_uid != os.getuid() or parent_stat.st_mode & 0o022:
        raise RuntimeError('Claude helper directory must be owned and not writable by others')
    if destination.is_symlink():
        raise RuntimeError('Refusing to replace a symlink at the private helper path')
    if destination.exists():
        validate(destination, architecture)
        print('Private Claude sign-in helper '+VERSION+' verified')
        return destination
    size, _ = RELEASES[architecture]
    release_platform = 'darwin-arm64' if architecture == 'arm64' else 'darwin-x64'
    url = ORIGIN+'/'+VERSION+'/'+release_platform+'/claude'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.claude-auth-', dir=destination.parent, delete=False) as target:
            temporary = Path(target.name)
            deadline = time.monotonic()+240
            received = 0
            opener = urllib.request.build_opener(NoRedirect())
            with opener.open(url, timeout=20) as response:
                if response.status != 200 or response.geturl() != url:
                    raise RuntimeError('Unexpected official release response')
                length = response.headers.get('Content-Length')
                if length is not None and int(length) != size:
                    raise RuntimeError('Official release size differs from the pinned release')
                while True:
                    if time.monotonic() > deadline:
                        raise RuntimeError('Claude helper download timed out')
                    # One socket read per iteration lets the elapsed deadline
                    # stop a server that keeps trickling bytes below its timeout.
                    chunk = response.read1(min(1024*1024, size-received+1))
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > size:
                        raise RuntimeError('Official release exceeded its pinned size')
                    target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        temporary.chmod(0o700)
        validate(temporary, architecture)
        os.replace(temporary, destination)
        print('Prepared private official Claude sign-in helper '+VERSION)
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    prepare()
