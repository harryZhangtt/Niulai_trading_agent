"""Independent offline OR/REC-C controls. Never reads real policy/fence/context."""
from contextlib import redirect_stdout, redirect_stderr, contextmanager
from copy import deepcopy
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from urllib import error, request

from shared.tiger import reconciliation as client
from shared.tiger.bridge import TigerBridgeError

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = Path(__file__).parent / '.runtime'
WORKER = ROOT / '.niulai-state/reports/trading-agent-smoke/53cbbf3b-1c8f-48c8-af34-f621bec276d6/owner-source-supported/.sites-checkout/worker/index.js'
COMMIT = '11111111-1111-4111-8111-111111111111'
LEASE = '22222222-2222-4222-8222-222222222222'
OTHER = '33333333-3333-4333-8333-333333333333'
CANARY = 'SYNTHETIC-BEARER-DO-NOT-EXPORT'
MUTATIONS = []


def encoded(value): return json.dumps(value, separators=(',', ':')).encode()


def health(**overrides):
    return {'schema': 1, 'initialized': True, 'revision': 7, 'lease_busy': False,
            'last_committed_at': '2023-11-14T22:00:00+00:00', **overrides}


def ack(**overrides):
    return {'committed': True, 'revision': 7, 'idempotent': True, 'released': True, **overrides}


class Response:
    def __init__(self, value=None, *, raw=None, status=200, hook=None):
        self.raw = encoded(value) if raw is None else raw
        self.status, self.hook, self.read_sizes, self.closed = status, hook, [], False
    def __enter__(self): return self
    def __exit__(self, *_): self.close()
    def close(self): self.closed = True
    def read(self, size):
        self.read_sizes.append(size)
        if self.hook: self.hook()
        return self.raw[:size]


class Opener:
    def __init__(self, replies=None):
        self.replies = list(replies) if replies is not None else [Response(health()), Response(ack())]
        self.calls = []
    def open(self, req, timeout):
        self.calls.append({'url': req.full_url, 'method': req.method, 'data': req.data,
                           'headers': dict(req.header_items()), 'timeout': timeout})
        if not self.replies: raise AssertionError('unexpected retry/network attempt')
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException): raise reply
        return reply


@contextmanager
def altered(old, new):
    original = Path(client.__file__).read_bytes()
    source = original.decode(); assert source.count(old) == 1
    name = 'shared.tiger._independent_reconciliation'
    module = types.ModuleType(name); module.__file__ = client.__file__; module.__package__ = 'shared.tiger'
    previous = sys.modules.get(name); sys.modules[name] = module
    try:
        exec(compile(source.replace(old, new), client.__file__, 'exec'), module.__dict__)
        yield module
    finally:
        if previous is None: sys.modules.pop(name, None)
        else: sys.modules[name] = previous
        assert Path(client.__file__).read_bytes() == original


