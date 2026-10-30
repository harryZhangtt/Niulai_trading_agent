"""Read-only report adapter: compare saved observations, never invent crossings."""
import argparse,hashlib,html,json,sqlite3
from collections import Counter
from datetime import datetime
from decimal import Decimal as D
from pathlib import Path
from zoneinfo import ZoneInfo

NY=ZoneInfo('America/New_York')
GROUPS=[('newly_satisfied','本次新到线（两次观察间）','#245cce'),('already_satisfied','上次已满足，本次仍满足','#13826d'),('newly_confirmed','补齐数据 / 首次确认满足','#0b819c'),('approach_only','仅接近，未达原始线','#a16b00'),('exited','触及后退出 / 目前不满足','#bc6b16'),('not_reached','尚未到价','#bf4058'),('unverifiable','数据不足，无法判断','#788491')]

def instant(v):
    x=datetime.fromisoformat(v.replace('Z','+00:00'))
    if x.tzinfo is None:raise ValueError('Source time requires timezone')
    return x

def num(v):
    x=D(str(v))
    if not x.is_finite() or x<=0:raise ValueError('Price/threshold must be positive finite')
    return x

def signature(r):
    return str(r.get('rule_id') or r.get('id')),r['ticker'],r['direction'],num(r['threshold'])

def satisfied(r):
    p,t=num(r['close']),num(r['threshold'])
    if r['direction'] not in ('below','above'):raise ValueError('Unknown direction')
    return p<=t if r['direction']=='below' else p>=t

def valid_prior(current, prior_run, previous):
    if not prior_run or not previous or prior_run.get('retrospective') or prior_run.get('mode')!='live':return False
    if signature(current)!=signature(previous):return False
    # Same quote mark repeated by a retry cannot establish a new price transition.
    return instant(previous['quote_time'])<instant(current['quote_time'])

def build(run, prior=None, definitions=None, historical=True):
    if run.get('status') not in ('completed','partial'):raise ValueError('No finalized evaluation to render')
    if prior and instant(prior['as_of'])>=instant(run['as_of']):raise ValueError('Future prior observation')
    expected=run['coverage']['enabled_rules'];raw=run.get('results',[]);errors=run.get('errors',[])
    ids=[str(r.get('rule_id') or r.get('id')) for r in raw+errors]
    if len(ids)!=expected or len(ids)!=len(set(ids)):raise ValueError('Rule scope missing/duplicate')
    defs={str(r['id']):r for r in (definitions or [])}
    if definitions is not None and set(ids)!={str(r['id']) for r in definitions if r.get('enabled') is True}:raise ValueError('Frozen rules do not match saved run scope')
    old={signature(r):r for r in (prior or {}).get('results',[])}
    old_errors={str(r.get('rule_id') or r.get('id')) for r in (prior or {}).get('errors',[])}
    events=run.get('new_signals',[])
    if any(str(e['rule_id']) not in ids for e in events):raise ValueError('Signal outside evaluated scope')
    if (run.get('retrospective') or run.get('mode')!='live') and events:raise ValueError('Replay cannot invent live signals')
    new_ids={str(e['rule_id']) for e in events};rows=[]
    for r in raw:
        r=dict(r);rid=str(r['rule_id']);p,t=num(r['close']),num(r['threshold']);sat=satisfied(r)
        prev=old.get(signature(r));comparable=valid_prior(r,prior,prev)
        prior_sat=satisfied(prev) if comparable else None
        quality=r.get('validation_scope') not in (None,'full_observed_range')
        if sat:
            group='already_satisfied' if prior_sat else 'newly_satisfied' if prior_sat is False else 'newly_confirmed'
            reason='两次采样均满足；不证明期间持续在区间内' if prior_sat else '上次未满足，本次满足；只知发生在两次观察之间' if prior_sat is False else '上次数据缺失，补齐后确认；非新穿越' if rid in old_errors else '无有效同规则前次报价，首次确认；非新穿越'
        elif r.get('threshold_reached') or (comparable and prior_sat):group='exited';reason='观察区间触及原始线或前次满足，目前已不满足；日线不能确定路径/次数'
        elif r.get('currently_in_zone'):group='approach_only';reason='仅在缓冲区，尚未达到原始线'
        elif r.get('zone_reached'):group='exited';reason='观察区间只触及缓冲区，现已退出；原始线未达到'
        else:group='not_reached';reason='观察范围及当前报价均未达到提醒条件'
        gap=(p-t)/t*100 if r['direction']=='below' else (t-p)/t*100
        ref=defs.get(rid,{})
        row={**r,'group':group,'currently_satisfied':sat,'prior_satisfied':prior_sat,'prior_close':prev.get('close') if comparable else None,'prior_quote_time':prev.get('quote_time') if comparable else None,'new_engine_record':rid in new_ids,'reason':reason,'quality_limited':quality,'gap_pct':str(gap),'rule_note':ref.get('note',r.get('note')),'entry_conditions':ref.get('entry_conditions',r.get('entry_conditions')),'expires_at':ref.get('expires_at',r.get('expires_at'))}
        rows.append(row)
    for r in errors:rows.append({**r,'rule_id':str(r.get('rule_id') or r.get('id')),'group':'unverifiable','currently_satisfied':None,'new_engine_record':False,'reason':r.get('error','未返回可用数据')})
    rows.sort(key=lambda r:(next(i for i,g in enumerate(GROUPS) if g[0]==r['group']),r['ticker'],r['direction'],-num(r['threshold']) if r['direction']=='below' else num(r['threshold'])))
    counts={k:sum(r['group']==k for r in rows) for k,_,_ in GROUPS};assert sum(counts.values())==expected
    return {'schema':'price-summary-view-v1','historical_presentation':historical,'run_id':run['id'],'session':run['session'],'as_of':run['as_of'],'prior_run_id':prior.get('id') if prior else None,'prior_as_of':prior.get('as_of') if prior else None,'coverage':run['coverage'],'groups':counts,'new_signal_records':events,'directional_evidence_count':sum(r.get('directional_entry_supported') is True for r in rows),'rows':rows,'quote_only':run.get('quote_only',[]),'rules_sha256':run.get('rules_sha256'),'source_payload_sha256':hashlib.sha256(json.dumps(run,sort_keys=True).encode()).hexdigest()}

