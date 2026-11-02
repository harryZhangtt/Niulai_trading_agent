"""Candidate transport failure contracts; real slash acceptance is separate."""
import fcntl
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from shared.job_runtime.skill_tui import run, sha, native_completion

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'.job-runtime/tests'
FAKE='''#!INTERPRETER
import os,tty,time
from pathlib import Path
tty.setraw(0)
def emit(s):os.write(1,s.encode())
def expect(s):
 b=b""
 while len(b)<len(s):b+=os.read(0,len(s)-len(b))
 assert b==s,(b,s)
BEFORE_READY
emit("\\x1b]7501;state=idle:app=codex\\x1b\\\\")
expect(b"/skills")
emit("/skills use skills")
expect(b"\\r")
SCENARIO
emit("Skills Choose an action")
expect(b"\\r");emit("enter insert $ ")
expect(b"ego-browser");emit("ego-browser")
expect(b"\\r");emit("$ego-browser")
b=b""
while not b.endswith(b"\\x1b[201~"):b+=os.read(0,1)
emit("Pasted text")
expect(b"\\r")
Path("dispatched").write_text("yes")
AFTER_DISPATCH
emit("\\x1b]7501;state=idle:app=codex\\x1b\\\\")
expect(b"\\x01\\x0b/quit");emit("/quit exit Codex")
expect(b"\\r");emit("Session ID: 11111111-1111-1111-1111-111111111111\\n")
'''


