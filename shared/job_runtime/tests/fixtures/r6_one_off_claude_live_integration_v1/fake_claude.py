#!/usr/bin/env python3
import json,os,signal,subprocess,sys,time,urllib.error,urllib.request
base=os.environ["ANTHROPIC_BASE_URL"];scenario=os.environ.get("R6_SCENARIO","nominal");req=urllib.request.Request(base+"/v1/messages",data=b'{}',method="POST",headers={"X-R6-Fingerprint":os.environ["R6_FINGERPRINT"]})
def call():
 try:
  with urllib.request.urlopen(req,timeout=1) as r:r.read()
 except urllib.error.HTTPError:pass
call()
if scenario=="second_request":call()
if scenario in ("resistant_descendant","parent_exit_resistant"):
 child=subprocess.Popen([sys.executable,"-c","import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)"]);sys.stderr.write("CHILD_PID=%d\n"%child.pid);sys.stderr.flush()
 if scenario=="resistant_descendant":time.sleep(10)
if scenario=="timeout":time.sleep(10)
if scenario=="secret":sys.stderr.write("synthetic sk-ant-test-secret must remain private\n")
if scenario=="truncation":sys.stdout.write('{"type":"result"');sys.exit(0)
print(json.dumps({"type":"result","subtype":"success","is_error":False,"model":"claude-opus-5-5","result":"synthetic loopback only"},sort_keys=True,separators=(",",":")))
if scenario=="nonzero_success":sys.exit(7)
