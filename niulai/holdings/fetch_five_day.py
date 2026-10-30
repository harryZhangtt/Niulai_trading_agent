"""Collect a bounded five-completed-session audit using existing read-only Tiger auth."""
import json,logging
from pathlib import Path
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal
import niulai_tiger as n
from session_date import completed_sessions,latest_completed_session
P=Path(__file__).parent/'five_day_daily';P.mkdir(exist_ok=True)
def main(out_dir=None, count=5, profile_dir=None):
 global P
 if out_dir is not None:P=Path(out_dir);P.mkdir(parents=True,exist_ok=True)
 logging.disable(logging.CRITICAL);now=datetime.now(timezone.utc)
 sessions=list(reversed(completed_sessions(now,count)));first=datetime.fromisoformat(sessions[0]['close_utc']);prev=latest_completed_session(datetime.combine(first.astimezone(ZoneInfo('America/New_York')).date(),datetime.min.time(),tzinfo=ZoneInfo('America/New_York')))
 start=int(datetime.fromisoformat(prev['close_utc']).timestamp()*1000);end=int(now.timestamp()*1000)
 out={'query_at':now.isoformat(),'sessions':sessions,'prior_session':prev,'start_ms':start,'end_ms':end,'evidence':{}}
 def save(): (P/'sources.json').write_text(json.dumps(out,default=str,indent=2))
 profile=Path(profile_dir or '/root/.config/niulai-tiger-standalone')
 with n.profile_lock(profile):
  S,make=n.sdk_classes(include_transactions=True,include_quotes=True);s=S(issuer=n.ISSUER,home=str(profile),surface=n.SURFACE,client_name=n.CLIENT_NAME);n.validate_token(s.status());c=make(s)
  accounts=c.get_managed_accounts();refs=n.account_refs(profile,accounts)
  standard=[a for a in accounts if a.account_type=='STANDARD'];n.require(len(standard)==1,'STANDARD_ACCOUNT_AMBIGUOUS')
  account=standard[0];ref=refs[account.account];out['account_ref']=ref
  def capture(name,fn,raw_client=None):
   try:
    value=fn();entry={'ok':True,'result':value.to_dict(orient='records') if hasattr(value,'to_dict') else value,'queried_at':datetime.now(timezone.utc).isoformat()}
    if raw_client is not None:entry['raw']=raw_client.raw
   except Exception as e:entry={'ok':False,'error':n.safe_error(e),'diagnostic':n.safe_diagnostic(e)}
   out['evidence'][name]=entry;save();print(json.dumps({'step':name,'ok':entry['ok']}),flush=True);return entry
  hp=capture('holdings',lambda:n.fetch_account(c,{'account':account.account,'ref':ref},n.DEFAULT_SECURITY_TYPES))
  if hp['ok']:
   hp['result']['sourceAccountMetadata']={key:None if getattr(account,key,None) is None else str(getattr(account,key)) for key in ('account_type','status','capability')}
   save()
  capture('current_assets',lambda:n.fetch_assets_account(c,{'account':account.account,'ref':ref}))
  tx=capture('transactions',lambda:n.fetch_transaction_window(c,{'account':account.account,'ref':ref},start,end,'STK'))
  if not hp['ok'] or not tx['ok']:return
  try:n.validate_token(s.status(),require_quotes=True)
  except n.ReadOnlyError as error:
   out['evidence']['quote_permission']={'ok':False,'error':n.safe_error(error)};save();return
  symbols=sorted({r['symbol'] for r in hp['result']['positions']}|{r['symbol'] for r in tx['result']['transactions']});out['symbols']=symbols;save()
  from tigeropen.quote.quote_client import QuoteClient
  from tigeropen.trade.trade_client import TradeClient
  from tigeropen.common.consts.service_types import POSITION_TRANSFER_RECORDS,POSITION_TRANSFER_EXTERNAL_RECORDS
  class Quote(QuoteClient):
   def _TigerOpenClient__prepare_request(self,req,url=''):
    n.require(req._method in ('kline','corporate_action'),'READ_QUOTE_ONLY');return super()._TigerOpenClient__prepare_request(req,url)
   def _TigerOpenClient__parse_response(self,data,timestamp=None):
    v=super()._TigerOpenClient__parse_response(data,timestamp);self.raw=json.loads(data,parse_float=Decimal);return v
  class Transfers(TradeClient):
   def _TigerOpenClient__prepare_request(self,req,url=''):
    n.require(req._method in (POSITION_TRANSFER_RECORDS,POSITION_TRANSFER_EXTERNAL_RECORDS),'READ_TRANSFER_ONLY');return super()._TigerOpenClient__prepare_request(req,url)
  config=c._TigerOpenClient__config;q=Quote(config,is_grab_permission=False);t=Transfers(config)
  begin=int(datetime.fromisoformat(prev['date']).replace(tzinfo=ZoneInfo('America/New_York')).timestamp()*1000)
  for i in range(0,len(symbols),40):
   group=symbols[i:i+40];capture('bars_'+str(i),lambda group=group:q.get_bars(group,period='day',begin_time=begin,end_time=end,right='nr',limit=10),q)
  for action in ('split','symbol_change','dividend','delisting'):
   for i in range(0,len(symbols),10):
    group=symbols[i:i+10];entry=capture(action+'_'+str(i),lambda group=group,action=action:getattr(q,'get_corporate_'+action)(group,'US',prev['date'],now.date().isoformat(),timezone='America/New_York'),q);entry['symbols']=group;save()
  for name in ('get_position_transfer_records','get_position_transfer_external_records'):
   def call(name=name):
    records=getattr(t,name)(prev['date'],now.date().isoformat(),account_id=account.account)
    return {'record_count':None if records is None else len(records),'empty_list_verified':isinstance(records,list) and not records}
   capture(name,call)
  capture('history',lambda:n.fetch_analytics_account(c,{'account':account.account,'ref':ref},prev['date'],now.date().isoformat(),'USD'))
 print(json.dumps({'sessions':[v['date'] for v in sessions],'universe':len(symbols),'transactions':len(tx['result']['transactions'])}))
if __name__=='__main__':main()
