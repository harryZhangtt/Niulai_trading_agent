import unittest,json,base64
from pathlib import Path
from compose_digest import compose
from price_summary_view import render
P=Path(__file__).parent
class CombinedPriceViewTests(unittest.TestCase):
 def test_full_scope_and_holdings_in_one_body(self):
  v=json.loads((P/'daily_pipeline_test/daily.json').read_text());m=json.loads((P/'price_visual_test/price_view.json').read_text());r=compose(v,'source summary',P/'daily_pipeline_test/Tiger_Daily_Compact_Test_20261026.pdf','Test','me',True,m);body=r['payload']['parts'][0]['body']['content']
  self.assertIn(render(m),body)
  for x in m['rows']:self.assertIn(x['ticker'],body)
  for x in v['accounts'][0]['daily_performance']['positions']:self.assertIn('>'+x['symbol']+'<',body)
  self.assertEqual(base64.urlsafe_b64decode(r['payload']['parts'][1]['body']['base64_url_content']),(P/'daily_pipeline_test/Tiger_Daily_Compact_Test_20261026.pdf').read_bytes())
 def test_historical_session_mismatch_rejected(self):
  v=json.loads((P/'daily_pipeline_test/daily.json').read_text());m=json.loads((P/'price_visual_test/price_view.json').read_text());m['session']='2026-10-22'
  with self.assertRaises(ValueError):compose(v,'source summary',P/'daily_pipeline_test/Tiger_Daily_Compact_Test_20261026.pdf','Test','me',True,m)
 def test_empty_price_cannot_silently_drop_section(self):
  with self.assertRaises(ValueError):compose({},'',P/'daily_pipeline_test/Tiger_Daily_Compact_Test_20261026.pdf','Test','me')
