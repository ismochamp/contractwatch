#!/usr/bin/env python3
"""ContractWatch: real HTTP checks with JSON contracts and persisted comparisons."""
import argparse, csv, io, ipaddress, json, os, secrets, sqlite3, threading, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parent
DB=Path(os.environ.get('MONITOR_DB',str(ROOT/'monitor.sqlite3')))
PORT=int(os.environ.get('PORT','8104'))
MAX_BODY=262144
RUN_LOCK=threading.Lock()
def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def connect():
    con=sqlite3.connect(DB,timeout=15);con.row_factory=sqlite3.Row;return con
def init():
    with connect() as con:
        con.executescript('''PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS monitors(id TEXT PRIMARY KEY,name TEXT NOT NULL,url TEXT NOT NULL,expected_status INTEGER NOT NULL,max_latency_ms INTEGER NOT NULL,rules TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY,monitor_id TEXT NOT NULL,at TEXT NOT NULL,status INTEGER,duration_ms INTEGER NOT NULL,passed INTEGER NOT NULL,checks TEXT NOT NULL,changes TEXT NOT NULL,response TEXT,error TEXT);
        ''')
def target(value):
    u=urllib.parse.urlsplit(value)
    if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or u.fragment:raise ValueError('Use an HTTP(S) URL without credentials or a fragment')
    try:
        if u.port is not None and not 1<=u.port<=65535:raise ValueError()
    except ValueError:raise ValueError('Invalid endpoint port')
    if os.environ.get('ALLOW_REMOTE_ENDPOINTS')!='1':
        if u.hostname!='localhost':
            try:allowed=ipaddress.ip_address(u.hostname).is_loopback
            except ValueError:allowed=False
            if not allowed:raise ValueError('Remote checks are disabled. Set ALLOW_REMOTE_ENDPOINTS=1 to enable them.')
    return value
def validate_config(data):
    name=str(data.get('name','')).strip()
    if not 1<=len(name)<=80:raise ValueError('Name must contain 1–80 characters')
    url=target(str(data.get('url','')).strip())
    status=int(data.get('expected_status',200));latency=int(data.get('max_latency_ms',800))
    if not 100<=status<=599:raise ValueError('Expected status must be 100–599')
    if not 1<=latency<=30000:raise ValueError('Latency limit must be 1–30000 ms')
    rules=data.get('rules',{})
    if not isinstance(rules,dict) or len(rules)>32:raise ValueError('Rules must be an object containing at most 32 paths')
    for path,kind in rules.items():
        if not isinstance(path,str) or not 1<=len(path)<=150 or path.count('.')>16 or kind not in ('string','number','integer','boolean','object','array','null'):raise ValueError('Invalid path or JSON type in rules')
    return name,url,status,latency,json.dumps(rules)
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*a,**kw):return None
OPENER=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
def matches(value,kind):
    if kind=='number':return type(value) in (int,float)
    return type(value) is {'string':str,'integer':int,'boolean':bool,'object':dict,'array':list,'null':type(None)}[kind]
def lookup(data,path):
    if path=='$':return True,data
    for part in path.split('.'):
        if isinstance(data,dict) and part in data:data=data[part]
        elif isinstance(data,list) and part.isdigit() and int(part)<len(data):data=data[int(part)]
        else:return False,None
    return True,data
def differences(old,new,path='$',out=None):
    if out is None:out=[]
    if len(out)>=50:return out
    if type(old) is not type(new):out.append({'path':path,'change':'type changed','before':type(old).__name__,'after':type(new).__name__})
    elif isinstance(new,dict):
        for key in sorted(old.keys()|new.keys()):
            p=path+'.'+key
            if key not in old:out.append({'path':p,'change':'added'})
            elif key not in new:out.append({'path':p,'change':'removed'})
            else:differences(old[key],new[key],p,out)
            if len(out)>=50:break
    elif isinstance(new,list):
        if len(old)!=len(new):out.append({'path':path,'change':'length changed','before':len(old),'after':len(new)})
        for i,(a,b) in enumerate(zip(old,new)):
            differences(a,b,path+'.'+str(i),out)
            if len(out)>=50:break
    elif old!=new:out.append({'path':path,'change':'value changed','before':str(old)[:100],'after':str(new)[:100]})
    return out[:50]
