"""Drive only the hosted-model handoff through Agent Server's public API."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlparse

from langgraph_sdk import get_sync_client

from .session_model import (IDENTIFIER, PROTOCOL, STATE, canonical, configure,
                            load_binding, private_read, private_write, require,
                            response_message)


def model_requests(value):
    found = {}
    def visit(node):
        if isinstance(node, dict):
            if node.get('protocol') == PROTOCOL and 'request_id' in node and 'tools' in node:
                found[node['request_id']] = node
            else:
                for child in node.values(): visit(child)
        elif isinstance(node, (list, tuple)):
            for child in node: visit(child)
    visit(value.get('tasks', [])); visit(value.get('interrupts', []))
    visit(value.get('__interrupt__', []))
    return list(found.values())


def pending(client, thread, *, state_directory=STATE):
    state = client.threads.get_state(thread, subgraphs=True)
    requests = model_requests(state)
    require(len(requests) <= 1, 'SESSION_MULTIPLE_REQUESTS_UNSUPPORTED')
    result = {'thread_id': thread, 'result': state.get('values', {}).get('result'),
              'checkpoint': state.get('checkpoint'), 'request': None}
    if requests:
        request = requests[0]
        result['request'] = {**request, 'binding_at_interrupt': request['binding'],
                             'binding': load_binding(state_directory)}
    return result


def advance(client, thread, *, input=None, command=None, checkpoint=None,
            state_directory=STATE):
    events = []; run_id = None
    def created(value):
        nonlocal run_id
        run_id = value['run_id']
    for event in client.runs.stream(thread, 'trading_pilot', input=input, command=command,
                                    checkpoint=checkpoint, stream_mode=['updates', 'values'],
                                    config={'recursion_limit': 24},
                                    on_run_created=created, on_disconnect='cancel',
                                    multitask_strategy='reject'):
        events.append({'event': event.event, 'data': event.data})
    require(run_id is not None, 'SESSION_RUN_ID_MISSING')
    run = client.runs.get(thread, run_id)
    state = pending(client, thread, state_directory=state_directory)
    result = {'run_id': run_id, 'run_status': run.get('status'), 'events': events,
              'state': state}
    if (run.get('run_id') != run_id or run.get('thread_id') != thread
            or any(e['event'] == 'metadata' and e['data'].get('run_id') != run_id for e in events)):
        return {**result, 'outcome': 'unknown', 'error': 'SESSION_RUN_IDENTITY_UNCONFIRMED'}
    if any(event['event'] == 'error' for event in events) or run['status'] in {'error', 'timeout'}:
        return {**result, 'outcome': 'failed', 'error': 'SESSION_GRAPH_RUN_FAILED'}
    if run['status'] not in {'success', 'interrupted'}:
        return {**result, 'outcome': 'unknown', 'error': 'SESSION_RUN_NOT_TERMINAL'}
    # Latest thread state can already contain another run. Bind its projection
    # to this exact run's streamed interrupt/result before using it as evidence.
    streamed = model_requests({'interrupts': [event['data'] for event in events
                              if event['event'] in {'updates', 'values'}]})
    if state['request']:
        projected = dict(state['request'])
        projected['binding'] = projected.pop('binding_at_interrupt')
        if projected in streamed:
            return {**result, 'outcome': 'waiting'}
        return {**result, 'outcome': 'unknown', 'error': 'SESSION_PENDING_RUN_BINDING_UNCONFIRMED'}
    values = [e['data'] for e in events if e['event'] == 'values']
    final = (values[-1].get('result') or {}) if values else {}
    if final.get('status') == 'passed':
        if final == state.get('result'):
            return {**result, 'outcome': 'completed'}
        return {**result, 'outcome': 'unknown', 'error': 'SESSION_RESULT_PROJECTION_CHANGED'}
    return {**result, 'outcome': 'failed', 'error': 'SESSION_GRAPH_RESULT_MISSING'}


def respond(client, thread, envelope, *, session_id, revision, state_directory=STATE):
    """Journal transport attempts; graph checkpoints remain workflow authority.

    Only a confirmed same-request rejection permits a fresh attempt. Dispatching,
    unknown, failed and accepted attempts retain their replay fence.
    """
    state_directory = Path(state_directory)
    state_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    lockpath = state_directory / ('respond-' + thread + '.lock')
    with os.fdopen(os.open(lockpath, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = pending(client, thread, state_directory=state_directory)
        request = before['request']
        require(request is not None, 'SESSION_NO_PENDING_MODEL_REQUEST')
        binding = load_binding(state_directory)
        require(session_id == binding['session_id'] and revision == binding['revision'],
                'SESSION_BINDING_STALE')
        response_message(envelope, request, binding)
        directory = state_directory / 'responses' / request['request_id']
        # Preserve and honor receipts from the previous flat journal format.
        previous = list(directory.glob('*.json'))
        legacy = directory.with_suffix('.json')
        if legacy.exists(): previous.append(legacy)
        for path in previous:
            claim = private_read(path)
            require(isinstance(claim, dict) and claim.get('thread_id') == thread
                    and claim.get('request_id') == request['request_id']
                    and claim.get('status') == 'rejected',
                    'SESSION_RESPONSE_ALREADY_CLAIMED_RECONCILE_BEFORE_REPLAY')
        evidence = directory / (str(time.time_ns()) + '.json')
        receipt = {'status': 'dispatching', 'thread_id': thread,
                   'request_id': request['request_id'], 'binding': binding,
                   'response_sha256': hashlib.sha256(canonical(envelope).encode()).hexdigest()}
        private_write(evidence, receipt)
        try:
            result = advance(client, thread, command={'resume': envelope},
                             checkpoint=before['checkpoint'], state_directory=state_directory)
            after = result['state']['request']
            if result['outcome'] in {'failed', 'unknown'}:
                status = result['outcome']
            elif after and after['request_id'] == request['request_id']:
                status = 'rejected' if after.get('response_error') else 'unknown'
            else:
                status = 'processed'
            result['response_status'] = status
            private_write(evidence, {**receipt, **result, 'status': status}, replace=True)
            return result
        except BaseException:
            private_write(evidence, {**receipt, 'status': 'unknown'}, replace=True)
            raise


def report(result):
    """Keep pending's convenient shape, but never conceal the run disposition."""
    public = {**result['state'], **{key: result[key] for key in
              ('run_id', 'run_status', 'outcome', 'error', 'response_status') if key in result}}
    print(canonical(public))
    if result['outcome'] in {'failed', 'unknown'} or result.get('response_status') in {'rejected', 'unknown'}:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:2024')
    commands = parser.add_subparsers(dest='operation', required=True)
    bind = commands.add_parser('configure'); bind.add_argument('--session-id', required=True)
    bind.add_argument('--engine-id', default='codex-session')
    start = commands.add_parser('start'); start.add_argument('--case-file', required=True)
    commands.add_parser('list')
    for name in ('pending', 'respond'):
        command = commands.add_parser(name); command.add_argument('--thread-id', required=True)
        if name == 'respond':
            command.add_argument('--session-id', required=True)
            command.add_argument('--revision', required=True, type=int)
    args = parser.parse_args()
    if args.operation == 'configure':
        print(canonical(configure(args.session_id, engine_id=args.engine_id))); return
    endpoint = urlparse(args.url)
    require(endpoint.scheme == 'http' and endpoint.hostname in {'localhost', '127.0.0.1', '::1'}
            and not endpoint.username and not endpoint.password, 'SESSION_LOCAL_SERVER_REQUIRED')
    client = get_sync_client(url=args.url, timeout=20)
    if args.operation == 'list':
        # Studio-created threads have no CLI engine tag; keep them discoverable.
        print(canonical(client.threads.search(limit=20, select=[
            'thread_id', 'status', 'metadata', 'updated_at']))); return
    if args.operation == 'start':
        load_binding()
        case = json.loads(Path(args.case_file).read_text())
        thread = client.threads.create(metadata={'engine': PROTOCOL})['thread_id']
        evidence = STATE / 'starts' / (thread + '.json')
        private_write(evidence, {'status': 'dispatching', 'thread_id': thread})
        try:
            result = advance(client, thread, input={'case': case})
            private_write(evidence, result, replace=True)
        except BaseException:
            private_write(evidence, {'status': 'unknown', 'thread_id': thread}, replace=True)
            raise
        report(result)
        return
    require(IDENTIFIER.fullmatch(args.thread_id), 'SESSION_THREAD_ID_INVALID')
    if args.operation == 'pending':
        print(canonical(pending(client, args.thread_id))); return
    result = respond(client, args.thread_id, json.load(sys.stdin),
                     session_id=args.session_id, revision=args.revision)
    report(result)


if __name__ == '__main__':
    main()
