from copy import deepcopy
import json
from pathlib import Path
import unittest
from jsonschema import Draft202012Validator


class InformationLabelTests(unittest.TestCase):
    def setUp(self):
        schema=json.loads((Path(__file__).parents[1]/'information-labels.schema.json').read_text())
        Draft202012Validator.check_schema(schema);self.validator=Draft202012Validator(schema)
        ref={'path':'synthetic/source.json','sha256':'a'*64}
        self.document={'schema_version':1,'source_ref':ref,'claim_ref':None,'scope':'document',
            'publisher_kind':'sell_side','perspectives':['market'],'document_type':'analyst_report',
            'topics':['financial.performance','business.model'],'epistemic_status':'mixed',
            'annotation':{'method':'model','status':'provisional','policy_version':'synthetic-1','review_ref':None},
            'limitations':['Synthetic schema check; source support and review authenticity are not established.']}

    def test_mixed_analyst_report_can_contain_reported_actual_and_subjective_estimate(self):
        self.assertTrue(self.validator.is_valid(self.document))
        for status in ['reported_actual','analyst_estimate','author_opinion']:
            claim={**self.document,'scope':'claim','claim_ref':{'path':'synthetic/claim.json','sha256':'b'*64},
                   'epistemic_status':status}
            with self.subTest(status=status):self.assertTrue(self.validator.is_valid(claim))

    def test_issuer_origin_does_not_force_a_forecast_to_be_an_actual(self):
        claim={**self.document,'publisher_kind':'issuer','document_type':'earnings_release','scope':'claim',
            'claim_ref':{'path':'synthetic/forecast.json','sha256':'c'*64},'epistemic_status':'management_target'}
        self.assertTrue(self.validator.is_valid(claim))
        for changes in [{'epistemic_status':'mixed'},{'claim_ref':None},
                        {'annotation':{**claim['annotation'],'status':'reviewed'}}]:
            with self.subTest(changes=changes):self.assertFalse(self.validator.is_valid({**claim,**changes}))


if __name__=='__main__':unittest.main()
