#!/usr/bin/env python3
"""Offline compact portfolio and one-page daily views. Financial metrics come from analytics.py."""
import argparse
import html
import hashlib
import json
import math
from pathlib import Path
from datetime import datetime, timezone, timedelta

COLORS = ['#2864dc','#069f8c','#9162d8','#d49b2d','#df647a','#2586a5','#7f9458','#a3755a','#6d7891','#c47aae','#6d9db7','#858585']

def esc(v): return html.escape(str(v if v is not None else '—'), quote=True)
def n(v):
    try:
        z=float(v)
        return z if math.isfinite(z) else None
    except (TypeError,ValueError): return None

def fmt(v, decimals=2, signed=False):
    z=n(v)
    if z is None:return '—'
    if z and abs(z)<0.01 and decimals==2:return ('+' if signed and z>0 else '-' if z<0 else '')+'<0.01'
    return ('+' if signed and z>0 else '')+f'{z:,.{decimals}f}'
def pct(v):return '—' if n(v) is None else fmt(v,1)+'%'
def mult(v):return '—' if n(v) is None else fmt(v,2)+'×'
def cls(v): return 'pos' if n(v) is not None and n(v)>0 else 'neg' if n(v) is not None and n(v)<0 else 'muted'
def moment(v):
    try:
        d=datetime.fromisoformat(str(v).replace('Z','+00:00'))
        if d.utcoffset() is None:return esc(v)+'（时区未知）'
        return '<time title="'+esc(d.astimezone(timezone.utc).isoformat())+'">'+d.astimezone(timezone(timedelta(hours=8))).strftime('%m-%d %H:%M:%S')+' 北京时间</time>'
    except (ValueError,TypeError):return esc(v)
def sources_text(value):
    if isinstance(value,dict):return ' · '.join(esc(k)+': '+esc(v) for k,v in value.items() if v is not None)
    if isinstance(value,list):return ' · '.join(esc(v) for v in value)
    return esc(value)

def source_links(refs):
    output=[]
    for ref in refs or []:
        url=ref.get('url') if isinstance(ref,dict) else str(ref)
        claim=ref.get('claim') if isinstance(ref,dict) else ''
        if url and str(url).startswith(('https://','http://')):
            output.append('<a href="'+esc(url)+'" rel="noreferrer" title="'+esc(claim)+'">'+esc(str(url).split('/')[2])+'</a>')
    return ' · '.join(output) or '未提供'

def metric(label,value,sub='',color=''):

    return f'<div class="metric"><span>{esc(label)}</span><strong class="{color}">{value}</strong><small>{esc(sub)}</small></div>'

def bars(items,limit=None,signed=False):
    items=items or []
    shown=items[:limit] if limit else items
    if not shown:return '<div class="empty">暂无可核实数据</div>'
    out=[]
    maximum=max((abs(n(x.get('value')) or 0) for x in shown),default=0)
    for i,x in enumerate(shown):
        val=n(x.get('value')); share=n(x.get('pct'))
        width=max(0,min(100,100*abs(val or 0)/maximum)) if maximum else 0
        color=('#13826d' if val is not None and val>=0 else '#ce435a') if signed else COLORS[i%len(COLORS)]
        right=fmt(val,2,signed) if signed else pct(share)
        detail=fmt(val,2,signed) if not signed else (str(x.get('count'))+' 项' if x.get('count') is not None else '')
        out.append(f'<div class="barrow"><div class="barlabel"><span title="{esc(x.get("name"))}">{esc(x.get("name"))}</span><b class="{cls(val) if signed else ""}">{right}</b></div><div class="track"><i style="width:{width:.4f}%;background:{color}"></i></div><small>{detail}</small></div>')
    if limit and len(items)>limit:out.append(f'<div class="muted more">另有 {len(items)-limit} 类；全量明细见下方分类与持仓。</div>')
    return ''.join(out)

def donut(items, center, subtitle):
    valid=[x for x in (items or []) if n(x.get('pct')) is not None and n(x.get('pct'))>=0]
    if not valid:return '<div class="empty">暂无可核实数据</div>'
    offset=0; circles=[]
    for i,x in enumerate(valid):
        p=max(0,min(100,n(x['pct'])))
        circles.append(f'<circle cx="70" cy="70" r="52" pathLength="100" stroke="{COLORS[i%len(COLORS)]}" stroke-dasharray="{p:.6f} {100-p:.6f}" stroke-dashoffset="{-offset:.6f}"/>')
        offset+=p
    legend=''.join(f'<li><i style="background:{COLORS[i%len(COLORS)]}"></i><span>{esc(x.get("name"))}</span><b>{pct(x.get("pct"))}</b></li>' for i,x in enumerate(valid))
    return '<div class="donutwrap"><svg class="donut" viewBox="0 0 140 140" role="img" aria-label="'+esc(subtitle)+'"><circle class="base" cx="70" cy="70" r="52"/><g transform="rotate(-90 70 70)">'+''.join(circles)+'</g><text x="70" y="68">'+esc(center)+'</text><text class="sub" x="70" y="84">'+esc(subtitle)+'</text></svg><ul class="legend">'+legend+'</ul></div>'

def panel(title,body,note='',extra=''):
    return f'<section class="panel {extra}"><h2>{esc(title)}</h2>'+body+(f'<p class="note">{esc(note)}</p>' if note else '')+'</section>'

