"""Render an unchanged price_watch result as an accessible colored HTML report."""
import argparse, collections, html, json
from pathlib import Path

def category(r):
    if r.get('error'): return '数据异常', 'error'
    if r.get('validation_scope')=='corroborated_close_only': return ('仅收盘满足；区间未知' if r.get('currently_in_zone') else '收盘未满足；区间未知'), 'approach'
    if r.get('zone_reached') and not r.get('currently_in_zone'): return '触及后已退出', 'exit'
    if r.get('zone_reached') and not r.get('threshold_reached'): return '仅触及缓冲区', 'approach'
    if r.get('directional_entry_supported'): return '当日方向性进入有依据', 'new'
    if r.get('currently_in_zone'): return '当前满足；无新穿越证明', 'hit'
    return '未触及', 'miss'

def render(result, output):
    rows=result.get('results',[])+result.get('errors',[])
    assert len(rows)==result['coverage']['enabled_rules'], 'Incomplete rule accounting'
    counts=collections.Counter(category(r)[0] for r in rows)
    esc=lambda x:html.escape(str(x))
    num=lambda x: '—' if x is None else f'{float(x):,.2f}'
    body=[]
    new_ids={r['rule_id'] for r in result.get('new_signals',[])}
    order={'new':0,'hit':1,'approach':2,'exit':3,'miss':4,'error':5}
    for r in sorted(rows,key=lambda r:(order[category(r)[1]],r['ticker'],-float(r.get('threshold',0)))):
        label,cls=category(r)
        cond=json.dumps(r.get('entry_conditions'),ensure_ascii=False) if r.get('entry_conditions') else ''
        note=r.get('error') or r.get('note','')
        if r.get('quality_warning'): note+=' '+r['quality_warning']
        link=r.get('source_url','')
        ticker=f'<a href="{esc(link)}">{esc(r["ticker"])}</a>' if link else esc(r['ticker'])
        label+= ' · 本次新记录事件' if r.get('rule_id') in new_ids else ' · 非本次新记录事件'
        cells=[ticker,esc(label),esc({'below':'≤','above':'≥'}.get(r.get('direction'),'—')),num(r.get('threshold')),num(r.get('zone_edge')),num(r.get('close')),num(r.get('low')),num(r.get('high')),esc(r.get('quote_time','—')),esc(note+' '+cond)]
        body.append('<tr class="'+cls+'">'+''.join('<td>'+v+'</td>' for v in cells)+'</tr>')
    cards=''.join('<div class="card"><b>'+str(v)+'</b><span>'+esc(k)+'</span></div>' for k,v in counts.items())
    title='牛来价格检查 · '+result['session']
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'''+title+'''</title><style>
body{font:15px system-ui,sans-serif;color:#172337;background:#f4f7fb;margin:0;padding:32px}main{max-width:1500px;margin:auto}h1{margin-bottom:8px}p{line-height:1.7}.cards{display:flex;flex-wrap:wrap;gap:12px;margin:24px 0}.card{background:white;border:1px solid #dce3ed;padding:16px 22px;border-radius:12px}.card b{font-size:28px;display:block}.card span{font-size:13px}.scroll{overflow:auto;border-radius:12px;border:1px solid #dce3ed}table{border-collapse:collapse;width:100%;background:white}th,td{text-align:left;padding:12px;border-bottom:1px solid #dce3ed;vertical-align:top}th{background:#172337;color:white;white-space:nowrap}td:last-child{min-width:280px;font-size:12px}td:nth-child(2){min-width:160px}.hit,.new{background:#e5f5e9}.new td:first-child{border-left:5px solid #168340}.miss{background:#fff0f0}.error{background:#eceff3}.approach,.exit{background:#fff5d8}a{color:#173c83;font-weight:700}input,select{padding:10px;margin:0 12px 16px 0;border:1px solid #b9c5d6;border-radius:6px}footer{font-size:13px;margin-top:20px;color:#536171}
</style><main><h1>'''+title+'''</h1><p>历史结果重新排版 · 以各行报价时间和证据范围为准，非当前报价。绿色＝价格条件满足，红色＝未触及，黄色＝缓冲/已退出，灰色＝无法判断；颜色不代表买卖建议。</p><p>评估截止：'''+esc(result['as_of'])+'''。报价时间保留原始UTC（纽约减4小时，北京加8小时）。方向性进入有依据不等于本次新增通知；无新穿越证明不等于已证明连续多日满足。</p><div class="cards">'''+cards+'''</div><input id="query" placeholder="搜索标的、价格或条件"><select id="status"><option value="">全部规则</option><option value="new">方向性进入</option><option value="hit">仍满足</option><option value="miss">未触及</option><option value="error">数据异常</option><option value="approach">缓冲区</option><option value="exit">已退出</option></select><div class="scroll"><table><thead><tr>'''+''.join('<th>'+x+'</th>' for x in ['标的/来源','状态','方向','原始提醒线','缓冲边界','收盘价','已观测最低','已观测最高','报价时间UTC','条件/备注'])+'''</tr></thead><tbody>'''+''.join(body)+'''</tbody></table></div><footer>覆盖 '''+esc(result['coverage'])+'''。日线不能确定精确穿越时刻或次数；新事件仅以原始new_signals及去重记录判定。条件提醒的基本面、伴随标的和仓位限制未由价格引擎自动验证。</footer></main><script>function filter(){let q=document.querySelector('#query').value.toUpperCase(),s=document.querySelector('#status').value;document.querySelectorAll('tbody tr').forEach(r=>r.hidden=!(r.textContent.toUpperCase().includes(q)&&(!s||r.classList.contains(s))))}document.querySelector('#query').oninput=filter;document.querySelector('#status').onchange=filter;</script></html>'''
    extra='<h2>报价覆盖：尚无启用提醒线</h2><p>这些标的纳入报价覆盖，但不伪造到价或买入信号。</p><table><tr><th>标的</th><th>收盘/最近完成报价</th><th>状态</th></tr>'
    for s in result.get('quote_only',[]):
        extra+='<tr><td><a href="'+esc(s.get('source_url',''))+'">'+esc(s['ticker'])+'</a></td><td>'+num(s.get('bar',{}).get('close'))+'<br>'+esc(s.get('bar',{}).get('quote_time',''))+'</td><td>'+esc(s.get('error','已覆盖报价；提醒线待验证'))+' '+esc(s.get('bar',{}).get('quality_warning',''))+'</td></tr>'
    extra+='</table>'
    if result.get('quote_only'): page=page.replace('</main>',extra+'</main>')
    page=page.replace('纽约减4小时，北京加8小时','北京加8小时；纽约依交易日夏令时换算')
    page=page.replace('>仍满足<','>当前满足<')
    if not result.get('retrospective'): page=page.replace('历史结果重新排版 · 以各行报价时间和证据范围为准，非当前报价。','本次价格检查 · 以各行报价时间和证据范围为准。')
    Path(output).write_text(page,encoding='utf-8')
    return counts

def message(result):
    groups=collections.defaultdict(list)
    for r in sorted(result.get('results',[]),key=lambda r:(r['ticker'],-float(r['threshold']))):
        label,_=category(r)
        if True:
            op='≤' if r['direction']=='below' else '≥'
            groups[label].append(f"{r['ticker']} {float(r['close']):.2f} / {op}{r['threshold']}")
    lines=[f"🔔 {result['session']} 全量价格摘要（美元；价格条件不等于买入建议）",f"评估截止UTC：{result['as_of']}。" ]
    if result.get('retrospective'): lines.append('历史补报/重排：当日方向性进入有依据，不代表本次新增实时事件。')
    lines.append('本次新记录事件：'+str(len(result.get('new_signals',[]))))
    for r in result.get('new_signals',[]): lines.append(f"新记录：{r['ticker']} {r['direction']} {r['threshold']} / 报价{r['close']}")
    for label,items in groups.items():lines.extend(['',label+'：','；'.join(items)])
    lines.extend(['',f"覆盖：{result['coverage']}"])
    for e in result.get('errors',[]):lines.append(e['ticker']+'：'+e['error'])
    for s in result.get('quote_only',[]):lines.append(s['ticker']+'：'+(s.get('error') or str(s['bar']['close'])+'，仅报价；提醒线待验证'))
    return '\n'.join(lines)+'\n'

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('result');p.add_argument('output');a=p.parse_args()
    print(json.dumps(render(json.loads(Path(a.result).read_text()),a.output),ensure_ascii=False))
    Path(a.output).with_suffix('.txt').write_text(message(json.loads(Path(a.result).read_text())),encoding='utf-8')
