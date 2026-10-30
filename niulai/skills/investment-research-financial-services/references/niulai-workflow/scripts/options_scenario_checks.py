#!/usr/bin/env python3
"""European BSM diagnostics, not American-option executable fair values.

Stdlib only. T is ACT/365 years; r/q continuous annual rates, volatility annual
decimal. Prices/Greeks are per underlying share: vega per 1 vol percentage
point, rho per 1 rate percentage point, theta per calendar day. No contracts,
trade sizes, real-world probabilities, discrete dividends or fitted IV surface.
API: bsm(kind,S,K,T,r,q,sigma), implied_vol(...,premium), iv_interval(...,bid,ask).
calculate packet: version/kind/spot/strike/years/rate/yield/volatility/quotes/
scenarios. quotes is null or {bid,ask}; scenarios are {id,spot,elapsed_days,
volatility}. Values are finite JSON numbers; all input provenance stays in the
parent evidence record. Example packet in test_options_scenario_checks.py.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

VERSION = '2026-10-23-options-bsm-diagnostic-1'
LIMITATION = ('European, continuous-yield, flat-volatility diagnostic only. '
              'US equity American exercise, discrete dividends, borrow, jumps, '
              'skew dynamics and execution prices need separate treatment. '
              'No probability of profit or recommendation is inferred.')


class OptionError(ValueError):
    pass


def number(value, label, low, high, strict_low=False):
    if (type(value) not in (int, float) or value > high or value < low
            or not math.isfinite(value) or (strict_low and value == low)):
        raise OptionError(label + ': outside finite supported domain')
    return float(value)


def inputs(kind, S, K, T, r, q):
    if kind not in ('call', 'put'):
        raise OptionError('kind must be call or put')
    T = number(T, 'years', 0, 30)
    if 0 < T < 1e-12:
        raise OptionError('Positive years below supported precision; supply exact zero for expiry')
    return (number(S, 'spot', 1e-12, 1e12), number(K, 'strike', 1e-12, 1e12),
            T, number(r, 'rate', -1, 1), number(q, 'yield', -1, 1))


def cdf(x):
    return .5 * math.erfc(-x / math.sqrt(2))


def bounds(kind, S, K, T, r, q):
    S, K, T, r, q = inputs(kind, S, K, T, r, q)
    a, b = S * math.exp(-q * T), K * math.exp(-r * T)
    return (max(a-b, 0), a) if kind == 'call' else (max(b-a, 0), b)


def bsm(kind, S, K, T, r, q, sigma):
    S, K, T, r, q = inputs(kind, S, K, T, r, q)
    sigma = number(sigma, 'volatility', 1e-12, 10)
    if T == 0:
        return {'price': max(S-K, 0) if kind == 'call' else max(K-S, 0),
                'delta': None, 'gamma': None, 'vega_per_vol_point': None,
                'theta_per_calendar_day': None, 'rho_per_rate_point': None,
                'status': 'expired_payoff_only'}
    sqrtT = math.sqrt(T)
    d1 = (math.log(S)-math.log(K) + (r-q + .5*sigma*sigma)*T) / (sigma*sqrtT)
    d2 = d1 - sigma*sqrtT
    eq, er = math.exp(-q*T), math.exp(-r*T)
    density = math.exp(-.5*d1*d1) / math.sqrt(2*math.pi)
    first = -S*eq*density*sigma/(2*sqrtT)
    if kind == 'call':
        price = S*eq*cdf(d1)-K*er*cdf(d2)
        delta, theta, rho = eq*cdf(d1), first+q*S*eq*cdf(d1)-r*K*er*cdf(d2), K*T*er*cdf(d2)
    else:
        price = K*er*cdf(-d2)-S*eq*cdf(-d1)
        delta, theta, rho = -eq*cdf(-d1), first-q*S*eq*cdf(-d1)+r*K*er*cdf(-d2), -K*T*er*cdf(-d2)
    lower, upper = bounds(kind, S, K, T, r, q)
    return {'price': min(upper, max(lower, price)), 'delta': delta,
            'gamma': eq*density/(S*sigma*sqrtT),
            'vega_per_vol_point': S*eq*density*sqrtT*.01,
            'theta_per_calendar_day': theta/365,
            'rho_per_rate_point': rho*.01, 'status': 'european_diagnostic'}


def implied_vol(kind, S, K, T, r, q, premium):
    S, K, T, r, q = inputs(kind, S, K, T, r, q)
    premium = number(premium, 'premium', 0, 1e26)
    if T == 0:
        raise OptionError('Implied volatility is unidentified at expiration')
    lower, upper = bounds(kind, S, K, T, r, q)
    if premium < lower or premium >= upper:
        raise OptionError('Premium outside European no-arbitrage inversion bounds')
    if premium == lower:
        return 0.0  # boundary limit, not a measured zero-volatility market
    lo, hi = 1e-12, 10.0
    if bsm(kind, S, K, T, r, q, hi)['price'] < premium:
        raise OptionError('IV exceeds supported volatility bracket; no estimate returned')
    for _ in range(150):
        mid = (lo+hi)/2
        price = bsm(kind, S, K, T, r, q, mid)['price']
        if price < premium: lo = mid
        else: hi = mid
        if hi-lo < 1e-12: break
    estimate = (lo+hi)/2
    if abs(bsm(kind, S, K, T, r, q, estimate)['price']-premium) > max(1e-8, premium*1e-10):
        raise OptionError('IV inversion failed repricing tolerance')
    return estimate


def iv_interval(kind, S, K, T, r, q, bid, ask):
    bid, ask = number(bid, 'bid', 0, 1e26), number(ask, 'ask', 0, 1e26)
    if ask < bid:
        raise OptionError('Crossed bid/ask')
    return {'bid_iv': implied_vol(kind,S,K,T,r,q,bid),
            'ask_iv': implied_vol(kind,S,K,T,r,q,ask),
            'meaning': 'European model IV endpoints; not quote freshness or American IV certification.'}


def calculate(packet):
    fields = {'version','kind','spot','strike','years','rate','yield','volatility','quotes','scenarios'}
    if type(packet) is not dict or set(packet) != fields or packet['version'] != VERSION:
        raise OptionError('Exact versioned packet fields required')
    args = [packet[k] for k in ('kind','spot','strike','years','rate','yield')]
    base = bsm(*args, packet['volatility'])
    quote = packet['quotes']
    if quote is not None and (type(quote) is not dict or set(quote) != {'bid','ask'}):
        raise OptionError('quotes must be null or bid/ask object')
    iv = None if quote is None else iv_interval(*args, quote['bid'], quote['ask'])
    if type(packet['scenarios']) is not list or not 1 <= len(packet['scenarios']) <= 1000:
        raise OptionError('One to 1000 explicit scenarios required')
    results, seen = [], set()
    for s in packet['scenarios']:
        if type(s) is not dict or set(s) != {'id','spot','elapsed_days','volatility'}:
            raise OptionError('Exact scenario fields required')
        if type(s['id']) is not str or not s['id'].strip() or s['id'] in seen:
            raise OptionError('Unique nonempty scenario id required')
        seen.add(s['id'])
        # Normalize only machine-roundoff at the exact endpoint. A genuine
        # post-expiry scenario remains invalid; never silently shorten its date.
        total_days = packet['years']*365
        days = number(s['elapsed_days'], 'elapsed_days', 0, 30*365+1)
        tolerance = 8*max(math.ulp(total_days),math.ulp(days))
        if days > total_days+tolerance:
            raise OptionError('elapsed_days: scenario lies after expiry')
        remaining = 0.0 if abs(days-total_days)<=tolerance else (total_days-days)/365
        value = bsm(packet['kind'],s['spot'],packet['strike'],remaining,packet['rate'],packet['yield'],s['volatility'])
        results.append({'id':s['id'],'remaining_years':remaining,**value,
                        'model_price_change':value['price']-base['price']})
    raw = json.dumps(packet,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    return {'version':VERSION,'model':'European Black-Scholes-Merton continuous yield',
            'input_sha256':hashlib.sha256(raw).hexdigest(),'base':base,'quote_iv':iv,
            'scenarios':results,'limitation':LIMITATION,'trade_recommendation':False}


def decode_packet(raw):
    def pairs(rows):
        out = {}
        for key,value in rows:
            if key in out: raise OptionError('Duplicate JSON key: '+key)
            out[key] = value
        return out
    def invalid(value): raise OptionError('Nonfinite JSON constant: '+value)
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',required=True); p.add_argument('--output',required=True)
    a = p.parse_args(); code = 0
    try: result = calculate(decode_packet(Path(a.input).read_bytes()))
    except (ValueError,TypeError,KeyError,OSError,OverflowError) as exc:
        result,code = {'version':VERSION,'status':'rejected','error':str(exc)},2
    path = Path(a.output); path.parent.mkdir(parents=True,exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile('w',dir=path.parent,delete=False) as out:
            tmp=out.name; json.dump(result,out,indent=2,allow_nan=False); out.write('\n')
        os.replace(tmp,path)
    finally:
        if tmp and os.path.exists(tmp): os.unlink(tmp)
    print(json.dumps(result,allow_nan=False)); return code


if __name__ == '__main__': raise SystemExit(main())
