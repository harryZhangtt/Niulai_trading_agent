import copy
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import niulai_tiger as app

class AssetsTests(unittest.TestCase):
    def standard(self):
        return {'items':[{'account':'synthetic', 'currency':'USD', 'netLiquidation':Decimal('100.10'), 'cashValue':Decimal('20.10'), 'buyingPower':800,
                          'segments':{'S':{'grossPositionValue':80, 'cashValue':Decimal('20.10'), 'leverage':Decimal('.7992007992')}},
                          'marketValues':{'USD':{'cashBalance':20}, 'HKD':{'cashBalance':800}}}]}
    def test_summary_cash_not_buying_power_and_decimal_exact(self):
        r=app.normalize_assets(self.standard(),'synthetic','assets')
        self.assertEqual(r['summary']['amounts']['cash'],'20.1')
        self.assertEqual(r['summary']['amounts']['buyingPower'],'800')
        self.assertEqual(r['summary']['amounts']['netLiquidation'],'100.1')
        self.assertEqual(r['summary']['sourceFields']['cash'],'cashValue')
    def test_currency_and_segments_not_aggregated_or_guessed(self):
        r=app.normalize_assets(self.standard(),'synthetic','assets')
        self.assertEqual([v['currency'] for v in r['currencyAssets']],['USD','HKD'])
        self.assertEqual(r['currencyAssets'][1]['amounts']['cash'],'800')
        self.assertIsNone(r['segments'][0]['currency'])
    def test_zero_negative_unknown_distinct(self):
        r=app.normalize_asset_block({'currency':'USD','cashValue':0,'netLiquidation':-10})
        self.assertEqual(r['amounts']['cash'],'0'); self.assertEqual(r['amounts']['netLiquidation'],'-10')
        self.assertIsNone(r['amounts']['reportedLoanValue'])
    def test_invalid_numbers_not_become_zero(self):
        r=app.normalize_asset_block({'cashValue':float('inf'),'netLiquidation':True})
        self.assertIsNone(r['amounts']['cash']); self.assertIsNone(r['amounts']['netLiquidation'])
        self.assertCountEqual(r['invalidFields'],['cashValue','netLiquidation'])
    def test_account_mismatch_and_count_rejected(self):
        with self.assertRaisesRegex(app.ReadOnlyError,'ASSET_ACCOUNT_MISMATCH'): app.normalize_assets(self.standard(),'other','assets')
        d=self.standard(); d['items']*=2
        with self.assertRaisesRegex(app.ReadOnlyError,'ASSET_ACCOUNT_COUNT_MISMATCH'): app.normalize_assets(d,'synthetic','assets')
    def test_prime_keeps_segments_without_synthetic_account_total(self):
        d={'accountId':'synthetic','updateTimestamp':1234,'segments':[{'category':'S','currency':'USD','cashBalance':20,'netLiquidation':100,'totalTodayPl':2,'currencyAssets':[{'currency':'HKD','cashBalance':1}]}]}
        r=app.normalize_assets(d,'synthetic','prime_assets')
        self.assertIsNone(r['summary']); self.assertEqual(r['segments'][0]['amounts']['reportedTodayPnl'],'2')
        self.assertEqual(r['currencyAssets'][0]['category'],'S'); self.assertEqual(r['sourceUpdateTime'],'1234')
    def test_conflicting_aliases_rejected(self):
        with self.assertRaisesRegex(app.ReadOnlyError,'CONFLICTING_ASSET_ALIASES'): app.normalize_asset_block({'cashValue':1,'cashBalance':2})
    def test_pnl_periods_stay_separate(self):
        r=app.normalize_asset_block({'todayPnl':5,'realizedPnL':3,'unrealizedPnL':100})
        self.assertEqual(r['amounts']['reportedTodayPnl'],'5'); self.assertEqual(r['amounts']['reportedRealizedPnl'],'3'); self.assertEqual(r['amounts']['reportedUnrealizedPnl'],'100')
        r=app.normalize_asset_block({'unrealizedPnL':100}); self.assertIsNone(r['amounts']['reportedTodayPnl'])
    def test_positions_today_not_inferred_and_original_security_fields_preserved(self):
        base={'account':'synthetic','symbol':'TEST','secType':'STK','currency':'USD','positionQty':2,'unrealizedPnl':100}
        r=app.normalize_items([base],'synthetic')[0]
        self.assertIsNone(r['reportedTodayPnl']); self.assertEqual(r['unrealizedPnl'],'100')
        r=app.normalize_items([{**base,'todayPnl':-4,'todayPnlPercent':Decimal('-.02')}],'synthetic')[0]
        self.assertEqual(r['reportedTodayPnl'],'-4'); self.assertEqual(r['reportedTodayPnlPercent'],'-0.02')
    def test_transport_error_does_not_cause_endpoint_retry(self):
        client=SimpleNamespace(get_assets=lambda **kw: (_ for _ in ()).throw(TimeoutError()),get_prime_assets=lambda **kw: self.fail('must not retry'))
        r=app.fetch_assets_account(client,{'account':'synthetic','ref':'a'*32})
        self.assertEqual(r['sourceReadStatus'],'failed'); self.assertEqual(len(r['attempts']),1)
    def test_read_success_records_endpoint_and_account_ref_only(self):
        client=SimpleNamespace(raw_data=self.standard(),get_assets=lambda **kw:[object()])
        r=app.fetch_assets_account(client,{'account':'synthetic','ref':'a'*32})
        self.assertTrue(r['accountIdentityChecked']); self.assertEqual(r['accountRef'],'a'*32); self.assertNotIn('account',r)
        self.assertEqual(r['endpoint'],'assets')
    def test_partial_provider_marker_rejected(self):
        d=self.standard();d['hasMore']=True
        with self.assertRaisesRegex(app.ReadOnlyError,'ASSET_PARTIAL_RESPONSE'): app.normalize_assets(d,'synthetic','assets')

