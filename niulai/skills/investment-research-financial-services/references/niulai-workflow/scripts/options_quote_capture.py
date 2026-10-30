#!/usr/bin/env python3
"""Bounded read-only Tradier/Alpaca quote capture; no account/order methods.

This is a data-recovery adapter, NOT an executable/options-completion certificate.
Capture uses actual UTC. Offline normalize keeps source timestamps and nulls.
See references/options-data-access.md for configuration and admission boundaries.
"""
import argparse
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from options_payoff_checks import parse_contract_id

VERSION = '2026-10-24-options-quote-capture-1'
MAX_BYTES = 10_000_000
ENDPOINTS = {
    'tradier': ('https://api.tradier.com/v1/markets/quotes',),
    'alpaca': ('https://data.alpaca.markets/v1beta1/options/quotes/latest',
               'https://data.alpaca.markets/v2/stocks/quotes/latest'),
}
CREDENTIALS = {'tradier': ('TRADIER_ACCESS_TOKEN',),
               'alpaca': ('ALPACA_API_KEY', 'ALPACA_SECRET_KEY')}


class CaptureError(ValueError): pass


def decode(raw):
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result: raise CaptureError('duplicate_json_key')
            result[k] = v
        return result
    def bad(_): raise CaptureError('nonfinite_json')
    try:return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)
    except (json.JSONDecodeError,UnicodeDecodeError):raise CaptureError('malformed_json') from None


def utc(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?(?:Z|[+-]\d\d:\d\d)', value):
        raise CaptureError('timezone_qualified_quote_time_required')
    try: return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone.utc)
    except ValueError as exc: raise CaptureError('invalid_quote_time') from exc


def iso(t): return t.astimezone(timezone.utc).isoformat().replace('+00:00','Z')


def timestamp(value, unit):
    if value is None or value == 0: return None
    if unit == 'rfc3339':
        utc(value)
        # Preserve nanosecond source string, do not invent independent side times.
        return value
    if unit not in ('seconds','milliseconds') or type(value) not in (int,float):
        raise CaptureError('explicit_epoch_unit_required')
    try:
        t = datetime.fromtimestamp(value/(1000 if unit == 'milliseconds' else 1), timezone.utc)
        if not 2000 <= t.year <= 2100: raise ValueError('epoch range')
        return iso(t)
    except (ValueError, OverflowError, OSError): raise CaptureError('invalid_epoch_time')


def money(v):
    if v is None: return None
    if type(v) not in (int,float,str) or isinstance(v,bool): raise CaptureError('invalid_quote_number')
    try:
        if len(str(v))>80:raise InvalidOperation()
        n = Decimal(str(v))
        if not n.is_finite() or n < 0 or n>Decimal('1000000000000') or len(n.as_tuple().digits)>40 or not -12 <= n.as_tuple().exponent <= 12 or (n and n.adjusted() < -12): raise InvalidOperation()
        return format(n,'f')
    except InvalidOperation: raise CaptureError('invalid_quote_number')


def size(v):
    if v is None: return None
    if type(v) is not int or not 0 <= v <= 10**9: raise CaptureError('invalid_quote_size')
    return v


def contract(symbol):
    try:
        parsed = parse_contract_id(symbol)
    except ValueError as exc: raise CaptureError('invalid_occ_contract') from exc
    return {**parsed, "expiry": parsed["expiry"].isoformat(), "strike": str(parsed["strike"])}


