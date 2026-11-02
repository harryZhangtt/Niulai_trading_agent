"""Pure, bounded eligibility policy; no retrieval, persistence or truth flag.

These receipts describe mechanical applicability to a frozen requirement.
Source meaning and any declared review still require source-grounded review.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from itertools import combinations
import math
import re

from shared.research_sources.artifacts import SourceError, digest, require

VERSION = 'use-policy-v1'
DIMENSIONS = ('entity', 'metric', 'definition', 'period', 'unit', 'basis')


def stamp(value):
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(result.tzinfo is not None and result.utcoffset() is not None, 'POLICY_TIME_INVALID')
        return result.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        raise SourceError('POLICY_TIME_INVALID') from None


def number(value):
    require(isinstance(value, str) and len(value) <= 100, 'POLICY_DECIMAL_STRING_REQUIRED')
    try:
        result = Decimal(value)
        require(result.is_finite(), 'POLICY_VALUE_NONFINITE')
        return result
    except InvalidOperation:
        raise SourceError('POLICY_VALUE_INVALID') from None


def binding(observation):
    require(isinstance(observation, dict) and isinstance(observation.get('id'), str), 'POLICY_OBSERVATION_INVALID')
    require(all(type(observation.get(k)) is int and observation[k] > 0
                for k in ('revision', 'lifecycle_revision')), 'POLICY_REVISION_INVALID')
    return {k: observation[k] for k in ('id', 'revision', 'lifecycle_revision')}


def policy(requirement):
    require(isinstance(requirement, dict) and isinstance(requirement.get('id'), str)
            and bool(requirement['id']), 'POLICY_REQUIREMENT_INVALID')
    require(requirement.get('mode') in ('historical', 'current'), 'POLICY_MODE_REQUIRED')
    require(requirement.get('criticality') in ('critical', 'context'), 'POLICY_CRITICALITY_REQUIRED')
    cutoff = stamp(requirement.get('cutoff', requirement.get('as_of')))
    for key in ('max_age_seconds', 'refresh_after_seconds'):
        if requirement.get(key) is not None:
            require(type(requirement[key]) is int and requirement[key] >= 0, 'POLICY_INTERVAL_INVALID')
    if requirement.get('decision_deadline') is not None:
        stamp(requirement['decision_deadline'])
    return cutoff


def classify(requirement, observation, now):
    """Fetching unchanged bytes never resets source_time or decision age."""
    cutoff, at = policy(requirement), stamp(now)
    ref = binding(observation)
    payload = observation.get('payload')
    require(isinstance(payload, dict), 'POLICY_PAYLOAD_INVALID')
    reasons, status = [], 'eligible'
    if observation.get('state') != 'active':
        reasons.append('WITHDRAWN')
    for key in DIMENSIONS:
        if requirement.get(key) is not None:
            if payload.get(key) is None:
                reasons.append('MISSING_' + key.upper())
            elif payload[key] != requirement[key]:
                reasons.append('MISMATCH_' + key.upper())
    if requirement.get('value_kind') == 'numeric':
        if payload.get('value') is None:
            reasons.append('MISSING_NUMERIC_VALUE')
        else:
            number(payload['value'])
    if payload.get('available_at') is None:
        reasons.append('AVAILABILITY_UNKNOWN')
    elif stamp(payload['available_at']) > cutoff:
        reasons.append('AVAILABLE_AFTER_CUTOFF')
    hard_expiry = None
    source_time = payload.get('source_time')
    if source_time is not None:
        source_time = stamp(source_time)
        if source_time > at or source_time > cutoff:
            reasons.append('SOURCE_TIME_AFTER_INFORMATION_SET')
    age = requirement.get('max_age_seconds')
    if age is not None:
        if source_time is None:
            reasons.append('SOURCE_TIME_UNKNOWN')
        else:
            hard_expiry = source_time + timedelta(seconds=age)
            reference = cutoff if requirement['mode'] == 'historical' else at
            if reference >= hard_expiry:
                reasons.append('SOURCE_EXPIRED')
    elif requirement['mode'] == 'current' and requirement['criticality'] == 'critical':
        reasons.append('FRESHNESS_POLICY_REQUIRED')
    refresh_due = False
    if requirement.get('refresh_after_seconds') is not None:
        checked = payload.get('last_checked_at')
        if checked is not None and stamp(checked) > at:
            reasons.append('CHECK_TIME_IN_FUTURE')
        refresh_due = checked is None or (at - stamp(checked)).total_seconds() >= requirement['refresh_after_seconds']
    if reasons:
        status = 'blocked' if requirement['criticality'] == 'critical' else 'qualified'
    return {'status': status, 'reasons': reasons, 'binding': ref, 'refresh_due': refresh_due,
            'hard_expiry_at': hard_expiry.isoformat() if hard_expiry else None,
            'requirement_sha256': digest(requirement), 'policy_version': VERSION}


def schedule_check(requirement, outcome, now, attempt=0):
    """Return a due record; no timer, retry loop or deadline extension."""
    policy(requirement); at = stamp(now)
    require(type(attempt) is int and 0 <= attempt <= 32, 'POLICY_ATTEMPT_INVALID')
    deadline = stamp(requirement['decision_deadline']) if requirement.get('decision_deadline') else None
    reasons = set(outcome.get('reasons', []))
    result = {'requirement_sha256': digest(requirement), 'policy_version': VERSION,
              'next_check_at': None, 'resume_condition': None,
              'decision_deadline': deadline.isoformat() if deadline else None, 'attempt': attempt}
    if deadline is not None and at >= deadline:
        return {**result, 'resume_condition': 'deadline_expired'}
    if reasons & {'AUTH_REQUIRED', 'ENTITLEMENT_REQUIRED'}:
        return {**result, 'resume_condition': 'access_changed'}
    if reasons & {'NO_SUPPORTED_HOST', 'UNSUPPORTED_FORMAT', 'NO_COVERAGE'}:
        return {**result, 'resume_condition': 'compatible_route_available'}
    if reasons & {'TIMEOUT', 'RATE_LIMITED', 'TRANSIENT_FAILURE'}:
        delay = max(min(30 * 2 ** attempt, 900), outcome.get('retry_after_seconds', 0))
    else:
        delay = requirement.get('refresh_after_seconds')
        if delay is None:
            return {**result, 'resume_condition': 'refresh_policy_required'}
    require(type(delay) in (int, float) and math.isfinite(delay) and delay >= 0, 'POLICY_RETRY_DELAY_INVALID')
    due = at + timedelta(seconds=delay)
    if deadline is not None and due >= deadline:
        return {**result, 'resume_condition': 'wait_exceeds_deadline'}
    return {**result, 'next_check_at': due.isoformat(), 'resume_condition': 'due'}


def _artifact_ref(value):
    return (isinstance(value, dict) and set(value) == {'path', 'sha256'}
            and isinstance(value['path'], str) and bool(value['path'])
            and isinstance(value['sha256'], str) and re.fullmatch('[0-9a-f]{64}', value['sha256']) is not None)


def _review_matches(review, requirement_hash, bindings, kind):
    """Only scoped review declarations qualify; publication resolves artifacts."""
    return (isinstance(review, dict) and review.get('kind') == kind
            and review.get('requirement_sha256') == requirement_hash
            and review.get('bindings') == bindings
            and isinstance(review.get('reason'), str) and bool(review['reason'].strip())
            and _artifact_ref(review.get('review_ref')))


def resolve(requirement, observations, now, remaining_attempts=1, *, exception=None, reviewed_bounds=None):
    """Mechanical agreement or bounded repair; publication still reviews support."""
    policy(requirement); at = stamp(now)
    require(type(remaining_attempts) is int and remaining_attempts >= 0, 'POLICY_ATTEMPT_INVALID')
    require(isinstance(observations, list) and len(observations) <= 8, 'POLICY_CANDIDATE_LIMIT')
    identities = [(o.get('id'), o.get('revision'), o.get('lifecycle_revision')) for o in observations]
    require(len(set(identities)) == len(identities), 'POLICY_DUPLICATE_OBSERVATION')
    assessments = [classify(requirement, o, at) for o in observations]
    eligible = [(o, a) for o, a in zip(observations, assessments) if a['status'] == 'eligible']
    bindings = [a['binding'] for _, a in eligible]
    rh = digest(requirement)
    receipt = {'schema_version': 1, 'policy_version': VERSION, 'requirement_id': requirement['id'],
               'requirement_sha256': rh, 'bindings': bindings, 'assessments': assessments,
               'status': 'needs_check', 'reasons': [], 'next_action': None,
               'semantic_truth_verified': False}
    expired = requirement.get('decision_deadline') is not None and at >= stamp(requirement['decision_deadline'])
    def unresolved(reasons, action):
        return {**receipt, 'status': 'restricted' if expired or remaining_attempts == 0 else 'needs_check',
                'reasons': reasons, 'next_action': None if expired or remaining_attempts == 0 else action}
    if expired:
        return unresolved(['DECISION_DEADLINE_EXPIRED'], None)
    if not eligible:
        return unresolved(sorted({r for a in assessments for r in a['reasons']}) or ['MISSING_EVIDENCE'], 'fetch_compatible_source')
    rows = [o['payload'] for o, _ in eligible]
    # A missing requirement dimension cannot silently make incompatible rows agree.
    if len(rows) > 1 and any(any(row.get(k) is None for row in rows) or len({str(row[k]) for row in rows}) != 1 for k in DIMENSIONS):
        return unresolved(['NOT_COMPARABLE'], 'reconcile_definitions')
    values = [number(row['value']) for row in rows if row.get('value') is not None]
    if values and len(values) != len(rows):
        return unresolved(['MISSING_NUMERIC_VALUE'], 'extract_missing_value')
    if len(values) > 1:
        require('absolute_tolerance' in requirement and 'relative_tolerance' in requirement, 'POLICY_TOLERANCE_REQUIRED')
        absolute, relative = number(requirement['absolute_tolerance']), number(requirement['relative_tolerance'])
        require(absolute >= 0 and relative >= 0, 'POLICY_TOLERANCE_INVALID')
        differences = [abs(a - b) for a, b in combinations(values, 2)]
        bound = max(absolute, relative * max(abs(v) for v in values))
        receipt.update(values=[str(v) for v in values], max_difference=str(max(differences)), allowed_difference=str(bound),
                       observed_range={'low': str(min(values)), 'high': str(max(values))})
        if max(differences) > bound:
            if (_review_matches(reviewed_bounds, rh, bindings, 'bounded_use')
                    and _artifact_ref(reviewed_bounds.get('calculation_ref'))):
                low, high = number(reviewed_bounds.get('low')), number(reviewed_bounds.get('high'))
                if low <= min(values) <= max(values) <= high:
                    return {**receipt, 'status': 'bounded', 'reasons': ['REVIEWED_CONFLICT_BOUNDS'], 'review': reviewed_bounds}
            return unresolved(['CONFLICTING_VALUES'], 'inspect_revisions_or_independent_source')
    required = requirement.get('minimum_sources', 2 if requirement['criticality'] == 'critical' else 1)
    require(type(required) is int and 1 <= required <= 8, 'POLICY_MINIMUM_SOURCES_INVALID')
    lineage = [row.get('upstream_lineage') for row in rows]
    independent = len(set(lineage)) if all(isinstance(x, str) and x and x != 'unknown' for x in lineage) else 0
    if independent < required:
        if (_review_matches(exception, rh, bindings, 'primary_only') and _artifact_ref(exception.get('alternative_attempt_ref'))
                and _artifact_ref(exception.get('sensitivity_ref')) and all(row.get('source_role') == 'primary' for row in rows)):
            return {**receipt, 'status': 'supported', 'reasons': ['REVIEWED_PRIMARY_ONLY_EXCEPTION'], 'review': exception}
        return unresolved(['INSUFFICIENT_INDEPENDENT_LINEAGE'], 'obtain_independent_observation_or_review_exception')
    return {**receipt, 'status': 'supported', 'reasons': ['MECHANICALLY_COMPARABLE_EVIDENCE']}
