from __future__ import annotations
import ast,json,smtplib,socket,subprocess,sys,tempfile,unittest,urllib.request
from pathlib import Path
from unittest import mock
from shared.job_runtime.candidates.r6_one_off_claude_live_driver_v1 import FakeFerryObserver,FakeProcess,run_provider_free
ROOT=Path(__file__).resolve().parents[5];FIX=ROOT/"shared/job_runtime/tests/fixtures/r6_one_off_claude_live_driver_v1";CASES=json.loads((FIX/"cases.json").read_text())
class DriverTests(unittest.TestCase):
 def guarded(self,root,scenario,process=None,ferry=None):
  deny=AssertionError("external effect attempted")
  with mock.patch.object(socket,"socket",side_effect=deny),mock.patch.object(socket,"create_connection",side_effect=deny),mock.patch.object(subprocess,"Popen",side_effect=deny),mock.patch.object(subprocess,"run",side_effect=deny),mock.patch.object(urllib.request,"urlopen",side_effect=deny),mock.patch.object(smtplib,"SMTP",side_effect=deny):return run_provider_free(root,scenario,process,ferry)
 def test_all_frozen_cases(self):
  for scenario,expected in CASES.items():
   with self.subTest(scenario=scenario),tempfile.TemporaryDirectory(dir=FIX) as t:
    r=self.guarded(Path(t)/"case",scenario);self.assertEqual(r.evidence["status"],expected);self.assertEqual(set(r.evidence["effects"].values()),{0});self.assertFalse(r.evidence["countable"])
 def test_engine_materialized_before_process_and_exact_readback(self):
  class Inspect(FakeProcess):
   def start(self,spec,readback):
    assert readback["verified"] is True and readback["counts"]=={"job":1,"slot":1,"attempt":1,"prompt_artifact":1};assert readback["native_prompt"]["sha256"]==spec["prompt"]["sha256"];return super().start(spec,readback)
  with tempfile.TemporaryDirectory(dir=FIX) as t:
   p=Inspect();r=self.guarded(Path(t)/"case","nominal",p);e=r.evidence;self.assertEqual(e["status"],"PASS");self.assertEqual(p.starts,1);self.assertTrue(all(e["engine_readback"][k] for k in ("job_id","slot_id","attempt_id","operation_id","provider_process_id","request_id")))
 def test_launch_receipt_exact_echo(self):
  with tempfile.TemporaryDirectory(dir=FIX) as t:
   e=self.guarded(Path(t)/"case","nominal").evidence;p=e["process"]
   self.assertEqual(p["launch_spec_digest_echo"],e["launch_spec_digest"]);self.assertFalse(p["shell"]);self.assertEqual(p["model"],"claude-opus-5-5");self.assertTrue(p["process_group"] and p["terminate_policy"] and p["kill_policy"] and p["reap_policy"]);self.assertEqual(p["deadline_seconds"],30)
 def test_duplicate_rejected_before_only_process_start(self):
  with tempfile.TemporaryDirectory(dir=FIX) as t:
   p=FakeProcess();f=FakeFerryObserver();e=self.guarded(Path(t)/"case","duplicate",p,f).evidence;self.assertEqual((p.starts,e["ferry"]["admission_count"],e["ferry"]["upstream_count"],e["ferry"]["second_reject_count"]),(1,1,1,1))
 def test_predispatch_drift_stop_zero(self):
  for case in ("auth","model","cost","window","custody","binding","launch_spec"):
   with self.subTest(case=case),tempfile.TemporaryDirectory(dir=FIX) as t:
    p=FakeProcess();f=FakeFerryObserver();r=self.guarded(Path(t)/"case",case,p,f);self.assertEqual(r.evidence["status"],"STOP");self.assertEqual((p.starts,f.admission_count,f.upstream_count),(0,0,0))
 def test_faults_alter_boundary_and_create_fence_without_public_final(self):
  expectations={"path_swap":("output_identity","swapped/output"),"parser":("parser_identity","wrong_parser"),"terminal":("terminal_state","truncated"),"cleanup":("reaps",0),"secret":("nested_error",{"present":True,"code":"REDACTED_SENSITIVE_ERROR"}),"launch_echo":("launch_spec_digest_echo","0"*64)}
  for case,(key,value) in expectations.items():
   with self.subTest(case=case),tempfile.TemporaryDirectory(dir=FIX) as t:
    root=Path(t)/"case";e=self.guarded(root,case).evidence;self.assertEqual(e["status"],"UNKNOWN");self.assertEqual(e["process"][key],value);self.assertTrue((root/"unknown-fence.json").is_file());self.assertTrue((root/"ferry/admission.json").is_file());self.assertFalse((root/"sanitized/execution").exists());self.assertTrue((root/"owner-private/execution").is_dir())
    admission=json.loads((root/"ferry/admission.json").read_text());self.assertEqual(admission["operation_id"],e["engine_readback"]["operation_id"]);self.assertEqual(admission["provider_process_id"],e["engine_readback"]["provider_process_id"]);self.assertEqual(admission["launch_spec_digest"],e["launch_spec_digest"])
 def test_publication_failures_fence_before_return_and_no_partial_final(self):
  for case in ("publication","owner_publication"):
   with self.subTest(case=case),tempfile.TemporaryDirectory(dir=FIX) as t:
    root=Path(t)/"case";r=self.guarded(root,case);self.assertEqual(r.evidence["status"],"UNKNOWN");self.assertTrue((root/"unknown-fence.json").is_file());self.assertFalse((root/"sanitized/execution").exists());self.assertFalse(any("staging" in p.name for p in root.rglob('*')))
 def test_no_replay_after_unknown(self):
  with tempfile.TemporaryDirectory(dir=FIX) as t:
   root=Path(t)/"case";p=FakeProcess("timeout");f=FakeFerryObserver();one=self.guarded(root,"timeout",p,f);two=self.guarded(root,"nominal",p,f);self.assertEqual(one.evidence,two.evidence);self.assertEqual(p.starts,1);self.assertEqual(f.status_calls,0)
 def test_true_no_replace_preserves_prior_public_final(self):
  with tempfile.TemporaryDirectory(dir=FIX) as t:
   root=Path(t)/"case";prior=root/"sanitized/execution";prior.mkdir(parents=True);(prior/"prior").write_text("valid")
   e=self.guarded(root,"collision").evidence;self.assertEqual(e["status"],"UNKNOWN");self.assertTrue(e["publication"]["collision_preserved"]);self.assertEqual((prior/"prior").read_text(),"valid");self.assertTrue((root/"unknown-fence.json").exists())
 def test_import_inert_and_forbidden_imports_absent(self):
  src=ROOT/"shared/job_runtime/candidates/r6_one_off_claude_live_driver_v1";names=[]
  for p in src.glob("*.py"):
   tree=ast.parse(p.read_text());names += [n.module or "" for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)];names += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
  joined="\n".join(names);self.assertNotIn("codex_live_evidence_r6_live_v1",joined);self.assertNotIn("claude-live-smoke",joined)

