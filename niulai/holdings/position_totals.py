"""Same-currency position totals, with snapshot/close provenance kept separate."""
from decimal import Decimal

def attach_totals(view, source, rows):
    h=source['evidence']['holdings']['result']
    a=view['accounts'][0]
    assert h['ok'] and h['accountIdentityChecked'] and h['sourceReadStatus']=='complete'
    assert h['accountRef']==a['accountRef']
    positions=h['positions']
    assert all(p['currency']==a['currency'] for p in positions)
    assert len({p['contractId'] for p in positions})==len(positions)
    values=[Decimal(p['marketValue']) if p.get('marketValue') is not None else None for p in positions]
    assert all(v is None or v.is_finite() for v in values)
    complete=all(v is not None for v in values)
    known=[Decimal(r['closing_quantity'])*Decimal(r['close']) for r in rows if r.get('close') is not None]
    a['position_totals']={'snapshot_net':str(sum(values)) if complete else None,
      'snapshot_gross':str(sum(abs(v) for v in values)) if complete else None,
      'snapshot_count':len(positions),'snapshot_query_at':h.get('queryCompletedAt'),
      'snapshot_price_timestamp_verified':False,'close_known_net':str(sum(known)),
      'close_known_count':len(known),'close_expected_count':len(rows),
      'basis':'broker_returned_positions_snapshot_not_historical_close'}
    assets=source.get('evidence',{}).get('current_assets',{}).get('result',{})
    if assets.get('ok') and assets.get('sourceReadStatus')=='complete' and assets.get('accountIdentityChecked'):
        assert assets['accountRef']==a['accountRef']
        summary=assets.get('summary') or {};assert summary.get('currency')==a['currency']
        amounts=summary.get('amounts',{})
        nav=Decimal(amounts['netLiquidation']) if amounts.get('netLiquidation') is not None else None
        cash=Decimal(amounts['cash']) if amounts.get('cash') is not None else None
        assert all(v is None or v.is_finite() for v in (nav,cash))
        t=a['position_totals'];t.update(snapshot_nav=str(nav) if nav is not None else None,snapshot_cash=str(cash) if cash is not None else None,assets_query_at=assets.get('queryCompletedAt'))
        if nav is not None and cash is not None and complete and nav>0:
            residual=nav-cash-sum(values);t['snapshot_residual']=str(residual)
            a['metrics'].update(nav=float(nav),cash=float(cash),cash_pct=float(cash/nav*100),positions_nav_pct=float(sum(values)/nav*100),other_net_assets_pct=float(residual/nav*100))
            perf=a.get('daily_performance',{})
            perf['note']=perf.get('note','').replace('账户收益率及现金比例留空','历史账户收益率留空；现金/NAV图采用当前账户快照')
    return view
