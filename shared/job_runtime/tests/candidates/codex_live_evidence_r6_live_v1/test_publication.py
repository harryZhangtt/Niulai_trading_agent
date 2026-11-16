import tempfile,unittest
from pathlib import Path
from _loader import module
from _support import public_projection
class T(unittest.TestCase):
 def test_strict_projection_and_disguised_nested_secrets(self):
  pub=module("publication");c=module("contracts")
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);r=pub.publish(root/"private",root/"public",{"terminal_outcome":"PASS"},public_projection());self.assertTrue(r["private_committed"] and r["public_committed"] and r["recovery_complete"])
  for evidence in ({"nested":{"value":"Bearer disguised-token"}},{"nested":[{"value":"password=synthetic"}]},{"credential_value":"x"}):
   with tempfile.TemporaryDirectory() as d:
    root=Path(d)
    with self.assertRaises(c.ContractError):pub.publish(root/"private",root/"public",evidence,public_projection())
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);bad=public_projection();bad["extra"]=1
   with self.assertRaises(c.ContractError):pub.publish(root/"private",root/"public",{"x":1},bad)
 def test_partial_publication_rolls_back_with_receipt(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)
   with self.assertRaises(module("publication").PublicationError) as caught:module("publication").publish(root/"private",root/"public",{"x":1},public_projection(),fail_after_private=True)
   receipt=caught.exception.receipt;self.assertTrue(receipt["partial_publication"] and receipt["rolled_back"] and receipt["recovery_complete"]);self.assertFalse((root/"private").exists() or (root/"public").exists());self.assertTrue(Path(receipt["receipt_path"]).is_file())
