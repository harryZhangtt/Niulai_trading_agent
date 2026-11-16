import copy
import json
from pathlib import Path
import unittest

from factor.source_inventory import corporate_actions as ca
from factor.source_inventory.tests.schema_helper import accepts

ROOT=Path(__file__).resolve().parents[1]
RESPONSE=ROOT/'fixtures/synthetic-corporate-actions-response-v1.json'
RECEIPT=ROOT/'fixtures/synthetic-corporate-actions-receipt-v1.json'
REQUEST=ROOT/'fixtures/synthetic-total-return-request-v1.json'


class CorporateActionTests(unittest.TestCase):
    def setUp(self):
        self.response=json.loads(RESPONSE.read_text())
        self.receipt=json.loads(RECEIPT.read_text())
        self.request=json.loads(REQUEST.read_text())
        self.closes=[{'session_date':'2026-01-02','unadjusted_close':'100'},
                     {'session_date':'2026-01-05','unadjusted_close':'102'},
                     {'session_date':'2026-01-06','unadjusted_close':'52'},
                     {'session_date':'2026-01-07','unadjusted_close':'53'}]
        self.action_values={'div-event':{'amount':'1','split_ratio':None},
                            'split-event':{'amount':None,'split_ratio':'2'}}

    def test_latest_correction_and_cancel_selection_at_cutoff(self):
        receipt=ca.normalize_response(self.response)
        early=ca.select_actions_as_of(receipt,'2026-01-02T10:00:00Z')
        final=ca.select_actions_as_of(receipt,'2026-01-10T00:00:00Z')
        self.assertEqual(next(row for row in early if row['event_unique_id']=='div-event')['event_action'],'new')
        self.assertEqual(next(row for row in final if row['event_unique_id']=='div-event')['event_action'],'correct')
        self.assertEqual({row['event_unique_id'] for row in final},{'div-event','split-event'})
        self.assertNotIn('cancel-event',{row['event_unique_id'] for row in final})

    def test_same_recorded_time_uses_native_record_and_cancel_order(self):
        response=copy.deepcopy(self.response)
        for row in response["records"]: row["recorded_at"]="2026-01-10T00:00:00Z"
        receipt=ca.normalize_response(response)
        selected=ca.select_actions_as_of(receipt,"2026-01-10T00:00:00Z")
        self.assertEqual(next(row for row in selected if row["event_unique_id"]=="div-event")["event_action"],"correct")
        self.assertNotIn("cancel-event",{row["event_unique_id"] for row in selected})

    def test_exact_duplicate_dedupes_but_same_key_conflict_fails(self):
        duplicate=copy.deepcopy(self.response)
        exact=copy.deepcopy(duplicate["records"][1]); exact["record_id"]="div-duplicate"
        duplicate["records"].append(exact)
        receipt=ca.normalize_response(duplicate)
        self.assertEqual(len(receipt["normalized_actions"]),5)
        conflict=copy.deepcopy(duplicate); conflict["records"][-1]["source_row_sha256"]="e"*64
        with self.assertRaisesRegex(ca.CorporateActionError,"VERSION_AMBIGUOUS"):
            ca.validate_response(conflict)

    def test_post_cutoff_correction_does_not_change_earlier_selection(self):
        base=ca.normalize_response(self.response)
        changed=copy.deepcopy(self.response)
        later=copy.deepcopy(changed['records'][1])
        later.update(record_id='div-r3',event_action='correct',ts_record='2026-01-11T10:00:00Z',
                     recorded_at='2026-01-11T10:00:00Z',amount_commitment_sha256=ca.digest({'amount':'2'}),
                     source_row_sha256='f'*64)
        changed['records'].append(later); receipt=ca.normalize_response(changed)
        self.assertEqual(ca.select_actions_as_of(base,'2026-01-10T00:00:00Z'),
                         ca.select_actions_as_of(receipt,'2026-01-10T00:00:00Z'))
        selected=ca.select_actions_as_of(receipt,'2026-01-12T00:00:00Z')
        self.assertEqual(next(row for row in selected if row['event_unique_id']=='div-event')['amount_commitment_sha256'],
                         ca.digest({'amount':'2'}))

    def test_ticker_splice_missing_ids_and_receipts_fail(self):
        splice=copy.deepcopy(self.response); splice['records'][1]['listing_id']='other-listing'
        with self.assertRaisesRegex(ca.CorporateActionError,'TICKER_SPLICE'):
            ca.validate_response(splice)
        missing=copy.deepcopy(self.response); del missing['records'][0]['event_unique_id']
        with self.assertRaisesRegex(ca.CorporateActionError,'ROW_SCHEMA'):
            ca.validate_response(missing)
        no_receipt=copy.deepcopy(self.response); no_receipt['acquisition_receipt_sha256']=None
        with self.assertRaises(ca.CorporateActionError): ca.validate_response(no_receipt)

    def test_total_return_output_commitment_is_recomputable_but_value_free(self):
        receipt=ca.compute_total_return_receipt(self.request,self.receipt,
                                                self.closes,self.action_values)
        repeated=ca.compute_total_return_receipt(copy.deepcopy(self.request),
                                                 copy.deepcopy(self.receipt),
                                                 copy.deepcopy(self.closes),
                                                 copy.deepcopy(self.action_values))
        self.assertEqual(receipt,repeated)
        self.assertEqual(receipt['output_rows'],4)
        expected_rows=[
            {'session_date':'2026-01-02','total_return_index':'1'},
            {'session_date':'2026-01-05','total_return_index':'1.03'},
            {'session_date':'2026-01-06','total_return_index':'1.050196078431372549019607843137255'},
            {'session_date':'2026-01-07','total_return_index':'1.07039215686274509803921568627451'},
        ]
        self.assertEqual(receipt['output_commitment_sha256'],ca.digest(expected_rows))
        self.assertFalse(receipt['values_included'])
        self.assertEqual(receipt['performance_claim'],'withheld')
        self.assertNotIn('total_return_index',json.dumps(receipt))

    def test_adjusted_input_formula_and_action_value_drift_fail(self):
        adjusted=copy.deepcopy(self.request); adjusted['adjusted_input_allowed']=True
        with self.assertRaisesRegex(ca.CorporateActionError,'REQUEST_INVALID'):
            ca.validate_total_return_request(adjusted)
        formula=copy.deepcopy(self.request); formula['formula_version']='formula-v2'
        with self.assertRaisesRegex(ca.CorporateActionError,'REQUEST_INVALID'):
            ca.validate_total_return_request(formula)
        wrong=copy.deepcopy(self.action_values); wrong['div-event']['amount']='9'
        with self.assertRaisesRegex(ca.CorporateActionError,'VALUE_COMMITMENT_MISMATCH'):
            ca.compute_total_return_receipt(self.request,self.receipt,self.closes,wrong)
        closes=copy.deepcopy(self.closes); closes[0]['unadjusted_close']='99'
        with self.assertRaisesRegex(ca.CorporateActionError,'CLOSE_COMMITMENT_MISMATCH'):
            ca.compute_total_return_receipt(self.request,self.receipt,closes,self.action_values)

    def test_exact_schemas_accept_tracked_value_free_fixtures_and_receipt(self):
        names=['corporate-action-response-v1.schema.json','corporate-action-receipt-v1.schema.json',
               'total-return-request-v1.schema.json','total-return-receipt-v1.schema.json']
        schemas={name:json.loads((ROOT/name).read_text()) for name in names}
        self.assertTrue(accepts(self.response,schemas[names[0]]))
        self.assertTrue(accepts(self.receipt,schemas[names[1]]))
        self.assertTrue(accepts(self.request,schemas[names[2]]))
        output=ca.compute_total_return_receipt(self.request,self.receipt,
                                               self.closes,self.action_values)
        self.assertTrue(accepts(output,schemas[names[3]]))
        tracked=''.join(path.read_text() for path in (RESPONSE,RECEIPT,REQUEST))
        self.assertNotIn('"amount":',tracked)
        self.assertNotIn('"split_ratio":',tracked)
        self.assertNotIn('"unadjusted_close":',tracked)
        for schema in schemas.values():
            self.assertEqual(set(schema['required']),set(schema['properties']))


if __name__=='__main__': unittest.main()
