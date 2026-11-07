import json
from pathlib import Path
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Handler


class FakeApplication:
    def __init__(self): self.requests=[]
    def snapshot(self): return {'providers':[], 'running':False}
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


if __name__ == '__main__': unittest.main()
