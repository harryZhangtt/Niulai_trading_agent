import unittest
from research_triage import route, envelope_test
class Routing(unittest.TestCase):
    def setUp(self): self.b=dict(ticker="TEST",identity_verified=True,in_scope=True,quote_valid=True,baseline_valid=True,delta_scan_complete=True,material_new_evidence=False,price_or_time_changed=False,evidence_refs={k:['fixture:'+k] for k in ('baseline','delta_scan','quote','identity','envelope','capital_claims','independent_review')})
    def test_no_provenance_no_reuse(self): self.assertEqual(route(dict(self.b,evidence_refs={}))['route'],'bounded_probe')
    def test_risk_before_mapping(self): self.assertEqual(route(dict(self.b,identity_verified=False,held_position=True,material_risk_event=True))['route'],'priority_risk_review')
    def test_envelope_calculated(self):
        x=dict(self.b,optimistic_envelope_reviewed=True,optimistic_envelope=dict(price=100,terminal_wealth_per_share=110,years=2,required_annual_return=.1,option_value_considered=True,claims_reconciled=True))
        r=route(x)
        self.assertEqual(r['route'],'defer_price')
        self.assertAlmostEqual(r['calculation']['reopen_price'],110/1.1**2)
        x['optimistic_envelope']['terminal_wealth_per_share']=200
        self.assertEqual(route(x)['route'],'reuse')
    def test_invalid_envelope_not_reject(self):
        for bad in (float('nan'),float('inf'),True,-1):
            x=dict(self.b,optimistic_envelope_reviewed=True,optimistic_envelope=dict(price=bad,terminal_wealth_per_share=110,years=2,required_annual_return=.1,option_value_considered=True,claims_reconciled=True))
            self.assertIsNone(envelope_test(x))
            self.assertNotEqual(route(x)['route'],'defer_price')
    def test_unknown(self): self.assertEqual(route({})["route"],"data_repair")
    def test_unchanged(self): self.assertEqual(route(self.b)["route"],"reuse")
    def test_price(self): self.assertEqual(route(dict(self.b,price_or_time_changed=True))["route"],"reprice")
    def test_hold(self): self.assertEqual(route(dict(self.b,user_hold=True))["route"],"held")
    def test_risk_overrides_price(self): self.assertEqual(route(dict(self.b,held_position=True,material_risk_event=True,envelope_below_hurdle=True))["route"],"priority_risk_review")
    def test_no_baseline(self): self.assertEqual(route(dict(self.b,baseline_valid=False))["route"],"bounded_probe")
    def test_new_evidence(self): self.assertEqual(route(dict(self.b,material_new_evidence=True))["route"],"delta_review")
    def test_fund(self): self.assertEqual(route(dict(self.b,leveraged_fund=True))["route"],"fund_path_refresh")
    def test_new_regime(self): self.assertEqual(route(dict(self.b,regime_changed=True))["route"],"full_review")
    def test_no_unverified_optimistic_veto(self): self.assertEqual(route(dict(self.b,envelope_below_hurdle=True))["route"],"reuse")
    def test_no_ratio_veto(self): self.assertEqual(route(dict(self.b,pe=1000,fcf=-100,sbc_ratio=.8))["route"],"reuse")
    def test_missing_news_not_unchanged(self): self.assertEqual(route(dict(self.b,material_new_evidence=None))["route"],"delta_review")
if __name__=="__main__":unittest.main()