def f(v):return '—' if v is None else f'{D(str(v)):,.2f}'
def ts(v):return instant(v).astimezone(NY).strftime('%m/%d %H:%M:%S NY') if v else '前次未知'
def level(r):return ('≤' if r['direction']=='below' else '≥')+f(r['threshold'])
def conditions_text(value):
    if not isinstance(value,dict):return str(value)
    parts=[str(value['action'])] if value.get('action') else []
    if value.get('companion_ticker'):parts.append(value['companion_ticker']+' '+('≤' if value.get('direction')=='below' else '≥')+str(value.get('threshold','未知')))
    parts+=value.get('conditions',[])
    if value.get('invalidators'):parts.append('失效：'+'、'.join(value['invalidators']))
    if value.get('manual_recheck_required'):parts.append('必须人工复核')
    return '；'.join(parts)

def render(model):
    e=html.escape;c=model['groups'];rows=model['rows'];total=sum(c.values())
    body='<section style="font-family:Arial,sans-serif;color:#1b2c40"><h2 style="font-size:25px;margin:12px 0">价格提醒 · 新变化和既有条件分开</h2>'
    body+='<p><b>'+('历史格式修订，非当前行情 / 非新发送信号。' if model['historical_presentation'] else '本次已保存评估。')+'</b> 纽约交易日 '+e(model['session'])+'；评估截止 '+ts(model['as_of'])+'；对比 '+ts(model['prior_as_of'])+'。</p>'
    body+='<table width="100%" cellpadding="8" style="border-collapse:collapse"><tr>'
    for key,label,color in GROUPS:
        body+='<td style="background:#f2f5fa;border-top:4px solid '+color+';vertical-align:top"><b style="font-size:23px;color:'+color+'">'+str(c[key])+'</b><br><span style="font-size:11px">'+e(label)+'</span></td>'
    body+='</tr></table><p style="font-size:12px">计数单位为规则，非股票。'+str(total)+'条全部列出；实际新增记录 '+str(len(model['new_signal_records']))+' 条，方向性进入证据 '+str(model['directional_evidence_count'])+' 条。到价不等于建议买入。缓冲触及不等于原始线达到。</p>'
    # A stacked bar encodes the entire scope; status always also has a text label.
    body+='<table width="100%" cellspacing="0" cellpadding="0" role="presentation"><tr>'
    for key,label,color in GROUPS:
        if c[key]:body+='<td width="'+str(c[key]/total*100)+'%" style="height:12px;background:'+color+'"></td>'
    body+='</tr></table>'
    for key,label,color in sorted(GROUPS,key=lambda g: ['newly_satisfied','newly_confirmed','already_satisfied','approach_only','exited','not_reached','unverifiable'].index(g[0])):
        rr=[r for r in rows if r['group']==key]
        body+='<h3 style="border-left:5px solid '+color+';padding-left:9px;color:'+color+'">'+e(label)+' · '+str(len(rr))+'条</h3>'
        if not rr:body+='<p style="font-size:12px;color:#738195">本类为0条。</p>';continue
        body+='<table width="100%" cellpadding="6" style="border-collapse:collapse;font-size:12px"><thead><tr style="background:#edf2f8"><th align="left">标的 / 备注</th><th align="right">上次 → 本次</th><th align="right">原始提醒线 / 缓冲边界</th><th align="right">距原始线</th><th align="left">时点 / 状态</th></tr></thead><tbody>'
        for r in rr:
            gap=r.get('gap_pct');distance='—' if gap is None else ('已越过 '+f(abs(D(gap)))+'%' if D(gap)<=0 else '尚差 '+f(gap)+'%')
            maximum=min(abs(D(gap)),D(30)) if gap else D(0);bar='<span style="display:inline-block;width:'+str(maximum/30*65)+'px;height:5px;background:'+color+'"></span>'
            note=('新增记录；' if r.get('new_engine_record') else '')+('仅可验证收盘价；' if r.get('quality_limited') else '')+r.get('reason','')
            rule=r.get('rule_note') or ''
            if rule.startswith('Copied from Tiger.'):rule=''
            body+='<tr style="border-bottom:1px solid #e3eaf2"><td><b>'+e(r['ticker'])+'</b><br><small>'+e(rule)+'</small></td><td align="right">'+f(r.get('prior_close'))+' → <b style="color:'+color+'">'+f(r.get('close'))+'</b></td><td align="right">'+level(r)+'<br><small>缓冲 '+f(r.get('zone_edge'))+'</small></td><td align="right">'+distance+'<br>'+bar+'</td><td>'+e(ts(r.get('quote_time')))+'<br><small>'+e(note)+'</small></td></tr>'
            if r.get('entry_conditions') or r.get('expires_at'):body+='<tr><td colspan="5" style="font-size:10px;color:#63748b">附加条件（价格引擎未核验）：'+e(conditions_text(r.get('entry_conditions')) if r.get('entry_conditions') else '无额外已保存条件')+'；有效期 '+e(str(r.get('expires_at') or '未提供'))+'</td></tr>'
        body+='</tbody></table>'
    body+='<h3>实际新增信号记录 · '+str(len(model['new_signal_records']))+'条</h3><p>这是保存的引擎记录增量，不等于市场刚刚越线；历史展示不重新发送这些信号。</p><ul>'
    for r in model['new_signal_records']:body+='<li>'+e(r['ticker'])+' '+level(r)+'：'+('方向性进入有依据' if r.get('directional_entry_supported') else '无新方向性穿越证明')+'</li>'
    body+='</ul><h3>仅报价 · 没有启用提醒线</h3><ul>'
    for q in model['quote_only']:
        body+='<li>'+e(q['ticker'])+' '+f(q.get('bar',{}).get('close'))+'；'+e(ts(q.get('bar',{}).get('quote_time')))+'</li>'
    body+='</ul><p style="font-size:11px;color:#6a7a8d">所有规则、错误及仅报价范围均保留。日线/离散采样不能证明持续在区间、准确穿越时间、顺序或次数。行情条件不等于基本面及仓位条件已通过。没有逐笔交易或设备送达承诺。</p></section>'
    return body

