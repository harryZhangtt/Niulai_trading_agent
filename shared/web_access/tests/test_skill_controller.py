from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from shared.research_sources.artifacts import ROOT
from shared.web_access import skill_acceptance as a


class SkillControllerTests(unittest.TestCase):
    def setUp(self):
        base=ROOT/'.job-runtime/tests';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.base=self.root/'candidate';self.base.mkdir(mode=0o700)
        self.path=self.base/'record.json'
        self.record={'execution_status':'pending','attempts':[],'label':'synthetic-no-real-service',
            'jobs':[{'id':'future.fixture','enabled':True,'replay_safe':False,'schedule':{'kind':'once',
                'at':(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(),'grace_seconds':60}}],
            'retry':{'max_attempts':3,'backoff_seconds':30,'max_backoff_seconds':120}}
        self.path.write_text(json.dumps(self.record))
        p=patch.object(a,'HERE',self.root);p.start();self.addCleanup(p.stop)

    def test_real_engine_entry_uses_current_timestamp_and_does_not_run_future_work(self):
        with patch.object(a,'run') as model:
            a.tick(self.path)
        model.assert_not_called()
        self.assertEqual(json.loads(self.path.read_text())['execution_status'],'pending')
        with sqlite3.connect(self.base/'engine/schedule.sqlite') as db:
            self.assertEqual(db.execute('select count(*) from jobs').fetchone()[0],1)
            self.assertEqual(db.execute('select count(*) from attempts').fetchone()[0],0)

    def test_controller_fault_is_sanitized_and_stops_on_next_tick(self):
        with patch.object(a,'Engine',side_effect=RuntimeError('SYNTHETIC_PRIVATE_CANARY')):
            a.tick(self.path)
        r=json.loads(self.path.read_text());self.assertEqual(r['execution_status'],'failed')
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY',json.dumps(r))
        with patch.object(a.subprocess,'run') as command,patch.object(a,'run') as model:
            a.tick(self.path)
        model.assert_not_called();self.assertEqual(command.call_args.args[0][1],'bootout')


if __name__=='__main__':unittest.main()
