"""Long-stock gross daily capital return, distinct from account NAV return/TWR."""
from decimal import Decimal,InvalidOperation

def daily_return_rate(case,gross):
 try:
  q=Decimal(str(case['opening']['quantity']));p=Decimal(str(case['opening']['price']));v=Decimal(str(gross))
  if not all(z.is_finite() for z in (q,p,v)) or q<0 or p<0:return None
  capital=q*p;position=q
  for fill in sorted(case['executions'],key=lambda f:f['timestamp']):
   size=Decimal(str(fill['quantity']));price=Decimal(str(fill['price']))
   if not size.is_finite() or not price.is_finite() or size<=0 or price<0:return None
   if fill['side']=='BUY':capital+=size*price;position+=size
   elif fill['side']=='SELL':position-=size
   else:return None
   if position<0:return None # Short crossings need a separate capital definition.
  if capital<=0:return None
  return {'denominator':str(capital),'percent':str(v/capital*100),'basis':'gross_pnl/(prior_close_market_value+new_long_purchase_amount)'}
 except (KeyError,TypeError,ValueError,InvalidOperation):return None
