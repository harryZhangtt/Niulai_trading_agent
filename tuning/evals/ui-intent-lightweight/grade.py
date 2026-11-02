"""Frozen host grader: intent accuracy is distinct from resolver validity."""
from ui.route import read_catalog, resolve

METRICS = [
    'intent_correct', 'missing_skills', 'extra_skills', 'optional_skills_loaded',
    'selection_precision', 'selection_recall', 'clarification_correct',
    'resolver_status_correct', 'selected_body_bytes',
]


def expanded(decisions):
    catalog = read_catalog()
    names = set()

    def add(name):
        names.add(name)
        for dependency in catalog['skills'][name].get('requires', []):
            add(dependency)

    for decision in decisions:
        for name in catalog['decisions'][decision]:
            add(name)
    return names


def grade(case_id, frozen, expected, output):
    reasons = []
    if set(output) != {'id', 'needs_clarification', 'plans'} or output.get('id') != case_id:
        reasons.append('OUTPUT_SCHEMA')
    clarify = output.get('needs_clarification') is expected['clarify']
    if not clarify:
        reasons.append('CLARIFICATION_MISMATCH')
    plans = output.get('plans', [])
    chosen, byte_count, statuses = [], 0, []
    for plan in plans:
        if set(plan) != {'decisions'} or len(plan['decisions']) != len(set(plan['decisions'])):
            reasons.append('PLAN_SCHEMA_OR_DUPLICATE')
        result = resolve(decisions=plan['decisions'], available_tools=frozen['available_tools'])
        statuses.append(result['status'] == expected['status'])
        chosen.append({s['skill'] for s in result['selected']})
        byte_count += result.get('selected_body_bytes', 0)
    if not all(statuses):
        reasons.append('RESOLVER_STATUS_MISMATCH')
    required = expanded(expected['required_decisions'])
    optional = expanded(expected['optional_decisions']) - required
    selected = set().union(*chosen) if chosen else set()
    if expected['clarify']:
        if plans:
            reasons.append('AMBIGUOUS_REQUEST_LOADED_PLAN')
        missing, extra = set(), selected
    elif expected['variants']:
        variants = [expanded(decisions) for decisions in expected['variants']]
        if sorted(tuple(sorted(x)) for x in variants) != sorted(tuple(sorted(x)) for x in chosen):
            reasons.append('VARIANT_PARTITION_MISMATCH')
        required = set().union(*variants)
        missing, extra = required - selected, selected - required
    else:
        if len(plans) != 1:
            reasons.append('PLAN_COUNT_MISMATCH')
        # backend-only must be an explicit no-UI decision rather than an empty plan.
        if expected['required_decisions'] == ['backend-only'] and plans != [{'decisions': ['backend-only']}]:
            reasons.append('BACKEND_PLAN_MISMATCH')
        missing, extra = required - selected, selected - required - optional
    if missing:
        reasons.append('REQUIRED_SKILL_MISSING')
    if extra:
        reasons.append('UNNECESSARY_SKILL_LOADED')
    passed = not reasons
    return {'passed': passed, 'metrics': {
        'intent_correct': int(passed), 'missing_skills': len(missing), 'extra_skills': len(extra),
        'optional_skills_loaded': len(selected & optional),
        'selection_precision': len(selected - extra) / len(selected) if selected else 1.0,
        'selection_recall': len(required - missing) / len(required) if required else 1.0,
        'clarification_correct': int(clarify), 'resolver_status_correct': int(all(statuses)),
        'selected_body_bytes': byte_count,
    }, 'reasons': sorted(set(reasons))}