class OrderingDurabilityImportTests(unittest.TestCase):
 def test_ferry_full_binding_and_order(self):
  with tempfile.TemporaryDirectory(dir=FIX) as t:
   root=Path(t)/"case";e=run_provider_free(root,"nominal").evidence;f=e["ferry"];rb=e["engine_readback"]
   self.assertEqual((f["engine_readback_event"],f["admission_event"]),(1,2))
   for left,right in (("job_id","job_id"),("slot_id","slot_id"),("attempt_id","attempt_id"),("operation_id","operation_id"),("provider_process_id","provider_process_id"),("request_id","request_id")):self.assertEqual(f[left],rb[right])
   self.assertEqual(f["native_prompt_artifact_identity"],rb["native_prompt"]["source_identity_sha256"]);self.assertEqual(f["native_prompt_sha256"],rb["native_prompt"]["sha256"]);self.assertEqual(f["model"],"claude-opus-5-5");self.assertEqual(f["launch_spec_digest"],e["launch_spec_digest"])
 def test_ferry_mismatch_stops_before_admission_upstream_process(self):
  with tempfile.TemporaryDirectory(dir=FIX) as t:
   p=FakeProcess();f=FakeFerryObserver();e=run_provider_free(Path(t)/"case","ferry_mismatch",p,f).evidence
   self.assertEqual(e["status"],"STOP");self.assertEqual((p.starts,f.admission_count,f.upstream_count),(0,0,0))
 def test_injected_owner_and_public_fsync_commit_failures(self):
  from shared.job_runtime.candidates.r6_one_off_claude_live_driver_v1.publication import PublicationTrace
  cases={"owner_file_fsync":"owner_file_fsync","owner_dir_fsync":"owner_stage_dir_fsync","public_commit":"public_commit_attempt","public_dir_fsync":"public_parent_dir_fsync"}
  for case,event in cases.items():
   with self.subTest(case=case),tempfile.TemporaryDirectory(dir=FIX) as t:
    root=Path(t)/"case";trace=PublicationTrace(cases[case]);e=run_provider_free(root,case,publication_trace=trace).evidence
    self.assertEqual(e["status"],"UNKNOWN");self.assertIn(event,trace.events);self.assertTrue((root/"unknown-fence.json").is_file());self.assertIn("fence_file_fsync",trace.events);self.assertIn("fence_dir_fsync",trace.events);self.assertFalse((root/"sanitized/execution").exists());self.assertFalse(any("staging" in p.name for p in root.rglob('*')))
    if case.startswith("public"):self.assertTrue((root/"owner-private/execution").is_dir())
 def test_fence_fsync_failures_never_claim_durable(self):
  from shared.job_runtime.candidates.r6_one_off_claude_live_driver_v1.publication import PublicationError,PublicationTrace
  for case,event in (("fence_file_fsync","fence_file_fsync"),("fence_dir_fsync","fence_dir_fsync")):
   with self.subTest(case=case),tempfile.TemporaryDirectory(dir=FIX) as t:
    root=Path(t)/"case";trace=PublicationTrace(event)
    with self.assertRaisesRegex(PublicationError,"UNKNOWN_FENCE_NOT_DURABLE"):run_provider_free(root,case,publication_trace=trace)
    self.assertIn(event,trace.events);self.assertFalse((root/"unknown-fence.json").exists());self.assertFalse(any("staging" in p.name for p in root.rglob('*')))
 def test_full_transitive_candidate_import_graph_has_no_forbidden_path(self):
  import ast
  candidate="shared.job_runtime.candidates.r6_one_off_claude_live_driver_v1";queue=[candidate];seen=set();forbidden=("codex_live_evidence","claude_live_smoke","claude-live-smoke","niulai-private","live_provider_evidence","anthropic","requests","urllib","socket")
  while queue:
   mod=queue.pop()
   if mod in seen:continue
   seen.add(mod);rel=Path(*mod.split('.'));choices=[ROOT/(str(rel)+".py"),ROOT/rel/"__init__.py"];path=next((x for x in choices if x.is_file()),None)
   if path is None:continue
   self.assertFalse(any(x in mod.lower() or x in path.as_posix().lower() for x in forbidden),(mod,path))
   tree=ast.parse(path.read_text())
   package=mod if path.name=="__init__.py" else mod.rpartition('.')[0]
   for node in ast.walk(tree):
    if isinstance(node,ast.Import):names=[a.name for a in node.names]
    elif isinstance(node,ast.ImportFrom):
     if node.level:
      parts=package.split('.');base='.'.join(parts[:len(parts)-node.level+1]);names=[base+('.'+node.module if node.module else '')]
     else:names=[node.module or '']
    else:continue
    for name in names:
     if name.startswith("shared.job_runtime") or name.startswith("shared.job_runtime.candidates.r6_one_off_claude_adapter_v1"):queue.append(name)
  self.assertIn(candidate,seen);self.assertGreater(len(seen),8)
 def test_isolated_effect_denied_import_subprocess(self):
  script='''import json, pathlib, socket, subprocess, sys, urllib.request\nroot=pathlib.Path(sys.argv[1]);sys.path.insert(0,str(root))\nforbidden=[root/".job-runtime/live-provider-evidence",root/"runtime/claude-live-smoke-20261109-r5"]\nbefore=[p.exists() for p in forbidden]\ndef deny(*a,**k): raise AssertionError("effect")\nsocket.socket=deny;socket.create_connection=deny;urllib.request.urlopen=deny;subprocess.Popen=deny\nimport shared.job_runtime.candidates.r6_one_off_claude_live_driver_v1\nafter=[p.exists() for p in forbidden]\nprint(json.dumps({"before":before,"after":after,"ok":True}))'''
  proc=subprocess.run([sys.executable,"-I","-c",script,str(ROOT)],capture_output=True,text=True,check=True,timeout=30)
  value=json.loads(proc.stdout);self.assertTrue(value["ok"]);self.assertEqual(value["before"],value["after"])
