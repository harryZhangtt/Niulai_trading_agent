"""Offline integrity and negative controls for the inert LLM engineering corpus."""
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SPEC=importlib.util.spec_from_file_location('llmk_validate',ROOT/'mentor/references/llm-engineering/validate.py')
MOD=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(MOD)
PACKAGE=ROOT/'mentor/references/llm-engineering'

class LLMEngineeringReferenceTests(unittest.TestCase):
    def copy(self):
        td=tempfile.TemporaryDirectory(); dst=Path(td.name)/'corpus'; shutil.copytree(PACKAGE,dst); return td,dst
    def mutate(self,dst,name,fn):
        path=dst/name; value=json.loads(path.read_text()); fn(value); path.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    def codes(self,dst): return {e['code'] for e in MOD.validate(dst)}
    def test_real_candidate_validates(self): self.assertEqual(MOD.validate(PACKAGE),[])
    def test_private_locator_rejected(self):
        td,dst=self.copy(); self.addCleanup(td.cleanup); self.mutate(dst,'source-ledger.json',lambda v:v['sources'][1]['locator'].update({'kind':'url','value':'https://bytetech.info/articles/x?message_id=1'})); self.assertIn('LLMK_PRIVATE_LOCATOR',self.codes(dst))
    def test_unknown_claim_rejected(self):
        td,dst=self.copy(); self.addCleanup(td.cleanup); self.mutate(dst,'knowledge-cards.json',lambda v:v['cards'][0]['source_claim_ids'].append('CLM-MISSING')); self.assertIn('LLMK_REFERENCE_UNKNOWN',self.codes(dst))
    def test_runtime_ready_rejected(self):
        td,dst=self.copy(); self.addCleanup(td.cleanup); self.mutate(dst,'knowledge-cards.json',lambda v:v['cards'][0].update({'readiness':'runtime_ready'})); self.assertIn('LLMK_REVIEW_REQUIRED',self.codes(dst))
    def test_cost_and_catalog_drift_rejected(self):
        td,dst=self.copy(); self.addCleanup(td.cleanup); self.mutate(dst,'knowledge-cards.json',lambda v:v['cards'][0]['context_cost'].update({'body_utf8_bytes':1})); codes=self.codes(dst); self.assertIn('LLMK_CONTEXT_COST_MISMATCH',codes); self.assertIn('LLMK_CATALOG_PROJECTION_MISMATCH',codes)
    def test_guide_drift_rejected(self):
        td,dst=self.copy(); self.addCleanup(td.cleanup); p=dst/'guide.md'; p.write_text(p.read_text().replace('KC-EVIDENCE-001','KC-DRIFT',1)); self.assertIn('LLMK_GUIDE_PROJECTION_MISMATCH',self.codes(dst))
    def test_duplicate_json_key_rejected(self):
        td,dst=self.copy(); self.addCleanup(td.cleanup); p=dst/'catalog.json'; p.write_text('{"schema_version":1,"schema_version":1}\n'); self.assertIn('LLMK_DUPLICATE_KEY',self.codes(dst))
    def test_decision_contract_is_bound_and_inert(self):
        contract=json.loads((PACKAGE/'decision-contract.json').read_text())
        self.assertFalse(contract['active'])
        self.assertEqual(contract['release_state'],'candidate')
        self.assertLessEqual((PACKAGE/'decision-contract.json').stat().st_size,4096)
        catalog=json.loads((PACKAGE/'catalog.json').read_text())
        self.assertEqual(catalog['decision_contract']['path'],'decision-contract.json')
    def test_active_boundary_unchanged(self):
        spec=importlib.util.spec_from_file_location('mentor_session_init',ROOT/'mentor/session_init.py'); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        self.assertEqual(tuple(mod.CORE),('mentor/AGENTS.md','mentor/ROUTING.md'))
        self.assertEqual(set(mod.SKILLS),set(MOD.ROUTES))
        for rel in ('mentor/AGENTS.md','mentor/ROUTING.md','mentor/session_init.py'):
            self.assertNotIn('mentor/references/llm-engineering',(ROOT/rel).read_text())
if __name__=='__main__': unittest.main()
