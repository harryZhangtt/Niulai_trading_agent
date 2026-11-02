"""Actual macOS sandbox regression for a narrow scheduled artifact grant."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from shared.research_sources.artifacts import ROOT, private_path


class NarrowRootTests(unittest.TestCase):
    @unittest.skipUnless(Path('/usr/bin/sandbox-exec').is_file(),'macOS sandbox required')
    def test_already_private_ancestors_do_not_need_write_authority(self):
        base=private_path(ROOT/'.research-sources/web-access-test-tmp',create=True)
        with tempfile.TemporaryDirectory(dir=base) as tmp:
            out=private_path(Path(tmp)/'granted',create=True)
            policy='(version 1)(allow default)(deny file-write*)(allow file-write* (subpath '+json.dumps(str(out))+'))'
            code='from shared.research_sources.artifacts import save,read;import sys;ref=save(sys.argv[1],{"ok":True});assert read(ref)=={"ok":True};print("NARROW_ARTIFACT_OK")'
            r=subprocess.run(['/usr/bin/sandbox-exec','-p',policy,sys.executable,'-B','-c',code,str(out)],
                cwd=ROOT,capture_output=True,text=True,timeout=10)
            self.assertEqual(r.returncode,0,r.stderr[-1500:])
            self.assertEqual(r.stdout.strip(),'NARROW_ARTIFACT_OK')


if __name__=='__main__':unittest.main()
