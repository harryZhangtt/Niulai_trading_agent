from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from shared.research_sources.artifacts import SOURCE_STATE,save,SourceError
from tuning.evals.now_contribution.grade import grade,DIMENSIONS


class ContentBindingTests(unittest.TestCase):
    def test_neutral_copy_accepted_but_changed_or_corrupt_content_rejected(self):
        parent=SOURCE_STATE/'tmp';parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as tmp:
            root=Path(tmp);proposal={'observed_facts':[{'evidence_id':'e1'}]}
            original=save(root/'author',proposal);neutral=save(root/'blind',proposal)
            self.assertNotEqual(original['path'],neutral['path'])
            execution=save(root,{'status':'succeeded','receipt':{'turn_completed':True,'usage':None}})
            packet=save(root,{'question':'synthetic'})
            result=save(root,{'case_id':'synthetic','packet_ref':packet,'proposal_ref':original,
                              'model_execution_refs':[execution]})
            review={'case_id':'synthetic','proposal_ref':neutral,'reviewer_role':'arm_label_blinded_source_review',
                'scores':{k:2 for k in DIMENSIONS},'source_checks':[{'fact_index':0,'evidence_id':'e1','support':'supported'}],
                'rationale':'Synthetic boundary test, not economic validation.','critical_error_count':0,'critical_errors':[],
                'unsupported_inferences':0,'false_novelty':0,'unsupported_forecast_revision':0}
            def check(value):return grade('synthetic',{'packet_ref':packet},{},
                {'case_result_ref':result,'review_ref':save(root,value)})
            self.assertTrue(check(review)['passed'])
            changed=deepcopy(review);changed['proposal_ref']=save(root/'blind',{'observed_facts':[]})
            with self.assertRaisesRegex(SourceError,'NOW_REVIEW_BINDING'):check(changed)
            Path(neutral['path']).write_bytes(b'corrupt anonymous copy')
            with self.assertRaisesRegex(SourceError,'ARTIFACT_HASH_MISMATCH'):check(review)


if __name__=='__main__':unittest.main()
