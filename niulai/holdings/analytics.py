#!/usr/bin/env python3
"""Deterministic, account/currency-scoped holdings analytics. No network or credentials."""
import argparse, hashlib, json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

D = Decimal

def num(v):
    if v is None or isinstance(v, bool): return None
    try:
        x=D(str(v))
        return x if x.is_finite() else None
    except (InvalidOperation, ValueError): return None

def total(rows, key):
    values=[num(r.get(key)) for r in rows]
    return sum(values,D(0)) if all(v is not None for v in values) else None

def pct(a,b): return a / b * 100 if a is not None and b is not None and b>0 else None

def ratio(a,b): return a/b if a is not None and b is not None and b>0 else None

def taxonomy_map(t):
    p=t.get('positions', t.get('securities',{}))
    if isinstance(p,list):
        if len({r['symbol'] for r in p}) != len(p): raise ValueError('duplicate_taxonomy_symbol')
        return {r['symbol']:r for r in p}
    return p

def breakdown(rows, key, denominator, multi=False, exposure=False):
    groups=defaultdict(list)
    for r in rows:
        names=r.get(key) or (['未分类'] if multi else '未分类')
        if not multi: names=[names]
        for n in dict.fromkeys(names): groups[str(n)].append(r)
    out=[]
    for name,rr in groups.items():
        k='proxy_exposure' if exposure else 'marketValue'
        vals=[num(r.get(k)) for r in rr]
        known=sum((abs(v) for v in vals if v is not None),D(0)) if any(v is not None for v in vals) else None
        out.append(dict(name=name,value=known,pct=pct(known,denominator),count=len(rr),
            unrealized_pnl=total(rr,'unrealizedPnl'),daily_pnl=total(rr,'dailyPnl'),
            known_value_count=sum(v is not None for v in vals),value_complete=all(v is not None for v in vals)))
    return sorted(out,key=lambda r:r['value'] if r['value'] is not None else D('-1'),reverse=True)

