"""Grade the independent development route screen and instruction-size proxies."""
import argparse
import json
import os
from pathlib import Path

from ui.route import ROOT, read_catalog, resolve
from ui.session_init import initialize


def summarize():
    cases = json.loads((ROOT / 'ui/tests/expansion-routing-cases.json').read_text())['cases']
    raw = json.loads((ROOT / 'ui/runtime/expansion-20261102/router-screen/results.json').read_text())['results']
    by_id = {item['id']: item for item in raw}
    if len(by_id) != len(raw) or set(by_id) != {case['id'] for case in cases}:
        raise ValueError('Missing or duplicate screen cases')
    catalog = read_catalog()
    texts = {name: (ROOT / 'ui/skills' / name / 'SKILL.md').read_text() for name in catalog['skills']}
    all_bytes = sum(len(text.encode()) for text in texts.values())
    os.environ.setdefault('TIKTOKEN_CACHE_DIR', str(ROOT / 'tuning/runtime/tokenizer-cache'))
    try:
        import tiktoken
        encoding = tiktoken.get_encoding('o200k_base')
        tokens = lambda text: len(encoding.encode(text))
        token_measurement = 'o200k_base full-entrypoint instruction proxy; not actual model context or billed usage'
    except ImportError:
        tokens = lambda text: None
        token_measurement = 'unavailable; run in documented optional project tokenizer environment'
    rows = []
    for case in cases:
        item = by_id[case['id']]
        actual = resolve(item.get('decisions', []), item.get('skill_flags', []),
                         item.get('available_tools_declared', []), item.get('guidance_only', False))
        selected = [entry['skill'] for entry in actual['selected']]
        missing = sorted(set(case['required']) - set(selected))
        unnecessary = sorted(set(selected) - set(case['required']) - set(case['optional']))
        row = {'id': case['id'], 'status': actual['status'], 'selected': selected,
               'missing': missing, 'unnecessary': unnecessary,
               'recorded_selection_matches_replay': item['selected_names'] == selected,
               'status_correct': case['status'] == actual['status'],
               'selected_body_bytes': sum(len(texts[name].encode()) for name in selected),
               'selected_body_tokens_proxy': tokens('\n'.join(texts[name] for name in selected))}
        row['passed'] = (not missing and not unnecessary and row['status_correct']
                         and row['recorded_selection_matches_replay'])
        rows.append(row)
    direct = initialize(ROOT, {'hook_event_name': 'SessionStart', 'source': 'startup', 'cwd': str(ROOT)})
    context = direct['hookSpecificOutput']['additionalContext']
    return {'cases': rows, 'passed': sum(row['passed'] for row in rows), 'total': len(rows),
            'entrypoints': len(texts), 'all_body_bytes': all_bytes,
            'all_body_tokens_proxy': tokens('\n'.join(texts.values())),
            'direct_startup_bytes': len(context.encode()), 'direct_startup_tokens_proxy': tokens(context),
            'direct_startup_status': direct['systemMessage'], 'actual_host_initialization': 'unverified',
            'measurement': token_measurement,
            'allowed_claim': 'One independent development routing screen and source-size measurements; no statistical quality/ROI or billed-usage claim'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    target = (ROOT / parser.parse_args().output).resolve()
    if not target.is_relative_to(ROOT) or target.exists():
        raise ValueError('Output must be a new workspace-local file')
    result = summarize()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'cases'}, indent=2))
    raise SystemExit(result['passed'] != result['total'])