def rank_table(items,title, daily=False,limit=5):
    rows=[]
    for x in (items or [])[:limit]:
        value=x.get('dailyPnl') if daily else x.get('unrealizedPnl')
        if value is None:value=x.get('value')
        rows.append(f'<tr><td><b>{esc(x.get("symbol") or x.get("name"))}</b><small>{esc(x.get("subindustry") or x.get("sector") or "")}</small></td><td class="num {cls(value)}">{fmt(value,signed=True)}</td></tr>')
    return panel(title,'<table class="rank"><tbody>'+''.join(rows)+'</tbody></table>' if rows else '<div class="empty">本口径暂无可排行记录</div>')

def holdings_table(rows):
    out=[]
    for x in rows or []:
        mv=n(x.get('marketValue')); pnl=n(x.get('unrealizedPnl')); daily=n(x.get('dailyPnl'))
        name=x.get('name') or ''; sector=x.get('sector') or x.get('primary_sector') or '未分类'; sub=x.get('subindustry') or '未分类'
        lev=x.get('daily_leverage'); underlying=x.get('underlying') or '—'
        refs=x.get('source_refs') or []
        source_title='；'.join(str(r.get('url') if isinstance(r,dict) else r) for r in refs)+'；分类置信：'+str(x.get('classification_confidence') or '未知')+'；'+str(x.get('classification_notes') or '')
        tag='leveraged' if n(lev) is not None and abs(n(lev))>1 else 'unknown' if n(lev) is None else 'plain'
        qty=n(x.get('quantity')); qtyfmt=fmt(qty,0) if qty is not None and qty.is_integer() else fmt(qty,4)
        out.append(f'<tr data-sector="{esc(sector)}" data-lev="{tag}" data-value="{mv if mv is not None else ""}" data-pnl="{pnl if pnl is not None else ""}" data-symbol="{esc(x.get("symbol"))}"><td><b>{esc(x.get("symbol"))}</b><small class="security-name" title="{esc(name)}">{esc(name)}</small></td><td title="{esc(source_title)}">{esc(sub)}<small>{esc(sector)}</small></td><td class="num" title="{esc(x.get("quantity"))}">{qtyfmt}</td><td class="num" title="成本原值 {esc(x.get("averageCost"))} / 价格原值 {esc(x.get("marketPrice"))}">{fmt(x.get("marketPrice"))}<small>成本 {fmt(x.get("averageCost"))}</small></td><td class="num">{fmt(mv)}<small>{pct(x.get("weight_pct"))} 持仓市值</small></td><td class="num {cls(pnl)}">{fmt(pnl,signed=True)}<small class="muted">持有期浮盈亏</small></td><td class="num {cls(daily)}">{fmt(daily,signed=True)}</td><td class="num">{mult(lev)}<small>{esc(underlying)}</small></td></tr>')
    sectors=sorted(set(str(x.get('sector') or x.get('primary_sector') or '未分类') for x in rows or []))
    controls='<div class="controls"><input class="search" placeholder="搜索代码、名称、细分行业" aria-label="搜索持仓"><select class="sector-filter" aria-label="行业筛选"><option value="">全部行业</option>'+''.join('<option>'+esc(s)+'</option>' for s in sectors)+'</select><select class="lev-filter" aria-label="杠杆筛选"><option value="">全部杠杆</option><option value="leveraged">杠杆产品</option><option value="plain">1×</option><option value="unknown">待核实</option></select><select class="sort" aria-label="排序"><option value="value">市值从高到低</option><option value="pnl">浮盈亏从高到低</option><option value="symbol">代码顺序</option></select><span class="rowcount">'+str(len(rows or []))+' 项</span></div>'
    return controls+'<div class="table-wrap"><table class="holdings"><thead><tr><th>证券</th><th>细分分类</th><th class="num">数量</th><th class="num">价格 / 成本</th><th class="num">市值 / 占比</th><th class="num">浮盈亏</th><th class="num">当日盈亏</th><th class="num">日目标 / 底层</th></tr></thead><tbody>'+''.join(out)+'</tbody></table></div>'

