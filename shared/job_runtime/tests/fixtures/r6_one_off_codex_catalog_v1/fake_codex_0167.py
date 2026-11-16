#!/usr/bin/env python3
import http.client,json,os,re,sys,time
from pathlib import Path
mode=Path.cwd().name.split('.')[-1];argv=sys.argv[1:];config=next((v for v in argv if 'base_url=' in v),'');match=re.search(r'base_url="http://127\.0\.0\.1:(\d+)/backend-api/codex"',config)
if not match or argv[-3:]!=['app-server','--listen','stdio://']:sys.exit(80)
port=int(match.group(1));secret=os.environ['CODEX_API_KEY'];Path(os.environ['CODEX_HOME'],'contained-write').write_text('contained');print('fake-app-server-stderr',file=sys.stderr,flush=True)
def call(path='/backend-api/codex/models?client_version=0.167.0',body=None,method='GET'):
 c=http.client.HTTPConnection('127.0.0.1',port,timeout=3);c.request(method,path,body=body,headers={'Authorization':'Bearer '+secret});r=c.getresponse();status=r.status;data=r.read();c.close();return status,data
if mode=='wrongpath':call('/wrong')
elif mode=='wrongbody':call(body=b'x')
else:status,provider=call()
init=sys.stdin.buffer.readline();expected=b'{"id":1,"method":"initialize","params":{"clientInfo":{"name":"r6-one-off-codex-catalog-v8","version":"8"}}}\n'
if init!=expected:sys.exit(81)
if mode=='inittimeout':time.sleep(60)
identifier=True if mode=='boolid' else 1
print(json.dumps({'id':identifier,'result':{'codexHome':os.environ['CODEX_HOME'],'platformFamily':'unix','platformOs':'macos','userAgent':'fake'}},separators=(',',':')),flush=True)
if mode=='boolid':time.sleep(60)
if sys.stdin.buffer.readline()!=b'{"method":"initialized"}\n':sys.exit(82)
if sys.stdin.buffer.readline()!=b'{"id":2,"method":"model/list","params":{"includeHidden":true}}\n':sys.exit(83)
if mode=='second':call();print('{"id":2,"error":{"code":-32600,"message":"second rejected"}}',flush=True)
elif mode=='alternate':call(method='HEAD');call(method='TRACE');call(method='BREW');print('{"id":2,"error":{"code":-32600,"message":"subsequent rejected"}}',flush=True)
elif mode=='rpcfail':print('{"id":2,"error":{"code":-32603,"message":"synthetic"}}',flush=True)
elif mode=='id2timeout':time.sleep(60)
elif status==200:
 try:slugs=[x['slug'] for x in json.loads(provider)['models']]
 except Exception:slugs=[]
 print(json.dumps({'id':2,'result':{'data':[{'id':s} for s in slugs],'nextCursor':None}},separators=(',',':')),flush=True)
else:print('{"id":2,"error":{"code":-32603,"message":"catalog failed"}}',flush=True)
for line in sys.stdin.buffer:
 if line.strip():sys.exit(84)
