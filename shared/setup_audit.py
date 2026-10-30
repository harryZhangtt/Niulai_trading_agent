"""Require portable setup documentation to track declared setup sources."""
import argparse,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
LOCK=ROOT/'docs/deployment/setup-lock.json'
DOCS=['docs/local-setup.md','docs/deployment/*.md','docs/deployment/setup-inventory.json','shared/tiger/README.md','investment/research/README.md','shared/research_sources/README.md']
SOURCE=['.codex/config.toml','shared/job_runtime/*.py','shared/job_runtime/*requirements.txt',
'niulai-runtime/niulai_runtime/*.py','niulai-runtime/jobs/*','niulai-runtime/config/*','niulai-runtime/requirements.txt',
'shared/market_data_mcp/*.py','shared/market_data_mcp/*.mjs','shared/market_data_mcp/*.json','shared/market_data_mcp/*.toml',
'shared/market_data_mcp/auth/*.mjs','shared/market_data_mcp/adapters/*.mjs','shared/market_data_mcp/core/*.mjs',
'shared/tiger/*.py','shared/tiger/config/*.json',
'mentor/tests/requirements.txt','tuning/evals/*/requirements.txt','shared/setup_audit.py']

def snapshot(patterns):
    values={}
    for pattern in patterns:
        for p in ROOT.glob(pattern):
            if p.is_file() and not p.is_symlink() and 'node_modules' not in p.parts:
                values[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
    return dict(sorted(values.items()))

def main():
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--check',action='store_true');g.add_argument('--refresh',action='store_true');a=p.parse_args()
    inventory=ROOT/'docs/deployment/setup-inventory.json'
    declared=json.loads(inventory.read_text()).get('setup_sensitive_source_paths_for_consistency_gate',[]) if inventory.exists() else []
    patterns=sorted(set(SOURCE+declared))
    sources=snapshot(patterns);docs=snapshot(DOCS)
    required={'docs/local-setup.md','docs/deployment/job-runtime.md','docs/deployment/niulai.md','docs/deployment/shared-and-tuning.md','docs/deployment/frontend.md','docs/deployment/setup-inventory.json'}
    if not required<=docs.keys():print('SETUP_DOCUMENTATION_INCOMPLETE');return 2
    current={'schema_version':1,'source_patterns':patterns,'documentation_patterns':DOCS,'sources':sources,'documentation':docs}
    previous=json.loads(LOCK.read_text()) if LOCK.exists() else None
    if a.check:
        if previous!=current:print('SETUP_DOC_SYNC_REQUIRED');return 2
        print('SETUP_DOC_SYNC_OK');return 0
    if previous and previous['sources']!=sources and previous['documentation']==docs:
        print('SETUP_DOC_UPDATE_REQUIRED_BEFORE_REFRESH');return 2
    LOCK.write_text(json.dumps(current,indent=2)+'\n');print('SETUP_DOC_FINGERPRINT_UPDATED');return 0

if __name__=='__main__':raise SystemExit(main())