CSS='''
:root{--ink:#19283e;--muted:#66748a;--line:#e1e8f1;--bg:#f3f6fa;--blue:#2864dc}*{box-sizing:border-box}body{margin:0;background:var(--bg);font:13px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;color:var(--ink)}main{max-width:1390px;margin:auto;padding:24px}.mast{display:flex;justify-content:space-between;align-items:flex-end;gap:20px;margin-bottom:17px}.eyebrow{font-size:10px;font-weight:800;letter-spacing:2px;color:var(--blue)}h1{font-size:28px;line-height:1.2;margin:4px 0 7px;letter-spacing:-.6px}h2{font-size:14px;margin:0 0 12px}p{margin:5px 0}.muted,.note,small{color:var(--muted)}small{display:block;font-size:10px;line-height:1.45}a{color:var(--blue)}.stamp{font-size:11px;text-align:right}.account{margin-bottom:30px}.account-title{display:flex;align-items:center;justify-content:space-between;margin:20px 0 10px}.account-title h2{margin:0;font-size:17px}.tag{display:inline-block;border:1px solid #d9e3f2;background:#edf3fc;color:#4c6388;padding:2px 7px;border-radius:5px;font-size:10px}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:10px 0}.metric{background:#fff;border:1px solid var(--line);border-radius:9px;padding:13px 15px}.metric>span{font-size:11px;color:var(--muted)}.metric strong{display:block;font-size:25px;letter-spacing:-.7px;font-variant-numeric:tabular-nums;line-height:1.4}.metric small{font-size:10px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:12px 0}.grid.two{grid-template-columns:repeat(2,minmax(0,1fr))}.panel{background:#fff;border:1px solid var(--line);border-radius:9px;padding:16px;min-width:0}.note{font-size:10px;line-height:1.5;margin-top:10px}.barrow{position:relative;margin:8px 0}.barlabel{display:flex;justify-content:space-between;gap:8px;font-size:11px;line-height:1.4}.barlabel span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.barlabel b{font-variant-numeric:tabular-nums;font-weight:650}.barrow small{text-align:right;font-size:9px}.track{height:6px;background:#edf1f6;border-radius:3px;overflow:hidden;margin-top:3px}.track i{height:100%;display:block;border-radius:3px}.donutwrap{display:flex;align-items:center;gap:14px}.donut{width:145px;min-width:110px;max-width:45%}.donut circle{fill:none;stroke-width:17}.donut .base{stroke:#edf1f6}.donut text{font-size:16px;fill:var(--ink);font-weight:700;text-anchor:middle}.donut text.sub{font-size:8px;fill:var(--muted);font-weight:400}.legend{list-style:none;margin:0;padding:0;flex:1;font-size:10px}.legend li{display:flex;align-items:center;gap:6px;margin:7px 0}.legend i{width:7px;height:7px;border-radius:2px;flex-shrink:0}.legend span{flex:1}.legend b{font-weight:600}.pos{color:#13826d}.neg{color:#ce435a}.empty{min-height:46px;display:flex;align-items:center;color:#8490a1;font-size:11px}.notice{padding:10px 13px;border-radius:7px;border:1px solid #e8d6a7;background:#fff9e9;font-size:11px;color:#7f631e;margin:11px 0}.summaryline{padding:10px 14px;border-left:3px solid var(--blue);background:#edf3ff;font-size:12px}.summaryline b{color:#1e4eac}.controls{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin-bottom:10px}input,select{font:inherit;font-size:11px;color:var(--ink);border:1px solid #dbe3ee;border-radius:5px;padding:6px 8px;background:#fff}.search{width:240px}.rowcount{font-size:10px;color:var(--muted);margin-left:auto}.table-wrap{overflow:auto;max-height:730px}.holdings{width:100%;border-collapse:collapse;min-width:820px;font-size:11px;font-variant-numeric:tabular-nums}.holdings th{position:sticky;top:0;background:#f5f7fb;z-index:2;font-weight:600;font-size:10px;color:#62718a;padding:8px 9px;border-bottom:1px solid #dbe3ee;text-align:left;white-space:nowrap}.holdings td{border-bottom:1px solid #edf0f5;padding:6px 9px;vertical-align:middle}.holdings tr:hover{background:#f5f8fe}.holdings small{font-size:9px}.holdings td:first-child{width:180px}.security-name{max-width:170px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.num{text-align:right!important}.rank{width:100%;border-collapse:collapse;font-size:11px;font-variant-numeric:tabular-nums}.rank td{padding:6px 0;border-bottom:1px solid #edf1f5}.rank small{font-size:9px}.kv{display:grid;grid-template-columns:1fr auto;gap:6px;font-size:11px}.kv span{color:var(--muted)}.kv b{text-align:right;font-weight:600;font-variant-numeric:tabular-nums}.wide{grid-column:span 2}details{margin:10px 0;font-size:11px}summary{cursor:pointer;color:var(--blue)}.audit{font-size:10px;color:var(--muted);word-break:break-word}.audit li{margin:5px 0}.footer{font-size:10px;color:var(--muted);margin-top:16px;padding-top:10px;border-top:1px solid var(--line)}.more{font-size:10px}.dailylink{white-space:nowrap}.daily main{max-width:1130px;padding:23px 28px}.daily .mast{margin-bottom:9px}.daily h1{font-size:24px}.daily .metrics{grid-template-columns:repeat(6,minmax(0,1fr));gap:7px}.daily .metric{padding:9px 10px}.daily .metric strong{font-size:21px}.daily .metric>span{font-size:10px}.daily .metric small{font-size:9px}.daily .grid{grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin:9px 0}.daily .panel{padding:11px 13px}.daily h2{font-size:12px;margin-bottom:7px}.daily .barrow{margin:5px 0}.daily .barrow small{display:none}.daily .track{height:5px}.daily .rank td{padding:4px 0}.daily .note{font-size:9px;line-height:1.4;margin-top:6px}.daily .notice{margin:8px 0;padding:7px 10px;font-size:10px}.daily .footer{font-size:9px;margin-top:9px;padding-top:7px}.daily .summaryline{font-size:11px;padding:8px 11px}.daily .donut{width:120px}.daily .legend li{margin:5px 0}.daily .kv{gap:4px;font-size:10px}.daily .empty{min-height:40px}.daily .rank small{font-size:8px}
@media(max-width:760px){main,.daily main{padding:14px}.mast{align-items:flex-start;flex-direction:column;gap:4px}.stamp{text-align:left}.grid,.grid.two,.daily .grid{grid-template-columns:1fr}.metrics,.daily .metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.metric strong,.daily .metric strong{font-size:22px}.wide{grid-column:auto}.search{width:100%}.rowcount{margin-left:0}.panel{padding:12px}.daily .grid{gap:9px}.account-title{align-items:flex-start;gap:5px}.donut{width:140px}.footer{line-height:1.6}}
@page{size:A4 landscape;margin:8mm}@media print{body{background:#fff;-webkit-print-color-adjust:exact;print-color-adjust:exact}.daily main{width:281mm;max-width:none;margin:0;padding:0}.daily .mast{flex-direction:row;align-items:flex-end}.daily .metrics{grid-template-columns:repeat(6,minmax(0,1fr))}.daily .grid{grid-template-columns:repeat(3,minmax(0,1fr))}.daily .grid.two{grid-template-columns:repeat(2,minmax(0,1fr))}.daily .wide{grid-column:span 2}.daily .panel,.daily .metric{break-inside:avoid}.daily .footer{margin-top:6px;font-size:8px}.daily .panel{padding:8px 10px}.daily .barrow{margin:3px 0}.daily .barlabel{font-size:9px;line-height:1.2}.daily .track{height:3px;margin-top:2px}.daily .rank td{padding:2px 0;font-size:9px}.daily .rank small{font-size:7px}.daily h2{font-size:10px;margin-bottom:5px}.daily .note{font-size:8px;line-height:1.25}.daily .metric{padding:7px 9px}.daily .metric strong{font-size:19px}.daily .metric small{font-size:8px}.daily .stamp{font-size:9px}.daily .grid{gap:7px;margin:7px 0}.daily .mast{margin-bottom:6px}.daily h1{font-size:22px}.daily .summaryline{padding:6px 9px;font-size:10px}.daily .donut{width:105px}.daily .dailylink{display:none}.controls{display:none}.table-wrap{max-height:none;overflow:visible}.account{break-before:page}.account:first-of-type{break-before:auto}}
'''
SCRIPT='''document.querySelectorAll('.holdings-panel').forEach(p=>{const body=p.querySelector('tbody'),rows=[...body.querySelectorAll('tr')],search=p.querySelector('.search'),sector=p.querySelector('.sector-filter'),lev=p.querySelector('.lev-filter'),sort=p.querySelector('.sort');function update(){const q=search.value.toLocaleLowerCase();let count=0;rows.forEach(r=>{r.hidden=!!((q&&!r.textContent.toLocaleLowerCase().includes(q))||(sector.value&&r.dataset.sector!==sector.value)||(lev.value&&r.dataset.lev!==lev.value));if(!r.hidden)count++});p.querySelector('.rowcount').textContent=count+' / '+rows.length+' 项（分母不随筛选改变）';const k=sort.value;rows.sort((a,b)=>k==='symbol'?a.dataset.symbol.localeCompare(b.dataset.symbol):(b.dataset[k]===''?-Infinity:Number(b.dataset[k]))-(a.dataset[k]===''?-Infinity:Number(a.dataset[k]))).forEach(r=>body.append(r))}for(const x of [search,sector,lev,sort])x.addEventListener('input',update);update()});'''

