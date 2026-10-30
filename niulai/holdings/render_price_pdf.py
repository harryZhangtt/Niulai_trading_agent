"""Self-contained colored PDF from the exact same frozen price presentation model."""
from pathlib import Path
import argparse,json,html
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,KeepTogether
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor,white
from reportlab.lib.pagesizes import A4,landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from price_summary_view import GROUPS,f,level,ts,conditions_text

FONT='PriceCJK'
pdfmetrics.registerFont(TTFont(FONT,str(Path(__file__).with_name('fonts')/'NotoSansSC-Regular.ttf')))
def make(model,path):
    normal=ParagraphStyle('p',fontName=FONT,fontSize=8,leading=11,textColor=HexColor('#24364c'))
    small=ParagraphStyle('s',parent=normal,fontSize=7,leading=9)
    title=ParagraphStyle('t',parent=normal,fontSize=19,leading=24,spaceAfter=8)
    heading=ParagraphStyle('h',parent=normal,fontSize=12,leading=16,spaceBefore=10,spaceAfter=6)
    def p(s,style=normal):return Paragraph(html.escape(str(s)),style)
    context='历史格式修订｜' if model.get('historical_presentation') else '本次已保存评估｜'
    caveat='历史资料，不是当前行情。' if model.get('historical_presentation') else ''
    story=[p('牛来 · 价格提醒变化总览',title),p(context+'纽约交易日 '+model['session']+'｜评估截止 '+ts(model['as_of'])+'｜对比 '+ts(model['prior_as_of'])),p(caveat+'新增记录 ≠ 新穿越；到价 ≠ 买入建议。两次采样均满足，不证明期间持续满足。')]
    cells=[]
    for key,label,color in GROUPS:
        cells.append(Paragraph('<font color="'+color+'" size="20">'+str(model['groups'][key])+'</font><br/>'+html.escape(label),small))
    cards=Table([cells],colWidths=[109]*7,hAlign='LEFT');cards.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),HexColor('#f0f4f9')),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10)]));story+=[Spacer(1,9),cards,Spacer(1,6)]
    eventlist='；'.join(e['ticker']+' '+level(e) for e in model['new_signal_records']) or '无'
    story+=[p('实际新增引擎记录 '+str(len(model['new_signal_records']))+'条：'+eventlist),p('本次有依据的方向性进入 '+str(model['directional_evidence_count'])+'条。所有启用规则均列于后表，计数单位为规则。')]
    widths=[64,90,105,105,90,309]
    for key,label,color in sorted(GROUPS,key=lambda g:['newly_satisfied','newly_confirmed','already_satisfied','approach_only','exited','not_reached','unverifiable'].index(g[0])):
        rows=[r for r in model['rows'] if r['group']==key]
        story.append(p(label+' · '+str(len(rows))+'条',heading))
        if not rows:story.append(p('0条',small));continue
        data=[[p(x,small) for x in ['标的','原始线 / 缓冲边界','上次 → 本次','距原始线','报价时点','证据与限制']]]
        for r in rows:
            gap=r.get('gap_pct');dist='未知' if gap is None else ('已越过 '+f(abs(float(gap)))+'%' if float(gap)<=0 else '尚差 '+f(gap)+'%')
            status=('新增记录；' if r.get('new_engine_record') else '')+('仅可验证收盘；' if r.get('quality_limited') else '')+r['reason']
            if r.get('entry_conditions'):status+='；附加条件未被价格引擎核验：'+conditions_text(r['entry_conditions'])
            if r.get('expires_at'):status+='；有效期 '+r['expires_at']
            data.append([p(r['ticker'],small),p(level(r)+' / '+f(r.get('zone_edge')),small),p(f(r.get('prior_close'))+' → '+f(r.get('close')),small),p(dist,small),p(ts(r.get('quote_time')),small),p(status,small)])
        tint={'already_satisfied':'#edf8f3','newly_confirmed':'#edf9fc','newly_satisfied':'#edf3ff','approach_only':'#fff9e9','exited':'#fff3e8','not_reached':'#fff4f5','unverifiable':'#f1f3f5'}[key]
        tab=Table(data,colWidths=widths,repeatRows=1,hAlign='LEFT');tab.setStyle(TableStyle([('FONTNAME',(0,0),(-1,-1),FONT),('BACKGROUND',(0,0),(-1,0),HexColor('#edf2f7')),('BACKGROUND',(0,1),(-1,-1),HexColor(tint)),('TEXTCOLOR',(0,1),(0,-1),HexColor(color)),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,-1),.3,HexColor('#dfe7f0')),('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3)]));story.append(tab)
    story+=[p('仅报价，没有启用提醒线',heading),p('；'.join(q['ticker']+' '+f(q.get('bar',{}).get('close'))+' ('+ts(q.get('bar',{}).get('quote_time'))+')' for q in model['quote_only'])),p('来源与范围：全部保存的启用规则、原始提醒线和错误。基于离散采样/日线，不能确定穿越时刻、顺序或次数。保存来源哈希 '+model['source_payload_sha256'],small)]
    def footer(c,doc):
        c.setFont(FONT,7);c.setFillColor(HexColor('#6a7a8d'));c.drawString(30,16,'纽约 '+model['session']+(' · 历史价格报告' if model.get('historical_presentation') else ' · 价格报告')+' · 规则范围 '+str(len(model['rows']))+' · 第'+str(doc.page)+'页')
    SimpleDocTemplate(str(path),pagesize=landscape(A4),leftMargin=30,rightMargin=30,topMargin=24,bottomMargin=28,title='牛来价格提醒变化总览').build(story,onFirstPage=footer,onLaterPages=footer)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('model',type=Path);p.add_argument('output',type=Path);a=p.parse_args();make(json.loads(a.model.read_text()),a.output)
