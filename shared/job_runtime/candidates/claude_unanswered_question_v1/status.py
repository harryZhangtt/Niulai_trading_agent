"""Non-authorizing capability status."""
from .contracts import CAPABILITY, CAPABILITY_STATUS, HOST_VERSION


def capability_status():
    return {
        "capability": CAPABILITY,
        "status": CAPABILITY_STATUS,
        "host_version_required": HOST_VERSION,
        "live_unanswered_question_fixture_present": False,
        "live_answer_ack_fixture_present": False,
        "synthetic_evidence_authoritative": False,
        "activation_authorized": False,
    }
