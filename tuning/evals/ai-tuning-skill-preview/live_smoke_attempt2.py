"""Explicitly authorized follow-up; preserve the pre-dispatch denied attempt."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('smoke_attempt2_base', HERE / 'live_smoke_v1.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)

if __name__ == '__main__':
    prior = smoke.runtime.strict_load(smoke.STATE / 'final-results-v1.json')
    smoke.require(prior['status'] == 'local_pass_live_permission_blocked', 'PRIOR_STATE_CHANGED')
    smoke.require(prior['native_model_calls'] == 0 and prior['new_cost_usd'] == 0
                  and prior['unresolved_new_cost_usd'] == 0, 'PRIOR_RECONCILIATION_REQUIRED')
    smoke.require(not list((smoke.STATE / 'native').glob('*.intent.json')),
                  'PRIOR_DISPATCH_INTENT_FOUND')
    smoke.STATE = smoke.STATE / 'attempt2'
    result = smoke.main(live=True)
    raise SystemExit(0 if result['status'] == 'six_call_development_smoke_passed' else 2)
