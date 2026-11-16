"""Inert data contracts for proposed visible Claude sessions.

Importing this package performs no I/O and exposes no execution adapter.
"""

from .contracts import (
    ContractError,
    load_frozen_cases,
    validate_case,
    validate_cli_placeholder,
    validate_evidence_bundle,
    validate_fixture_payloads,
)

__all__ = [
    "ContractError",
    "load_frozen_cases",
    "validate_case",
    "validate_cli_placeholder",
    "validate_evidence_bundle",
    "validate_fixture_payloads",
]
