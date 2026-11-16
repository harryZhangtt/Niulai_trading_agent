import copy,json,unittest
from pathlib import Path
from shared.job_runtime.candidates.r6_data_quality_fable_allocation_integration_v2.manifest import validate,MANIFEST_SHA256
R=Path(__file__).resolve().parents[5];V=json.loads((R/"shared/job_runtime/tests/fixtures/r6_data_quality_fable_allocation_integration_v2/manifest-v2.json").read_text())
class T(unittest.TestCase):
 def test_exact(self):self.assertEqual(validate(copy.deepcopy(V)),V)
 def test_drift(self):
  x=copy.deepcopy(V);x["prompt"]["bytes"]=1
  with self.assertRaises(Exception):validate(x)
if __name__=="__main__":unittest.main()
