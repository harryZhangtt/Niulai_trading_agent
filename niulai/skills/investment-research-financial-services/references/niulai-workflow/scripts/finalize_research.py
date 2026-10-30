#!/usr/bin/env python3
"""Assemble already-performed independent review and real save/readback proof.
No shared DB writes, no invented review, no model changes, no source gate bypass.
"""
import argparse,copy,hashlib,json,sys
from research_store import instant
from pathlib import Path
SKILL=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(SKILL/'references/niulai-workflow/scripts'))
import research_completion as completion
from valuation_evidence import validate as validate_valuation_evidence
from entry_policy_evidence import validate as validate_entry_policy_evidence
from crypto_evidence import validate as validate_crypto_evidence
from options_evidence import validate as validate_options_evidence
from critical_data_evidence import validate as validate_critical_data
from research_resolution_evidence import validate as validate_research_resolution
from rationale_guard import validate as validate_rationale, publication_times, requires_current, SCHEMA_VERSION
from jsonschema import Draft202012Validator,FormatChecker


def ref(path):
    p=Path(path).resolve();return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}


def load(path):return json.loads(Path(path).read_text())

def receipt_identity(value):
    if isinstance(value,dict):
        if value.get('library_file_id') and value.get('current_version_number') is not None and (value.get('status')=='succeeded' or value.get('success') is True):
            return value['library_file_id'],value['current_version_number']
        for v in value.values():
            got=receipt_identity(v)
            if got:return got
    if isinstance(value,list):
        for v in value:
            got=receipt_identity(v)
            if got:return got
    return None