CSS += """.pnlbars{display:grid;grid-template-columns:repeat(var(--cols,1),minmax(0,1fr));grid-auto-flow:column;grid-template-rows:repeat(var(--percol),auto);gap:3px 22px}.pnlrow{display:grid;grid-template-columns:48px minmax(25px,1fr) 125px;align-items:center;gap:5px;font-size:10px;font-variant-numeric:tabular-nums}.pnlrow>b{font-size:10px}.pnlrow>span{text-align:right}.pnltrack{height:9px;background:#f3f5f8;position:relative}.pnltrack:before{content:'';position:absolute;left:50%;top:-2px;height:13px;width:1px;background:#a4afbc}.pnltrack i{position:absolute;height:9px;top:0}.daily .legend li{margin:3px 0}.daily .legend{font-size:9px}@media(max-width:760px){.pnlbars{grid-template-columns:1fr;grid-auto-flow:row;grid-template-rows:none}}@media print{.daily .pnlrow{font-size:8px}.daily .pnlrow>b{font-size:8px}.daily .pnlbars{gap:2px 14px}.daily .legend{font-size:7px}}"""

def report_names(data):
    date=str(data.get('report_date') or '')
    if len(date)>=10:date=date[:10].replace('-','')
    if len(date)!=8 or not date.isdigit():
        try:
            d=datetime.fromisoformat(str(data.get('generated_at')).replace('Z','+00:00'))
            date=d.astimezone(timezone(timedelta(hours=8))).strftime('%Y%m%d')
        except (ValueError,TypeError):date='snapshot'
    return ('Tiger_Portfolio_Overview_'+date+'.html','Tiger_Portfolio_Daily_'+date+'.html')

def balance_chart(m):
    parts=cash_parts(m)
    vals=[n(x.get('pct')) for x in parts]
    if any(v is None or v<0 for v in vals) or sum(v for v in vals if v is not None)>100.05:
        return '<div class="kv">'+''.join('<span>'+esc(x['name'])+'</span><b>'+pct(x.get('pct'))+'</b>' for x in parts)+'</div><p class="note">含未知、负项或不完整余额：显示原比率，不绘误导环图。</p>'
    return donut(parts,pct(m.get('cash_pct')),'现金 / NAV')

