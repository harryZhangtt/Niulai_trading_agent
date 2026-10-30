import unittest
from datetime import datetime
from session_date import latest_completed_session
class SessionTests(unittest.TestCase):
 def date(self,s):return latest_completed_session(datetime.fromisoformat(s))['date']
 def test_weekend_uses_friday(self):self.assertEqual(self.date('2026-10-25T17:00:00+00:00'),'2026-10-23')
 def test_monday_before_close(self):self.assertEqual(self.date('2026-10-26T18:00:00+00:00'),'2026-10-23')
 def test_monday_after_close(self):self.assertEqual(self.date('2026-10-26T20:01:00+00:00'),'2026-10-26')
 def test_thanksgiving_closed(self):self.assertEqual(self.date('2026-11-26T23:00:00+00:00'),'2026-11-25')
 def test_early_close_not_completed(self):self.assertEqual(self.date('2026-11-27T17:59:00+00:00'),'2026-11-25')
 def test_early_close_completed(self):self.assertEqual(self.date('2026-11-27T18:01:00+00:00'),'2026-11-27')
 def test_dst_weekend(self):self.assertEqual(self.date('2026-03-08T17:00:00+00:00'),'2026-03-06')
 def test_naive_rejected(self):
  with self.assertRaises(ValueError): latest_completed_session(datetime(2026,10,25))

from session_date import completed_sessions, select_available_session
class AvailableSessionTests(unittest.TestCase):
 def choose(self, dates, now='2026-10-25T17:00:00+00:00',limit=5):
  return select_available_session(dates,datetime.fromisoformat(now),limit)
 def test_preferred_available(self):
  r=self.choose(['2026-10-22','2026-10-23']);self.assertEqual(r['selected_session'],'2026-10-23');self.assertFalse(r['delayed']);self.assertEqual(r['session_lag'],0)
 def test_weekend_friday_missing_thursday(self):
  r=self.choose(['2026-10-22']);self.assertEqual(r['preferred_session'],'2026-10-23');self.assertEqual(r['selected_session'],'2026-10-22');self.assertTrue(r['delayed']);self.assertEqual(r['session_lag'],1)
 def test_no_weekend_date(self):
  r=self.choose(['2026-10-24','2026-10-25']);self.assertIsNone(r['selected_session'])
 def test_future_and_incomplete_rejected(self):
  r=self.choose(['2026-10-26','2026-10-27'],'2026-10-26T18:00:00+00:00');self.assertIsNone(r['selected_session'])
 def test_five_exchange_sessions_not_calendar_days(self):
  r=self.choose(['2026-10-19']);self.assertEqual(r['candidate_sessions'],['2026-10-23','2026-10-22','2026-10-21','2026-10-20','2026-10-19']);self.assertEqual(r['session_lag'],4)
 def test_older_than_bound_rejected(self):self.assertIsNone(self.choose(['2026-10-16'])['selected_session'])
 def test_holiday_not_eligible(self):
  r=self.choose(['2026-11-26','2026-11-24'],'2026-11-26T23:00:00+00:00');self.assertEqual(r['preferred_session'],'2026-11-25');self.assertEqual(r['selected_session'],'2026-11-24')
 def test_early_close_before(self):
  r=self.choose(['2026-11-27','2026-11-25'],'2026-11-27T17:59:00+00:00');self.assertEqual(r['selected_session'],'2026-11-25')
 def test_early_close_after(self):
  r=self.choose(['2026-11-27'],'2026-11-27T18:01:00+00:00');self.assertEqual(r['selected_session'],'2026-11-27');self.assertTrue(r['selected_close_utc'].startswith('2026-11-27T18:00:00'))
 def test_dst_close_not_fixed_hour(self):
  r=self.choose(['2026-03-09'],'2026-03-09T20:01:00+00:00');self.assertEqual(r['selected_session'],'2026-03-09');self.assertTrue(r['selected_close_utc'].startswith('2026-03-09T20:00:00'))
 def test_no_mixing_single_date_even_unordered_duplicates(self):
  r=self.choose(['2026-10-21','2026-10-22','2026-10-22']);self.assertEqual(r['selected_session'],'2026-10-22')
 def test_none_available_not_preferred_zero(self):
  r=self.choose([]);self.assertIsNone(r['selected_session']);self.assertIsNone(r['session_lag']);self.assertEqual(r['status'],'unavailable_within_lookback')
 def test_invalid_limit(self):
  for n in (0,6,True,1.5):
   with self.subTest(limit=n),self.assertRaises(ValueError):self.choose([],limit=n)
 def test_invalid_date_collection(self):
  with self.assertRaises(ValueError):self.choose('2026-10-23')
 def test_calendar_failure_propagates(self):
  from unittest.mock import patch
  with patch('exchange_calendars.get_calendar',side_effect=RuntimeError('calendar_failed')):
   with self.assertRaises(RuntimeError):self.choose(['2026-10-23'])

if __name__=='__main__':unittest.main()
