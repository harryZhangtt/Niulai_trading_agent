"""Disabled provider-free R6 Claude metadata-preflight candidate."""
from .public import auth_readiness, catalog_readiness

__all__ = ["auth_readiness", "catalog_readiness"]
