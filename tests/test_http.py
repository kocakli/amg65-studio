import json
from pathlib import Path
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Handler, Application
from unittest.mock import Mock


class FakeAccounts:
    def __init__(self): self.calls=[]
    def start(self,provider): self.calls.append(('start',provider))
    def submit(self,provider,code): self.calls.append(('submit',provider,code))
    def cancel(self,provider): self.calls.append(('cancel',provider))


class FakeApplication:
    def __init__(self): self.requests=[]; self.accounts=FakeAccounts()
    def snapshot(self): return {'providers':[], 'running':False}
    def account_snapshot(self): return {'accounts':[{'provider':'claude','phase':'idle'}]}
    def request(self, command, **params): self.requests.append((command,params))


class LocalHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.server.application=FakeApplication()
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.url=f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def request(self,path,method='GET',headers=None,payload=None):
        data=None if payload is None else json.dumps(payload).encode()
        request=urllib.request.Request(self.url+path,method=method,headers=headers or {},data=data)
        try:
            response=urllib.request.urlopen(request,timeout=2)
        except urllib.error.HTTPError as error:
            response=error
        with response: return response.status,json.load(response)

    def test_account_actions_require_exact_provider_fields_and_origin(self):
        headers={'Origin':self.url,'Content-Type':'application/json'}
        for payload in ({'provider':'evil'}, {'provider':'claude','command':'unsafe'}, {'provider':True}):
            status,_=self.request('/api/accounts/start','POST',headers,payload)
            self.assertEqual(status,400)
        status,_=self.request('/api/accounts/start','POST',headers,{'provider':'claude'})
        self.assertEqual(status,202)
        self.assertEqual(self.server.application.accounts.calls[-1],('start','claude'))
        status,_=self.request('/api/accounts/start','POST',{'Origin':'https://evil.example','Content-Type':'application/json'},{'provider':'claude'})
        self.assertEqual(status,403)

    def test_account_status_is_available_without_exposing_credentials(self):
        status,data=self.request('/api/accounts')
        self.assertEqual(status,200)
        self.assertEqual(data['accounts'][0]['phase'],'idle')

    def test_foreign_host_rejected(self):
        status,_=self.request('/api/status',headers={'Host':'evil.example'})
        self.assertEqual(status,403)

    def test_cross_origin_write_rejected(self):
        status,_=self.request('/api/display','POST',{'Origin':'https://evil.example','Content-Type':'application/json'},{'enabled':True})
        self.assertEqual(status,403)

    def test_same_origin_write_is_queued_without_claiming_completion(self):
        status,data=self.request('/api/display','POST',{'Origin':self.url,'Content-Type':'application/json'},{'enabled':True})
        self.assertEqual(status,202)
        self.assertTrue(data['ok'])
        self.assertEqual(self.server.application.requests[-1],('display',{'enabled':True}))

    def test_enabled_requires_boolean(self):
        status,_=self.request('/api/display','POST',{'Origin':self.url,'Content-Type':'application/json'},{'enabled':'false'})
        self.assertEqual(status,400)

    def test_native_failure_handoff_preserves_registry_identifier(self):
        identity=2**63+123
        status,_=self.request('/api/control','POST',{'Origin':self.url,'Content-Type':'application/json'},
                              {'owner':'dashboard','faulted_registry_id':identity})
        self.assertEqual(status,202)
        self.assertEqual(self.server.application.requests[-1],
                         ('control',{'owner':'dashboard','faulted_registry_id':identity}))

    def test_failed_attachment_requires_valid_identifier_and_dashboard_owner(self):
        headers={'Origin':self.url,'Content-Type':'application/json'}
        for identity in (True,0,-1,2**64,1.5,'123'):
            with self.subTest(identity=identity):
                status,_=self.request('/api/control','POST',headers,
                                      {'owner':'dashboard','faulted_registry_id':identity})
                self.assertEqual(status,400)
        status,_=self.request('/api/control','POST',headers,{'owner':'native','faulted_registry_id':123})
        self.assertEqual(status,400)


class AccountSnapshotTests(unittest.TestCase):
    def test_login_completion_refreshes_once_and_omits_private_usage_fields(self):
        application=Application.__new__(Application)
        application.lock=threading.RLock()
        application._completed_logins={}
        application.accounts=Mock()
        application.accounts.snapshot.side_effect=lambda:{'accounts':[{'provider':'claude','phase':'complete','expires_at':'2026-11-07T10:00:00Z'}]}
        application.adapter=Mock()
        application.state={'providers':[{'id':'claude','remaining_percent':42,'remaining_label':'7d','stale':False,
                                       'error':None,'updated_at':'2026-11-07T09:59:00Z',
                                       'accountFingerprint':'private','accountEmail':'private'}]}
        first=application.account_snapshot()
        application.account_snapshot()
        application.adapter.request_refresh.assert_called_once_with(force=True)
        usage=first['accounts'][0]['usage']
        self.assertEqual(usage['remaining_percent'],42)
        self.assertNotIn('accountFingerprint',usage)
        self.assertNotIn('accountEmail',usage)
        application.accounts.snapshot.side_effect=lambda:{'accounts':[{'provider':'claude','phase':'complete','expires_at':'2026-11-07T10:10:00Z'}]}
        application.account_snapshot()
        self.assertEqual(application.adapter.request_refresh.call_count,2)


if __name__ == '__main__': unittest.main()
