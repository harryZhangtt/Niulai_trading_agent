from __future__ import annotations
from dataclasses import dataclass
from .contracts import AnswerDecision, ContractError
from .ledger import AnswerLedger
@dataclass
class SyntheticFakeHost:
    fault:str="none";submit_count:int=0;acknowledgements:int=0
    def submit(self,decision:AnswerDecision)->bool:
        self.submit_count+=1
        if self.fault=="during_submit_unknown":raise RuntimeError("synthetic outcome unknown")
        return self.fault!="after_submit_before_ack"
def synthetic_roundtrip(decision,ledger,host,*,crash="none"):
    current=ledger.state_for(decision)
    if current is not None:return current
    if crash=="before_submit":raise RuntimeError("synthetic crash before submit")
    try:ledger.begin_submit(decision)
    except ContractError as error:
        if error.code=="ANSWER_NO_REPLAY_FENCE":
            current=ledger.state_for(decision)
            if current is not None:return current
        raise
    try:ack=host.submit(decision)
    except BaseException:ledger.mark_unknown(decision);return "UNKNOWN"
    if crash=="after_submit" or not ack:ledger.mark_unknown(decision);return "UNKNOWN"
    ledger.acknowledge(decision);host.acknowledgements+=1
    if crash=="after_ack":raise RuntimeError("synthetic crash after ack")
    return "ACKED"
