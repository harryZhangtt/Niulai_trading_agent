import unittest
from datetime import datetime
from market_preflight import preflight

class CalendarGateTests(unittest.TestCase):
    def at(self,s):return preflight(datetime.fromisoformat(s.replace('Z','+00:00')))
    def test_normal_session_near_close(self):
        r=self.at('2026-10-19T19:55:00Z');self.assertTrue(r['due']);self.assertFalse(r['early_close'])
    def test_normal_midday_not_due(self):self.assertFalse(self.at('2026-10-19T16:55:00Z')['due'])
    def test_early_close_day(self):
        r=self.at('2026-11-27T17:55:00Z');self.assertTrue(r['due']);self.assertTrue(r['early_close'])
    def test_christmas_skips(self):self.assertEqual(self.at('2026-12-25T20:55:00Z')['reason'],'not_a_trading_session')
    def test_weekend_skips(self):self.assertFalse(self.at('2026-10-17T19:55:00Z')['due'])
    def test_dst_close_shift(self):
        self.assertTrue(self.at('2026-11-02T20:55:00Z')['due'])
        self.assertFalse(self.at('2026-11-02T19:55:00Z')['due'])
    def test_late_quote_not_assumed_fresh(self):self.assertFalse(self.at('2026-10-19T20:03:00Z')['due'])

if __name__=='__main__':unittest.main()
