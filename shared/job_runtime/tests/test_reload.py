"""An invalid schedule edit must not replace a healthy live allocation."""
import copy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from shared.job_runtime.engine import Engine
from shared.job_runtime.service import validate_reload
from shared.job_runtime.config import ConfigError

ROOT = Path(__file__).resolve().parents[3]


class ReloadTests(unittest.TestCase):
    def test_persisted_schedule_change_rejected_and_original_engine_remains_usable(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.job-runtime/tests') as folder:
            job = {'id': 'synthetic-reload', 'enabled': True, 'schedule': {'kind': 'interval', 'seconds': 300}, 'replay_safe': True}
            calls = []
            def dispatch(job, context):
                calls.append(context['slot_id']); return {'status': 'succeeded', 'code': 'FIXTURE_OK', 'receipt': {'fixture': True}}
            engine = Engine(Path(folder) / 'engine', [job], {'max_attempts': 2, 'backoff_seconds': 1, 'max_backoff_seconds': 2},
                            dispatch, workspace_root=ROOT)
            now = datetime.now(timezone.utc); engine.tick(now)
            changed = copy.deepcopy(job); changed['schedule']['seconds'] = 600
            with self.assertRaisesRegex(ConfigError, 'SCHEDULE_CHANGE_REQUIRES_NEW_JOB_ID'):
                validate_reload(engine, [changed])
            self.assertEqual(engine.jobs[job['id']]['schedule']['seconds'], 300)
            validate_reload(engine, [job])
            renamed = dict(changed, id='synthetic-reload-new-version')
            validate_reload(engine, [renamed])
            self.assertEqual(engine.tick(now)['unknown'], 0)