def normalize(provider, payload, symbols, *, retrieved_at, feed, epoch_unit=None):
    """Normalize exact requested symbols; preserve missing quote rows as errors."""
    utc(retrieved_at)
    if provider not in ENDPOINTS: raise CaptureError('provider_not_allowlisted')
    if not isinstance(payload,dict): raise CaptureError('invalid_response_shape')
    if any(k in payload for k in ('error','errors','message','code')): raise CaptureError('provider_semantic_error')
    if provider == 'tradier':
        quotes = payload.get('quotes')
        if not isinstance(quotes,dict): raise CaptureError('missing_quotes')
        rows = quotes.get('quote')
        rows = [rows] if isinstance(rows,dict) else rows
        if not isinstance(rows,list): rows=[]
        mapped = {}
        for row in rows:
            if not isinstance(row,dict) or not isinstance(row.get('symbol'),str) or not row['symbol'] or row['symbol'] in mapped: raise CaptureError('duplicate_or_invalid_quote')
            mapped[row.get('symbol')] = row
    else:
        mapped = payload.get('quotes')
        if not isinstance(mapped,dict): raise CaptureError('missing_quotes')
    result=[]; errors=[]
    for symbol in symbols:
        try:
            row=mapped.get(symbol)
            if not isinstance(row,dict): raise CaptureError('missing_symbol')
            if provider == 'tradier':
                bt=timestamp(row.get('bid_date'),epoch_unit); at=timestamp(row.get('ask_date'),epoch_unit)
                vals=(row.get('bid'),row.get('ask'),row.get('bidsize'),row.get('asksize'))
                basis='provider_per_side_event_time'; greeks=row.get('greeks')
            else:
                bt=at=timestamp(row.get('t'),'rfc3339')
                vals=(row.get('bp'),row.get('ap'),row.get('bs'),row.get('as'))
                basis='shared_quote_event_time_not_independent_side_times'; greeks=None
            is_option=bool(re.search(r'\d{6}[CP]\d{8}$',symbol))
            cid=contract(symbol) if is_option else None
            rec={'symbol':symbol,'contract':cid,'bid':money(vals[0]),'ask':money(vals[1]),
                 'bid_size':size(vals[2]),'ask_size':size(vals[3]),'bid_time':bt,'ask_time':at,
                 'time_basis':basis,'retrieved_at':retrieved_at,'provider':provider,'feed':feed,
                 'quote_condition':row.get('c') if provider=='alpaca' else row.get('condition'),
                 'upstream_family':'US_consolidated_options' if is_option else 'provider_stock_feed',
                 'size_units':'provider_display_units_unverified','currency':'USD',
                 'contract_terms':{'multiplier':row.get('contract_size') if provider=='tradier' else None,
                                   'deliverable_verified':False,'adjustment_status':'unknown',
                                   'exercise_style':None,'settlement_style':None},
                 'provider_greeks':greeks,'greeks_are_not_quote_timestamp':True}
            # Provider contract metadata must agree where supplied; never repair mismatch.
            if cid and provider=='tradier':
                if row.get('expiration_date') and row['expiration_date'] != cid['expiry']: raise CaptureError('contract_metadata_mismatch')
                if row.get('option_type') and row['option_type'] != cid['right']: raise CaptureError('contract_metadata_mismatch')
                if row.get('strike') is not None and Decimal(money(row['strike'])) != Decimal(cid['strike']): raise CaptureError('contract_metadata_mismatch')
            result.append(rec)
        except (CaptureError, ValueError, KeyError) as exc:
            errors.append({'symbol':symbol,'code':str(exc) if isinstance(exc,CaptureError) else 'normalization_failed'})
    return {'records':result,'errors':errors,'expected_count':len(symbols)}


def session_state(now):
    """Actual calendar check; never treat closed-market history as fresh live data."""
    try:
        import exchange_calendars as xc
        cal=xc.get_calendar('XNYS',start=str((now-timedelta(days=10)).date()),end=str((now+timedelta(days=10)).date()))
        return 'open' if cal.is_open_on_minute(now.replace(second=0,microsecond=0)) else 'closed'
    except Exception: return 'calendar_unavailable'


