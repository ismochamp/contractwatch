#!/usr/bin/env python3
"""Add clearly labeled local fixtures and record real endpoint checks."""
import json,urllib.request
import server
base=f'http://127.0.0.1:{server.PORT}'
def post(path,data):
    req=urllib.request.Request(base+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
for scenario in ('valid','missing','type','unavailable'):post('/api/verification',{'scenario':scenario})
print(json.dumps(post('/api/run',{}),indent=2))
with urllib.request.urlopen(base+'/api/state',timeout=8) as r:print(json.dumps(json.load(r),indent=2))
