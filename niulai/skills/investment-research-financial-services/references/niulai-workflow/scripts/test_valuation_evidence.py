import unittest
from valuation_evidence import validate, VERSION, SECTIONS

class GateTests(unittest.TestCase):
    def record(self):
        return {'scope':'company_full','artifacts':[{'id':'model'}], 'valuation_evidence':{'version':VERSION, **{k:{'status':'evidenced','finding':'Inspectable analysis','artifact_refs':['model']} for k in SECTIONS}}}
    def test_complete(self): validate(self.record())
    def test_missing(self):
        with self.assertRaises(ValueError):validate({'scope':'company_full'})
    def test_missing_each_section(self):
        for name in SECTIONS:
            r=self.record();del r['valuation_evidence'][name]
            with self.assertRaises(ValueError):validate(r)
    def test_dangling(self):
        r=self.record();r['artifacts']=[]
        with self.assertRaises(ValueError):validate(r)
    def test_honest_limitation(self):
        r=self.record();s=r['valuation_evidence']['technical_confirmation'];s['status']='limited'
        with self.assertRaises(ValueError):validate(r)
        s['limitations']='History unavailable; no technical confirmation claimed';validate(r)
    def test_archived(self):validate({'scope':'fund_full','persistence':{'receipts':[{'confirmed_at':'2026-10-20T11:00:00Z'}]}})
    def test_new_receipt_rejected(self):
        with self.assertRaises(ValueError):validate({'scope':'fund_full','persistence':{'receipts':[{'confirmed_at':'2026-10-20T13:00:00Z'}]}})
    def test_forced_upgrade(self):
        with self.assertRaises(ValueError):validate({'scope':'fund_full','persistence':{'receipts':[{'confirmed_at':'2026-10-20T11:00:00Z'}]}},force=True)
if __name__=='__main__':unittest.main()
