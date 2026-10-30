from datetime import datetime,timezone
import json,unittest
from unittest.mock import patch
from urllib.error import HTTPError,URLError
import options_quote_capture as q
S='CRWV270416C00065000';T='2026-10-23T19:00:00Z';NOW=datetime(2026,10,23,19,0,2,tzinfo=timezone.utc)
def tradier():return {'quotes':{'quote':[{'symbol':S,'bid':9.9,'ask':10.8,'bidsize':2,'asksize':3,'bid_date':1792782000000,'ask_date':1792782000000,'expiration_date':'2027-04-16','strike':65,'option_type':'call','contract_size':100}]}}
def alpaca():return {'quotes':{S:{'bp':9.9,'ap':10.8,'bs':2,'as':3,'t':T,'c':'A'}}}
def rec():return q.normalize('alpaca',alpaca(),[S],retrieved_at=T,feed='opra')['records'][0]
def config():return {'underlying':'CRWV','contracts':[S],'providers':[{'provider':'tradier','feed':'consolidated_realtime','epoch_unit':'milliseconds','entitlement_ref':'fixture_not_verified'},{'provider':'alpaca','feed':'opra','stock_feed':'sip','entitlement_ref':'fixture_not_verified'}],'policy':{'max_quote_age_seconds':15,'max_side_skew_seconds':5,'max_stock_option_skew_seconds':5,'price_absolute_tolerance':'0.05','price_relative_tolerance':'0.01'}}
class Reply:
 def __init__(self,url,data):self.url=url;self.data=data
 def __enter__(self):return self
 def __exit__(self,*a):pass
 def geturl(self):return self.url
 def read(self,n):return self.data[:n]
class Opener:
 def __init__(self,reply):self.reply=reply;self.requests=[]
 def open(self,request,timeout):
  self.requests.append(request)
  if isinstance(self.reply,Exception):raise self.reply
  return self.reply
