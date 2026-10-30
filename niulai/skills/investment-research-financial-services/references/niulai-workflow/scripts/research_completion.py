#!/usr/bin/env python3
"""Audit all-ticker research completion; never execute agents or certify truth.
Reuses the maintained research-run schema plus artifact/reference/readback checks.
A completed queue attempt with partial research remains unfinished research.
"""
import argparse
import hashlib
import json
import io
import zipfile
from decimal import Decimal
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
from research_store import connect
from task_queue import read
from valuation_evidence import validate as validate_valuation_evidence
from entry_policy_evidence import validate as validate_entry_policy_evidence
from crypto_evidence import validate as validate_crypto_evidence
from options_evidence import validate as validate_options_evidence
from critical_data_evidence import validate as validate_critical_data
from research_resolution_evidence import validate as validate_research_resolution
from rationale_guard import validate as validate_rationale, publication_times

ROOT=Path(__file__).resolve().parents[3]
SCHEMA=ROOT/'schemas/research-run.schema.json'
ACTIONS={'buy','add','hold','wait','no_buy','reduce','exit'}


def hashed(ref):
    if not isinstance(ref,dict) or not ref.get('path') or not ref.get('sha256'):
        raise ValueError('Hashed artifact reference required')
    path=Path(ref['path'])
    if not path.is_absolute() or not path.is_file():raise ValueError('Artifact missing or nonabsolute')
    raw=path.read_bytes()
    if not raw or hashlib.sha256(raw).hexdigest()!=ref['sha256']:raise ValueError('Artifact empty or hash mismatch')
    return raw


def structured(ref):return json.loads(hashed(ref))


def find_receipt(value,file_id,version):
    if isinstance(value,dict):
        fid=value.get('library_file_id',value.get('file_id'))
        v=value.get('current_version_number',value.get('version'))
        success=value.get('status') in ('succeeded','success') or value.get('success') is True
        if fid==file_id and str(v)==str(version) and success:return True
        return any(find_receipt(x,file_id,version) for x in value.values())
    if isinstance(value,list):return any(find_receipt(x,file_id,version) for x in value)
    return False


