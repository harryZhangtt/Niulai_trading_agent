"""Freeze real NOW evidence and controlled baseline contrasts before model outputs.

Historical release bodies are provider reconstructions, not a verified vintage
archive. Only one distinct resolved forecast quarter is available in this packet.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from shared.research_sources.artifacts import ROOT, SOURCE_STATE, digest, read, save
from shared.research_sources.store import Store
from shared.research_sources.indexing import RecordIndex

STUDY = 'now-contribution-e2e-20261031'
BASE = SOURCE_STATE / 'runtime' / STUDY / 'prepared-v1'
RESEARCH = ROOT / 'mentor/runtime' / STUDY / 'source-research'
OBSERVATIONS = {
    'S01': [('actual_q1','FY2025Q1','USD','USD millions','GAAP subscription revenue','3005'),
            ('guidance_q2','FY2025Q2','USD','USD millions','GAAP subscription revenue guidance',None),
            ('margin_q1','FY2025Q1','not_applicable','percent','GAAP subscription gross margin','81.5')],
    'S04': [('actual_q2','FY2025Q2','USD','USD millions','GAAP subscription revenue','3113'),
            ('guidance_q3','FY2025Q3','USD','USD millions','GAAP subscription revenue guidance',None),
            ('acv_target','by2026','USD','USD millions annual contract value','management target','1000'),
            ('margin_q2','FY2025Q2','not_applicable','percent','GAAP subscription gross margin','80'),
            ('renewal_timing','FY2025Q3','not_applicable','percentage points of cRPO growth','management renewal-timing forecast',None)],
    'S02': [('ai_asset_meter','effective_2025-05-01','not_applicable','Subscription Units per managed AI Asset','contract meter definition','1')],
    'S03': [('assists','FAQ_revision_2025-09-23','not_applicable','Assists usage units','issuer-employee FAQ',None)],
    'S05': [('launch','2025-05-06_launch','not_applicable','availability statement','issuer product announcement',None)],
    'S08': [('itom_basis','FY2023Q3','not_applicable','Subscription Units per managed IT resources','SEC filing pricing description',None)]}


def clean(text):
    text = re.sub(r'(?m)^L\d+(?:@P[\d-]+)?: ?', '', text)
    return re.sub(r'【\d+†([^†】]+)(?:†[^】]+)?】', r'\1', text)


def source_segments():
    captures = json.loads((RESEARCH / 'native-receipts.json').read_text())
    found = {}
    for operation in captures['operations']:
        if 'search_query' in operation['args']: continue
        raw = operation['result'] or ''
        heads = list(re.finditer(r'(?m)^([^\n]+)\n\ue200cite\ue202([^\ue201]+)\ue201', raw))
        for i, head in enumerate(heads):
            found[head[2]] = raw[head.start():heads[i+1].start() if i+1 < len(heads) else len(raw)]
    return found


def prepare():
    BASE.mkdir(parents=True, exist_ok=True)
    reference = json.loads((RESEARCH / 'source-fact-roster.json').read_text())
    segments = source_segments(); sources = {}; now = datetime.now(timezone.utc).isoformat()
    for source in reference['sources']:
        sid = source['id']
        if sid not in {'S01','S02','S03','S04','S05','S08'}: continue
        raw = segments[source['native_ref']]; text = clean(raw)
        pub = source.get('last_modified_date') or source.get('publication_date')
        available = pub + 'T23:59:59Z' if pub else now
        receipt = {'schema_version':1,'provider':'native_open_primary_capture',
            'source_url':source['url'],'upstream_id':source['url'],'source_version':digest(raw),
            'published_at':source.get('publication_date'),'available_at':available,
            'retrieved_at':now,'availability_basis':'issuer_dated_reconstruction' if pub else 'first_observed',
            'modified_at':source.get('last_modified_date','')+'T23:59:59Z' if source.get('last_modified_date') else None,
            'access_level':'document','raw':save(BASE/'sources',raw.encode(),suffix='txt'),
            'text':save(BASE/'sources',text.encode(),suffix='txt'),
            'capture_method':'substantive native open/find text, not raw issuer HTML/PDF bytes',
            'limitations':[source['vintage_limit']]}
        sources[sid]={'source_ref':save(BASE/'sources',receipt),'receipt':receipt,'text':text,'metadata':source}
    # Reuse actual indexed old research metadata as context, never as new facts.
    history_dir = SOURCE_STATE/'runtime/raw-index-integration-20261031/shadow-v1.0.1/catalog/index'
    history = RecordIndex(history_dir)
    selected = history.select(entity='NOW',baseline_hash=digest({'study':STUDY,'role':'history'}),
        requirement_id='now-existing-research',cutoff='2026-10-31T23:59:59Z',limit=32)
    history_snapshot = history.checkpoint('now-contribution-history:'+digest(selected['context']),selected)
    old_notes=[]
    for candidate in selected['candidates']:
        row=history.store.read(candidate['binding']['observation_id'])
        if row['payload']['kind']=='section_metadata':
            old_notes.append({'title':row['payload']['title'],'metadata':row['payload']['content'],
                'binding':candidate['binding'],'status':'unverified_prior_research_context_not_original_source'})
    current='2026-10-31T23:59:59Z'
    basic=[{'id':'h1','text':'AI governance may support commercial value capture, but incremental AI-only net pricing, paid usage and customer profit are not established.','status':'hypothesis'},
           {'id':'h2','text':'ServiceNow already had subscription-unit concepts in ITOM; a non-seat concept alone is not entirely new to the company.','status':'prior_context'}]
    configurations=[
        ('meter_refinement',current,['S02','S08'],basic,None,
         'What does the AI Control Tower asset-to-SU definition add to the existing commercial thesis? Identify exactly what it establishes and what it does not.'),
        ('meter_already_known',current,['S02'],basic+[{'id':'h3','text':'AI Control Tower already maps one managed AI Asset to one Subscription Unit. Dollar pricing, extra purchases and realized incremental revenue remain unverified.','status':'already_recorded'}],None,
         'Does this repeat of the same licensing document add a new revenue mechanism to this baseline, or chiefly confirm an existing one?'),
        ('launch_scope','2025-05-07T23:59:59Z',['S05'],[{'id':'h1','text':'An AI-governance product is a possible new platform capability; launch status and commercial outcomes need evidence.','status':'hypothesis'}],None,
         'Separate the launch and availability states of AI Control Tower and AI Agent Fabric. What can be added to research without claiming adoption or revenue?'),
        ('usage_entitlements',current,['S02','S03'],basic,None,
         'Distinguish AI Control Tower Subscription Units from Now Assist Assists and tier entitlements. What incremental economics remain unknown?'),
        ('acv_target','2025-07-24T23:59:59Z',['S04'],basic,'Q3',
         'Assess the Now Assist ACV target and Q3 subscription guidance. Does the ACV target establish achieved AI revenue or support an extra Q3 forecast uplift?'),
        ('margin_counterevidence','2025-07-24T23:59:59Z',['S01','S04'],basic,'Q3',
         'Assess the subscription gross-margin comparison and renewal-timing caveat. Identify risk and alternatives without attributing company-wide movements solely to AI.'),
        ('forecast_q2','2025-05-07T23:59:59Z',['S01','S05'],[{'id':'h1','text':'Baseline Q2 subscription forecast is the midpoint of issuer Q1 guidance. AI commercialization is already part of company planning; a new launch is not automatically incremental booked revenue.','status':'baseline_assumption'}],'Q2',
         'Given the April guidance baseline and May Control Tower launch, retain or revise the same Q2 subscription revenue point forecast with a source-bound rationale. No later outcome is available in this packet.'),
        ('historical_vintage','2025-05-07T23:59:59Z',['S01'],[{'id':'h1','text':'Baseline Q2 subscription forecast is the issuer-guidance midpoint. A currently edited FAQ is not proof of its earlier text.','status':'baseline_assumption'}],'Q2',
         'The current FAQ was modified on September 23, 2025 and its earlier body is not archived; it is excluded at this May cutoff. Does this information gap justify changing the Q2 forecast?')]
    cases=[]; labels=[]
    for cid,cutoff,sids,hypotheses,target,question in configurations:
        forecast=None
        if target:
            forecast={'period':'FY2025'+target,'currency':'USD','unit':'USD millions','basis':'GAAP subscription revenue',
                      'point':'3032.5' if target=='Q2' else '3262.5',
                      'origin':'issuer_guidance_midpoint_research_baseline_not_consensus'}
        baseline={'entity':'NOW','as_of':cutoff,'hypotheses':hypotheses,'forecast':forecast,
            'origin':'controlled source-bound development baseline, not a claimed historical fund forecast',
            'prior_index_metadata':old_notes if cutoff==current else [],
            'history_snapshot_ref':history_snapshot['selection_ref'] if cutoff==current else None}
        baseline_ref=save(BASE/'baselines',baseline)
        store=Store(BASE/'cases'/cid/'store');bindings=[];visible=[]
        for sid in sids:
            source=sources[sid]
            # Exact document excerpts, limited before dispatch. These headers distinguish
            # statement scope from target dimensions on an optional forecast.
            text=source['text'];pieces=[text[:2200]]
            needles={'S01':['Second Quarter 2025 Outlook','3,030','Subscription gross profit'],
                'S04':['1 billion','3,260','two percentage','Gross Margin','80%'],
                'S02':['AI Asset','Ratio','Subscription Units'],
                'S03':['license','Assists','Pro Plus'],'S05':['Availability','generally available'],
                'S08':['ITOM']}[sid]
            for needle in needles:
                pos=text.casefold().find(needle.casefold())
                if pos>=0:pieces.append(text[max(0,pos-500):pos+2800])
            excerpt='\n\n'.join(dict.fromkeys(pieces))
            for key,period,currency,unit,basis,value in OBSERVATIONS[sid]:
                eid=sid+'_'+key
                payload={'entity':'NOW','metric':key,'period':period,'currency':currency,
                    'unit':unit,'basis':basis,'value':value,
                    'available_at':source['receipt']['available_at'],'source_ref':source['source_ref']}
                store.create('freeze:'+eid,eid,payload)
                bindings.append({'observation_id':eid,'revision':1,'lifecycle_revision':1})
                metric_needles={'actual_q1':['3,005'],'guidance_q2':['3,030'],
                    'margin_q1':['81.5'],'actual_q2':['3,113'],'guidance_q3':['3,260'],
                    'acv_target':['1 billion'],'margin_q2':['80%','Gross Margin'],
                    'renewal_timing':['renew','two percentage']}
                metric_excerpt=excerpt
                if sid in {'S01','S04'}:
                    slices=[text[:1600]]
                    for needle in metric_needles[key]:
                        pos=text.casefold().find(needle.casefold())
                        if pos>=0:slices.append(text[max(0,pos-600):pos+2000])
                    metric_excerpt='\n\n'.join(dict.fromkeys(slices))
                visible.append({'evidence_id':eid,'revision':1,'lifecycle_revision':1,
                    'source_sha256':source['source_ref']['sha256'],**{k:payload[k] for k in ('entity','period','currency','unit','basis')},
                    'source_url':source['receipt']['source_url'],'available_at':payload['available_at'],
                    'availability_basis':source['receipt']['availability_basis'],
                    'limitations':source['receipt']['limitations'],'text_excerpt':metric_excerpt})
        context={'case_id':cid,'entity':'NOW','cutoff':cutoff,'baseline_ref':baseline_ref,
            'store_directory':str(BASE/'cases'/cid/'store'),'bindings':bindings,'allow_reconstructed_history':True}
        snapshot=store.commit_snapshot('source-context',save(BASE/'contexts',{'case_id':cid,'cutoff':cutoff}),bindings)
        packet={'case_id':cid,'entity':'NOW','cutoff':cutoff,'question':question,
            'baseline_sha256':baseline_ref['sha256'],'baseline':baseline,'evidence':visible,
            'excluded_sources':[{'source':'S03','reason':'edited_after_cutoff; earlier body not archived'}] if cid=='historical_vintage' else [],
            'historical_limit':'Reconstructed dated issuer evidence; modern model may know later outcomes. No sealed point-in-time or alpha claim.'}
        packet_ref=save(BASE/'worker-packets',packet)
        cases.append({'id':cid,'packet_ref':packet_ref,'validation_context_ref':save(BASE/'contexts',context),
            'evidence_snapshot':snapshot,'target':forecast['period'] if forecast else None})
        labels.append({'id':cid,'target':forecast['period'] if forecast else None,
            'actual':'3113' if target=='Q2' else None,'actual_source':sources['S04']['source_ref'] if target=='Q2' else None,
            'actual_published_at':'2025-07-23T23:59:59Z' if target=='Q2' else None,
            'outcome_state':'resolved_shared_target' if target=='Q2' else 'not_retrieved' if target else 'not_applicable'})
    result={'study':STUDY,'cases':cases,'labels_ref':save(BASE/'expected-only',labels),
        'history_snapshot':history_snapshot,'source_refs':{k:v['source_ref'] for k,v in sources.items()},
        'resolved_unique_forecast_targets':1,'source_scope':'historical/current source-bound development cases'}
    return save(BASE/'inputs',result)


if __name__=='__main__':
    print(json.dumps(prepare()))
