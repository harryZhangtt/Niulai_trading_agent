import copy, unittest
from decimal import Decimal as D
from fractions import Fraction as F
from analytics import build

def fixture():
    rows=[dict(symbol='X',currency='USD',marketValue='60',unrealizedPnl='5',dailyPnl=None),dict(symbol='Y',currency='USD',marketValue='40',unrealizedPnl='-2',dailyPnl=None)]
    h={'accountResults':[dict(accountRef='a',accountIdentityChecked=True,ok=True,sourceReadStatus='complete',positions=rows,sourceAccountMetadata={'account_type':'STANDARD'})]}
    a={'accountResults':[dict(accountRef='a',accountIdentityChecked=True,ok=True,sourceReadStatus='complete',summary={'currency':'USD','amounts':{'netLiquidation':'125','cash':'25','buyingPower':'500'}})]}
    t={'positions':{'X':dict(primary_sector='半导体',subindustry='存储',daily_leverage=2,underlying='X',themes=['AI','存储']), 'Y':dict(primary_sector='软件',subindustry='订阅',daily_leverage=1,underlying='Y',themes=['AI'])}}
    return h,a,t
class AnalyticsTests(unittest.TestCase):
    def result(self,h=None,a=None,t=None):
        hh,aa,tt=fixture();return build(h or hh,a or aa,t or tt)['accounts'][0]
    def test_cash_not_buying_power(self):
        m=self.result()['metrics'];self.assertEqual(m['cash_pct'],20);self.assertEqual(m['positions_nav_pct'],80);self.assertEqual(m['other_net_assets'],0)
    def test_concentration_independent_fraction(self):
        m=self.result()['metrics'];q=F(3,5)**2+F(2,5)**2
        self.assertEqual(m['hhi'],D(q.numerator)/D(q.denominator)*10000);self.assertAlmostEqual(float(m['effective_n']),float(1/q));self.assertEqual(m['top5_pct'],100)
    def test_embedded_and_broker_not_same(self):
        m=self.result()['metrics'];self.assertEqual(m['gross_nav_multiple'],D('.8'));self.assertEqual(m['embedded_gross_nav_multiple'],D('1.28'));self.assertEqual(m['leveraged_capital_pct'],60)
    def test_no_fake_daily(self):
        r=self.result();self.assertEqual(r['metrics']['unrealized_pnl'],3);self.assertIsNone(r['metrics']['daily_pnl']);self.assertEqual(r['daily_top_gainers'],[])
    def test_partition_and_overlap(self):
        r=self.result();self.assertEqual(sum(x['pct'] for x in r['sector_breakdown']),100);self.assertGreater(sum(x['pct'] for x in r['themes']),100)
    def test_missing_leverage_preserves_unknown(self):
        h,a,t=fixture();t['positions']['X']['daily_leverage']=None;r=self.result(h,a,t);self.assertEqual(r['metrics']['leverage_coverage_pct'],40);self.assertIsNone(r['metrics']['embedded_gross_nav_multiple'])
    def test_short_signed_net_abs_gross(self):
        h,a,t=fixture();h['accountResults'][0]['positions'][1]['marketValue']='-40';r=self.result(h,a,t);self.assertEqual(r['metrics']['positions_value'],20);self.assertEqual(r['metrics']['gross_positions_value'],100);self.assertEqual(r['metrics']['embedded_net_nav_multiple'],D('.64'))
    def test_no_identity_match(self):
        h,a,t=fixture();a['accountResults'][0]['accountRef']='other';self.assertIsNone(self.result(h,a,t)['metrics']['nav'])
    def test_wrong_currency_does_not_convert(self):
        h,a,t=fixture();a['accountResults'][0]['summary']['currency']='HKD';self.assertIsNone(self.result(h,a,t)['metrics']['cash_pct'])
    def test_unknown_currency_not_aggregated(self):
        h,a,t=fixture()
        for p in h['accountResults'][0]['positions']:p['currency']=None
        r=self.result(h,a,t);self.assertIsNone(r['metrics']['positions_value']);self.assertEqual(r['sector_breakdown'],[])
    def test_failed_read_not_empty(self):
        h,a,t=fixture();h['accountResults'][0].update(positions=None,ok=False,sourceReadStatus='failed');r=self.result(h,a,t);self.assertIsNone(r['metrics']['positions_value']);self.assertIsNone(r['metrics']['unrealized_pnl'])
    def test_empty_success_is_zero(self):
        h,a,t=fixture();h['accountResults'][0]['positions']=[];r=self.result(h,a,t);self.assertEqual(r['metrics']['positions_value'],0);self.assertIsNone(r['metrics']['hhi'])
    def test_missing_mv_not_full_hhi(self):
        h,a,t=fixture();h['accountResults'][0]['positions'][0]['marketValue']=None;r=self.result(h,a,t);self.assertIsNone(r['metrics']['hhi']);self.assertIsNone(r['metrics']['gross_nav_multiple'])
    def test_paper_not_combined(self):
        h,a,t=fixture();p=copy.deepcopy(h['accountResults'][0]);p.update(accountRef='p',positions=[],sourceAccountMetadata={'account_type':'PAPER'});h['accountResults'].append(p);r=build(h,a,t);self.assertEqual(len(r['accounts']),2);self.assertEqual(r['accounts'][0]['metrics']['nav'],125);self.assertIsNone(r['accounts'][1]['metrics']['nav'])
if __name__=='__main__': unittest.main()