def inspect_record(item,run_id):
    rec=structured(item.get('record'))
    Draft202012Validator(json.loads(SCHEMA.read_text()),format_checker=FormatChecker()).validate(rec)
    validate_valuation_evidence(rec)
    validate_entry_policy_evidence(rec)
    validate_crypto_evidence(rec)
    if rec['status']!='complete' or rec['scope'] not in ('company_full','fund_full','crypto_full'):
        raise ValueError('Full applicable research remains incomplete')
    if rec['subject']['ticker']!=item['ticker']:raise ValueError('Ticker mismatch')
    if rec.get('parent_run_id')!=run_id and rec['run_id']!=run_id+':'+item['ticker']:raise ValueError('Research record is not from this run')
    if item.get('action') not in ACTIONS:raise ValueError('Supported decision required; no forced buy')
    if rec['persistence']['status']!='saved' or rec['result']['publication_status']!='saved':
        raise ValueError('Research persistence not completed')
    arts={a['id']:a for a in rec['artifacts']}
    if len(arts)!=len(rec['artifacts']):raise ValueError('Duplicate artifact IDs')
    for a in arts.values():
        hashed(a)
        for dep in a.get('depends_on',[]):
            if dep['artifact_id'] not in arts or arts[dep['artifact_id']]['sha256']!=dep['sha256']:
                raise ValueError('Unresolved or stale artifact dependency')
    def refs(values):
        if any(v not in arts for v in values):raise ValueError('Unresolved artifact reference')
    sources={s['id']:s for s in rec['sources']};claims={c['id']:c for c in rec['claims']}
    if len(sources)!=len(rec['sources']) or len(claims)!=len(rec['claims']):raise ValueError('Duplicate source/claim IDs')
    for s in sources.values():refs([s['snapshot_artifact_id']])
    for c in claims.values():
        refs(c.get('artifact_refs',[]))
        for e in c['evidence_refs']:
            if e['source_id'] not in sources or e['passage_id'] not in {p['id'] for p in sources[e['source_id']]['passages']}:
                raise ValueError('Claim source passage unresolved')
    for topic in rec['coverage'].values():
        if any(c not in claims for c in topic.get('claim_ids',[])):raise ValueError('Coverage claim unresolved')
        refs(topic.get('artifact_refs',[]))
    audit=rec['audit'];review=audit['independent_review']
    if review['reviewer_id']==audit['author_id']:raise ValueError('Review is not independent')
    refs([review['review_artifact_id']]+review['reviewed_artifact_ids'])
    if not audit['factual_samples'] or not audit['numerical_checks']:raise ValueError('Zero checked review samples')
    for sample in audit['factual_samples']:
        cid,sid,pid=sample['claim_id'],sample['source_id'],sample['passage_id']
        if cid not in claims or sid not in sources or pid not in {p['id'] for p in sources[sid]['passages']}:
            raise ValueError('Factual review sample unresolved')
        if sample['status']!='matched' or sample['reported']!=sample['verified']:raise ValueError('Unresolved factual mismatch')
    model=rec['model']
    for check in model['checks']+audit['numerical_checks']:
        refs(check['input_artifact_ids']+[check['output_artifact_id']])
        actual,expected,tol=(Decimal(str(check[k])) for k in ('actual','expected','tolerance'))
        if not all(x.is_finite() for x in (actual,expected,tol)) or tol<0 or abs(actual-expected)>tol:
            raise ValueError('Numerical check does not reconcile')
    weights=[Decimal(str(s['weight'])) for s in model['scenarios']]
    if any(not w.is_finite() or w<0 for w in weights) or abs(sum(weights)-1)>Decimal('0.000000001'):
        raise ValueError('Scenario weights invalid')
    for k,v in model.items():
        if k.endswith('_artifact_ids'):refs(v)
        elif k.endswith('_artifact_id'):refs([v])
    command_ids=set(model['command_artifact_ids']+audit['command_artifact_ids'])
    if not command_ids:raise ValueError('Missing execution receipt')
    for cid in command_ids:
        refs([cid]);cmd=structured(arts[cid])
        if cmd.get('exit_code')!=0 or isinstance(cmd.get('exit_code'),bool) or not cmd.get('command') or not (cmd.get('output') or cmd.get('stdout')):
            raise ValueError('Execution receipt lacks successful command/output')
    persisted={r['artifact_id']:r for r in rec['persistence']['receipts']}
    report_id=rec['result']['report_artifact_id']
    if report_id not in persisted:raise ValueError('Final report has no persistence receipt')
    readbacks={r['artifact_id']:r for r in item.get('persistence_readbacks',[])}
    observed_publication_times=[]
    for aid,p in persisted.items():
        refs([aid])
        if p['sha256']!=arts[aid]['sha256']:raise ValueError('Saved receipt hash differs from artifact')
        rb=readbacks.get(aid)
        if not rb or rb.get('file_id')!=p['file_id'] or str(rb.get('version'))!=str(p['version']):
            raise ValueError('Saved artifact lacks matching readback')
        readback_bytes=hashed(rb['content'])
        if rb.get('archive_member'):
            member=rb['archive_member']
            if member.startswith('/') or '..' in Path(member).parts:raise ValueError('Unsafe archive member')
            with zipfile.ZipFile(io.BytesIO(readback_bytes)) as archive:readback_bytes=archive.read(member)
        if hashlib.sha256(readback_bytes).hexdigest()!=arts[aid]['sha256']:
            raise ValueError('Readback bytes differ from saved artifact')
        actual_receipt=structured(rb['receipt'])
        observed_publication_times.extend(publication_times(actual_receipt))
        if not find_receipt(actual_receipt,p['file_id'],p['version']):
            raise ValueError('Actual saved receipt not referenced/matched')
    validate_options_evidence(rec, observed_publication_times=observed_publication_times)
    validate_critical_data(rec, observed_publication_times=observed_publication_times, decision_action=item['action'])
    validate_research_resolution(rec, observed_publication_times=observed_publication_times, decision_action=item['action'])
    rationale_result=validate_rationale(rec, observed_publication_times=observed_publication_times)
    if rationale_result.get('status')=='validated' and rationale_result['action']!=item['action']:
        raise ValueError('Rationale action differs from published decision')
    return {'record_run_id':rec['run_id'],'checked_artifacts':len(arts),'checked_facts':len(audit['factual_samples']),'checked_numbers':len(audit['numerical_checks'])}


