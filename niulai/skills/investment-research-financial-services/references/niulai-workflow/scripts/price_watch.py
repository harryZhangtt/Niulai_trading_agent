#!/usr/bin/env python3
"""Standalone, auditable session-range monitoring. No Studio/API keys required.
Daily OHLC proves reached levels, not intraday ordering or exact crossing times.
Replay is retrospective and never inserts live notification events.
"""
import argparse, hashlib, json, math, re, sqlite3, socket, time, os
from urllib.error import HTTPError, URLError
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode, quote
from zoneinfo import ZoneInfo
from niulai_state import validate_config
UTC=timezone.utc
NY=ZoneInfo('America/New_York')
VERSION='2026-10-20-session-range-1'

def instant(s):
    d=datetime.fromisoformat(s.replace('Z','+00:00'))
    if d.tzinfo is None: raise ValueError('Timezone required')
    return d.astimezone(UTC)

def decimal(v):
    if isinstance(v,bool): raise ValueError('Boolean price')
    d=Decimal(str(v))
    if not d.is_finite() or d<=0: raise ValueError('Invalid price')
    return d

def session(asof):
    import exchange_calendars as xc
    c=xc.get_calendar('XNYS'); day=asof.astimezone(NY).date().isoformat()
    if not c.is_session(day): return None
    return {'date':day,'open':c.session_open(day).to_pydatetime(), 'close':c.session_close(day).to_pydatetime(), 'previous':str(c.previous_session(day).date())}

def gate(config,role,now):
    s=next((r for r in config['schedules'] if r['role']==role),None)
    p=config['notifications']['policies'].get(role,{})
    if not s or not s.get('enabled') or not p.get('enabled'): return False,'disabled',None
    market=session(now)
    if not market: return False,'not_a_session',None
    local=now.astimezone(NY)
    if role in ('existing_summary','daily_triggered_research'):
        for slot in s['times']:
            h,m=map(int,slot.split(':')); scheduled=local.replace(hour=h,minute=m,second=0,microsecond=0)
            delta=(local-scheduled).total_seconds()
            if 0<=delta<=60*min(s.get('runtime_slot_grace_minutes',60),60):
                if role=='daily_triggered_research' and now<market['close']:return False,'before_close',market
                return True,slot,market
        return False,'outside_slot',market
    seconds=(market['close']-now).total_seconds()
    return -120<=seconds<=600,'close_window',market

def validate_rules(rules):
    ids=set()
    for r in rules:
        if r['id'] in ids: raise ValueError('Duplicate rule id')
        ids.add(r['id']); decimal(r['threshold'])
        if r['direction'] not in ('above','below') or type(r['enabled']) is not bool: raise ValueError('Invalid rule')
        if not re.fullmatch(r'[A-Z0-9.^=-]{1,20}',r['ticker']): raise ValueError('Invalid ticker')
        instant(r['updatedAt'])

def classify(r,bar,previous,buffer):
    t=decimal(r['threshold']); b=Decimal(str(buffer))
    if not b.is_finite() or not 0<=b<=Decimal('.05'): raise ValueError('Invalid buffer')
    close_only=bar.get('validation_scope')=='corroborated_close_only'
    last=decimal(bar['close'])
    low,high=(None,None) if close_only else tuple(map(decimal,(bar['low'],bar['high'])))
    if not close_only and not low<=last<=high: raise ValueError('Invalid range')
    below=r['direction']=='below'; edge=t*(1+b if below else 1-b)
    matches=lambda p: p<=edge if below else p>=edge
    exact=lambda p: p<=t if below else p>=t
    observed=last if close_only else low if below else high
    reached=matches(observed)
    outside_previous=previous is not None and not matches(decimal(previous))
    # Open precedes extrema. A daily high and low alone do not establish their order.
    outside_open=not close_only and bar.get('open_observed',True) and not matches(decimal(bar['open']))
    directional=not close_only and reached and (outside_previous or outside_open)
    return {'rule_id':r['id'],'ticker':r['ticker'],'direction':r['direction'], 'threshold':str(t),
      'zone_edge':str(edge),'buffer_fraction':str(b),'close':str(last),'low':None if close_only else str(low),'high':None if close_only else str(high),
      'zone_reached':reached,'threshold_reached':exact(observed),'currently_in_zone':matches(last),
      'validation_scope':bar.get('validation_scope','full_observed_range'),'quality_warning':bar.get('quality_warning'),
      'directional_entry_supported':directional,'exact_crossing_time':None,
      'classification':'directional_zone_entry' if directional else 'in_zone_without_new_crossing_proof' if reached else 'not_reached',
      'quote_time':bar['quote_time'],'evidence':bar['evidence'],
      **{k:r[k] for k in ('note','review_range','research_ref','entry_conditions','expires_at') if k in r},
      **({'entry_condition_status':'requires_research_recheck_not_evaluated_by_price_engine'} if r.get('entry_conditions') else {})}

