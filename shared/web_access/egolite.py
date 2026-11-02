"""Pinned candidate connector; no installer, arbitrary scripts, retries or global settings."""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import uuid

from shared.research_sources.artifacts import digest, private_path, require, save
from .policy import fingerprint, origin, validate_config

SCRIPT = Path(__file__).with_name('ego_read.js')


def doctor(config):
    config = validate_config(config)
    browser = config['egolite']
    discovered = shutil.which('ego-browser')
    if not browser['enabled']:
        return {'status': 'blocked', 'code': 'EGOLITE_NOT_CONFIGURED', 'command_on_path': bool(discovered),
                'live_browser_tested': False, 'default_changed': False}
    path = Path(browser['executable'])
    valid = path.is_file() and os.access(path, os.X_OK) and fingerprint(path) == browser['sha256']
    return {'status': 'ready_for_explicit_probe' if valid else 'blocked',
            'code': 'CLI_PIN_VERIFIED' if valid else 'EGOLITE_EXECUTABLE_MISMATCH',
            'command_on_path': bool(discovered), 'live_browser_tested': False, 'default_changed': False}


def _execute(command, script, timeout, maximum, directory):
    """Bound wall time and sampled output-file growth; discard all raw diagnostics."""
    # CLI output is private and temporary; no unbounded communicate() capture.
    with tempfile.TemporaryFile(dir=directory) as stdin, tempfile.TemporaryFile(dir=directory) as stdout, tempfile.TemporaryFile(dir=directory) as stderr:
        stdin.write(script.encode()); stdin.seek(0)
        environment = {key: os.environ[key] for key in ('HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL') if key in os.environ}
        environment.update(PATH='/usr/bin:/bin:/usr/sbin:/sbin', TMPDIR=str(directory), PYTHONDONTWRITEBYTECODE='1')
        process = subprocess.Popen(command, stdin=stdin, stdout=stdout, stderr=stderr,
                                   cwd=directory, env=environment, start_new_session=True)
        failure = None
        def stop():
            group_verified = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                group_verified = False
                # Some hosts permit signalling our child but reject killpg.
                # Reap the owned leader; descendants/browser state stay unknown.
                process.kill()
            process.wait(timeout=5)
            return group_verified
        try:
            deadline = time.monotonic() + timeout
            while True:
                if os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size > maximum:
                    failure = 'EGO_OUTPUT_LIMIT'; break
                if time.monotonic() >= deadline:
                    failure = 'EGO_TIMEOUT'; break
                if process.poll() is not None:
                    break
                time.sleep(0.02)
            if failure:
                # Kill only this live CLI group. The separately running browser
                # may retain an unknown task; caller must reconcile, not retry.
                group_verified = stop()
                require(False, failure if group_verified else failure + '_CLEANUP_UNVERIFIED')
            require(process.returncode == 0, 'EGO_CLI_FAILED')
            require(os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size <= maximum,
                    'EGO_OUTPUT_LIMIT')
            stdout.seek(0)
            raw = stdout.read(maximum + 1)
            # The installed macOS SDK forwards console.log on stderr. Treat it
            # as the protocol only when stdout is empty; read() still requires
            # exactly one closed nonce-bound JSON record. Raw errors never echo.
            if not raw.strip():
                stderr.seek(0)
                raw = stderr.read(maximum + 1)
            require(len(raw) <= maximum, 'EGO_OUTPUT_LIMIT')
            return raw
        finally:
            if process.returncode is None:
                stop()


