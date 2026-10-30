#!/usr/bin/env python3
"""Bind performed recovery work to new full research publication; no new executor.

Validates declared question coverage, calculation and independent review. It does
not discover omitted questions, authenticate sources or promise investment alpha.
"""
import hashlib
import re
from html import unescape
from pathlib import Path
import research_resolution as method
from rationale_guard import publication_times

VERSION = method.VERSION
EFFECTIVE_AT = '2026-10-24T10:28:00Z'
SCOPES = {'company_full', 'fund_full', 'crypto_full'}


def fail(message):
    raise ValueError('Research resolution: ' + message)


def applies(record, observed_publication_times=()):
    if record.get('scope') not in SCOPES: return False
    if 'research_resolution_evidence' in record or 'active_resolution' in record.get('policy_versions', {}): return True
    dates = list(observed_publication_times) + publication_times(record.get('persistence', {}))
    if record.get('subject', {}).get('cutoff'): dates.append(record['subject']['cutoff'])
    return any(method.timestamp(t) >= method.timestamp(EFFECTIVE_AT) for t in dates)


def validate(record, *, observed_publication_times=(), decision_action=None):
    if not applies(record, observed_publication_times):
        return {'status': 'historical_or_narrow_exempt'}
    block = record.get('research_resolution_evidence')
    if not isinstance(block, dict) or block.get('version') != VERSION: fail('versioned resolution evidence required')
    if block.get('status') == 'pending':
        if record.get('status') == 'complete': fail('pending recovery work cannot certify completed research')
        return {'status': 'pending'}
    if block.get('status') != 'reviewed': fail('actual reviewed resolution evidence required')
    arts = {a['id']: a for a in record.get('artifacts', [])}
    if len(arts) != len(record.get('artifacts', [])): fail('duplicate artifacts')
    def raw(aid):
        if aid not in arts: fail('unregistered artifact ' + str(aid))
        a=arts[aid]; p=Path(a.get('path', ''))
        if not p.is_absolute() or not p.is_file(): fail('absolute existing artifact required')
        data=p.read_bytes()
        if hashlib.sha256(data).hexdigest()!=a.get('sha256'): fail('artifact changed after review')
        return data
    def load(aid): return method.decode(raw(aid))
    ledger_id=block.get('ledger_artifact_id'); output_id=block.get('output_artifact_id'); review_id=block.get('review_artifact_id')
    ledger=load(ledger_id); output=load(output_id); review=load(review_id)
    subject=record['subject']; author=record['audit']['author_id']
    if ledger.get('subject')!=subject['ticker'] or ledger.get('as_of')!=subject['cutoff'] or ledger.get('author_id')!=author:
        fail('ledger subject/cutoff/author must bind current research')
    if decision_action is not None and ledger.get('proposed_action')!=decision_action: fail('published action differs from ledger')
    expected=block.get('expected_question_ids')
    if not isinstance(expected,list) or not expected or len(set(expected))!=len(expected): fail('frozen nonempty expected question inventory required')
    if ledger.get('expected_question_ids')!=expected: fail('frozen question scope differs')
    if method.calculate(ledger,base_dir=Path(arts[ledger_id]['path']).parent)!=output: fail('resolution output not reproducible')
    required={ledger_id,output_id}
    report_id=record.get('result',{}).get('report_artifact_id')
    report=raw(report_id).decode('utf-8'); required.add(report_id)
    communication=block.get('communication',{})
    route=communication.get('route')
    if route=='direct': method.text(communication.get('reason'))
    elif route=='rewrite':
        import financial_report_checks as editor
        inp_id=communication.get('input_artifact_id'); out_id=communication.get('output_artifact_id')
        packet=load(inp_id); checked=editor.check(packet)
        if load(out_id)!=checked or checked['status']!='parity_pass_semantic_review_required': fail('editorial parity output absent, stale or rejected')
        plain=unescape(re.sub(r'<[^>]+>',' ',report))
        plain=' '.join(plain.split())
        for claim in packet['after']['claims']:
            if ' '.join(claim['text'].split()) not in plain: fail('reviewed rewritten claim absent from published report')
        required.update((inp_id,out_id))
    else: fail('direct or rewrite communication route required')
    for a in ledger['artifacts']:
        aid=a['id']; raw(aid); required.add(aid)
        if a['sha256']!=arts[aid]['sha256'] or Path(a['path']).resolve()!=Path(arts[aid]['path']).resolve(): fail('nested evidence differs from registered artifact')
    reviewer=review.get('reviewer_id','')
    if not reviewer or reviewer.split('/')[-1]==author.split('/')[-1]: fail('independent reviewer required')
    if reviewer!=record['audit']['independent_review']['reviewer_id']: fail('reviewer differs from research review')
    if (review.get('status')!='approved_resolution_scope' or review.get('subject')!=subject['ticker']
            or review.get('cutoff')!=subject['cutoff'] or review.get('proposed_action')!=ledger['proposed_action']
            or review.get('reviewed_question_ids')!=expected): fail('independent review scope/identity mismatch')
    for field in ('inventory_completeness_finding','attempt_sufficiency_finding','decision_bounds_finding','communication_finding'):
        method.text(review.get(field))
    for aid in required:
        if review.get('artifact_hashes',{}).get(aid)!=arts[aid]['sha256']: fail('review does not pin all actual evidence')
    if method.timestamp(review.get('reviewed_at'))<method.timestamp(ledger['as_of']): fail('review predates research cutoff')
    if record.get('status')=='complete' and any(q['status']=='open' for q in ledger['questions']): fail('open investigation cannot certify completed research; perform work or evidence a scoped blocker')
    action=ledger['proposed_action']
    if action not in {'buy','add','hold','wait','no_buy','reduce','exit'}: fail('unsupported published action')
    for q in ledger['questions']:
        if action not in q['decision_matrix']['actions']: fail('published action absent from decision matrix')
        if q['status'] in ('assumption_bound','research_wait') and action in q['required_for_actions']:
            metrics=method.decision_metrics(q['decision_matrix'])
            if action not in metrics['robust_actions']: fail('published action not supported by declared robust bounds')
    blockers=[q['id'] for q in ledger['questions'] if q['status'] in ('open','external_blocker') and action in q['required_for_actions']]
    if blockers: fail('action-critical recovery remains incomplete: '+', '.join(blockers))
    return {'status':'validated','questions':len(expected),'action':action,
            'semantic_truth_verified':False,'calibrated_alpha_verified':False}