def parse(payload,symbol,market,asof):
    chart=payload['chart']
    if chart.get('error'): raise ValueError('Provider error')
    result=chart['result'][0]; meta=result['meta']
    if meta['symbol'].upper()!=symbol or meta.get('currency')!='USD' or meta.get('exchangeTimezoneName')!='America/New_York': raise ValueError('Symbol/currency/timezone mismatch')
    stamps=result.get('timestamp',[]); q=result['indicators']['quote'][0]
    if any(len(q.get(k,[]))!=len(stamps) for k in ('open','high','low','close')): raise ValueError('Malformed arrays')
    if stamps!=sorted(set(stamps)): raise ValueError('Unordered or duplicate timestamps')
    rows=[]
    completed=asof>=market['close']+timedelta(minutes=1)
    previous=None
    for i,stamp in enumerate(stamps):
        ts=datetime.fromtimestamp(stamp,UTC); day=ts.astimezone(NY).date().isoformat()
        if day==market['previous'] and completed and q['close'][i] is not None: previous=str(decimal(q['close'][i]))
        if day!=market['date']: continue
        if not completed and (ts<market['open'] or ts+timedelta(minutes=5)>min(asof,market['close'])): continue
        values={k:str(decimal(q[k][i])) for k in ('open','high','low','close')}
        if not decimal(values['low'])<=min(decimal(values['open']),decimal(values['close']))<=max(decimal(values['open']),decimal(values['close']))<=decimal(values['high']):
            # Retain an actual corroborated close, never invent replacement extrema.
            mt=datetime.fromtimestamp(meta.get('regularMarketTime',0),UTC)
            close_ok=decimal(values['low'])<=decimal(values['close'])<=decimal(values['high'])
            corroborated=meta.get('regularMarketPrice') is not None and abs(decimal(meta['regularMarketPrice'])-decimal(values['close']))<=Decimal('.005')
            if not (completed and close_ok and corroborated and market['close']<=mt<=min(asof,market['close']+timedelta(minutes=10))):
                raise ValueError('Malformed OHLC; closing price not corroborated')
            values.update(open=None,low=None,high=None,validation_scope='corroborated_close_only',quality_warning='Provider open outside daily range; actual close corroborated by same-provider regularMarketPrice. Intraday range/crossing unavailable.')
        rows.append((ts,values))
    if not rows: raise ValueError('Missing target session prices')
    if completed:
        if len(rows)!=1: raise ValueError('Ambiguous daily session')
        bar=rows[0][1]; end=market['close']; evidence='completed_daily_range_retrieved_retrospectively'
    else:
        end=rows[-1][0]+timedelta(minutes=5)
        if (asof-end).total_seconds()>1200: raise ValueError('Stale intraday data')
        # Missing bars mean range is only observed coverage, never a complete day claim.
        bar={'open':rows[0][1]['open'],'close':rows[-1][1]['close'],'low':str(min(decimal(v['low']) for _,v in rows)),'high':str(max(decimal(v['high']) for _,v in rows))}
        evidence='observed_completed_5m_bars_partial_session'
    bar.update(quote_time=end.isoformat(),evidence='corroborated_regular_session_close_range_unavailable' if bar.get('validation_scope') else evidence,open_observed=not bar.get('validation_scope') and (completed or rows[0][0]==market['open']))
    splits=result.get('events',{}).get('splits',{})
    return bar,previous,[int(e['date']) for e in splits.values()]

