"""Disabled, provider-free R6 final authority verifier.

The sole public operation returns a DENY report.  This package intentionally has
no writer, issuer, signer, installer, activation, or live-execution API.
"""
from .compiler import DENY, STATUS, compile_deny_report

__all__ = ["DENY", "STATUS", "compile_deny_report"]
