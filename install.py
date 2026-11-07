#!/usr/bin/env python3
"""Install this dependency-free companion for the current macOS user."""
import argparse
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import time
import socket
import urllib.request
import json
import tempfile

LABEL = 'io.github.kocakli.amg65studio'
APP_ID = LABEL + '.desktop'
SOURCE = Path(__file__).resolve().parent
DEST = Path.home()/'Library/Application Support/AMG65 Studio'
PLIST = Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist'
APP = Path.home()/'Applications/AMG65 Studio.app'
SERVICE = f'gui/{os.getuid()}/{LABEL}'


def install_native_app(source):
    APP.parent.mkdir(parents=True,exist_ok=True)
    if APP.exists():
        info=plistlib.loads((APP/'Contents/Info.plist').read_bytes())
        if info.get('CFBundleIdentifier')!=APP_ID:
            raise SystemExit('A different app already occupies the AMG65 Studio destination.')
    with tempfile.TemporaryDirectory(prefix='.amg65-install-',dir=APP.parent) as directory:
        stage=Path(directory)/APP.name
        previous=Path(directory)/'previous.app'
        shutil.copytree(source,stage)
        info=plistlib.loads((stage/'Contents/Info.plist').read_bytes())
        if info.get('CFBundleIdentifier')!=APP_ID:
            raise SystemExit('The built app has an unexpected bundle identifier.')
        subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(stage)],check=True)
        had_previous=APP.exists()
        if had_previous:
            APP.rename(previous)
        try:
            stage.rename(APP)
        except OSError:
            if had_previous:
                previous.rename(APP)
            raise


def install(dashboard_only=False):
    executable = Path(sys.executable).resolve()
    for file in ('app.py','renderer.py','usage_adapter.py','configuration.py','dashboard.html','bin/amg65-hid','THIRD_PARTY_LICENSE.txt'):
        if not (SOURCE/file).is_file():
            raise SystemExit(f'Missing required file: {file}')
    native_app=SOURCE/'NativeApp/build/AMG65 Studio.app'
    if not dashboard_only and not native_app.is_dir():
        raise SystemExit('Build the native app first: ./build.sh')
    if not dashboard_only:
        install_native_app(native_app)
    old_plist=Path.home()/'Library/LaunchAgents/local.amg65.limits.plist'
    if old_plist.exists():
        subprocess.run(['/bin/launchctl','bootout',f'gui/{os.getuid()}/local.amg65.limits'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        backup=Path.home()/'Library/Application Support/AMG65 Limits/previous-launchagent.plist'
        backup.parent.mkdir(parents=True,exist_ok=True)
        old_plist.replace(backup)
    subprocess.run(['/bin/launchctl','bootout',SERVICE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # bootout returns before launchd has fully removed the previous job.
    deadline = time.monotonic() + 12
    while subprocess.run(['/bin/launchctl','print',SERVICE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        if time.monotonic() >= deadline:
            raise SystemExit('The previous AMG65 service is still stopping; run installer again shortly.')
        time.sleep(0.2)
    deadline=time.monotonic()+15
    while True:
        try:
            with socket.socket() as check:
                check.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                check.bind(('127.0.0.1',47866))
            break
        except OSError:
            if time.monotonic()>=deadline:
                raise SystemExit('Port 47866 is still in use. Stop the other local AMG65 server and retry.')
            time.sleep(0.2)
    DEST.mkdir(parents=True, exist_ok=True, mode=0o700)
    state = DEST/'state'
    state.mkdir(exist_ok=True, mode=0o700)
    for file in ('app.py','renderer.py','usage_adapter.py','configuration.py','dashboard.html','bin/amg65-hid','THIRD_PARTY_LICENSE.txt'):
        target = DEST/file
        target.parent.mkdir(parents=True, exist_ok=True)
        if (SOURCE/file).resolve() != target.resolve():
            shutil.copy2(SOURCE/file,target)
    (DEST/'bin/amg65-hid').chmod(0o755)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    spec = {
        'Label':LABEL, 'ProgramArguments':[str(executable),str(DEST/'app.py')],
        'WorkingDirectory':str(DEST), 'RunAtLoad':True, 'KeepAlive':True,
        'ThrottleInterval':30, 'ExitTimeOut':15, 'ProcessType':'Background',
        'StandardOutPath':'/dev/null', 'StandardErrorPath':str(state/'launchd.log'),
        'EnvironmentVariables':{'PYTHONUNBUFFERED':'1','PYTHONDONTWRITEBYTECODE':'1'},
    }
    PLIST.write_bytes(plistlib.dumps(spec))
    PLIST.chmod(0o600)
    for attempt in range(6):
        started = subprocess.run(['/bin/launchctl','bootstrap',f'gui/{os.getuid()}',str(PLIST)],capture_output=True,text=True)
        if started.returncode == 0:
            break
        if attempt == 5:
            raise SystemExit('launchd could not start AMG65 Studio: ' + started.stderr.strip())
        time.sleep(0.5)
    deadline=time.monotonic()+12
    while True:
        try:
            with urllib.request.urlopen('http://127.0.0.1:47866/api/status',timeout=1) as response:
                status=json.load(response)
            if status.get('product',{}).get('id')=='amg65-studio':
                break
        except (OSError,ValueError):
            pass
        if time.monotonic()>=deadline:
            raise SystemExit('Service was registered but did not become ready; inspect state/launchd.log.')
        time.sleep(0.2)
    print('AMG65 Studio installed; login startup enabled.')
    print('Dashboard: http://127.0.0.1:47866/')
    if not dashboard_only:
        print(f'App: {APP}')


def remove_startup():
    subprocess.run(['/bin/launchctl','bootout',SERVICE],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if PLIST.exists():
        PLIST.unlink()
    print('AMG65 service stopped; login startup removed. Source, app and settings retained.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--remove-startup',action='store_true')
    parser.add_argument('--dashboard-only',action='store_true',help='Install only the background bridge and local panel')
    args = parser.parse_args()
    os.umask(0o077)
    remove_startup() if args.remove_startup else install(args.dashboard_only)