def read(config, decision, *, output_directory, runner=None):
    config = validate_config(config)
    require(decision.get('route') == 'egolite' and origin(decision.get('url')) in config['allowed_origins'], 'EGO_ROUTE_REJECTED')
    timeout = decision.get('timeout_seconds')
    require(type(timeout) in (int, float) and math.isfinite(timeout)
            and 0 < timeout <= config['limits']['timeout_seconds'], 'EGO_TIMEOUT_INVALID')
    require(doctor(config)['code'] == 'CLI_PIN_VERIFIED', 'EGOLITE_NOT_READY')
    out = private_path(output_directory, create=True)
    operation = str(uuid.uuid4())
    work = private_path(out / operation, create=True)
    inputs = {'nonce': operation, 'space': 'research-' + operation, 'url': decision['url'],
              'profile_id': config['egolite']['profile_id'], 'allowed_origins': config['allowed_origins'],
              'timeout_ms': max(1, int(decision['timeout_seconds'] * 1000)),
              'max_chars': config['limits']['max_snapshot_chars']}
    script = SCRIPT.read_text().replace('__HOST_INPUT__', json.dumps(inputs, ensure_ascii=True))
    identity = {'schema_version': 1, 'kind': 'browser_read_intent', 'operation_id': operation,
                'config_sha256': digest(config), 'script_sha256': fingerprint(SCRIPT),
                'requested_url': inputs['url'], 'task_space': inputs['space'],
                'started_at': datetime.now(timezone.utc).isoformat(), 'automatic_retry': False}
    intent_ref = save(work, identity)
    started = time.monotonic()
    try:
        raw = (runner or _execute)([config['egolite']['executable'], 'nodejs'], script,
              decision['timeout_seconds'], config['limits']['max_output_bytes'], work)
        require(len(raw) <= config['limits']['max_output_bytes'], 'EGO_OUTPUT_LIMIT')
        # The installed SDK terminates console output with an extra blank line.
        # Only surrounding whitespace is framing; extra records/logs still fail.
        lines = raw.decode('utf-8').strip().splitlines()
        require(len(lines) == 1, 'EGO_PROTOCOL_INVALID')
        def pairs(items):
            value = {}
            for key, item in items:
                require(key not in value, 'EGO_PROTOCOL_INVALID')
                value[key] = item
            return value
        result = json.loads(lines[0], object_pairs_hook=pairs,
                            parse_constant=lambda _: require(False, 'EGO_PROTOCOL_INVALID'))
        require(type(result) is dict and type(result.get('schema_version')) is int
                and result['schema_version'] == 1 and result.get('nonce') == operation, 'EGO_PROTOCOL_INVALID')
        require(result.get('status') == 'observed' and result.get('cleanup_verified') is True, 'EGO_OBSERVATION_INCOMPLETE')
        require(set(result) == {'schema_version', 'nonce', 'status', 'observed_url', 'snapshot', 'truncated', 'cleanup_verified'}, 'EGO_PROTOCOL_INVALID')
        require(origin(result.get('observed_url')) in config['allowed_origins'], 'EGO_REDIRECT_REJECTED')
        require(type(result.get('snapshot')) is str and 0 < len(result['snapshot']) <= config['limits']['max_snapshot_chars']
                and type(result.get('truncated')) is bool, 'EGO_PROTOCOL_INVALID')
        require(fingerprint(config['egolite']['executable']) == config['egolite']['sha256'], 'EGO_EXECUTABLE_CHANGED')
        snapshot_ref = save(work, result['snapshot'].encode(), suffix='txt')
        receipt = {**identity, 'kind': 'browser_read_observation', 'intent_ref': intent_ref,
            'status': 'observed', 'provider': 'egolite', 'observed_url': result['observed_url'],
            'retrieved_at': datetime.now(timezone.utc).isoformat(), 'representation': 'semantic_snapshot',
            'access_level': 'rendered_extract', 'snapshot_ref': snapshot_ref, 'truncated': result['truncated'],
            'cleanup_verified': True, 'browser_version': None, 'approval_events': None, 'reauth_events': None,
            'source_truth_verified': False, 'elapsed_seconds': time.monotonic() - started}
    except Exception as error:
        from shared.research_sources.artifacts import SourceError
        code = str(error) if isinstance(error, SourceError) else 'EGO_CONNECTOR_FAILED'
        receipt = {**identity, 'kind': 'browser_read_observation', 'intent_ref': intent_ref,
                   'status': 'blocked', 'code': code, 'cleanup_verified': False,
                   'task_state': 'unknown_reconcile_before_reuse', 'elapsed_seconds': time.monotonic() - started}
    return {'status': receipt['status'], 'receipt_ref': save(work, receipt)}
