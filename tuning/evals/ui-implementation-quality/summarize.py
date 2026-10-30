"""Validate captured evidence and report implementation, routing and cost separately."""
import hashlib
import json
from pathlib import Path

from grade import ROOT, RUN, SOURCE, digest, immutable_errors, read, require


def comparison(cases, general, routed, invalid):
    ids = {c['id'] for c in cases}
    require(set(general) == set(routed) == ids, 'Incomplete comparison')
    require(set(invalid) <= ids, 'Unknown invalid measurement')
    valid = sorted(ids - set(invalid))
    regressions = [cid for cid in valid if general[cid]['passed'] and not routed[cid]['passed']]
    gains = [cid for cid in valid if not general[cid]['passed'] and routed[cid]['passed']]
    critical = [c['id'] for c in cases if c['severity'] == 'critical' and c['id'] in valid and not routed[c['id']]['passed']]
    return {'valid_case_ids': valid, 'invalid_measurements': invalid,
            'general_valid_passed': sum(general[c]['passed'] for c in valid),
            'routed_valid_passed': sum(routed[c]['passed'] for c in valid),
            'valid_case_gains': gains, 'valid_case_regressions': regressions,
            'critical_routed_failures': critical,
            'implementation_quality_advantage': 'directional_on_this_task' if gains and not regressions and not critical else 'inconclusive',
            'generalization': 'not established: one paired task, one worker per condition'}


