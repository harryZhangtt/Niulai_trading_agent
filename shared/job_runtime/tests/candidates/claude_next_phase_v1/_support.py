from __future__ import annotations
import json
from pathlib import Path
from types import SimpleNamespace

from shared.job_runtime.candidates.claude_campaign_v1 import CampaignIdentityV1
from shared.job_runtime.candidates.claude_loopback_gateway_v1 import ExpectedPreForwardBinding
from shared.job_runtime.candidates.claude_next_phase_v1 import O1IdentityBindingV1, SameProcessIntegrationVerifier

SHA = {
    "run": "1" * 64, "slot": "2" * 64, "attempt": "3" * 64,
    "operation": "4" * 64, "prompt_binding": "5" * 64,
    "prompt": "6" * 64, "source": "7" * 64, "config": "8" * 64,
}
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "claude_next_phase_v1"

class FakeGatewayVerifier:
    def __init__(self, binding): self.binding = binding; self.calls = 0; self.proofs = []
    def verify_and_consume(self, proof, *, expected_binding, request_ordinal):
        self.calls += 1; self.proofs.append((proof, expected_binding, request_ordinal))
        if proof != {"signed": "gateway", "ordinal": request_ordinal} or expected_binding is not self.binding:
            raise ValueError("bad gateway proof")
        return SimpleNamespace(binding=self.binding, status=502, upstream_attempts=0,
                               submission="not_submitted")

def identity(campaign, attempt="1", operation="1", request="1", process="1"):
    return CampaignIdentityV1(
        campaign_id=campaign, run_id=campaign.lower()+"-run", job_id="claude-campaign-v1.%s.slot-1" % campaign.lower(),
        slot_id="slot-1", attempt_id=campaign.lower()+"-attempt-"+attempt,
        operation_id=campaign.lower()+"-operation-"+operation, request_id=campaign.lower()+"-request-"+request,
        prompt_id=campaign.lower()+"-prompt", gateway_id="gateway-"+process, process_id="process-"+process,
        prompt_sha256=SHA["prompt"], source_sha256=SHA["source"], config_sha256=SHA["config"])

def stack():
    binding = ExpectedPreForwardBinding(
        run_binding_hash=SHA["run"], slot_binding_hash=SHA["slot"],
        attempt_binding_hash=SHA["attempt"], operation_binding_hash=SHA["operation"],
        prompt_binding_hash=SHA["prompt_binding"])
    gateway = FakeGatewayVerifier(binding)
    return SameProcessIntegrationVerifier(gateway_verifier=gateway, expected_binding=binding), gateway

def o1(item):
    return O1IdentityBindingV1(item.operation_id, item.prompt_id, SHA["operation"], SHA["prompt_binding"])

def raw(name):
    value=json.loads((FIXTURES/name).read_text())
    for key in ("campaign_id", "expected_route", "expected_status"): value.pop(key)
    value["proof"] = ({"signed":"gateway", "ordinal":value["request_ordinal"]}
                      if value["gateway_disposition"] == "rejected_before_forward" else None)
    return value
