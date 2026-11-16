import contextlib
import hashlib
import http.server
import inspect
import io
import json
import logging
import os
from pathlib import Path
import socket
import stat
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from jsonschema import Draft202012Validator

import shared.job_runtime.candidates.r6_one_off_codex_credential_broker_v2 as candidate
from shared.job_runtime.candidates import r6_one_off_codex_direct_catalog_v1 as direct_catalog
from shared.job_runtime.candidates.r6_one_off_codex_direct_catalog_v1 import capability, transport

ROOT = Path(__file__).resolve().parents[5]
CANDIDATE = ROOT / "shared/job_runtime/candidates/r6_one_off_codex_credential_broker_v2"
SECRET = b"synthetic-v2-access-token"
RESPONSE_MARKER = b"SYNTHETIC-V2-RAW-MARKER-53a1"
CATALOG = b'{"models":[{"slug":"gpt-6.1-sol","note":"' + RESPONSE_MARKER + b'"}]}'


def canonical(value):
    return (json.dumps(value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n").encode("ascii")


def official_auth(**overrides):
    value = {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {
            "id_token": "synthetic-id-token",
            "access_token": SECRET.decode("ascii"),
            "refresh_token": "synthetic-refresh-token",
            "oauth_provenance": {"issuer": "https://auth.example", "client_id": "synthetic-client"},
            "login_owner_id": "synthetic-login",
            "account_id": "synthetic-account",
        },
        "last_refresh": "2026-11-11T00:00:00Z",
        "agent_identity": {
            "agent_runtime_id": "runtime-1",
            "agent_private_key": "synthetic-private-key",
            "account_id": "synthetic-account",
            "chatgpt_user_id": "synthetic-user",
            "email": None,
            "plan_type": "plus",
            "chatgpt_account_is_fedramp": False,
            "task_id": None,
        },
        "personal_access_token": "synthetic-pat",
        "bedrock_api_key": {"api_key": "synthetic-bedrock-key", "region": "us-east-1"},
        "bedrock_access_keys": {"access_key_id": "synthetic-access-id", "secret_access_key": "synthetic-secret", "session_token": None},
    }
    value.update(overrides)
    return value


def chain_for(directory):
    directory = Path(directory).resolve()
    current = Path("/")
    result = []
    for name in directory.parts[1:]:
        current /= name
        info = os.stat(current, follow_symlinks=True)
        result.append((name, info.st_uid, stat.S_IMODE(info.st_mode)))
    return tuple(result)


def write_private(path, content):
    path.write_bytes(content)
    path.chmod(0o600)
    return path


def authority_files(base):
    grant = {
        "version": "r6-one-off-codex-credential-broker-live-grant-v2",
        "status": "APPROVED_EXACT_ONE_SHOT_LIVE",
        "activation": True,
        "credential_path": "/Users/bytedance/Desktop/Trading Agent/.job-runtime/codex-home/auth.json",
        "output_root": "/Users/bytedance/Desktop/Trading Agent/.job-runtime/private/r6-one-off-codex-credential-broker-v2",
        "physical_forwards": 1,
        "retry": 0,
        "replay": 0,
        "auth_recovery": 0,
        "status_queries": 0,
        "inference_requests": 0,
        "bytedcli_calls": 0,
    }
    grant_raw = canonical(grant)
    grant_path = write_private(base / "live-grant.json", grant_raw)
    grant_sha = hashlib.sha256(grant_raw).hexdigest()
    review = {"version": "r6-one-off-codex-credential-broker-live-grant-review-v2", "independent": True, "grant_sha256": grant_sha, "verdict": "CLEAN_EXACT_ONE_SHOT_LIVE_GRANT"}
    review_raw = canonical(review)
    review_path = write_private(base / "live-review.json", review_raw)
    return (str(grant_path), len(grant_raw), grant_sha), (str(review_path), len(review_raw), hashlib.sha256(review_raw).hexdigest())


@contextlib.contextmanager
def fixed_fixture(raw=None, output_name="execution"):
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        auth_parent = base / "auth-home"
        output_base = base / "output-base"
        auth_parent.mkdir(mode=0o700)
        output_base.mkdir(mode=0o700)
        source = write_private(auth_parent / "auth.json", canonical(official_auth()) if raw is None else raw)
        grant_pin, review_pin = authority_files(base)
        patches = (
            mock.patch.object(candidate, "_OWNER_UID", os.getuid()),
            mock.patch.object(candidate, "_AUTH_CHAIN", chain_for(auth_parent)),
            mock.patch.object(candidate, "_OUTPUT_BASE_CHAIN", chain_for(output_base)),
            mock.patch.object(candidate, "_OUTPUT_PARENT_SPEC", ("private", os.getuid(), 0o700)),
            mock.patch.object(candidate, "_OUTPUT_SPEC", (output_name, os.getuid(), 0o700)),
            mock.patch.object(candidate, "_LIVE_GRANT_PIN", grant_pin),
            mock.patch.object(candidate, "_LIVE_REVIEW_PIN", review_pin),
        )
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            yield SimpleNamespace(base=base, source=source, output=output_base / "private" / output_name)


def fake_direct(captured, response=CATALOG, fail=None):
    @contextlib.contextmanager
    def scope(source):
        captured.append(source)
        snapshot = bytes(source)
        for index in range(len(source)):
            source[index] = 0
        source.clear()
        captured.append(snapshot)
        try:
            yield object()
        finally:
            pass

    class Executor:
        calls = 0

        def __init__(self):
            pass

        def execute(self, capability, *, include_owner_private_raw=False):
            type(self).calls += 1
            if fail is not None:
                raise fail
            return SimpleNamespace(
                models=("gpt-6.1-sol",),
                receipt={"status": "PASS", "http_status": 200, "body_sha256": hashlib.sha256(response).hexdigest(), "body_bytes": len(response), "model_count": 1},
                origin=SimpleNamespace(kind="fixture_loopback", host="127.0.0.1", tls_hostname_verified=False),
                owner_private_raw=response if include_owner_private_raw else None,
            )

    return scope, Executor


@contextlib.contextmanager
def patched_fake(captured, response=CATALOG):
    scope, executor = fake_direct(captured, response)
    with mock.patch.object(direct_catalog, "transient_bearer_scope", scope), mock.patch.object(direct_catalog, "DirectCatalogExecutor", executor):
        yield executor


def assert_graph_excludes(testcase, error, forbidden):
    objects = set()
    tracebacks = set()
    stack = [error]
    while stack:
        value = stack.pop()
        if value is None or id(value) in objects:
            continue
        objects.add(id(value))
        if isinstance(value, str):
            raw = value.encode("utf-8", "ignore")
            for marker in forbidden:
                testcase.assertNotIn(marker, raw)
        elif isinstance(value, (bytes, bytearray, memoryview)):
            raw = bytes(value)
            for marker in forbidden:
                testcase.assertNotIn(marker, raw)
        elif isinstance(value, BaseException):
            stack.extend((value.args, value.__dict__, value.__cause__, value.__context__))
            cursor = value.__traceback__
            while cursor is not None and id(cursor) not in tracebacks:
                tracebacks.add(id(cursor))
                stack.extend(cursor.tb_frame.f_locals.values())
                cursor = cursor.tb_next
        elif isinstance(value, dict):
            stack.extend(value.keys())
            stack.extend(value.values())
        elif isinstance(value, (tuple, list, set, frozenset)):
            stack.extend(value)
        else:
            state = getattr(value, "__dict__", None)
            if isinstance(state, dict):
                stack.append(state)


class FakeUpstream:
    def __init__(self):
        self.requests = []

    def __enter__(self):
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def do_GET(self):
                outer.requests.append({"method": self.command, "path": self.path, "auth_exact": self.headers.get("Authorization") == "Bearer " + SECRET.decode("ascii")})
                self.send_response(200)
                self.send_header("Content-Length", str(len(CATALOG)))
                self.end_headers()
                self.wfile.write(CATALOG)

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    @property
    def endpoint(self):
        return transport._Endpoint("127.0.0.1", self.server.server_address[1], False, "fixture_loopback")


class CredentialBrokerV2Tests(unittest.TestCase):
    def tearDown(self):
        self.assertEqual(capability._active_material_count(), 0)

    def test_public_namespace_has_only_zero_arg_execute_live_and_no_seam(self):
        self.assertEqual(candidate.__all__, ["execute_live"])
        self.assertEqual(sorted(name for name in vars(candidate) if not name.startswith("_")), ["execute_live"])
        self.assertEqual(list(inspect.signature(candidate.execute_live).parameters), [])
        self.assertEqual(sorted(name for name, value in vars(candidate).items() if inspect.isfunction(value)), ["execute_live"])
        self.assertFalse(any(inspect.ismodule(value) for value in vars(candidate).values()))
        source = (CANDIDATE / "__init__.py").read_text()
        for forbidden in ("_TEST_SEAM", "_execute_for_test", "executor_factory", "caller_selected", "sentinel"):
            self.assertNotIn(forbidden, source)
        self.assertFalse((CANDIDATE / "broker.py").exists())

    def test_default_gate_rejects_before_auth_or_output_access(self):
        real_open = os.open
        auth_or_output = []

        def observed(path, *args, **kwargs):
            if path in ("auth.json", "private", "r6-one-off-codex-credential-broker-v2"):
                auth_or_output.append(path)
            return real_open(path, *args, **kwargs)

        with mock.patch("os.open", side_effect=observed), self.assertRaises(Exception) as caught:
            candidate.execute_live()
        self.assertEqual(caught.exception.code, "SEPARATE_EXACT_LIVE_GRANT_AND_REVIEW_REQUIRED")
        self.assertEqual(auth_or_output, [])

    def test_nominal_direct_catalog_e2e_commits_last_and_wipes_token(self):
        captured = []
        real_scope = direct_catalog.transient_bearer_scope

        @contextlib.contextmanager
        def observed_scope(source):
            captured.append(source)
            with real_scope(source) as capability_value:
                yield capability_value

        stdout = io.StringIO()
        stderr = io.StringIO()
        handlers = tuple(logging.getLogger().handlers)
        with fixed_fixture(), FakeUpstream() as upstream:
            with mock.patch.object(transport, "_fixed_endpoint", return_value=upstream.endpoint), mock.patch.object(direct_catalog, "transient_bearer_scope", observed_scope), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                published = candidate.execute_live()
            self.assertEqual(upstream.requests, [{"method": "GET", "path": "/backend-api/codex/models?client_version=0.167.0", "auth_exact": True}])
            self.assertEqual(captured, [bytearray()])
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(tuple(logging.getLogger().handlers), handlers)
            self.assertEqual(published.raw_catalog_path.read_bytes(), CATALOG)
            membership = json.loads(published.membership_receipt_path.read_text())
            execution = json.loads(published.execution_receipt_path.read_text())
            marker = json.loads(published.commit_marker_path.read_text())
            self.assertEqual(execution["physical_forwards"], 1)
            self.assertEqual((execution["retry"], execution["replay"], execution["auth_recovery"], execution["status_queries"], execution["inference_requests"], execution["bytedcli_calls"]), (0, 0, 0, 0, 0, 0))
            self.assertTrue(marker["committed"])
            for path in published.commit_marker_path.parent.iterdir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            times = [published.raw_catalog_path.stat().st_mtime_ns, published.membership_receipt_path.stat().st_mtime_ns, published.execution_receipt_path.stat().st_mtime_ns]
            self.assertGreaterEqual(published.commit_marker_path.stat().st_mtime_ns, max(times))
            schemas = CANDIDATE / "schemas"
            Draft202012Validator(json.loads((schemas / "catalog-membership-receipt-v2.schema.json").read_text())).validate(membership)
            Draft202012Validator(json.loads((schemas / "execution-receipt-v2.schema.json").read_text())).validate(execution)
            Draft202012Validator(json.loads((schemas / "commit-marker-v2.schema.json").read_text())).validate(marker)

    def test_every_official_top_level_and_nested_valid_shape(self):
        cases = []
        for mode in ("apikey", "chatgpt", "chatgptAuthTokens", "headers", "agentIdentity", "personalAccessToken", "bedrockApiKey", "bedrockAccessKeys"):
            cases.append(("auth-mode-" + mode, official_auth(auth_mode=mode)))
        cases.extend((
            ("nullable-top", official_auth(auth_mode=None, OPENAI_API_KEY=None, last_refresh=None, agent_identity=None, personal_access_token=None, bedrock_api_key=None, bedrock_access_keys=None)),
            ("string-top", official_auth(OPENAI_API_KEY="synthetic-key", last_refresh="2026-11-11T00:00:00+00:00", personal_access_token="synthetic-pat")),
            ("identity-jwt", official_auth(agent_identity="synthetic-agent-jwt")),
            ("identity-record-min", official_auth(agent_identity={"agent_runtime_id":"r","agent_private_key":"k","account_id":"a","chatgpt_user_id":"u","plan_type":"future-plan-maps-to-unknown","chatgpt_account_is_fedramp":True})),
            ("bedrock-null-session", official_auth(bedrock_access_keys={"access_key_id":"a","secret_access_key":"s","session_token":None})),
            ("bedrock-string-session", official_auth(bedrock_access_keys={"access_key_id":"a","secret_access_key":"s","session_token":"t"})),
            ("tokens-optionals-absent", official_auth(tokens={"id_token":"i","access_token":SECRET.decode(),"refresh_token":"r"})),
            ("tokens-optionals-null", official_auth(tokens={"id_token":"i","access_token":SECRET.decode(),"refresh_token":"r","oauth_provenance":None,"login_owner_id":None,"account_id":None})),
        ))
        for index, (name, document) in enumerate(cases):
            captured = []
            with self.subTest(name=name), fixed_fixture(canonical(document), "valid-" + str(index)), patched_fake(captured) as executor:
                candidate.execute_live()
                self.assertEqual(executor.calls, 1)
                self.assertEqual(captured[-2], bytearray())
                self.assertEqual(captured[-1], SECRET)

    def test_invalid_official_field_types_unknowns_duplicates_malformed_and_nonfinite_reject(self):
        invalid = []
        replacements = {
            "auth_mode": {}, "OPENAI_API_KEY": [], "last_refresh": {}, "agent_identity": 1,
            "personal_access_token": {}, "bedrock_api_key": [], "bedrock_access_keys": "bad",
        }
        for name, child in replacements.items():
            invalid.append(("type-" + name, canonical(official_auth(**{name: child}))))
        invalid.extend((
            ("unknown-top", canonical({**official_auth(), "unknown": "x"})),
            ("bad-mode", canonical(official_auth(auth_mode="ChatGPT"))),
            ("unknown-token", canonical(official_auth(tokens={**official_auth()["tokens"], "unknown":"x"}))),
            ("bad-token-access", canonical(official_auth(tokens={**official_auth()["tokens"], "access_token": []}))),
            ("bad-provenance", canonical(official_auth(tokens={**official_auth()["tokens"], "oauth_provenance":{"issuer":"i","client_id":"c","unknown":"x"}}))),
            ("bad-identity", canonical(official_auth(agent_identity={"agent_runtime_id":"r","agent_private_key":"k","account_id":"a","chatgpt_user_id":"u","plan_type":"p","chatgpt_account_is_fedramp":0}))),
            ("bad-bedrock-key", canonical(official_auth(bedrock_api_key={"api_key":"k","region":"r","unknown":"x"}))),
            ("bad-bedrock-access", canonical(official_auth(bedrock_access_keys={"access_key_id":"a","secret_access_key":"s","session_token":1}))),
            ("escaped-duplicate", b'{"tok\\u0065ns":{"id_token":"i","access_token":"a","refresh_token":"r"},"tokens":{"id_token":"i","access_token":"b","refresh_token":"r"}}'),
            ("escaped-unknown", b'{"tokens":{"id_token":"i","access_token":"a","refresh_token":"r"},"unkn\\u006fwn":"x"}'),
            ("malformed", b'{"tokens":'),
            ("nonfinite", b'{"tokens":{"id_token":"i","access_token":"a","refresh_token":"r"},"last_refresh":NaN}'),
        ))
        for index, (name, raw) in enumerate(invalid):
            captured = []
            with self.subTest(name=name), fixed_fixture(raw, "invalid-" + str(index)), patched_fake(captured) as executor, self.assertRaises(Exception) as caught:
                candidate.execute_live()
            self.assertEqual(caught.exception.code, "CREDENTIAL_FORMAT_REJECTED")
            self.assertEqual(executor.calls, 0)
            assert_graph_excludes(self, caught.exception, (SECRET, RESPONSE_MARKER))

    def test_ancestor_mode_owner_and_symlink_rejected_before_executor(self):
        captured = []
        with fixed_fixture(output_name="bad-mode") as fixture, patched_fake(captured) as executor:
            fixture.source.parent.chmod(0o777)
            with self.assertRaises(Exception):
                candidate.execute_live()
            self.assertEqual(executor.calls, 0)
        with fixed_fixture(output_name="bad-owner") as fixture, patched_fake(captured) as executor:
            chain = list(candidate._AUTH_CHAIN)
            name, uid, mode = chain[-1]
            chain[-1] = (name, uid + 1, mode)
            with mock.patch.object(candidate, "_AUTH_CHAIN", tuple(chain)), self.assertRaises(Exception):
                candidate.execute_live()
            self.assertEqual(executor.calls, 0)
        with fixed_fixture(output_name="symlink") as fixture, patched_fake(captured) as executor:
            real = fixture.source.parent
            moved = real.with_name("auth-real")
            real.rename(moved)
            real.symlink_to(moved, target_is_directory=True)
            with self.assertRaises(Exception):
                candidate.execute_live()
            self.assertEqual(executor.calls, 0)

    def test_ancestor_symlink_swap_race_detected_descriptor_relatively(self):
        captured = []
        with fixed_fixture(output_name="ancestor-swap") as fixture, patched_fake(captured) as executor:
            real_open = os.open
            swapped = False

            def racing_open(path, *args, **kwargs):
                nonlocal swapped
                descriptor = real_open(path, *args, **kwargs)
                if path == "auth.json" and not swapped:
                    swapped = True
                    parent = fixture.source.parent
                    held = parent.with_name("auth-held")
                    attacker = parent.with_name("auth-attacker")
                    attacker.mkdir(mode=0o700)
                    write_private(attacker / "auth.json", canonical(official_auth(tokens={**official_auth()["tokens"], "access_token":"attacker-token"})))
                    parent.rename(held)
                    parent.symlink_to(attacker, target_is_directory=True)
                return descriptor

            with mock.patch("os.open", side_effect=racing_open), self.assertRaises(Exception) as caught:
                candidate.execute_live()
            self.assertEqual(caught.exception.state, "UNKNOWN")
            self.assertEqual(executor.calls, 0)
            self.assertEqual(captured, [])

    def test_final_file_swap_race_detected_before_executor(self):
        captured = []
        with fixed_fixture(output_name="file-swap") as fixture, patched_fake(captured) as executor:
            real_open = os.open
            swapped = False

            def racing_open(path, *args, **kwargs):
                nonlocal swapped
                descriptor = real_open(path, *args, **kwargs)
                if path == "auth.json" and not swapped:
                    swapped = True
                    original = fixture.source.with_name("auth-original.json")
                    fixture.source.rename(original)
                    write_private(fixture.source, canonical(official_auth(tokens={**official_auth()["tokens"], "access_token":"attacker-token"})))
                return descriptor

            with mock.patch("os.open", side_effect=racing_open), self.assertRaises(Exception) as caught:
                candidate.execute_live()
            self.assertEqual(caught.exception.code, "CREDENTIAL_SOURCE_DRIFT")
            self.assertEqual(caught.exception.state, "UNKNOWN")
            self.assertEqual(executor.calls, 0)

    def test_short_writes_complete_zero_write_after_forward_fences_unknown_and_cleans_graph(self):
        captured = []
        real_write = os.write
        calls = 0

        def short_write(descriptor, value):
            nonlocal calls
            calls += 1
            return real_write(descriptor, value[:max(1, len(value) // 2)])

        with fixed_fixture(output_name="short"), patched_fake(captured), mock.patch("os.write", side_effect=short_write):
            candidate.execute_live()
        self.assertGreater(calls, 8)

        def zero_on_response(descriptor, value):
            raw = bytes(value)
            if RESPONSE_MARKER in raw:
                return 0
            return real_write(descriptor, value)

        with fixed_fixture(output_name="zero"), patched_fake(captured) as executor, mock.patch("os.write", side_effect=zero_on_response), self.assertRaises(Exception) as caught:
            candidate.execute_live()
        self.assertEqual(caught.exception.state, "UNKNOWN")
        self.assertEqual(executor.calls, 1)
        assert_graph_excludes(self, caught.exception, (SECRET, RESPONSE_MARKER))

    def test_crash_after_forward_fences_unknown_second_execution_without_replay(self):
        class Crash(BaseException):
            pass

        captured = []
        with fixed_fixture(output_name="crash") as fixture, patched_fake(captured) as executor:
            real_link = os.link
            crashed = False

            def crash_link(*args, **kwargs):
                nonlocal crashed
                result = real_link(*args, **kwargs)
                if not crashed:
                    crashed = True
                    raise Crash("synthetic crash")
                return result

            with mock.patch("os.link", side_effect=crash_link), self.assertRaises(Crash) as caught:
                candidate.execute_live()
            assert_graph_excludes(self, caught.exception, (SECRET, RESPONSE_MARKER))
            self.assertFalse((fixture.output / "COMMITTED.json").exists())
            self.assertEqual(executor.calls, 1)
            with self.assertRaises(Exception) as second:
                candidate.execute_live()
            self.assertEqual(second.exception.code, "UNKNOWN_EXISTING_EXECUTION_FENCE")
            self.assertEqual(second.exception.state, "UNKNOWN")
            self.assertEqual(executor.calls, 1)

    def test_second_execution_after_commit_rejected_before_provider(self):
        captured = []
        with fixed_fixture(output_name="second"), patched_fake(captured) as executor:
            candidate.execute_live()
            with self.assertRaises(Exception) as caught:
                candidate.execute_live()
            self.assertEqual(caught.exception.code, "SECOND_EXECUTION_REJECTED")
            self.assertEqual(executor.calls, 1)

    def test_live_grant_and_review_are_both_exactly_pinned(self):
        captured = []
        with fixed_fixture(output_name="tamper") as fixture, patched_fake(captured) as executor:
            grant = fixture.base / "live-grant.json"
            grant.write_bytes(grant.read_bytes() + b" ")
            grant.chmod(0o600)
            with self.assertRaises(Exception) as caught:
                candidate.execute_live()
            self.assertIn(caught.exception.code, ("PINNED_ARTIFACT_SIZE_CHANGED", "PINNED_ARTIFACT_IDENTITY_REJECTED", "PINNED_ARTIFACT_HASH_REJECTED"))
            self.assertEqual(executor.calls, 0)

    def test_source_pins_v1_open_review_and_remains_unregistered_effect_free(self):
        source = (CANDIDATE / "__init__.py").read_text()
        self.assertIn("247853762db3ee1cc3666671b252319d3f5d054b6a2f7f5010f3d6ef6899a3ae", source)
        self.assertIn("OPEN-CB-001", source)
        self.assertIn("OPEN-CB-003", source)
        for path in (ROOT / "shared/job_runtime/config.py", ROOT / "shared/job_runtime/service.py"):
            self.assertNotIn("r6_one_off_codex_credential_broker_v2", path.read_text())
        for forbidden in ("subprocess", "requests.", "urllib.", "os.system", "bytedcli ", "status_query(", "auth_recover("):
            self.assertNotIn(forbidden, source)

    def test_closed_schemas(self):
        for path in (CANDIDATE / "schemas").glob("*.schema.json"):
            schema = json.loads(path.read_text())
            Draft202012Validator.check_schema(schema)
            stack = [schema]
            while stack:
                value = stack.pop()
                if isinstance(value, dict):
                    if value.get("type") == "object":
                        self.assertIs(value.get("additionalProperties"), False)
                        self.assertIs(value.get("unevaluatedProperties"), False)
                    stack.extend(value.values())
                elif isinstance(value, list):
                    stack.extend(value)


if __name__ == "__main__":
    unittest.main()
