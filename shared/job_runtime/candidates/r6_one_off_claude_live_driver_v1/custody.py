"""Raw owner-private payload builder; publication owns fsynced staging."""
from .contracts import canonical_bytes
def payloads(process_receipt):
    raw=b'{"type":"fake.completed"}\n' if process_receipt["terminal_state"]=="exact" else b'{"type":"fake.partial"'
    err=canonical_bytes(process_receipt["nested_error"])
    return {"stdout.raw":raw,"stderr.raw":err,"process-receipt.json":canonical_bytes(process_receipt)}
