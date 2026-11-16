from __future__ import annotations
import unittest
from tuning.probabilistic_manifold.development_inputs import _support


def row(index, x, y, query=False):
    return {"origin_id":f"o{index}","origin_index":1000 if query else index,"maturity_index":index,"features":{"x":float(x),"y":float(y)}}

class CorrectedSupportGeometryTests(unittest.TestCase):
    def test_insufficient_is_inconclusive(self):
        records=[row(i,i,i*i/10) for i in range(12)]+[row(99,1,1,True)]
        result=_support(records,12)
        self.assertEqual((result["status"],result["reason"]),("inconclusive","minimum_training_origins_not_met"))

    def test_zero_mad_is_inconclusive(self):
        records=[row(i,1,i) for i in range(18)]+[row(99,1,3,True)]
        result=_support(records,18)
        self.assertEqual((result["status"],result["reason"]),("inconclusive","zero_mad"))

    def test_deterministic_inside_edge_outside(self):
        training=[row(i,i,i*i/20) for i in range(20)]
        found={}
        for step in range(-200,601):
            x=step/20; query=row(99,x,x*x/20,True); result=_support(training+[query],20)
            found.setdefault(result["status"],(x,result))
        self.assertTrue({"inside","edge","outside"}.issubset(found))
        for status,(x,expected) in found.items():
            self.assertEqual(_support(training+[row(99,x,x*x/20,True)],20),expected)

    def test_old_min_distance_would_misclassify_isolated_duplicate(self):
        training=[row(i,i/20,(i/20)**2) for i in range(17)]+[row(17,100,80)]
        query=row(99,100,80,True)
        result=_support(training+[query],18)
        old_min_distance=0.0
        self.assertLessEqual(old_min_distance,result["training_loo_q95"])
        self.assertIn(result["status"],{"edge","outside"})
        self.assertGreater(result["query_k_distance"],result["training_loo_q95"])

if __name__=="__main__": unittest.main()
