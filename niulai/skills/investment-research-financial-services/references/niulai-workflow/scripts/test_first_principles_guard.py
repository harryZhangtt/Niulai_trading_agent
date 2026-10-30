"""Integration failures for the additive first-principles publication contract."""
import copy
import tempfile
import unittest
import rationale_guard as g
from test_rationale_guard import RationaleFixture, STAMP
from test_adoption_checks import example_packet


class FirstPrinciplesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = RationaleFixture(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.f = copy.deepcopy(self.base)
        self.f.refresh()

    def build(self):
        p = example_packet()
        # Preserve source-availability consistency with the earlier fixture cutoff.
        def replace(value):
            if isinstance(value, dict):
                return {k: replace(v) for k, v in value.items()}
            if isinstance(value, list): return [replace(v) for v in value]
            return STAMP if value == p['as_of'] else value
        p = replace(p)
        self.f.save('adoption_input', p)
        self.f.save('adoption_output', g.adoption_math.calculate(p))
        self.f.card['issued_at'] = g.FIRST_PRINCIPLES_AT
        self.f.card['first_principles'] = {
            'version': g.FIRST_PRINCIPLES_VERSION,
            'questions': {k: self.f.link() for k in g.FIRST_PRINCIPLES_QUESTIONS},
            'numerical_check': {'input_artifact_id': 'adoption_input', 'output_artifact_id': 'adoption_output'}}
        self.f.refresh()
        self.f.review['first_principles_check'] = self.f.link()
        self.f.save('r_review', self.f.review)

    def validate(self, **kw):
        return g.validate(self.f.rec, root=self.f.install, **kw)

    def test_genuine_old_record_stays_valid(self):
        self.assertEqual(self.validate()['status'], 'validated')

    def test_new_card_requires_extension(self):
        self.f.card['issued_at'] = g.FIRST_PRINCIPLES_AT
        self.f.refresh()
        with self.assertRaisesRegex(g.RationaleError, 'First-principles'): self.validate()

    def test_observed_publication_prevents_backdating(self):
        with self.assertRaisesRegex(g.RationaleError, 'First-principles'):
            self.validate(observed_publication_times=[g.FIRST_PRINCIPLES_AT])

    def test_saved_receipt_prevents_backdating(self):
        self.f.rec['persistence']['receipts'][0]['confirmed_at'] = g.FIRST_PRINCIPLES_AT
        with self.assertRaisesRegex(g.RationaleError, 'First-principles'): self.validate()

    def test_new_complete_packet_passes(self):
        self.build()
        self.assertEqual(self.validate()['status'], 'validated')

    def test_missing_independent_challenge(self):
        self.build()
        del self.f.review['first_principles_check']
        self.f.save('r_review', self.f.review)
        with self.assertRaisesRegex(g.RationaleError, 'Independent first-principles'): self.validate()

    def test_missing_customer_alternative_evidence(self):
        self.build()
        del self.f.card['first_principles']['questions']['alternatives_and_economics']
        self.f.refresh()
        with self.assertRaisesRegex(g.RationaleError, 'Six first-principles'): self.validate()

    def test_numeric_output_tamper(self):
        self.build()
        self.f.save('adoption_output', {'status': 'calculated'})
        with self.assertRaisesRegex(g.RationaleError, 'recomputation'): self.validate()

    def test_missing_save_receipt(self):
        self.build()
        self.f.rec['persistence']['receipts'] = [r for r in self.f.rec['persistence']['receipts'] if r['artifact_id'] != 'adoption_output']
        with self.assertRaisesRegex(g.RationaleError, 'persistence receipts'): self.validate()

    def test_missing_review_hash(self):
        self.build()
        del self.f.review['artifact_hashes']['adoption_input']
        self.f.save('r_review', self.f.review)
        with self.assertRaisesRegex(g.RationaleError, 'review hash'): self.validate()

    def test_wrong_subject_rejected(self):
        self.build()
        p = example_packet()
        p['subject'] = 'OTHER'
        self.f.save('adoption_input', p)
        with self.assertRaisesRegex(g.RationaleError, 'subject/cutoff'): self.validate()

    def test_optional_old_extension_still_checked(self):
        self.f.card['first_principles'] = {'version': 'invented'}
        self.f.refresh()
        with self.assertRaisesRegex(g.RationaleError, 'First-principles'): self.validate()


if __name__ == '__main__': unittest.main()