def build(holdings, assets, taxonomy):
    tm=taxonomy_map(taxonomy)
    amap={a.get('accountRef'):a for a in assets.get('accountResults',[]) if a.get('accountRef')}
    asset_ref_counts=Counter(a.get('accountRef') for a in assets.get('accountResults',[]))
    holding_ref_counts=Counter(a.get('accountRef') for a in holdings.get('accountResults',[]))
    out={'schema_version':2,'generated_at':datetime.now(timezone.utc).isoformat(),
         'classification_asof':taxonomy.get('generated_at_utc'),
         'source_times':{'holdings_query':[a.get('queryCompletedAt') for a in holdings.get('accountResults',[])],
                         'assets_query':[a.get('queryCompletedAt') for a in assets.get('accountResults',[])],
                         'quote_time':None},
         'limitations':['查询时间不等于行情时间；源未提供逐笔行情时点。',
          '行业/细分是可复核分析分类，非官方GICS；多主题标签相互重叠，不应相加。',
          '日目标倍率换算为一日方向敞口代理，不是实测beta、长期收益倍数、衍生品delta或完整穿透。',
          '未把持有期浮盈亏、资产净值变化或当前股数乘涨跌当作当日盈亏。'], 'accounts':[]}
    for i,a in enumerate(holdings.get('accountResults',[]),1):
        asset=amap.get(a.get('accountRef'),{})
        valid_asset=bool(asset and asset_ref_counts[a.get('accountRef')]==1 and asset.get('ok') is True and asset.get('sourceReadStatus')=='complete' and asset.get('accountIdentityChecked') is True)
        raw_positions=a.get('positions') or []
        keys=[(r.get('currency'),'contract',str(r['contractId'])) if r.get('contractId') else (r.get('currency'),'terms',r.get('symbol'),r.get('securityType'),r.get('expiry'),r.get('strike'),r.get('putCall')) for r in raw_positions]
        integrity_errors=[]
        if not a.get('accountRef') or holding_ref_counts[a.get('accountRef')]!=1: integrity_errors.append('missing_or_duplicate_account_identity')
        if a.get('accountIdentityChecked') is not True: integrity_errors.append('holdings_identity_unverified')
        if len(keys)!=len(set(keys)): integrity_errors.append('duplicate_position_identity')
        summary=asset.get('summary',{}) if valid_asset else {}
        base=summary.get('currency')
        amounts=summary.get('amounts',{})
        groups=defaultdict(list)
        for p in (a.get('positions') or []): groups[p.get('currency') or '币种未知'].append(p)
        if not groups: groups[base or '币种未知']=[]
        for currency,pp in groups.items():
            rr=[]
            for p in pp:
                meta=tm.get(p.get('symbol'),{})
                lev=num(meta.get('daily_leverage'))
                mv=num(p.get('marketValue'))
                # Never infer leverage from ticker or securityType.
                sector=meta.get('primary_sector') or '未分类'
                row={**p,'sector':sector,'subindustry':meta.get('subindustry') or '未分类',
                    'themes':meta.get('themes') or [],'underlying':meta.get('underlying') or p.get('symbol'),
                    'daily_leverage':lev,'classification_confidence':meta.get('confidence'),
                    'source_refs':meta.get('sources',[]),'classification_notes':meta.get('notes',[]),
                    'instrument_type':meta.get('instrument_type','未知'), 'flags':meta.get('flags',[]),
                    'exposure_basis':meta.get('exposure_basis'), 'lookthrough_status':meta.get('lookthrough_status'),
                    'proxy_exposure':mv*lev if mv is not None and lev is not None else None,
                    'dailyPnl':None}
                row['leverage_bucket']='未知' if lev is None else ('反向 '+str(lev)+'x' if lev<0 else str(lev.normalize())+'x')
                rr.append(row)
            scope_complete=not integrity_errors and isinstance(a.get('positions'),list) and a.get('ok') is True and a.get('sourceReadStatus')=='complete'
            complete_mv=scope_complete and currency!='币种未知' and all(num(r.get('marketValue')) is not None for r in rr)
            gross=sum((abs(num(r['marketValue'])) for r in rr if num(r.get('marketValue')) is not None),D(0))
            net=total(rr,'marketValue') if scope_complete and currency!='币种未知' else None
            same_ccy=valid_asset and base==currency and currency!='币种未知'
            nav=num(amounts.get('netLiquidation')) if same_ccy else None
            cash=num(amounts.get('cash')) if same_ccy else None
            daily=None  # Daily values require the session-bound enrichment gate.
            lev_known=[r for r in rr if r['proxy_exposure'] is not None]
            known_mv=sum((abs(num(r['marketValue'])) for r in lev_known),D(0))
            proxy_gross=sum((abs(r['proxy_exposure']) for r in lev_known),D(0))
            proxy_net=sum((r['proxy_exposure'] for r in lev_known),D(0))
            exposure_complete=complete_mv and len(lev_known)==len(rr)
            for r in rr:
                mv=num(r.get('marketValue'))
                r['weight_pct']=pct(abs(mv),gross) if mv is not None and currency!='币种未知' else None
                r['nav_weight_pct']=pct(mv,nav)
            ranked=sorted(rr,key=lambda r:abs(num(r.get('marketValue')) or D(0)),reverse=True)
            weights=[abs(num(r['marketValue']))/gross for r in ranked] if complete_mv and gross>0 else []
            hhi=sum((w*w for w in weights),D(0)) if weights else None
            lev_cap=sum((abs(num(r['marketValue'])) for r in lev_known if abs(r['daily_leverage'])>1),D(0))
            def top(n): return sum(weights[:n])*100 if weights else None
            notes=[]
            if any(not tm.get(r.get('symbol')) for r in rr): notes.append('存在未分类证券，已保留在未分类分组。')
            if not complete_mv: notes.append('部分市值缺失，金额图为已知子集；全持仓集中度与杠杆率不可完整判断。')
            if not exposure_complete: notes.append('部分倍率或市值未核实：敞口图只含已知部分，完整敞口/NAV保持未知。')
            if daily is None: notes.append('当日P&L未由账户接口提供；日报不将持有期浮盈亏替代当日收益。')
            if not all(r['dailyPnl'] is not None for r in rr): notes.append('逐仓当日P&L缺失，行业当日贡献及日内赢家/输家暂不可核验。')
            if nav is None: notes.append('缺同账户同币种有效NAV，现金/净值和敞口/净值比例保持未知。')
            if asset.get('queryCompletedAt') and a.get('queryCompletedAt'):
                try: skew=abs((datetime.fromisoformat(asset['queryCompletedAt'].replace('Z','+00:00'))-datetime.fromisoformat(a['queryCompletedAt'].replace('Z','+00:00'))).total_seconds())
                except ValueError: skew=None
            else: skew=None
            metrics={'nav':nav,'cash':cash,'buying_power':num(amounts.get('buyingPower')) if same_ccy else None,
                'positions_value':net,'gross_positions_value':gross if complete_mv else None,
                'unrealized_pnl':total(rr,'unrealizedPnl') if scope_complete and currency!='币种未知' else None,'daily_pnl':daily,'daily_pnl_status':'source_reported' if daily is not None else 'unavailable',
                'cash_pct':pct(cash,nav),'positions_nav_pct':pct(net,nav),
                'other_net_assets':nav-cash-net if all(v is not None for v in (nav,cash,net)) else None,
                'other_net_assets_pct':pct(nav-cash-net,nav) if all(v is not None for v in (nav,cash,net)) else None,
                'top1_pct':top(1),'top5_pct':top(5),'top10_pct':top(10),
                'hhi':hhi*10000 if hhi is not None else None,'effective_n':1/hhi if hhi else None,
                'gross_nav_multiple':ratio(gross,nav) if complete_mv else None,
                'embedded_gross_nav_multiple':ratio(proxy_gross,nav) if exposure_complete else None,
                'embedded_net_nav_multiple':ratio(proxy_net,nav) if exposure_complete else None,
                'known_proxy_gross_exposure':proxy_gross if currency!='币种未知' else None,'known_proxy_net_exposure':proxy_net if currency!='币种未知' else None,
                'leverage_coverage_pct':pct(known_mv,gross) if currency!='币种未知' else None,'leveraged_capital_pct':pct(lev_cap,gross) if currency!='币种未知' else None,
                'embedded_multiple_on_holdings':ratio(proxy_gross,gross) if exposure_complete else None,
                'financing_balance':num(amounts.get('reportedLoanValue')) if same_ccy else None}
            daily_valid=[r for r in rr if r['dailyPnl'] is not None]
            pnl_valid=[r for r in rr if num(r.get('unrealizedPnl')) is not None]
            result={'accountRef':a.get('accountRef'),'label':f'账户 {i}','account_type':a.get('sourceAccountMetadata',{}).get('account_type','未知'),
                'currency':currency,'metrics':metrics,'holdings':ranked,
                'sector_breakdown':breakdown(rr,'sector',gross) if currency!='币种未知' else [],
                'subindustry_breakdown':breakdown(rr,'subindustry',gross) if currency!='币种未知' else [],
                'themes':breakdown(rr,'themes',gross,multi=True) if currency!='币种未知' else [],
                'underlying_exposure':breakdown(rr,'underlying',proxy_gross,exposure=True) if currency!='币种未知' else [],
                'leverage_breakdown':breakdown(rr,'leverage_bucket',gross) if currency!='币种未知' else [],
                'top_gainers':sorted([r for r in pnl_valid if num(r['unrealizedPnl'])>0],key=lambda r:num(r['unrealizedPnl']),reverse=True)[:5],
                'top_losers':sorted([r for r in pnl_valid if num(r['unrealizedPnl'])<0],key=lambda r:num(r['unrealizedPnl']))[:5],
                'daily_top_gainers':sorted([r for r in daily_valid if r['dailyPnl']>0],key=lambda r:r['dailyPnl'],reverse=True)[:5],
                'daily_top_losers':sorted([r for r in daily_valid if r['dailyPnl']<0],key=lambda r:r['dailyPnl'])[:5],
                'notes':notes,'quality':{'row_count':len(rr),'classified_count':sum(r['sector']!='未分类' for r in rr),
                    'daily_pnl_rows':len(daily_valid),'market_value_complete':complete_mv,
                    'whole_portfolio_verified':a.get('coverage',{}).get('wholePortfolioVerified') is True,
                    'pagination_completeness_verified':a.get('coverage',{}).get('paginationCompletenessVerified') is True,
                    'requested_security_types':a.get('coverage',{}).get('requestedSecurityTypes',[]),
                    'holdings_read_status':a.get('sourceReadStatus'),'assets_read_status':asset.get('sourceReadStatus'),
                    'asset_identity_matched':valid_asset,'currency_matched':same_ccy,'query_skew_seconds':skew,
                    'holdings_query_at':a.get('queryCompletedAt'),'assets_query_at':asset.get('queryCompletedAt'),
                    'quote_time':None,'exposure_complete':exposure_complete}}
            result['quality']['integrity_errors']=integrity_errors
            if integrity_errors:
                result['notes'].append('来源身份或重复持仓校验失败，停用持仓汇总与风险比例；原始行保留供排查。')
                for key in metrics:
                    if key not in ('nav','cash','buying_power','cash_pct','financing_balance','daily_pnl_status'): metrics[key]=None
                for row in rr:
                    row['weight_pct']=None; row['nav_weight_pct']=None; row['proxy_exposure']=None
                for key in ('sector_breakdown','subindustry_breakdown','themes','underlying_exposure','leverage_breakdown','top_gainers','top_losers'): result[key]=[]
            out['accounts'].append(result)
    return out