def shell(title,body,daily=False):
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(title)+'</title><style>'+CSS+'</style></head><body'+(' class="daily"' if daily else '')+'><main>'+body+'</main>'+('' if daily else '<script>'+SCRIPT+'</script>')+'</body></html>'

def account_label(a):return a.get('label') or '账户'
def data_time(data,a=None):
    t=(a or {}).get('source_times') or data.get('source_times') or {}
    if isinstance(t,dict):
        labels={'holdings_query':'持仓查询','assets_query':'资产查询','quote_time':'行情'}
        bits=[]
        for k,v in t.items():
            if isinstance(v,list):v=max((str(q) for q in v if q),default=None)
            if v:bits.append(esc(labels.get(k,k))+' '+moment(v))
        return '<br>'.join(bits) or '查询时间未提供'
    return sources_text(t)
def cash_parts(m):
    # Percentages and residual supplied by analytics; never infer a balance or FX conversion.
    return [{'name':'现金','pct':m.get('cash_pct')},{'name':'所列证券','pct':m.get('positions_nav_pct')},{'name':'其他净资产/舍入','pct':m.get('other_net_assets_pct')}]
def leverage_kv(m):
    pairs=[('证券市值 / NAV',mult(m.get('gross_nav_multiple'))),('内嵌杠杆后总敞口 / NAV',mult(m.get('embedded_gross_nav_multiple'))),('内嵌杠杆后净敞口 / NAV',mult(m.get('embedded_net_nav_multiple'))),('杠杆产品资金占比',pct(m.get('leveraged_capital_pct'))),('杠杆核验市值覆盖',pct(m.get('leverage_coverage_pct'))),('已核实融资余额',fmt(m.get('financing_balance')))]
    return '<div class="kv">'+''.join('<span>'+esc(k)+'</span><b>'+v+'</b>' for k,v in pairs)+'</div>'
def concentration(m):
    pairs=[('最大单仓',pct(m.get('top1_pct'))),('前 5 仓合计',pct(m.get('top5_pct'))),('前 10 仓合计',pct(m.get('top10_pct'))),('HHI（0–10,000）',fmt(m.get('hhi'),0)),('等效等权持仓数',fmt(m.get('effective_n'),1))]
    return '<div class="kv">'+''.join('<span>'+esc(k)+'</span><b>'+v+'</b>' for k,v in pairs)+'</div>'
def counter_boundary(a,data):
    c=a.get('broker_counters') or {}
    if not c:return ''
    value=c.get('securities_today_pnl')
    latest=max((str(x.get('date')) for x in a.get('historical_nav',[]) if x.get('date')),default='未知')
    session=data.get('latest_completed_session') or '最近交易日'
    prefix='查询时'
    try:
        from zoneinfo import ZoneInfo
        d=datetime.fromisoformat(str(c.get('query_at')).replace('Z','+00:00')).astimezone(ZoneInfo('America/New_York'))
        if d.weekday()==6:prefix='周日'
    except (ValueError,TypeError,KeyError):pass
    return prefix+'券商 today 计数 '+fmt(value)+'；历史截至 '+latest+'，不能替代 '+str(session)+' 盈亏。'

def history_chart(a):
    points=[x for x in a.get('historical_nav',[]) if n(x.get('nav')) is not None and x.get('date')]
    if not points:return '<div class="empty">未取得历史净值</div>'
    vals=[n(x['nav']) for x in points];lo=min(vals);hi=max(vals);span=hi-lo or max(abs(hi)*0.01,1)
    low=lo-span*.12;high=hi+span*.12
    coords=[(60+i*530/max(len(points)-1,1),25+(high-v)/(high-low)*100) for i,v in enumerate(vals)]
    poly=' '.join(f'{x:.2f},{y:.2f}' for x,y in coords)
    svg='<svg viewBox="0 0 650 165" role="img" aria-label="历史账户净值，纵轴局部缩放" style="width:100%;max-height:190px"><line x1="60" y1="125" x2="610" y2="125" stroke="#e1e8f1"/><polyline points="'+poly+'" fill="none" stroke="#2864dc" stroke-width="2.5"/>'
    for item,(x,y) in zip(points,coords):
        svg+='<circle cx="'+fmt(x)+'" cy="'+fmt(y)+'" r="3.5" fill="#2864dc"><title>'+esc(item['date'])+' NAV '+fmt(item['nav'])+'</title></circle><text x="'+fmt(x)+'" y="'+fmt(y-10)+'" text-anchor="middle" font-size="11" fill="#19283e">'+fmt(item['nav'])+'</text><text x="'+fmt(x)+'" y="148" text-anchor="middle" font-size="10" fill="#66748a">'+esc(str(item['date'])[5:])+'</text>'
    svg+='</svg>'
    rows=''.join('<tr><td>'+esc(x['date'])+'</td><td class="num">'+fmt(x['nav'])+'</td><td class="num '+cls(x.get('flow_adjusted_nav_change'))+'">'+fmt(x.get('flow_adjusted_nav_change'),signed=True)+'</td><td class="num">'+fmt(x.get('deposit'))+' / '+fmt(x.get('withdrawal'))+'</td></tr>' for x in points)
    return svg+'<table class="rank"><thead><tr><th>历史日期</th><th class="num">来源 NAV</th><th class="num">扣已报入出金后净值变化</th><th class="num">入金 / 出金</th></tr></thead><tbody>'+rows+'</tbody></table>'

