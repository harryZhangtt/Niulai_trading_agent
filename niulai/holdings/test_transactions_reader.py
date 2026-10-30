import copy, unittest
from decimal import Decimal
from niulai_tiger import fetch_transaction_window
PIN={'account':'private-account','ref':'a'*32};START=1792699200000;END=1792785600000

def item(id=1):return {'accountId':PIN['account'],'id':id,'symbol':'TEST','secType':'STK','currency':'USD','action':'BUY','filledQuantity':12,'filledQuantityScale':0,'filledPrice':'84.92','filledAmount':'1019.04','transactionTime':1792770015454,'transactedAt':'2026-10-23 23:40:15'}
class Client:
 def __init__(self,pages):self.pages=iter(pages);self.calls=[]
 def get_transactions(self,**kw):self.calls.append(kw);self.raw_data=next(self.pages)
class TransactionTests(unittest.TestCase):
 def run_reader(self,pages,**kw):return fetch_transaction_window(Client(pages),PIN,START,END,**kw)
 def test_correct_request_and_precision(self):
  c=Client([{'items':[item()]}]);r=fetch_transaction_window(c,PIN,START,END)
  self.assertTrue(r['ok']);self.assertEqual(c.calls[0]['sec_type'],'STK');self.assertEqual(c.calls[0]['start_time'],START);self.assertNotIn('since_date',c.calls[0]);t=r['transactions'][0];self.assertEqual(t['executionTimeUtc'],'2026-10-23T15:40:15.454000+00:00');self.assertEqual(t['quantity'],'12');self.assertNotIn('accountId',t);self.assertNotIn('id',t);self.assertEqual(len(t['executionIdHash']),64)
 def test_numeric_account_identity(self):
  v=item();v['accountId']=Decimal('123');r=fetch_transaction_window(Client([{'items':[v]}]),{'account':'123','ref':'b'*32},START,END);self.assertTrue(r['ok'])
 def test_full_page_without_token_is_partial(self):
  r=self.run_reader([{'items':[item(i) for i in range(100)]}]);self.assertFalse(r['paginationComplete']);self.assertEqual(r['sourceReadStatus'],'partial')
 def test_options_unsupported(self):
  with self.assertRaises(ValueError):self.run_reader([],sec_type='OPT')
 def test_split_executions_not_collapsed(self):
  r=self.run_reader([{'items':[item(1)],'nextPageToken':'next'},{'items':[item(2)]}]);self.assertEqual(len(r['transactions']),2);self.assertTrue(r['paginationComplete'])
 def test_duplicate_execution_rejected(self):
  r=self.run_reader([{'items':[item(),item()]}]);self.assertFalse(r['ok']);self.assertEqual(len(r['transactions']),1)
 def test_pagination_budget_partial(self):
  r=self.run_reader([{'items':[item()],'nextPageToken':'next'}],max_pages=1);self.assertFalse(r['ok']);self.assertEqual(r['sourceReadStatus'],'partial')
 def test_fractional_quantity_scale(self):
  v=item();v.update(filledQuantity=12345,filledQuantityScale=3,filledPrice='10',filledAmount='123.45');r=self.run_reader([{'items':[v]}]);self.assertEqual(r['transactions'][0]['quantity'],'12.345')
 def test_invalid_values_rejected(self):
  for field,value in [('accountId','other'),('transactionTime',END+1),('filledPrice','NaN'),('filledAmount',0),('filledQuantityScale',True)]:
   v=item();v[field]=value;r=self.run_reader([{'items':[v]}]);self.assertFalse(r['ok'],field)
 def test_empty_response_complete_not_unknown_zero(self):
  r=self.run_reader([{'items':[]}]);self.assertTrue(r['ok']);self.assertEqual(r['transactions'],[]);self.assertNotIn('pnl',r)
if __name__=='__main__':unittest.main()