class Checks(unittest.TestCase):
 def test_tradier_fields(self):
  r=q.normalize('tradier',tradier(),[S],retrieved_at=T,feed='consolidated_realtime',epoch_unit='milliseconds')['records'][0]
  self.assertEqual(r['ask'],'10.8');self.assertFalse(r['contract_terms']['deliverable_verified']);json.dumps(r)
 def test_alpaca_shared_time(self):self.assertIn('not_independent',rec()['time_basis'])
 def test_bad_json(self):
  for v in ['{"x":NaN}','{"x":1,"x":2}']:
   with self.assertRaises(q.CaptureError):q.decode(v)
 def test_timezone_missing(self):
  p=alpaca();p['quotes'][S]['t']='2026-10-23 19:00:00';self.assertEqual(q.normalize('alpaca',p,[S],retrieved_at=T,feed='opra')['errors'][0]['code'],'timezone_qualified_quote_time_required')
 def test_nanosecond_preserved(self):
  p=alpaca();p['quotes'][S]['t']='2026-10-23T19:00:00.123456789Z';self.assertEqual(q.normalize('alpaca',p,[S],retrieved_at=T,feed='opra')['records'][0]['bid_time'],p['quotes'][S]['t'])
 def test_epoch_not_inferred(self):self.assertEqual(q.normalize('tradier',tradier(),[S],retrieved_at=T,feed='consolidated_realtime')['errors'][0]['code'],'explicit_epoch_unit_required')
 def test_semantic_error(self):
  with self.assertRaises(q.CaptureError):q.normalize('alpaca',{'code':401,'message':'bad'},[S],retrieved_at=T,feed='opra')
 def test_missing_symbol(self):self.assertEqual(q.normalize('alpaca',{'quotes':{}},[S],retrieved_at=T,feed='opra')['errors'][0]['code'],'missing_symbol')
 def test_metadata_mismatch(self):
  p=tradier();p['quotes']['quote'][0]['strike']=66;self.assertEqual(q.normalize('tradier',p,[S],retrieved_at=T,feed='consolidated_realtime',epoch_unit='milliseconds')['errors'][0]['code'],'contract_metadata_mismatch')
 def check(self,r,now=NOW,session='open'):return q.assess(r,now=now,max_age_seconds=15,max_side_skew_seconds=5,session=session)
 def test_good_never_trade_approval(self):
  r=self.check(rec());self.assertTrue(r['quote_data_checks_passed']);self.assertFalse(r['actionable_trade_approved'])
 def test_closed_and_unavailable(self):
  self.assertIn('market_closed',self.check(rec(),session='closed')['issues']);self.assertIn('calendar_unavailable',self.check(rec(),session='calendar_unavailable')['issues'])
 def test_indicative(self):
  r=rec();r['feed']='indicative';self.assertIn('non_executable_feed',self.check(r)['issues'])
 def test_old_not_fresh_by_download(self):
  r=rec();r['retrieved_at']='2026-10-24T19:00:00Z';self.assertIn('stale_bid',self.check(r,now=datetime(2026,10,24,19,tzinfo=timezone.utc))['issues'])
 def test_future(self):self.assertIn('future_bid_time',self.check(rec(),now=datetime(2026,10,23,18,tzinfo=timezone.utc))['issues'])
 def test_zero_size_and_crossed(self):
  r=rec();r['ask_size']=0;r['bid']='20';self.assertIn('empty_or_missing_display_size',self.check(r)['issues']);self.assertIn('crossed_quote',self.check(r)['issues'])
 def test_no_secret_url(self):
  op=Opener(Reply(q.ENDPOINTS['tradier'][0],b'{"quotes":{}}'));q.fetch('tradier',q.ENDPOINTS['tradier'][0],{'symbols':S},{'TRADIER_ACCESS_TOKEN':'abc123'},opener=op);self.assertNotIn('abc123',op.requests[0].full_url);self.assertEqual(op.requests[0].method,'GET')
 def test_orders_and_missing_creds(self):
  with self.assertRaises(q.CaptureError):q.fetch('tradier','https://api.tradier.com/v1/accounts/a/orders',{}, {})
  with self.assertRaisesRegex(q.CaptureError,'credentials_unavailable'):q.fetch('alpaca',q.ENDPOINTS['alpaca'][0],{}, {})
 def test_redirect_origin(self):
  with self.assertRaisesRegex(q.CaptureError,'redirect_refused'):q.NoRedirect().redirect_request(None,None,302,'',{},'https://evil.test')
  with self.assertRaisesRegex(q.CaptureError,'origin_changed'):q.fetch('tradier',q.ENDPOINTS['tradier'][0],{}, {'TRADIER_ACCESS_TOKEN':'secret'},opener=Opener(Reply('https://evil.test/quotes',b'{}')))
 def test_no_auth_retry(self):
  op=Opener(HTTPError('url',401,'SECRET',{},None))
  with self.assertRaisesRegex(q.CaptureError,'authentication_or_entitlement_failed'):q.fetch('tradier',q.ENDPOINTS['tradier'][0],{}, {'TRADIER_ACCESS_TOKEN':'SECRET'},opener=op)
  self.assertEqual(len(op.requests),1)
 def test_retry_bound(self):
  op=Opener(URLError('private context'))
  with patch.object(q.time,'sleep'):
   with self.assertRaisesRegex(q.CaptureError,'transient_network_exhausted'):q.fetch('tradier',q.ENDPOINTS['tradier'][0],{}, {'TRADIER_ACCESS_TOKEN':'SECRET'},opener=op)
  self.assertEqual(len(op.requests),2)
 def test_response_bound(self):
  with self.assertRaisesRegex(q.CaptureError,'response_too_large'):q.fetch('tradier',q.ENDPOINTS['tradier'][0],{}, {'TRADIER_ACCESS_TOKEN':'SECRET'},opener=Opener(Reply(q.ENDPOINTS['tradier'][0],b'x'*(q.MAX_BYTES+1))))
 def test_scrub(self):self.assertEqual(q.scrub({'x':['secret x']},['secret']),{'x':['[REDACTED] x']})
 def test_noauth_all_scope(self):
  r=q.capture(config(),env={});self.assertEqual(len(r['providers']),2);self.assertEqual(r['status'],'blocked');self.assertFalse(r['actionable_trade_approved']);json.dumps(r)
 def test_unknownkey_and_injection(self):
  c=config();c['base_url']='https://evil.test'
  with self.assertRaises(q.CaptureError):q.capture(c,env={})
  with self.assertRaises(q.CaptureError):q.contract('CRWV270416C00065000&secret=yes')
if __name__=='__main__':unittest.main()

