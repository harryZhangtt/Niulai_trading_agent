#!/usr/bin/env python3
"""Provider-free Codex-shaped process for the source-pinned v2 integration."""
import argparse,http.client,json,subprocess,sys,time
p=argparse.ArgumentParser(add_help=False)
p.add_argument('rest',nargs='*');p.add_argument('--fixture-port',type=int,required=True);p.add_argument('--scenario',required=True);p.add_argument('--fingerprint',required=True);p.add_argument('--admission',required=True)
a,_=p.parse_known_args();prompt=sys.stdin.buffer.read()
if a.scenario=='pre_timeout':time.sleep(20);raise SystemExit(2)
headers={'X-R6-Fingerprint':a.fingerprint,'X-R6-Admission':a.admission,'Authorization':'Bearer synthetic-v2-secret','Cookie':'synthetic-v2-cookie','Content-Type':'application/json'}
def send():
 c=http.client.HTTPConnection('127.0.0.1',a.fixture_port,timeout=3);c.request('POST','/backend-api/codex/responses',b'{}',headers);r=c.getresponse();data=r.read();status=r.status;c.close();return status,data
status,data=send()
if a.scenario=='second':status2,_=send();print('SECOND_STATUS=%d'%status2,file=sys.stderr)
if a.scenario=='malformed':data=b'{"type":"response.completed"'
if a.scenario=='multiple':data=data+data
if a.scenario=='contradictory':
 event=json.loads(data);event['model']='wrong-model';data=(json.dumps(event,separators=(',',':'))+'\n').encode()
if a.scenario=='post_timeout':time.sleep(20)
if a.scenario=='nonzero_success':sys.stdout.buffer.write(data);sys.stdout.buffer.flush();raise SystemExit(7)
sys.stdout.buffer.write(data);sys.stdout.buffer.flush()
