"""Session-bound daily attribution. No fetches, guessed sessions, or price proxies."""
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from datetime import datetime, time
from zoneinfo import ZoneInfo


def number(value):
    if value is None or isinstance(value, bool): return None
    try:
        value = Decimal(str(value))
        return value if value.is_finite() else None
    except (InvalidOperation, ValueError): return None


def verified_value(row, session):
    # A query timestamp, weekend previous-close field, or undocumented today counter
    # is not a trading-session identity. Only source-bound dated evidence qualifies.
    evidence = row.get('dailyPnlEvidence') or {}
    if not session or evidence.get('session') != session: return None
    if evidence.get('basis') != 'regular_session' or not evidence.get('source_ref'): return None
    if evidence.get('source_field') != 'reportedTodayPnl': return None
    return number(row.get('reportedTodayPnl'))


def history_daily_points(history_account, candidate_dates):
    """Broker cumulative day changes, corroborated by NAV, with exact prior XNYS date."""
    from session_date import latest_completed_session
    if not (history_account.get('accountRef') and history_account.get('ok') is True and history_account.get('sourceReadStatus') == 'complete' and history_account.get('currency') and history_account.get('segment') == 'SEC' and history_account.get('endpoint') == 'analytics_asset'): return {}
    by_date = {}; duplicates = set()
    for row in history_account.get('history', []):
        epoch = number(row.get('dateEpochMs'))
        if epoch is None or epoch != epoch.to_integral_value(): continue
        try: day = datetime.fromtimestamp(int(epoch)/1000, ZoneInfo('America/New_York')).date().isoformat()
        except (ValueError, OverflowError, OSError): continue
        if day in by_date: duplicates.add(day)
        by_date[day] = row
    output = {}
    for day in candidate_dates:
        try:
            midnight = datetime.combine(datetime.fromisoformat(day).date(), time.min, tzinfo=ZoneInfo('America/New_York'))
            prior = latest_completed_session(midnight)['date']
        except (ValueError, RuntimeError, ImportError): continue
        if day in duplicates or prior in duplicates or day not in by_date or prior not in by_date: continue
        r, p = by_date[day], by_date[prior]
        values = [number(x.get(k)) for x in (r,p) for k in ('asset','pnl','deposit','withdrawal')]
        if any(x is None for x in values): continue
        if any(number(x[k]) != 0 for x in (r,p) for k in ('deposit','withdrawal')): continue
        nav_delta = number(r['asset']) - number(p['asset'])
        pnl_delta = number(r['pnl']) - number(p['pnl'])
        if abs(nav_delta-pnl_delta) > Decimal('0.01'): continue
        output[day] = {'pnl':pnl_delta,'prior_date':prior,'nav_change':nav_delta,
            'cumulative_pnl_change':pnl_delta,'reconciliation_tolerance':'0.01',
            'query_at':history_account.get('queryCompletedAt'),'endpoint':history_account.get('endpoint'),
            'currency':history_account.get('currency'),'segment':history_account.get('segment')}
    return output


