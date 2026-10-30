#!/usr/bin/env python3
"""Read-only market-session gate; no quotes, app mutation or notifications."""
import argparse
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

def preflight(now):
    import exchange_calendars as xc
    local=now.astimezone(ZoneInfo('America/New_York'))
    c=xc.get_calendar('XNYS')
    date=local.date().isoformat()
    out={'schema_version':1,'calendar':'XNYS','calendar_package':xc.__version__,
         'now_utc':now.isoformat(),'session_date':date,'user_timezone':'Asia/Shanghai',
         'regular_session':bool(c.is_session(date)),'due':False}
    if not out['regular_session']:
        return {**out,'reason':'not_a_trading_session'}
    close=c.session_close(date).to_pydatetime()
    opened=c.session_open(date).to_pydatetime()
    seconds=(close-now).total_seconds()
    out.update(session_open_utc=opened.isoformat(),session_close_utc=close.isoformat(),
               session_close_shanghai=close.astimezone(ZoneInfo('Asia/Shanghai')).isoformat(),
               seconds_to_close=seconds,
               early_close=close.astimezone(ZoneInfo('America/New_York')).hour<16)
    if 0<=seconds<=600:
        return {**out,'due':True,'reason':'within_last_ten_minutes'}
    if -120<=seconds<0:
        return {**out,'due':True,'reason':'just_closed_provider_freshness_still_required'}
    if seconds < -120:
        return {**out,'reason':'session_already_closed'}
    return {**out,'reason':'not_yet_due'}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--now-utc')
    a=p.parse_args()
    try:
        now=datetime.fromisoformat(a.now_utc.replace('Z','+00:00')) if a.now_utc else datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError('now-utc must include timezone')
        print(json.dumps(preflight(now.astimezone(timezone.utc)),sort_keys=True))
    except Exception as e:
        print(json.dumps({'due':False,'reason':'calendar_unavailable','error':str(e)}))
        raise SystemExit(2)

if __name__=='__main__':
    main()
