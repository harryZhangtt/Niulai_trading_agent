"""Exercise the actual local Agent Server; save only synthetic case evidence."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from langgraph_sdk import get_client

ROOT = Path(__file__).resolve().parents[2]
CASE = {"case_id": "synthetic-fcff-one-period", "fcff": ["110"],
        "terminal_ev": "0", "rate": "0.1", "net_debt": "0", "shares": "10"}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:2024")
    parser.add_argument("--inspect-thread")
    args = parser.parse_args()
    if urlparse(args.url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("local pilot URL required")
    client = get_client(url=args.url)
    if args.inspect_thread:
        state = await client.threads.get_state(args.inspect_thread)
        result = state["values"].get("result")
        if not result or result.get("status") != "passed":
            raise SystemExit("completed thread was not retained")
        print(json.dumps({"thread_id": args.inspect_thread, "persisted_result": result}))
        return
    path = ROOT / ".langchain-pilot" / "runtime" / ("live-" + str(time.time_ns()))
    path.mkdir(mode=0o700)
    started = time.monotonic()
    receipt = {"scope": "isolated_live_synthetic_pilot", "status": "started",
               "started_at": datetime.now(timezone.utc).isoformat(),
               "provider": "openai",
               "endpoint": "https://api.openai.com/v1",
               "requested_model": os.environ.get("LANGCHAIN_PILOT_MODEL", "gpt-6.1-sol"),
               "actual_backend_identity": "unverified",
               "versions": {name: importlib.metadata.version(name) for name in (
                   "langchain", "langgraph", "langchain-openai", "langgraph-cli", "langgraph-api")},
               "source_sha256": {str(file.relative_to(ROOT)): hashlib.sha256(file.read_bytes()).hexdigest()
                                 for file in Path(__file__).parent.glob("*.py")}}
    events = []
    final_values = None
    def save_created(metadata):
        receipt["run_id"] = metadata["run_id"]
        (path / "receipt.json").write_text(json.dumps(receipt, indent=2))
    try:
        assistants = await client.assistants.search(graph_id="trading_pilot")
        assistant_id = assistants[0]["assistant_id"]
        receipt["assistant_id"] = assistant_id
        graph = await client.assistants.get_graph(assistant_id, xray=True)
        schemas = await client.assistants.get_schemas(assistant_id)
        (path / "graph.json").write_text(json.dumps(graph, indent=2))
        (path / "schemas.json").write_text(json.dumps(schemas, indent=2))
        thread = await client.threads.create()
        receipt["thread_id"] = thread["thread_id"]
        async for chunk in client.runs.stream(thread["thread_id"], assistant_id,
                                              input={"case": CASE}, context={"variant": "baseline"},
                                              stream_mode=["updates", "values"],
                                              config={"recursion_limit": 16},
                                              on_disconnect="cancel", on_run_created=save_created):
            events.append({"event": chunk.event, "data": chunk.data})
            if chunk.event == "error":
                raise RuntimeError("Agent Server emitted a run error")
            if chunk.event == "metadata" and chunk.data.get("run_id") != receipt.get("run_id"):
                raise ValueError("stream metadata is not bound to the created run")
            if chunk.event == "values":
                final_values = chunk.data
        (path / "events.json").write_text(json.dumps(events, indent=2))
        state = await client.threads.get_state(thread["thread_id"])
        (path / "state.json").write_text(json.dumps(state, indent=2))
        if not receipt.get("run_id"):
            raise ValueError("run creation identity was not captured")
        run = await client.runs.get(thread["thread_id"], receipt["run_id"])
        if run.get("run_id") != receipt["run_id"] or run.get("status") != "success":
            raise ValueError("the exact created run did not succeed")
        result = (final_values or {}).get("result", {})
        if (result.get("status") != "passed" or result.get("per_share") != "10"
                or result.get("case_id") != CASE["case_id"]):
            raise ValueError("live graph did not produce the independently verified result")
        receipt.update(status="passed", result=result,
                       stream_events=len(events))
    except BaseException as exc:
        receipt.update(status="unknown" if isinstance(exc, (asyncio.CancelledError, TimeoutError)) else "failed",
                       error_type=type(exc).__name__)
        if receipt.get("run_id"):
            try:
                await asyncio.wait_for(client.runs.cancel(receipt["thread_id"], receipt["run_id"],
                                                         wait=True, action="interrupt"), timeout=10)
                receipt["exact_run_cancel_requested"] = True
            except Exception as cleanup_error:
                receipt["cleanup_error_type"] = type(cleanup_error).__name__
        raise
    finally:
        (path / "events.json").write_text(json.dumps(events, indent=2))
        receipt["elapsed_seconds"] = round(time.monotonic() - started, 3)
        (path / "receipt.json").write_text(json.dumps(receipt, indent=2))
        print(json.dumps({"status": receipt["status"], "evidence": str(path.relative_to(ROOT)),
                          "thread_id": receipt.get("thread_id"), "error_type": receipt.get("error_type")}))


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=240))