def assemble(request,outdir):
    outdir=Path(outdir).resolve();outdir.mkdir(parents=True,exist_ok=True)
    original=Path(request['record']).resolve();rec=load(original);item=load(request['item'])
    review_path=Path(request['review']).resolve();review=load(review_path);binding_path=Path(request['bindings']).resolve();bindings=load(binding_path)
    ticker=rec['subject']['ticker'];run_id=request['run_id'];input_hash=request['input_hash']
    if item['ticker']!=ticker or review['ticker']!=ticker:raise ValueError('Ticker mismatch')
    if rec.get('parent_run_id')!=run_id and rec['run_id']!=run_id+':'+ticker:raise ValueError('Wrong parent run')
    if bindings['review_sha256']!=ref(review_path)['sha256'] or bindings['reviewer_id']!=review['reviewer_id']:raise ValueError('Binding/review mismatch')
    if review['reviewer_id'].split('/')[-1]==rec['audit']['author_id'].split('/')[-1]:raise ValueError('Reviewer equals author')
    if review['source_review']!='complete' or review['reasoning_review']!='complete' or review['status']!='approved_scoped_decision':raise ValueError('Review not approved')
    arts={a['id']:a for a in rec['artifacts']}
    if len(arts)!=len(rec['artifacts']):raise ValueError('Duplicate author artifact IDs')
    for a in arts.values():completion.hashed(a)
    for a in bindings.get('extra_artifacts',[]):
        completion.hashed(a)
        if a['id'] in arts and arts[a['id']]!=a:raise ValueError('Conflicting extra artifact ID')
        arts[a['id']]=a
    aliases=bindings['artifact_aliases']
    def mapped(i):
        a=aliases.get(i,i)
        if a not in arts:raise ValueError('Unresolved reviewer artifact '+i)
        return a
    # Canonical artifact IDs are authoritative; legacy basenames must be unique.
    if not review.get('artifact_hashes') or not review.get('reviewed_artifact_ids'):raise ValueError('Review input hashes required')
    pinned=set()
    for key,hash_value in review['artifact_hashes'].items():
        if key in arts:
            artifact=arts[key]
        else:
            matching=[a for a in arts.values() if Path(a['path']).name==key]
            if len(matching)>1:raise ValueError('Ambiguous review artifact basename '+key)
            if not matching:raise ValueError('Unresolved review artifact hash key '+key)
            artifact=matching[0]
        if artifact['sha256']!=hash_value:raise ValueError('Review is stale for '+key)
        pinned.add(artifact['id'])
    for i in review['reviewed_artifact_ids']:
        if mapped(i) not in pinned:raise ValueError('Reviewed artifact hash is not pinned')
    review_id='independent-review:'+ticker;binding_id='review-bindings:'+ticker
    arts[review_id]={'id':review_id,**ref(review_path),'kind':'review','depends_on':[{'artifact_id':mapped(i),'sha256':arts[mapped(i)]['sha256']} for i in review['reviewed_artifact_ids']]}
    arts[binding_id]={'id':binding_id,**ref(binding_path),'kind':'other','depends_on':[{'artifact_id':review_id,'sha256':ref(review_path)['sha256']}]}
    command_ref=bindings['review_command_receipt'];completion.hashed(command_ref)
    command_id='independent-command:'+ticker
    arts[command_id]={'id':command_id,**command_ref,'kind':'command_receipt','depends_on':[]}
    command=completion.structured(command_ref)
    if command.get('exit_code')!=0 or not command.get('command') or not (command.get('stdout') or command.get('output')):raise ValueError('Reviewer execution receipt incomplete')
    facts=copy.deepcopy(review['factual_samples']);maps=bindings['factual_sample_bindings']
    if len(maps)!=len(facts) or {m['index'] for m in maps}!=set(range(len(facts))):raise ValueError('Every reviewed fact needs explicit binding')
    claims={c['id']:c for c in rec['claims']};sources={s['id']:s for s in rec['sources']}
    for m in maps:
        cid,sid,pid=m['claim_id'],m['source_id'],m['passage_id']
        if cid not in claims or sid not in sources or pid not in {p['id'] for p in sources[sid]['passages']}:raise ValueError('Unresolved reviewed fact binding')
        if not any(e['source_id']==sid and e['passage_id']==pid for e in claims[cid]['evidence_refs']):raise ValueError('Review binding is not supported by the claim refs')
        facts[m['index']].update(claim_id=cid,source_id=sid,passage_id=pid)
    numbers=copy.deepcopy(review['numerical_checks'])
    for n in numbers:
        n['input_artifact_ids']=[mapped(i) for i in n['input_artifact_ids']];n['output_artifact_id']=mapped(n['output_artifact_id'])
    findings=[]
    for i,f in enumerate(review['findings']):
        if f['disposition']=='unresolved':raise ValueError('Unresolved review finding')
        findings.append({'id':'independent-finding-'+str(i),'description':f.get('description',f.get('finding')),'disposition':f['disposition'],'rationale':f['rationale'],'evidence_artifact_ids':[mapped(a) for a in f.get('evidence_artifact_ids',[])]})
    rec['artifacts']=list(arts.values());rec['audit'].update(factual_samples=facts,numerical_checks=numbers,findings=findings,
        independent_review={'reviewer_id':review['reviewer_id'],'review_artifact_id':review_id,'reviewed_artifact_ids':[mapped(i) for i in review['reviewed_artifact_ids']],'source_review':'complete','reasoning_review':'complete'},
        command_artifact_ids=[command_id],warnings_reviewed_artifact_id=review_id)
    rec['stages']['review']={'status':'complete','evidence_refs':[review_id,binding_id,command_id]}
    publications=request.get('publications',[]);readbacks=[];receipts=[];observed_publication_times=[]
    for pub in publications:
        aid=pub['artifact_id'];a=arts[aid];save_ref=ref(pub['receipt']);save_receipt=load(pub['receipt']);identity=receipt_identity(save_receipt)
        observed_publication_times.extend(publication_times(save_receipt))
        if not identity:raise ValueError('No successful actual Library save receipt')
        fid,version=identity
        confirmed=pub.get('confirmed_at')
        if not confirmed:raise ValueError('Fixed actual readback confirmed_at required; do not regenerate timestamp on retry')
        instant(confirmed)
        rb={'artifact_id':aid,'file_id':fid,'version':version,'content':ref(pub['readback']),'receipt':save_ref}
        if pub.get('archive_member'):rb['archive_member']=pub['archive_member']
        readbacks.append(rb);receipts.append({'artifact_id':aid,'file_id':fid,'version':version,'confirmed_at':confirmed,'sha256':a['sha256']})
    if publications:
        rec['status']='complete';rec['persistence']={'status':'saved','receipts':receipts};rec['result']['publication_status']='saved'
        rec['stages']['persistence']={'status':'complete','evidence_refs':[r['file_id'] for r in receipts]}
        topic=rec['coverage']['review_publication']
        topic.update(status='evidenced',finding='Independent factual/numerical/reasoning review completed; actual report save receipt and downloaded readback bytes are checked by finalization.',artifact_refs=[review_id,binding_id,command_id,rec['result']['report_artifact_id']])
    else:
        rec['status']='in_progress';rec['persistence']={'status':'unsaved'};rec['result']['publication_status']='draft';rec['stages']['persistence']={'status':'pending','evidence_refs':[]}
    if publications:
        validate_critical_data(rec, observed_publication_times=observed_publication_times, decision_action=item['action'])
        validate_research_resolution(rec, observed_publication_times=observed_publication_times, decision_action=item['action'])
        validate_options_evidence(rec, observed_publication_times=observed_publication_times)
        validate_valuation_evidence(rec)
        validate_entry_policy_evidence(rec)
        validate_crypto_evidence(rec)
        if requires_current(rec, observed_publication_times):
            rec['schema_version']=SCHEMA_VERSION
        validate_rationale(rec, observed_publication_times=observed_publication_times)
    record_path=outdir/(ticker+'_candidate_record.json');record_path.write_text(json.dumps(rec,ensure_ascii=False,indent=2)+'\n')
    Draft202012Validator(load(completion.SCHEMA),format_checker=FormatChecker()).validate(rec)
    final={'ticker':ticker,'status':'complete' if publications else 'partial','action':item['action'],'input_hash':input_hash,'record':ref(record_path),'persistence_readbacks':readbacks,'blockers':[]}
    if publications:completion.inspect_record(final,run_id)
    final_path=outdir/(ticker+'_finalized_record.json');record_path.replace(final_path);final['record']=ref(final_path)
    path=outdir/(ticker+'_completion_item.json');path.write_text(json.dumps(final,ensure_ascii=False,indent=2)+'\n')
    return final


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--request',required=True);p.add_argument('--output-directory',required=True);p.add_argument('--manifest');a=p.parse_args()
    req=load(a.request);items=[assemble(x,a.output_directory) for x in req['items']]
    if a.manifest:
        manifest=load(a.manifest);existing={i['ticker']:i for i in manifest['items']};existing.update({i['ticker']:i for i in items});manifest['items']=[existing[t] for t in manifest['expected_tickers'] if t in existing]
        out=Path(a.output_directory);(out/'completion_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        audit=completion.audit(manifest);(out/'completion_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'assembled':[i['ticker'] for i in items],'run_status':audit['status'],'complete':audit['complete'],'expected':audit['expected']}))
    else:print(json.dumps({'assembled':[i['ticker'] for i in items]}))
if __name__=='__main__':main()