def request_text(url):
    """Retry transport faults only; invalid financial payloads never get a free pass."""
    attempts=[]
    for attempt in range(3):
        try:
            with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0 Niulai/2.1'}),timeout=12) as response:
                return response.read().decode()
        except (HTTPError, URLError, TimeoutError, ConnectionError, socket.timeout) as exc:
            transient=not isinstance(exc,HTTPError) or exc.code in (408,429,500,502,503,504)
            attempts.append(f'{type(exc).__name__}: {exc}')
            if not transient or attempt==2:
                raise RuntimeError(f'HTTP source failed after {len(attempts)} attempt(s): '+ '; '.join(attempts)) from exc
            time.sleep(2**attempt)

def fetch_safe(*args):
    try:
        return fetch(*args)
    except Exception as exc:
        return {'ticker':args[0],'error':f'{type(exc).__name__}: {exc}',
                'retrieved_at':datetime.now(UTC).isoformat()}

def late_summary_slot(config,role,asof,market):
    if role!='existing_summary' or not market: return None
    if not config['price_monitor'].get('late_run_recovery',{}).get('enabled'): return None
    schedule=next(r for r in config['schedules'] if r['role']==role)
    local=asof.astimezone(NY)
    past=[slot for slot in schedule['times']
          if local.time().replace(tzinfo=None)>=datetime.strptime(slot,'%H:%M').time()]
    return max(past,default=None)


def fetch(symbol,market,asof,earliest):
    completed=asof>=market['close']+timedelta(minutes=1)
    start=min(earliest-timedelta(days=7),market['open']-timedelta(days=7)) if completed else market['open']-timedelta(days=4)
    url='https://query1.finance.yahoo.com/v8/finance/chart/'+quote(symbol,safe='')+'?'+urlencode({'period1':int(start.timestamp()),'period2':int(min(asof,market['close']+timedelta(minutes=5)).timestamp()),'interval':'1d' if completed else '5m','events':'splits','includePrePost':'false'})
    raw=None
    try:
        raw=request_text(url)
        bar,previous,splits=parse(json.loads(raw),symbol,market,asof)
        if not completed:
            daily_url='https://query1.finance.yahoo.com/v8/finance/chart/'+quote(symbol,safe='')+'?'+urlencode({'period1':int((earliest-timedelta(days=7)).timestamp()),'period2':int(asof.timestamp()),'interval':'1d','events':'splits','includePrePost':'false'})
            daily_raw=request_text(daily_url)
            daily=json.loads(daily_raw)['chart']['result'][0]
            if daily['meta']['symbol'].upper()!=symbol or daily['meta'].get('currency')!='USD' or daily['meta'].get('exchangeTimezoneName')!='America/New_York': raise ValueError('Daily source mismatch')
            if len(daily.get('timestamp',[]))!=len(daily['indicators']['quote'][0]['close']) or daily.get('timestamp',[])!=sorted(set(daily.get('timestamp',[]))): raise ValueError('Invalid secondary daily series')
            splits=[int(e['date']) for e in daily.get('events',{}).get('splits',{}).values()]
            for stamp,value in zip(daily.get('timestamp',[]),daily['indicators']['quote'][0]['close']):
                if datetime.fromtimestamp(stamp,UTC).astimezone(NY).date().isoformat()==market['previous'] and value is not None: previous=str(decimal(value))
            raw=json.dumps({'intraday':json.loads(raw),'daily':json.loads(daily_raw),'daily_source_url':daily_url})
        return {'ticker':symbol,'bar':bar,'previous':previous,'splits':splits,'source_url':url,'raw':raw,'retrieved_at':datetime.now(UTC).isoformat(),'sha256':hashlib.sha256(raw.encode()).hexdigest()}
    except Exception as e: return {'ticker':symbol,'error':str(e),'source_url':url,'raw':raw,'retrieved_at':datetime.now(UTC).isoformat()}

