#!/usr/bin/env python3
"""Install this dependency-free companion for the current macOS user."""
import argparse
import os
from pathlib import Path
import plistlib
import shutil
import signal
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
MENU_PLIST = PLIST.with_name(f'{APP_ID}.plist')
APP = Path.home()/'Applications/AMG65 Studio.app'
SERVICE = f'gui/{os.getuid()}/{LABEL}'
MENU_SERVICE = f'gui/{os.getuid()}/{APP_ID}'
STOP_WAIT_SECONDS = 15
PROCESS_QUERY_TIMEOUT = 5


def stop_job(service):
    try:
        subprocess.run(['/bin/launchctl','bootout',service],stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL,timeout=PROCESS_QUERY_TIMEOUT)
        deadline=time.monotonic()+STOP_WAIT_SECONDS
        while subprocess.run(['/bin/launchctl','print',service],stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,timeout=PROCESS_QUERY_TIMEOUT).returncode==0:
            if time.monotonic()>=deadline:
                raise SystemExit('The previous Studio process is finishing an operation. Retry after it closes.')
            time.sleep(0.2)
    except (OSError,subprocess.TimeoutExpired) as error:
        raise SystemExit('Could not confirm that launchd stopped Studio. Retry after it closes.') from error


def installed_app_pids():
    """Match the installed executable, not a name, argument or source-build copy."""
    executable=str(APP/'Contents/MacOS/AMG65Studio')
    try:
        result=subprocess.run(['/bin/ps','-axww','-o','pid=,comm='],capture_output=True,
                              text=True,check=True,timeout=PROCESS_QUERY_TIMEOUT)
    except (OSError,subprocess.SubprocessError) as error:
        raise SystemExit('Could not inspect running Studio processes; installation was not continued.') from error
    matches=set()
    for row in result.stdout.splitlines():
        fields=row.strip().split(None,1)
        if len(fields)==2 and fields[0].isdigit() and fields[1]==executable:
            pid=int(fields[0])
            if pid>0:
                matches.add(pid)
    return matches


def stop_installed_app():
    """Gracefully stop both login-started and manually opened installed copies.

    A removed launchd definition does not prove its process has exited. Re-query
    exact executable paths before signalling and while waiting; never escalate to
    SIGKILL. A busy native upload may finish after this installer asks for a retry.
    """
    pending=installed_app_pids()
    stop_job(MENU_SERVICE)
    deadline=time.monotonic()+STOP_WAIT_SECONDS
    signalled=set()
    while True:
        for pid in sorted(pending-signalled):
            # The old PID could have exited or been reused since the last query.
            if pid not in installed_app_pids():
                continue
            try:
                os.kill(pid,signal.SIGTERM)
            except ProcessLookupError:
                pass
            except OSError as error:
                raise SystemExit('Studio could not be closed gracefully. Close it and retry.') from error
            signalled.add(pid)
        pending=installed_app_pids()
        if not pending:
            return
        if time.monotonic()>=deadline:
            raise SystemExit('Studio is still finishing an operation. The installed app was kept; retry after it closes.')
        time.sleep(0.2)


def start_job(plist):
    for attempt in range(6):
        result=subprocess.run(['/bin/launchctl','bootstrap',f'gui/{os.getuid()}',str(plist)],capture_output=True,text=True)
        if result.returncode==0:
            return
        if attempt==5:
            raise SystemExit('launchd could not start AMG65 Studio: '+result.stderr.strip())
        time.sleep(0.5)


def menu_agent_spec():
    return {
        'Label':APP_ID,
        'ProgramArguments':[str(APP/'Contents/MacOS/AMG65Studio'),'--menu-bar'],
        'RunAtLoad':True,
        # Quit stays quit until the user next opens Studio or logs in again.
        'KeepAlive':False,
        # Give an in-flight media upload time to finish before releasing USB.
        'ExitTimeOut':180,
        'ProcessType':'Interactive',
        'LimitLoadToSessionType':'Aqua',
        'StandardOutPath':'/dev/null','StandardErrorPath':'/dev/null',
    }


