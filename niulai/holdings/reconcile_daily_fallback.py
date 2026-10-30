"""Reconstruct returned USD stock roster; never equate arithmetic checks with broker reconciliation."""
import json,hashlib
from pathlib import Path
from decimal import Decimal as D
from datetime import datetime
from zoneinfo import ZoneInfo
from daily_performance import compute_close_to_close_pnl
ROOT=Path(__file__).parent

def cross_check(reported,computed,tolerance=D('.01')):
 if reported is None:return {'status':'unavailable','reason':'broker_daily_pnl_missing'}
 if any(not reported.get(k) or reported.get(k)!=computed.get(k) for k in ('account_ref','contract_id','currency','session','basis')):return {'status':'not_comparable','reason':'identity_session_or_basis_mismatch'}
 try:
  a,b=D(str(reported['value'])),D(str(computed['value']))
  if not a.is_finite() or not b.is_finite():raise ValueError()
 except (ValueError,ArithmeticError,KeyError):return {'status':'invalid','reason':'invalid_value'}
 delta=a-b
 return {'status':'match' if abs(delta)<=tolerance else 'mismatch','delta':str(delta),'tolerance':str(tolerance)}

def build(root=ROOT):
 def read(name):return json.loads((root/name).read_text(),parse_float=D)
 sources=read('daily_reconciliation_sources.json');e=sources['evidence'];corp=read('corporate_batched_evidence.json');bars=read('broker_bars_all_authorized_evidence.json');tx=read('transactions_latest.json')
 # These are actual collected evidence, not caller-provided completeness booleans.
 assert e['fresh_holdings']['ok']
 a=next(a for a in e['fresh_holdings']['result']['accountResults'] if a['sourceAccountMetadata']['account_type']=='STANDARD')
 assert a['ok'] and a['sourceReadStatus']=='complete' and a['accountIdentityChecked'] is True
 ref=a['accountRef'];t=next(a for a in tx['accountResults'] if a['accountRef']==ref);post=e['post_close_executions']['result']
 assert t['ok'] and t['paginationComplete'] and t['startEpochMs']==1792699200000 and t['endEpochMs']==1792785600000
 assert post['ok'] and post['paginationComplete'] and post['accountRef']==ref and post['startEpochMs']==1792785600000 and post['transactions']==[]
 for name in ['get_position_transfer_records','get_position_transfer_external_records']:
  assert e[name]['ok'] and e[name]['result']['accountRef']==ref and e[name]['result']['emptyListVerified'] is True
 rows=a['positions'];assert len({r['symbol'] for r in rows})==len(rows)
 assert {f['symbol'] for f in t['transactions']}<= {r['symbol'] for r in rows},'Closed-out names need explicit reconstruction'
 # No records is provider-reported absence, not independent corporate-action confirmation.
 covered={}
 for action in ['split','symbol_change','dividend','delisting']:
  selected=[v for k,v in corp['evidence'].items() if k.startswith(action+'_')]
  assert selected and all(v['ok'] and v['raw']['code']==0 and v['raw']['data']=={} for v in selected),'Nonempty/failed action requires normalization'
  covered[action]={s for v in selected for s in v['requestedSymbols']}
 out=[];inputs=[]
 for r in rows:
  symbol=r['symbol'];ident={'account_ref':ref,'contract_id':r['contractId'],'currency':r['currency']}
  b=[v for v in bars['rows'] if v['symbol']==symbol]
  bydate={datetime.fromtimestamp(int(v['time'])/1000,ZoneInfo('America/New_York')).date().isoformat():v for v in b}
  entry=dict(symbol=symbol,broker_crosscheck=cross_check(None,{}))
  if len(b)!=2 or set(bydate)!= {'2026-10-22','2026-10-23'}:
   out.append(dict(entry,status='blocked',reason='missing_dated_close',gross_pnl=None));continue
  assert all(symbol in s for s in covered.values())
  assert all(D(v['low'])>0 and D(v['low'])<=D(v['close'])<=D(v['high']) and D(v['low'])<=D(v['open'])<=D(v['high']) for v in b)
  assert r['securityType']=='STK' and r['currency']=='USD' and D(r['multiplier'])==1
  fills=[f for f in t['transactions'] if f['symbol']==symbol]
  movement=sum(((D(1) if f['side']=='BUY' else D(-1))*D(f['quantity']) for f in fills),D(0))
  cq=D(r['quantity']);oq=cq-movement
  def mark(q,day):return dict(ident,quantity=str(q),price=str(bydate[day]['close']),session=day,price_basis='regular_session_close',source_ref='broker_bars_all_authorized_evidence.json#'+symbol+':'+day)
  case=dict(ident,security_type='STK',multiplier='1',opening=mark(oq,'2026-10-22'),closing=mark(cq,'2026-10-23'),ledger={'complete':True,'source_ref':'transactions_latest.json','start_utc':'2026-10-22T20:00:00Z','end_utc':'2026-10-23T20:00:00Z'},corporate_actions={'status':'verified_none','source_ref':'corporate_batched_evidence.json; provider-reported no records'},executions=[dict(ident,quantity=f['quantity'],price=f['price'],fee=f['fee'],side=f['side'],timestamp=f['executionTimeUtc'],source_ref=f['executionIdHash']) for f in fills])
  result=compute_close_to_close_pnl(case)
  # Distinct arithmetic oracle: mark opening shares, then each fill to closing price.
  cp=D(case['closing']['price']);oracle=oq*(cp-D(case['opening']['price']))+sum(((D(1) if f['side']=='BUY' else D(-1))*D(f['quantity'])*(cp-D(f['price'])) for f in fills),D(0))
  assert result['gross_pnl']==oracle,'Independent formula disagreement'
  if r.get('reportedTodayPnl') is not None:
   evidence=r.get('dailyPnlEvidence') or {}
   reported=dict(ident,value=r['reportedTodayPnl'],session=evidence.get('session'),basis=evidence.get('basis'))
   entry['broker_crosscheck']=cross_check(reported,dict(ident,value=str(result['gross_pnl']),session='2026-10-23',basis='gross_close_to_close'))
  out.append(dict(entry,status='reconstructed_gross',gross_pnl=str(result['gross_pnl']),net_pnl=None,opening_quantity=str(oq),closing_quantity=str(cq),previous_close=str(case['opening']['price']),close=str(cp),fills=len(fills),arithmetic_crosscheck='pass',quantity_basis='reconstructed from current snapshot minus complete executions; not independent historical holdings',corporate_action_basis='Tiger reported no records',fees='not reconciled'))
  inputs.append(case)
 result={'session':'2026-10-23','previous_session':'2026-10-22','currency':'USD','basis':'prior regular close to regular close; gross price/trade contribution','status':'PARTIAL_RECONSTRUCTED_NOT_BROKER_RECONCILED','excluded_accounts':[{'type':v['sourceAccountMetadata']['account_type'],'status':v['sourceReadStatus']} for v in e['fresh_holdings']['result']['accountResults'] if v['accountRef']!=ref],'expected_returned_roster':len(rows),'computed_count':sum(x['gross_pnl'] is not None for x in out),'computed_subtotal':str(sum((D(x['gross_pnl']) for x in out if x['gross_pnl'] is not None),D(0))),'broker_crosscheck':'UNAVAILABLE','account_nav_crosscheck':'UNAVAILABLE_FOR_MATCHING_DATE_AND_BASIS','limitations':['DCFCQ missing marks','Fees, interest and dividends excluded','Historical quantities reconstructed, not independent broker snapshots','Corporate action absence is one-provider evidence','Returned-roster completeness is not independently established'],'rows':out}
 names=['daily_reconciliation_sources.json','corporate_batched_evidence.json','broker_bars_all_authorized_evidence.json','transactions_latest.json']
 result['source_hashes']={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in names}
 (root/'daily_fallback_inputs.json').write_text(json.dumps(inputs,default=str,indent=2));(root/'daily_fallback_result.json').write_text(json.dumps(result,indent=2))
 return result
if __name__=='__main__':
 r=build();print(json.dumps({k:v for k,v in r.items() if k not in ('rows','source_hashes')}));print(json.dumps(sorted([x for x in r['rows'] if x['gross_pnl'] is not None],key=lambda x:D(x['gross_pnl']))[:3]))
