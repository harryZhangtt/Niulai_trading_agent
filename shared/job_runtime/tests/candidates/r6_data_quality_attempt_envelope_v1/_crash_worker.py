from __future__ import annotations
import json, os, signal, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.bundle import AttemptBundleStore
bundle=json.loads(Path(sys.argv[1]).read_text(encoding='ascii'))
root=Path(sys.argv[2]);window=sys.argv[3];owner_root=Path(sys.argv[4])
def kill(observed):
    if observed!=window:raise AssertionError((observed,window))
    os.kill(os.getpid(),signal.SIGKILL)
AttemptBundleStore(root,'crash_'+window,kill,owner_root).commit(bundle)
raise AssertionError('crash hook returned')
