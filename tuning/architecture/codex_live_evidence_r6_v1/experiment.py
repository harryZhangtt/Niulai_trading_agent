"""Architecture-owned provider-free R6 facade; intentionally no CLI entrypoint."""
from shared.job_runtime.candidates.codex_live_evidence_r6_v1.runner import run_synthetic
__all__ = ["run_synthetic"]
