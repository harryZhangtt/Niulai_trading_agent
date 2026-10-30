#!/usr/bin/env python3
"""Bind installed methods, a sourced rationale visual and cycle/forecast evidence.

Offline and read-only except explicit atomic output files. No agents, trading,
network calls, automatic model forecasts or claim of semantic truth.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from html import escape
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap

try:
    import cycle_checks as cycle_math
except ImportError:
    cycle_math = None

try:
    import adoption_checks as adoption_math
except ImportError:
    adoption_math = None

ROOT = Path(__file__).resolve().parents[3]
VERSION = '2026-10-23-rationale-cycle-1'
SCHEMA_VERSION = '2026-10-23-research-run-3'
EFFECTIVE_AT = '2026-10-23T16:03:21Z'
FIRST_PRINCIPLES_VERSION = '2026-10-23-first-principles-1'
FIRST_PRINCIPLES_AT = '2026-10-23T23:23:40Z'
FIRST_PRINCIPLES_QUESTIONS = {'customer_job', 'alternatives_and_economics', 'reference_class',
                            'adoption_to_capture', 'falsification', 'cycle_mechanism'}
SCOPES = {'company_full', 'fund_full', 'crypto_full'}
FAMILIES = {'ai_berkshire', 'anthropic_financial_services'}
NODE_TITLES = {
    'business': 'What it does', 'moat': 'Moat and fragility',
    'capture': 'Revenue to owner value', 'double_beat': 'Revenue and profit beat test',
    'expectations': 'What the price assumes', 'cycle': 'Lifecycle and industry cycle',
    'catalyst': 'Timing and realization', 'decision': 'Action, entry and downside',
}
CRITIC_CHECKS = {'peak_earnings', 'supply_response', 'priced_in', 'counterevidence', 'opportunity_cost'}
ECONOMIC_QUESTIONS = {'scarcity_and_supply_response', 'demand_quality', 'durability_vs_mean_reversion',
                      'funding_and_survival', 'expectations_and_returns', 'disconfirming_path'}
MANIFESTS = ['references/ai-berkshire/references/upstream-manifest.json',
             'references/upstream-manifest.json', 'references/modeling-upstream-manifest.json']
REPORT_CSS = 'body{margin:0;background:#eef3f6;color:#18374a;font:16px/1.6 system-ui,sans-serif}main{max-width:1100px;margin:24px auto;padding:28px;background:white}svg{display:block;width:100%;height:auto}table{border-collapse:collapse;width:100%}th,td{padding:10px;border-bottom:1px solid #d4e0e7;text-align:left}h1,h2{line-height:1.25}a{color:#18568b}'


class RationaleError(ValueError):
    pass


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise RationaleError(label + ' must be nonempty text')
    return value


def instant(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError) as exc:
        raise RationaleError('Timezone-aware timestamp required') from exc


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RationaleError('Finite numeric value required')
    return value


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'


def atomic_write(path, content):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as out:
            temporary = Path(out.name)
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def git(root, *args):
    try:
        result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RationaleError('Installed dependency git read failed: ' + type(exc).__name__) from exc
    if result.returncode:
        raise RationaleError('Installed dependency git history unavailable: ' + result.stderr.decode(errors='replace').strip())
    return result.stdout


def safe_relative(path):
    text(path, 'Dependency path')
    p = Path(path)
    if p.is_absolute() or '..' in p.parts or '\\' in path:
        raise RationaleError('Unsafe dependency path')
    return p.as_posix()


def required_paths(scope):
    if scope not in SCOPES:
        raise RationaleError('Full applicable scope required')
    paths = ['SKILL.md', 'references/research-harness.md',
             'references/rationale-cycle-policy.md', 'references/cycle-method-integration.md',
             'references/cycle-capital-allocation.md', 'references/opportunity-cost-policy.md',
             'references/first-principles-adoption.md', 'references/cycle-research-map.md',
             'references/niulai-workflow/scripts/cycle_checks.py',
             'references/niulai-workflow/scripts/adoption_checks.py',
             'references/niulai-workflow/scripts/cycle_vintage_checks.py',
             'references/niulai-workflow/scripts/rationale_guard.py',
             'references/ai-berkshire/WORKFLOW.md',
             'references/ai-berkshire/references/growth-aware-policy.md',
             'references/upstream/sector-overview/WORKFLOW.md',
             'references/upstream/competitive-analysis/WORKFLOW.md', *MANIFESTS]
    if scope == 'company_full':
        paths += ['references/trend-to-value-policy.md', 'references/modeling-adaptation.md',
                  'references/modeling-upstream/dcf-model/WORKFLOW.md',
                  'references/modeling-upstream/3-statement-model/WORKFLOW.md']
    elif scope == 'fund_full':
        paths += ['references/ai-berkshire/references/leveraged-funds-policy.md']
    else:
        paths += ['references/crypto-research-policy.md']
    return sorted(paths)


def tree_blob(root, revision, path):
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise RationaleError('Full installed git revision required')
    top = Path(git(root, 'rev-parse', '--show-toplevel').decode().strip())
    relative = (root.resolve().relative_to(top) / safe_relative(path)).as_posix()
    return git(root, 'show', revision + ':' + relative)


def manifest_pins_and_files(read):
    ai = json.loads(read(MANIFESTS[0]))
    research = json.loads(read(MANIFESTS[1]))
    modeling = json.loads(read(MANIFESTS[2]))
    if ai.get('source_url') != 'https://github.com/xbtlin/ai-berkshire':
        raise RationaleError('AI Berkshire source identity mismatch')
    if any(m.get('repository') != 'https://github.com/anthropics/financial-services' for m in [research, modeling]):
        raise RationaleError('Anthropic source identity mismatch')
    if research['revision'] != modeling['revision']:
        raise RationaleError('Anthropic workflow/model pins differ')
    files = {}
    for name, row in ai['files'].items():
        files['references/ai-berkshire/references/upstream/' + safe_relative(name)] = row['local_sha256']
    for manifest in [research, modeling]:
        for row in manifest['files']:
            files[safe_relative(row['path'])] = row['sha256']
    for path, expected in files.items():
        if digest(read(path)) != expected:
            raise RationaleError('Upstream dependency manifest mismatch: ' + path)
    pins = {'ai_berkshire': ai['upstream_commit'], 'anthropic_financial_services': research['revision']}
    return pins, files


def dependency_lock(scope, root=ROOT):
    root = Path(root).resolve()
    revision = git(root, 'rev-parse', 'HEAD').decode().strip()
    # Only this skill must be clean; unrelated personal skills do not block it.
    if git(root, 'status', '--porcelain', '--', str(root)).strip():
        raise RationaleError('Commit the installed skill before snapshotting dependencies')
    def read(path):
        raw = (root / safe_relative(path)).read_bytes()
        if raw != tree_blob(root, revision, path):
            raise RationaleError('Installed dependency differs from committed file: ' + path)
        return raw
    pins, manifest_files = manifest_pins_and_files(read)
    paths = sorted(set(required_paths(scope)) | set(manifest_files))
    return {'version': VERSION, 'scope': scope, 'skill_revision': revision,
            'upstream_pins': pins, 'files': {p: digest(read(p)) for p in paths},
            'meaning': 'Committed installed files; application and independent evidence are checked separately.'}


def validate_lock(lock, scope, revision, root=ROOT):
    if lock.get('version') != VERSION or lock.get('scope') != scope or lock.get('skill_revision') != revision:
        raise RationaleError('Dependency lock scope/version/revision mismatch')
    def read(path):
        return tree_blob(Path(root), revision, path)
    pins, manifest_files = manifest_pins_and_files(read)
    expected_paths = set(required_paths(scope)) | set(manifest_files)
    if lock.get('upstream_pins') != pins or set(lock.get('files', {})) != expected_paths:
        raise RationaleError('Dependency lock pins/file scope mismatch')
    for path, expected in lock['files'].items():
        if digest(read(safe_relative(path))) != expected:
            raise RationaleError('Dependency citation hash mismatch: ' + path)


def artifacts(record):
    rows = record.get('artifacts', [])
    result = {a['id']: a for a in rows}
    if len(result) != len(rows):
        raise RationaleError('Duplicate artifact IDs')
    return result


def raw_artifact(arts, aid):
    if aid not in arts:
        raise RationaleError('Unresolved rationale artifact: ' + str(aid))
    row = arts[aid]
    p = Path(row['path'])
    if not p.is_absolute() or not p.is_file():
        raise RationaleError('Rationale artifact missing or nonabsolute')
    raw = p.read_bytes()
    if not raw or digest(raw) != row.get('sha256'):
        raise RationaleError('Stale or empty rationale artifact: ' + aid)
    return raw


def json_artifact(arts, aid):
    return json.loads(raw_artifact(arts, aid))


def pointer(value, path):
    if not isinstance(path, str) or not path.startswith('/'):
        raise RationaleError('Nonempty JSON pointer required')
    try:
        for part in path[1:].split('/'):
            key = part.replace('~1', '/').replace('~0', '~')
            value = value[int(key)] if isinstance(value, list) else value[key]
        return value
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise RationaleError('Unresolved model JSON pointer') from exc


def bound_value(binding, arts):
    text(binding.get('units'), 'Model binding units')
    text(binding.get('period'), 'Model binding period')
    output = json_artifact(arts, binding['artifact_id'])
    if pointer(output, binding['units_pointer']) != binding['units'] or pointer(output, binding['period_pointer']) != binding['period']:
        raise RationaleError('Model value units/period metadata mismatch')
    return pointer(output, binding['pointer'])


def evidence_link(value, record, arts):
    text(value.get('finding'), 'Evidence finding')
    claim_ids = value.get('claim_ids')
    model_ids = value.get('model_artifact_ids')
    known_claims = {c['id'] for c in record.get('claims', [])}
    if not isinstance(claim_ids, list) or not claim_ids or any(c not in known_claims for c in claim_ids):
        raise RationaleError('Rationale needs resolved claim IDs')
    if not isinstance(model_ids, list) or not model_ids:
        raise RationaleError('Rationale needs actual model artifact references')
    for aid in model_ids:
        raw_artifact(arts, aid)


def check_forecasts(card, arts):
    forecasts = card.get('forecasts', [])
    if not isinstance(forecasts, list) or not forecasts:
        raise RationaleError('At least one material resolvable forecast required')
    issued = instant(card['issued_at'])
    ids = set()
    for f in forecasts:
        fid = text(f.get('id'), 'Forecast ID')
        if fid in ids:
            raise RationaleError('Duplicate forecast ID')
        ids.add(fid)
        for name in ['target', 'units', 'period', 'resolution_rule', 'resolution_source']:
            text(f.get(name), 'Forecast ' + name)
        if instant(f['resolve_after']) <= issued:
            raise RationaleError('Forecast outcome window must follow issuance')
        prediction = bound_value(f['model_binding'], arts)
        if 'prediction' not in f or f['prediction'] != prediction:
            raise RationaleError('Frozen prediction differs from actual model binding')
        if isinstance(f['prediction'], bool) or (isinstance(f['prediction'], list) and any(isinstance(v, bool) for v in f['prediction'])):
            raise RationaleError('Boolean is not a numeric forecast')
        if f['model_binding']['units'] != f['units'] or f['model_binding']['period'] != f['period']:
            raise RationaleError('Forecast metric definition/binding mismatch')
        if f.get('kind') == 'interval':
            if not isinstance(prediction, list) or len(prediction) != 2 or number(prediction[0]) > number(prediction[1]):
                raise RationaleError('Ordered interval bounds required')
            if not 0 < number(f.get('coverage')) < 1:
                raise RationaleError('Predictive interval coverage required')
        else:
            number(prediction)
            if f.get('kind') not in {'mean', 'median', 'binary'}:
                raise RationaleError('Supported forecast functional required')
            if f['kind'] == 'binary' and not 0 <= prediction <= 1:
                raise RationaleError('Binary probability outside [0,1]')


def verify_cycle_arithmetic(record, card, arts, lock):
    """Recompute declared economics; this does not authenticate source inputs."""
    numeric = card['cycle_challenge'].get('numerical_check', {})
    if not isinstance(numeric, dict):
        raise RationaleError('Cycle arithmetic packet required')
    if cycle_math is None:
        raise RationaleError('Installed cycle calculator unavailable; restore the locked dependency')
    try:
        packet = cycle_math.decode_packet(raw_artifact(arts, numeric['input_artifact_id']))
        actual = json_artifact(arts, numeric['output_artifact_id'])
        cases = numeric['case_calculation_ids']
        display = numeric['display_fcff_bindings']
    except KeyError as exc:
        raise RationaleError('Cycle arithmetic input/output and case bindings required') from exc
    except ValueError as exc:
        raise RationaleError('Cycle arithmetic rejected: ' + str(exc)) from exc
    if not isinstance(packet, dict):
        raise RationaleError('Cycle arithmetic packet must be an object')
    if packet.get('subject') != card['ticker'] or instant(packet.get('as_of')) != instant(card['as_of']):
        raise RationaleError('Cycle arithmetic subject/cutoff mismatch')
    method_path = 'references/niulai-workflow/scripts/cycle_checks.py'
    if digest(Path(cycle_math.__file__).read_bytes()) != lock['files'].get(method_path):
        raise RationaleError('Restore the pinned calculator before historical cycle revalidation')
    try:
        expected = cycle_math.calculate(packet)
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        raise RationaleError('Cycle arithmetic rejected: ' + str(exc)) from exc
    if actual != expected:
        raise RationaleError('Cycle arithmetic output differs from deterministic recomputation')
    if not isinstance(cases, dict) or set(cases) != {'peak', 'normalized', 'adverse'} or any(not isinstance(cid, str) for cid in cases.values()) or len(set(cases.values())) != 3:
        raise RationaleError('Three distinct cycle arithmetic case bindings required')
    if not isinstance(display, dict) or set(display) != set(cases):
        raise RationaleError('All three displayed FCFF cases require exact calculator bindings')
    currencies = set()
    shown = {}
    for label, cid in cases.items():
        result = actual['results'].get(cid, {})
        if result.get('kind') != 'state_bridge' or result.get('state') != label or result.get('cash_flow_measure') != 'FCFF':
            raise RationaleError('Cycle case must bind its matching actual FCFF bridge')
        currencies.add(result.get('currency_unit'))
        period = result['period']['start'] + '/' + result['period']['end']
        binding = display[label]
        if not isinstance(binding, dict) or binding.get('artifact_id') != numeric['output_artifact_id'] or binding.get('pointer') != '/results/' + cid + '/totals/fcff' or binding.get('units') != result['currency_unit'] or binding.get('period') != period:
            raise RationaleError('Displayed cycle FCFF differs from exact calculator scope/units/period binding')
        shown[label] = {'value': pointer(actual, binding['pointer']), 'units': result['currency_unit'], 'period': period}
    if len(currencies) != 1:
        raise RationaleError('Cycle arithmetic cases use incompatible currencies')
    return {'artifact_ids': {numeric['input_artifact_id'], numeric['output_artifact_id']}, 'display': shown}


def inspect_card(record, root=ROOT):
    block = record.get('rationale_evidence')
    if not isinstance(block, dict) or block.get('version') != VERSION:
        raise RationaleError('rationale_evidence missing or wrong version')
    arts = artifacts(record)
    lock = json_artifact(arts, block['dependency_lock_artifact_id'])
    validate_lock(lock, record['scope'], record['skill_revision'], root)
    card = json_artifact(arts, block['card_artifact_id'])
    if card.get('version') != VERSION or card.get('ticker') != record['subject']['ticker'] or card.get('scope') != record['scope']:
        raise RationaleError('Rationale card identity mismatch')
    if instant(card['as_of']) != instant(record['subject']['cutoff']) or instant(card['issued_at']) < instant(card['as_of']):
        raise RationaleError('Rationale information vintage mismatch')
    for name in ['cohort_id', 'thesis_family', 'limitations']:
        text(card.get(name), name)
    if card.get('origin') not in {'prospective', 'retrospective_extraction'}:
        raise RationaleError('Forecast record origin required')
    if card.get('action') not in {'buy', 'add', 'hold', 'wait', 'no_buy', 'reduce', 'exit'}:
        raise RationaleError('Explicit rationale action required')
    apps = card.get('methodology_applications', {})
    if set(apps) != FAMILIES:
        raise RationaleError('Both AI Berkshire and Anthropic applications required')
    for family, application in apps.items():
        evidence_link(application, record, arts)
        paths = application.get('workflow_paths', [])
        if family == 'ai_berkshire':
            correct = 'references/ai-berkshire/WORKFLOW.md' in paths and all(p.startswith('references/ai-berkshire/') for p in paths)
        else:
            correct = bool(paths) and all(p.startswith(('references/upstream/', 'references/modeling-upstream/')) and p.endswith('WORKFLOW.md') for p in paths)
        if not paths or any(p not in lock['files'] for p in paths) or not correct:
            raise RationaleError('Methodology application cites wrong dependency family')
    if set(card.get('nodes', {})) != set(NODE_TITLES):
        raise RationaleError('All eight rationale topics required')
    for node in card['nodes'].values():
        evidence_link(node, record, arts)
        if node.get('status') not in {'supported', 'mixed', 'not_established'}:
            raise RationaleError('Evidence status required; no forced bullish finding')
    beat = card.get('beat_test', {})
    evidence_link(beat, record, arts)
    for field in ['period', 'revenue_metric', 'profit_metric']:
        text(beat.get(field), 'Beat test ' + field)
    if beat.get('basis') == 'unavailable':
        if card['nodes']['double_beat']['status'] != 'not_established':
            raise RationaleError('A double beat cannot be established without an expectations basis')
    elif beat.get('basis') in {'dated_consensus', 'price_implied'}:
        for metric in ['revenue', 'profit']:
            bindings = [beat[metric + '_forecast'], beat[metric + '_expectation']]
            for binding in bindings: number(bound_value(binding, arts))
            if len({(b['units'], b['period']) for b in bindings}) != 1 or bindings[0]['period'] != beat['period']:
                raise RationaleError('Beat forecast/expectation units or target period differ')
    else:
        raise RationaleError('Dated, price-implied or explicitly unavailable beat basis required')
    metrics = card.get('metrics', {})
    values = {name: number(bound_value(binding, arts)) for name, binding in metrics.items()}
    if 'horizon_months' not in values or values['horizon_months'] <= 0:
        raise RationaleError('Positive bound valuation horizon required')
    if metrics['horizon_months']['units'] != 'months':
        raise RationaleError('horizon_months must use months, not years or another unit')
    quote_unit = text(card.get('quote_unit'), 'Quote unit')
    entry_period = text(card.get('entry_period'), 'Entry valuation period')
    for name in ['entry_low', 'entry_high', 'tested_entry_low', 'tested_entry_high']:
        if name in metrics and (metrics[name]['units'] != quote_unit or metrics[name]['period'] != entry_period):
            raise RationaleError('Entry endpoints have incompatible units/periods')
    for name in ['catalyst_low_months', 'catalyst_high_months']:
        if name in metrics and metrics[name]['units'] != 'months':
            raise RationaleError('Catalyst timing must use months')
    for pair in [('value_effect_low', 'value_effect_high'), ('catalyst_low_months', 'catalyst_high_months')]:
        if all(name in metrics for name in pair) and len({(metrics[name]['units'], metrics[name]['period']) for name in pair}) != 1:
            raise RationaleError('Catalyst bounds have incompatible definitions')
    for node in card['nodes'].values():
        finding = node['finding']
        tokens = re.findall(r'\{\{([a-z_]+)\}\}', finding)
        if any(key not in metrics for key in tokens):
            raise RationaleError('Unresolved visual metric placeholder')
        plain = re.sub(r'\{\{[a-z_]+\}\}', '', finding)
        # Keep literal quantitative estimates out of prose; technical identifiers
        # such as HBM4/3D can be source-linked rather than model estimates.
        plain = re.sub(r'\b(?:HBM\d+[A-Za-z]*|LP?DDR\d+[A-Za-z]*|DDR\d+|\d+D|\d+nm|CXL\s*\d+(?:\.\d+)*|PCIe\s*\d+(?:\.\d+)*)\b', '', plain)
        if re.search(r'(?<![A-Za-z0-9_])(?:[$€£¥]\s*)?[+-]?(?:\d+(?:[.,]\d+)*|\.\d+)(?:[eE][+-]?\d+)?(?:\s*(?:%|bps|bp|x|×|bn|billion|million|months?|years?|[kmb]))?(?![A-Za-z0-9_])', plain, re.I):
            raise RationaleError('Visual quantities must use bound metric placeholders')
    if card.get('entry_feasibility', 'feasible') == 'none':
        if not {'tested_entry_low', 'tested_entry_high'} <= set(metrics) or not 0 <= values['tested_entry_low'] <= values['tested_entry_high']:
            raise RationaleError('No-feasible-entry result needs a tested numeric domain')
        text(card.get('no_feasible_entry_reason'), 'No-feasible-entry reason')
        if card['action'] in {'buy', 'add'}:
            raise RationaleError('Cannot recommend purchase with no feasible entry')
    elif card.get('entry_feasibility', 'feasible') == 'feasible':
        if not {'entry_low', 'entry_high'} <= set(metrics) or not 0 <= values['entry_low'] <= values['entry_high']:
            raise RationaleError('Valid entry range bindings required')
    else:
        raise RationaleError('Unknown entry feasibility')
    if not {'catalyst_low_months', 'catalyst_high_months', 'value_effect_low', 'value_effect_high'} <= set(metrics):
        text(card.get('catalyst_limitations'), 'Unidentified catalyst timing/magnitude limitation')
    else:
        if not 0 <= values['catalyst_low_months'] <= values['catalyst_high_months'] or values['value_effect_low'] > values['value_effect_high']:
            raise RationaleError('Invalid catalyst timing/magnitude bounds')
    cycle = card.get('cycle_challenge', {})
    for clock in ['adoption_stage', 'industry_state', 'expectations_state']:
        text(cycle.get(clock), clock)
    economic_questions = cycle.get('economic_questions', {})
    if set(economic_questions) != ECONOMIC_QUESTIONS:
        raise RationaleError('Six evidence-linked economic cycle questions required')
    for answer in economic_questions.values():
        evidence_link(answer, record, arts)
    indicators = cycle.get('indicators', [])
    if len(indicators) < 3 or len({i.get('family') for i in indicators}) < 3:
        raise RationaleError('Three distinct indicator families required')
    for i in indicators:
        evidence_link(i, record, arts)
        text(i.get('units'), 'Indicator units')
        if instant(i['available_at']) > instant(card['as_of']):
            raise RationaleError('Cycle indicator uses future information')
    hypotheses = cycle.get('hypotheses', [])
    if len(hypotheses) < 2:
        raise RationaleError('Competing cycle hypotheses required')
    for h in hypotheses:
        evidence_link(h, record, arts)
        text(h.get('next_observation'), 'Discriminating observation')
        text(h.get('falsifier'), 'Hypothesis falsifier')
    normalization = cycle.get('normalization', {})
    classification = record['subject'].get('economics_classification', '').lower().replace('_', ' ')
    classification = re.sub(r'\bnon[ -]?cyclical\b|\bcapital[ -]?light\b', '', classification)
    cyclical = bool(re.search(r'\bcyclical\b|\bcapital[ -]?intensive\b', classification)) or str(cycle.get('industry', '')).casefold() == 'memory'
    if normalization.get('status') == 'applied':
        if set(normalization.get('cases', {})) != {'peak', 'normalized', 'adverse'}:
            raise RationaleError('Peak/normalized/adverse case bindings required')
        for binding in normalization['cases'].values():
            number(bound_value(binding, arts))
        definitions = {(b['units'], b['period']) for b in normalization['cases'].values()}
        if len(definitions) != 1:
            raise RationaleError('Normalized cycle cases have incompatible units/periods')
    elif normalization.get('status') == 'not_applicable' and not cyclical:
        text(normalization.get('reason'), 'Normalization exception reason')
    else:
        raise RationaleError('Cyclical/capital-intensive case cannot skip normalization')
    if record['scope'] == 'company_full' and cyclical:
        values['_cycle_display'] = verify_cycle_arithmetic(record, card, arts, lock)['display']
    elif cycle.get('numerical_check'):
        values['_cycle_display'] = verify_cycle_arithmetic(record, card, arts, lock)['display']
    check_forecasts(card, arts)
    return block, arts, lock, card, values


def diagram(card, values, card_hash, format='svg'):
    nodes = card['nodes']
    def finding(key):
        value = nodes[key]['finding']
        for metric, binding in card['metrics'].items():
            value = value.replace('{{' + metric + '}}', str(values[metric]) + ' ' + binding['units'])
        if key == 'cycle' and values.get('_cycle_display') and format == 'mermaid':
            value += ' | Diagnostic FCFF: ' + '; '.join(label + ' ' + v['value'] + ' ' + v['units'] + ' ' + v['period'] for label, v in values['_cycle_display'].items())
        return value
    if format == 'mermaid':
        lines = ['flowchart TD']
        for key, title in NODE_TITLES.items():
            # JSON-escaped labels plus entity encoding avoid graph syntax injection.
            label = escape(title + ': ' + finding(key), quote=True).replace('\n', ' ')
            lines.append('    ' + key + '[' + json.dumps(label, ensure_ascii=False) + ']')
        lines += ['    business --> moat', '    business --> capture', '    moat --> double_beat',
                  '    capture --> double_beat', '    double_beat --> expectations', '    cycle --> expectations',
                  '    expectations --> catalyst', '    catalyst --> decision', '    cycle --> decision',
                  '    %% rationale-card-sha256: ' + card_hash]
        return '\n'.join(lines) + '\n'
    if format != 'svg':
        raise RationaleError('Unsupported diagram format')
    if card.get('entry_feasibility', 'feasible') == 'none':
        entry_caption = 'No feasible entry in tested domain ' + str(values['tested_entry_low']) + '–' + str(values['tested_entry_high'])
    else:
        entry_caption = 'Entry ' + str(values['entry_low']) + '–' + str(values['entry_high']) + ' ' + card['metrics']['entry_low']['units']
    height = 1160 if values.get('_cycle_display') else 1040
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1040 ' + str(height) + '" role="img" data-rationale-card-sha256="' + card_hash + '">',
           '<title>' + escape(card['ticker'] + ' investment rationale') + '</title>',
           '<defs><marker id="rationale-arrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0 0L7 4L0 8" fill="none" stroke="#6a8293"/></marker></defs>',
           '<rect width="1040" height="' + str(height) + '" rx="16" fill="#f5f8fb"/>',
           '<g font-family="system-ui,sans-serif" fill="#18374a">',
           '<text x="30" y="35" font-size="23" font-weight="700">' + escape(card['ticker'] + ' | ' + card['action'].upper()) + '</text>',
           '<text x="30" y="62" font-size="13">' + escape('As of ' + card['as_of'] + ' | ' + entry_caption + ' | Horizon ' + str(values['horizon_months']) + ' months') + '</text>']
    positions = {key: (30 + (index % 2) * 510, 90 + (index // 2) * 220) for index, key in enumerate(NODE_TITLES)}
    for key, title in NODE_TITLES.items():
        x, y = positions[key]
        node = nodes[key]
        color = {'supported': '#e5f1eb', 'mixed': '#fff1d9', 'not_established': '#e9edf1'}[node['status']]
        out += [f'<rect x="{x}" y="{y}" width="470" height="190" rx="10" fill="{color}" stroke="#a3b5c1"/>',
                f'<text x="{x+16}" y="{y+28}" font-size="18" font-weight="650">{escape(title)}</text>']
        wrapped = textwrap.wrap(finding(key), width=53)
        if len(wrapped) > 6:
            wrapped = wrapped[:5] + [wrapped[5][:48] + '…']
        for index, line in enumerate(wrapped):
            out.append(f'<text x="{x+16}" y="{y+55+index*19}" font-size="14">{escape(line)}</text>')
        out.append(f'<text x="{x+16}" y="{y+174}" font-size="11">{escape(node["status"] + " | claims: " + ", ".join(node["claim_ids"])[:65])}</text>')
    for col in [0, 1]:
        x = 265 + col * 510
        for row in [0, 1, 2]:
            y = 280 + row * 220
            out.append(f'<path d="M{x} {y}V{y+22}" fill="none" stroke="#6a8293" marker-end="url(#rationale-arrow)"/>')
    for row in range(4):
        y = 185 + row * 220
        out.append(f'<path d="M500 {y}H532" fill="none" stroke="#6a8293" marker-end="url(#rationale-arrow)"/>')
    if values.get('_cycle_display'):
        out.append('<text x="30" y="985" font-size="13">Recomputed operating FCFF diagnostics; separate valuation and financing models remain required.</text>')
        for index, (label, item) in enumerate(values['_cycle_display'].items()):
            content = label + ': ' + item['value'] + ' ' + item['units'] + ' | ' + item['period']
            out.append('<text x="30" y="' + str(1010+index*25) + '" font-size="12">' + escape(content) + '</text>')
    out += ['<text x="30" y="' + str(height-50) + '" font-size="13">AI Berkshire + Anthropic methods | supporting and opposing evidence | no forced positive alpha</text>',
            '<text x="30" y="' + str(height-25) + '" font-size="11">Full source/model links and cycle forecasts are in the accompanying frozen rationale card.</text>', '</g></svg>']
    return '\n'.join(out) + '\n'


def visible_presentation(document, expected, card_hash, fmt):
    """Reject hidden/commented/offscreen-by-common-rules canonical figures.

    The controlled static presentation plus actual reviewer visual inspection
    is deliberate; this is not a general browser/CSS rendering engine.
    """
    hidden_css = r'display\s*:\s*none|visibility\s*:\s*(?:hidden|collapse)|opacity\s*:\s*0(?:\.0+)?(?:\s|;|!|})|transform\s*:\s*scale\(\s*0|@import'
    if re.search(hidden_css, re.sub(r'/\*.*?\*/', '', document, flags=re.S), re.I):
        raise RationaleError('Canonical presentation contains hidden styling')
    if fmt == 'mermaid':
        cleaned = re.sub(r'<!--.*?-->', '', document, flags=re.S)
        if re.search(r'<\s*/?\s*[A-Za-z][^>]*>|\bhidden\b|aria-hidden\s*=\s*[\"\']?true', cleaned, re.I):
            raise RationaleError('Markdown presentation may hide the rationale')
        lines = cleaned.splitlines(keepends=True)
        fenced = None
        offset = 0
        target = '```mermaid\n' + expected + '```'
        for line in lines:
            match = re.match(r'^( {0,3})(`{3,}|~{3,})(.*)$', line.rstrip('\r\n'))
            if match:
                marker, tail = match.group(2), match.group(3).strip()
                if fenced is None:
                    if marker == '```' and tail == 'mermaid' and offset <= 2500 and cleaned.startswith(target, offset):
                        return True
                    fenced = marker
                elif marker[0] == fenced[0] and len(marker) >= len(fenced) and not tail:
                    fenced = None
            offset += len(line)
        raise RationaleError('Markdown report lacks a prominent rendered rationale block')
    class FigureParser(HTMLParser):
        def __init__(self):
            super().__init__(); self.stack=[]; self.before=0; self.valid=False; self.invalid=False; self.style_text=[]; self.in_style=False
            self.offsets=[0]
            for line in document.splitlines(keepends=True): self.offsets.append(self.offsets[-1]+len(line))
        def handle_starttag(self, tag, attrs):
            attr=dict(attrs); parent=self.stack[-1][1:] if self.stack else (False, False, False)
            hidden, rationale, head=parent
            hidden = hidden or 'hidden' in attr or attr.get('aria-hidden', '').lower() == 'true' or tag in {'template','script','noscript','iframe','textarea','xmp','plaintext'} or (tag=='details' and 'open' not in attr)
            if tag in {'script','iframe'} or (tag=='link' and 'stylesheet' in attr.get('rel','').lower()): self.invalid=True
            if 'style' in attr: self.invalid=True
            if tag=='style': self.in_style=True; self.style_text=[]
            safe_ancestors=all(row[0] in {'html','body','main'} for row in self.stack)
            rationale = rationale or (tag=='section' and attr.get('data-investment-rationale')==card_hash and not hidden and safe_ancestors and self.before<=2000)
            head = head or tag in {'head','style','title'}
            line,col=self.getpos(); position=self.offsets[line-1]+col
            if tag=='svg' and rationale and not hidden and not head and any(r[0]=='body' for r in self.stack) and document.startswith(expected,position): self.valid=True
            if tag not in {'meta','link','br','hr','img','input','source','wbr'}: self.stack.append((tag,hidden,rationale,head))
        def handle_startendtag(self,tag,attrs):
            self.handle_starttag(tag,attrs); self.handle_endtag(tag)
        def handle_endtag(self,tag):
            if tag=='style':
                if ''.join(self.style_text).strip()!=REPORT_CSS: self.invalid=True
                self.in_style=False
            for i in range(len(self.stack)-1,-1,-1):
                if self.stack[i][0]==tag:
                    del self.stack[i:]; break
        def handle_data(self,data):
            if self.in_style: self.style_text.append(data)
            if self.stack:
                _,hidden,rationale,head=self.stack[-1]
                if not hidden and not rationale and not head: self.before+=len(data.strip())
    parser=FigureParser(); parser.feed(document)
    if not parser.valid or parser.invalid:
        raise RationaleError('Canonical report does not display the actual rationale diagram in a visible prominent static section')
    return True


def presentation(card, values, card_hash):
    figure = diagram(card, values, card_hash)
    return '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + escape(card['ticker'] + ' investment rationale') + '</title><style>' + REPORT_CSS + '</style></head><body><main><h1>' + escape(card['ticker'] + ' | ' + card['action'].upper()) + '</h1><section data-investment-rationale="' + card_hash + '">\n' + figure + '</section>\n<p>' + escape(card['limitations']) + '</p>\n<!-- Append the full sourced analysis here; keep the canonical static stylesheet. -->\n</main></body></html>\n'


def requires_current(record, observed_publication_times=()):
    if record.get('scope') not in SCOPES:
        return False
    if record.get('schema_version') == SCHEMA_VERSION or 'rationale' in record.get('policy_versions', {}):
        return True
    timestamps = list(observed_publication_times) + [r['confirmed_at'] for r in record.get('persistence', {}).get('receipts', [])]
    return any(instant(t) >= instant(EFFECTIVE_AT) for t in timestamps)


def verify_first_principles(record, card, arts, lock, review, observed_publication_times=()):
    """Check declared economics/provenance, never certify source or cohort truth."""
    block = card.get('first_principles')
    dates = [card['issued_at'], *publication_times(record.get('persistence', {})),
             *observed_publication_times]
    due = any(instant(d) >= instant(FIRST_PRINCIPLES_AT) for d in dates)
    if block is None and not due:
        return set()
    if not isinstance(block, dict) or block.get('version') != FIRST_PRINCIPLES_VERSION:
        raise RationaleError('First-principles customer/failure/cycle evidence required')
    questions = block.get('questions')
    if not isinstance(questions, dict) or set(questions) != FIRST_PRINCIPLES_QUESTIONS:
        raise RationaleError('Six first-principles evidence questions required')
    critic = review.get('first_principles_check')
    if not isinstance(critic, dict):
        raise RationaleError('Independent first-principles challenge required')
    needed = set()
    for item in [*questions.values(), critic]:
        if not isinstance(item, dict):
            raise RationaleError('First-principles finding must be an evidence object')
        evidence_link(item, record, arts)
        needed.update(item['model_artifact_ids'])
    if adoption_math is None:
        raise RationaleError('Pinned adoption calculator unavailable')
    method = 'references/niulai-workflow/scripts/adoption_checks.py'
    if digest(Path(adoption_math.__file__).read_bytes()) != lock['files'].get(method):
        raise RationaleError('Restore pinned adoption calculator before revalidation')
    numeric = block.get('numerical_check', {})
    try:
        input_id, output_id = numeric['input_artifact_id'], numeric['output_artifact_id']
        packet = adoption_math.decode_packet(raw_artifact(arts, input_id))
        if packet.get('subject') != card['ticker'] or instant(packet.get('as_of')) != instant(card['as_of']):
            raise RationaleError('Adoption packet subject/cutoff mismatch')
        expected = adoption_math.calculate(packet)
        if json_artifact(arts, output_id) != expected:
            raise RationaleError('Adoption arithmetic differs from deterministic recomputation')
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise RationaleError('First-principles calculation rejected: ' + str(exc)) from exc
    needed.update({input_id, output_id})
    if record.get('status') == 'complete':
        saved = {r['artifact_id'] for r in record.get('persistence', {}).get('receipts', [])}
        if not {input_id, output_id} <= saved:
            raise RationaleError('First-principles calculation lacks persistence receipts')
    return needed


def validate(record, *, require_current=False, root=ROOT, observed_publication_times=()):
    if record.get('scope') not in SCOPES:
        return {'status': 'exempt', 'semantic_truth_verified': False}
    if not require_current and not requires_current(record, observed_publication_times):
        return {'status': 'historical_not_certified', 'semantic_truth_verified': False}
    if record.get('policy_versions', {}).get('rationale') != VERSION:
        raise RationaleError('Current rationale policy declaration required')
    block, arts, lock, card, values = inspect_card(record, root)
    if block.get('status') != 'reviewed':
        raise RationaleError('Rationale independent review incomplete')
    presentation_id = block.get('presentation_artifact_id', record['result']['report_artifact_id'])
    presentation = raw_artifact(arts, presentation_id).decode('utf-8')
    figure = raw_artifact(arts, block['diagram_artifact_id']).decode('utf-8')
    card_hash = arts[block['card_artifact_id']]['sha256']
    fmt = 'mermaid' if Path(arts[block['diagram_artifact_id']]['path']).suffix == '.mmd' else 'svg'
    expected = diagram(card, values, card_hash, fmt)
    if figure != expected:
        raise RationaleError('Diagram is stale or differs from canonical rationale')
    visible_presentation(presentation, expected, card_hash, fmt)
    review = json_artifact(arts, block['review_artifact_id'])
    reviewer = record['audit']['independent_review']['reviewer_id']
    if review.get('status') != 'approved_rationale' or review.get('reviewer_id') != reviewer or reviewer.split('/')[-1] == record['audit']['author_id'].split('/')[-1]:
        raise RationaleError('Rationale reviewer is missing, unapproved or not independent')
    if review.get('ticker') != card['ticker'] or review.get('version') != VERSION:
        raise RationaleError('Rationale review identity/version mismatch')
    needed = {block[k] for k in ['dependency_lock_artifact_id', 'card_artifact_id', 'diagram_artifact_id']} | {presentation_id, record['result']['report_artifact_id']}
    needed.update(verify_first_principles(record, card, arts, lock, review, observed_publication_times))
    checks = review.get('critic_checks', {})
    all_evidence = list(card['nodes'].values()) + list(card['methodology_applications'].values()) + card['cycle_challenge']['indicators'] + card['cycle_challenge']['hypotheses'] + list(card['cycle_challenge']['economic_questions'].values()) + list(checks.values()) + [card['beat_test']]
    for node in all_evidence:
        needed.update(node['model_artifact_ids'])
    for binding in card['metrics'].values():
        needed.add(binding['artifact_id'])
    for f in card['forecasts']:
        needed.add(f['model_binding']['artifact_id'])
    for binding in card['cycle_challenge']['normalization'].get('cases', {}).values():
        needed.add(binding['artifact_id'])
    numeric = card['cycle_challenge'].get('numerical_check')
    if numeric:
        needed.update(verify_cycle_arithmetic(record, card, arts, lock)['artifact_ids'])
    if card['beat_test']['basis'] != 'unavailable':
        for key in ['revenue_forecast', 'revenue_expectation', 'profit_forecast', 'profit_expectation']:
            needed.add(card['beat_test'][key]['artifact_id'])
    for aid in needed:
        raw_artifact(arts, aid)
        if review.get('artifact_hashes', {}).get(aid) != arts[aid]['sha256']:
            raise RationaleError('Rationale review hash missing/stale: ' + aid)
    if set(review.get('critic_checks', {})) != CRITIC_CHECKS:
        raise RationaleError('Independent cycle/valuation challenge incomplete')
    for check in review['critic_checks'].values():
        evidence_link(check, record, arts)
    visual = review.get('visual_inspection', {})
    if visual.get('method') not in {'rendered_html', 'rendered_markdown', 'native_preview'}:
        raise RationaleError('Actual rendered-report visual inspection required')
    text(visual.get('finding'), 'Visual inspection finding')
    for finding in review.get('findings', []):
        if finding.get('disposition') not in {'fixed', 'explained'}:
            raise RationaleError('Unresolved rationale review finding')
        text(finding.get('rationale'), 'Review finding rationale')
    reviewed = set(record['audit']['independent_review']['reviewed_artifact_ids'])
    if not {block['dependency_lock_artifact_id'], block['card_artifact_id'], block['diagram_artifact_id'], presentation_id} <= reviewed:
        raise RationaleError('Main independent review did not cover rationale artifacts')
    if record.get('status') == 'complete':
        saved = {r['artifact_id'] for r in record.get('persistence', {}).get('receipts', [])}
        persistent = {block[k] for k in ['dependency_lock_artifact_id', 'card_artifact_id', 'diagram_artifact_id', 'review_artifact_id']} | {presentation_id}
        if numeric:
            persistent.update({numeric['input_artifact_id'], numeric['output_artifact_id']})
        if not persistent <= saved:
            raise RationaleError('Rationale package lacks persistence receipts')
    return {'status': 'validated', 'version': VERSION, 'ticker': card['ticker'], 'action': card['action'],
            'dependency_files': len(lock['files']), 'forecast_count': len(card['forecasts']),
            'semantic_truth_verified': False}


def publication_times(value):
    result = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {'created_at', 'modified_at', 'confirmed_at'} and isinstance(child, str):
                result.append(child)
            else:
                result.extend(publication_times(child))
    elif isinstance(value, list):
        for child in value:
            result.extend(publication_times(child))
    return result


def score(card, outcomes, *, as_of=None, card_sha256=None):
    now = instant(as_of) if as_of else datetime.now(timezone.utc)
    if card.get('version') != VERSION or not card_sha256:
        raise RationaleError('Exact frozen rationale card hash required')
    if outcomes.get('card_sha256') != card_sha256:
        raise RationaleError('Outcome belongs to a different forecast vintage')
    forecasts = {f['id']: f for f in card['forecasts']}
    rows = outcomes.get('observations', [])
    actuals = {r['forecast_id']: r for r in rows}
    if len(forecasts) != len(card['forecasts']) or len(actuals) != len(rows) or set(actuals) - set(forecasts):
        raise RationaleError('Duplicate/unknown forecast or outcome IDs')
    results = []
    for fid, f in forecasts.items():
        a = actuals.get(fid)
        if a is None or instant(f['resolve_after']) > now:
            results.append({'forecast_id': fid, 'status': 'pending'})
            continue
        if instant(a['available_at']) > now or instant(a['available_at']) < instant(f['resolve_after']):
            raise RationaleError('Outcome availability is premature or in the future')
        text(a.get('source'), 'Actual outcome source')
        if a.get('units') != f['units'] or a.get('period') != f['period']:
            raise RationaleError('Outcome units/period differ from frozen forecast')
        actual = number(a.get('actual'))
        predicted = f['prediction']
        row = {'forecast_id': fid, 'status': 'resolved', 'kind': f['kind'], 'units': f['units'], 'period': f['period'], 'actual': actual, 'source': a['source']}
        if f['kind'] == 'binary':
            if actual not in {0, 1} or not 0 <= number(predicted) <= 1:
                raise RationaleError('Binary outcome/probability invalid')
            row['brier_loss'] = (predicted - actual) ** 2
        elif f['kind'] == 'interval':
            low, high = map(number, predicted)
            alpha = 1 - number(f['coverage'])
            if low > high or not 0 < alpha < 1:
                raise RationaleError('Invalid interval or coverage')
            row.update(covered=low <= actual <= high, width=high-low,
                       interval_score=high-low + (2/alpha)*max(low-actual, actual-high, 0))
        else:
            error = number(predicted) - actual
            if f['kind'] == 'mean':
                row.update(signed_error=error, squared_error=error**2)
            elif f['kind'] == 'median':
                row['absolute_error'] = abs(error)
            else:
                raise RationaleError('Unsupported forecast kind')
        results.append(row)
    return {'version': VERSION, 'card_sha256': card_sha256, 'cohort_id': card['cohort_id'],
            'thesis_family': card['thesis_family'], 'origin': card['origin'],
            'expected': len(forecasts), 'resolved': sum(r['status'] == 'resolved' for r in results),
            'pending': sum(r['status'] == 'pending' for r in results), 'items': results,
            'meaning': 'Scoped descriptive scores; no pooled mixed units, calibration significance or causal attribution.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    s = sub.add_parser('snapshot'); s.add_argument('--scope', choices=sorted(SCOPES), required=True); s.add_argument('--output', required=True)
    v = sub.add_parser('validate'); v.add_argument('--record', required=True); v.add_argument('--output')
    d = sub.add_parser('render'); d.add_argument('--record', required=True); d.add_argument('--output', required=True); d.add_argument('--format', choices=['svg', 'mermaid', 'html'], default='svg')
    e = sub.add_parser('score'); e.add_argument('--card', required=True); e.add_argument('--outcomes', required=True); e.add_argument('--output', required=True); e.add_argument('--as-of')
    a = p.parse_args()
    try:
        if a.command == 'snapshot':
            value = dependency_lock(a.scope); atomic_write(a.output, encoded(value))
        elif a.command == 'render':
            record = json.loads(Path(a.record).read_text())
            block, arts, _, card, values = inspect_card(record)
            card_hash = arts[block['card_artifact_id']]['sha256']
            value = presentation(card, values, card_hash) if a.format=='html' else diagram(card, values, card_hash, a.format)
            atomic_write(a.output, value)
            value = {'status': 'rendered', 'full_research_complete': False}
        elif a.command == 'score':
            raw = Path(a.card).read_bytes(); card = json.loads(raw)
            value = score(card, json.loads(Path(a.outcomes).read_text()), as_of=a.as_of, card_sha256=digest(raw))
            atomic_write(a.output, encoded(value))
        else:
            value = validate(json.loads(Path(a.record).read_text()), require_current=True)
            if a.output: atomic_write(a.output, encoded(value))
        print(encoded(value), end='')
    except Exception as exc:
        print(encoded({'status': 'rejected', 'error': type(exc).__name__ + ': ' + str(exc), 'full_research_complete': False}), end='')
        raise SystemExit(2)


if __name__ == '__main__':
    main()
