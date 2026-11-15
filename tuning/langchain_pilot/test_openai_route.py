"""Official endpoint, credential and failure controls; no provider calls."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from openai import AuthenticationError

from tuning.langchain_pilot import credentials
from tuning.langchain_pilot.graph import bounded_model_call, openai_model as default_model


class OpenAIRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path('.langchain-pilot/tmp'))
        self.env_file = Path(self.temp.name) / '.env'
        self.secret = 'sk-synthetic-private-test-only'

    def tearDown(self):
        self.temp.cleanup()

    def write_env(self, mode=0o600):
        self.env_file.write_text('OPENAI_API_KEY=' + self.secret + '\n')
        self.env_file.chmod(mode)

    async def test_official_responses_endpoint_ignores_ferry_base_env(self):
        observed = []
        async def send(request):
            observed.append(request)
            return httpx.Response(200, request=request, json={
                'id': 'resp_test', 'object': 'response', 'created_at': 1,
                'status': 'completed', 'model': 'gpt-6.1-sol',
                'output': [{'id': 'msg_test', 'type': 'message', 'role': 'assistant',
                            'status': 'completed', 'content': [
                                {'type': 'output_text', 'text': 'OK', 'annotations': []}]}],
                'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(send)) as http_client:
          with patch.dict(os.environ, {
                'OPENAI_API_KEY': self.secret, 'OPENAI_BASE_URL': 'http://127.0.0.1:8790/v1',
                'OPENAI_API_BASE': 'http://127.0.0.1:8790/v1',
                'LANGCHAIN_PILOT_BASE_URL': 'http://127.0.0.1:8790'}, clear=True):
            model = default_model(http_async_client=http_client).model_copy(update={'streaming': False})
            result = await model.ainvoke('Synthetic route test')
        self.assertIn('OK', str(result.content))
        self.assertEqual(len(observed), 1)
        self.assertEqual(str(observed[0].url), 'https://api.openai.com/v1/responses')
        self.assertEqual(json.loads(observed[0].content)['model'], 'gpt-6.1-sol')
        self.assertEqual(observed[0].headers['authorization'], 'Bearer ' + self.secret)

    async def test_missing_key_prevents_any_http_dispatch(self):
        calls = []
        async def send(*args, **kwargs):
            calls.append(True)
            raise AssertionError('No request permitted without a credential')
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(credentials, 'PRIVATE_ENV', self.env_file), \
                patch.object(httpx.AsyncClient, 'send', new=send):
            # Construction and Studio graph discovery still work without a key.
            model = default_model()
            with self.assertRaisesRegex(ValueError, 'OPENAI_API_KEY_REQUIRED'):
                await model.ainvoke('Synthetic missing-key test')
        self.assertEqual(calls, [])

    async def test_private_key_file_is_read_without_native_auth(self):
        self.write_env()
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(credentials, 'PRIVATE_ENV', self.env_file):
            self.assertEqual(credentials.openai_api_key(), self.secret)

    async def test_shared_readable_key_file_is_rejected(self):
        self.write_env(0o644)
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(credentials, 'PRIVATE_ENV', self.env_file):
            with self.assertRaisesRegex(ValueError, 'OWNER_PRIVATE'):
                credentials.openai_api_key()

    async def test_ferry_model_and_placeholder_key_are_rejected(self):
        with patch.dict(os.environ, {'LANGCHAIN_PILOT_MODEL': 'ferry-gpt-6-1-sol'}, clear=True):
            with self.assertRaisesRegex(ValueError, 'OPENAI_MODEL_REQUIRED'):
                default_model()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'ferry'}, clear=True):
            with self.assertRaisesRegex(ValueError, 'OPENAI_API_KEY_REQUIRED'):
                credentials.openai_api_key()

    async def test_sdk_auth_error_does_not_publish_key_in_graph_error(self):
        async def handler(request):
            raise AuthenticationError('Incorrect API key: ' + self.secret,
                                      response=httpx.Response(401, request=httpx.Request(
                                          'POST', 'https://api.openai.com/v1/responses')),
                                      body={'error': {'message': self.secret}})
        with self.assertRaisesRegex(RuntimeError, '^OPENAI_REQUEST_FAILED_401$') as caught:
            await bounded_model_call.awrap_model_call(None, handler)
        self.assertNotIn(self.secret, str(caught.exception))

    async def test_wrapped_sdk_auth_error_is_also_sanitized(self):
        async def send(request):
            return httpx.Response(401, request=request, json={
                'error': {'message': 'Bad key: ' + self.secret,
                          'type': 'invalid_request_error', 'code': 'invalid_api_key'}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(send)) as client:
            with patch.dict(os.environ, {'OPENAI_API_KEY': self.secret}, clear=True):
                model = default_model(http_async_client=client).model_copy(update={'streaming': False})
                async def handler(request):
                    return await model.ainvoke('Synthetic wrapped-error test')
                with self.assertRaisesRegex(RuntimeError, '^OPENAI_REQUEST_FAILED_401$') as caught:
                    await bounded_model_call.awrap_model_call(None, handler)
        self.assertNotIn(self.secret, str(caught.exception))


if __name__ == '__main__':
    unittest.main()
