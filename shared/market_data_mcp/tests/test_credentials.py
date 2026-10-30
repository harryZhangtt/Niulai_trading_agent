import json
from pathlib import Path
import tempfile
import unittest

from shared.market_data_mcp.auth.credential_store import save_credentials


class CredentialTests(unittest.TestCase):
    def test_atomic_private_replace_and_failed_input_preserves_prior_file(self):
        parent = Path(__file__).resolve().parents[3] / '.market-data-mcp/tmp'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as folder:
            location = Path(folder) / 'credentials/provider.json'
            save_credentials(location, {'api_key': 'synthetic-first'})
            self.assertEqual(location.stat().st_mode & 0o777, 0o600)
            self.assertEqual(location.parent.stat().st_mode & 0o777, 0o700)
            with self.assertRaises(ValueError):
                save_credentials(location, {'api_key': 'bad\nvalue'})
            self.assertEqual(json.loads(location.read_text())['api_key'], 'synthetic-first')
            save_credentials(location, {'api_key': 'synthetic-second'})
            self.assertEqual(json.loads(location.read_text())['api_key'], 'synthetic-second')
            self.assertEqual(list(location.parent.glob('.credential-*')), [])

    def test_symlink_is_not_overwritten(self):
        parent = Path(__file__).resolve().parents[3] / '.market-data-mcp/tmp'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as folder:
            target = Path(folder) / 'target.json'
            target.write_text('unchanged')
            link = Path(folder) / 'link.json'
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                save_credentials(link, {'api_key': 'synthetic'})
            self.assertEqual(target.read_text(), 'unchanged')
