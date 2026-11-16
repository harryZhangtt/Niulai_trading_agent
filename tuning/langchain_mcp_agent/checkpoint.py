"""Private file persistence for the pinned InMemorySaver; no pickle loading.

This is a single-process experiment, locked by the runner. Atomic replacement
preserves the latest completed checkpoint on interruption, not production HA.
"""
from __future__ import annotations

import base64
import threading
from collections import defaultdict
from langgraph.checkpoint.memory import InMemorySaver

from shared.langchain_mcp.client import need, read_private, write_private


def encode(value):
    if isinstance(value, bytes): return ['bytes', base64.b64encode(value).decode()]
    if isinstance(value, tuple): return ['tuple', [encode(x) for x in value]]
    if isinstance(value, dict): return ['dict', [[encode(k), encode(v)] for k, v in value.items()]]
    if isinstance(value, list): return ['list', [encode(x) for x in value]]
    need(value is None or type(value) in (str, int, float, bool), 'MCP_CHECKPOINT_TYPE')
    return ['scalar', value]


def decode(value):
    need(isinstance(value, list) and len(value) == 2, 'MCP_CHECKPOINT_SHAPE')
    kind, data = value
    if kind == 'bytes': return base64.b64decode(data, validate=True)
    if kind == 'tuple': return tuple(decode(x) for x in data)
    if kind == 'list': return [decode(x) for x in data]
    if kind == 'dict': return {decode(k): decode(v) for k, v in data}
    need(kind == 'scalar', 'MCP_CHECKPOINT_SHAPE')
    return data


class FileSaver(InMemorySaver):
    def __init__(self, path):
        super().__init__()
        self.path = path
        self.lock = threading.RLock()
        if path.exists():
            value = read_private(path)
            need(value.get('version') == 1, 'MCP_CHECKPOINT_VERSION')
            saved = decode(value['state'])
            for thread, namespaces in saved['storage'].items():
                for namespace, rows in namespaces.items(): self.storage[thread][namespace].update(rows)
            self.writes.update(saved['writes']); self.blobs.update(saved['blobs'])

    def save(self):
        write_private(self.path, {'version': 1, 'state': encode({'storage': self.storage,
                      'writes': self.writes, 'blobs': self.blobs})}, replace=self.path.exists())

    def put(self, *args, **kwargs):
        with self.lock:
            value = super().put(*args, **kwargs); self.save(); return value

    def put_writes(self, *args, **kwargs):
        with self.lock:
            super().put_writes(*args, **kwargs); self.save()
