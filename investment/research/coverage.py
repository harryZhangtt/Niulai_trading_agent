"""Evidence-use gate. Fetch success is never a completed investment requirement."""
from datetime import datetime
from urllib.parse import urlsplit
from shared.research_sources.artifacts import digest, read, require
from .requirements import load


def timestamp(value):
    require(isinstance(value, str), 'SOURCE_AVAILABILITY_UNKNOWN')
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(t.tzinfo is not None, 'SOURCE_TIMEZONE_REQUIRED')
    return t


def pointer(value, path):
    require(isinstance(path, str) and path.startswith('/'), 'MODEL_POINTER_REQUIRED')
    for part in path[1:].split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        if isinstance(value, list):
            require(part.isdigit() and int(part) < len(value), 'MODEL_POINTER_INVALID')
            value = value[int(part)]
        else:
            value = value[part]
    return value


def validate(contract, packet_ref, *, record=None):
    snapshot = load(contract); packet = read(packet_ref)
    require(packet.get('requirements_sha256') == contract['expected_sha256'], 'PACKET_REQUIREMENTS_MISMATCH')
    evidence = packet.get('evidence')
    require(isinstance(evidence, list) and evidence, 'EVIDENCE_REQUIRED')
    requirements = {r['id']: r for r in snapshot['requirements']}
    covered = set(); issuer_lineages = set(); comparison_lineages = set()
    if record is not None:
        require(record['subject']['ticker'] == snapshot['subject']
                and timestamp(record['subject']['cutoff']) == timestamp(snapshot['as_of']), 'RECORD_SCOPE_MISMATCH')
        claims = {c['id']: c for c in record['claims']}
        sources = {s['id']: s for s in record['sources']}
        record_artifacts = {a['id']: a for a in record['artifacts']}
        def model_ids(value):
            result = set()
            if isinstance(value, dict):
                for k, v in value.items():
                    if k.endswith('_artifact_id') and isinstance(v, str): result.add(v)
                    elif k.endswith('_artifact_ids') and isinstance(v, list): result.update(v)
                    else: result.update(model_ids(v))
            elif isinstance(value, list):
                for v in value: result.update(model_ids(v))
            return result
        model_refs = {(a['path'], a['sha256']) for a in record['artifacts']
                      if a['id'] in model_ids(record['model']) and a['kind'].startswith('model_')}
        require(all(r['claim_id'] in claims for r in requirements.values()), 'MATERIAL_CLAIM_NOT_IN_RECORD')
        require(set(record.get('coverage', {}).get('industry_technology', {}).get('claim_ids', []))
                <= {r['claim_id'] for r in requirements.values()}, 'TECHNICAL_CLAIM_ROSTER_INCOMPLETE')
        if snapshot['subject'] == 'NVDA' and record.get('scope') == 'company_full':
            require(snapshot['profile'] == 'accelerated-compute', 'NVDA_FULL_TECHNICAL_PROFILE_REQUIRED')
    for item in evidence:
        rid = item.get('requirement_id')
        require(rid in requirements, 'EVIDENCE_REQUIREMENT_UNKNOWN')
        rule = requirements[rid]; receipt = read(item['source'])
        require(receipt.get('access_level') == rule['minimum_access'], 'SOURCE_ACCESS_INSUFFICIENT')
        require(urlsplit(receipt['source_url']).hostname in rule['allowed_hosts'], 'SOURCE_FAMILY_MISMATCH')
        require(timestamp(receipt.get('available_at')) <= timestamp(snapshot['as_of']), 'SOURCE_AFTER_CUTOFF')
        read(receipt['raw'], json_value=False)
        text = read(receipt['text'], json_value=False).decode()
        selected = item.get('passages')
        require(isinstance(selected, list) and selected, 'ACTUAL_PASSAGES_REQUIRED')
        for p in selected:
            require(type(p.get('start')) is int and type(p.get('end')) is int
                    and 0 <= p['start'] < p['end'] <= len(text)
                    and p.get('text') == text[p['start']:p['end']] and len(p['text'].strip()) >= 20,
                    'PASSAGE_NOT_IN_FETCHED_DOCUMENT')
            if record is not None:
                sid, pid = p.get('record_source_id'), p.get('record_passage_id')
                require(sid in sources and sources[sid]['url'] == receipt['source_url'], 'RECORD_SOURCE_UNBOUND')
                artifact = record_artifacts[sources[sid]['snapshot_artifact_id']]
                require(any(artifact['path'] == ref['path'] and artifact['sha256'] == ref['sha256']
                            for ref in (receipt['raw'], receipt['text'])), 'RECORD_SOURCE_SNAPSHOT_UNBOUND')
                actual = next((v for v in sources[sid]['passages'] if v['id'] == pid), None)
                require(actual and actual['text'] == p['text'] and any(
                    x['source_id'] == sid and x['passage_id'] == pid for x in claims[rule['claim_id']]['evidence_refs']),
                    'RECORD_CLAIM_PASSAGE_UNBOUND')
        require(isinstance(item.get('limitations'), str) and item['limitations'].strip(), 'APPLICABILITY_LIMITS_REQUIRED')
        lineage = item.get('upstream_lineage')
        require(isinstance(lineage, str) and lineage.strip() and lineage != 'unknown', 'LINEAGE_REVIEW_REQUIRED')
        if rule['family'] == 'issuer_technical': issuer_lineages.add(lineage)
        if rule['family'] == 'comparative_technical': comparison_lineages.add(lineage)
        link = item['economic_link']
        require(link.get('effect') in ('changed', 'unchanged', 'bounded') and isinstance(link.get('reason'), str)
                and link['reason'].strip(), 'ECONOMIC_LINK_REQUIRED')
        pointer(read(link['artifact']), link.get('pointer'))
        if record is not None:
            require((link['artifact']['path'], link['artifact']['sha256']) in model_refs, 'MODEL_ARTIFACT_NOT_IN_RECORD')
        covered.add(rid)
    require(covered == set(requirements), 'REQUIRED_SOURCE_COVERAGE_INCOMPLETE')
    require(not issuer_lineages.intersection(comparison_lineages), 'SHARED_UPSTREAM_NOT_INDEPENDENT')
    review = packet.get('review', {})
    require(review.get('status') == 'approved_source_coverage'
            and review.get('evidence_sha256') == digest(evidence), 'SOURCE_REVIEW_MISSING_OR_STALE')
    author, reviewer = review.get('author_id', ''), review.get('reviewer_id', '')
    require(author and reviewer and author.split('/')[-1] != reviewer.split('/')[-1], 'INDEPENDENT_REVIEW_REQUIRED')
    if record is not None:
        require(author == record['audit']['author_id'], 'REVIEW_AUTHOR_MISMATCH')
    findings = review.get('findings', [])
    require(len(findings) == len(requirements) and {f.get('requirement_id') for f in findings} == set(requirements),
            'REVIEW_COVERAGE_INCOMPLETE')
    for f in findings:
        require(all(f.get(k) is True for k in ('source_support_checked', 'applicability_checked',
                    'lineage_checked', 'economic_transfer_checked')) and isinstance(f.get('finding'), str)
                    and f['finding'].strip(), 'SUBSTANTIVE_REVIEW_REQUIRED')
    return {'status': 'validated_source_coverage', 'requirements_sha256': contract['expected_sha256'],
            'packet': packet_ref, 'requirements_checked': len(requirements),
            'semantic_review': 'recorded and hash-bound; reviewer truth not mechanically established',
            'investment_alpha_established': False}
