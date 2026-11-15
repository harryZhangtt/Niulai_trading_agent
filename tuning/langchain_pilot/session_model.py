"""A cooperative chat session supplies model messages; LangChain runs the tools.

No provider requests, copied login tokens, shell tools, or background poller.
Agent Server checkpoints each model request as an ordinary LangGraph interrupt.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.config import get_config
from langgraph.types import interrupt
from pydantic import Field

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / '.langchain-pilot/runtime/session-engine'
PROTOCOL = 'session-model-v1'
CODE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
IDENTIFIER = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$')


class SessionModelError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise SessionModelError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def private_read(path):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW)) as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and not info.st_mode & 0o077 and info.st_size <= 262144,
                'SESSION_STATE_NOT_PRIVATE')
        return json.load(stream)


def private_write(path, value, *, replace=False):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = canonical(value) + '\n'
    if not replace:
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                               0o600), 'w') as stream:
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        return
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix='.pending-')
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def load_binding(state=STATE):
    path = Path(state) / 'binding.json'
    require(path.is_file(), 'SESSION_ENGINE_UNCONFIGURED')
    binding = private_read(path)
    require(isinstance(binding, dict)
            and set(binding) == {'protocol', 'engine_id', 'session_id', 'revision'}
            and binding['protocol'] == PROTOCOL
            and isinstance(binding['engine_id'], str)
            and IDENTIFIER.fullmatch(binding['engine_id'])
            and isinstance(binding['session_id'], str)
            and IDENTIFIER.fullmatch(binding['session_id'])
            and type(binding['revision']) is int and binding['revision'] > 0,
            'SESSION_BINDING_INVALID')
    return binding


def configure(session_id, *, engine_id='codex-session', state=STATE):
    require(IDENTIFIER.fullmatch(session_id) and IDENTIFIER.fullmatch(engine_id),
            'SESSION_ID_INVALID')
    state = Path(state); state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with os.fdopen(os.open(state / 'binding.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                           0o600), 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = load_binding(state) if (state / 'binding.json').exists() else None
        binding = {'protocol': PROTOCOL, 'engine_id': engine_id, 'session_id': session_id,
                   'revision': previous['revision'] + 1 if previous else 1}
        private_write(state / 'bindings' / (str(time.time_ns()) + '.json'), binding)
        private_write(state / 'binding.json', binding, replace=True)
        return binding


def response_message(envelope, request, binding):
    require(isinstance(envelope, dict) and set(envelope) == {'request_id', 'binding', 'message'},
            'SESSION_RESPONSE_SHAPE')
    require(envelope['request_id'] == request['request_id'], 'SESSION_REQUEST_MISMATCH')
    require(envelope['binding'] == binding, 'SESSION_BINDING_STALE')
    message = envelope['message']
    require(isinstance(message, dict) and set(message) <= {'content', 'tool_calls'}
            and isinstance(message.get('content', ''), str)
            and isinstance(message.get('tool_calls', []), list),
            'SESSION_ASSISTANT_MESSAGE_REQUIRED')
    try:
        encoded = canonical(message)
        require(len(encoded) <= 16384 and json.loads(encoded) == message,
                'SESSION_ASSISTANT_MESSAGE_REQUIRED')
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise SessionModelError('SESSION_ASSISTANT_MESSAGE_REQUIRED') from None
    names = {tool['function']['name'] for tool in request['tools']}
    calls = []
    for index, call in enumerate(message.get('tool_calls', [])):
        require(isinstance(call, dict) and set(call) == {'name', 'args'}
                and isinstance(call['name'], str) and call['name'] in names
                and isinstance(call['args'], dict),
                'SESSION_TOOL_CALL_INVALID')
        calls.append({**call, 'id': 'session-' + request['request_id'][:24] + '-' + str(index)})
    require(len(calls) <= 8 and (calls or message.get('content')), 'SESSION_EMPTY_RESPONSE')
    return AIMessage(content=message.get('content', ''), tool_calls=calls,
                     id='session-response-' + request['request_id'],
                     response_metadata={'model_engine': PROTOCOL, 'binding': binding,
                                        'model_identity': 'host_session_declared_not_attested',
                                        'request_id': request['request_id']})


class SessionChatModel(BaseChatModel):
    tools: list[dict[str, Any]] = Field(default_factory=list)
    state_directory: str = str(STATE)

    @property
    def _llm_type(self):
        return PROTOCOL

    def bind_tools(self, tools, **kwargs):
        return self.model_copy(update={'tools': [convert_to_openai_tool(tool) for tool in tools]})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        thread = get_config().get('configurable', {}).get('thread_id')
        require(isinstance(thread, str) and thread, 'SESSION_THREAD_REQUIRED')
        body = {'protocol': PROTOCOL, 'thread_id': thread, 'engine_source_sha256': CODE_SHA256,
                'messages': [message.model_dump(mode='json') for message in messages],
                'tools': self.tools}
        require(len(canonical(body)) <= 131072, 'SESSION_REQUEST_TOO_LARGE')
        request = {**body, 'request_id': hashlib.sha256(canonical(body).encode()).hexdigest()}
        error = None
        # Invalid direct resumes remain visible and recoverable at another interrupt.
        while True:
            binding = load_binding(Path(self.state_directory))
            payload = {**request, 'binding': binding}
            if error:
                payload['response_error'] = error
            answer = interrupt(payload)
            try:
                # Admission uses this binding snapshot. A later rebind changes
                # subsequent admissions; it cannot revoke an accepted message.
                message = response_message(answer, request,
                                           load_binding(Path(self.state_directory)))
                return ChatResult(generations=[ChatGeneration(message=message)])
            except SessionModelError as invalid:
                error = str(invalid)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