class AnalyticsAndPrimeTests(unittest.TestCase):
    def test_prime_uppercase_pl_fields(self):
        r=app.normalize_asset_block({'totalTodayPL':Decimal('-12.34'),'realizedPL':1,'unrealizedPL':4})
        self.assertEqual(r['amounts']['reportedTodayPnl'],'-12.34')
        self.assertEqual(r['sourceFields']['reportedTodayPnl'],'totalTodayPL')
        self.assertEqual(r['sourceNumericFields']['totalTodayPL'],'-12.34')
    def test_raw_numeric_account_identifier_not_retained(self):
        r=app.normalize_asset_block({'accountId':12345678,'cashBalance':1})
        self.assertNotIn('accountId',r['sourceNumericFields'])
    def test_sdk_date_cast_does_not_mutate_raw_or_money(self):
        d={'history':[{'date':Decimal('1792382400000'),'pnl':Decimal('0.00000001')}]}
        r=app.analytics_sdk_data(d)
        self.assertIsInstance(r['history'][0]['date'],int)
        self.assertIsInstance(d['history'][0]['date'],Decimal)
        self.assertEqual(r['history'][0]['pnl'],Decimal('0.00000001'))
    def test_fractional_analytics_epoch_rejected(self):
        with self.assertRaisesRegex(app.ReadOnlyError,'ANALYTICS_DATE_INVALID'): app.analytics_sdk_data({'history':[{'date':Decimal('123.4')}]})
    def test_analytics_raw_cumulative_not_certified_daily(self):
        raw={'summary':{'pnl':Decimal('12.34')},'history':[{'date':1792382400000,'pnl':0,'asset':100,'deposit':0,'withdrawal':0},{'date':1792468800000,'pnl':Decimal('12.34'),'asset':Decimal('112.34'),'deposit':0,'withdrawal':0}]}
        client=SimpleNamespace(raw_data=raw,get_analytics_asset=lambda **kw:raw)
        r=app.fetch_analytics_account(client,{'account':'synthetic','ref':'a'*32},'2026-10-19','2026-10-20')
        self.assertEqual(r['history'][1]['pnl'],'12.34'); self.assertFalse(r['pnlSemanticsVerified'])
        self.assertEqual(r['currency'],'USD'); self.assertEqual(r['segment'],'SEC')
    def test_prime_preference_calls_prime_first(self):
        raw={'accountId':'synthetic','segments':[{'category':'S','currency':'USD','cashBalance':1}]}
        client=SimpleNamespace(raw_data=raw,get_prime_assets=lambda **kw: object(),get_assets=lambda **kw:self.fail('should not use generic'))
        r=app.fetch_assets_account(client,{'account':'synthetic','ref':'a'*32},prefer_prime=True)
        self.assertEqual(r['endpoint'],'prime_assets')

if __name__=='__main__': unittest.main()
