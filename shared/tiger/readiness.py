"""Read-only, credential-free readiness projection for the canonical agent."""
from pathlib import Path

def local_readiness(workspace):
    fence=Path(workspace).resolve()/'.niulai-state'/'tiger'/'unresolved.json'
    if fence.exists() or fence.is_symlink():
        return {'status':'blocked','code':'TIGER_PRIOR_OUTCOME_REQUIRES_RECONCILIATION'}
    return {'status':'waiting_for_host','code':'NATIVE_SERVICE_ACCESS_REQUIRED'}