def audit(a,classification_asof=None):
    notes=a.get('notes') or []
    quality=a.get('quality') or {}
    return '<details><summary>数据与分类口径 / 可复核来源</summary><p class="note">分类最近核验：'+esc(classification_asof or '未记录')+'；行情刷新不代表分类与杠杆来源重新核验。</p><ul class="audit">'+''.join('<li>'+esc(x)+'</li>' for x in notes)+('<li>'+sources_text(quality)+'</li>' if quality else '')+'</ul><table class="rank"><tbody>'+''.join('<tr><td>'+esc(x.get('symbol'))+'</td><td>'+esc(x.get('sector') or x.get('primary_sector'))+' / '+esc(x.get('subindustry'))+'</td><td>'+source_links(x.get('source_refs'))+'</td></tr>' for x in a.get('holdings',[]))+'</tbody></table></details>'

def render_full(data):
    body='<header class="mast"><div><div class="eyebrow">NIULAI · PORTFOLIO INTELLIGENCE</div><h1>持仓与风险总览</h1><p class="muted">从资金分布到行业、底层资产与内嵌杠杆 · 只读快照</p></div><div class="stamp">'+data_time(data)+'<br>查询时间不等于各证券行情时间<br><a class="dailylink" href="'+esc(report_names(data)[1])+'">打开一页日报 ↗</a></div></header>'
    for a in data.get('accounts',[]):
        m=a.get('metrics',{}); currency=a.get('currency') or '币种未知'; rows=a.get('holdings',[]);day=daily_view(data,a)
        body+='<section class="account"><div class="account-title"><h2>'+esc(account_label(a))+' <span class="tag">'+esc(a.get('account_type'))+' · '+esc(currency)+'</span></h2><span class="muted">'+str(len(rows))+' 项持仓 · 独立核算</span></div>'
        body+='<div class="metrics">'+metric('账户净值 · '+currency,fmt(m.get('nav')),'来源资产接口')+metric('现金',fmt(m.get('cash')),pct(m.get('cash_pct'))+' / NAV')+metric('所列证券净市值',fmt(m.get('positions_value')),pct(m.get('positions_nav_pct'))+' / NAV')+metric('持有期未实现盈亏',fmt(m.get('unrealized_pnl'),signed=True),'不是当日收益',cls(m.get('unrealized_pnl')))+metric('日 P&L · '+str(day['session'] or '日期未核实'),fmt(day['aggregate'],signed=True),day['basis_label'],cls(day['aggregate']))+metric('前 5 仓集中度',pct(m.get('top5_pct')),'以所列绝对市值为分母')+metric('内嵌杠杆后总敞口 / NAV',mult(m.get('embedded_gross_nav_multiple')),'日目标倍数代理；非长期回报倍数')+metric('有效等权持仓数',fmt(m.get('effective_n'),1),'1 / Σ持仓权重²')+'</div>'
        if a.get('notes'):body+='<div class="notice">'+esc(a['notes'][0])+'</div>'
        body+='<div class="grid">'+panel('现金与证券 / NAV',balance_chart(m),'负现金或负残差不绘入环图；实际数值以指标和残差为准。其他净资产/舍入：'+fmt(m.get('other_net_assets')))+panel('行业资金分布',bars(a.get('sector_breakdown')),'互斥主行业；以所列绝对市值为分母，不是收入占比。')+panel('集中度',concentration(m),'证券条目分散不等于底层资产或主题分散。')+'</div>'
        body+='<div class="grid">'+panel('细分行业',bars(a.get('subindustry_breakdown')),'半导体拆分存储、设计、设备、代工、封测、EDA与行业篮子；基金未伪造穿透。')+panel('主题交叉暴露',bars(a.get('themes')),'一项可属于多个主题，各主题占比不可相加为 100%。')+panel('产品杠杆结构',donut(a.get('leverage_breakdown'),'日目标','产品杠杆'), '占比以持仓绝对市值为分母。基金为已核实日目标倍率；普通股 1× 不代表公司没有财务杠杆。')+'</div>'
        body+='<div class="grid">'+panel('底层资产重叠 · 杠杆调整',bars(a.get('underlying_exposure')),'占比以已核验总代理敞口为分母，非持仓市值占比。相同底层合并，行业篮子单列，不假造穿透。')+panel('杠杆敞口核对',leverage_kv(m),'日目标倍率 × 证券市值的一阶代理，非期权 Delta、VaR 或长期损益预测。未知倍率不会默认为 1×。')+panel('行业持有期浮盈亏',bars([dict(x,value=x.get('unrealized_pnl')) for x in a.get('sector_breakdown',[])],signed=True),'持有期未实现盈亏的金额归属；不是今日归因，也不是时间加权收益率。')+'</div>'
        body+='<div class="grid two">'+rank_table(a.get('top_gainers'),'持有期浮盈贡献 · 前 5')+rank_table(a.get('top_losers'),'持有期浮亏贡献 · 前 5')+'</div>'
        if a.get('historical_nav'):
            c=a.get('broker_counters') or {}
            body+=panel('历史净值 · 截至 '+str(max(x['date'] for x in a['historical_nav'] if x.get('date'))),history_chart(a),'纵轴局部缩放。净值变化只扣已报告入金/出金，不是完整投资收益归因，也不是当前交易日P&L。'+counter_boundary(a,data)+' 来源证券浮盈亏与逐仓合计差额 '+fmt(c.get('position_sum_difference'))+'，原值分别保留。')
        body+=panel('已返回持仓 · 紧凑视图',holdings_table(rows),'表中成本 / 价格显示至 2 位小数，悬停查看原始精度。筛选只改变显示，不改变组合分母。','holdings-panel')+audit(a,data.get('classification_asof'))+'<p class="note">'+esc(scope_note(a))+'</p></section>'
    body+='<footer class="footer">'+esc('；'.join(data.get('limitations') or []))+'<br>灰色 — 表示未知，不等于 0。分类为可维护的分析分类，非官方 GICS。账户、模拟账户和币种不混合；这份报告不包含交易指令。</footer>'
    body+='<div class="footer" data-snapshot-sha256="'+snapshot_hash(data)+'">数据快照 '+snapshot_hash(data)[:12]+'</div>'
    return shell('牛来 · 持仓与风险总览',body)

