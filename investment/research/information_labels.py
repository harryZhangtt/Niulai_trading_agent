"""Immutable, policy-bound labels. Annotation never admits a source as evidence.

The writer validates source/claim bytes and review bindings. The read-only
projection can use ``classify`` without writing; persisted labels remain separate
from authoritative receipts and cannot change pipeline status.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator
from shared.research_sources.artifacts import INVESTMENT_STATE, SourceError, digest, encoded, private_path, read, require, save

HERE = Path(__file__).parent
POLICY_VERSION = 'source-labels-1.0.0'
POLICY = {'version': POLICY_VERSION, 'rule': 'origin-and-document-hints-only',
          'epistemic': 'document-mixed-or-unknown; no claim truth inference',
          'taxonomy_sha256': hashlib.sha256((HERE / 'information-taxonomy.json').read_bytes()).hexdigest(),
          'schema_sha256': hashlib.sha256((HERE / 'information-labels.schema.json').read_bytes()).hexdigest(),
          'implementation_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
POLICY_SHA256 = digest(POLICY)
DIRECTORY = INVESTMENT_STATE / 'information-labels'
SCHEMA = json.loads((HERE / 'information-labels.schema.json').read_text())
VALIDATOR = Draft202012Validator(SCHEMA)


def classify(source, source_ref, *, claim_ref=None):
    """Conservative provisional dimensions; issuer origin is not factual status."""
    url = source.get('source_url', '')
    try:
        host, path = urlsplit(url).hostname or '', urlsplit(url).path.lower()
    except (TypeError, ValueError):
        host, path = '', ''
    issuer = (host == 'servicenow.com' or host.endswith('.servicenow.com')) and '/community/' not in path
    regulator = host == 'sec.gov' or host.endswith('.sec.gov')
    academic = host in {'arxiv.org', 'export.arxiv.org', 'openalex.org', 'api.openalex.org'}
    kind = 'issuer' if issuer else 'regulator' if regulator else 'academic' if academic else 'unknown'
    perspective = 'supplier' if issuer else 'regulator' if regulator else 'researcher' if academic else 'unknown'
    doc = 'unknown'
    if 'financial-results' in path: doc = 'earnings_release'
    elif regulator: doc = 'filing'
    elif academic and 'arxiv' in host: doc = 'technical_paper'
    elif any(hint in path for hint in ('legal', 'licensing', 'entitlement')): doc = 'legal_terms'
    elif any(hint in path for hint in ('community', 'forum')): doc = 'discussion'
    topics = ['financial.performance'] if doc in {'earnings_release', 'filing'} else ['business.model'] if doc == 'legal_terms' else ['product.capability'] if issuer else ['unclassified']
    return {'schema_version': 1, 'source_ref': source_ref, 'claim_ref': claim_ref,
            'scope': 'claim' if claim_ref else 'document', 'publisher_kind': kind,
            'perspectives': [perspective], 'document_type': doc, 'topics': topics,
            'epistemic_status': 'unknown' if claim_ref or doc == 'unknown' else 'mixed',
            'annotation': {'method': 'rule', 'status': 'provisional',
                           'policy_version': POLICY_VERSION, 'review_ref': None},
            'limitations': ['Origin/document hints only; passage support, truth and historical eligibility are not established.',
                            'A document may mix actuals, targets, estimates and opinion.']}


def validate_label(label, *, loader=read):
    require(VALIDATOR.is_valid(label), 'LABEL_SCHEMA_INVALID')
    source = loader(label['source_ref'])
    require(isinstance(source, dict) and isinstance(source.get('source_url'), str), 'LABEL_SOURCE_INVALID')
    # A receipt's declared hash is not enough: inspect the bound capture bytes.
    loader(source.get('raw'), json_value=False)
    if source.get('text') is not None: loader(source['text'], json_value=False)
    if label['claim_ref'] is not None: loader(label['claim_ref'])
    annotation = label['annotation']
    if annotation['status'] == 'reviewed':
        review = loader(annotation['review_ref'])
        unsigned = {**label, 'annotation': {**annotation, 'status': 'provisional', 'review_ref': None}}
        require(isinstance(review, dict) and review.get('label_sha256') == digest(unsigned)
                and review.get('source_sha256') == label['source_ref']['sha256']
                and review.get('decision') == 'approved'
                and isinstance(review.get('reviewer_id'), str) and bool(review['reviewer_id'].strip()), 'LABEL_REVIEW_BINDING_INVALID')
    return source


def annotate_source(source_ref, directory=None, *, label=None, policy=None):
    """Persist one immutable version; does not mutate the source or a latest head."""
    source = read(source_ref)
    label = classify(source, source_ref) if label is None else label
    require(isinstance(label, dict) and label.get('source_ref') == source_ref, 'LABEL_SOURCE_BINDING_MISMATCH')
    validate_label(label)
    selected_policy = POLICY if policy is None else policy
    require(isinstance(selected_policy, dict) and isinstance(selected_policy.get('version'), str) and
            0 < len(selected_policy['version']) <= 96 and len(encoded(selected_policy)) <= 32*1024, 'LABEL_POLICY_INVALID')
    selected_policy = json.loads(encoded(selected_policy))
    policy_sha256 = digest(selected_policy)
    require(label['annotation']['policy_version'] == selected_policy['version'], 'LABEL_POLICY_VERSION_MISMATCH')
    source_version_sha256 = digest([source.get('source_version'), source.get('raw'), source.get('text')])
    identity = digest({'label': label, 'policy_sha256': policy_sha256, 'source_version_sha256': source_version_sha256})
    output = private_path(directory or DIRECTORY, create=True)
    keys = private_path(output / 'keys', create=True)
    marker = keys / (identity + '.json')
    if marker.exists():
        require(not marker.is_symlink(), 'LABEL_INDEX_UNSAFE')
        existing = json.loads(marker.read_bytes())
        previous = read_sidecar(existing['sidecar_ref'], source_ref=source_ref)
        require(previous['label'] == label and previous['policy_sha256'] == policy_sha256, 'LABEL_INDEX_MISMATCH')
        return existing['sidecar_ref']
    envelope = {'schema_version': 1, 'kind': 'information_label_sidecar',
                'label': label, 'policy_sha256': policy_sha256,
                'policy': selected_policy, 'source_version_sha256': source_version_sha256,
                'recorded_at': datetime.now(timezone.utc).isoformat(),
                'scope': 'annotation_only_not_evidence_admission'}
    ref = save(output, envelope)
    index_ref = save(keys, {'sidecar_ref': ref, 'annotation_id': identity})
    try:
        os.link(index_ref['path'], marker)
    except FileExistsError:
        require(not marker.is_symlink(), 'LABEL_INDEX_UNSAFE')
        existing = json.loads(marker.read_bytes())
        read_sidecar(existing['sidecar_ref'], source_ref=source_ref)
        return existing['sidecar_ref']
    return ref


def read_sidecar(ref, *, source_ref=None, loader=read):
    envelope = loader(ref)
    require(isinstance(envelope, dict) and envelope.get('kind') == 'information_label_sidecar', 'LABEL_SIDECAR_INVALID')
    require(envelope.get('policy_sha256') == digest(envelope.get('policy')), 'LABEL_POLICY_HASH_MISMATCH')
    label = envelope['label']; source = validate_label(label, loader=loader)
    require(label['annotation']['policy_version'] == envelope['policy'].get('version'), 'LABEL_POLICY_VERSION_MISMATCH')
    require(envelope['source_version_sha256'] == digest([source.get('source_version'), source.get('raw'), source.get('text')]), 'LABEL_VERSION_MISMATCH')
    require(source_ref is None or label['source_ref'] == source_ref, 'LABEL_SOURCE_BINDING_MISMATCH')
    return envelope


def source_refs(value, *, maximum=16):
    """Bound traversal of a report's artifact refs; no arbitrary string paths."""
    seen, found, pending, visited, artifact_reads, byte_count = set(), [], [value], 0, 0, 0
    while pending and len(found) < maximum and visited < 256:
        node = pending.pop(); visited += 1
        if isinstance(node, dict):
            if set(node) == {'path', 'sha256'}:
                key = node.get('sha256')
                if not isinstance(key, str) or key in seen: continue
                seen.add(key)
                try:
                    require(artifact_reads < 64, 'LABEL_READ_BUDGET')
                    path = private_path(node['path'])
                    byte_count += path.stat().st_size
                    require(byte_count <= 16 * 1024 * 1024, 'LABEL_BYTE_BUDGET')
                    artifact_reads += 1
                    child = read(node)
                    if isinstance(child, dict) and {'source_url', 'provider', 'raw'} <= child.keys():
                        found.append(node)
                    elif isinstance(child, (dict, list)): pending.append(child)
                except (SourceError, OSError, ValueError, TypeError): continue
            else: pending.extend(list(node.values())[:64])
        elif isinstance(node, list): pending.extend(node[:64])
    return found


def observe_report(report_ref, *, directory=None):
    """Opt-in bounded writer; callers must use the exception-isolated wrapper."""
    report = read(report_ref)
    refs = source_refs(report)
    return [annotate_source(ref, directory) for ref in refs]


def best_effort_observe(report_ref, *, observer=None):
    """Noncritical optional logging: observer failure cannot alter business status."""
    try:
        refs = (observer or observe_report)(report_ref)
        return {'status': 'recorded', 'sidecars': len(refs)}
    except Exception:
        return {'status': 'unavailable', 'code': 'OPTIONAL_OBSERVABILITY_FAILED'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['annotate', 'index-report'])
    parser.add_argument('--ref', required=True, help='JSON ArtifactRef, not a raw source path')
    args = parser.parse_args()
    try:
        ref = json.loads(args.ref)
        result = annotate_source(ref) if args.command == 'annotate' else best_effort_observe(ref)
        # CLI writer output is a hash receipt only; paths stay behind the boundary.
        print(json.dumps({'status': 'recorded', 'sha256': result['sha256']} if 'sha256' in result else result))
    except Exception:
        print(json.dumps({'status': 'unavailable', 'code': 'LABEL_WRITE_FAILED'}))
        raise SystemExit(1)


if __name__ == '__main__': main()
