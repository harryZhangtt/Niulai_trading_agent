from __future__ import annotations

import ast
import copy
import hashlib
from enum import IntEnum
import inspect
import json
import multiprocessing
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from jsonschema import Draft202012Validator, ValidationError, validators

from shared.job_runtime.candidates.r6_common_execution_window_v3 import window as w


class IntSubclass(int):
    pass


def exact_draft_validator(schema):
    checker = Draft202012Validator.TYPE_CHECKER.redefine(
        "integer", lambda unused_checker, value: type(value) is int and not isinstance(value, bool)
    )
    return validators.extend(Draft202012Validator, type_checker=checker)(schema)


def numeric_paths(value, prefix=()):
    paths=[]
    if type(value) is int and not isinstance(value,bool):
        paths.append(prefix)
    elif isinstance(value,dict):
        for key,item in value.items(): paths.extend(numeric_paths(item,prefix+(key,)))
    elif isinstance(value,list):
        for index,item in enumerate(value): paths.extend(numeric_paths(item,prefix+(index,)))
    return paths


def get_path(value,path):
    for part in path: value=value[part]
    return value


def mutate_numeric(value,path,replacement):
    result=copy.deepcopy(value); target=result
    for part in path[:-1]: target=target[part]
    target[path[-1]]=replacement
    if isinstance(result,dict) and "seal" in result and (not path or path[0] != "seal"):
        result=w._seal({key:item for key,item in result.items() if key != "seal"})
    return result


def schema_object_paths(schema,value,prefix=()):
    paths=[]
    if isinstance(value,dict):
        if schema.get("additionalProperties") is False: paths.append(prefix)
        props=schema.get("properties",{})
        for key,item in value.items():
            if key in props: paths.extend(schema_object_paths(props[key],item,prefix+(key,)))
    elif isinstance(value,list):
        prefix_items=schema.get("prefixItems",[])
        item_schema=schema.get("items") if isinstance(schema.get("items"),dict) else None
        for index,item in enumerate(value):
            child=prefix_items[index] if index < len(prefix_items) else item_schema
            if child is not None: paths.extend(schema_object_paths(child,item,prefix+(index,)))
    return paths


def mutate_extra(value,path):
    result=copy.deepcopy(value); target=result
    for part in path: target=target[part]
    target["unexpected_nested_extra"]=0
    if isinstance(result,dict) and "seal" in result and (not path or path[0] != "seal"):
        result=w._seal({key:item for key,item in result.items() if key != "seal"})
    return result


def fixture_receipt():
    start_wall = 1_700_000_000_000_000_000
    start_mono = 10_000_000_000
    jobs = []
    for index, cell in enumerate(w.CELL_ORDER):
        ch = "ABCD"[index]
        offset = w.ADMISSION_OFFSETS_SECONDS[index] * 1_000_000_000
        jobs.append({"ordinal":index+1,"cell_id":cell,"job_id":"job_"+ch*32,"slot_id":"slot_"+ch*32,"attempt_id":"attempt_"+ch*32,"operation_id":"operation_"+ch*32,"admission_deadline_utc_ns":start_wall+offset,"admission_deadline_monotonic_ns":start_mono+offset})
    pins = {name:{"path":path,"bytes":1,"sha256":"a"*64} for name,path in w.PIN_PATHS.items()}
    return w._seal({"version":"r6-common-execution-window-receipt-v3","status":"ISSUED","immutable":True,"block_id":"block_"+"B"*32,"window_id":"window_"+"W"*32,"root":w.RUNTIME_RELATIVE_ROOT.as_posix(),"block_duration_seconds":1800,"concurrency":1,"cell_order":list(w.CELL_ORDER),"start_utc_ns":start_wall,"deadline_utc_ns":start_wall+w.BLOCK_DURATION_NS,"start_monotonic_ns":start_mono,"deadline_monotonic_ns":start_mono+w.BLOCK_DURATION_NS,"clock_pair_span_ns":10,"issuer_pid":101,"issuer_process_token":"e"*64,"jobs":jobs,"template_sha256":"f"*64,"authority_pins":pins,"reissue_allowed":False,"extension_allowed":False,"replay_allowed":False})


def pair(receipt, seconds=1, wall_delta_ns=0):
    return w.ClockPair(receipt["start_utc_ns"]+seconds*1_000_000_000+wall_delta_ns, receipt["start_monotonic_ns"]+seconds*1_000_000_000, 10)


def claim_value(receipt, index, pid=701, token="1"*64, seconds=1):
    job=receipt["jobs"][index]; p=pair(receipt,seconds)
    return w._seal({"version":"r6-common-execution-window-claim-v3","decision":"ADMIT","window_id":receipt["window_id"],"ordinal":index+1,"cell_id":job["cell_id"],"job_id":job["job_id"],"slot_id":job["slot_id"],"attempt_id":job["attempt_id"],"operation_id":job["operation_id"],"concurrency":1,"replay_allowed":False,"claimant_pid":pid,"claimant_process_token":token,"claimed_utc_ns":p.wall_utc_ns,"claimed_monotonic_ns":p.monotonic_ns,"immutable":True})


def terminal_value(receipt, claim, state="PASS"):
    return w._seal({"version":"r6-common-execution-window-terminal-v3","window_id":receipt["window_id"],"ordinal":claim["ordinal"],"cell_id":claim["cell_id"],"job_id":claim["job_id"],"slot_id":claim["slot_id"],"attempt_id":claim["attempt_id"],"operation_id":claim["operation_id"],"claim_sha256":w._sha256(w.canonical_bytes(claim)),"terminal_state":state,"immutable":True})


def exclusive_worker(root, start, queue):
    try:
        root_fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            start.wait(10)
            w._write_exclusive_fd(root_fd,w.CLAIM_NAMES[0],b'{"exclusive":true}')
            queue.put("CREATED")
        finally: os.close(root_fd)
    except BaseException as exc:
        queue.put(getattr(exc,"code",type(exc).__name__))


