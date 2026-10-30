"""One complete price + holdings email payload; no network or second sender."""
import argparse,base64,html,json,re
from pathlib import Path
def amount(v):return '待补' if v is None else f'{float(v):,.2f}'
def compose(view, price_text, pdf, subject, recipient, historical=False, price_view=None):
    if not price_text.strip():raise ValueError('Price results or explicit failure must be present')
    raw=Path(pdf).read_bytes()
    if not raw.startswith(b'%PDF-'):raise ValueError('Actual PDF required')
    a=view['accounts'][0];d=a['daily_performance'];t=a['position_totals'];e=html.escape
    body='<html><body style="font-family:Arial,sans-serif;color:#172a3a;max-width:900px;margin:auto"><h1 style="font-size:25px;font-weight:800">DAILY HOLDING UPDATE｜价格提醒与持仓日报</h1>'
    body+='<p><b>'+('历史合并测试，非当前实时价格或新穿越。' if historical else '本时段统一摘要；价格和持仓数据各自标明时点。')+'</b></p>'
    if price_view is not None:
        from price_summary_view import render
        if price_view.get('session')!=a['daily_performance']['session'] and historical:raise ValueError('Historical test session mismatch')
        body+=render(price_view)
    else:body+='<h2>价格提醒 · 完整正文</h2><div style="white-space:pre-wrap;line-height:1.6;font-family:Arial,sans-serif">'+e(price_text)+'</div>'
    body+='<hr><h2>持仓日报 · '+e(d['session'])+'</h2><table cellpadding="10" style="background:#f2f5f8;width:100%"><tr>'
    for label,value in [('总资产净值（含现金）',t.get('snapshot_nav')),('证券持仓市值',t.get('snapshot_net')),('现金余额',t.get('snapshot_cash'))]:
        body+='<td>'+label+'<br><b style="font-size:22px">$'+amount(value)+'</b></td>'
    body+='</tr></table><p>税费前逐股盈亏：<b>$'+amount(d['aggregate_pnl'])+'</b>；已覆盖资金回报 <b>'+amount(d.get('capital_return_pct'))+'%</b>。百分比分母为前收持仓市值加当日买入额，非账户NAV收益率。</p>'
    body+='<p>持仓读取 '+e(t.get('snapshot_query_at') or '未知')+'；资产读取 '+e(t.get('assets_query_at') or '未知')+'。读取时间不等于行情时间。净资产减现金和证券市值的残差 $'+amount(t.get('snapshot_residual'))+'，不强行配平。</p>'
    body+='<h3>逐股盈亏 · 金额降序</h3><table cellpadding="5" style="width:100%;border-collapse:collapse"><tr><th align="left">代码</th><th align="right">P&L USD</th><th align="right">资金回报 %</th></tr>'
    rows=d['positions'];known=[r for r in rows if r.get('pnl') is not None]
    from decimal import Decimal
    assert [Decimal(r['pnl']) for r in known]==sorted([Decimal(r['pnl']) for r in known],reverse=True)
    for r in rows:
        color='#8490a1' if r.get('pnl') is None else '#13826d' if Decimal(r['pnl'])>=0 else '#ce435a'
        body+='<tr style="border-bottom:1px solid #e5eaf0;color:'+color+'"><td>'+e(r['symbol'])+'</td><td align="right">'+amount(r.get('pnl'))+'</td><td align="right">'+amount(r.get('pnl_pct'))+('%' if r.get('pnl_pct') is not None else '')+'</td></tr>'
    body+='</table><h3>覆盖与限制</h3><p>'+str(len(known))+'/'+str(len(rows))+' 项可计算。'+e(d.get('note',''))+'</p><p>账户与日期范围分别保留；不合并PAPER，不将未知填零，不将税费前价格损益当成券商账户净盈亏。完整图表见直接附上的一页PDF，可在邮箱或本地打开，无需ChatGPT。邮件接受不证明手机推送收悉。</p></body></html>'
    return {'to':recipient,'subject':subject,'payload':{'mime_type':'multipart/mixed','parts':[{'mime_type':'text/html','charset':'UTF-8','body':{'content':body}},{'mime_type':'application/pdf','filename':'Niulai_Daily_Holdings_'+d['session']+'.pdf','content_disposition':'attachment','body':{'base64_url_content':base64.urlsafe_b64encode(raw).decode()}}]}}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--portfolio',required=True,type=Path);p.add_argument('--price-message',required=True,type=Path);p.add_argument('--price-view',type=Path);p.add_argument('--price-pdf',type=Path);p.add_argument('--pdf',required=True,type=Path);p.add_argument('--subject',required=True);p.add_argument('--recipient',required=True);p.add_argument('--historical',action='store_true');p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    payload=compose(json.loads(a.portfolio.read_text()),a.price_message.read_text(),a.pdf,a.subject,a.recipient,a.historical,json.loads(a.price_view.read_text()) if a.price_view else None)
    if a.price_pdf:
        raw=a.price_pdf.read_bytes()
        if not raw.startswith(b'%PDF-'):raise ValueError('Actual price PDF required')
        payload['payload']['parts'].append({'mime_type':'application/pdf','filename':'Niulai_Price_Alert_Details.pdf','content_disposition':'attachment','body':{'base64_url_content':base64.urlsafe_b64encode(raw).decode()}})
    a.output.write_text(json.dumps(payload,ensure_ascii=False));print('Complete combined email payload prepared; not sent')
