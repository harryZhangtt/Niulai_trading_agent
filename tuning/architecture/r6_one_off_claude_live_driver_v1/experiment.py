from pathlib import Path
import tempfile
from shared.job_runtime.candidates.r6_one_off_claude_live_driver_v1 import run_provider_free
ROOT=Path(__file__).resolve().parents[3]
FIX=ROOT/"shared/job_runtime/tests/fixtures/r6_one_off_claude_live_driver_v1"
CASES=(("nominal","PASS"),("auth","STOP"),("timeout","UNKNOWN"),("publication","UNKNOWN"))
def main():
    with tempfile.TemporaryDirectory(dir=FIX) as temp:
        for i,(case,expected) in enumerate(CASES):
            result=run_provider_free(Path(temp)/("case"+str(i)),case)
            if result.evidence["status"]!=expected: raise SystemExit("FAIL "+case)
            print(case+":"+expected)
if __name__=="__main__": main()