class CaptureIntegration(unittest.TestCase):
 def test_successful_mock_is_data_only(self):
  def fake(provider,endpoint,params,env):
   names=params['symbols'].split(',')
   if provider=='tradier':
    payload=tradier();row=dict(payload['quotes']['quote'][0]);row['symbol']='CRWV';row.pop('strike');row.pop('expiration_date');row.pop('option_type');payload['quotes']['quote'].append(row)
   else:
    payload={'quotes':{symbol:{'bp':9.9,'ap':10.8,'bs':2,'as':3,'t':T,'c':'A'} for symbol in names}}
   return payload,'a'*64
  with patch.object(q,'session_state',return_value='closed'):
   r=q.capture(config(),env={},fetcher=fake)
  self.assertEqual(r['status'],'captured_data_only');self.assertEqual(len(r['comparisons']),4);json.dumps(r)
  self.assertTrue(all(x['status']=='ineligible_quote_data' for x in r['comparisons']))
 def test_stock_iex_cannot_clear_synced_option(self):
  r=rec();r['feed']='iex';self.assertIn('non_executable_feed',q.assess(r,now=NOW,max_age_seconds=15,max_side_skew_seconds=5,session='open')['issues'])
 def test_wrong_underlying_root_rejected(self):
  c=config();c['underlying']='SPY'
  with self.assertRaisesRegex(q.CaptureError,'root_mapping'):q.capture(c,env={})

class AdversarialMetadata(unittest.TestCase):
 def test_secret_keys_and_collisions(self):
  r=q.scrub({'FAKE_REVIEW_TOKEN':'FAKE_REVIEW_TOKEN','[REDACTED]':'keep'},['FAKE_REVIEW_TOKEN'])
  self.assertNotIn('FAKE_REVIEW_TOKEN',json.dumps(r));self.assertEqual(len(r),2);self.assertIn('keep',r.values())
 def test_invalid_contract_strike_is_scoped(self):
  for strike in ['broken','NaN','Infinity',{},-1]:
   p=tradier();p['quotes']['quote'][0]['strike']=strike
   r=q.normalize('tradier',p,[S],retrieved_at=T,feed='consolidated_realtime',epoch_unit='milliseconds')
   self.assertEqual(len(r['errors']),1);self.assertFalse(r['records'])

class StrictInputAndCondition(unittest.TestCase):
 def test_provider_shape(self):
  for x in ['bad',None,1]:
   c=config();c['providers']=[x]
   with self.assertRaises(q.CaptureError):q.capture(c,env={})
 def test_no_null_tolerance(self):
  for k in ['price_relative_tolerance','price_absolute_tolerance']:
   c=config();c['policy'][k]=None
   with self.assertRaises(q.CaptureError):q.capture(c,env={})
 def test_nonfirm_unknown_conditions_fail(self):
  for cond in ['F','I','R','T','X','Y','Z',None,'']:
   r=rec();r['quote_condition']=cond
   self.assertIn('nonfirm_unsupported_or_missing_quote_condition',q.assess(r,now=NOW,max_age_seconds=15,max_side_skew_seconds=5,session='open')['issues'])
 def test_valid_opra_condition_preserved(self):
  r=rec();self.assertEqual(r['quote_condition'],'A');self.assertTrue(q.assess(r,now=NOW,max_age_seconds=15,max_side_skew_seconds=5,session='open')['quote_data_checks_passed'])

class ResponseContainment(unittest.TestCase):
 def test_malformed_json_scoped(self):
  for raw in [b'{',b'\xffinvalid']:
   with self.assertRaisesRegex(q.CaptureError,'malformed_json'):q.decode(raw)
 def test_extreme_price_does_not_expand(self):
  for v in ['1e100000000','1e-100000000','0e-100000','0e100000',10**90]:
   with self.assertRaisesRegex(q.CaptureError,'invalid_quote_number'):q.money(v)

class ResponseSymbolContainment(unittest.TestCase):
 def test_bad_tradier_symbol_is_scoped(self):
  for symbol in [[],{},None,123,'']:
   with self.assertRaises(q.CaptureError):q.normalize('tradier',{'quotes':{'quote':{'symbol':symbol}}},[S],retrieved_at=T,feed='consolidated_realtime',epoch_unit='milliseconds')
 def test_bad_tradier_keeps_alpaca(self):
  def fake(provider,endpoint,params,env):
   if provider=='tradier':return {'quotes':{'quote':{'symbol':[]}}},'a'*64
   return {'quotes':{s:{'bp':9.9,'ap':10.8,'bs':2,'as':3,'t':T,'c':'A'} for s in params['symbols'].split(',')}},'b'*64
  r=q.capture(config(),env={},fetcher=fake)
  self.assertEqual(r['providers'][0]['status'],'failed');self.assertEqual(r['providers'][1]['status'],'captured');self.assertEqual(r['status'],'partial')
