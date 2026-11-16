"""Injected process group fake receiving and echoing an immutable launch spec."""
from __future__ import annotations
from .contracts import MODEL,validate_process_receipt
class FakeProcess:
    def __init__(self,fault="none"):self.fault=fault;self.starts=0;self.receipt_value=None
    def start(self,spec,readback):
        self.starts+=1;timeout=self.fault=="timeout";bad_cleanup=self.fault in ("cleanup","process_loss");term=self.fault in ("terminal","truncation","timeout","process_loss","parser","path_swap","secret","launch_echo")
        x={"version":1,"starts":1,"terminations":1 if timeout else 0,"kills":1 if timeout else 0,"reaps":0 if bad_cleanup else 1,"descriptors_closed":2,"launch_spec_digest_echo":"0"*64 if self.fault=="launch_echo" else spec["digest"],"binary_sha256":spec["binary"]["sha256"],"argv_sha256":spec["argv"]["sha256"],"shell":spec["shell"],"env_allowlist":list(spec["env_allowlist"]),"config_sha256":spec["config"]["sha256"],"catalog_sha256":spec["catalog"]["sha256"],"model":spec["model"],"prompt_sha256":spec["prompt"]["sha256"],"process_group":spec["process_group"],"deadline_seconds":spec["deadline_seconds"],"terminate_policy":spec["terminate"],"kill_policy":spec["kill"],"reap_policy":spec["reap"],"output_identity":"swapped/output" if self.fault=="path_swap" else "owner/stdout.raw","parser_identity":"wrong_parser" if self.fault=="parser" else "claude_terminal_v1","terminal_state":"truncated" if term else "exact","exit_code":None if term else 0,"nested_error":{"present":self.fault=="secret","code":"credential_value=synthetic" if self.fault=="secret" else "NONE"}}
        validate_process_receipt(x);self.receipt_value=x;return x
    def receipt(self):return None if self.receipt_value is None else dict(self.receipt_value)
