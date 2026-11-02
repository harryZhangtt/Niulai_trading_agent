"""Small content-addressed bundles of registered public action source only.

Local code is immutable by convention/read-only modes and hash enforcement.
This is not an OS sandbox or an immutable third-party dependency environment.
"""
from copy import deepcopy
import ast
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from shared.research_sources.artifacts import ROOT, digest, encoded, private_path, read, save

GUARANTEE = 'immutable_local_code_bundle; pinned_interpreter_and_dependency_versions; no_adversarial_isolation'
SYNTHETIC_SHARED = b'"""Frozen registered-action package boundary."""\n'


def _error(code):
    from .runtime import ActionError
    raise ActionError(code)


def _relative(value):
    p = Path(value)
    if not isinstance(value, str) or p.is_absolute() or '..' in p.parts or not p.parts:
        _error('ACTION_RELEASE_PATH_INVALID')
    return p


def _hash(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        _error('ACTION_RELEASE_FILE_INVALID')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _paths(source_root):
    paths = [*Path(source_root, 'shared/actions').glob('*.py'),
        Path(source_root, 'shared/actions/contracts.json'),
        Path(source_root, 'shared/research_sources/__init__.py'),
        Path(source_root, 'shared/research_sources/fetch.py'),
        Path(source_root, 'shared/research_sources/artifacts.py'),
        Path(source_root, 'shared/research_sources/requirements.txt'),
        Path(source_root, 'shared/job_runtime/__init__.py'),
        Path(source_root, 'shared/job_runtime/business.py'), Path(source_root, 'shared/job_runtime/model.py'),
        Path(source_root, 'niulai/skills/investment-research-financial-services/references/niulai-workflow/scripts/evidence_crosscheck.py')]
    return {str(p.relative_to(source_root)): p for p in sorted(paths)}


def _descriptor(metadata, release_ref):
    result = deepcopy(metadata['descriptor'])
    manifest = metadata['manifest']
    return {**result, 'release_ref': deepcopy(release_ref), 'release_sha256': digest(manifest),
        'release_manifest': manifest,
        'schema_registry_ref': {'path': str(Path(metadata['bundle_directory']) / 'shared/actions/contracts.json'),
                                'sha256': manifest['files']['shared/actions/contracts.json']}}


def _frozen_descriptor(bundle, action_id):
    """Read the reviewed literal catalog without importing/executing frozen code.

    Legacy manifests hash runtime.py but did not include descriptor metadata.
    Its exact SPECS entry is therefore the authority for both old and new
    releases, independently of a later working-tree catalog or retirement.
    """
    try:
        tree = ast.parse((bundle / 'shared/actions/runtime.py').read_text(encoding='utf-8'))
        declarations = [node for node in tree.body if isinstance(node, ast.Assign)
                        and any(isinstance(target, ast.Name) and target.id == 'SPECS'
                                for target in node.targets)]
        if len(declarations) != 1 or len(declarations[0].targets) != 1:
            raise ValueError()
        specs = ast.literal_eval(declarations[0].value)
        selected = specs[action_id]
        if not isinstance(selected, dict):
            raise ValueError()
        return {'action_id': action_id, **selected}
    except (OSError, UnicodeError, SyntaxError, ValueError, TypeError, KeyError, RecursionError):
        _error('ACTION_RELEASE_DESCRIPTOR_INVALID')


def _publish_version(base, descriptor, release_sha256):
    """First complete publication owns an action/version within this catalog."""
    directory = private_path(base / 'published' / descriptor['action_id'], create=True)
    target = directory / (descriptor['version'] + '.json')
    raw = encoded({'action_id': descriptor['action_id'], 'version': descriptor['version'],
                   'release_sha256': release_sha256})
    fd, pending = tempfile.mkstemp(prefix='.version-', dir=directory)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        try:
            os.link(pending, target)
        except FileExistsError:
            if target.is_symlink() or not target.is_file() or target.stat().st_size != len(raw) or target.read_bytes() != raw:
                _error('ACTION_RELEASE_VERSION_REUSED')
        parent_fd = os.open(directory, os.O_RDONLY)
        try: os.fsync(parent_fd)
        finally: os.close(parent_fd)
    finally:
        os.unlink(pending)


def verify_release(release_ref, *, selector=None):
    """Verify containment, all frozen bytes and interpreter/dependency identity."""
    from . import runtime
    if (not isinstance(release_ref, dict) or set(release_ref) != {'path', 'sha256'}
            or not isinstance(release_ref['path'], str) or len(release_ref['path']) > 4096
            or not isinstance(release_ref['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', release_ref['sha256'])):
        _error('ACTION_RELEASE_REF_INVALID')
    metadata = runtime.decode(read(release_ref, json_value=False))
    required = {'schema_version', 'workspace_root', 'bundle_directory', 'descriptor', 'manifest'}
    if not isinstance(metadata, dict) or set(metadata) != required or metadata['schema_version'] != 1:
        _error('ACTION_RELEASE_METADATA_INVALID')
    if metadata['workspace_root'] != str(ROOT):
        _error('ACTION_RELEASE_WORKSPACE_MISMATCH')
    manifest = metadata['manifest']
    if (not isinstance(manifest, dict) or set(manifest) != {'schema_version', 'files', 'environment', 'action', 'guarantee'}
            or manifest['schema_version'] != 1 or manifest['guarantee'] != GUARANTEE):
        _error('ACTION_RELEASE_MANIFEST_INVALID')
    bundle = private_path(metadata['bundle_directory'])
    if bundle.name != digest(manifest) or not bundle.is_dir():
        _error('ACTION_RELEASE_DIRECTORY_INVALID')
    files = manifest['files']
    if not isinstance(files, dict) or not 10 <= len(files) <= 64:
        _error('ACTION_RELEASE_FILE_SET_INVALID')
    required_files = {'shared/__init__.py', 'shared/actions/runtime.py', 'shared/actions/releases.py',
        'shared/actions/frozen_worker.py', 'shared/actions/__init__.py', 'shared/actions/contracts.json',
        'shared/research_sources/artifacts.py', 'shared/research_sources/fetch.py',
        'shared/job_runtime/business.py', 'shared/job_runtime/model.py',
        'niulai/skills/investment-research-financial-services/references/niulai-workflow/scripts/evidence_crosscheck.py'}
    if not required_files <= set(files):
        _error('ACTION_RELEASE_FILE_SET_INVALID')
    for relative, expected in files.items():
        rel = _relative(relative)
        path = bundle / rel
        if any(p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(bundle)):
            _error('ACTION_RELEASE_SYMLINK_REJECTED')
        if _hash(path) != expected:
            _error('ACTION_RELEASE_HASH_MISMATCH')
    actual_files = {str(p.relative_to(bundle)) for p in bundle.rglob('*') if p.is_file()}
    if actual_files != set(files):
        _error('ACTION_RELEASE_FILE_SET_INVALID')
    if manifest['environment'] != runtime.environment_manifest():
        _error('ACTION_RELEASE_ENVIRONMENT_MISMATCH')
    spec = metadata['descriptor']
    keys = {'action_id', 'version', 'lifecycle', 'input_schema', 'output_schema', 'effects', 'retry_owner', 'capability', 'limits'}
    if (not isinstance(spec, dict) or set(spec) != keys or spec['lifecycle'] != 'active'
            or spec['action_id'] not in runtime.SPECS
            or not isinstance(spec['version'], str) or not re.fullmatch(r'\d+\.\d+\.\d+', spec['version'])
            or manifest['action'] != {'action_id': spec['action_id'], 'version': spec['version']}):
        _error('ACTION_RELEASE_DESCRIPTOR_INVALID')
    if encoded(spec) != encoded(_frozen_descriptor(bundle, spec['action_id'])):
        _error('ACTION_RELEASE_DESCRIPTOR_MISMATCH')
    if selector is not None:
        if not isinstance(selector, str) or '@' not in selector:
            _error('ACTION_SELECTOR_INVALID')
        action_id, version = selector.rsplit('@', 1)
        if action_id != spec['action_id'] or version not in ('1', spec['version']):
            _error('ACTION_RELEASE_ACTION_MISMATCH')
    return metadata


def freeze_release(selector, *, directory):
    """Resolve active source once and publish a read-only content bundle."""
    from . import runtime
    resolved = runtime.resolve(selector)
    source_root = runtime.SOURCE_ROOT
    paths = _paths(source_root)
    bytes_by_path = {relative: p.read_bytes() for relative, p in paths.items() if _hash(p)}
    bytes_by_path['shared/__init__.py'] = SYNTHETIC_SHARED
    if sum(len(x) for x in bytes_by_path.values()) > 8 * 1024 * 1024:
        _error('ACTION_RELEASE_TOO_LARGE')
    descriptor = {k: deepcopy(resolved[k]) for k in ('action_id', 'version', 'lifecycle', 'input_schema',
        'output_schema', 'effects', 'retry_owner', 'capability', 'limits')}
    manifest = {'schema_version': 1, 'files': {k: hashlib.sha256(v).hexdigest() for k, v in bytes_by_path.items()},
        'environment': runtime.environment_manifest(), 'action': {'action_id': descriptor['action_id'], 'version': descriptor['version']},
        'guarantee': GUARANTEE}
    # The capture must correspond to one verified source state, not a mixture.
    if runtime.manifest()['files'] != resolved['release_manifest']['files']:
        _error('ACTION_RELEASE_SOURCE_CHANGED')
    for relative, path in paths.items():
        if _hash(path) != manifest['files'][relative]:
            _error('ACTION_RELEASE_SOURCE_CHANGED')
    base = private_path(directory, create=True)
    bundles = private_path(base / 'bundles', create=True)
    target = bundles / digest(manifest)
    pending = Path(tempfile.mkdtemp(prefix='.release-', dir=bundles))
    try:
        for relative, raw in bytes_by_path.items():
            path = pending / _relative(relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            path.chmod(0o444)
        # Only complete source trees become visible under the release identity.
        try:
            if not target.exists():
                os.rename(pending, target)
        except OSError as error:
            if error.errno not in (errno.EEXIST, errno.ENOTEMPTY, errno.EACCES) or not target.is_dir():
                raise
        for path in sorted(target.rglob('*'), key=lambda p: len(p.parts), reverse=True):
            if path.is_dir(): path.chmod(0o555)
        target.chmod(0o555)
        fd = os.open(bundles, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        if pending.exists(): shutil.rmtree(pending)
    metadata = {'schema_version': 1, 'workspace_root': str(ROOT), 'bundle_directory': str(target),
                'descriptor': descriptor, 'manifest': manifest}
    release_ref = save(base, metadata)
    verify_release(release_ref, selector=selector)
    _publish_version(base, descriptor, digest(manifest))
    return _descriptor(metadata, release_ref)


def resolve_frozen(selector, release_ref):
    return _descriptor(verify_release(release_ref, selector=selector), release_ref)