def from_database(path, run_id=None, definitions=None, historical=False):
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True) as c:allruns=[json.loads(r[0]) for r in c.execute('SELECT payload FROM price_runs')]
    eligible=[r for r in allruns if r.get('status') in ('completed','partial') and r.get('role')=='existing_summary' and r.get('results')]
    run=next(r for r in eligible if r['id']==run_id) if run_id else max(eligible,key=lambda r:instant(r['as_of']))
    prior=[r for r in eligible if r.get('mode')=='live' and not r.get('retrospective') and instant(r['as_of'])<instant(run['as_of'])]
    previous=max(prior,key=lambda r:instant(r['as_of'])) if prior else None
    return build(run,previous,definitions,historical)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',required=True,type=Path);p.add_argument('--rules',type=Path);p.add_argument('--run-id');p.add_argument('--historical',action='store_true');p.add_argument('--out',required=True,type=Path);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    if not a.historical and not a.run_id:p.error('Production rendering requires exact --run-id; historical reformat requires --historical')
    defs=json.loads(a.rules.read_text())['alerts'] if a.rules else None;m=from_database(a.db,a.run_id,defs,a.historical)
    (a.out/'price_view.json').write_text(json.dumps(m,ensure_ascii=False,indent=2));fragment=render(m);(a.out/'price_fragment.html').write_text(fragment)
    (a.out/'price_report.html').write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><body style="max-width:1250px;margin:24px auto;padding:16px">'+fragment+'</body></html>')
    print(json.dumps({'groups':m['groups'],'all_rules':sum(m['groups'].values()),'new_engine_records':len(m['new_signal_records'])},ensure_ascii=False))