def backend_agent_spec(executable, state):
    return {
        'Label':LABEL, 'ProgramArguments':[str(executable),str(DEST/'app.py')],
        'WorkingDirectory':str(DEST), 'RunAtLoad':True, 'KeepAlive':True,
        # The user-visible LED depends on timely serial HID acknowledgements.
        # Background policy coalesces each 5/10ms wait to ~100ms. Adaptive
        # promotes XPC activity, but our native/bridge IPC is HTTP and stdin.
        # Keep the helper's ACK deadlines, spacing and frame limit unchanged.
        'ThrottleInterval':30, 'ExitTimeOut':15, 'ProcessType':'Interactive',
        'StandardOutPath':'/dev/null', 'StandardErrorPath':str(state/'launchd.log'),
        'EnvironmentVariables':{'PYTHONUNBUFFERED':'1','PYTHONDONTWRITEBYTECODE':'1'},
    }


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
        # A user can reopen the app while staging or signature verification runs.
        if installed_app_pids():
            raise SystemExit('Studio reopened during installation. The installed app was kept; close it and retry.')
        had_previous=APP.exists()
        if had_previous:
            APP.rename(previous)
        try:
            stage.rename(APP)
        except OSError:
            if had_previous:
                previous.rename(APP)
            raise


def replace_file(source,target):
    """Swap in a new inode: rewriting a signed Mach-O in place gets its next launch killed."""
    staging=target.with_name(f'.{target.name}.installing')
    try:
        shutil.copy2(source,staging)
        os.replace(staging,target)
    finally:
        staging.unlink(missing_ok=True)


def install(dashboard_only=False):
    executable = Path(sys.executable).resolve()
    files = ('app.py','renderer.py','usage_adapter.py','configuration.py','dashboard.html','bin/amg65-hid','bin/amg65-usage','activity.py','activity_hooks.py','account_auth.py','UsageEngine/NOTICE.md','THIRD_PARTY_LICENSE.txt') + (() if dashboard_only else ('bin/claude-auth',))
    for file in files:
        if not (SOURCE/file).is_file():
            raise SystemExit(f'Missing required file: {file}')
    native_app=SOURCE/'NativeApp/build/AMG65 Studio.app'
    if not dashboard_only and not native_app.is_dir():
        raise SystemExit('Build the native app first: ./build.sh')
    if not dashboard_only:
        stop_installed_app()
    old_plist=Path.home()/'Library/LaunchAgents/local.amg65.limits.plist'
    if old_plist.exists():
        subprocess.run(['/bin/launchctl','bootout',f'gui/{os.getuid()}/local.amg65.limits'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        backup=Path.home()/'Library/Application Support/AMG65 Limits/previous-launchagent.plist'
        backup.parent.mkdir(parents=True,exist_ok=True)
        old_plist.replace(backup)
    stop_job(SERVICE)
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
    for file in files:
        target = DEST/file
        target.parent.mkdir(parents=True, exist_ok=True)
        if (SOURCE/file).resolve() != target.resolve():
            replace_file(SOURCE/file,target)
    (DEST/'bin/amg65-hid').chmod(0o755)
    (DEST/'bin/amg65-usage').chmod(0o755)
    if not dashboard_only:
        (DEST/'bin/claude-auth').chmod(0o755)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    spec = backend_agent_spec(executable, state)
    PLIST.write_bytes(plistlib.dumps(spec))
    PLIST.chmod(0o600)
    start_job(PLIST)
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
    if not dashboard_only:
        # Swap the app only after its backend is proven ready; a failed upgrade keeps the old app.
        install_native_app(native_app)
        MENU_PLIST.write_bytes(plistlib.dumps(menu_agent_spec()))
        MENU_PLIST.chmod(0o600)
        start_job(MENU_PLIST)
    print('AMG65 Studio installed; login startup enabled.')
    print('Dashboard: http://127.0.0.1:47866/')
    if not dashboard_only:
        print(f'App: {APP}')
        print('Menu bar app started; login startup enabled.')


def remove_startup():
    stop_installed_app()
    stop_job(SERVICE)
    for plist in (MENU_PLIST,PLIST):
        if plist.exists():
            plist.unlink()
    print('Studio menu bar app and service stopped; login startup removed. Source, app and settings retained.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--remove-startup',action='store_true')
    parser.add_argument('--dashboard-only',action='store_true',help='Install only the background bridge and local panel')
    args = parser.parse_args()
    os.umask(0o077)
    remove_startup() if args.remove_startup else install(args.dashboard_only)
