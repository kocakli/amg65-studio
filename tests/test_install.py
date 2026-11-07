"""Installer lifecycle regressions; process inspection and signals are mocked."""
import importlib.util
from pathlib import Path
import plistlib
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch


SPEC = importlib.util.spec_from_file_location('studio_installer', Path(__file__).resolve().parents[1]/'install.py')
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class InstallLifecycleTests(unittest.TestCase):
    def setUp(self):
        # Accidental new process calls must fail rather than touch the host.
        self.run = self.enterContext(patch.object(installer.subprocess, 'run', side_effect=AssertionError('Unexpected process call')))
        self.kill = self.enterContext(patch.object(installer.os, 'kill', side_effect=AssertionError('Unexpected signal')))
        self.sleep = self.enterContext(patch.object(installer.time, 'sleep'))

    def test_process_match_uses_exact_executable_with_spaces(self):
        app = Path('/Applications/AMG65 Studio.app')
        executable = str(app/'Contents/MacOS/AMG65Studio')
        self.run.side_effect = None
        self.run.return_value = subprocess.CompletedProcess([], 0, '\n'.join([
            f' 101 {executable}', f'102 {executable} --menu-bar',
            f'103 {executable}-other', f'104 /source/build{executable}',
            '105 AMG65Studio', f'0 {executable}', f'bad {executable}',
            f'  106    {executable}',
        ]))
        with patch.object(installer, 'APP', app):
            self.assertEqual(installer.installed_app_pids(), {101, 106})
        self.run.assert_called_once_with(['/bin/ps', '-axww', '-o', 'pid=,comm='],
                                         capture_output=True, text=True, check=True, timeout=5)
        self.kill.assert_not_called()

    def test_failed_process_inventory_fails_closed(self):
        for failure in (OSError('unavailable'), subprocess.CalledProcessError(1, 'ps'),
                        subprocess.TimeoutExpired('ps', 5)):
            with self.subTest(failure=type(failure).__name__):
                self.run.side_effect = failure
                with self.assertRaisesRegex(SystemExit, 'Could not inspect'):
                    installer.installed_app_pids()
        self.kill.assert_not_called()

    def test_manual_app_is_signalled_once_and_exit_is_observed(self):
        events = []
        snapshots = iter([{41}, {41}, {41}, set()])
        def inspect():
            events.append('inspect')
            return next(snapshots)
        self.kill.side_effect = lambda pid, sig: events.append(('signal', pid, sig))
        with patch.object(installer, 'installed_app_pids', side_effect=inspect), \
             patch.object(installer, 'stop_job', side_effect=lambda service: events.append(('bootout', service))):
            installer.stop_installed_app()
        self.assertEqual(events[:2], ['inspect', ('bootout', installer.MENU_SERVICE)])
        self.assertEqual(events[2:4], ['inspect', ('signal', 41, signal.SIGTERM)])
        self.kill.assert_called_once_with(41, signal.SIGTERM)
        self.assertEqual(events[-1], 'inspect')

    def test_exited_or_reused_pid_is_not_signalled(self):
        with patch.object(installer, 'installed_app_pids', side_effect=[{41}, set(), set()]), \
             patch.object(installer, 'stop_job'):
            installer.stop_installed_app()
        self.kill.assert_not_called()

    def test_app_opened_during_bootout_is_also_stopped(self):
        self.kill.side_effect = None
        with patch.object(installer, 'installed_app_pids', side_effect=[set(), {99}, {99}, set()]), \
             patch.object(installer, 'stop_job'):
            installer.stop_installed_app()
        self.kill.assert_called_once_with(99, signal.SIGTERM)

    def test_exit_between_recheck_and_signal_is_harmless(self):
        self.kill.side_effect = ProcessLookupError()
        with patch.object(installer, 'installed_app_pids', side_effect=[{41}, {41}, set()]), \
             patch.object(installer, 'stop_job'):
            installer.stop_installed_app()
        self.kill.assert_called_once_with(41, signal.SIGTERM)

    def test_signal_permission_error_aborts(self):
        self.kill.side_effect = PermissionError()
        with patch.object(installer, 'installed_app_pids', return_value={41}), \
             patch.object(installer, 'stop_job'):
            with self.assertRaisesRegex(SystemExit, 'closed gracefully'):
                installer.stop_installed_app()

    def test_busy_app_aborts_install_before_bundle_replacement(self):
        self.kill.side_effect = None
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            for name in ('app.py', 'renderer.py', 'usage_adapter.py', 'configuration.py',
                         'dashboard.html', 'bin/amg65-hid', 'bin/amg65-usage', 'activity.py', 'activity_hooks.py', 'account_auth.py', 'UsageEngine/NOTICE.md', 'THIRD_PARTY_LICENSE.txt'):
                path = source/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            (source/'NativeApp/build/AMG65 Studio.app').mkdir(parents=True)
            with patch.object(installer, 'SOURCE', source), \
                 patch.object(installer, 'installed_app_pids', return_value={41}), \
                 patch.object(installer, 'stop_job') as stop, \
                 patch.object(installer, 'install_native_app') as replace, \
                 patch.object(installer.time, 'monotonic', side_effect=[0, 15]):
                with self.assertRaisesRegex(SystemExit, 'installed app was kept'):
                    installer.install()
            replace.assert_not_called()
            stop.assert_called_once_with(installer.MENU_SERVICE)
        self.kill.assert_called_once_with(41, signal.SIGTERM)

    def test_relaunch_during_staging_keeps_old_bundle(self):
        self.run.side_effect = None
        self.run.return_value = subprocess.CompletedProcess([], 0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root/'source.app', root/'AMG65 Studio.app'
            for app, marker in ((source, 'new'), (target, 'old')):
                (app/'Contents').mkdir(parents=True)
                (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': installer.APP_ID}))
                (app/'marker').write_text(marker)
            with patch.object(installer, 'APP', target), \
                 patch.object(installer, 'installed_app_pids', return_value={41}):
                with self.assertRaisesRegex(SystemExit, 'reopened during installation'):
                    installer.install_native_app(source)
            self.assertEqual((target/'marker').read_text(), 'old')
            self.assertEqual((source/'marker').read_text(), 'new')
            self.assertEqual(sorted(path.name for path in root.iterdir()), ['AMG65 Studio.app', 'source.app'])
        self.assertEqual(self.run.call_args.args[0][:4], ['/usr/bin/codesign', '--verify', '--deep', '--strict'])
        self.kill.assert_not_called()

    def test_remove_startup_waits_for_manual_app_before_removing_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            menu, backend = Path(directory)/'menu.plist', Path(directory)/'backend.plist'
            for path in (menu, backend): path.write_text('retained')
            with patch.object(installer, 'MENU_PLIST', menu), patch.object(installer, 'PLIST', backend), \
                 patch.object(installer, 'stop_installed_app', side_effect=SystemExit('still busy')), \
                 patch.object(installer, 'stop_job') as stop:
                with self.assertRaisesRegex(SystemExit, 'still busy'):
                    installer.remove_startup()
            stop.assert_not_called()
            self.assertTrue(menu.is_file() and backend.is_file())

    def test_remove_startup_stops_native_then_backend(self):
        events = []
        with tempfile.TemporaryDirectory() as directory:
            menu, backend = Path(directory)/'menu.plist', Path(directory)/'backend.plist'
            for path in (menu, backend): path.touch()
            with patch.object(installer, 'MENU_PLIST', menu), patch.object(installer, 'PLIST', backend), \
                 patch.object(installer, 'stop_installed_app', side_effect=lambda: events.append('native')), \
                 patch.object(installer, 'stop_job', side_effect=lambda service: events.append(service)), \
                 patch('builtins.print'):
                installer.remove_startup()
            self.assertFalse(menu.exists() or backend.exists())
        self.assertEqual(events, ['native', installer.SERVICE])

    def test_unresponsive_launchctl_aborts_without_signalling(self):
        self.run.side_effect = subprocess.TimeoutExpired('launchctl', 5)
        with self.assertRaisesRegex(SystemExit, 'Could not confirm'):
            installer.stop_job(installer.MENU_SERVICE)
        self.assertEqual(self.run.call_args.kwargs['timeout'], 5)
        self.kill.assert_not_called()


if __name__ == '__main__':
    unittest.main()