def run_monitor(mid):
    with connect() as con:
        row=con.execute('SELECT * FROM monitors WHERE id=?',(mid,)).fetchone()
        previous=con.execute('SELECT response FROM runs WHERE monitor_id=? AND response IS NOT NULL ORDER BY id DESC LIMIT 1',(mid,)).fetchone()
    if not row:raise ValueError('Monitor not found')
    m=dict(row);status=None;error=None;payload=None;rawtext=None;checks=[];changes=[]
    start=time.monotonic()
    try:
        target(m['url']);headers={'Accept':'application/json','User-Agent':'ContractWatch/1.0'}
        token=os.environ.get('MONITOR_BEARER_TOKEN')
        if token:headers['Authorization']='Bearer '+token
        request=urllib.request.Request(m['url'],headers=headers)
        try:response=OPENER.open(request,timeout=5)
        except urllib.error.HTTPError as exc:response=exc
        with response:
            status=response.status;body=response.read(MAX_BODY+1)
            if len(body)>MAX_BODY:raise ValueError('Response exceeds the 256 KiB limit')
        rawtext=body.decode('utf-8');payload=json.loads(rawtext)
        # Reject NaN/Infinity and overly deep JSON before recursive comparison.
        def depth(value,level=0):
            if level>50:raise ValueError('JSON nesting exceeds 50 levels')
            if isinstance(value,dict):
                for child in value.values():depth(child,level+1)
            elif isinstance(value,list):
                for child in value:depth(child,level+1)
        depth(payload)
        json.dumps(payload,allow_nan=False)
    except Exception as exc:error=str(exc)[:300];rawtext=None
    duration=int((time.monotonic()-start)*1000)
    checks.append({'rule':'HTTP status','expected':m['expected_status'],'actual':status,'passed':status==m['expected_status']})
    checks.append({'rule':'Response time','expected':str(m['max_latency_ms'])+' ms maximum','actual':str(duration)+' ms','passed':error is None and duration<=m['max_latency_ms']})
    checks.append({'rule':'Valid JSON','expected':'UTF-8 JSON, ≤256 KiB','actual':error or 'Valid JSON','passed':error is None})
    for path,kind in json.loads(m['rules']).items():
        exists,value=lookup(payload,path) if error is None else (False,None)
        checks.append({'rule':path,'expected':kind,'actual':type(value).__name__ if exists else 'missing','passed':exists and matches(value,kind)})
    if previous and rawtext is not None:changes=differences(json.loads(previous['response']),payload)
    with connect() as con:
        cur=con.execute('INSERT INTO runs(monitor_id,at,status,duration_ms,passed,checks,changes,response,error) VALUES (?,?,?,?,?,?,?,?,?)',(mid,now(),status,duration,int(all(c['passed'] for c in checks)),json.dumps(checks),json.dumps(changes),rawtext,error))
        rid=cur.lastrowid
    return rid