def process_token_worker(queue):
    queue.put((os.getpid(), w._get_process_token()))


def receipt_recovery_worker(parent, start, queue):
    try:
        start.wait(15)
        root=os.open(pathlib.Path(parent)/w.RUNTIME_RELATIVE_ROOT.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            value=w._recover_receipt_fd(root)
            queue.put(("AUTHORIZED",value["window_id"]))
        finally: os.close(root)
    except BaseException as exc:
        queue.put(("DENY",getattr(exc,"code",type(exc).__name__)))


def race_worker(parent, receipt, start, queue, token):
    try:
        parent_fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            root_fd=w._create_or_open_root(parent_fd,w.RUNTIME_RELATIVE_ROOT.name)
            try:
                recovered=w._recover_receipt_fd(root_fd)
                start.wait(10)
                value=w._claim_at(root_fd,recovered,pair(receipt),current_pid=os.getpid(),process_token=token)
                queue.put(("ADMIT",value["ordinal"]))
            finally: os.close(root_fd)
        finally: os.close(parent_fd)
    except BaseException as exc:
        queue.put(("DENY",getattr(exc,"code",type(exc).__name__)))


class WindowV3Tests(unittest.TestCase):
    def setUp(self):
        self.receipt=fixture_receipt()

    def assertCode(self, code, fn, *args, **kwargs):
        with self.assertRaises(w.WindowError) as caught: fn(*args,**kwargs)
        self.assertEqual(code,caught.exception.code)

    def env(self):
        temp=tempfile.TemporaryDirectory(); parent=pathlib.Path(temp.name)/"runtime"; parent.mkdir(mode=0o700)
        parent_fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        w._publish_receipt_at(parent_fd,self.receipt)
        root_fd=w._create_or_open_root(parent_fd,w.RUNTIME_RELATIVE_ROOT.name)
        return temp,parent,parent_fd,root_fd

    def put(self, root_fd, name, value):
        raw=w.canonical_bytes(value)
        if name in w.CLAIM_NAMES:
            w._publish_slot(root_fd,"claim",w.CLAIM_NAMES.index(name),raw)
        elif name in w.TERMINAL_NAMES:
            w._publish_slot(root_fd,"terminal",w.TERMINAL_NAMES.index(name),raw)
        else:
            w._write_exclusive_fd(root_fd,name,raw)

    def test_public_disabled_gate_precedes_pin_io_clock_token_ids_and_runtime_io(self):
        funcs=(w.issue_live_window,w.recover_live_window,w.validate_live_window,w.admit_next_cell)
        for fn in funcs:
            with self.subTest(fn=fn.__name__), mock.patch.object(w,"_open_workspace_fd",side_effect=AssertionError("pin io")), mock.patch.object(w,"_trusted_clock_pair",side_effect=AssertionError("clock")), mock.patch.object(w,"_get_process_token",side_effect=AssertionError("token")), mock.patch.object(w,"_new_id",side_effect=AssertionError("id")), mock.patch.object(w,"_open_runtime_parent_fd",side_effect=AssertionError("runtime io")):
                self.assertCode(w.STATUS,fn)
        self.assertEqual([],list(inspect.signature(w.issue_live_window).parameters))
        self.assertEqual([],list(inspect.signature(w.admit_next_cell).parameters))
        with self.assertRaises(TypeError): w.admit_next_cell(root="/tmp")

    def test_import_makes_no_clock_entropy_or_token_call(self):
        code="import time,secrets; time.time_ns=lambda:(_ for _ in ()).throw(RuntimeError('time')); time.monotonic_ns=lambda:(_ for _ in ()).throw(RuntimeError('mono')); secrets.token_hex=lambda *a:(_ for _ in ()).throw(RuntimeError('entropy')); import shared.job_runtime.candidates.r6_common_execution_window_v3.window as w; assert w._PROCESS_INSTANCE_TOKEN is None"
        run=subprocess.run([sys.executable,"-c",code],cwd=w.WORKSPACE_ROOT,text=True,capture_output=True)
        self.assertEqual(0,run.returncode,run.stderr)
        tree=ast.parse(pathlib.Path(w.__file__).read_text())
        module_calls=[]
        for node in tree.body:
            if isinstance(node,(ast.Assign,ast.AnnAssign)):
                for child in ast.walk(node):
                    if isinstance(child,ast.Call) and isinstance(child.func,ast.Attribute) and child.func.attr in {"time_ns","monotonic_ns","token_hex","token_urlsafe"}: module_calls.append(child.func.attr)
        self.assertEqual([],module_calls)

    def test_template_and_all_draft_schemas_are_strict(self):
        value=w.prepare_window_template(); self.assertEqual(w.STATUS,value["status"]); self.assertFalse(value["activation"])
        self.assertEqual([450,900,1350,1800],value["admission_offsets_seconds"])
        self.assertEqual(0o600,stat.S_IMODE(os.stat(w.TEMPLATE_PATH).st_mode))
        schemas={p.name:json.loads(p.read_text()) for p in (w.TEMPLATE_PATH.parent/"schemas").glob("*.json")}
        self.assertEqual(6,len(schemas))
        for schema in schemas.values():
            self.assertEqual("https://json-schema.org/draft/2020-12/schema",schema["$schema"]); self.assertFalse(schema["additionalProperties"])
            Draft202012Validator.check_schema(schema)
        Draft202012Validator(schemas["window-template-v3.schema.json"]).validate(value)
        Draft202012Validator(schemas["window-receipt-v3.schema.json"]).validate(self.receipt)
        c=claim_value(self.receipt,0); t=terminal_value(self.receipt,c)
        Draft202012Validator(schemas["admission-claim-v3.schema.json"]).validate(c)
        Draft202012Validator(schemas["terminal-receipt-v3.schema.json"]).validate(t)
        Draft202012Validator(schemas["slot-commit-v3.schema.json"]).validate(w._slot_marker(w.CLAIM_NAMES[0],w.canonical_bytes(c)))
        bad=dict(c); bad["extra"]=1
        with self.assertRaises(ValidationError): Draft202012Validator(schemas["admission-claim-v3.schema.json"]).validate(bad)

    def test_pin_chain_missing_hash_mode_owner_and_coherent_fake_reject(self):
        with tempfile.TemporaryDirectory() as td:
            workspace=pathlib.Path(td); wsfd=os.open(workspace,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:
                name="g1"; rel=w.PIN_PATHS[name]; target=workspace/rel; target.parent.mkdir(parents=True,mode=0o700)
                for p in list(target.parents)[:-1]:
                    if p.is_relative_to(workspace): os.chmod(p,0o700)
                ref={"path":rel,"bytes":1,"sha256":"0"*64}
                self.assertCode("PIN_G1_MISSING",w._verify_activation_pin,wsfd,name,ref)
                fake={"immutable":True,"role":w.PIN_ROLES[name],"status":"APPROVED","subject":"r6_common_execution_window_v1","version":"r6-common-execution-window-activation-pin-v3"}
                raw=w.canonical_bytes(fake); target.write_bytes(raw); os.chmod(target,0o600); ref={"path":rel,"bytes":len(raw),"sha256":w._sha256(raw)}
                self.assertCode("PIN_G1_SUBJECT",w._verify_activation_pin,wsfd,name,ref)
                fake["subject"]="r6_common_execution_window_v3"; fake["status"]="OPEN"; raw=w.canonical_bytes(fake); target.write_bytes(raw); ref={"path":rel,"bytes":len(raw),"sha256":w._sha256(raw)}
                self.assertCode("PIN_G1_STATUS",w._verify_activation_pin,wsfd,name,ref)
                fake["status"]="APPROVED"; raw=w.canonical_bytes(fake); target.write_bytes(raw); os.chmod(target,0o644); ref={"path":rel,"bytes":len(raw),"sha256":w._sha256(raw)}
                self.assertCode("PIN_G1_MODE",w._verify_activation_pin,wsfd,name,ref)
                os.chmod(target,0o600); bad=dict(ref); bad["sha256"]="f"*64
                self.assertCode("PIN_G1_HASH",w._verify_activation_pin,wsfd,name,bad)
                self.assertEqual(ref,w._verify_activation_pin(wsfd,name,ref))
                backing=target.with_name("backing.json"); backing.write_bytes(raw); os.chmod(backing,0o600); target.unlink(); target.symlink_to(backing)
                self.assertCode("PIN_G1_MISSING",w._verify_activation_pin,wsfd,name,ref)
            finally: os.close(wsfd)

    def test_parent_swap_cannot_redirect_child_creation_or_publication(self):
        with tempfile.TemporaryDirectory() as td:
            base=pathlib.Path(td); parent=base/"runtime"; parent.mkdir(mode=0o700); moved=base/"held-runtime"; replacement=base/"runtime"
            parent_fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            def swap():
                os.rename(parent,moved); replacement.mkdir(mode=0o700)
            try: recovered=w._publish_receipt_at(parent_fd,self.receipt,before_open=swap)
            finally: os.close(parent_fd)
            self.assertEqual(self.receipt,recovered)
            self.assertTrue((moved/w.RUNTIME_RELATIVE_ROOT.name/w.MARKER_NAME).is_file())
            self.assertFalse((replacement/w.RUNTIME_RELATIVE_ROOT.name).exists())

    def test_forked_process_gets_distinct_lazy_process_token(self):
        w._PROCESS_INSTANCE_TOKEN=None; w._PROCESS_INSTANCE_PID=None
        parent_pid=os.getpid(); parent_token=w._get_process_token()
        ctx=multiprocessing.get_context("fork"); queue=ctx.Queue(); proc=ctx.Process(target=process_token_worker,args=(queue,))
        proc.start(); child_pid,child_token=queue.get(timeout=15); proc.join(15)
        self.assertEqual(0,proc.exitcode); self.assertNotEqual(parent_pid,child_pid); self.assertNotEqual(parent_token,child_token)

    def test_fixed_child_swap_is_detected_and_never_redirects_publication(self):
        with tempfile.TemporaryDirectory() as td:
            parent=pathlib.Path(td)/"runtime"; parent.mkdir(mode=0o700); moved=parent/"created-root"
            pfd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            def swap_child():
                os.rename(parent/w.RUNTIME_RELATIVE_ROOT.name,moved)
                (parent/w.RUNTIME_RELATIVE_ROOT.name).mkdir(mode=0o700)
            try:
                self.assertCode("ROOT_BINDING",w._publish_receipt_at,pfd,self.receipt,before_open=swap_child)
            finally: os.close(pfd)
            self.assertTrue((moved/w.MARKER_NAME).is_file())
            self.assertFalse((parent/w.RUNTIME_RELATIVE_ROOT.name/w.MARKER_NAME).exists())

    def test_true_multiprocess_admission_race_has_one_admit(self):
        temp,parent,parent_fd,root_fd=self.env(); os.close(root_fd); os.close(parent_fd)
        try:
            ctx=multiprocessing.get_context("fork"); start=ctx.Event(); queue=ctx.Queue()
            ps=[ctx.Process(target=race_worker,args=(str(parent),self.receipt,start,queue,ch*64)) for ch in ("1","2")]
            for p in ps: p.start()
            start.set()
            results=[queue.get(timeout=15) for _ in ps]
            for p in ps: p.join(15); self.assertEqual(0,p.exitcode)
            self.assertEqual(1,sum(r[0]=="ADMIT" for r in results),results)
            self.assertEqual(1,sum(r[0]=="DENY" for r in results),results)
            root=os.open(parent/w.RUNTIME_RELATIVE_ROOT.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:
                state=w._scan_namespace(root,self.receipt); self.assertIsNotNone(state.active_claim); self.assertEqual(1,state.active_claim["ordinal"])
            finally: os.close(root)
        finally: temp.cleanup()

    def test_true_multiprocess_exclusive_create_has_one_winner(self):
        temp,parent,pfd,rfd=self.env(); os.close(rfd); os.close(pfd)
        try:
            root=parent/w.RUNTIME_RELATIVE_ROOT.name
            ctx=multiprocessing.get_context("fork"); start=ctx.Event(); queue=ctx.Queue()
            ps=[ctx.Process(target=exclusive_worker,args=(str(root),start,queue)) for _ in range(2)]
            for proc in ps: proc.start()
            start.set(); results=[queue.get(timeout=15) for _ in ps]
            for proc in ps: proc.join(15); self.assertEqual(0,proc.exitcode)
            self.assertEqual(1,results.count("CREATED"),results)
            self.assertEqual(1,results.count("ARTIFACT_EXISTS"),results)
        finally: temp.cleanup()

    def test_replay_restart_and_pid_reuse_are_denied_after_exact_reconciliation(self):
        temp,parent,pfd,rfd=self.env()
        try:
            c=w._claim_at(rfd,self.receipt,pair(self.receipt),current_pid=77,process_token="1"*64)
            self.assertEqual("ADMIT",c["decision"])
            self.assertCode("CONCURRENCY_ONE_ACTIVE",w._claim_at,rfd,self.receipt,pair(self.receipt),current_pid=77,process_token="1"*64)
            self.assertCode("PID_REUSE_UNKNOWN",w._claim_at,rfd,self.receipt,pair(self.receipt),current_pid=77,process_token="2"*64)
            self.assertCode("ACTIVE_PROCESS_RESTART_UNKNOWN",w._claim_at,rfd,self.receipt,pair(self.receipt),current_pid=78,process_token="3"*64)
        finally: os.close(rfd); os.close(pfd); temp.cleanup()

    def test_all_claim_terminal_gap_classes_and_malformed_later_slots_fence(self):
        cases=[]
        for index in range(4): cases.append((index,"terminal_only")); cases.append((index,"claim_only"))
        for index,kind in cases:
            with self.subTest(index=index,kind=kind):
                temp,parent,pfd,rfd=self.env()
                try:
                    c=claim_value(self.receipt,index)
                    if kind=="terminal_only": self.put(rfd,w.TERMINAL_NAMES[index],terminal_value(self.receipt,c))
                    else: self.put(rfd,w.CLAIM_NAMES[index],c)
                    if index==0 and kind=="claim_only":
                        state=w._scan_namespace(rfd,self.receipt); self.assertEqual(1,state.active_claim["ordinal"])
                    else:
                        self.assertCode("NAMESPACE_LATER_ARTIFACT" if kind=="claim_only" else "NAMESPACE_TERMINAL_WITHOUT_CLAIM",w._scan_namespace,rfd,self.receipt)
                finally: os.close(rfd); os.close(pfd); temp.cleanup()
        for index in range(4):
            with self.subTest(malformed=index):
                temp,parent,pfd,rfd=self.env()
                try:
                    w._publish_slot(rfd,"claim",index,b"{}")
                    self.assertCode("CLAIM_FIELDS",w._scan_namespace,rfd,self.receipt)
                finally: os.close(rfd); os.close(pfd); temp.cleanup()

    def test_incomplete_earlier_claim_rejects_every_later_pair_and_unknown_later(self):
        for later in (1,2,3):
            with self.subTest(later=later):
                temp,parent,pfd,rfd=self.env()
                try:
                    c0=claim_value(self.receipt,0); self.put(rfd,w.CLAIM_NAMES[0],c0)
                    c=claim_value(self.receipt,later); self.put(rfd,w.CLAIM_NAMES[later],c); self.put(rfd,w.TERMINAL_NAMES[later],terminal_value(self.receipt,c))
                    self.assertCode("NAMESPACE_LATER_ARTIFACT",w._scan_namespace,rfd,self.receipt)
                finally: os.close(rfd); os.close(pfd); temp.cleanup()
        temp,parent,pfd,rfd=self.env()
        try:
            c0=claim_value(self.receipt,0); self.put(rfd,w.CLAIM_NAMES[0],c0); self.put(rfd,w.TERMINAL_NAMES[0],terminal_value(self.receipt,c0,"UNKNOWN"))
            c1=claim_value(self.receipt,1); self.put(rfd,w.CLAIM_NAMES[1],c1)
            self.assertCode("NAMESPACE_LATER_ARTIFACT",w._scan_namespace,rfd,self.receipt)
        finally: os.close(rfd); os.close(pfd); temp.cleanup()

    def test_receipt_refs_bind_exact_verified_template_and_pins(self):
        bad=copy.deepcopy(self.receipt); bad["authority_pins"]["g1"]["bytes"]=0; bad=w._seal({k:v for k,v in bad.items() if k!="seal"})
        self.assertCode("WINDOW_AUTHORITY_BYTES",w._validate_live_receipt,bad)
        bad=copy.deepcopy(self.receipt); bad["authority_pins"]["g1"]["sha256"]="not-a-hash"; bad=w._seal({k:v for k,v in bad.items() if k!="seal"})
        self.assertCode("WINDOW_AUTHORITY_HASH",w._validate_live_receipt,bad)
        template=w.prepare_window_template(); pins=copy.deepcopy(self.receipt["authority_pins"])
        bound=copy.deepcopy(self.receipt); bound["template_sha256"]=template["seal"]["sha256"]; bound["authority_pins"]=pins; bound=w._seal({k:v for k,v in bound.items() if k!="seal"})
        w._validate_receipt_binding(bound,template,pins)
        other=copy.deepcopy(pins); other["g1"]["bytes"]=2
        self.assertCode("WINDOW_AUTHORITY_BINDING",w._validate_receipt_binding,bound,template,other)
        wrong=copy.deepcopy(template); wrong["seal"]={"bytes":1,"sha256":"0"*64}
        self.assertCode("WINDOW_TEMPLATE_BINDING",w._validate_receipt_binding,bound,wrong,pins)

    def test_recovered_claim_time_must_be_within_deadline_and_clock_consistent(self):
        temp,parent,pfd,rfd=self.env()
        try:
            late=claim_value(self.receipt,0,seconds=1801); self.put(rfd,w.CLAIM_NAMES[0],late)
            self.assertCode("CLAIM_WALL_DEADLINE",w._scan_namespace,rfd,self.receipt)
        finally: os.close(rfd); os.close(pfd); temp.cleanup()
        temp,parent,pfd,rfd=self.env()
        try:
            drift=claim_value(self.receipt,0); body={k:v for k,v in drift.items() if k!="seal"}; body["claimed_utc_ns"]+=w.WALL_MONOTONIC_MAX_DRIFT_NS+1; drift=w._seal(body); self.put(rfd,w.CLAIM_NAMES[0],drift)
            self.assertCode("CLAIM_CLOCK_DRIFT",w._scan_namespace,rfd,self.receipt)
        finally: os.close(rfd); os.close(pfd); temp.cleanup()

    def test_terminal_consumes_exact_claim_once_and_advances_once(self):
        temp,parent,pfd,rfd=self.env()
        try:
            c=w._claim_at(rfd,self.receipt,pair(self.receipt),current_pid=77,process_token="1"*64)
            t=w._publish_terminal_at(rfd,self.receipt,"PASS",current_pid=77,process_token="1"*64)
            self.assertEqual(w._sha256(w.canonical_bytes(c)),t["claim_sha256"])
            state=w._scan_namespace(rfd,self.receipt); self.assertEqual(1,state.next_index); self.assertIsNone(state.active_claim)
            self.assertCode("NO_ACTIVE_CLAIM",w._publish_terminal_at,rfd,self.receipt,"PASS",current_pid=77,process_token="1"*64)
            c2=w._claim_at(rfd,self.receipt,pair(self.receipt),current_pid=77,process_token="1"*64); self.assertEqual(2,c2["ordinal"])
        finally: os.close(rfd); os.close(pfd); temp.cleanup()

    def test_claim_short_zero_fsync_crash_and_restart_are_fail_closed(self):
        temp,parent,pfd,rfd=self.env()
        try:
            short=lambda fd,data: os.write(fd,data[:7])
            c=w._claim_at(rfd,self.receipt,pair(self.receipt),current_pid=77,process_token="1"*64,write_fn=short); self.assertEqual(1,c["ordinal"])
        finally: os.close(rfd); os.close(pfd); temp.cleanup()
        for stage in ("created","written","file_fsynced","parent_fsynced","reopened"):
            with self.subTest(stage=stage):
                temp,parent,pfd,rfd=self.env()
                try:
                    self.assertCode("INJECTED_CRASH_"+stage.upper(),w._claim_at,rfd,self.receipt,pair(self.receipt),current_pid=77,process_token="1"*64,crash_after=stage)
                    with self.assertRaises(w.WindowError): w._claim_at(rfd,self.receipt,pair(self.receipt),current_pid=77,process_token="1"*64)
                finally: os.close(rfd); os.close(pfd); temp.cleanup()
        temp,parent,pfd,rfd=self.env()
        try:
            self.assertCode("WRITE_ZERO_OR_INVALID",w._claim_at,rfd,self.receipt,pair(self.receipt),current_pid=77,process_token="1"*64,write_fn=lambda fd,data:0)
            with self.assertRaises(w.WindowError): w._scan_namespace(rfd,self.receipt)
        finally: os.close(rfd); os.close(pfd); temp.cleanup()
        temp,parent,pfd,rfd=self.env()
        try:
            with mock.patch.object(w,"_fsync_file",side_effect=OSError("fsync")):
                with self.assertRaises(OSError): w._claim_at(rfd,self.receipt,pair(self.receipt),current_pid=77,process_token="1"*64)
            self.assertCode("INCOMPLETE_CLAIM_1",w._scan_namespace,rfd,self.receipt)
            self.assertCode("INCOMPLETE_CLAIM_1",w._publish_terminal_at,rfd,self.receipt,"PASS",current_pid=77,process_token="1"*64)
            self.assertCode("INCOMPLETE_CLAIM_1",w._claim_at,rfd,self.receipt,pair(self.receipt),current_pid=77,process_token="1"*64)
        finally: os.close(rfd); os.close(pfd); temp.cleanup()

    def test_slot_parent_fsync_failure_never_authorizes_dependent_transition(self):
        temp,parent,pfd,rfd=self.env()
        try:
            original=w._fsync_dir
            def fail_claim(fd,boundary):
                if boundary=="claim_1_data_publish": raise OSError("parent fsync")
                return original(fd,boundary)
            with mock.patch.object(w,"_fsync_dir",side_effect=fail_claim):
                with self.assertRaises(OSError): w._claim_at(rfd,self.receipt,pair(self.receipt),current_pid=77,process_token="1"*64)
            self.assertCode("INCOMPLETE_CLAIM_1",w._publish_terminal_at,rfd,self.receipt,"PASS",current_pid=77,process_token="1"*64)
        finally: os.close(rfd); os.close(pfd); temp.cleanup()
        temp,parent,pfd,rfd=self.env()
        try:
            w._claim_at(rfd,self.receipt,pair(self.receipt),current_pid=77,process_token="1"*64)
            original=w._fsync_dir
            def fail_terminal(fd,boundary):
                if boundary=="terminal_1_marker_publish": raise OSError("parent fsync")
                return original(fd,boundary)
            with mock.patch.object(w,"_fsync_dir",side_effect=fail_terminal):
                with self.assertRaises(OSError): w._publish_terminal_at(rfd,self.receipt,"PASS",current_pid=77,process_token="1"*64)
            self.assertCode("INCOMPLETE_TERMINAL_1",w._claim_at,rfd,self.receipt,pair(self.receipt),current_pid=77,process_token="1"*64)
        finally: os.close(rfd); os.close(pfd); temp.cleanup()

    def test_receipt_recovery_is_locked_before_marker_parent_fsync(self):
        with tempfile.TemporaryDirectory() as td:
            parent=pathlib.Path(td)/"runtime"; parent.mkdir(mode=0o700); pfd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            ctx=multiprocessing.get_context("fork"); start=ctx.Event(); queue=ctx.Queue(); proc=ctx.Process(target=receipt_recovery_worker,args=(str(parent),start,queue)); proc.start()
            observed=[]
            def before_fsync():
                start.set(); observed.append(queue.get(timeout=15))
            try:
                recovered=w._publish_receipt_at(pfd,self.receipt,before_marker_parent_fsync=before_fsync)
                self.assertEqual(self.receipt,recovered)
            finally:
                os.close(pfd); proc.join(15)
            self.assertEqual(0,proc.exitcode); self.assertEqual([("DENY","NAMESPACE_BUSY")],observed)

    def test_receipt_marker_parent_fsync_failure_fences_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            parent=pathlib.Path(td)/"runtime"; parent.mkdir(mode=0o700); pfd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            original=w._fsync_dir
            def fail_marker(fd,boundary):
                if boundary=="marker_publish": raise OSError("marker parent fsync")
                return original(fd,boundary)
            try:
                with mock.patch.object(w,"_fsync_dir",side_effect=fail_marker):
                    with self.assertRaises(OSError): w._publish_receipt_at(pfd,self.receipt)
                rfd=w._create_or_open_root(pfd,w.RUNTIME_RELATIVE_ROOT.name)
                try: self.assertCode("INCOMPLETE_WINDOW_NO_REISSUE",w._recover_receipt_fd,rfd)
                finally: os.close(rfd)
                self.assertCode("SINGLE_ISSUANCE_ONLY",w._publish_receipt_at,pfd,self.receipt)
            finally: os.close(pfd)

    def test_receipt_marker_last_crash_recovery_short_and_fsync(self):
        for stage in ("receipt_created","receipt_written","receipt_file_fsynced","receipt_parent_fsynced","receipt_reopened","receipt_published","marker_created","marker_written","marker_file_fsynced","marker_parent_fsynced","marker_reopened"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as td:
                parent=pathlib.Path(td)/"runtime"; parent.mkdir(mode=0o700); pfd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
                try:
                    with self.assertRaises(w.WindowError): w._publish_receipt_at(pfd,self.receipt,crash_after=stage)
                    rfd=w._create_or_open_root(pfd,w.RUNTIME_RELATIVE_ROOT.name)
                    try:
                        if stage.startswith("marker_") and stage not in {"marker_created","marker_written","marker_file_fsynced","marker_parent_fsynced","marker_reopened"}:
                            self.assertEqual(self.receipt,w._recover_receipt_fd(rfd))
                        else:
                            with self.assertRaises(w.WindowError): w._recover_receipt_fd(rfd)
                    finally: os.close(rfd)
                finally: os.close(pfd)
        with tempfile.TemporaryDirectory() as td:
            parent=pathlib.Path(td)/"runtime"; parent.mkdir(mode=0o700); pfd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:
                recovered=w._publish_receipt_at(pfd,self.receipt,write_fn=lambda fd,data:os.write(fd,data[:9])); self.assertEqual(self.receipt,recovered)
                self.assertCode("SINGLE_ISSUANCE_ONLY",w._publish_receipt_at,pfd,self.receipt)
            finally: os.close(pfd)

    def test_terminal_short_zero_fsync_crash_and_restart_are_fail_closed(self):
        temp,parent,pfd,rfd=self.env()
        try:
            w._claim_at(rfd,self.receipt,pair(self.receipt),current_pid=77,process_token="1"*64)
            short=lambda fd,data: os.write(fd,data[:5])
            t=w._publish_terminal_at(rfd,self.receipt,"PASS",current_pid=77,process_token="1"*64,write_fn=short)
            self.assertEqual("PASS",t["terminal_state"])
        finally: os.close(rfd); os.close(pfd); temp.cleanup()
        for stage in ("created","written","file_fsynced","parent_fsynced","reopened"):
            with self.subTest(stage=stage):
                temp,parent,pfd,rfd=self.env()
                try:
                    w._claim_at(rfd,self.receipt,pair(self.receipt),current_pid=77,process_token="1"*64)
                    self.assertCode("INJECTED_CRASH_"+stage.upper(),w._publish_terminal_at,rfd,self.receipt,"PASS",current_pid=77,process_token="1"*64,crash_after=stage)
                    with self.assertRaises(w.WindowError): w._publish_terminal_at(rfd,self.receipt,"PASS",current_pid=77,process_token="1"*64)
                finally: os.close(rfd); os.close(pfd); temp.cleanup()
        temp,parent,pfd,rfd=self.env()
        try:
            w._claim_at(rfd,self.receipt,pair(self.receipt),current_pid=77,process_token="1"*64)
            self.assertCode("WRITE_ZERO_OR_INVALID",w._publish_terminal_at,rfd,self.receipt,"PASS",current_pid=77,process_token="1"*64,write_fn=lambda fd,data:0)
            with self.assertRaises(w.WindowError): w._scan_namespace(rfd,self.receipt)
        finally: os.close(rfd); os.close(pfd); temp.cleanup()
        temp,parent,pfd,rfd=self.env()
        try:
            w._claim_at(rfd,self.receipt,pair(self.receipt),current_pid=77,process_token="1"*64)
            with mock.patch.object(w,"_fsync_file",side_effect=OSError("fsync")):
                with self.assertRaises(OSError): w._publish_terminal_at(rfd,self.receipt,"PASS",current_pid=77,process_token="1"*64)
            self.assertCode("INCOMPLETE_TERMINAL_1",w._scan_namespace,rfd,self.receipt)
            self.assertCode("INCOMPLETE_TERMINAL_1",w._claim_at,rfd,self.receipt,pair(self.receipt),current_pid=77,process_token="1"*64)
            self.assertCode("INCOMPLETE_TERMINAL_1",w._publish_terminal_at,rfd,self.receipt,"PASS",current_pid=77,process_token="1"*64)
        finally: os.close(rfd); os.close(pfd); temp.cleanup()

    def test_commit_marker_published_is_recoverable_after_crash(self):
        with tempfile.TemporaryDirectory() as td:
            parent=pathlib.Path(td)/"runtime"; parent.mkdir(mode=0o700); pfd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:
                self.assertCode("INJECTED_CRASH_MARKER_PUBLISHED",w._publish_receipt_at,pfd,self.receipt,crash_after="marker_published")
                rfd=w._create_or_open_root(pfd,w.RUNTIME_RELATIVE_ROOT.name)
                try: self.assertEqual(self.receipt,w._recover_receipt_fd(rfd))
                finally: os.close(rfd)
                self.assertCode("SINGLE_ISSUANCE_ONLY",w._publish_receipt_at,pfd,self.receipt)
            finally: os.close(pfd)

    def test_clock_deadline_rollback_jump_and_unknown_fence(self):
        w._validate_clock(self.receipt,pair(self.receipt,0))
        self.assertCode("MONOTONIC_ROLLBACK_OR_REBOOT",w._validate_clock,self.receipt,w.ClockPair(self.receipt["start_utc_ns"],self.receipt["start_monotonic_ns"]-1,1))
        self.assertCode("WALL_CLOCK_JUMP",w._validate_clock,self.receipt,pair(self.receipt,1,2_000_000_000))
        temp,parent,pfd,rfd=self.env()
        try:
            edge=pair(self.receipt,450); c=w._claim_at(rfd,self.receipt,edge,current_pid=77,process_token="1"*64); self.assertEqual(1,c["ordinal"])
        finally: os.close(rfd); os.close(pfd); temp.cleanup()
        temp,parent,pfd,rfd=self.env()
        try:
            past=w.ClockPair(self.receipt["start_utc_ns"]+450_000_000_001,self.receipt["start_monotonic_ns"]+450_000_000_001,1)
            self.assertCode("CELL_MONOTONIC_DEADLINE",w._claim_at,rfd,self.receipt,past,current_pid=77,process_token="1"*64)
        finally: os.close(rfd); os.close(pfd); temp.cleanup()

    def artifact_validator_matrix(self):
        schemas={path.name:json.loads(path.read_text()) for path in (w.TEMPLATE_PATH.parent/"schemas").glob("*.json")}
        template=w.prepare_window_template(); claim=claim_value(self.receipt,0); terminal=terminal_value(self.receipt,claim)
        claim_raw=w.canonical_bytes(claim); receipt_raw=w.canonical_bytes(self.receipt)
        slot=w._slot_marker(w.CLAIM_NAMES[0],claim_raw)
        commit={"version":"r6-common-execution-window-commit-v3","receipt":w.RECEIPT_NAME,"receipt_bytes":len(receipt_raw),"receipt_sha256":w._sha256(receipt_raw),"committed":True}
        return {
            "window-template-v3.schema.json":(template,w._validate_template),
            "window-receipt-v3.schema.json":(self.receipt,w._validate_live_receipt),
            "admission-claim-v3.schema.json":(claim,lambda value:w._validate_claim(value,self.receipt,0)),
            "terminal-receipt-v3.schema.json":(terminal,lambda value:w._validate_terminal(value,self.receipt,claim,0)),
            "slot-commit-v3.schema.json":(slot,lambda value:w._validate_slot_marker(value,w.CLAIM_NAMES[0],claim_raw)),
            "commit-marker-v3.schema.json":(commit,lambda value:w._validate_receipt_marker(value,receipt_raw)),
        },schemas

    def test_all_numeric_fields_exact_int_property_matrix_matches_exact_draft(self):
        matrix,schemas=self.artifact_validator_matrix(); exercised=0
        for schema_name,(valid,runtime_validate) in matrix.items():
            schema=schemas[schema_name]; exact=exact_draft_validator(schema)
            with self.subTest(schema=schema_name,case="valid"):
                exact.validate(valid); runtime_validate(valid)
            paths=numeric_paths(valid)
            self.assertGreater(len(paths),0,schema_name)
            for path in paths:
                current=get_path(valid,path)
                enum_value=IntEnum("Probe_"+str(exercised),{"VALUE":current}).VALUE
                variants={"bool":bool(current or 1),"integral_float":float(current),"IntEnum":enum_value,"int_subclass":IntSubclass(current),"negative":-1,"overflow":w.MAX_WIRE_INT+1}
                for kind,replacement in variants.items():
                    exercised+=1; mutated=mutate_numeric(valid,path,replacement)
                    with self.subTest(schema=schema_name,path=path,kind=kind):
                        self.assertTrue(list(exact.iter_errors(mutated)),"exact Draft-derived schema accepted invalid numeric")
                        with self.assertRaises(w.WindowError): runtime_validate(mutated)
        self.assertGreaterEqual(exercised,300)

    def test_stock_draft_number_semantics_are_explicit_and_application_is_stricter(self):
        stock=Draft202012Validator({"type":"integer","minimum":0,"maximum":w.MAX_WIRE_INT})
        exact=exact_draft_validator({"type":"integer","minimum":0,"maximum":w.MAX_WIRE_INT})
        enum_one=IntEnum("One",{"VALUE":1}).VALUE
        for value in (1,): self.assertFalse(list(stock.iter_errors(value))); self.assertFalse(list(exact.iter_errors(value)))
        for value in (True,False,1.5,-1,w.MAX_WIRE_INT+1):
            self.assertTrue(list(stock.iter_errors(value))); self.assertTrue(list(exact.iter_errors(value)))
        for value in (1.0,enum_one,IntSubclass(1)):
            self.assertFalse(list(stock.iter_errors(value)),type(value).__name__)
            self.assertTrue(list(exact.iter_errors(value)),type(value).__name__)
            self.assertFalse(w._is_exact_int(value),type(value).__name__)

    def test_nested_extras_reject_across_every_schema_and_runtime_validator(self):
        matrix,schemas=self.artifact_validator_matrix(); exercised=0
        for schema_name,(valid,runtime_validate) in matrix.items():
            schema=schemas[schema_name]; exact=exact_draft_validator(schema)
            paths=schema_object_paths(schema,valid)
            self.assertGreater(len(paths),0,schema_name)
            for path in paths:
                exercised+=1; mutated=mutate_extra(valid,path)
                with self.subTest(schema=schema_name,path=path):
                    self.assertTrue(list(exact.iter_errors(mutated)))
                    with self.assertRaises(w.WindowError): runtime_validate(mutated)
        self.assertGreaterEqual(exercised,20)

    def test_marker_bound_boolean_receipt_claim_terminal_reject_before_authority(self):
        bad_receipt=copy.deepcopy(self.receipt); bad_receipt["jobs"][0]["ordinal"]=True; bad_receipt=w._seal({k:v for k,v in bad_receipt.items() if k!="seal"})
        with tempfile.TemporaryDirectory() as td:
            parent=pathlib.Path(td)/"runtime"; parent.mkdir(mode=0o700); pfd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:
                self.assertCode("WINDOW_JOB_ORDINAL",w._publish_receipt_at,pfd,bad_receipt)
                self.assertFalse((parent/w.RUNTIME_RELATIVE_ROOT.name).exists())
            finally: os.close(pfd)
        temp,parent,pfd,rfd=self.env()
        try:
            claim=claim_value(self.receipt,0); claim["ordinal"]=True; claim=w._seal({k:v for k,v in claim.items() if k!="seal"}); self.put(rfd,w.CLAIM_NAMES[0],claim)
            self.assertCode("CLAIM_ORDINAL",w._scan_namespace,rfd,self.receipt)
            self.assertCode("CLAIM_ORDINAL",w._publish_terminal_at,rfd,self.receipt,"PASS",current_pid=701,process_token="1"*64)
        finally: os.close(rfd); os.close(pfd); temp.cleanup()
        temp,parent,pfd,rfd=self.env()
        try:
            claim=claim_value(self.receipt,0); self.put(rfd,w.CLAIM_NAMES[0],claim)
            terminal=terminal_value(self.receipt,claim); terminal["ordinal"]=True; terminal=w._seal({k:v for k,v in terminal.items() if k!="seal"}); self.put(rfd,w.TERMINAL_NAMES[0],terminal)
            self.assertCode("TERMINAL_ORDINAL",w._scan_namespace,rfd,self.receipt)
            self.assertCode("TERMINAL_ORDINAL",w._claim_at,rfd,self.receipt,pair(self.receipt),current_pid=701,process_token="1"*64)
        finally: os.close(rfd); os.close(pfd); temp.cleanup()

    def test_internal_indices_clock_pids_and_write_counters_require_plain_bounded_ints(self):
        aliases=(True,1.0,IntEnum("IndexOne",{"VALUE":1}).VALUE,IntSubclass(1),-1,w.MAX_WIRE_INT+1)
        claim=claim_value(self.receipt,0); terminal=terminal_value(self.receipt,claim)
        for value in aliases:
            with self.subTest(surface="slot_index",value=repr(value)): self.assertCode("SLOT_KIND_INDEX",w._slot_names,"claim",value)
            with self.subTest(surface="claim_index",value=repr(value)): self.assertCode("CLAIM_INDEX",w._validate_claim,claim,self.receipt,value)
            with self.subTest(surface="terminal_index",value=repr(value)): self.assertCode("TERMINAL_INDEX",w._validate_terminal,terminal,self.receipt,claim,value)
            with self.subTest(surface="current_pid",value=repr(value)):
                self.assertCode("CLAIM_CURRENT_PID",w._claim_at,-1,self.receipt,pair(self.receipt),current_pid=value,process_token="1"*64)
                self.assertCode("TERMINAL_CURRENT_PID",w._publish_terminal_at,-1,self.receipt,"PASS",current_pid=value,process_token="1"*64)
        clock_variants=(
            w.ClockPair(True,1,1),w.ClockPair(1,1.0,1),w.ClockPair(1,1,IntSubclass(1)),
            w.ClockPair(-1,1,1),w.ClockPair(1,w.MAX_WIRE_INT+1,1),w.ClockPair(1,1,w.CLOCK_PAIR_MAX_SPAN_NS+1))
        for pair_value in clock_variants:
            with self.subTest(clock=pair_value):
                with self.assertRaises(w.WindowError): w._validate_clock(self.receipt,pair_value)
        with tempfile.TemporaryDirectory() as td:
            path=pathlib.Path(td)/"x"; fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            try:
                for returned in (True,1.0,IntSubclass(1),-1,w.MAX_WIRE_INT+1):
                    with self.subTest(write_count=repr(returned)): self.assertCode("WRITE_ZERO_OR_INVALID",w._full_write,fd,b"x",lambda unused_fd,unused_raw,returned=returned:returned)
            finally: os.close(fd)

    def test_v1_v2_history_and_open_reviews_match_frozen_hashes(self):
        baseline=json.loads((w.WORKSPACE_ROOT/"tuning/architecture/r6_common_execution_window_v3/v2-preservation-baseline.json").read_text())
        self.assertEqual("r6-common-execution-window-v2-preservation-baseline-for-v3",baseline["version"]); self.assertGreaterEqual(len(baseline["members"]),30)
        for entry in baseline["members"]:
            raw=(w.WORKSPACE_ROOT/entry["path"]).read_bytes(); self.assertEqual(entry["bytes"],len(raw),entry["path"]); self.assertEqual(entry["sha256"],hashlib.sha256(raw).hexdigest(),entry["path"])
        review_path=w.WORKSPACE_ROOT/"mentor/runtime/scheduler-midresponse-recovery-20261107/r6-common-execution-window-v2-fourth-independent-review-open-fable-20261115-8e9a8076.json"
        review=json.loads(review_path.read_text()); self.assertEqual("OPEN",review["outcome"]); self.assertEqual("EW-V2-OPEN-004-001",review["findings"][0]["id"])


if __name__ == "__main__": unittest.main()