def assess(record, *, now, max_age_seconds, max_side_skew_seconds, session):
    issues=[]
    if record.get('contract') and record.get('quote_condition') not in (' ', 'A', 'B', 'O', 'C'):
        issues.append('nonfirm_unsupported_or_missing_quote_condition')
    if session != 'open': issues.append('market_closed' if session=='closed' else 'calendar_unavailable')
    if record['feed'] not in ('opra','consolidated_realtime','sip'): issues.append('non_executable_feed')
    if record['bid'] is None or record['ask'] is None: issues.append('missing_price')
    elif Decimal(record['bid']) > Decimal(record['ask']): issues.append('crossed_quote')
    elif Decimal(record['ask']) <= 0: issues.append('nonpositive_ask')
    if not record['bid_size'] or not record['ask_size']: issues.append('empty_or_missing_display_size')
    times=[]
    for side in ('bid','ask'):
        v=record[side+'_time']
        if v is None: issues.append('missing_'+side+'_time');continue
        t=utc(v);times.append(t);age=(now-t).total_seconds()
        if age < 0: issues.append('future_'+side+'_time')
        elif age > max_age_seconds: issues.append('stale_'+side)
    if len(times)==2 and abs((times[0]-times[1]).total_seconds()) > max_side_skew_seconds: issues.append('asynchronous_sides')
    return {'quote_data_checks_passed':not issues,'issues':issues,
            'actionable_trade_approved':False,'remaining':'deliverables, entitlement proof, thesis, costs and independent review remain separate'}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CaptureError('redirect_refused')


def headers(provider, env):
    values=[env.get(k) for k in CREDENTIALS[provider]]
    if any(not v for v in values): raise CaptureError('credentials_unavailable')
    if any(any(ord(c)<32 for c in v) for v in values): raise CaptureError('invalid_credential')
    if provider=='tradier': return {'Authorization':'Bearer '+values[0],'Accept':'application/json'}
    return {'APCA-API-KEY-ID':values[0],'APCA-API-SECRET-KEY':values[1],'Accept':'application/json'}


def fetch(provider, endpoint, params, env=os.environ, *, opener=None, retries=1):
    if endpoint not in ENDPOINTS.get(provider,()): raise CaptureError('endpoint_not_allowlisted')
    auth=headers(provider,env)
    req=Request(endpoint+'?'+urlencode(params),headers=auth,method='GET')
    client=opener or build_opener(NoRedirect())
    for attempt in range(retries+1):
        try:
            with client.open(req,timeout=8) as response:
                final=urlsplit(response.geturl());expected=urlsplit(endpoint)
                if (final.scheme,final.netloc,final.path)!=(expected.scheme,expected.netloc,expected.path): raise CaptureError('response_origin_changed')
                raw=response.read(MAX_BYTES+1)
                if len(raw)>MAX_BYTES: raise CaptureError('response_too_large')
                data=decode(raw)
                return data,hashlib.sha256(raw).hexdigest()
        except HTTPError as exc:
            code=exc.code
            if code in (401,403): raise CaptureError('authentication_or_entitlement_failed') from None
            if code in (429,500,502,503,504) and attempt < retries:
                time.sleep(0.25);continue
            raise CaptureError('http_'+str(code)) from None
        except (URLError,TimeoutError,OSError):
            if attempt < retries: time.sleep(0.25);continue
            raise CaptureError('transient_network_exhausted') from None
    raise CaptureError('request_failed')


def scrub(value, secrets):
    if isinstance(value,dict):
        result={}
        for k,v in value.items():
            key=scrub(k,secrets)
            if key in result:
                base=key;counter=1
                while key in result:
                    key=base+'__redacted_key_collision_'+str(counter);counter+=1
            result[key]=scrub(v,secrets)
        return result
    if isinstance(value,list): return [scrub(v,secrets) for v in value]
    if isinstance(value,str):
        for secret in secrets:
            if secret:value=value.replace(secret,'[REDACTED]')
    return value


