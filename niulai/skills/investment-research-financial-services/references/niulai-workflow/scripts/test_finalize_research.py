"""Test actual-format binding/finalization mechanics with synthetic artifacts."""
import copy
import json
from pathlib import Path
import unittest
import test_research_completion as fixture_module
import finalize_research as f

class FinalizeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture_module.CompletionTests();self.fixture.setUp();self.root=self.fixture.root
        rec=self.fixture.rec;arts={a['id']:a for a in rec['artifacts']}
        self.review={'ticker':'AAA','reviewer_id':'reviewer','status':'approved_scoped_decision',
            'source_review':'complete','reasoning_review':'complete','reviewed_artifact_ids':['review-output','review-report'],
            'artifact_hashes':{Path(arts[a]['path']).name:arts[a]['sha256'] for a in ['outputs','report']},
            'factual_samples':copy.deepcopy(rec['audit']['factual_samples']),
            'numerical_checks':copy.deepcopy(rec['audit']['numerical_checks']),'findings':[]}
        self.review_path=self.root/'real_review_fixture.json';self.review_path.write_text(json.dumps(self.review))
        self.bindings={'reviewer_id':'reviewer','review_sha256':f.ref(self.review_path)['sha256'],
            'artifact_aliases':{'review-output':'outputs','review-report':'report'},
            'factual_sample_bindings':[{'index':0,'claim_id':'c1','source_id':'s1','passage_id':'p1'}],
            'review_command_receipt':{'path':arts['cmd']['path'],'sha256':arts['cmd']['sha256']},'extra_artifacts':[]}
        self.bindings_path=self.root/'bindings.json';self.bindings_path.write_text(json.dumps(self.bindings))
        self.item_path=self.root/'item.json';self.item_path.write_text(json.dumps({'ticker':'AAA','action':'wait'}))
        self.request={'record':str(self.root/'record.json'),'item':str(self.item_path),'review':str(self.review_path),
            'bindings':str(self.bindings_path),'run_id':'run1','input_hash':'inputs','publications':[{'artifact_id':'report',
            'receipt':str(self.root/'receipt.json'),'readback':arts['report']['path'],'confirmed_at':fixture_module.fixtures.STAMP}]}
        self.out=self.root/'finalized'
    def tearDown(self):self.fixture.tearDown()
    def test_same_inputs_repeat_byte_identical_author_unchanged(self):
        before=Path(self.request['record']).read_bytes();a=f.assemble(self.request,self.out)
        record=Path(a['record']['path']).read_bytes();b=f.assemble(self.request,self.out)
        self.assertEqual(a,b);self.assertEqual(record,Path(b['record']['path']).read_bytes());self.assertEqual(before,Path(self.request['record']).read_bytes())
    def save_review(self):
        self.review_path.write_text(json.dumps(self.review))
        self.bindings['review_sha256']=f.ref(self.review_path)['sha256']
        self.bindings_path.write_text(json.dumps(self.bindings))
    def add_same_basename(self):
        arts={a['id']:a for a in self.fixture.rec['artifacts']}
        path=self.root/'nested'/Path(arts['outputs']['path']).name
        path.parent.mkdir();path.write_text('distinct reviewed underlying output')
        self.bindings['extra_artifacts'].append({'id':'underlying-output',**f.ref(path),'kind':'other','depends_on':[]})
        self.review['reviewed_artifact_ids'].append('underlying-output')
        self.review['artifact_hashes']={i:arts[i]['sha256'] for i in ['outputs','report']}
        self.review['artifact_hashes']['underlying-output']=f.ref(path)['sha256']
        return arts
    def test_distinct_same_basename_pinned_by_exact_ids(self):
        self.add_same_basename();self.save_review()
        self.assertEqual(f.assemble(self.request,self.out)['status'],'complete')
    def test_legacy_unique_basename_still_accepted(self):
        self.assertEqual(f.assemble(self.request,self.out)['status'],'complete')
    def test_ambiguous_legacy_basename_rejected_even_if_hash_matches(self):
        arts=self.add_same_basename()
        self.review['artifact_hashes'][Path(arts['outputs']['path']).name]=self.review['artifact_hashes'].pop('outputs')
        self.save_review()
        with self.assertRaisesRegex(ValueError,'Ambiguous review artifact basename'):f.assemble(self.request,self.out)
    def test_unknown_id_rejected(self):
        self.review['artifact_hashes']['nonexistent-artifact']=next(iter(self.review['artifact_hashes'].values()))
        self.save_review()
        with self.assertRaisesRegex(ValueError,'Unresolved review artifact hash key'):f.assemble(self.request,self.out)
    def test_exact_id_cannot_pin_other_artifact_hash(self):
        self.add_same_basename()
        self.review['artifact_hashes']['outputs']=self.review['artifact_hashes']['underlying-output']
        self.save_review()
        with self.assertRaisesRegex(ValueError,'Review is stale for outputs'):f.assemble(self.request,self.out)
    def test_equal_hash_does_not_pin_unlisted_artifact_id(self):
        arts={a['id']:a for a in self.fixture.rec['artifacts']}
        self.bindings['extra_artifacts'].append({**arts['outputs'],'id':'same-content-other-id'})
        self.review['artifact_hashes']={'same-content-other-id':arts['outputs']['sha256'],'report':arts['report']['sha256']}
        self.save_review()
        with self.assertRaisesRegex(ValueError,'Reviewed artifact hash is not pinned'):f.assemble(self.request,self.out)

    def test_new_entry_policy_missing_comparison_cannot_finalize(self):
        rec=json.loads(Path(self.request['record']).read_text())
        rec['policy_versions']['entry_policy']='2026-10-23-entry-policy-2'
        Path(self.request['record']).write_text(json.dumps(rec))
        with self.assertRaisesRegex(ValueError,'entry_policy_evidence missing'):
            f.assemble(self.request,self.out)

    def test_equity_options_profile_cannot_finalize_without_options_package(self):
        rec=json.loads(Path(self.request['record']).read_text())
        rec['instrument_profile']='equity_options'
        Path(self.request['record']).write_text(json.dumps(rec))
        with self.assertRaisesRegex(ValueError,'Options evidence'):
            f.assemble(self.request,self.out)

    def test_new_report_cannot_finalize_without_visual_rationale(self):
        rec=json.loads(Path(self.request['record']).read_text())
        rec['valuation_evidence']={'version':'2026-10-20-valuation-evidence-1',**{k:{'status':'evidenced','finding':'Synthetic fixture only.','artifact_refs':['outputs']} for k in ['business_values','forecast_validation','probability_basis','professional_research','technical_confirmation']}}
        Path(self.request['record']).write_text(json.dumps(rec))
        self.request['publications'][0]['confirmed_at']='2026-10-24T00:00:00Z'
        with self.assertRaisesRegex(ValueError,'rationale policy'):
            f.assemble(self.request,self.out)

    def test_backdated_confirmation_cannot_hide_actual_new_save(self):
        (self.root/'receipt.json').write_text(json.dumps({'status':'succeeded','library_file_id':'libfile_synthetic','current_version_number':1,'modified_at':'2026-10-24T00:00:00Z'}))
        with self.assertRaisesRegex(ValueError,'rationale policy'):
            f.assemble(self.request,self.out)

    def test_actual_new_save_requires_critical_input_evidence(self):
        (self.root/'receipt.json').write_text(json.dumps({'status':'succeeded','library_file_id':'libfile_synthetic','current_version_number':1,'modified_at':'2026-10-24T00:11:00Z'}))
        with self.assertRaisesRegex(ValueError,'Critical data'):
            f.assemble(self.request,self.out)

    def test_missing_fixed_confirmation_rejected(self):
        self.request['publications'][0].pop('confirmed_at')
        with self.assertRaisesRegex(ValueError,'confirmed_at'):f.assemble(self.request,self.out)
    def test_stale_binding_rejected_preserves_prior_output(self):
        valid=f.assemble(self.request,self.out);before=Path(valid['record']['path']).read_bytes()
        self.review['status']='incomplete';self.review_path.write_text(json.dumps(self.review))
        with self.assertRaisesRegex(ValueError,'Binding/review mismatch'):f.assemble(self.request,self.out)
        self.assertEqual(before,Path(valid['record']['path']).read_bytes())
    def test_unresolved_semantic_binding_not_guessed(self):
        self.bindings['factual_sample_bindings'][0]['claim_id']='human prose label'
        self.bindings_path.write_text(json.dumps(self.bindings))
        with self.assertRaisesRegex(ValueError,'Unresolved reviewed fact'):f.assemble(self.request,self.out)
    def test_changed_artifact_not_silently_rehashed(self):
        rec=self.fixture.rec;Path(rec['artifacts'][0]['path']).write_text('changed after review')
        with self.assertRaisesRegex(ValueError,'hash mismatch'):f.assemble(self.request,self.out)
    def test_false_receipt_cannot_finalize(self):
        (self.root/'receipt.json').write_text(json.dumps({'status':'failed','library_file_id':'libfile_synthetic','current_version_number':1}))
        with self.assertRaisesRegex(ValueError,'No successful actual'):f.assemble(self.request,self.out)
    def test_prepare_without_publication_remains_partial(self):
        self.request['publications']=[];out=f.assemble(self.request,self.out)
        self.assertEqual(out['status'],'partial');self.assertEqual(json.loads(Path(out['record']['path']).read_text())['status'],'in_progress')
    def test_missing_artifact_alias_rejected(self):
        self.bindings['artifact_aliases'].pop('review-output');self.bindings_path.write_text(json.dumps(self.bindings))
        with self.assertRaisesRegex(ValueError,'Unresolved reviewer artifact'):f.assemble(self.request,self.out)

if __name__=='__main__':unittest.main()
