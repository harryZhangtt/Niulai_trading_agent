import unittest

from shared.research_sources.acquisition_validation import validate_dispatch
from shared.research_sources.artifacts import SourceError


class AcquisitionValidationTests(unittest.TestCase):
    def test_distinct_question_and_operation_id_grammars(self):
        questions = {"pricing.v1:issuer": {
            "source_roles": ["issuer document"],
            "capability_ids": ["web_search"],
        }}
        result = validate_dispatch(
            "search-pricing", {"search_query": [{"q": "pricing"}]},
            questions=questions, question_ids=["pricing.v1:issuer"],
            source_role="issuer document", one_item=True,
        )
        self.assertEqual(result[:2], ("search", "search_query"))
        with self.assertRaisesRegex(SourceError, "ACQ_OPERATION_ID"):
            validate_dispatch("search.pricing", {"search_query": [{"q": "pricing"}]})

    def test_public_url_role_and_capability_fail_before_reservation(self):
        questions = {
            "one": {"source_roles": ["issuer"], "capability_ids": ["official_document"]},
            "two": {"source_roles": ["customer"], "capability_ids": ["web_search"]},
        }
        with self.assertRaisesRegex(SourceError, "ACQ_SOURCE_ROLE"):
            validate_dispatch(
                "open-one", {"open": [{"ref_id": "https://example.com/report"}]},
                questions=questions, question_ids=["one", "two"],
                source_role="issuer", one_item=True,
            )
        with self.assertRaisesRegex(SourceError, "ACQ_CAPABILITY_OPERATION"):
            validate_dispatch(
                "open-two", {"open": [{"ref_id": "https://example.com/report"}]},
                questions=questions, question_ids=["two"],
                source_role="customer", one_item=True,
            )
        for url in ["https://localhost/report", "https://127.0.0.1/report", "https://example.com/report#fragment"]:
            with self.subTest(url=url), self.assertRaisesRegex(SourceError, "ACQ_URL_INVALID"):
                validate_dispatch("open-url", {"open": [{"ref_id": url}]})


if __name__ == "__main__":
    unittest.main()