def capture(config, *, env=os.environ, fetcher=fetch):
    if set(config)!={'underlying','contracts','providers','policy'}: raise CaptureError('invalid_config_keys')
    underlying=config['underlying'];contracts=config['contracts'];providers=config['providers'];policy=config['policy']
    if not isinstance(underlying,str) or not re.fullmatch(r'[A-Z]{1,6}(?:\.[A-Z])?',underlying): raise CaptureError('invalid_underlying')
    if not isinstance(contracts,list) or not 1<=len(contracts)<=20 or len(set(contracts))!=len(contracts): raise CaptureError('invalid_contract_scope')
    for c in contracts:
        parsed=contract(c)
        if parsed['canonical_id'] != c:raise CaptureError('canonical_compact_occ_required')
        if parsed['root'] != underlying:raise CaptureError('explicit_root_mapping_not_supported')
    if not isinstance(providers,list) or not 1<=len(providers)<=2 or not all(isinstance(p,dict) for p in providers): raise CaptureError('invalid_provider_scope')
    if len({p.get('provider') for p in providers})!=len(providers): raise CaptureError('duplicate_provider')
    if set(policy)!={'max_quote_age_seconds','max_side_skew_seconds','max_stock_option_skew_seconds','price_absolute_tolerance','price_relative_tolerance'}:raise CaptureError('invalid_policy')
    for k in ('max_quote_age_seconds','max_side_skew_seconds','max_stock_option_skew_seconds'):
        if type(policy[k]) is not int or not 0<policy[k]<=300:raise CaptureError('invalid_time_policy')
    for k in ('price_absolute_tolerance','price_relative_tolerance'):
        if policy[k] is None:raise CaptureError('missing_price_tolerance')
        money(policy[k])
    if Decimal(str(policy['price_relative_tolerance']))>1:raise CaptureError('invalid_relative_tolerance')
    output={'version':VERSION,'started_at':iso(datetime.now(timezone.utc)),'status':'collecting',
            'actionable_trade_approved':False,'providers':[],'comparisons':[],'policy':policy,
            'configuration_is_not_entitlement_proof':True}
    for p in providers:
        item={'provider':p.get('provider'),'status':'failed','records':[],'errors':[],'responses':[]}
        try:
            name=p['provider']
            if name not in ENDPOINTS:raise CaptureError('provider_not_allowlisted')
            allowed={'provider','feed','stock_feed','entitlement_ref','epoch_unit'}
            if set(p)-allowed:raise CaptureError('unknown_provider_config_key')
            feed=p.get('feed')
            if name=='tradier' and feed!='consolidated_realtime':raise CaptureError('tradier_live_feed_required')
            if name=='alpaca' and feed not in ('opra','indicative'):raise CaptureError('invalid_alpaca_feed')
            if not isinstance(p.get('entitlement_ref'),str) or not p['entitlement_ref'].strip():raise CaptureError('entitlement_reference_required')
            item['entitlement_ref']=p['entitlement_ref'];item['feed']=feed
            requests=[(ENDPOINTS[name][0],contracts+[underlying],{'symbols':','.join(contracts+[underlying]),'greeks':'false','includeLotSize':'true'},feed)] if name=='tradier' else [
                (ENDPOINTS[name][0],contracts,{'symbols':','.join(contracts),'feed':feed},feed),
                (ENDPOINTS[name][1],[underlying],{'symbols':underlying,'feed':p.get('stock_feed','sip')},p.get('stock_feed','sip'))]
            if name=='alpaca' and p.get('stock_feed','sip') not in ('sip','iex'):raise CaptureError('invalid_stock_feed')
            for endpoint,scope,params,thisfeed in requests:
                try:
                    payload,digest=fetcher(name,endpoint,params,env)
                    retrieved=iso(datetime.now(timezone.utc))
                    normalized=normalize(name,payload,scope,retrieved_at=retrieved,feed=thisfeed,epoch_unit=p.get('epoch_unit'))
                    item['records'].extend(normalized['records']);item['errors'].extend(normalized['errors'])
                    item['responses'].append({'endpoint':endpoint,'retrieved_at':retrieved,'response_sha256':digest,'response':payload})
                except CaptureError as exc:item['errors'].append({'scope':scope,'code':str(exc)})
            item['status']='captured' if len(item['records'])==len(contracts)+1 and not item['errors'] else 'partial' if item['records'] else 'failed'
        except (CaptureError,KeyError) as exc:item['errors'].append({'code':str(exc) if isinstance(exc,CaptureError) else 'invalid_provider_config'})
        output['providers'].append(item)
    now=datetime.now(timezone.utc);state=session_state(now)
    for p in output['providers']:
        for r in p['records']:
            r['checks']=assess(r,now=now,max_age_seconds=policy['max_quote_age_seconds'],max_side_skew_seconds=policy['max_side_skew_seconds'],session=state)
        stock=next((r for r in p['records'] if r['symbol']==underlying),None)
        for r in p['records']:
            if r['contract'] and stock:
                if not stock['checks']['quote_data_checks_passed']:
                    r['checks']['issues'].append('underlying_quote_ineligible');r['checks']['quote_data_checks_passed']=False
                rt=[utc(r[k]) for k in ('bid_time','ask_time') if r[k]];st=[utc(stock[k]) for k in ('bid_time','ask_time') if stock[k]]
                skew=max((abs((a-b).total_seconds()) for a in rt for b in st),default=None)
                r['stock_option_skew_seconds']=skew
                if skew is None or skew>policy['max_stock_option_skew_seconds']:
                    r['checks']['issues'].append('stock_option_unsynchronized');r['checks']['quote_data_checks_passed']=False
            elif r['contract']:
                r['checks']['issues'].append('underlying_quote_missing');r['checks']['quote_data_checks_passed']=False
    if len(output['providers'])==2:
        a,b=output['providers']
        for symbol in contracts+[underlying]:
            ra=next((r for r in a['records'] if r['symbol']==symbol),None);rb=next((r for r in b['records'] if r['symbol']==symbol),None)
            for side in ('bid','ask'):
                status='unavailable';diff=None
                if ra and rb and ra[side] is not None and rb[side] is not None:
                    va,vb=Decimal(ra[side]),Decimal(rb[side]);diff=format(va-vb,'f')
                    skew=abs((utc(ra[side+'_time'])-utc(rb[side+'_time'])).total_seconds()) if ra[side+'_time'] and rb[side+'_time'] else None
                    if not ra['checks']['quote_data_checks_passed'] or not rb['checks']['quote_data_checks_passed']:status='ineligible_quote_data'
                    elif skew is None or skew>policy['max_side_skew_seconds']:status='asynchronous_sources'
                    elif ra['feed']=='indicative' or rb['feed']=='indicative':status='incomparable_feed'
                    else:
                        tol=max(Decimal(str(policy['price_absolute_tolerance'])),Decimal(str(policy['price_relative_tolerance']))*max(va,vb))
                        status='shared_upstream_quote_consistency' if abs(va-vb)<=tol else 'disagreement'
                output['comparisons'].append({'symbol':symbol,'side':side,'status':status,'signed_difference':diff,'not_independent_market_confirmation':True})
    output['completed_at']=iso(now);output['session_state']=state
    output['status']='captured_data_only' if all(p['status']=='captured' for p in output['providers']) else 'partial' if any(p['records'] for p in output['providers']) else 'blocked'
    secrets=[env.get(k,'') for ks in CREDENTIALS.values() for k in ks]
    return scrub(output,secrets)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--config',required=True);ap.add_argument('--output',required=True);a=ap.parse_args()
    try:result=capture(decode(Path(a.config).read_bytes()))
    except (ValueError,TypeError) as exc:result={'version':VERSION,'status':'error','code':str(exc) if isinstance(exc,CaptureError) else 'invalid_input','actionable_trade_approved':False}
    dest=Path(a.output);dest.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=dest.parent,prefix=dest.name+'.');os.close(fd)
    try:Path(tmp).write_text(json.dumps(result,indent=2,allow_nan=False));os.replace(tmp,dest)
    finally:
        if Path(tmp).exists():Path(tmp).unlink()
    print(json.dumps({'status':result['status'],'output':str(dest)}))
    return 0 if result['status']=='captured_data_only' else 2

if __name__=='__main__':raise SystemExit(main())
