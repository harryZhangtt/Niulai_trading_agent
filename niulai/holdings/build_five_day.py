"""Frozen-source five-session replay; reverse quantities, independent forward roll, no invented NAV."""
import json,hashlib,copy
from pathlib import Path
from decimal import Decimal as D
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
from daily_performance import compute_close_to_close_pnl,history_daily_points
from daily_return_rate import daily_return_rate
from render_portfolio import render_daily,snapshot_hash
P=Path(__file__).parent;OUT=P/'five_day_daily';NY=ZoneInfo('America/New_York')
def stamp(s):return int(datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()*1000)
def main(out_dir=None, metadata_file=None):
 global OUT
 if out_dir is not None:OUT=Path(out_dir)
 source=json.loads((OUT/'sources.json').read_text(),parse_float=D);e=source['evidence'];h=e['holdings']['result'];ledger=e['transactions']['result'];ref=source['account_ref']
 assert h['ok'] and h['sourceReadStatus']=='complete' and h['accountIdentityChecked'] and h['accountRef']==ref
 assert ledger['ok'] and ledger['paginationComplete'] and ledger['accountRef']==ref and ledger['startEpochMs']==source['start_ms'] and ledger['endEpochMs']==source['end_ms']
 tx=ledger['transactions'];assert len({f['executionIdHash'] for f in tx})==len(tx)
 for name in ['get_position_transfer_records','get_position_transfer_external_records']:assert e[name]['ok'] and e[name]['result']['empty_list_verified'] is True
 actions={s:[] for s in source['symbols']}
 for action in ['split','symbol_change','dividend','delisting']:
  seen=set()
  for key,v in e.items():
   if not key.startswith(action+'_'):continue
   seen.update(v['symbols'])
   if not v['ok'] or v.get('raw',{}).get('code')!=0:
    for symbol in v['symbols']:actions[symbol].append(action+'_unverified')
   elif v['raw'].get('data'):
    for symbol in v['symbols']:actions[symbol].append(action+'_requires_normalization')
  assert seen==set(source['symbols'])
 bars={};duplicate=set()
 for key,v in e.items():
  if not key.startswith('bars_'):continue
  assert v['ok']
  for b in v['result']:
   day=datetime.fromtimestamp(int(b['time'])/1000,NY).date().isoformat();key=(b['symbol'],day)
   if key in bars:duplicate.add(key)
   bars[key]=b
 base=json.loads(Path(metadata_file or P/'analytics.json').read_text());meta={r['symbol']:r for a in base['accounts'] if a['accountRef']==ref for r in a['holdings']};current={r['symbol']:r for r in h['positions']}
 for symbol in set(source['symbols'])-set(current):
  fills=[f for f in tx if f['symbol']==symbol]
  assert fills and len({(f['contractId'],f['currency'],f['securityType']) for f in fills})==1
  f=fills[0];current[symbol]={'symbol':symbol,'contractId':f['contractId'],'currency':f['currency'],'securityType':f['securityType'],'multiplier':'1','quantity':'0'}
  meta[symbol]={'symbol':symbol,'contractId':f['contractId'],'sector':'未分类','daily_leverage':None}
 for r in current.values():assert r['securityType']=='STK' and r['currency']=='USD' and D(r['multiplier'])==1
 def signed(f):return (D(1) if f['side']=='BUY' else D(-1))*D(f['quantity'])
 for f in tx:assert f['securityType']=='STK' and f['currency']=='USD' and f['side'] in ('BUY','SELL') and source['start_ms']<f['executionEpochMs']<=source['end_ms']
 initial={s:D(v['quantity'])-sum((signed(f) for f in tx if f['symbol']==s),D(0)) for s,v in current.items()};forward=initial.copy()
 hist=e.get('history',{}).get('result',{});points=history_daily_points(hist,[s['date'] for s in source['sessions']]) if hist.get('ok') else {};history={datetime.fromtimestamp(int(v['dateEpochMs'])/1000,NY).date().isoformat():v for v in hist.get('history',[])}
 summaries=[];allcases=[];prior=source['prior_session']
 for session in source['sessions']:
  day=session['date'];start,end=stamp(prior['close_utc']),stamp(session['close_utc']);dayfills=[f for f in tx if start<f['executionEpochMs']<=end];results=[];active=[];sectorp=defaultdict(D);sectorm=defaultdict(D);den=D(0);gross=D(0);mark_values=[];exposures=D(0)
  for symbol in sorted(source['symbols']):
   r=current[symbol];fills=[f for f in dayfills if f['symbol']==symbol];cq=D(r['quantity'])-sum((signed(f) for f in tx if f['symbol']==symbol and end<f['executionEpochMs']<=source['end_ms']),D(0));oq=cq-sum((signed(f) for f in fills),D(0))
   assert forward[symbol]==oq,'Reverse/forward quantity mismatch'
   forward[symbol]+=sum((signed(f) for f in fills),D(0));assert forward[symbol]==cq
   if oq==0 and cq==0 and not fills:continue
   metadata=copy.deepcopy(meta.get(symbol,{'symbol':symbol,'sector':'未分类','daily_leverage':None}));metadata['quantity']=str(cq);active.append(metadata)
   ident={'account_ref':ref,'contract_id':r['contractId'],'currency':'USD'};row={'symbol':symbol,'sector':metadata['sector'],'opening_quantity':str(oq),'closing_quantity':str(cq),'fills':len(fills),'session':day,'pnl':None,'pnl_pct':None,'status':'blocked'}
   reasons=list(actions[symbol]);op=bars.get((symbol,prior['date']));cp=bars.get((symbol,day))
   if not op or not cp:reasons.append('missing_dated_bar')
   if (symbol,prior['date']) in duplicate or (symbol,day) in duplicate:reasons.append('duplicate_bar')
   if reasons:row['reason']=';'.join(reasons);results.append(row);continue
   for b in (op,cp):assert D(b['low'])>0 and D(b['low'])<=D(b['close'])<=D(b['high']) and D(b['low'])<=D(b['open'])<=D(b['high'])
   def mark(q,b,date):return dict(ident,quantity=str(q),price=str(b['close']),session=date,price_basis='regular_session_close',source_ref='sources.json:bars:'+symbol+':'+date)
   case=dict(ident,security_type='STK',multiplier='1',opening=mark(oq,op,prior['date']),closing=mark(cq,cp,day),ledger={'complete':True,'source_ref':'sources.json:transactions','start_utc':prior['close_utc'],'end_utc':session['close_utc']},corporate_actions={'status':'verified_none','source_ref':'sources.json:corporate_action; provider-reported absence'},executions=[dict(ident,side=f['side'],quantity=f['quantity'],price=f['price'],fee=f['fee'],timestamp=f['executionTimeUtc'],source_ref=f['executionIdHash']) for f in fills])
   calc=compute_close_to_close_pnl(case);assert calc['gross_pnl'] is not None,calc
   independent=oq*(D(cp['close'])-D(op['close']))+sum((signed(f)*(D(cp['close'])-D(f['price'])) for f in fills),D(0));assert calc['gross_pnl']==independent
   rate=daily_return_rate(case,calc['gross_pnl']);row.update(status='reconstructed_gross',pnl=str(calc['gross_pnl']),pnl_pct=rate['percent'] if rate else None,return_denominator=rate['denominator'] if rate else None,previous_close=str(op['close']),close=str(cp['close']),arithmetic_crosscheck='PASS')
   gross+=calc['gross_pnl'];sectorp[metadata['sector']]+=calc['gross_pnl']
   if rate:den+=D(rate['denominator'])
   mv=abs(cq*D(cp['close']));sectorm[metadata['sector']]+=mv;mark_values.append(mv);exposures+=mv*abs(D(str(metadata['daily_leverage']))) if metadata.get('daily_leverage') is not None else D(0)
   results.append(row);allcases.append(case)
  results.sort(key=lambda r:(r['pnl'] is None,-D(r['pnl']) if r['pnl'] is not None else D(0),r['symbol']));valid=[r for r in results if r['pnl'] is not None];coverage=f'{len(valid)}/{len(results)}';rate=str(gross/den*100) if den>0 and all(r['pnl_pct'] is not None for r in valid) else None
  histpoint=points.get(day);navrow=history.get(day);accountpnl=str(histpoint['pnl']) if histpoint else None;prevnav=history.get(prior['date'],{}).get('asset');accountpct=str(D(accountpnl)/D(prevnav)*100) if accountpnl is not None and prevnav else None
  summary={'session':day,'prior_session':prior['date'],'computed':len(valid),'expected_active':len(results),'gross_pnl':str(gross),'capital_return_pct':rate,'execution_count':len(dayfills),'account_analysis_pnl':accountpnl,'account_analysis_pct':accountpct,'diagnostic_difference':str(gross-D(accountpnl)) if accountpnl is not None else None,'broker_stock_pnl_crosscheck':'UNAVAILABLE','account_comparison':'DIFFERENT_OR_UNCONFIRMED_CUTOFF_AND_NET_BASIS','missing':[{'symbol':r['symbol'],'reason':r.get('reason')} for r in results if r['pnl'] is None]};summaries.append(summary)
  x=copy.deepcopy(base);a=next(a for a in x['accounts'] if a['accountRef']==ref);x['accounts']=[a];x['latest_completed_session']=day;a['holdings']=active;a['label']='实盘 · 历史重建';a['broker_counters']={}
  m=a['metrics'];m.update(nav=float(navrow['asset']) if navrow else None,cash=float(navrow['cashBalance']) if navrow else None,cash_pct=float(D(navrow['cashBalance'])/D(navrow['asset'])*100) if navrow else None,positions_nav_pct=float(D(navrow['grossPositionValue'])/D(navrow['asset'])*100) if navrow else None,other_net_assets_pct=float((D(navrow['asset'])-D(navrow['cashBalance'])-D(navrow['grossPositionValue']))/D(navrow['asset'])*100) if navrow else None)
  marked=sum(mark_values,D(0));m['top5_pct']=float(sum(sorted(mark_values,reverse=True)[:5])/marked*100) if marked else None;m['embedded_gross_nav_multiple']=None # Do not mix regular-close exposures with unconfirmed account-history cutoff.
  a['sector_breakdown']=[{'name':s,'pct':float(v/marked*100)} for s,v in sorted(sectorm.items(),key=lambda z:z[1],reverse=True)] if marked else []
  ordered=sorted(sectorp.items(),key=lambda z:abs(z[1]),reverse=True);shown=dict(ordered[:5]);shown['其他行业（'+str(max(0,len(ordered)-5))+'类）']=sum((v for _,v in ordered[5:]),D(0));assert sum(shown.values())==gross
  histnote=('账户分析日盈亏 '+accountpnl+' 美元；与税费前收盘重建值差额 '+summary['diagnostic_difference']+'，口径/截止点未核实，不算对账通过。') if accountpnl is not None else '券商账户分析缺该日，账户收益率及现金比例留空。'
  a['daily_performance']={'session':day,'preferred_session':day,'selectedPerformanceSession':day,'status':'reconstructed','aggregate_basis':'reconstructed_gross','aggregate_pnl':str(gross),'capital_return_pct':rate,'positions':results,'sectors':[{'sector':s,'pnl':str(v),'session':day} for s,v in sorted(shown.items(),key=lambda z:z[1],reverse=True)],'position_population':'reconstructed_returned_roster','source_asof':source['query_at'],'note':coverage+' 项税费前价格及成交损益；非账户净收益。'+histnote}
  x['source_times']={'holdings_query':source['query_at']};a['source_times']={'holdings_query':source['query_at']};x['five_day_evidence_sha256']=hashlib.sha256((OUT/'sources.json').read_bytes()).hexdigest()
  path=OUT/day;path.mkdir(exist_ok=True);(path/'viewport.json').write_text(json.dumps(x,ensure_ascii=False,indent=2));(path/'result.json').write_text(json.dumps({'summary':summary,'rows':results},ensure_ascii=False,indent=2))
  html=render_daily(x).replace('资金结构 · 快照','资金结构 · 当日账户分析').replace('行业权重 · 快照','行业权重 · 已估值持仓').replace('账户快照','历史分析值').replace('href="Tiger_Portfolio_Overview_20261026.html"','href="../index.html"').replace('完整持仓与风险总览 ↗','五日核验总览 ↗')
  (path/'daily.html').write_text(html)
  prior=session
 # Cross-day rollforward to current snapshot, including trades after the final close.
 end=stamp(source['sessions'][-1]['close_utc'])
 for f in tx:
  if f['executionEpochMs']>end:forward[f['symbol']]+=signed(f)
 assert all(forward[s]==D(current[s]['quantity']) for s in current)
 (OUT/'summary.json').write_text(json.dumps({'status':'PARTIAL_RECONSTRUCTED_NOT_BROKER_RECONCILED','sessions':summaries,'quantity_rollforward':'PASS','source_sha256':hashlib.sha256((OUT/'sources.json').read_bytes()).hexdigest(),'direct_daily_fields_available':sum(r['reportedTodayPnl'] is not None for r in h['positions'])},indent=2));(OUT/'inputs.json').write_text(json.dumps(allcases,default=str,indent=2))
 print(json.dumps(summaries,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