class SkillTuiTests(unittest.TestCase):
    def setUp(self):
        BASE.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=BASE);self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)
        self.home=self.path/'auth';self.home.mkdir(mode=0o700)
        p=self.home/'auth.json';p.write_text('{"synthetic":true}');p.chmod(0o600)
        self.cli=self.path/'codex'
        p=self.path/'SKILL.md';p.write_text('Synthetic fixture')
        self.skill={'name':'ego-browser','path':str(p),'sha256':sha(p)}
        self.profile={'codex_bin':str(self.cli),'model':'gpt-6.1-sol','effort':'low','timeout_seconds':5,
            'auth_home':str(self.home),'max_output_bytes':65536,'approval_mode':'never','writable_roots':[]}

    def execute(self,scenario='',after='',before='',native=True):
        # Kernel shebangs cannot contain a venv interpreter path with spaces.
        self.cli.write_text(FAKE.replace('INTERPRETER','/usr/bin/env python3').replace('SCENARIO',scenario).replace('AFTER_DISPATCH',after).replace('BEFORE_READY',before))
        self.cli.chmod(0o700)
        def completion(*_):
            if native and (self.path/'run/work/dispatched').exists():
                return {'thread_id':'11111111-1111-1111-1111-111111111111','turn_completed':True,
                        'native_skill_attachment_verified':True}
        with patch('shared.job_runtime.skill_tui.native_completion',side_effect=completion):
            return run(self.profile,'Synthetic task',self.skill,workspace=ROOT,
                       run_directory=self.path/'run',expected_cli_sha256=sha(self.cli))

    def test_real_pty_selection_precedes_model_turn_and_does_not_self_accept(self):
        r=self.execute()
        self.assertEqual(r['status'],'succeeded',r)
        self.assertTrue(r['receipt']['skill_selected'])
        self.assertTrue((self.path/'run/work/dispatched').exists())
        self.assertTrue(r['receipt']['native_skill_attachment_verified'])
        self.assertEqual(r['receipt']['thread_id'],'11111111-1111-1111-1111-111111111111')

    def test_interactive_client_has_a_controlling_terminal(self):
        r=self.execute('fd=os.open("/dev/tty",os.O_RDWR);os.close(fd)')
        self.assertEqual(r['status'],'succeeded',r)

    def test_terminal_device_probe_is_answered_before_selection(self):
        r=self.execute(before='emit("\\x1b[?u");expect(b"\\x1b[?0u")')
        self.assertEqual(r['status'],'succeeded',r)
        self.assertIn('keyboard',r['receipt']['terminal_queries_answered'])

    def test_untrusted_hooks_are_explicitly_declined_and_not_trusted(self):
        r=self.execute(before='emit("\\x1b[?2026hHooks need review 3. Continue without trusting\\x1b[?2026l");expect(b"\\x1b")')
        self.assertEqual(r['status'],'succeeded',r)
        self.assertTrue(r['receipt']['hooks_skipped_untrusted'])

    def test_unsupported_slash_is_permanent_and_never_dispatches(self):
        r=self.execute('emit("Unrecognized command");time.sleep(10)')
        self.assertEqual((r['status'],r['code']),('failed','SKILL_TUI_UNSUPPORTED_SLASH'))
        self.assertFalse(r['receipt']['turn_submitted'])
        self.assertFalse((self.path/'run/work/dispatched').exists())

    def test_timeout_after_submission_is_unknown_and_not_replayed(self):
        self.profile['timeout_seconds']=5
        r=self.execute(after='time.sleep(10)',native=False)
        self.assertEqual(r['status'],'unknown',r)
        self.assertTrue(r['receipt']['turn_submitted'])
        self.assertTrue((self.path/'run/turn-intent.json').exists())
        self.assertFalse(r['receipt']['automatic_retry'])

    def test_idle_text_without_native_completion_never_accepts(self):
        self.profile['timeout_seconds']=5
        r=self.execute(native=False)
        self.assertEqual(r['status'],'unknown',r)
        self.assertIsNone(r['receipt']['turn_completed'])

    def test_native_history_requires_prompt_skill_and_completed_turn(self):
        import sqlite3
        run_dir=self.path/'native';(run_dir/'sqlite').mkdir(parents=True);(run_dir/'work').mkdir()
        history=self.home/'sessions/fixture.jsonl';history.parent.mkdir()
        rows=[{'type':'response_item','payload':{'type':'message','role':'user','content':[{'text':'$ego-browser Synthetic task'}]}},
            {'type':'response_item','payload':{'type':'message','role':'user','content':[{'text':f'<skill><name>ego-browser</name><path>{self.skill["path"]}</path></skill>'}]}},
            {'type':'event_msg','payload':{'type':'task_started','turn_id':'t'}},
            {'type':'event_msg','payload':{'type':'task_complete','turn_id':'t','completed_at':1}}]
        import json
        history.write_text(''.join(json.dumps(x)+'\n' for x in rows))
        with sqlite3.connect(run_dir/'sqlite/state_5.sqlite') as c:
            c.execute('create table threads(id text,rollout_path text,cwd text)')
            c.execute('insert into threads values(?,?,?)',('thread',str(history),str(run_dir/'work')))
        self.assertTrue(native_completion(run_dir,self.home,self.skill,'Synthetic task')['turn_completed'])
        with self.assertRaisesRegex(ValueError,'SKILL_TUI_NATIVE_SKILL_NOT_INJECTED'):
            native_completion(run_dir,self.home,self.skill,'Different task')
        rows[-1]['payload']['turn_id']='different';history.write_text(''.join(json.dumps(x)+'\n' for x in rows))
        with self.assertRaisesRegex(ValueError,'SKILL_TUI_NATIVE_TURN_BINDING'):
            native_completion(run_dir,self.home,self.skill,'Synthetic task')

    def test_shared_auth_contention_is_only_retryable_before_dispatch(self):
        self.cli.write_text('#!'+sys.executable+'\n');self.cli.chmod(0o700)
        fd=os.open(self.home/'runtime.lock',os.O_CREAT|os.O_RDWR,0o600)
        self.addCleanup(os.close,fd);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        r=run(self.profile,'Synthetic task',self.skill,workspace=ROOT,
              run_directory=self.path/'run',expected_cli_sha256=sha(self.cli))
        self.assertEqual(r['status'],'retryable')
        self.assertEqual(r['receipt']['effect_state'],'not_started')
        self.assertFalse((self.path/'run').exists())


if __name__=='__main__':unittest.main()