def enrich_daily(data, holdings, assets, history=None, now=None):
    preferred_session = data.get('latest_completed_session')
    history_accounts = (history or {}).get('accountResults', [])
    history_refs = Counter(a.get('accountRef') for a in history_accounts)
    hmap = {a.get('accountRef'): a for a in history_accounts}
    try:
        from session_date import completed_sessions
        candidate_dates = [s['date'] for s in completed_sessions(now=now,limit=5) if preferred_session and s['date'] <= preferred_session]
    except (ImportError,ValueError,RuntimeError): candidate_dates = []
    source_accounts = holdings.get('accountResults', [])
    refs = Counter(a.get('accountRef') for a in source_accounts)
    asset_accounts = assets.get('accountResults', [])
    asset_refs = Counter(a.get('accountRef') for a in asset_accounts)
    amap = {a.get('accountRef'): a for a in asset_accounts}
    for account in data['accounts']:
        session = preferred_session
        history_point = None
        ref = account.get('accountRef')
        currency = account['currency']
        src = next((a for a in source_accounts if a.get('accountRef') == ref), {})
        complete = bool(ref and refs[ref] == 1 and src.get('ok') is True
                        and src.get('accountIdentityChecked') is True
                        and src.get('sourceReadStatus') == 'complete'
                        and isinstance(src.get('positions'), list) and currency != '币种未知')
        preferred_asset = amap.get(ref,{})
        ps = preferred_asset.get('summary',{})
        preferred_value = verified_value(ps.get('amounts',{}),preferred_session) if (ref and asset_refs[ref] == 1 and preferred_asset.get('ok') is True and preferred_asset.get('sourceReadStatus') == 'complete' and preferred_asset.get('accountIdentityChecked') is True and ps.get('currency') == currency) else None
        h = hmap.get(ref,{})
        if (ref and history_refs[ref] == 1 and h.get('ok') is True and h.get('sourceReadStatus') == 'complete'
                and h.get('currency') == currency and currency != '币种未知' and h.get('segment') == 'SEC'
                and h.get('endpoint') == 'analytics_asset'):
            points = history_daily_points(h,candidate_dates)
            chosen = next((d for d in candidate_dates if d in points),None)
            if chosen and preferred_value is None:
                session = chosen; history_point = points[chosen]
        rows = account['holdings']
        def key(r):
            return ('contract',r.get('currency'),r['contractId']) if r.get('contractId') else ('fallback',r.get('symbol'),r.get('securityType'),r.get('expiry'),r.get('strike'),r.get('putCall'))
        duplicates = Counter(key(r) for r in rows)
        groups = defaultdict(list)
        for r in rows:
            v = verified_value(r, session) if complete and duplicates[key(r)] == 1 and r.get('currency') == currency else None
            r['dailyPnl'] = v
            groups[r['symbol']].append(r)
        positions = []
        for symbol, rr in groups.items():
            valid = [r['dailyPnl'] for r in rr if r['dailyPnl'] is not None]
            value = sum(valid, Decimal(0)) if len(valid) == len(rr) else None
            positions.append({'symbol':symbol,'sector':rr[0]['sector'],'pnl':value,
                              'status':'verified' if value is not None else 'unavailable'})
        positions.sort(key=lambda r: (r['pnl'] is None, -(r['pnl'] or Decimal(0)), r['symbol']))
        sectors = []
        for sector in sorted({r['sector'] for r in positions}):
            members = [r for r in positions if r['sector'] == sector]
            value = sum((r['pnl'] for r in members),Decimal(0)) if all(r['pnl'] is not None for r in members) else None
            sectors.append({'sector':sector,'pnl':value,'count':len(members)})
        asset = amap.get(ref,{})
        summary = asset.get('summary',{})
        aggregate = verified_value(summary.get('amounts',{}), session) if (ref and asset_refs[ref] == 1
            and asset.get('ok') is True and asset.get('accountIdentityChecked') is True
            and asset.get('sourceReadStatus') == 'complete'
            and summary.get('currency') == currency and currency != '币种未知') else None
        aggregate_basis = 'source_dated_regular_session'
        if aggregate is None and history_point is not None:
            aggregate = history_point['pnl']; aggregate_basis = 'account_history_daily'
        verified = sum(r['pnl'] is not None for r in positions)
        status = 'verified' if aggregate is not None and complete and verified == len(positions) else ('partial' if aggregate is not None or verified else 'unavailable')
        account['daily_performance'] = {'session':session,'selectedPerformanceSession':session,'preferred_session':preferred_session,
            'aggregate_basis':aggregate_basis,'aggregate_method':'cumulative_pnl_difference_corroborated_by_nav_zero_flows' if history_point else 'reported_dated_daily_pnl',
            'source_asof':session if history_point else None,'source_query_at':history_point.get('query_at') if history_point else None,
            'history_reconciliation':history_point,'position_population':'current_snapshot_not_historical_roster' if history_point else 'current_snapshot',
            'fallback_reason':'最近已完成交易日的数据尚未返回，使用有完整相邻交易日记录的最近历史账户表现。' if session != preferred_session else None,
            'status':status,'aggregate_pnl':aggregate,
            'positions':positions,'sectors':sectors,'coverage':{'expected':len(positions),'verified':verified,'missing':len(positions)-verified},
            'position_contribution_total':sum((r['pnl'] for r in positions),Decimal(0)) if complete and positions and verified == len(positions) else None,
            'basis':'账户历史分析口径：累计盈亏逐交易日差分，并与净值差、显式零出入金核对；非美股常规时段盈亏。' if history_point else '来源明确标注交易日的常规时段日盈亏；账户与币种隔离。',
            'limitations':['缺少目标交易日的逐仓盈亏，不能以持有期浮盈、零值或当前股数乘未知日期价差代替。'] if status != 'verified' else []}
        account['metrics'].update(daily_pnl=aggregate,daily_pnl_status=status)
        account['quality']['daily_pnl_rows'] = sum(r['dailyPnl'] is not None for r in rows)
        account['daily_top_gainers'] = sorted([r for r in rows if r['dailyPnl'] is not None and r['dailyPnl']>0],key=lambda r:r['dailyPnl'],reverse=True)[:5]
        account['daily_top_losers'] = sorted([r for r in rows if r['dailyPnl'] is not None and r['dailyPnl']<0],key=lambda r:r['dailyPnl'])[:5]
        # Existing allocation views remain, but cannot leak unbound daily values.
        for name in ('sector_breakdown','subindustry_breakdown','themes','underlying_exposure','leverage_breakdown'):
            for entry in account.get(name,[]): entry['daily_pnl'] = None
        for entry in account.get('sector_breakdown',[]):
            entry['daily_pnl'] = next((s['pnl'] for s in sectors if s['sector'] == entry['name']),None)
    return data