class ClientControls(unittest.TestCase):
    def setUp(self):
        base = RUNTIME / 'tmp'; base.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.tmp = tempfile.TemporaryDirectory(dir=base, prefix='client-independent-')
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name)
        self.private = self.workspace / '.niulai-state'
        self.state = self.private / 'tiger'; self.state.mkdir(parents=True, mode=0o700)
        self.source = self.private / 'source' / 'index.js'
        self.put(self.source, WORKER.read_bytes())
        self.fence = self.state / 'unresolved.json'
        self.fence_value = {'phase': 'checkpoint', 'automatic_retry': False, 'attempt_id': LEASE,
                            'commit_id': COMMIT, 'private_canary': CANARY}
        self.put(self.fence, encoded(self.fence_value)); self.original = self.fence.read_bytes()
        self.lock = self.state / 'bridge.lock'; self.put(self.lock, b'')
        self.profile = self.state / 'profile' / 'private.json'; self.put(self.profile, encoded({'canary': CANARY}))
        self.policy = {'project_id': 'synthetic-project', 'origin': 'https://fixture.chatgpt.site',
                       'owner_email': 'owner@example.invalid'}
        self.put(self.private / 'config' / 'tiger.json', encoded(self.policy))
        owner = {'email': self.policy['owner_email'], 'role': 'owner', 'is_external': False,
                 'pending': False, 'account_user_id': 'synthetic-user'}
        self.context = {'site': {'id': self.policy['project_id'], 'current_user_role': 'owner', 'status': 'active',
            'current_live_url': self.policy['origin'], 'access_mode': 'custom', 'latest_version_number': 1,
            'siwc_bypass_bearer_token': CANARY, 'access_policy': {'access_mode': 'custom',
            'project_id': self.policy['project_id'], 'allowed_users': [owner],
            'allowed_account_user_ids': ['synthetic-user'], 'allowed_groups': [],
            'allowed_workspace_group_ids': [], 'allowed_tenant_group_ids': [],
            'external_visitor_count': 0, 'allowed_editors': []}},
            'version': {'id': client.VERSION_ID, 'project_id': self.policy['project_id'], 'version_number': 1,
            'source': {'commit_sha': client.SOURCE_COMMIT}, 'deployment_id': client.DEPLOYMENT_ID},
            'deployment': {'id': client.DEPLOYMENT_ID, 'project_id': self.policy['project_id'],
            'version_id': client.VERSION_ID, 'status': 'succeeded', 'failure_message': None}}
    def put(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(value); path.chmod(0o600)
    def diagnose(self, opener=None, module=client, context=None):
        return module.diagnose(self.workspace, self.policy, context or self.context, self.source,
                               opener=opener or Opener())
    def reject(self, action, code='READBACK_'):
        with self.assertRaisesRegex(TigerBridgeError, code): action()
    def held(self):
        fd = os.open(self.lock, os.O_RDONLY); fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.addCleanup(os.close, fd); return fd
    def lock_free(self):
        fd = os.open(self.lock, os.O_RDONLY)
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally: os.close(fd)

    def test_exact_two_routes_original_ids_body_bounds_and_no_private_mutation(self):
        opener = Opener(); profile = self.profile.read_bytes(); result = self.diagnose(opener)
        self.assertEqual([(r['method'], r['url']) for r in opener.calls],
            [('GET', self.policy['origin'] + '/health'), ('POST', self.policy['origin'] + '/lease/checkpoint')])
        self.assertIsNone(opener.calls[0]['data'])
        self.assertEqual(json.loads(opener.calls[1]['data']), {'commit_id': COMMIT, 'lease_id': LEASE})
        self.assertTrue(all(r['timeout'] == 15 for r in opener.calls))
        self.assertTrue(all(next(v for k, v in r['headers'].items() if k.lower() == 'oai-sites-authorization') == 'Bearer ' + CANARY for r in opener.calls))
        self.assertEqual(result['http_attempts'], 2); self.assertEqual(result['original_commit'], 'latest_commit_acknowledged')
        self.assertFalse(result['fence_retired']); self.assertFalse(result['lease_release_verified'])
        self.assertEqual(result['broker_calls'], 0); self.assertEqual(result['credential_writes'], 0)
        self.assertEqual(self.fence.read_bytes(), self.original); self.assertEqual(self.profile.read_bytes(), profile)
        self.assertNotIn(CANARY, json.dumps(result)); self.lock_free()

    def test_pinned_source_and_native_deployment_fail_before_http(self):
        self.assertEqual(client.SOURCE_SHA256, 'ed1b7a20b85b2444dd30039c94e67cc9594e6a7923c00b689b312b9193172ac0')
        self.assertEqual(client.SOURCE_COMMIT, 'ce58b639c137abda72f0bdea65118300355f4478')
        self.put(self.source, b'sanitized different source'); opener = Opener()
        self.reject(lambda: self.diagnose(opener), 'SOURCE_DRIFT'); self.assertEqual(opener.calls, [])
        self.put(self.source, WORKER.read_bytes())
        for group, key, value in [('version','id','foreign'), ('version','version_number',2),
            ('version','source',{'commit_sha':'foreign'}), ('deployment','status','failed'),
            ('deployment','id','foreign'), ('deployment','version_id','foreign'),
            ('deployment','project_id','foreign'), ('deployment','failure_message','CANARY')]:
            context = deepcopy(self.context); context[group][key] = value; opener = Opener()
            self.reject(lambda: self.diagnose(opener, context=context), 'DEPLOYMENT_UNVERIFIED')
            self.assertEqual(opener.calls, [])

    def test_site_owner_audience_and_origin_guards_before_http(self):
        variants = []
        for key, value in [('id','foreign'), ('current_user_role','editor'), ('status','inactive'),
                           ('current_live_url','https://foreign.chatgpt.site'), ('access_mode','public')]:
            context = deepcopy(self.context); context['site'][key] = value; variants.append(context)
        context = deepcopy(self.context); context['site']['access_policy']['allowed_users'].append({'role':'viewer'}); variants.append(context)
        context = deepcopy(self.context); context['site']['access_policy']['allowed_groups'] = ['foreign']; variants.append(context)
        context = deepcopy(self.context); context['site']['access_policy']['allowed_account_user_ids'] = ['foreign']; variants.append(context)
        for context in variants:
            opener = Opener(); self.reject(lambda: self.diagnose(opener, context=context), 'TIGER_SITE_')
            self.assertEqual(opener.calls, [])

    def test_existing_private_policy_loader_and_context_extras(self):
        loaded = client.load_policy(self.private / 'config' / 'tiger.json', self.workspace)
        self.assertEqual(loaded, self.policy)
        context = {**self.context, 'extra': CANARY}; opener = Opener()
        self.reject(lambda: self.diagnose(opener, context=context), 'NATIVE_CONTEXT_REQUIRED')
        self.assertEqual(opener.calls, [])
        path = self.private / 'config' / 'tiger.json'; path.chmod(0o644)
        self.reject(lambda: client.load_policy(path, self.workspace), 'PRIVATE_POLICY_REQUIRED')

    def test_fence_shape_private_paths_and_lock_contention(self):
        for key, value in [('phase','acquire'), ('automatic_retry',True), ('commit_id',OTHER[:-1]), ('attempt_id',None)]:
            record = {**self.fence_value, key: value}; self.put(self.fence, encoded(record)); opener = Opener()
            self.reject(lambda: self.diagnose(opener), 'CHECKPOINT_FENCE_REQUIRED'); self.assertEqual(opener.calls, [])
        self.put(self.fence, self.original); self.held(); opener = Opener()
        self.reject(lambda: self.diagnose(opener), 'BRIDGE_BUSY'); self.assertEqual(opener.calls, [])

    def test_private_file_permissions_and_symlink_reject(self):
        self.source.chmod(0o644); opener = Opener()
        self.reject(lambda: self.diagnose(opener), 'PRIVATE_FILE_REQUIRED'); self.assertEqual(opener.calls, [])
        self.source.chmod(0o600); original = self.source.read_bytes(); self.source.unlink()
        target = self.private / 'target.js'; self.put(target, original); self.source.symlink_to(target)
        self.reject(lambda: self.diagnose(opener), 'PRIVATE_PATH_REQUIRED'); self.assertEqual(opener.calls, [])

    def test_fence_lock_is_held_during_transport_and_profile_is_not_read(self):
        real_open = os.open; observed = []
        def guarded_open(path, *args, **kwargs):
            self.assertNotEqual(Path(path), self.profile); return real_open(path, *args, **kwargs)
        def hook():
            fd = real_open(self.lock, os.O_RDONLY)
            try:
                with self.assertRaises(BlockingIOError): fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                observed.append(True)
            finally: os.close(fd)
        opener = Opener([Response(health(),hook=hook), Response(ack(),hook=hook)])
        with patch.object(client.os, 'open', side_effect=guarded_open): self.diagnose(opener)
        self.assertEqual(observed, [True, True]); self.lock_free()

    def test_fence_drift_after_receipt_detected_and_lock_released(self):
        def change(): self.put(self.fence, encoded({**self.fence_value, 'commit_id': OTHER}))
        opener = Opener([Response(health()), Response(ack(),hook=change)])
        self.reject(lambda: self.diagnose(opener), 'FENCE_DRIFT'); self.lock_free()

    def test_unknown_transport_no_retry_or_second_route_and_resources_close(self):
        for failure in (TimeoutError(CANARY), error.URLError(CANARY)):
            opener = Opener([failure]); result = self.diagnose(opener)
            self.assertEqual(len(opener.calls), 1); self.assertEqual(result['health']['status'], 'transport_unconfirmed')
            self.assertEqual(result['checkpoint_ack']['status'], 'not_run')
            self.assertEqual(result['original_commit'], 'history_unavailable_or_unconfirmed')
            self.assertNotIn(CANARY,json.dumps(result)); self.assertEqual(self.fence.read_bytes(),self.original); self.lock_free()

    def test_http_error_scalar_status_bounds_close_and_no_raw_error(self):
        for status in (100,302,400,401,409,599):
            body = io.BytesIO(CANARY.encode()); exc = error.HTTPError('https://fixture.invalid',status,CANARY,{},body)
            opener = Opener([exc]); result = self.diagnose(opener)
            self.assertEqual(result['health'], {'status':'http_rejected','http_status':status})
            self.assertEqual(len(opener.calls),1); self.assertTrue(body.closed); self.assertNotIn(CANARY,json.dumps(result))
        for status in (99,600,True,'409'):
            body = io.BytesIO(CANARY.encode()); exc = error.HTTPError('https://fixture.invalid',status,CANARY,{},body)
            self.reject(lambda: self.diagnose(Opener([exc])),'HTTP_UNEXPECTED'); self.assertTrue(body.closed)

    def test_uninitialized_health_skips_ack_preserves_fence(self):
        opener = Opener([Response(health(initialized=False))]); result = self.diagnose(opener)
        self.assertEqual(len(opener.calls),1); self.assertEqual(result['checkpoint_ack']['status'],'not_run')
        self.assertEqual(self.fence.read_bytes(),self.original)

    def test_ack_rejected_after_successful_health_is_not_retried_or_called_recovery(self):
        opener = Opener([Response(health()), error.HTTPError('https://fixture.invalid',409,CANARY,{},io.BytesIO())])
        result = self.diagnose(opener)
        self.assertEqual(len(opener.calls),2); self.assertEqual(result['checkpoint_ack']['status'],'http_rejected')
        self.assertEqual(result['original_commit'],'history_unavailable_or_unconfirmed')
        self.assertFalse(result['lease_release_verified']); self.assertEqual(self.fence.read_bytes(),self.original)

    def test_exact_64k_boundary_and_utf8_duplicate_deep_nonfinite_reject(self):
        raw = encoded(health()); exact = raw + b' ' * (65536-len(raw))
        opener = Opener([Response(raw=exact),Response(ack())]); self.diagnose(opener)
        response = Response(raw=exact+b' ')
        self.reject(lambda:self.diagnose(Opener([response])),'RESPONSE_TOO_LARGE'); self.assertTrue(response.closed)
        for raw in (b'\xff', b'{"revision":1,"revision":2}', b'{"revision":NaN}', b'{broken', b'['*2000+b'0'+b']'*2000):
            response = Response(raw=raw)
            self.reject(lambda:self.diagnose(Opener([response])),'RESPONSE_INVALID'); self.assertTrue(response.closed)

    def test_health_closed_scalar_schema_and_secret_payload_reject(self):
        for overrides in ({'revision':True},{'revision':2**53+1},{'revision':7.0},{'lease_busy':'false'},
            {'schema':True},{'last_committed_at':CANARY},{'last_committed_at':'2023-01-01T00:00:00'}, {'profile':{'token':CANARY}}):
            response = Response(health(**overrides))
            self.reject(lambda:self.diagnose(Opener([response])),'RESPONSE_INVALID'); self.assertTrue(response.closed)

    def test_ack_closed_schema_false_or_secret_claim_reject(self):
        for overrides in ({'committed':False},{'idempotent':False},{'released':1},{'profile':{'token':CANARY}},{'lease_id':LEASE}):
            responses=[Response(health()),Response(ack(**overrides))]
            self.reject(lambda:self.diagnose(Opener(responses)),'RESPONSE_INVALID'); self.assertTrue(all(r.closed for r in responses))

    def test_route_and_argument_whitelist_reject_before_dispatch(self):
        opener=Opener(); c=client.ReadbackClient({'origin':self.policy['origin'],'bearer':CANARY},opener=opener)
        for operation in ('acquire','release','profile','https://foreign.invalid','snapshot'):
            self.reject(lambda:c.once(operation),'ROUTE_REJECTED')
        self.reject(lambda:c.once('health',commit_id=COMMIT),'ROUTE_REJECTED')
        self.reject(lambda:c.once('checkpoint_ack',commit_id=COMMIT,lease_id='bad'),'ORIGINAL_IDS_REQUIRED')
        self.assertEqual(opener.calls,[])

    def test_no_redirect_handler_actually_rejects_foreign_redirect(self):
        c=client.ReadbackClient({'origin':self.policy['origin'],'bearer':CANARY})
        handler=next(h for h in c.opener.handlers if isinstance(h,request.HTTPRedirectHandler))
        req=request.Request(self.policy['origin']+'/health',headers={'OAI-Sites-Authorization':'Bearer '+CANARY})
        self.assertIsNone(handler.redirect_request(req,None,302,'Found',{},'https://foreign.invalid/health'))

    def call_main(self, out, opener):
        output=io.StringIO(); real=client.diagnose; old_umask=os.umask(0o077)
        try:
            with patch.object(Path,'cwd',return_value=self.workspace), patch.object(client,'hidden_input',return_value=self.context), \
                 patch.object(client,'diagnose',side_effect=lambda *args:real(*args,opener=opener)), \
                 patch.object(client.signal,'signal'), patch.object(client.signal,'alarm'), \
                 patch.object(sys,'argv',['reconciliation','--source',str(self.source),'--out',str(out)]), redirect_stdout(output),redirect_stderr(output):
                code=client.main()
        finally: os.umask(old_umask)
        return code,output.getvalue()

    def test_cli_new_failure_record_private_sanitized_and_original_not_overwritten(self):
        out=self.private/'reports'/'failure'; out.parent.mkdir(mode=0o700)
        code,text=self.call_main(out,Opener([Response(health(profile={'token':CANARY}))]))
        self.assertEqual(code,2); self.assertNotIn(CANARY,text)
        record=out/'readback-failure.json'; old=record.read_bytes()
        self.assertEqual(record.stat().st_mode&0o777,0o600); self.assertFalse((out/'readback.json').exists())
        value=json.loads(old); self.assertFalse(value['fence_retired']); self.assertFalse(value['automatic_retry'])
        code,text=self.call_main(out,Opener()); self.assertEqual(code,2); self.assertEqual(record.read_bytes(),old)
        self.assertEqual(self.fence.read_bytes(),self.original)

    def test_cli_success_has_only_closed_diagnostic_data_and_no_credential_echo(self):
        out=self.private/'reports'/'success'; out.parent.mkdir(mode=0o700)
        code,text=self.call_main(out,Opener()); self.assertEqual(code,0); self.assertNotIn(CANARY,text)
        record=out/'readback.json'; value=json.loads(record.read_text())
        self.assertEqual(record.stat().st_mode&0o777,0o600); self.assertFalse(value['fence_retired'])
        self.assertEqual(set(value),{'status','source_sha256','source_commit','fence_sha256','health','checkpoint_ack',
            'http_attempts','automatic_retry','fence_retired','original_commit','lease_release_verified','broker_calls','credential_writes'})


class DeliberateBreakControls(ClientControls):
    # Reuse fixture helpers but do not duplicate the ordinary test roster.
    def killed(self, identity, old, new, control):
        control(client)
        with altered(old,new) as module:
            with self.assertRaises(AssertionError): control(module)
        MUTATIONS.append({'id':identity,'status':'KILLED','source_unchanged':True})

    def test_mut_source_pin_removed(self):
        self.put(self.source,b'wrong source')
        def control(module):self.reject(lambda:self.diagnose(module=module),'SOURCE_DRIFT')
        self.killed('MUT-C-01',"require(hashlib.sha256(_private_bytes(source, workspace)).hexdigest() == SOURCE_SHA256,",
            'require(True,',control)

    def test_mut_deployment_status_ignored(self):
        context=deepcopy(self.context);context['deployment']['status']='failed'
        def control(module):self.reject(lambda:self.diagnose(module=module,context=context),'DEPLOYMENT_UNVERIFIED')
        self.killed('MUT-C-02',"and deployment.get('status') == 'succeeded'",'and True',control)

    def test_mut_lock_removed(self):
        self.held()
        def control(module):self.reject(lambda:self.diagnose(module=module),'BRIDGE_BUSY')
        self.killed('MUT-C-03','fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)','pass',control)

    def test_mut_body_includes_release(self):
        def control(module):
            opener=Opener();self.diagnose(opener,module=module)
            self.assertEqual(set(json.loads(opener.calls[1]['data'])),{'commit_id','lease_id'})
        self.killed('MUT-C-04',"{'commit_id': commit_id, 'lease_id': lease_id}",
            "{'commit_id': commit_id, 'lease_id': lease_id, 'release': True}",control)

    def test_mut_byte_cap_removed(self):
        raw=encoded(health());raw+=b' '*(65537-len(raw))
        def control(module):self.reject(lambda:self.diagnose(Opener([Response(raw=raw),Response(ack())]),module=module),'RESPONSE_TOO_LARGE')
        self.killed('MUT-C-05',"require(len(raw) <= _LIMIT, 'READBACK_RESPONSE_TOO_LARGE')",'pass',control)

    def test_mut_raw_error_exported(self):
        def control(module):
            exc=error.HTTPError('https://fixture.invalid',409,CANARY,{},io.BytesIO())
            value=self.diagnose(Opener([exc]),module=module);self.assertNotIn(CANARY,json.dumps(value))
        self.killed('MUT-C-06',"return {'status': 'http_rejected', 'http_status': status}",
            "return {'status': 'http_rejected', 'http_status': status, 'raw_error': str(exc)}",control)

    def test_mut_lease_release_claim_invented(self):
        def control(module):self.assertFalse(self.diagnose(module=module)['lease_release_verified'])
        self.killed('MUT-C-07',"'lease_release_verified': False","'lease_release_verified': True",control)

    def test_mut_fence_drift_gate_removed(self):
        def control(module):
            self.put(self.fence,self.original)
            def change():self.put(self.fence,encoded({**self.fence_value,'commit_id':OTHER}))
            self.reject(lambda:self.diagnose(Opener([Response(health()),Response(ack(),hook=change)]),module=module),'FENCE_DRIFT')
        self.killed('MUT-C-08',"require(_private_bytes(fence, workspace) == original, 'READBACK_FENCE_DRIFT')",'pass',control)


def load_tests(loader, tests, pattern):
    # Explicitly avoid unittest inheriting ordinary controls in mutation subclass.
    suite=loader.loadTestsFromTestCase(ClientControls)
    suite.addTests(DeliberateBreakControls(name) for name in sorted(vars(DeliberateBreakControls)) if name.startswith('test_mut_'))
    return suite


if __name__=='__main__':unittest.main()
