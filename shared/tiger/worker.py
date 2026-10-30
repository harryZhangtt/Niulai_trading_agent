"""One leased query per isolated child; service context enters only via a pipe."""
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import sys

from .bridge import TigerBridgeError, TigerDeadline, load_policy, require, run_bridge, safe_failure

ROOT = Path(__file__).resolve().parents[2]
MAX_CONTEXT_BYTES = 1024 * 1024


class WorkerDeadline(TigerDeadline):
    pass


class Discard(io.TextIOBase):
    def write(self, value):
        return len(value)


def deadline(*_):
    # BaseException bypasses legacy per-security-type exception handlers.
    raise WorkerDeadline()


def main():
    os.umask(0o077)
    signal.signal(signal.SIGALRM, deadline)
    signal.signal(signal.SIGTERM, deadline)
    signal.alarm(100)
    result = None
    try:
        raw = sys.stdin.buffer.read(MAX_CONTEXT_BYTES + 1)
        require(len(raw) <= MAX_CONTEXT_BYTES, "TIGER_CONTEXT_TOO_LARGE")
        context = json.loads(raw)
        require(isinstance(context, dict) and set(context) == {"policy", "out", "site", "query"},
                "TIGER_CONTEXT_INVALID")
        policy = load_policy(context["policy"], ROOT)
        with contextlib.redirect_stdout(Discard()), contextlib.redirect_stderr(Discard()):
            result = run_bridge(ROOT, policy, context["site"], context["out"],
                                mode="query", query=context["query"])
    except (Exception, WorkerDeadline) as exc:
        if isinstance(exc, WorkerDeadline):
            exc = TigerBridgeError("TIGER_RUN_DEADLINE")
        result = {**safe_failure(exc), "automatic_retry": False,
                  "reconciliation_required": (ROOT / ".niulai-state/tiger/unresolved.json").exists()}
    finally:
        signal.alarm(0)
    print(json.dumps(result))
    return 0 if result["status"] == "queried" else 2


if __name__ == "__main__":
    raise SystemExit(main())