def main():
    import tiktoken
    enc = tiktoken.get_encoding('o200k_base')
    manifest = read(RUN / 'manifest.json')
    for relative, expected in manifest['source_sha256'].items():
        require(digest(ROOT / relative) == expected, 'Frozen source changed: ' + relative)
    for relative, expected in read(RUN / 'grader-freeze.json')['sha256'].items():
        require(digest(ROOT / relative) == expected, 'Frozen grader/control changed: ' + relative)
    gold = read(SOURCE / 'gold.json')
    audit = read(RUN / 'audit/q04-validity-diagnostic-v1/summary.json')
    require(audit['preservation']['all_source_hashes_unchanged'], 'Diagnostic modified implementation/source')
    require(audit['stats']['expected'] == 12 and audit['stats']['unexpected'] == audit['stats']['skipped'] == 0, 'Diagnostic incomplete')
    for relative, expected in audit['diagnostic_source_sha256'].items():
        require(digest(ROOT / relative) == expected, 'Diagnostic source changed')
    rows = audit['rows']
    require(len(rows) == 12 and len({(r['subject'], r['case']) for r in rows}) == 12, 'Missing/duplicate diagnostic')
    for patch in ('patch-X', 'patch-Y'):
        group = [r for r in rows if r['subject'] == patch]
        require(len(group) == 3 and all(r['save_succeeded'] and r['commits'] == r['writes'] == 1 and r['harbor_unchanged'] and not r['settled_alerts'] for r in group), 'Counterfactual evidence mismatch')
    arms = {}
    for job in manifest['jobs']:
        worker = RUN / job['id']
        require(not immutable_errors(worker, job['protected_sha256']), 'Worker changed protected files')
        summary = read(RUN / 'evaluations' / job['id'] / 'summary.json')
        require(summary['status'] in ('passed', 'failed_checks'), 'Incomplete/infrastructure-invalid implementation evidence')
        require(summary['typecheck']['exit_code'] == summary['build']['exit_code'] == 0, 'Invalid implementation')
        for relative, expected in summary['implementation_sha256'].items():
            require(digest(worker / relative) == expected, 'Implementation changed after grading')
        inspection = read(worker / 'inspection.json')
        require(isinstance(inspection['issues'], list) and bool(inspection['issues']), 'Missing initial discovery evidence')
        for issue in inspection['issues']:
            require(all(isinstance(issue.get(k), str) and issue[k].strip() for k in ('description', 'location', 'mechanism', 'planned_check')), 'Incomplete discovery claim')
        read(worker / 'result.json')
        resources = []
        routing = None
        if job['arm'] == 'routed':
            route = read(worker / 'route.json')
            selected = route['skills']
            require(len(selected) == len(set(selected)), 'Duplicate selected package')
            required = {'async-state-reliability', 'impeccable', 'vercel-react-best-practices', 'playwright-cli'}
            missing, extra = sorted(required - set(selected)), sorted(set(selected) - required - {'ui-ux-pro-max'})
            routing = {'selected': selected, 'missing': missing, 'unnecessary': extra, 'passed': not missing and not extra}
            declared = read(worker / 'resources.json')['paths']
            resources = sorted({p for p in declared if p.startswith('skills/')})
            for relative in resources:
                path = worker / relative
                require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(worker.resolve()), 'Invalid declared resource')
            require(all('skills/' + name + '/SKILL.md' in resources for name in selected), 'Selected skill body not declared')
        resource_cost = sum(len(enc.encode((worker / p).read_text())) for p in resources)
        all_entries = set(str(p.relative_to(worker)) for p in (worker / 'skills').glob('*/SKILL.md'))
        extra_refs = set(resources) - all_entries
        all_with_refs = job['packet_tokens_proxy'] + sum(len(enc.encode((worker / p).read_text())) for p in all_entries | extra_refs) if all_entries else None
        arms[job['arm']] = {'worker': job['id'], 'raw_passed': summary['passed'], 'total': summary['total'],
                            'cases': summary['cases'], 'critical_failures': summary['critical_failures'],
                            'typecheck': 'passed', 'build': 'passed', 'immutable_contract': 'preserved',
                            'initial_inspection': inspection, 'routing': routing,
                            'packet_tokens_proxy': job['packet_tokens_proxy'],
                            'declared_skill_resource_tokens_proxy': resource_cost,
                            'declared_instruction_union_tokens_proxy': job['packet_tokens_proxy'] + resource_cost,
                            'all_seven_with_same_references_tokens_proxy': all_with_refs,
                            'declared_resources': resources,
                            'result_artifact': str((worker / 'result.json').relative_to(ROOT)),
                            'implementation_source_tokens_proxy': sum(len(enc.encode(p.read_text())) for p in (worker / 'app/src').rglob('*') if p.is_file())}
    require(set(arms) == {'general', 'routed'}, 'Missing comparison arm')
    invalid = {'Q04': {'reason': 'Enabled-pristine-Save assertion rejects a legitimate no-change policy; edited saves and late-error counterfactuals succeed',
                      'diagnostic': 'q04-validity-diagnostic-v1', 'raw_result_preserved': True}}
    comparison_result = comparison(gold['cases'], arms['general']['cases'], arms['routed']['cases'], invalid)
    result = {'experiment': manifest['experiment'], 'arms': arms, 'comparison': comparison_result,
              'author_controls': {'seed_raw_passed': 1, 'corrected_reference_raw_passed': 12, 'total': 12},
              'discovery_review': 'Both initial inspections identify concrete mechanisms across layout, races/writes/drafts, payload/errors, preview boundary and expensive rendering; raw issue counts differ in grouping and are not comparable defect totals',
              'provider_usage': None,
              'cost_scope': 'Known serialized packet plus declared skill/reference text; not billing, reasoning, tool outputs or an independently audited load trace',
              'runtime_acceptance_scope': 'Isolated synthetic implementation evaluation; does not accept UI SessionStart activation or scheduled production behavior',
              'verdict': 'inconclusive_incremental_skill_effectiveness; routed implementation works on scoped checks and route is correct'}
    (SOURCE / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'raw_scores': {a: value['raw_passed'] for a, value in arms.items()},
                      'valid_comparison': comparison_result, 'routing': arms['routed']['routing'],
                      'context_proxy': {a: value['declared_instruction_union_tokens_proxy'] for a, value in arms.items()},
                      'verdict': result['verdict']}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
