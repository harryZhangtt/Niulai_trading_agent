"""Architecture-owned provider-free experiment facade; no CLI entrypoint."""
from shared.job_runtime.candidates.provider_free_lifecycle_v1.runner import run_provider_free_experiment
__all__=["run_provider_free_experiment"]
