"""Host-owned intent grading; successful resolution is not intent accuracy."""
from ui.route import resolve

METRICS = ['intent_correct','missing_skills','extra_skills','optional_skills_loaded',
           'selection_precision','selection_recall','loaded_body_bytes','clarification_correct']


def grade(case_id, frozen, expected, output):
    plans = output.get('plans', [])
    reasons = []
    if output.get('id') != case_id: reasons.append('CASE_ID_MISMATCH')
    needs = expected.get('clarify', False)
    clarification_correct = output.get('needs_clarification') is needs
    if not clarification_correct: reasons.append('CLARIFICATION_MISMATCH')
    required = set(expected.get('required', [])); optional = set(expected.get('optional', []))
    chosen = []; byte_count = 0
    for plan in plans:
        result = resolve(plan['decisions'], plan['skills'], available_tools=frozen.get('tools', []))
        if result['status'] != expected.get('status','UI_ROUTE_OK'): reasons.append('RESOLVER_STATUS_MISMATCH')
        chosen.append({s['skill'] for s in result['selected']})
        byte_count += result.get('selected_body_bytes', 0)
    selected = set().union(*chosen) if chosen else set()
    if needs:
        if plans: reasons.append('AMBIGUOUS_REQUEST_LOADED_SKILLS')
        missing = set(); extra = selected
    elif expected.get('variants'):
        want = sorted(tuple(sorted(v)) for v in expected['variants'])
        if sorted(tuple(sorted(v)) for v in chosen) != want: reasons.append('VARIANT_PARTITION_MISMATCH')
        required = set().union(*(set(v) for v in expected['variants']))
        missing = required-selected; extra = selected-required
    else:
        if len(plans) != 1: reasons.append('PLAN_COUNT_MISMATCH')
        missing = required-selected; extra = selected-required-optional
    if missing: reasons.append('REQUIRED_SKILL_MISSING')
    if extra: reasons.append('UNNECESSARY_SKILL_LOADED')
    passed = not reasons
    precision = len(selected-extra)/len(selected) if selected else 1.0
    recall = len(required-missing)/len(required) if required else 1.0
    return {'passed':passed,'metrics':{'intent_correct':int(passed),
        'missing_skills':len(missing),'extra_skills':len(extra),
        'optional_skills_loaded':len(selected & optional),
        'selection_precision':precision,'selection_recall':recall,
        'loaded_body_bytes':byte_count,'clarification_correct':int(clarification_correct)},
        'reasons':sorted(set(reasons))}
