"""Disabled, provider-free R6 evidence candidate; imports perform no I/O."""
from .contracts import CALL_BUDGET, DESIGN_SHA256, REVIEW_SHA256, R6ContractError
from .runner import run_synthetic
__all__ = ["CALL_BUDGET", "DESIGN_SHA256", "REVIEW_SHA256", "R6ContractError", "run_synthetic"]