def enrich(data, holdings, prime, history):
    """Attach separate source counters/history; never relabel them current session P&L."""
    from zoneinfo import ZoneInfo
    refs={f"账户 {i}":a.get('accountRef') for i,a in enumerate(holdings.get('accountResults',[]),1)}
    pm={a.get('accountRef'):a for a in prime.get('accountResults',[]) if a.get('ok') is True}
    hm={a.get('accountRef'):a for a in history.get('accountResults',[]) if a.get('ok') is True}
    for account in data['accounts']:
        ref=refs.get(account['label']);p=pm.get(ref,{});h=hm.get(ref,{})
        segs=[v for v in p.get('segments',[]) if v.get('currency')==account['currency']]
        sec=next((v for v in segs if v.get('category')=='S'),{})
        am=sec.get('amounts',{})
        account['broker_counters']={'securities_today_pnl':num(am.get('reportedTodayPnl')),
            'status':'source_counter_not_aligned_to_completed_session',
            'query_at':p.get('queryCompletedAt'),'asset_update_epoch_ms':p.get('sourceUpdateTime'),
            'reported_securities_unrealized_pnl':num(am.get('reportedUnrealizedPnl')),
            'position_sum_difference':num(am.get('reportedUnrealizedPnl'))-account['metrics']['unrealized_pnl']
              if num(am.get('reportedUnrealizedPnl')) is not None and account['metrics']['unrealized_pnl'] is not None else None}
        account['historical_nav']=[]
        if h.get('currency')!=account['currency']:continue
        prior=None
        valid_history=[v for v in h.get('history',[]) if num(v.get('dateEpochMs')) is not None]
        epochs=[num(v['dateEpochMs']) for v in valid_history]
        if len(set(epochs))!=len(epochs):
            account['notes'].append('历史日期重复，已停用历史变动计算。');continue
        for v in sorted(valid_history,key=lambda v:num(v['dateEpochMs'])):
            epoch=num(v.get('dateEpochMs'));nav=num(v.get('asset'));dep=num(v.get('deposit'));wd=num(v.get('withdrawal'))
            if epoch is None or nav is None:continue
            day=datetime.fromtimestamp(float(epoch/1000),timezone.utc).astimezone(ZoneInfo('America/New_York')).date().isoformat()
            change=nav-prior['nav'] if prior and dep==0 and wd==0 else None
            point={'date':day,'nav':nav,'deposit':dep,'withdrawal':wd,'flow_adjusted_nav_change':change,
                'prior_date':prior['date'] if prior else None,'basis':'相邻历史净值差，仅在已报告入/出金均为零时计算；非零流量口径未核实不计算。不是当前交易日收益，未归因逐仓'}
            account['historical_nav'].append(point);prior=point
        if account['historical_nav']:
            last=account['historical_nav'][-1]
            account['notes'].append('历史净值序列最近仅到 '+last['date']+'；历史变化与当前日报日盈亏分开，不能按当前仓位归因。')
    return data

