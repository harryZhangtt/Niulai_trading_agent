#!/usr/bin/env python3
"""Provider-free held fixture binary: loopback only, exact stdin, optional child/signal faults."""
import argparse,http.client,json,os,signal,subprocess,sys,time
p=argparse.ArgumentParser(add_help=False)
p.add_argument('rest',nargs='*'); p.add_argument('--fixture-port',type=int,required=True); p.add_argument('--scenario',required=True); p.add_argument('--fingerprint',required=True); p.add_argument('--admission',required=True)
a,unknown=p.parse_known_args(); prompt=sys.stdin.buffer.read()
if a.scenario=='pre_timeout': time.sleep(10); raise SystemExit(2)
headers={'X-R6-Fingerprint':a.fingerprint,'X-R6-Admission':a.admission,'Authorization':'Bearer synthetic-process-secret','Cookie':'fixture-cookie','Content-Type':'application/json'}
def send():
 c=http.client.HTTPConnection('127.0.0.1',a.fixture_port,timeout=2); c.request('POST','/backend-api/codex/responses',b'{}',headers); r=c.getresponse(); data=r.read(); status=r.status; c.close(); return status,data
status,data=send()
if a.scenario=='second':
 status2,_=send(); print('SECOND_STATUS=%d'%status2,file=sys.stderr)
if a.scenario in ('child','signal'):
 child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); print('CHILD_PID=%d'%child.pid,file=sys.stderr,flush=True); time.sleep(30)
if a.scenario=='resistant_child':
 child=subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)']); print('CHILD_PID=%d'%child.pid,file=sys.stderr,flush=True); time.sleep(.15)
if a.scenario=='exception_secret': raise RuntimeError('Bearer synthetic-exception-secret Cookie=fixture-cookie')
if a.scenario=='absent': data=b'{"type":"response.delta"}\n'
if a.scenario=='multiple': data=data+data
if a.scenario=='contradictory':
 event=json.loads(data); event['model']='wrong-model'; data=(json.dumps(event,separators=(',',':'))+'\n').encode()
if a.scenario=='malformed': data=b'{"type":"response.completed"'
if a.scenario=='post_timeout': time.sleep(10)
sys.stdout.buffer.write(data); sys.stdout.buffer.flush()