class Handler(BaseHTTPRequestHandler):
    server_version='ContractWatch/1.0'
    def log_message(self,*args):pass
    def send(self,code,data,ctype='application/json'):
        raw=json.dumps(data).encode() if ctype=='application/json' else data.encode()
        self.send_response(code);self.send_header('Content-Type',ctype+'; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'");self.end_headers();self.wfile.write(raw)
    def guard(self,write=False):
        allowed={f'127.0.0.1:{PORT}',f'localhost:{PORT}'}
        if self.headers.get('Host') not in allowed:self.send(403,{'error':'Unrecognized Host'});return False
        if write and self.headers.get('Origin') not in (None,*['http://'+x for x in allowed]):self.send(403,{'error':'Cross-origin writes disabled'});return False
        return True
    def do_GET(self):
        if not self.guard():return
        parsed=urllib.parse.urlsplit(self.path);path=parsed.path
        if path=='/':return self.send(200,(ROOT/'index.html').read_text(),'text/html')
        if path=='/fixtures/orders':
            mode=urllib.parse.parse_qs(parsed.query).get('scenario',['valid'])[0]
            payload=json.loads((ROOT/'fixtures'/'orders.json').read_text())
            if mode=='missing':del payload['order']['id']
            if mode=='type':payload['order']['total_minor']='12900'
            if mode=='slow':time.sleep(1)
            if mode=='invalid':return self.send(200,'Not JSON','text/plain')
            return self.send(503 if mode=='unavailable' else 200,payload)
        if path=='/api/state':
            with connect() as con:
                monitors=[dict(x) for x in con.execute('SELECT * FROM monitors ORDER BY created_at,id')]
                for m in monitors:
                    m['rules']=json.loads(m['rules']);last=con.execute('SELECT * FROM runs WHERE monitor_id=? ORDER BY id DESC LIMIT 1',(m['id'],)).fetchone()
                    m['last']=dict(last) if last else None
                    if m['last']:
                        m['last']['checks']=json.loads(last['checks']);m['last']['changes']=json.loads(last['changes']);m['last'].pop('response')
                runs=[dict(x) for x in con.execute('SELECT r.id,r.monitor_id,m.name,r.at,r.status,r.duration_ms,r.passed,r.error FROM runs r JOIN monitors m ON m.id=r.monitor_id ORDER BY r.id DESC LIMIT 16')]
                total=con.execute('SELECT count(*) FROM runs').fetchone()[0]
            return self.send(200,{'monitors':monitors,'runs':runs,'total_runs':total,'remote_enabled':os.environ.get('ALLOW_REMOTE_ENDPOINTS')=='1'})
        if path.startswith('/api/runs/'):
            with connect() as con:row=con.execute('SELECT * FROM runs WHERE id=?',(path.rsplit('/',1)[-1],)).fetchone()
            if not row:return self.send(404,{'error':'Run not found'})
            data=dict(row)
            for key in ('checks','changes','response'):
                if data[key] is not None:data[key]=json.loads(data[key])
            return self.send(200,data)
        if path=='/api/export.csv':
            stream=io.StringIO();w=csv.writer(stream);w.writerow(['run_id','monitor','timestamp','status','duration_ms','passed','error'])
            with connect() as con:
                for row in con.execute('SELECT r.id,m.name,r.at,r.status,r.duration_ms,r.passed,r.error FROM runs r JOIN monitors m ON m.id=r.monitor_id ORDER BY r.id'):
                    w.writerow([("'"+str(v)) if str(v).startswith(('=','+','-','@','\t','\r')) else v for v in row])
            return self.send(200,stream.getvalue(),'text/csv')
        self.send(404,{'error':'Not found'})
    def do_POST(self):
        if not self.guard(True):return
        try:
            if self.headers.get('Transfer-Encoding'):raise ValueError('Transfer-Encoding is unsupported')
            n=int(self.headers.get('Content-Length','0'))
            if not 1<=n<=MAX_BODY:raise ValueError('Request must contain 1–262144 bytes')
            self.connection.settimeout(10);raw=self.rfile.read(n)
            if len(raw)!=n:raise ValueError('Incomplete request')
            data=json.loads(raw)
            if not isinstance(data,dict):raise ValueError('Expected a JSON object')
            path=urllib.parse.urlsplit(self.path).path
            if path=='/api/monitors':
                cfg=validate_config(data);mid='mon_'+secrets.token_hex(5)
                with connect() as con:
                    if con.execute('SELECT count(*) FROM monitors').fetchone()[0]>=50:raise ValueError('Maximum of 50 monitors reached')
                    con.execute('INSERT INTO monitors VALUES (?,?,?,?,?,?,?)',(mid,*cfg,now()))
                return self.send(201,{'id':mid})
            if path=='/api/verification':
                scenario=data.get('scenario','valid')
                if scenario not in ('valid','missing','type','unavailable','slow','invalid'):raise ValueError('Invalid verification scenario')
                cfg=validate_config({'name':'Verification / '+scenario,'url':f'http://127.0.0.1:{PORT}/fixtures/orders?scenario='+scenario,'rules':{'source':'string','order.id':'string','order.total_minor':'integer','order.currency':'string'},'expected_status':200,'max_latency_ms':800});mid='mon_'+secrets.token_hex(5)
                with connect() as con:
                    if con.execute('SELECT count(*) FROM monitors').fetchone()[0]>=50:raise ValueError('Maximum of 50 monitors reached')
                    con.execute('INSERT INTO monitors VALUES (?,?,?,?,?,?,?)',(mid,*cfg,now()))
                return self.send(201,{'id':mid})
            if path.startswith('/api/update/'):
                mid=path.rsplit('/',1)[-1];cfg=validate_config(data)
                with connect() as con:
                    # A changed contract starts a new version so earlier runs remain interpretable.
                    row=con.execute('SELECT id FROM monitors WHERE id=?',(mid,)).fetchone()
                    if not row:return self.send(404,{'error':'Monitor not found'})
                    if con.execute('SELECT count(*) FROM monitors').fetchone()[0]>=50:raise ValueError('Maximum of 50 monitors reached')
                    new_id='mon_'+secrets.token_hex(5)
                    con.execute('INSERT INTO monitors VALUES (?,?,?,?,?,?,?)',(new_id,*cfg,now()))
                return self.send(201,{'id':new_id,'previous_version':mid})
            if path=='/api/run' or path.startswith('/api/run/'):
                if not RUN_LOCK.acquire(False):return self.send(409,{'error':'Checks are already running'})
                try:
                    with connect() as con:ids=[x[0] for x in con.execute('SELECT id FROM monitors')] if path=='/api/run' else [path.rsplit('/',1)[-1]]
                    results=[run_monitor(mid) for mid in ids]
                finally:RUN_LOCK.release()
                return self.send(200,{'run_ids':results})
            self.send(404,{'error':'Not found'})
        except (ValueError,TypeError,UnicodeError) as exc:self.send(400,{'error':str(exc)[:300]})
        except Exception as exc:self.send(500,{'error':'Check could not complete'});print(type(exc).__name__,str(exc),flush=True)
if __name__=='__main__':
    init();server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler);server.daemon_threads=True
    print(f'ContractWatch available at http://127.0.0.1:{PORT}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
