import builtins,copy,importlib,json,os,stat,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from _loader import module
from _support import NOW,REQUEST,fixture,make,sha
class ReviewRepairTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.c=module("contracts");cls.p=module("preflight");cls.a=module("adapter");cls.r=module("runner");cls.rec=module("reconciliation")
 def adapter(self):return self.a.SyntheticObservationAdapter("nominal",fixture("nominal.json")["observation"])
 def run_stop(self,grant,root):
  adapter=self.adapter();result=self.r.run_synthetic(grant=grant,synthetic_root=Path(root),now=NOW,request=REQUEST,adapter=adapter)
  self.assertEqual((result["terminal_outcome"],result["upstream_attempt_count"],adapter.observation_count),("STOP",0,0))
 def rewrite(self,grant,name,data):
  p=Path(grant["artifacts"][name]["path"]);p.chmod(0o600);p.write_bytes(data);p.chmod(0o500 if name=="executable" else 0o400);info=p.stat();grant["artifacts"][name].update(bytes=len(data),sha256=sha(data),inode=info.st_ino,owner=info.st_uid,mode=stat.S_IMODE(info.st_mode))
 def test_single_writer_and_transition_enforcement_table(self):
  for owner,fields in self.c.STATE_WRITERS.items():
   for field in fields:self.c.enforce_authority(owner,{field})
  for transition in self.c.LEGAL_TRANSITIONS:self.c.enforce_authority("Engine",{"status"},transition)
  forbidden=[("gateway",{"status"},None),("Engine",{"request_admission"},None),("translator",{"raw_streams"},None),("reconciler",{"provider_status_calls"},None),("evaluation",{"countability_decision"},("ADMITTED","PASS")),("Engine",{"status"},("PASS","UNKNOWN")),("Engine",set(),None)]
  for owner,writes,transition in forbidden:
   with self.assertRaises(self.c.R6ContractError):self.c.enforce_authority(owner,writes,transition)
 def test_exact_historical_field_reuse_and_fresh_tuple(self):
  with tempfile.TemporaryDirectory() as d:
   fresh=make(d)["identity"];self.c.validate_identity(fresh)
   checked=0
   for record in self.c.HISTORICAL_IDENTITIES.values():
    for field,value in record.items():
     if value is None:continue
     bad=dict(fresh);bad[field]=value[7:] if value.startswith("sha256:") else value
     with self.assertRaisesRegex(self.c.R6ContractError,"R6_PRIOR_IDENTITY_REUSE"):self.c.validate_identity(bad)
     checked+=1
   self.assertEqual(checked,5)
 def test_all_artifacts_reject_identity_metadata_and_same_length_drift(self):
  for name in ("executable","canonical_argv","canonical_config","model_catalog","prompt"):
   for field in ("inode","owner","mode"):
    with tempfile.TemporaryDirectory() as d:
     grant=make(d);bad=copy.deepcopy(grant["artifacts"]);bad[name][field]+=1
     with self.assertRaises(self.c.R6ContractError):
      with self.c.SecureArtifactSet(bad,Path(d)) as opened:opened.read_all()
   with tempfile.TemporaryDirectory() as d:
    grant=make(d);p=Path(grant["artifacts"][name]["path"]);old=p.read_bytes();p.chmod(0o600);p.write_bytes(bytes((x^1) for x in old));p.chmod(grant["artifacts"][name]["mode"])
    with self.assertRaisesRegex(self.c.R6ContractError,"R6_FILE_DIGEST_MISMATCH"):
     with self.c.SecureArtifactSet(grant["artifacts"],Path(d)) as opened:opened.read_all()
 def test_all_artifacts_reject_path_swap_while_descriptor_held(self):
  for name in ("executable","canonical_argv","canonical_config","model_catalog","prompt"):
   with tempfile.TemporaryDirectory() as d:
    grant=make(d);p=Path(grant["artifacts"][name]["path"]);old=p.read_bytes();mode=grant["artifacts"][name]["mode"]
    with self.c.SecureArtifactSet(grant["artifacts"],Path(d)) as opened:
     p.rename(p.with_name(p.name+".held"));p.write_bytes(old);p.chmod(mode)
     with self.assertRaisesRegex(self.c.R6ContractError,"R6_PATH_SUBSTITUTION"):opened.read_all()
 def test_symlink_parent_rejected(self):
  with tempfile.TemporaryDirectory() as d,tempfile.TemporaryDirectory() as out:
   root=Path(d).resolve();external=Path(out).resolve();p=external/"x";p.write_bytes(b"x");p.chmod(0o400);info=p.stat();(root/"link").symlink_to(external,target_is_directory=True)
   bound={"path":str(root/"link/x"),"bytes":1,"sha256":sha(b"x"),"inode":info.st_ino,"owner":info.st_uid,"mode":stat.S_IMODE(info.st_mode)}
   with self.assertRaises(self.c.R6ContractError):
    with self.c.SecureArtifactSet({"x":bound},root) as opened:opened.read_all()
 def test_every_preflight_gate_stops_before_adapter(self):
  cases=[]
  cases += [("account_shape",lambda g:g["account"].update(extra=False)),("entitlement",lambda g:g["account"].update(entitlement=False)),("model_access",lambda g:g["account"].update(model_access=False)),("auth_checked",lambda g:g["account"].update(auth_checked_at="2030-01-01T02:00:00Z")),("auth_expiry",lambda g:g["account"].update(auth_expires_at="2029-01-01T00:00:00Z")),("fingerprint",lambda g:g["account"].update(opaque_account_fingerprint="d"*64)),("credential_ref",lambda g:g["account"].update(credential_reference_only=False))]
  cases += [("currency",lambda g:g["budget"].update(currency="EUR")),("hard_max",lambda g:g["budget"].update(hard_maximum=0)),("cost_authority",lambda g:g["budget"].update(cost_authority="live")),("final_cost",lambda g:g["budget"].update(final_cost_receipt={})),("not_before",lambda g:g["window"].update(not_before="2031-01-01T00:00:00Z")),("deadline",lambda g:g["window"].update(deadline="2029-01-01T00:00:00Z")),("uid",lambda g:g["private_root"].update(owner_uid=-1)),("mode_flag",lambda g:g["private_root"].update(mode_0700=False)),("nofollow",lambda g:g["private_root"].update(nofollow_components=False)),("atomic",lambda g:g["private_root"].update(atomic_finalization=False)),("synthetic",lambda g:g.update(synthetic_only=False)),("enabled",lambda g:g.update(enabled=True)),("live_authority",lambda g:g.update(live_authority=True)),("parser",lambda g:g["artifacts"]["model_catalog"].update(parser_source_sha256="0"*64)),("catalog",lambda g:g["artifacts"]["model_catalog"].update(selected_model_occurrences=2))]
  for name,mutate in cases:
   with self.subTest(name=name),tempfile.TemporaryDirectory() as d:
    grant=make(d);mutate(grant);self.run_stop(grant,d)
  for name,data in (("canonical_argv",b'[]'),("canonical_config",b'{}')):
   with self.subTest(name=name),tempfile.TemporaryDirectory() as d:
    grant=make(d);self.rewrite(grant,name,data);self.run_stop(grant,d)
  with tempfile.TemporaryDirectory() as d:
   grant=make(d);os.chmod(d,0o755);self.run_stop(grant,d)
 def test_unknown_atomic_reload_fresh_lifecycle_no_dispatch(self):
  with tempfile.TemporaryDirectory() as d:
   grant=make(d);adapter=self.a.SyntheticObservationAdapter("post_admission_ambiguity",fixture("post-admission-unknown.json")["observation"]);result=self.r.run_synthetic(grant=grant,synthetic_root=Path(d),now=NOW,request=REQUEST,adapter=adapter);path=Path(d)/"unknown.json";receipt=self.rec.persist_unknown(path,result,synthetic_root=Path(d));self.assertTrue(receipt["atomic"])
   lifecycle=self.rec.UnknownLifecycle(path,Path(d));loaded=lifecycle.resume();self.assertEqual((loaded["terminal_outcome"],lifecycle.dispatch_count,lifecycle.replay_count,adapter.observation_count),("UNKNOWN",0,0,1))
 def test_cleanup_resources_explicitly_inapplicable(self):
  with tempfile.TemporaryDirectory() as d:
   grant=make(d);result=self.r.run_synthetic(grant=grant,synthetic_root=Path(d),now=NOW,request=REQUEST,adapter=self.adapter())
   for key in ("process_group","listener","socket_path","file_descriptors","temporary_paths"):self.assertEqual(result["cleanup"][key],{"applicable":False,"evidence":"provider_free_no_resource_created"})
 def test_real_package_import_has_no_product_filesystem_or_effect_calls(self):
  package="codex_live_evidence_r6_v1";workspace=str(Path(__file__).resolve().parents[3]/"candidates");sys.path.insert(0,workspace);saved={k:v for k,v in sys.modules.items() if k==package or k.startswith(package+".")}
  for key in saved:sys.modules.pop(key,None)
  calls=[]
  original_open=os.open;original_read=Path.read_bytes;original_write=Path.write_bytes
  def watched_open(*a,**k):calls.append(("os.open",a[0]));return original_open(*a,**k)
  def watched_read(self,*a,**k):calls.append(("read",str(self)));return original_read(self,*a,**k)
  def watched_write(self,*a,**k):calls.append(("write",str(self)));return original_write(self,*a,**k)
  try:
   with patch("os.open",watched_open),patch("pathlib.Path.read_bytes",watched_read),patch("pathlib.Path.write_bytes",watched_write):importlib.import_module(package)
  finally:
   for key in list(sys.modules):
    if key==package or key.startswith(package+"."):sys.modules.pop(key,None)
   sys.modules.update(saved);sys.path.remove(workspace)
  self.assertEqual(calls,[])
