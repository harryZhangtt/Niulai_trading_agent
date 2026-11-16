"""Disabled, provider-free validation for R6 human grader attestations."""
from .registry import ContractError, validate_registry_attestations

__all__ = ["ContractError", "validate_registry_attestations"]
