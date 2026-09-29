#!/usr/bin/env python3
"""Run configured contracts through the local service; exit 1 if any latest check fails."""
import json, urllib.request
import server
base=f'http://127.0.0.1:{server.PORT}'
req=urllib.request.Request(base+'/api/run',data=b'{}',headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req,timeout=300) as r:result=json.load(r)
with urllib.request.urlopen(base+'/api/state',timeout=8) as r:state=json.load(r)
summary=[{'name':m['name'],'passed':bool(m['last']['passed']),'status':m['last']['status'],'duration_ms':m['last']['duration_ms']} for m in state['monitors'] if m['last']]
print(json.dumps({'run_ids':result['run_ids'],'results':summary},indent=2))
raise SystemExit(1 if any(not m['passed'] for m in summary) else 0)
