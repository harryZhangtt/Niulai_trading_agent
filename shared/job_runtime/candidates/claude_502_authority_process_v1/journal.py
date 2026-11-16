"""Append-only sanitized journal whose committed snapshots are authoritative."""
import copy, hashlib, hmac
from .canonical import dumps
from .contracts import DESIGN_SHA256
from .errors import UnknownOutcome

ZERO_HASH="0"*64
class SanitizedJournal:
    def __init__(self, signer): self._entries=[]; self._signer=signer; self.fail_next_append=False
    def append_commit(self,event,generation,session_id,request_sequence,timestamp,state_snapshot):
        if self.fail_next_append:
            self.fail_next_append=False
            raise UnknownOutcome("JOURNAL_APPEND_UNKNOWN")
        core={"commit":True,"design_sha256":DESIGN_SHA256,"event":event,"generation":generation,
              "journal_sequence":len(self._entries)+1,"previous_hash":self._entries[-1]["entry_hash"] if self._entries else ZERO_HASH,
              "request_sequence":request_sequence,"session_id":session_id,"state_snapshot":copy.deepcopy(state_snapshot),"timestamp":timestamp}
        digest=hashlib.sha256(dumps(core)).hexdigest(); entry=dict(core); entry["entry_hash"]=digest
        entry["authority_signature"]=self._signer({"design_sha256":DESIGN_SHA256,"kind":"journal_commit","entry_hash":digest})
        self._entries.append(entry); return copy.deepcopy(entry)
    def snapshot(self): return tuple(copy.deepcopy(self._entries))
    @staticmethod
    def verify(entries,key,generation):
        previous=ZERO_HASH
        for index,entry in enumerate(entries,1):
            if entry.get("commit") is not True or entry.get("design_sha256") != DESIGN_SHA256 or entry.get("generation") != generation: raise UnknownOutcome("JOURNAL_RECOVERY_INVALID")
            core={k:v for k,v in entry.items() if k not in ("entry_hash","authority_signature")}
            digest=hashlib.sha256(dumps(core)).hexdigest()
            expected=hmac.new(key,dumps({"design_sha256":DESIGN_SHA256,"kind":"journal_commit","entry_hash":digest}),hashlib.sha256).hexdigest()
            if entry.get("journal_sequence") != index or entry.get("previous_hash") != previous or entry.get("entry_hash") != digest or not hmac.compare_digest(entry.get("authority_signature",""),expected): raise UnknownOutcome("JOURNAL_RECOVERY_INVALID")
            previous=digest
        return copy.deepcopy(entries[-1]["state_snapshot"]) if entries else None