def compute_close_to_close_pnl(case):
    """STK single-currency ledger calculation; missing evidence stays blocked.

    case: security_type='STK', multiplier=1, account_ref, contract_id, currency.
    opening/closing: quantity, price, session, currency, source_ref, account_ref,
      contract_id, price_basis='regular_session_close'.
    executions: side BUY/SELL, quantity (actual decimal units), price, fee,
      currency, timestamp (aware ISO), source_ref (unique execution identity),
      account_ref, contract_id. Exact adjacent XNYS closes are required.
    ledger: complete, source_ref, start_utc, end_utc (previous/target close).
    corporate_actions: status='verified_none', source_ref; splits require a
      separately normalized verified ledger and are deliberately unsupported.
    """
    def blocked(reason): return {'status':'blocked','reason':reason,'gross_pnl':None,'net_pnl':None}
    try:
        currency=case['currency']; o=case['opening']; c=case['closing']; ledger=case['ledger']; ca=case['corporate_actions']
        if case.get('security_type')!='STK' or not currency or number(case.get('multiplier'))!=1:return blocked('unsupported_instrument_or_currency')
        if not case.get('account_ref') or not case.get('contract_id'):return blocked('instrument_or_account_missing')
        def identity(r): return r.get('account_ref')==case['account_ref'] and r.get('contract_id')==case['contract_id']
        if not identity(o) or not identity(c):return blocked('instrument_or_account_mismatch')
        if ledger.get('complete') is not True or not ledger.get('source_ref'):return blocked('ledger_incomplete')
        if ca.get('status')!='verified_none' or not ca.get('source_ref'):return blocked('corporate_actions_unverified_or_unsupported')
        start=datetime.fromisoformat(ledger['start_utc'].replace('Z','+00:00')); end=datetime.fromisoformat(ledger['end_utc'].replace('Z','+00:00'))
        if start.tzinfo is None or end.tzinfo is None or start>=end:return blocked('invalid_window')
        ny=ZoneInfo('America/New_York')
        from session_date import latest_completed_session
        first=latest_completed_session(start);last=latest_completed_session(end)
        previous=latest_completed_session(datetime.combine(end.astimezone(ny).date(),time.min,tzinfo=ny))
        if datetime.fromisoformat(first['close_utc'].replace('Z','+00:00'))!=start or datetime.fromisoformat(last['close_utc'].replace('Z','+00:00'))!=end or previous['date']!=first['date']:return blocked('not_adjacent_xnys_closes')
        if any(r.get('price_basis')!='regular_session_close' for r in (o,c)):return blocked('mark_price_basis_unverified')
        if o.get('session')!=start.astimezone(ny).date().isoformat() or c.get('session')!=end.astimezone(ny).date().isoformat():return blocked('mark_session_mismatch')
        if any(r.get('currency')!=currency or not r.get('source_ref') for r in (o,c)):return blocked('mark_identity_missing')
        oq,op,cq,cp=(number(r[k]) for r,k in ((o,'quantity'),(o,'price'),(c,'quantity'),(c,'price')))
        if any(v is None for v in (oq,op,cq,cp)) or op<0 or cp<0:return blocked('invalid_marks_or_quantities')
        cash=Decimal(0); movement=Decimal(0); fees=Decimal(0); fees_complete=True; seen=set()
        for fill in case['executions']:
            q=number(fill.get('quantity')); p=number(fill.get('price')); fee=number(fill.get('fee')); execution_ref=fill.get('source_ref')
            if not execution_ref or execution_ref in seen:return blocked('execution_identity_missing_or_duplicate')
            seen.add(execution_ref)
            if not identity(fill):return blocked('instrument_or_account_mismatch')
            if q is None or p is None or q<=0 or p<0 or fill.get('currency')!=currency or fill.get('side') not in ('BUY','SELL'):return blocked('invalid_execution')
            stamp=datetime.fromisoformat(fill['timestamp'].replace('Z','+00:00'))
            if stamp.tzinfo is None or not start<stamp<=end:return blocked('execution_outside_window')
            sign=Decimal(1) if fill['side']=='BUY' else Decimal(-1)
            movement+=sign*q;cash-=sign*q*p
            if fee is None:fees_complete=False
            elif fee<0:return blocked('negative_fee_unsupported')
            else:fees+=fee
        if oq+movement!=cq:return blocked('quantity_reconciliation_failed')
        gross=cq*cp-oq*op+cash
        return {'status':'computed_gross_and_net' if fees_complete else 'computed_gross_only','gross_pnl':gross,'net_pnl':gross-fees if fees_complete else None,
                'fees':fees if fees_complete else None,'currency':currency,'previous_session':o['session'],'session':c['session'],
                'basis':'Reconciled stock price and execution contribution, not total account P&L; excludes cash interest, dividends and non-trading flows.',
                'opening_value':oq*op,'closing_value':cq*cp,'trade_cashflow':cash,'quantity_reconciled':True}
    except (KeyError,TypeError,ValueError,InvalidOperation,OverflowError,ImportError,RuntimeError):return blocked('missing_or_invalid_input')
