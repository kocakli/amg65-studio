"""Offline login-boundary tests: no real provider process, browser or credentials."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.parse import quote

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import account_auth as auth

CLAUDE_URL = ('https://claude.ai/oauth/authorize?client_id='+auth.CLAUDE_CLIENT_ID+
              '&response_type=code&code_challenge=syntheticchallenge&code_challenge_method=S256&state=syntheticstate')


class AuthURLTests(unittest.TestCase):
    def test_accepts_official_pkce_authorize_and_device_routes(self):
        self.assertTrue(auth.auth_url_allowed('claude',CLAUDE_URL))
        nested='/oauth/authorize?'+CLAUDE_URL.split('?',1)[1]
        self.assertTrue(auth.auth_url_allowed('claude','https://platform.claude.com/login?returnTo='+quote(nested,safe='')))
        self.assertTrue(auth.auth_url_allowed('codex','https://auth.openai.com/codex/device'))

    def test_rejects_credential_urls_redirect_confusion_and_forged_hosts(self):
        for value in (CLAUDE_URL.replace('https:','http:'), CLAUDE_URL.replace('claude.ai','claude.ai.evil.test'),
                      CLAUDE_URL.replace('claude.ai','claude.ai@evil.test'),CLAUDE_URL+'&access_token=secret',
                      CLAUDE_URL+'&code_verifier=secret',CLAUDE_URL+'#access_token=secret',
                      CLAUDE_URL.replace(auth.CLAUDE_CLIENT_ID,'different-client')):
            with self.subTest(value=value): self.assertFalse(auth.auth_url_allowed('claude',value))

    def test_nested_login_rejects_duplicate_targets_fragments_and_credentials(self):
        target='/oauth/authorize?'+CLAUDE_URL.split('?',1)[1]
        for suffix in ('&refresh_token=secret','#access_token=secret','&code_verifier=secret'):
            self.assertFalse(auth.auth_url_allowed('claude','https://platform.claude.com/login?returnTo='+quote(target+suffix,safe='')))
        value='https://platform.claude.com/login?returnTo='+quote(target,safe='')
        self.assertFalse(auth.auth_url_allowed('claude',value+'&returnTo='+quote(target,safe='')))
        self.assertFalse(auth.auth_url_allowed('claude','https://platform.claude.com/login?returnTo=https://evil.test'))

    def test_output_projection_never_returns_raw_output_or_tokens(self):
        output='private@example.invalid secret-token\n'+CLAUDE_URL+'\nPaste code here\n'
        event=auth.inspect_output('claude',output)
        self.assertEqual(event['auth_url'],CLAUDE_URL)
        self.assertTrue(event['input_required'])
        encoded=json.dumps(event)
        self.assertNotIn('private@example',encoded)
        self.assertNotIn('secret-token',encoded)
        self.assertNotIn('output',event)

    def test_actual_trust_prompt_requires_selected_yes(self):
        prompt='Do you trust the files in this folder?\n❯ 1. Yes, proceed\n  2. No, exit\n'
        event=auth.inspect_output('claude',prompt)
        self.assertEqual(event['interaction'],'workspace_trust')
        self.assertTrue(event['confirmation_ready'])
        changed=prompt.replace('❯ 1.','  1.').replace('  2.','❯ 2.')
        self.assertFalse(auth.inspect_output('claude',changed)['confirmation_ready'])

    def test_codex_device_code_and_terminal_success(self):
        event=auth.inspect_output('codex','Open https://auth.openai.com/codex/device\nEnter code ABCD-EFGH\n')
        self.assertEqual(event['user_code'],'ABCD-EFGH')
        self.assertFalse(event['input_required'])
        self.assertTrue(auth.inspect_output('claude','Successfully logged in')['complete'])
        self.assertTrue(auth.inspect_output('claude','invalid_grant')['code_rejected'])


class AccountLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=self.enterContext(tempfile.TemporaryDirectory())
        self.manager=auth.AccountManager(Path(self.temp))
        self.write=self.enterContext(patch.object(auth.os,'write',side_effect=AssertionError('Unexpected PTY input')))
        self.spawn=self.enterContext(patch.object(auth.subprocess,'Popen',side_effect=AssertionError('Unexpected provider process')))
        self.kill=self.enterContext(patch.object(auth.os,'killpg',side_effect=AssertionError('Unexpected signal')))

    def test_start_uses_only_fixed_commands_and_disables_user_hooks(self):
        command=auth.login_arguments('claude',Path('/fixture/claude'))
        settings=json.loads(command[command.index('--settings')+1])
        self.assertTrue(settings['disableAllHooks'])
        self.assertEqual(command[command.index('--setting-sources')+1],'project')
        self.assertEqual(command[command.index('--mcp-config')+2],'--settings')
        self.assertEqual(command[-1],'/login')
        self.assertEqual(auth.login_arguments('codex',Path('/fixture/codex')),['/fixture/codex','login','--device-auth'])

    def test_bad_provider_never_starts_process(self):
        for value in ('claude;echo bad','all',None,{},1):
            with self.assertRaises(ValueError): self.manager.start(value)
        self.spawn.assert_not_called()

    def test_restart_waits_for_old_worker_after_cancel(self):
        session=self.manager._sessions['claude']
        session.phase='awaiting_browser'; session.thread=Mock()
        session.thread.is_alive.return_value=True
        self.manager.cancel('claude')
        with self.assertRaises(ValueError): self.manager.start('claude')
        self.spawn.assert_not_called()

    def test_cursor_waiting_state_expires_without_worker(self):
        row=self.manager.start('cursor')
        self.assertEqual(row['method'],'provider_app')
        session=self.manager._sessions['cursor']
        session.expires_at=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        row=next(row for row in self.manager.snapshot()['accounts'] if row['provider']=='cursor')
        self.assertEqual((row['phase'],row['error']),('error','login_timeout'))
        self.spawn.assert_not_called()

    def test_confirmation_requires_exact_live_prompt_then_sends_only_enter(self):
        session=self.manager._sessions['claude']; session.master=42
        with self.assertRaises(ValueError): self.manager.submit('claude','trust_login_workspace')
        session.phase='awaiting_confirmation';session.interaction='workspace_trust'
        with self.assertRaises(ValueError): self.manager.submit('claude','trust_login_workspace')
        session.confirmation_ready=True; self.write.side_effect=None
        self.assertEqual(session.public()['actions'],['trust_login_workspace'])
        row=self.manager.submit('claude','trust_login_workspace')
        self.write.assert_called_once_with(42,b'\r')
        self.assertEqual(row['phase'],'starting')
        self.assertIsNone(row['interaction'])
        self.assertEqual(row['actions'],[])

    def test_only_bounded_authorization_code_can_enter_code_prompt(self):
        session=self.manager._sessions['claude'];session.master=42
        session.phase='awaiting_code';session.input_required=True
        for code in ('/login','\x1b[A','A'*16+'\n/exit','A'*2048,'password with spaces',''):
            with self.assertRaises(ValueError):self.manager.submit('claude',code)
        self.write.assert_not_called()
        self.write.side_effect=None
        row=self.manager.submit('claude','A'*32+'#'+'B'*32)
        self.assertFalse(row['input_required'])
        self.assertEqual(self.write.call_args.args[1],b'A'*32+b'#'+b'B'*32+b'\r')
        self.assertNotIn('A'*32,json.dumps(self.manager.snapshot()))

    def test_stale_prompt_revision_cannot_reenable_input(self):
        session=self.manager._sessions['claude'];session.input_revision=2
        self.manager._set(session,_revision=1,input_required=True,phase='awaiting_code')
        self.assertFalse(session.input_required)
        self.assertEqual(session.phase,'idle')

    def test_close_joins_outside_lock_and_clears_public_login_data(self):
        session=self.manager._sessions['claude'];session.auth_url=CLAUDE_URL;session.phase='awaiting_browser'
        worker=Mock();session.thread=worker
        def joined(timeout):
            # Another real thread can take the lock during close's join callback.
            acquired=[]
            task=threading.Thread(target=lambda:acquired.append(self.manager.snapshot()))
            task.start();task.join(timeout=1)
            self.assertTrue(acquired)
        worker.join.side_effect=joined
        self.manager.close()
        self.assertTrue(session.cancel.is_set())
        self.assertIsNone(session.auth_url)
        worker.join.assert_called_once()
        with self.assertRaises(ValueError):self.manager.start('cursor')

    def test_terminate_targets_only_child_process_group_and_reaps(self):
        process=Mock(pid=987);process.poll.return_value=None
        self.kill.side_effect=None
        self.manager._terminate(process)
        self.kill.assert_called_once_with(987,signal.SIGTERM)
        process.wait.assert_called_once_with(timeout=2)

    def test_terminate_escalates_only_unresponsive_owned_child(self):
        process=Mock(pid=987);process.poll.return_value=None
        process.wait.side_effect=[subprocess.TimeoutExpired('fixture',2),0]
        self.kill.side_effect=None
        self.manager._terminate(process)
        self.assertEqual([call.args for call in self.kill.call_args_list],[(987,signal.SIGTERM),(987,signal.SIGKILL)])
        self.assertEqual(process.wait.call_count,2)

    def run_fixture_output(self,output):
        process=Mock(pid=987);process.poll.return_value=None
        self.spawn.side_effect=None;self.spawn.return_value=process
        self.kill.side_effect=None
        session=self.manager._sessions['claude']
        with patch.object(auth,'locate_binary',return_value=Path('/fixture/claude')), \
             patch.object(auth.pty,'openpty',return_value=(101,102)), \
             patch.object(auth.fcntl,'ioctl'),patch.object(auth.os,'close'), \
             patch.object(auth.os,'read',return_value=output.encode()), \
             patch.object(auth.select,'select',return_value=([101],[],[])):
            self.manager._run(session)
        return session.public()

    def test_unsupported_appearance_prompt_is_terminal_not_actionless_wait(self):
        row=self.run_fixture_output('Choose the text style that looks best with your terminal')
        self.assertEqual((row['phase'],row['error']),('error','login_interaction_required'))
        self.assertEqual(row['actions'],[])
        self.write.assert_not_called()

    def test_rejected_code_is_not_overwritten_by_generic_exit_error(self):
        row=self.run_fixture_output('invalid_grant: invalid authorization code')
        self.assertEqual((row['phase'],row['error']),('error','code_rejected'))
        self.write.assert_not_called()


if __name__=='__main__':unittest.main()
