"""Disabled provider-free Engine-result adapter for the frozen Fable A/B candidate."""
from .adapter import AdapterError, adapt_engine_provider_results, default_adapt
__all__ = ["AdapterError", "adapt_engine_provider_results", "default_adapt"]