def serial(v):
    if isinstance(v,D): return float(v)
    raise TypeError(type(v).__name__)

def main():
    p=argparse.ArgumentParser(); here=Path(__file__).parent
    for n in ('holdings','assets','taxonomy'): p.add_argument('--'+n,type=Path,default=here/(n+'_latest.json' if n!='taxonomy' else 'taxonomy.json'))
    p.add_argument('--output',type=Path,default=here/'analytics.json'); p.add_argument('--prime',type=Path,default=here/'prime_assets_latest.json'); p.add_argument('--history',type=Path,default=here/'analytics_latest.json'); a=p.parse_args()
    inputs={n:getattr(a,n) for n in ('holdings','assets','taxonomy')}
    result=build(*(json.loads(inputs[n].read_text()) for n in inputs))
    result=enrich(result,json.loads(a.holdings.read_text()),json.loads(a.prime.read_text()) if a.prime.exists() else {},json.loads(a.history.read_text()) if a.history.exists() else {})
    try:
        from session_date import latest_completed_session
        result['report_session']=latest_completed_session()
        result['latest_completed_session']=result['report_session']['date']
        result['report_session_status']='calendar_verified'
    except (ImportError,ValueError,RuntimeError) as e:
        result['latest_completed_session']=None
        result['report_session_status']='calendar_unavailable'
        result['calendar_error_type']=type(e).__name__
    from daily_performance import enrich_daily
    enrich_daily(result,json.loads(a.holdings.read_text()),json.loads(a.assets.read_text()),json.loads(a.history.read_text()) if a.history.exists() else {})
    result['input_sha256']={n:hashlib.sha256(p.read_bytes()).hexdigest() for n,p in inputs.items()}
    for n in ('prime','history'):
        f=getattr(a,n)
        if f.exists():result['input_sha256'][n]=hashlib.sha256(f.read_bytes()).hexdigest()
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=serial)+'\n')
    print(json.dumps({'groups':len(result['accounts']),'rows':sum(len(x['holdings']) for x in result['accounts']),'output':str(a.output)}))
if __name__=='__main__': main()
