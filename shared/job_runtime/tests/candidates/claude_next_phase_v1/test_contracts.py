import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import MappingProxyType
import unittest
from shared.job_runtime.candidates.claude_next_phase_v1 import IntegrationContractError, O1IdentityBindingV1
from ._support import identity, o1, raw, stack

class ContractTests(unittest.TestCase):
    def test_authenticated_summary_is_immutable(self):
        verifier, _ = stack(); item=identity("R6")
        summary=verifier._issue_authenticated_summary(raw("nominal.json"), identity=item, o1_binding=o1(item))
        with self.assertRaises(AttributeError): summary.other=True
        with self.assertRaises(TypeError): summary.value["http_status"]=500

    def test_summary_verifier_identity_is_pinned(self):
        first,_=stack(); second,_=stack(); item=identity("R6")
        summary=first._issue_authenticated_summary(raw("nominal.json"), identity=item, o1_binding=o1(item))
        from shared.job_runtime.candidates.claude_next_phase_v1 import adapt_authenticated_summary
        with self.assertRaises(IntegrationContractError): adapt_authenticated_summary(item, summary, verifier=second, o1_binding=o1(item))

    def test_state_attestation_is_linear_and_consumed(self):
        verifier,_=stack(); item=identity("R6")
        summary=verifier._issue_authenticated_summary(raw("nominal.json"), identity=item, o1_binding=o1(item))
        from shared.job_runtime.candidates.claude_next_phase_v1 import adapt_authenticated_summary
        result=adapt_authenticated_summary(item, summary, verifier=verifier, o1_binding=o1(item))
        old=result.state.to_mapping(); old["status"]="ready"
        from shared.job_runtime.candidates.claude_campaign_v1 import restore_state
        with self.assertRaises(Exception): restore_state(old, verifier=verifier, pinned_verifier=verifier)

    def test_summary_cannot_be_replayed(self):
        verifier,_=stack(); item=identity("R7")
        summary=verifier._issue_authenticated_summary(raw("pre-forward-502.json"), identity=item, o1_binding=o1(item))
        from shared.job_runtime.candidates.claude_next_phase_v1 import adapt_authenticated_summary
        adapt_authenticated_summary(item, summary, verifier=verifier, o1_binding=o1(item))
        with self.assertRaises(IntegrationContractError):
            adapt_authenticated_summary(item, summary, verifier=verifier, o1_binding=o1(item))

    def test_nested_summary_payload_is_recursively_immutable(self):
        verifier,_=stack(); item=identity("R7")
        summary=verifier._issue_authenticated_summary(raw("pre-forward-502.json"), identity=item, o1_binding=o1(item))
        with self.assertRaises(TypeError): summary.value["proof"]["signed"]="changed"

    def test_summary_copy_and_deepcopy_are_rejected(self):
        verifier,_=stack(); item=identity("R6")
        summary=verifier._issue_authenticated_summary(raw("nominal.json"), identity=item, o1_binding=o1(item))
        with self.assertRaises(TypeError): copy.copy(summary)
        with self.assertRaises(TypeError): copy.deepcopy(summary)

    def test_every_route_rejects_wrong_verifier_and_reuse(self):
        from shared.job_runtime.candidates.claude_next_phase_v1 import adapt_authenticated_summary
        for fixture,campaign in (("nominal.json","R6"),("pre-forward-502.json","R7"),
                                 ("forwarded-502.json","R8"),("cut.json","R8")):
            owner,_=stack(); wrong,_=stack(); item=identity(campaign)
            summary=owner._issue_authenticated_summary(raw(fixture), identity=item, o1_binding=o1(item))
            with self.assertRaises(IntegrationContractError):
                adapt_authenticated_summary(item,summary,verifier=wrong,o1_binding=o1(item))
            adapt_authenticated_summary(item,summary,verifier=owner,o1_binding=o1(item))
            with self.assertRaises(IntegrationContractError):
                adapt_authenticated_summary(item,summary,verifier=owner,o1_binding=o1(item))

    def test_result_contract_rejects_contradictory_tuples(self):
        from shared.job_runtime.candidates.claude_next_phase_v1 import IntegrationResultV1
        invalid=(("R6","unknown","none",1,1,False,True,None),
                 ("R7","retry_wait","restart",1,1,True,False,30),
                 ("R8","unknown","reconcile_only",1,1,True,True,None),
                 ("R6","succeeded","none",2,1,False,False,30))
        for args in invalid:
            with self.assertRaises(IntegrationContractError): IntegrationResultV1(*args,None,None)

    def test_full_identity_o1_and_evidence_commitments_reject_rebinding(self):
        verifier,_=stack(); item=identity("R6"); binding=o1(item)
        summary=verifier._issue_authenticated_summary(raw("nominal.json"), identity=item, o1_binding=binding)
        fields=("campaign_id","run_id","job_id","slot_id","attempt_id","operation_id","request_id",
                "prompt_id","gateway_id","process_id","prompt_sha256","source_sha256","config_sha256","version")
        for field in fields:
            rebound=object.__new__(type(item))
            for name in item.__dataclass_fields__: object.__setattr__(rebound,name,getattr(item,name))
            current=getattr(item,field)
            object.__setattr__(rebound,field,current+"-rebound" if type(current) is str else current+1)
            with self.assertRaises(IntegrationContractError):
                verifier.consume_summary(summary,identity=rebound,o1_binding=binding)
        for changed in (replace(binding,operation_id="other-operation"),
                        replace(binding,prompt_id="other-prompt"),
                        replace(binding,operation_binding_sha256="9"*64),
                        replace(binding,prompt_binding_sha256="a"*64)):
            with self.assertRaises(IntegrationContractError):
                verifier.consume_summary(summary,identity=item,o1_binding=changed)
        original=summary.value
        changed=dict(original); changed["http_status"]=201
        object.__setattr__(summary,"_value",MappingProxyType(changed))
        with self.assertRaises(IntegrationContractError):
            verifier.consume_summary(summary,identity=item,o1_binding=binding)
        object.__setattr__(summary,"_value",original)
        verifier.consume_summary(summary,identity=item,o1_binding=binding)

    def test_concurrent_and_subclass_verifier_identities_are_unique(self):
        def build(_):
            verifier,_=stack()
            return verifier.verifier_identity,verifier.generation_id,verifier.anchor_id
        with ThreadPoolExecutor(max_workers=8) as pool:
            values=list(pool.map(build,range(32)))
        self.assertEqual(len({item for triple in values for item in triple}),96)
        parent,_=stack()
        from shared.job_runtime.candidates.claude_next_phase_v1 import SameProcessIntegrationVerifier
        class ChildVerifier(SameProcessIntegrationVerifier): pass
        child=ChildVerifier(gateway_verifier=parent._gateway_verifier,expected_binding=parent._expected_binding)
        self.assertTrue(set((parent.verifier_identity,parent.generation_id,parent.anchor_id)).isdisjoint(
                            (child.verifier_identity,child.generation_id,child.anchor_id)))

    def test_o1_hashes_are_strict(self):
        with self.assertRaises(IntegrationContractError): O1IdentityBindingV1("op", "prompt", "x", "5"*64)

if __name__ == "__main__": unittest.main()
