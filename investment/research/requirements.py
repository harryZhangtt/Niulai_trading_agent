"""Freeze what the investment question needs; contains no network/provider code."""
from datetime import datetime
import json
from pathlib import Path
from shared.research_sources.artifacts import digest, read, require, save

PROFILES = Path(__file__).with_name('profiles')


def freeze(request, directory):
    require(set(request) == {'subject', 'as_of', 'profile', 'claims'}, 'REQUIREMENT_REQUEST_INVALID')
    require(request['profile'] in ('accelerated-compute', 'business-economics'), 'PROFILE_UNKNOWN')
    profile = json.loads((PROFILES / (request['profile'] + '.json')).read_text())
    require(isinstance(request['subject'], str) and bool(request['subject'].strip()), 'SUBJECT_REQUIRED')
    stamp = datetime.fromisoformat(request['as_of'].replace('Z', '+00:00'))
    require(stamp.tzinfo is not None, 'AS_OF_TIMEZONE_REQUIRED')
    claims = request['claims']
    require(isinstance(claims, list) and bool(claims), 'MATERIAL_CLAIMS_REQUIRED')
    require(all(isinstance(c, dict) and set(c) == {'id', 'question'} and
                isinstance(c['id'], str) and c['id'] and isinstance(c['question'], str) and c['question'] for c in claims),
            'CLAIM_INVALID')
    require(len({c['id'] for c in claims}) == len(claims), 'CLAIM_DUPLICATE')
    requirements = []
    for claim in claims:
        for rule in profile['requirements']:
            # The initial issuer-specific adapter deliberately supports NVDA only.
            # It must never silently apply NVIDIA source rules to another company.
            if rule.get('issuer_override'):
                require(rule['issuer_override'] == request['subject'], 'ISSUER_PROFILE_OVERRIDE_REQUIRED')
            requirements.append({**rule, 'id': claim['id'] + ':' + rule['family'],
                                 'claim_id': claim['id'], 'investment_question': claim['question']})
    snapshot = {'schema_version': 1, 'subject': request['subject'], 'as_of': request['as_of'],
                'profile': profile['id'], 'profile_version': profile['version'],
                'profile_sha256': digest(profile), 'claims': claims, 'requirements': requirements}
    ref = save(directory, snapshot)
    # This pin travels in the coordinator/job envelope, outside the worker packet.
    return {'requirements': ref, 'expected_sha256': ref['sha256']}


def load(contract):
    require(set(contract) == {'requirements', 'expected_sha256'}, 'REQUIREMENT_CONTRACT_INVALID')
    require(contract['requirements']['sha256'] == contract['expected_sha256'], 'REQUIREMENTS_PIN_MISMATCH')
    snapshot = read(contract['requirements'])
    require(snapshot.get('schema_version') == 1 and snapshot.get('requirements'), 'REQUIREMENTS_SNAPSHOT_INVALID')
    return snapshot
