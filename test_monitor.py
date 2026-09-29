import json, tempfile, threading, unittest, urllib.error, urllib.request
from pathlib import Path
import server

class MonitorIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        server.PORT=cls.http.server_port;cls.base=f'http://127.0.0.1:{server.PORT}'
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):cls.http.shutdown();cls.http.server_close();cls.tmp.cleanup()
    def setUp(self):server.DB=Path(self.tmp.name)/(self._testMethodName+'.sqlite3');server.init()
    def request(self,path,data=None,headers=None):
        req=urllib.request.Request(self.base+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json',**(headers or {})})
        try:r=urllib.request.urlopen(req,timeout=8)
        except urllib.error.HTTPError as exc:r=exc
        with r:return r.status,json.loads(r.read())
    def fixture(self,scenario):
        status,m=self.request('/api/verification',{'scenario':scenario});self.assertEqual(status,201)
        status,run=self.request('/api/run/'+m['id'],{});self.assertEqual(status,200)
        return m['id'],self.request('/api/runs/'+str(run['run_ids'][0]))[1]
    def test_valid_response_passes_all_contract_checks(self):
        _,r=self.fixture('valid');self.assertEqual(r['passed'],1);self.assertEqual(len(r['checks']),7)
        self.assertEqual(r['response']['source'],'local-verification-fixture')
    def test_missing_required_field_fails(self):
        _,r=self.fixture('missing');self.assertEqual(r['passed'],0)
        failed=[c for c in r['checks'] if not c['passed']];self.assertEqual(failed[0]['rule'],'order.id');self.assertEqual(failed[0]['actual'],'missing')
    def test_json_type_change_is_identified(self):
        _,r=self.fixture('type');self.assertEqual(r['passed'],0)
        self.assertEqual([c['rule'] for c in r['checks'] if not c['passed']],['order.total_minor'])
    def test_non_success_status_is_evaluated(self):
        _,r=self.fixture('unavailable');self.assertEqual(r['status'],503);self.assertEqual(r['passed'],0)
    def test_latency_contract_records_real_delay(self):
        _,r=self.fixture('slow');self.assertGreaterEqual(r['duration_ms'],900);self.assertEqual(r['passed'],0)
    def test_invalid_json_has_explicit_parse_failure(self):
        _,r=self.fixture('invalid');self.assertEqual(r['passed'],0);self.assertIsNotNone(r['error']);self.assertIsNone(r['response'])
    def test_comparison_detects_changed_fields(self):
        mid,_=self.fixture('valid')
        # Alter only the endpoint behind the same test contract to exercise a real second request.
        with server.connect() as con:con.execute('UPDATE monitors SET url=? WHERE id=?',(self.base+'/fixtures/orders?scenario=type',mid))
        rid=self.request('/api/run/'+mid,{})[1]['run_ids'][0];r=self.request('/api/runs/'+str(rid))[1]
        self.assertEqual(r['changes'][0]['path'],'$.order.total_minor');self.assertEqual(r['changes'][0]['change'],'type changed')
    def test_bool_does_not_satisfy_integer_contract(self):
        self.assertFalse(server.matches(True,'integer'));self.assertFalse(server.matches(True,'number'));self.assertTrue(server.matches(3,'number'))
        self.assertEqual(server.lookup({'items':[{'id':'a'}]},'items.0.id'),(True,'a'))
    def test_origin_host_and_remote_endpoint_guards(self):
        self.assertEqual(self.request('/api/verification',{'scenario':'valid'},{'Origin':'https://untrusted.example'})[0],403)
        self.assertEqual(self.request('/api/state',headers={'Host':'untrusted.example'})[0],403)
        self.assertEqual(self.request('/api/monitors',{'name':'Remote','url':'https://example.com/api'})[0],400)
    def test_versions_preserve_previous_contract_and_runs(self):
        mid,r=self.fixture('valid');status,new=self.request('/api/update/'+mid,{'name':'Version two','url':self.base+'/fixtures/orders','rules':{'order.id':'string'}})
        self.assertEqual(status,201);self.assertNotEqual(mid,new['id']);self.assertEqual(self.request('/api/state')[1]['total_runs'],1)
        self.assertEqual(len(self.request('/api/state')[1]['monitors']),2)
    def test_runs_survive_database_reinitialization(self):
        self.fixture('valid');server.init();self.assertEqual(self.request('/api/state')[1]['total_runs'],1)

if __name__=='__main__':unittest.main(verbosity=2)
