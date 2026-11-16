"""Sanitized candidate exceptions; supplied values are never rendered."""
class AuthorityError(Exception):
    def __init__(self,code): self.code=code; super().__init__(code)
class ProtocolError(AuthorityError): pass
class UnknownOutcome(AuthorityError): pass
class CrashSimulated(UnknownOutcome): pass
class PreSendFailure(AuthorityError):
    """Explicit evidence that no request byte was handed to the transport."""
