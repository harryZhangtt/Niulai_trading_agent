"""Pinned XNYS calendar, with a bounded single-session availability fallback."""
from datetime import datetime, timedelta, timezone


def completed_sessions(now=None, limit=5):
    """Latest-first completed exchange sessions; never calendar-day subtraction."""
    import exchange_calendars as ec
    import pandas as pd
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5:
        raise ValueError('session lookback must be between 1 and 5')
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None: raise ValueError('timezone-aware now required')
    utc = now.astimezone(timezone.utc)
    start = (utc-timedelta(days=20)).date().isoformat()
    end = (utc+timedelta(days=2)).date().isoformat()
    cal = ec.get_calendar('XNYS', start=start, end=end)
    elapsed = cal.schedule.loc[cal.schedule['close'] <= pd.Timestamp(utc)]
    if elapsed.empty: raise ValueError('no completed session in calendar window')
    return [{'calendar':'XNYS', 'date':s.date().isoformat(),
             'close_utc':close.isoformat(), 'checked_at':utc.isoformat()}
            for s,close in elapsed['close'].tail(limit).iloc[::-1].items()]


def latest_completed_session(now=None):
    return completed_sessions(now, limit=1)[0]


def select_available_session(available_dates, now=None, limit=5):
    """Choose one exact completed date. Caller certifies source availability.

    This function never certifies prices/P&L or mixes data from different dates.
    Unknown, malformed, future and out-of-window dates are simply ineligible.
    """
    if isinstance(available_dates, (str, bytes, dict)):
        raise ValueError('available_dates must be a collection of ISO date strings')
    available = {d for d in available_dates if isinstance(d, str)}
    candidates = completed_sessions(now, limit)
    picked = next(((i,s) for i,s in enumerate(candidates) if s['date'] in available), None)
    return {'calendar':'XNYS', 'preferred_session':candidates[0]['date'],
            'selected_session':picked[1]['date'] if picked else None,
            'selected_close_utc':picked[1]['close_utc'] if picked else None,
            'delayed':bool(picked and picked[0] > 0),
            'session_lag':picked[0] if picked else None,
            'candidate_sessions':[s['date'] for s in candidates],
            'checked_at':candidates[0]['checked_at'],
            'status':'available' if picked else 'unavailable_within_lookback'}


if __name__=='__main__':
    import json
    print(json.dumps(latest_completed_session()))
