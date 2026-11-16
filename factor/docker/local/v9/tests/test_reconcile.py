import copy, json, stat, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from factor.docker.local.v9 import reconcile as r
class R:
 def __init__(self,code,out):self.returncode=code;self.stdout=out;self.stderr=b''
def good(argv,env,timeout=30):
 s=' '.join(argv)
 if 'context show' in s:return R(0,b'default\n')
 if 'status factor-mining' in s:return R(0,json.dumps({'display_name':'colima [profile=factor-mining]','driver':'macOS Virtualization.Framework','arch':'aarch64','runtime':'docker','mount_type':'virtiofs','docker_socket':'x','containerd_socket':'x','kubernetes':False,'cpu':6,'memory':12884901888,'disk':42949672960}).encode())
 if 'context inspect' in s:return R(0,json.dumps([{'Name':'colima-factor-mining','Endpoints':{'docker':{'Host':'unix:///w/.c/factor-mining/docker.sock'}},'Storage':{'MetadataPath':'/w/d/contexts/meta/x','TLSPath':'/w/d/contexts/tls/x'}}]).encode())
 return R(0,json.dumps({'Name':'colima-factor-mining','NCPU':6,'MemTotal':12513542144,'Containers':0,'Images':0,'PidsLimit':True,'MemoryLimit':True,'SwapLimit':True,'CPUShares':True,'CgroupVersion':'2'}).encode())
class Tests(unittest.TestCase):
 def test_strict_rejects_duplicate_nonfinite(self):
  for x in (b'{"a":1,"a":2}',b'{"a":NaN}',b'{} trailing'):
   with self.assertRaises(r.ReconcileError):r.strict(x)
 def test_nonzero_rejected(self):
  def bad(a,e,t=30):return R(7,b'{}')
  with self.assertRaises(r.ReconcileError):r.reconcile(bad)
 def test_live_shape_with_private_temp_roots(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);c=root/'.c';d=root/'d';(c/'factor-mining').mkdir(parents=True);(d/'contexts/meta/x').mkdir(parents=True);(d/'contexts/tls/x').mkdir(parents=True);sock=c/'factor-mining/docker.sock';sock.touch();containerd=c/'factor-mining/containerd.sock';containerd.touch()
   def f(a,e,t=30):
    z=good(a,e,t);s=' '.join(a)
    if 'status factor-mining' in s:
     value=json.loads(z.stdout);value['docker_socket']='unix://'+str(sock);value['containerd_socket']='unix://'+str(containerd);z.stdout=json.dumps(value).encode()
    z.stdout=z.stdout.replace(b'/w/.c',str(c).encode()).replace(b'/w/d',str(d).encode());return z
   with patch.multiple(r,COLIMA_HOME=c,DOCKER_CONFIG=d):
    real=r.stat.S_ISSOCK;r.stat.S_ISSOCK=lambda _m:True
    try:self.assertEqual(r.reconcile(f)['status'],'reconciled-running')
    finally:r.stat.S_ISSOCK=real
if __name__=='__main__':unittest.main()