def audit(manifest):
    expected=manifest.get('expected_tickers')
    if not isinstance(expected,list) or not expected or len(expected)!=len(set(expected)) or any(not isinstance(t,str) or not t for t in expected):
        raise ValueError('Nonempty unique expected ticker list required')
    run_id=manifest.get('run_id')
    if not isinstance(run_id,str) or not run_id:raise ValueError('run_id required')
    input_hash=manifest.get('input_hash')
    if not isinstance(input_hash,str) or not input_hash:raise ValueError('Frozen input_hash required')
    items=manifest.get('items',[]);by={i['ticker']:i for i in items}
    if len(by)!=len(items) or set(by)-set(expected):raise ValueError('Duplicate or unexpected result tickers')
    with connect(manifest['queue_db'],readonly=True) as db:
        jobs=[j for j in read(db) if j['run_id']==run_id]
    queues={j['ticker']:j for j in jobs}
    if len(queues)!=len(jobs) or set(queues)-set(expected):raise ValueError('Queue roster differs from expected scope')
    outcomes=[];actions=[]
    for ticker in expected:
        item=by.get(ticker);job=queues.get(ticker);issues=[]
        if item is None:issues.append('Missing ticker result')
        elif item.get('input_hash')!=input_hash:issues.append('Result input fingerprint mismatch')
        if job is None:issues.append('Missing queue task')
        elif job['state']!='completed':issues.append('Queue attempt '+job['state'])
        if item is not None and item.get('status')=='complete':
            try:details=inspect_record(item,run_id)
            except (ValueError,KeyError,TypeError,OSError,ArithmeticError) as e:issues.append(str(e));details={}
            except Exception as e:issues.append(type(e).__name__+': '+str(e));details={}
        else:
            details={};issues.append('Research '+str(item.get('status','missing') if item else 'missing'))
        blockers=item.get('blockers',[]) if item else []
        confirmed_external=[]
        for b in blockers:
            if b.get('kind')=='external' and b.get('reason') and b.get('attempts'):
                try:
                    attempts=[structured(a) for a in b['attempts']]
                    allowed={'access_denied','source_not_disclosed','upstream_unavailable'}
                    if all(a.get('obstacle_type') in allowed and a.get('attempted_at') and a.get('detail') and a.get('source') for a in attempts):confirmed_external.append(b['reason'])
                except (ValueError,KeyError,TypeError,OSError):pass
        if not issues:
            outcomes.append({'ticker':ticker,'status':'COMPLETE',**details});continue
        status='BLOCKED' if confirmed_external and item and item.get('status')=='blocked' and item.get('input_hash')==input_hash and job and job['state'] in ('completed','failed') and all(b.get('kind')=='external' for b in blockers) else 'IN_PROGRESS'
        outcomes.append({'ticker':ticker,'status':status,'issues':issues,'external_blockers':confirmed_external})
        actions.append({'ticker':ticker,'action':'resolve_external_dependency' if status=='BLOCKED' else 'continue_or_retry_pipeline',
                        'queue_attempt_state':job['state'] if job else 'missing','reason':issues,
                        'completed_attempt_is_not_completed_research':bool(job and job['state']=='completed')})
    states={o['status'] for o in outcomes}
    status='COMPLETE' if states=={'COMPLETE'} else 'IN_PROGRESS' if 'IN_PROGRESS' in states else 'BLOCKED'
    return {'run_id':run_id,'status':status,'expected':len(expected),'complete':sum(o['status']=='COMPLETE' for o in outcomes),
            'items':outcomes,'continuation_actions':actions,'semantic_truth_verified':False,
            'meaning':'Artifact/schema/arithmetic/reference checks only; inspect evidence quality and reasoning independently.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    result=audit(json.loads(Path(a.manifest).read_text()));Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'expected':result['expected'],'complete':result['complete']}))
if __name__=='__main__':main()
