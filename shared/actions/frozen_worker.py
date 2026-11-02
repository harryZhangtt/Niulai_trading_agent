"""Isolated bootstrap for a verified registered release; no working-tree imports."""
import hashlib
import json
from pathlib import Path
import sys


def main():
    # Parent has already verified this bootstrap and all files before execution.
    # Python -I removes cwd/PYTHONPATH; only the frozen public package is added.
    ref_path, ref_sha, workspace = sys.argv[1:]
    root = Path(workspace).resolve(strict=True)
    raw = Path(ref_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref_sha:
        raise ValueError('ACTION_RELEASE_METADATA_HASH')
    metadata = json.loads(raw)
    bundle = Path(__file__).resolve().parents[2]
    if metadata.get('workspace_root') != str(root) or metadata.get('bundle_directory') != str(bundle):
        raise ValueError('ACTION_RELEASE_CONTEXT_MISMATCH')
    for relative, expected in metadata['manifest']['files'].items():
        rel = Path(relative)
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError('ACTION_RELEASE_PATH_INVALID')
        p = bundle / rel
        if p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise ValueError('ACTION_RELEASE_HASH_MISMATCH')
    sys.path.insert(0, str(bundle))
    from shared.research_sources import artifacts
    # Trusted data root is independent of the frozen code root.
    artifacts.ROOT = root
    artifacts.SOURCE_STATE = root / '.niulai-state/reports/research-sources'
    artifacts.INVESTMENT_STATE = root / '.niulai-state/reports/investment-research'
    artifacts.STATE_ROOTS = (artifacts.SOURCE_STATE, artifacts.INVESTMENT_STATE, root / '.research-sources', root / 'investment/runtime')
    artifacts.READ_ROOTS = (*artifacts.STATE_ROOTS, root / '.niulai-state/reports')
    from shared.actions import runtime
    runtime.FROZEN_CONTEXT = {'manifest': metadata['manifest'], 'release_ref': {'path': ref_path, 'sha256': ref_sha}}
    from shared.actions.releases import verify_release
    verify_release(runtime.FROZEN_CONTEXT['release_ref'])
    envelope = runtime.decode(sys.stdin.buffer.read(runtime.MAX_REQUEST_BYTES + 1))
    if not isinstance(envelope, dict) or set(envelope) != {'request', 'output_directory'}:
        raise ValueError('ACTION_WORKER_ENVELOPE_INVALID')
    if envelope['request'].get('release_ref') != runtime.FROZEN_CONTEXT['release_ref']:
        raise ValueError('ACTION_RELEASE_REQUEST_MISMATCH')
    result = runtime.dispatch(envelope['request'], output_directory=envelope['output_directory'])
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
