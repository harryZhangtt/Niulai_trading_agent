"""Disabled, provider-free authority-process protocol candidate.

The package is intentionally inert: it binds no socket, starts no process, reads
no environment, and exposes no command-line entry point.
"""
from .authority import Authority, AuthorityClient, CrashPoint, ManualClock
from .errors import AuthorityError, CrashSimulated, PreSendFailure, ProtocolError, UnknownOutcome
from .framing import FrameDecoder, encode_frame
from .transport import MemoryTransport

ENABLED = False
CAPABILITY_OPEN = False
LIVE = False
PRODUCTION = False
PROVIDER_CALLS_AUTHORIZED = False
DESIGN_CONTRACT_SHA256 = "74599835c69be8598cb4a4b9d5a3a7fee1d19e43195405bda608fe5befbb13a3"
DESIGN_CONTRACT_BYTES = 5161

__all__ = (
    "Authority", "AuthorityClient", "AuthorityError", "CrashPoint",
    "CrashSimulated", "FrameDecoder", "ManualClock", "MemoryTransport",
    "PreSendFailure", "ProtocolError", "UnknownOutcome", "encode_frame",
)
