import unittest
from investment.research.acquisition_trace import check_eiy_matched_case,issue_eiy_matched_case
from shared.research_sources.artifacts import SourceError
class RejectedEiyV2Tests(unittest.TestCase):
 def test_v2_check_fixed_fails(self):
  with self.assertRaisesRegex(SourceError,'EIY_SELF_ASSERTED_BUNDLE_DISABLED'):check_eiy_matched_case({})
 def test_v2_publication_fixed_fails(self):
  with self.assertRaisesRegex(SourceError,'EIY_SELF_ASSERTED_BUNDLE_DISABLED'):issue_eiy_matched_case(None,request={})
if __name__=='__main__':unittest.main()
