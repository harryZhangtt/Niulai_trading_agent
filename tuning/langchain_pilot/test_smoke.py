"""Independent offline smoke-run identity and failure controls.

SDK responses are synthetic. Artifact writes are intercepted in memory, so this
suite does not start a server, call a provider, or create live-run evidence.
"""
from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tuning.langchain_pilot import smoke


CREATED_RUN = "synthetic-created-run"
OTHER_RUN = "synthetic-different-run"
THREAD = "synthetic-thread"
RESULT = {"status": "passed", "per_share": "10", "case_id": smoke.CASE["case_id"]}


def client_double(*, chunks=None, created_run=CREATED_RUN, run=None,
                  projection=None, stream_error=None, cancel_error=None):
    """Keep stream identity, exact-run status and latest state independent."""
    if chunks is None:
        chunks = [("metadata", {"run_id": CREATED_RUN}), ("values", {"result": RESULT})]

    async def stream(*args, **kwargs):
        if created_run is not None:
            kwargs["on_run_created"]({"run_id": created_run})
        for event, data in chunks:
            yield SimpleNamespace(event=event, data=data)
        if stream_error is not None:
            raise stream_error

    runs = SimpleNamespace(
        stream=stream,
        get=AsyncMock(return_value=run or {"run_id": CREATED_RUN, "status": "success"}),
        # A plausible unrelated newest run must never be an acceptance oracle.
        list=AsyncMock(return_value=[{"run_id": OTHER_RUN, "status": "success"}]),
        cancel=AsyncMock(side_effect=cancel_error),
    )
    return SimpleNamespace(
        assistants=SimpleNamespace(
            search=AsyncMock(return_value=[{"assistant_id": "synthetic-assistant"}]),
            get_graph=AsyncMock(return_value={"nodes": []}),
            get_schemas=AsyncMock(return_value={"input_schema": {}}),
        ),
        threads=SimpleNamespace(
            create=AsyncMock(return_value={"thread_id": THREAD}),
            get_state=AsyncMock(return_value=projection or {"values": {"result": RESULT}}),
        ),
        runs=runs,
    )


class SmokeIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def run_smoke(self, client):
        self.artifacts = {}

        def capture(path, content, *args, **kwargs):
            self.artifacts[path.name] = json.loads(content)
            return len(content)

        with patch.object(smoke, "get_client", return_value=client), \
                patch("sys.argv", ["smoke"]), \
                patch.object(smoke.Path, "mkdir"), \
                patch.object(smoke.Path, "write_text", autospec=True, side_effect=capture), \
                patch("builtins.print"):
            await smoke.main()

    def assert_cancelled_exact_run(self, client):
        client.runs.cancel.assert_awaited_once_with(
            THREAD, CREATED_RUN, wait=True, action="interrupt")
        self.assertEqual(self.artifacts["receipt.json"]["run_id"], CREATED_RUN)
        client.runs.list.assert_not_awaited()

    async def test_exact_run_and_its_stream_result_succeed(self):
        # Latest thread state is a projection, and may already reflect other work.
        client = client_double(projection={"values": {"result": {"status": "other-run"}}})
        await self.run_smoke(client)
        receipt = self.artifacts["receipt.json"]
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(receipt["run_id"], CREATED_RUN)
        self.assertEqual(receipt["result"], RESULT)
        client.runs.get.assert_awaited_once_with(THREAD, CREATED_RUN)
        client.runs.list.assert_not_awaited()
        client.runs.cancel.assert_not_awaited()

    async def test_error_stream_cannot_borrow_another_runs_success(self):
        client = client_double(
            chunks=[("error", {"message": "created run failed"})],
            run={"run_id": OTHER_RUN, "status": "success"})
        with self.assertRaises(RuntimeError):
            await self.run_smoke(client)
        self.assertEqual(self.artifacts["receipt.json"]["status"], "failed")
        client.runs.get.assert_not_awaited()
        self.assert_cancelled_exact_run(client)

    async def test_get_response_must_match_created_identity(self):
        client = client_double(run={"run_id": OTHER_RUN, "status": "success"})
        with self.assertRaises(ValueError):
            await self.run_smoke(client)
        self.assertEqual(self.artifacts["receipt.json"]["status"], "failed")
        self.assert_cancelled_exact_run(client)

    async def test_failed_exact_run_cannot_pass_from_stream_result(self):
        client = client_double(run={"run_id": CREATED_RUN, "status": "error"})
        with self.assertRaises(ValueError):
            await self.run_smoke(client)
        self.assertEqual(self.artifacts["receipt.json"]["status"], "failed")
        self.assert_cancelled_exact_run(client)

    async def test_latest_thread_result_cannot_replace_missing_stream_result(self):
        client = client_double(chunks=[("metadata", {"run_id": CREATED_RUN})])
        with self.assertRaises(ValueError):
            await self.run_smoke(client)
        self.assertEqual(self.artifacts["receipt.json"]["status"], "failed")
        self.assert_cancelled_exact_run(client)

    async def test_stream_metadata_cannot_change_created_identity(self):
        client = client_double(chunks=[("metadata", {"run_id": OTHER_RUN})])
        with self.assertRaises(ValueError):
            await self.run_smoke(client)
        client.runs.get.assert_not_awaited()
        self.assert_cancelled_exact_run(client)

    async def test_missing_creation_identity_is_not_success(self):
        client = client_double(created_run=None, chunks=[("values", {"result": RESULT})])
        with self.assertRaises(ValueError):
            await self.run_smoke(client)
        receipt = self.artifacts["receipt.json"]
        self.assertEqual(receipt["status"], "failed")
        self.assertNotIn("run_id", receipt)
        client.runs.get.assert_not_awaited()
        client.runs.cancel.assert_not_awaited()
        client.runs.list.assert_not_awaited()

    async def test_cancellation_retains_unknown_and_cancels_exact_created_run(self):
        client = client_double(chunks=[], stream_error=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            await self.run_smoke(client)
        receipt = self.artifacts["receipt.json"]
        self.assertEqual(receipt["status"], "unknown")
        self.assertEqual(receipt["error_type"], "CancelledError")
        self.assertTrue(receipt["exact_run_cancel_requested"])
        self.assert_cancelled_exact_run(client)

    async def test_unknown_before_creation_does_not_guess_run_to_cancel(self):
        client = client_double(created_run=None, chunks=[], stream_error=TimeoutError())
        with self.assertRaises(TimeoutError):
            await self.run_smoke(client)
        self.assertEqual(self.artifacts["receipt.json"]["status"], "unknown")
        client.runs.get.assert_not_awaited()
        client.runs.cancel.assert_not_awaited()
        client.runs.list.assert_not_awaited()

    async def test_cleanup_failure_does_not_hide_original_cancellation(self):
        client = client_double(chunks=[], stream_error=asyncio.CancelledError(),
                               cancel_error=RuntimeError("synthetic cleanup failure"))
        with self.assertRaises(asyncio.CancelledError):
            await self.run_smoke(client)
        receipt = self.artifacts["receipt.json"]
        self.assertEqual(receipt["status"], "unknown")
        self.assertEqual(receipt["error_type"], "CancelledError")
        self.assertEqual(receipt["cleanup_error_type"], "RuntimeError")
        self.assertNotIn("exact_run_cancel_requested", receipt)
        self.assert_cancelled_exact_run(client)


if __name__ == "__main__":
    unittest.main()