def scope_note(a):
    q=a.get('quality') or {};count=len(a.get('holdings') or [])
    verified=q.get('whole_portfolio_verified') is True and q.get('pagination_completeness_verified') is True
    return '已返回 '+str(count)+' 项；'+('账户全量/分页完整性已核实。' if verified else '账户全量/分页完整性未核实。')

def snapshot_hash(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def daily_view(data,a):
    """Presentation-only gate: never promote an unaligned provider counter to P&L."""
    d=a.get('daily_performance') or {}; preferred=data.get('latest_completed_session')
    session=d.get('selectedPerformanceSession') if d.get('preferred_session')==preferred and d.get('selectedPerformanceSession') else preferred
    aligned=bool(session and d.get('session')==session)
    verified=aligned and d.get('status') in ('verified','partial','reconstructed')
    # Canonical daily positions already consolidate distinct contracts by symbol.
    # Preserve missing holdings in the roster, but never repeat a symbol's summed P&L.
    canonical=d.get('positions',[]) if aligned else []
    scope={}; source={}; repeated=set()
    for x in canonical:
        symbol=str(x.get('symbol'))
        if symbol in source:repeated.add(symbol)
        source[symbol]=x;scope.setdefault(symbol,x)
    for x in a.get('holdings',[]):scope.setdefault(str(x.get('symbol')),x)
    rows=[dict(name=symbol,value=source.get(symbol,{}).get('pnl') if verified and symbol not in repeated
               and source.get(symbol,{}).get('session',session)==session
               and d.get('position_population')!='current_snapshot_not_historical_roster' else None,
               pnl_pct=source.get(symbol,{}).get('pnl_pct') if verified and symbol not in repeated and source.get(symbol,{}).get('session',session)==session and d.get('position_population')!='current_snapshot_not_historical_roster' else None,sector=x.get('sector')) for symbol,x in scope.items()]
    rows.sort(key=lambda x:(n(x['value']) is None,-(n(x['value']) or 0),x['name']))
    sectors=[dict(name=x.get('sector') or x.get('name'),value=x.get('pnl')) for x in d.get('sectors',[]) if x.get('session',session)==session] if verified and d.get('position_population')!='current_snapshot_not_historical_roster' else []
    return dict(capital_return_pct=d.get('capital_return_pct') if verified else None,session=session,preferred=preferred,delayed=bool(session and preferred and session!=preferred),
                fallback_reason=d.get('fallback_reason'),basis_label='重建值 · 未扣费用/未与券商对账' if d.get('aggregate_basis')=='reconstructed_gross' else '账户分析口径，非逐仓 RTH' if d.get('aggregate_basis')=='account_history_daily' else '交易日对齐后展示',
                current_population=d.get('position_population')=='current_snapshot_not_historical_roster',aggregate=d.get('aggregate_pnl') if verified else None,rows=rows,sectors=sectors,
                known=sum(n(x['value']) is not None for x in rows),total=len(rows),
                note=d.get('note') or '；'.join(d.get('limitations') or []) or ('已核验目标交易日日盈亏；账户与逐仓口径分别保留。' if verified else '目标交易日盈亏尚未取得；缺失不当作零，也不用累计盈亏替代。'),
                source_asof=d.get('source_asof'),status=d.get('status','unavailable'))


def signed_bars(items,columns=1):
    """All rows, symmetric zero-centered axis, unknowns have no painted bar."""
    if not items:return '<div class="empty">暂无该口径数据</div>'
    maximum=max((abs(n(x.get('value')) or 0) for x in items),default=0)
    rows=[]
    for x in items:
        v=n(x.get('value'));w=50*abs(v)/maximum if maximum and v is not None else 0
        left=50-w if v is not None and v<0 else 50
        bar='' if v is None else '<i style="left:'+str(left)+'%;width:'+str(w)+'%;background:'+('#13826d' if v>=0 else '#ce435a')+'"></i>'
        rows.append('<div class="pnlrow"><b>'+esc(x.get('name'))+'</b><div class="pnltrack">'+bar+'</div><span class="'+cls(v)+'">'+(fmt(v,signed=True)+(' / '+fmt(x['pnl_pct'],signed=True)+'%' if n(x.get('pnl_pct')) is not None else '') if v is not None else '待补')+'</span></div>')
    return '<div class="pnlbars" style="--cols:'+str(columns)+';--percol:'+str(math.ceil(len(items)/columns))+'">'+''.join(rows)+'</div>'


def render_daily(data):
    accounts=data.get('accounts') or []
    a=next((x for x in accounts if str(x.get('account_type')).upper()!='PAPER'),{})
    m=a.get('metrics') or {}; currency=a.get('currency') or '未知'; d=daily_view(data,a)
    known=n(d['aggregate']) is not None
    date_label='实际盈亏日期' if d['delayed'] else '目标交易日'
    fallback=('优先交易日 '+str(d['preferred'])+' 未齐；'+str(d['fallback_reason'] or '采用最近可核验历史交易日')+'。') if d['delayed'] else ''
    population='当前返回代码（不是 '+str(d['session'])+' 历史持仓名单）' if d['current_population'] else '已返回代码'
    body='<header class="mast"><div><div class="eyebrow">NIULAI · DAILY PERFORMANCE</div><h1>当日表现日报 <span class="tag">'+esc(account_label(a))+' · '+esc(currency)+'</span></h1><p><b>'+date_label+' '+esc(d['session'] or '未提供')+('（盈亏待补齐）' if not known else '')+'</b> · 绿=盈利 / 红=亏损 / 灰=待补</p></div><div class="stamp">'+data_time(data,a)+'<br>盈亏来源查询：'+(moment(d['source_asof']) if d['source_asof'] else '未提供')+'<br>持仓查询时间不是价格时点<br><a class="dailylink" href="'+esc(report_names(data)[0])+'">完整持仓与风险总览 ↗</a></div></header>'
    vals=[x for x in d['rows'] if n(x['value']) is not None]
    best=max(vals,key=lambda x:n(x['value']),default=None);worst=min(vals,key=lambda x:n(x['value']),default=None)
    body+='<div class="metrics">'+metric('逐股税费前小计' if d['status']=='reconstructed' else '账户当日 P&L',fmt(d['aggregate'],signed=True),currency+' · 已覆盖资金回报 '+fmt(d.get('capital_return_pct'),signed=True)+'%（非账户收益）' if n(d.get('capital_return_pct')) is not None else currency+' · '+d['basis_label'],cls(d['aggregate']))+metric('总持仓市值 · 快照',fmt((a.get('position_totals') or {}).get('snapshot_net')),'USD · '+str((a.get('position_totals') or {}).get('snapshot_count','—'))+' 项；非历史收盘')+metric('最大盈利贡献',esc(best['name']) if best and n(best['value'])>0 else '—',fmt(best['value'],signed=True) if best and n(best['value'])>0 else '暂无可核验盈利', 'pos')+metric('最大亏损贡献',esc(worst['name']) if worst and n(worst['value'])<0 else '—',fmt(worst['value'],signed=True) if worst and n(worst['value'])<0 else '暂无可核验亏损','neg')+metric('账户净值',fmt(m.get('nav')),currency+' · 账户快照')+metric('现金余额',fmt((a.get('position_totals') or {}).get('snapshot_cash')),'现金/NAV '+pct(m.get('cash_pct'))+' · 当前快照')+'</div>'
    body+='<div class="notice">'+esc('逐仓日盈亏覆盖 '+str(d['known'])+'/'+str(d['total'])+' · '+fallback+d['note'])+'</div>'
    body+=panel('逐证券日盈亏 · '+population+' · '+str(d['total'])+' 个',signed_bars(d['rows'],3),'单位 '+currency+'；金额从高到低，每列从上到下、再向右读。百分比分母=前收市值+当日买入额；未扣费用。')
    body+='<div class="grid">'+panel('行业当日盈亏贡献',signed_bars(d['sectors']),str(d['known'])+' / '+str(d['total'])+' 项重建值按行业汇总；缺值不填零，非完整净损益。' if d['status']=='reconstructed' else '仅展示已核验的当日归因；不使用持有期盈亏代替。')+panel('资金结构 · 快照',balance_chart(m),'现金 / 证券 / 其他净资产按净值；前5仓 '+pct(m.get('top5_pct'))+'，日目标杠杆代理敞口/NAV '+mult(m.get('embedded_gross_nav_multiple'))+'；均为快照，非日收益。')+panel('行业权重 · 快照',donut(a.get('sector_breakdown'),str(d['total'])+' 项','持仓市值构成'),'分母为所列绝对持仓市值；行业互斥，基金不伪造穿透。')+'</div>'
    body+='<footer class="footer">'+esc(scope_note(a))+' '+esc(counter_boundary(a,data))+' 全量日盈亏与账户盈亏可能因已平仓交易、费用、利息、股息和汇兑存在差额，未核对不强行配平。其他账户（含 PAPER）不合并。周末/假日取最近已完成交易日；盘中快照不能当作收盘归因。</footer>'
    body+='<div class="footer" data-snapshot-sha256="'+snapshot_hash(data)+'">数据快照 '+snapshot_hash(data)[:12]+'</div>'
    return shell('牛来 · 当日表现日报',body,True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',default=str(Path(__file__).with_name('analytics.json')));p.add_argument('--output-dir',default=str(Path(__file__).parent));a=p.parse_args()
    data=json.loads(Path(a.input).read_text());out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
    for name,body in zip(report_names(data),(render_full(data),render_daily(data))):
        (out/name).write_text(body,encoding='utf-8');print(out/name)
if __name__=='__main__':main()