def setup(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS price_runs(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS price_completed_slots(slot_id TEXT PRIMARY KEY,run_id TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS price_sources(run_id TEXT,ticker TEXT,payload TEXT NOT NULL,PRIMARY KEY(run_id,ticker));
    CREATE TABLE IF NOT EXISTS price_signals(id TEXT PRIMARY KEY,session TEXT,rule_id TEXT,kind TEXT,payload TEXT NOT NULL,delivery TEXT NOT NULL DEFAULT 'unconfirmed');''')

def run(config,rules,db,asof,role,mode):
    validate_config(config); validate_rules(rules)
    if config['alert_authority']!='niulai_saved_json_sqlite': raise ValueError('Standalone authority not activated')
    now=datetime.now(UTC)
    if asof>now: raise ValueError('Future cutoff')
    catchup=False
    if mode=='live':
        if abs((now-asof).total_seconds())>120: raise ValueError('Live cutoff must be current; use replay for history')
        due,slot,market=gate(config,role,asof)
        if not due and slot=='outside_slot':
            late=late_summary_slot(config,role,asof,market)
            if late: due,slot,catchup=True,late,True
        if not due:
            retry=None
            if market and role=='daily_price_watch':
                seconds=(market['close']-asof).total_seconds()
                if 600<seconds<=720: retry=math.ceil(seconds-600)
            if market and role=='existing_summary':
                local=asof.astimezone(NY)
                for scheduled in next(r for r in config['schedules'] if r['role']==role)['times']:
                    h,m=map(int,scheduled.split(':'));delta=(local.replace(hour=h,minute=m,second=0,microsecond=0)-local).total_seconds()
                    if 0<delta<=120: retry=math.ceil(delta)
            return {'status':'skipped','reason':slot,'retry_after_seconds':retry}
    else: market=session(asof);slot=asof.isoformat()
    if not market: return {'status':'skipped','reason':'not_a_session'}
    if asof<market['open']: return {'status':'skipped','reason':'before_open'}
    identity=f'{VERSION}:{mode}:{role}:{market["date"]}:{slot}'
    setup(db)
    slot_identity=identity
    prior=db.execute('SELECT payload FROM price_runs WHERE id=COALESCE((SELECT run_id FROM price_completed_slots WHERE slot_id=?),?)',(identity,identity)).fetchone()
    if prior:
        old=json.loads(prior[0])
        if old['status']=='completed': return {'status':'duplicate_completed_slot','id':identity,'original_config_revision':old['config_revision'],'new_signals':[]}
        identity += ':retry:'+now.isoformat()
    active=[r for r in rules if r['enabled']]
    quote_only=config['price_monitor'].get('quote_only_symbols',[])
    if not isinstance(quote_only,list) or any(not isinstance(s,str) or not re.fullmatch(r'[A-Z0-9.^=-]{1,20}',s) for s in quote_only): raise ValueError('Invalid quote-only symbols')
    symbols=sorted({r['ticker'] for r in active}|set(quote_only))
    # Each finished symbol is checkpointed before waiting on the slowest source.
    sources=[]
    db.execute('INSERT INTO price_runs VALUES(?,?)',(identity,json.dumps({
        'id':identity,'status':'collecting','config_revision':config['config_revision'],
        'as_of':asof.isoformat(),'expected_symbols':symbols,'delivery':'unconfirmed'})))
    db.commit()
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures={pool.submit(fetch_safe,s,market,asof,min((min(instant(r['updatedAt']),instant(r.get('effective_from',r['updatedAt']))) for r in active if r['ticker']==s),default=market['open'])):s for s in symbols}
        for future in as_completed(futures):
            source=future.result();sources.append(source)
            db.execute('INSERT INTO price_sources VALUES(?,?,?)',(identity,source['ticker'],json.dumps(source)))
            db.commit()
    sources.sort(key=lambda row:row['ticker'])
    by={r['ticker']:r for r in sources}; results=[];errors=[];signals=[]
    for r in active:
        source=by[r['ticker']]
        try:
            if source.get('error'): raise ValueError(source['error'])
            effective=instant(r.get('effective_from',r['updatedAt']))
            if effective>market['open']: raise ValueError('Rule not effective for entire evaluated session')
            if r.get('expires_at') and instant(r['expires_at'])<=asof: raise ValueError('Rule expired')
            if any(effective.timestamp()<s<=asof.timestamp() for s in source['splits']): raise ValueError('Split since rule revision; threshold review required')
            leverage=abs(Decimal(str(config['price_monitor'].get('leverage_multipliers',{}).get(r['ticker'],1))))
            buffer=r.get('buffer_fraction',str(Decimal(config['price_monitor']['buffer_fraction'])*leverage))
            row=classify(r,source['bar'],source['previous'],buffer)
            row['daily_leverage_multiplier']=str(leverage)
            row.update(session=market['date'],source_url=source['source_url'],retrieved_at=source['retrieved_at'])
            results.append(row)
            if mode=='live' and not catchup and row['zone_reached']:
                kind=row['classification']+(':threshold' if row['threshold_reached'] else ':approach');key=hashlib.sha256(f'{VERSION}:{market["date"]}:{r["id"]}:{r["updatedAt"]}:{kind}'.encode()).hexdigest()
                row['event_id']=key
                if db.execute('INSERT OR IGNORE INTO price_signals(id,session,rule_id,kind,payload) VALUES(?,?,?,?,?)',(key,market['date'],r['id'],kind,json.dumps(row))).rowcount:signals.append(row)
        except Exception as e: errors.append({**r,'rule_id':r['id'],'error':str(e)})
    out={'id':identity,'status':'completed' if not errors else 'partial','mode':mode,'role':role,'version':VERSION,'config_revision':config['config_revision'],'as_of':asof.isoformat(),'session':market['date'],'created_at':now.isoformat(),'coverage':{'enabled_rules':len(active),'valid_rules':len(results),'failed_rules':len(errors),'symbols':len(symbols)},'results':results,'errors':errors,'new_signals':signals,'recorded_live_totals':{str(d)+'d':db.execute('SELECT COUNT(*) FROM price_signals WHERE session>=? AND session<=?',((asof.astimezone(NY).date()-timedelta(days=d-1)).isoformat(),market['date'])).fetchone()[0] for d in (1,3,7,10)},'delivery':'unconfirmed','retrospective':mode=='replay' or catchup,'delayed_catchup':catchup,'intended_slot':slot,'engine_revision':'2026-10-22-resilience-1','limitations':['Ranges do not establish exact crossing time or repeated intraday crossings.','Historical replay uses data retrieved now and is not evidence of an original notification.','First in-zone observation is a level condition, not automatically a new crossing.']}
    out['quote_only']=[{k:v for k,v in by[s].items() if k not in ('raw','splits')} for s in quote_only if s not in {r['ticker'] for r in active}]
    out['quality_warnings']=[{'ticker':s['ticker'],'warning':s['bar']['quality_warning']} for s in sources if s.get('bar',{}).get('quality_warning')]
    out['coverage']['quote_only_symbols']=len(out['quote_only'])
    out['coverage']['valid_symbols']=sum(not s.get('error') for s in sources)
    out['coverage']['failed_symbols']=sum(bool(s.get('error')) for s in sources)
    if out['quality_warnings'] or any(s.get('error') for s in out['quote_only']): out['status']='partial'
    out['engine_revision']='2026-10-23-report-quality-1'
    out['rules_sha256']=hashlib.sha256(json.dumps(rules,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    out['config_sha256']=hashlib.sha256(json.dumps(config,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    db.execute('UPDATE price_runs SET payload=? WHERE id=?',(json.dumps(out),identity))
    if out['status']=='completed':db.execute('INSERT OR IGNORE INTO price_completed_slots VALUES(?,?)',(slot_identity,identity))
    db.commit();return out

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for x in ('config','rules','db','output'):p.add_argument('--'+x,required=True)
    p.add_argument('--as-of');p.add_argument('--role',choices=['existing_summary','daily_price_watch'],default='existing_summary');p.add_argument('--mode',choices=['live','replay'],default='live')
    a=p.parse_args();dbpath=Path(a.db)
    try:
        if not dbpath.exists(): raise ValueError('Restore existing alerts database first')
        config=json.loads(Path(a.config).read_text());rules=json.loads(Path(a.rules).read_text())['alerts']
        with sqlite3.connect(dbpath) as db:out=run(config,rules,db,instant(a.as_of) if a.as_of else datetime.now(UTC),a.role,a.mode)
    except Exception as exc:
        out={'status':'failed','error':f'{type(exc).__name__}: {exc}','delivery':'unconfirmed','created_at':datetime.now(UTC).isoformat()}
    output=Path(a.output);tmp=output.with_name(output.name+f'.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');os.replace(tmp,output)
    print(json.dumps({k:v for k,v in out.items() if k not in ('results','new_signals')},ensure_ascii=False))
    if out['status']=='failed': raise SystemExit(1)
if __name__=='__main__':main()
