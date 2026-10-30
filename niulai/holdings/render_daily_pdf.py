#!/usr/bin/env python3
"""One-page daily report using the same session-gated view as HTML; no finance calculations."""
import argparse,json,math
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from render_portfolio import daily_view,n,fmt,COLORS,snapshot_hash,scope_note
W,H=841.89,595.28
INK='#172A3A';MUTED='#627587';GREEN='#13826d';RED='#ce435a';BG='#F2F5F8'
from reportlab.pdfbase.ttfonts import TTFont
pdfmetrics.registerFont(TTFont('NiulaiCJK',str(Path(__file__).with_name('fonts')/'NotoSansSC-Regular.ttf')))

def make(data,path):
 a=next((x for x in data.get('accounts',[]) if str(x.get('account_type')).upper()!='PAPER'),{})
 historical=bool(data.get('five_day_evidence_sha256')) and not (a.get('position_totals') or {}).get('assets_query_at');m=a.get('metrics',{});d=daily_view(data,a);c=canvas.Canvas(str(path),pagesize=(W,H));c.setTitle('牛来当日表现日报');c.setSubject('analytics_snapshot_sha256='+snapshot_hash(data))
 def text(x,y,s,size=9,color=INK):
  c.setFillColor(HexColor(color));c.setFont('NiulaiCJK',size);c.drawString(x,y,str(s))
 def box(x,y,w,h,color='#FFFFFF'):
  c.setFillColor(HexColor(color));c.roundRect(x,y,w,h,7,fill=1,stroke=0)
 def clip(s,width,size=8):
  s=str(s)
  while pdfmetrics.stringWidth(s,'NiulaiCJK',size)>width:s=s[:-2]+'…'
  return s
 def row(x,y,width,label,value,size=8,max_value=0,pnl_pct=None):
  v=n(value);text(x,y,label,size);axis=x+width*.43;half=width*.17
  c.setStrokeColor(HexColor('#CED8E2'));c.line(axis,y-2,axis,y+8)
  if v is not None and max_value:
   bw=half*abs(v)/max_value;c.setFillColor(HexColor(GREEN if v>=0 else RED));c.rect(axis-bw if v<0 else axis,y,bw,6,stroke=0,fill=1)
  text(x+width-82,y,(fmt(v,signed=True)+(' / '+fmt(pnl_pct,signed=True)+'%' if n(pnl_pct) is not None else '')) if v is not None else '待补',min(size,7),GREEN if v is not None and v>0 else RED if v is not None and v<0 else MUTED)
 def pie(x,y,r,items):
  valid=[(label,n(p)) for label,p in items]
  if not valid or any(p is None or p<0 for _,p in valid) or abs(sum(p for _,p in valid)-100)>.1:
   text(x-r,y,'构成未核实',9,MUTED);return
  angle=90
  for i,(label,p) in enumerate(valid):
   c.setFillColor(HexColor(COLORS[i%len(COLORS)]));c.wedge(x-r,y-r,x+r,y+r,angle,-3.6*p,fill=1,stroke=0);angle-=3.6*p
  c.setFillColor(HexColor('#FFFFFF'));c.circle(x,y,r*.56,fill=1,stroke=0)
 box(0,0,W,H,BG);text(24,559,'牛来 · 当日表现日报',21)
 text(315,559,('实际盈亏日期 ' if d['delayed'] else '目标交易日 ')+str(d['session'] or '未核实'),10,MUTED)
 text(24,540,f"{a.get('label','')} · {a.get('currency','')} · {d['total']} 项持仓 · 绿=盈利 / 红=亏损 / 灰=待补",9,MUTED)
 text(564,540,('日盈亏已计算 ' if d['status']=='reconstructed' else '日盈亏已核验 ')+str(d['known'])+'/'+str(d['total'])+' · PAPER 未合并',9,MUTED)
 vals=[x for x in d['rows'] if n(x['value']) is not None]
 best=max(vals,key=lambda x:n(x['value']),default={});worst=min(vals,key=lambda x:n(x['value']),default={})
 cards=[('逐股税费前小计' if d['status']=='reconstructed' else '账户当日 P&L',fmt(d['aggregate'],signed=True),('已覆盖资金回报 '+fmt(d.get('capital_return_pct'),signed=True)+'% · 非账户收益') if n(d.get('capital_return_pct')) is not None else 'USD · '+d['basis_label']),('当日盈利贡献第一',best.get('name','—') if n(best.get('value')) is not None and n(best['value'])>0 else '—',fmt(best.get('value'),signed=True) if n(best.get('value')) is not None and n(best['value'])>0 else '暂无可核验盈利'),('当日亏损贡献第一',worst.get('name','—') if n(worst.get('value')) is not None and n(worst['value'])<0 else '—',fmt(worst.get('value'),signed=True) if n(worst.get('value')) is not None and n(worst['value'])<0 else '暂无可核验亏损'),('现金 / NAV',fmt(m.get('cash_pct'),1)+'%','当日账户分析 · 非收盘快照' if historical else '账户快照 · 不是日收益')]
 totals=a.get('position_totals') or {}
 cards.insert(1,('总持仓市值 · 快照',fmt(totals.get('snapshot_net')),'USD · '+str(totals.get('snapshot_count','—'))+' 项；非历史收盘'))
 if totals.get('assets_query_at'):
  cards[-1]=('现金余额 · 快照',fmt(totals.get('snapshot_cash')),'USD · 现金/NAV '+fmt(m.get('cash_pct'),1)+'%')
  cards.insert(1,('总资产净值 · 含现金',fmt(totals.get('snapshot_nav')),'USD · 券商净资产口径'))
 for i,(label,value,desc) in enumerate(cards):
  width=793/len(cards);x=24+i*width;box(x,468,width-7,58);text(x+8,510,label,8,MUTED);text(x+8,489,value,16);text(x+8,476,clip(desc,width-20,6),6,MUTED)
 notice=('优先交易日 '+str(d['preferred'])+' 未齐；'+str(d['fallback_reason'] or '采用最近可核验历史交易日')+'。' if d['delayed'] else '')+d['note']
 text(24,452,clip(notice,790,8),8,MUTED)
 box(24,202,793,240);text(36,422,'逐证券日盈亏 · 当前返回代码' if d['current_population'] else '逐证券当日 P&L · 已返回代码',12);text(500,422,'非 '+str(d['session'])+' 历史持仓名单；缺历史归因' if d['current_population'] else '金额降序；先竖读再向右 · 美元 / 百分比',8,MUTED)
 rows=d['rows'];per_col=max(1,math.ceil(len(rows)/3));spacing=min(12.3,190/max(1,per_col));maximum=max((abs(n(x['value']) or 0) for x in rows),default=0)
 for i,x in enumerate(rows):
  col=i//per_col;idx=i%per_col;row(36+col*260,402-idx*spacing,244,x['name'],x['value'],min(8,spacing*.7),maximum,x.get('pnl_pct'))
 box(24,64,270,127);text(36,173,'行业当日盈亏贡献',11)
 sectors=d['sectors'];maximum=max((abs(n(x['value']) or 0) for x in sectors),default=0)
 if not sectors:text(36,145,'尚无已核验当日归因',9,MUTED)
 else:
  spacing=min(12,86/max(1,len(sectors)))
  for i,x in enumerate(sectors):row(36,153-i*spacing,246,clip(x['name'],75,7),x['value'],7,maximum)
 box(305,64,244,127);text(317,173,'资金结构 · 当日账户分析' if historical else '资金结构 · 账户快照',11)
 cash=[('现金',m.get('cash_pct')),('证券',m.get('positions_nav_pct')),('其他',m.get('other_net_assets_pct'))];pie(353,116,33,cash)
 for i,(label,value) in enumerate(cash):text(400,143-i*22,label+' '+fmt(value,1)+'%',9,COLORS[i])
 text(317,74,'前5仓 '+fmt(m.get('top5_pct'),1)+'% · 代理敞口/NAV '+fmt(m.get('embedded_gross_nav_multiple'),2)+'x',7,MUTED)
 box(560,64,257,127);text(572,173,'行业权重 · 已估值收盘仓位' if data.get('five_day_evidence_sha256') else '行业权重 · 持仓快照',11)
 sectors=a.get('sector_breakdown',[]);pie(603,116,33,[(x['name'],x.get('pct')) for x in sectors])
 for i,x in enumerate(sectors[:5]):text(650,149-i*15,clip(x['name'],92,7)+' '+fmt(x.get('pct'),1)+'%',7,COLORS[i])
 if len(sectors)>5:text(650,72,'另 '+str(len(sectors)-5)+' 类见完整总览',6.5,MUTED)
 text(24,45,'历史数量按成交反推；税费前重建值不等于券商净盈亏。费用/利息/分红未计；缺值不填零，数值一致不等于逐股对账。' if d['status']=='reconstructed' else '账户日盈亏与逐仓贡献的差额可能包括已平仓交易、费用、利息、股息和汇兑；未核对不强行配平。',7.5,MUTED)
 text(24,30,scope_note(a)+' 百分比=损益/(前收市值+当日买入额)；非TWR。未知不填零。',7.5,MUTED)
 text(24,15,clip('采集：'+str(d.get('source_asof') or '未提供')+'；资产：'+str(totals.get('assets_query_at') or '未提供'),600,7),7,MUTED)
 text(680,15,'数据快照 '+snapshot_hash(data)[:12],7,MUTED)
 c.showPage();c.save()

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--input',type=Path,default=Path(__file__).with_name('analytics.json'));p.add_argument('--output',type=Path);args=p.parse_args();data=json.loads(args.input.read_text());out=args.output or Path(__file__).with_name('Tiger_Daily_Brief_'+str(data.get('latest_completed_session') or 'unknown').replace('-','')+'.pdf');make(data,out);print(out)
