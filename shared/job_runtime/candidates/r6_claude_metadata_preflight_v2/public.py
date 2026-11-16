"""Only public API: two zero-argument, inert, hard-disabled entrypoints."""
from __future__ import annotations

from .constants import MODEL, STATUS


def _disabled(operation: str) -> dict:
    return {
        "version": 1,
        "operation": operation,
        "status": STATUS,
        "model": MODEL,
        "activation": False,
        "registered": False,
        "countable": False,
        "effects": {
            "account_status_reads": 0,
            "catalog_requests": 0,
            "inference": 0,
            "provider_processes": 0,
            "network": 0,
            "browser": 0,
            "mcp": 0,
            "bytedcli": 0,
        },
    }


def auth_readiness() -> dict:
    """Report disabled auth-readiness capability without I/O or execution."""
    return _disabled("auth_status")


def catalog_readiness() -> dict:
    """Report disabled catalog capability without I/O or execution."""
    return _disabled("model_catalog")
