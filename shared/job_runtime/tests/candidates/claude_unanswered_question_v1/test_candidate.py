from __future__ import annotations
import copy, json, os, tempfile, threading, unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock
from shared.job_runtime.candidates.claude_unanswered_question_v1 import (
    CAPABILITY_STATUS, AnswerDecision, AnswerLedger, ContractError, SyntheticFakeHost, capability_status, create_owner_private_directory,
    decide_answer, load_evidence_manifest, load_source_closure, load_synthetic_fixture,
    parse_live_answer_ack, parse_live_host_event, parse_synthetic_event, synthetic_roundtrip,
    verify_evidence_manifest, verify_source_closure,
)
from shared.job_runtime.candidates.claude_unanswered_question_v1.contracts import FENCE_TERMS, FORBIDDEN_EFFECTS
import shared.job_runtime.candidates.claude_unanswered_question_v1.ledger as ledger_module

ROOT=Path(__file__).resolve().parents[5]
FIXTURE=ROOT/"shared/job_runtime/tests/fixtures/claude_unanswered_question_v1/cases.json"
PACKAGE=ROOT/"shared/job_runtime/candidates/claude_unanswered_question_v1"
OUTER_KEYS={"schema_version","authority","host_contract_observed","host_version_under_study","cases"}

class CandidateTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.outer=json.loads(FIXTURE.read_text(encoding="ascii"));cls.cases=cls.outer["cases"]
 def event(self,index=0,mutate=None):
  raw=copy.deepcopy(self.cases[index]);mutate and mutate(raw);return parse_synthetic_event(raw)
 def ledger(self):
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);parent=Path(temp.name).resolve()/"state";create_owner_private_directory(parent);return AnswerLedger(parent/"answers.jsonl")
 def decision(self,index=0):
  event=self.event(index);return decide_answer(event,now_monotonic_ns=event.observed_monotonic_ns+300_000_000_000)
 def test_live_status_and_parsers_remain_blocked(self):
  status=capability_status();self.assertEqual(status["status"],CAPABILITY_STATUS);self.assertFalse(status["activation_authorized"])
  for parser in (parse_live_host_event,parse_live_answer_ack):
   with self.assertRaisesRegex(ContractError,CAPABILITY_STATUS):parser({})
 def test_outer_fixture_is_exact_sanitized_and_nonauthoritative(self):
  self.assertEqual(set(self.outer),OUTER_KEYS);self.assertEqual(len(load_synthetic_fixture(FIXTURE)),2)
  for mutation,code in ((lambda x:x.update(extra=True),"FIXTURE_SHAPE_INVALID"),(lambda x:x.update(access_token="x"),"FIXTURE_SHAPE_INVALID"),(lambda x:x.update(authority="REAL"),"FIXTURE_INVALID")):
   temp=tempfile.NamedTemporaryFile("w",delete=False);self.addCleanup(lambda p=temp.name:os.unlink(p) if os.path.exists(p) else None)
   bad=copy.deepcopy(self.outer);mutation(bad);json.dump(bad,temp);temp.close()
   with self.assertRaisesRegex(ContractError,code):load_synthetic_fixture(Path(temp.name))
 def test_typed_authority_is_separate_from_caller_category(self):
  event=self.event(mutate=lambda x:x.update(caller_category="anything_caller_claims"));decision=decide_answer(event,now_monotonic_ns=1_300_000_000_000);self.assertTrue(decision.option_ids)
  for effect in sorted(FORBIDDEN_EFFECTS):
   with self.subTest(effect=effect),self.assertRaisesRegex(ContractError,"QUESTION_EFFECT_FENCED"):
    event=self.event(mutate=lambda x,effect=effect:x["authority"].update(forbidden_effects=[effect]));decide_answer(event,now_monotonic_ns=1_300_000_000_000)
  with self.assertRaisesRegex(ContractError,"SAFE_CAPABILITY_INVALID"):self.event(mutate=lambda x:x["authority"].update(safe_capability="caller_safe"))
 def test_text_fence_vocabulary_bypasses_and_descriptions(self):
  for term in FENCE_TERMS:
   with self.subTest(term=term),self.assertRaisesRegex(ContractError,"(QUESTION_TEXT_FENCED|SECRET_SANITIZATION_FAILED)"):
    event=self.event(mutate=lambda x,term=term:x.update(prompt="Please "+term+" this"));decide_answer(event,now_monotonic_ns=1_300_000_000_000)
  for text in ("a p p r o v e this","AUTH-ORIZE this","p.r.i.v.a.t.e k.e.y","accesstoken value"):
   with self.subTest(text=text),self.assertRaises(ContractError):
    event=self.event(mutate=lambda x,text=text:x.update(prompt=text));decide_answer(event,now_monotonic_ns=1_300_000_000_000)
  with self.assertRaisesRegex(ContractError,"QUESTION_TEXT_FENCED"):
   event=self.event(mutate=lambda x:x["options"][0].update(description="deploy target"));decide_answer(event,now_monotonic_ns=1_300_000_000_000)
 def test_recommendation_shapes_and_multi_order(self):
  self.assertEqual(self.decision(1).option_ids,("option.lint.0001","option.unit.0002"))
  cases=((0,lambda x:[o.update(recommended=False) for o in x["options"]],"SINGLE_RECOMMENDATION_INVALID"),(0,lambda x:[o.update(recommended=True) for o in x["options"]],"SINGLE_RECOMMENDATION_INVALID"),(1,lambda x:[o.update(recommended=False) for o in x["options"]],"MULTI_RECOMMENDATION_MISSING"),(0,lambda x:x["options"][0].update(recommended=1),"OPTION_RECOMMENDATION_NOT_EXPLICIT"),(0,lambda x:x["options"].append(copy.deepcopy(x["options"][0])),"DUPLICATE_OPTIONS"),(0,lambda x:x.update(question_kind="freeform"),"FREEFORM_FORBIDDEN"))
  for index,mutation,code in cases:
   with self.subTest(code=code),self.assertRaisesRegex(ContractError,code):
    event=self.event(index,mutation);decide_answer(event,now_monotonic_ns=event.observed_monotonic_ns+300_000_000_000)
 def test_integer_nanosecond_clock_boundaries(self):
  event=self.event()
  decide_answer(event,now_monotonic_ns=1_300_000_000_000)
  for value,code in ((1_299_999_999_999,"QUESTION_NOT_DUE"),(999_999_999_999,"MONOTONIC_INVALID"),(1_300_000_000_000.0,"MONOTONIC_INVALID"),(True,"MONOTONIC_INVALID"),(float("inf"),"MONOTONIC_INVALID"),(float("nan"),"MONOTONIC_INVALID")):
   with self.subTest(value=value),self.assertRaisesRegex(ContractError,code):decide_answer(event,now_monotonic_ns=value)
  with self.assertRaisesRegex(ContractError,"MONOTONIC_INVALID"):self.event(mutate=lambda x:x.update(observed_monotonic_ns=1.0))
 def test_replaced_stale_and_option_drift_transitions(self):
  with self.assertRaisesRegex(ContractError,"QUESTION_REPLACED"):
   event=self.event(mutate=lambda x:x.update(replaced_by_question_id="question.synthetic.9999"));decide_answer(event,now_monotonic_ns=1_300_000_000_000)
  ledger=self.ledger();decision=self.decision(1);ledger.begin_submit(decision)
  drift=AnswerDecision(decision.job,tuple(reversed(decision.option_ids)),decision.observed_monotonic_ns)
  with self.assertRaisesRegex(ContractError,"ANSWER_BINDING_MISMATCH"):ledger.acknowledge(drift)
  changed=self.event(1,lambda x:x.update(prompt="Choose alternate local preference."));stale=decide_answer(changed,now_monotonic_ns=2_300_000_000_000)
  with self.assertRaisesRegex(ContractError,"STALE_OR_REPLACED_IDENTITY"):ledger.begin_submit(stale)
 def test_concurrent_claim_has_exactly_one_winner(self):
  ledger=self.ledger();decision=self.decision();barrier=threading.Barrier(12);wins=[];errors=[]
  def claim():
   barrier.wait()
   try:AnswerLedger(ledger.path).begin_submit(decision);wins.append(1)
   except ContractError as e:errors.append(e.code)
  threads=[threading.Thread(target=claim) for _ in range(12)]
  for t in threads:t.start()
  for t in threads:t.join()
  self.assertEqual(len(wins),1);self.assertEqual(errors.count("ANSWER_NO_REPLAY_FENCE"),11);self.assertEqual(ledger.state_for(decision),"SUBMITTING")
 def test_crash_unknown_ack_and_duplicate_tick_no_replay(self):
  decision=self.decision();ledger=self.ledger();host=SyntheticFakeHost()
  with self.assertRaisesRegex(RuntimeError,"before submit"):synthetic_roundtrip(decision,ledger,host,crash="before_submit")
  self.assertEqual(synthetic_roundtrip(decision,ledger,host),"ACKED");self.assertEqual(synthetic_roundtrip(decision,ledger,host),"ACKED");self.assertEqual(host.submit_count,1)
  ackledger=self.ledger();ackhost=SyntheticFakeHost()
  with self.assertRaisesRegex(RuntimeError,"after ack"):synthetic_roundtrip(decision,ackledger,ackhost,crash="after_ack")
  self.assertEqual(synthetic_roundtrip(decision,ackledger,ackhost),"ACKED");self.assertEqual(ackhost.submit_count,1)
  for fault,crash in (("during_submit_unknown","none"),("none","after_submit"),("after_submit_before_ack","none")):
   other=self.ledger();fake=SyntheticFakeHost(fault)
   self.assertEqual(synthetic_roundtrip(decision,other,fake,crash=crash),"UNKNOWN");self.assertEqual(synthetic_roundtrip(decision,other,fake),"UNKNOWN");self.assertEqual(fake.submit_count,1)
 def test_parent_must_preexist_be_nonsymlinked_and_identity_stable(self):
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name).resolve();parent=root/"state"
  with self.assertRaises((FileNotFoundError,ContractError)):AnswerLedger(parent/"answers.jsonl")
  with self.assertRaises((FileNotFoundError,ContractError)):AnswerLedger(parent/"nested"/"answers.jsonl")
  create_owner_private_directory(parent);ledger=AnswerLedger(parent/"answers.jsonl");ledger.begin_submit(self.decision())
  moved=root/"state-old";parent.rename(moved);create_owner_private_directory(parent)
  with self.assertRaisesRegex(ContractError,"LEDGER_PARENT_IDENTITY_DRIFT"):ledger.state_for(self.decision())
  symlink=root/"linked-state";os.symlink(moved,symlink)
  with self.assertRaises((OSError,ContractError)):AnswerLedger(symlink/"answers.jsonl")
 def test_preexisting_parent_helper_sets_exact_mode(self):
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);parent=Path(temp.name).resolve()/"state";create_owner_private_directory(parent)
  self.assertEqual(os.stat(parent,follow_symlinks=False).st_mode & 0o777,0o700)
  ledger=AnswerLedger(parent/"answers.jsonl");ledger.begin_submit(self.decision());self.assertEqual(ledger.state_for(self.decision()),"SUBMITTING")
 def test_partial_tail_truncate_symlink_and_hardlink_fail_closed(self):
  decision=self.decision();ledger=self.ledger();ledger.begin_submit(decision)
  ledger.path.write_bytes(ledger.path.read_bytes()[:-1])
  with self.assertRaisesRegex(ContractError,"LEDGER_PARTIAL_TAIL"):ledger.state_for(decision)
  ledger=self.ledger();ledger.begin_submit(decision);ledger.path.write_bytes(b"")
  with self.assertRaisesRegex(ContractError,"LEDGER_TRUNCATED"):ledger.state_for(decision)
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name).resolve();target=root/"target";target.write_text("");os.chmod(target,0o600);os.symlink(target,root/"answers.jsonl")
  with self.assertRaises((OSError,ContractError)):AnswerLedger(root/"answers.jsonl").state_for(decision)
  os.unlink(root/"answers.jsonl");os.link(target,root/"answers.jsonl")
  with self.assertRaisesRegex(ContractError,"LEDGER_FILE_UNSAFE"):AnswerLedger(root/"answers.jsonl").state_for(decision)
  os.unlink(root/"answers.jsonl");lock=root/"answers.jsonl.lock";lock.unlink(missing_ok=True);os.symlink(target,lock)
  with self.assertRaises((OSError,ContractError)):AnswerLedger(root/"answers.jsonl").state_for(decision)
  lock.unlink();os.link(target,lock)
  with self.assertRaisesRegex(ContractError,"LEDGER_FILE_UNSAFE"):AnswerLedger(root/"answers.jsonl").state_for(decision)
 def test_write_and_fsync_failures_surface(self):
  decision=self.decision()
  with mock.patch.object(ledger_module,"_write_all",side_effect=OSError("short write")):
   with self.assertRaisesRegex(OSError,"short write"):self.ledger().begin_submit(decision)
  calls=[0]
  def fail_fsync(fd):calls[0]+=1;raise OSError("fsync failure")
  with mock.patch.object(ledger_module,"_fsync",side_effect=fail_fsync):
   with self.assertRaisesRegex(OSError,"fsync failure"):self.ledger().begin_submit(decision)
 def test_secret_names_values_and_event_extras_rejected(self):
  mutations=(lambda x:x.update(access_token="x"),lambda x:x.update(prompt="Bearer abc"),lambda x:x["options"][0].update(description="private key material"),lambda x:x["authority"].update(auth="x"))
  for mutation in mutations:
   with self.assertRaises(ContractError):self.event(mutate=mutation)
 def test_source_and_evidence_closure(self):
  source=load_source_closure();self.assertEqual(verify_source_closure(PACKAGE,source),source["closure_sha256"])
  evidence=load_evidence_manifest();self.assertEqual(verify_evidence_manifest(ROOT,evidence),evidence["evidence_sha256"])
if __name__=="__main__":unittest.main()
