from __future__ import annotations
import hashlib,json,os,stat,unittest
from pathlib import Path
REAL=Path(__file__).resolve().parents[5]
EVIDENCE=REAL/'tuning/architecture/r6_data_quality_blind_map_commitment_v7'
def actual(row):
 p=REAL/row['path'];lst=os.lstat(p);fd=os.open(p,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
 try:
  fst=os.fstat(fd);h=hashlib.sha256();size=0
  while True:
   chunk=os.read(fd,65536)
   if not chunk:break
   h.update(chunk);size+=len(chunk)
 finally:os.close(fd)
 if (lst.st_dev,lst.st_ino)!=(fst.st_dev,fst.st_ino):raise AssertionError(row['path'])
 return {'path':row['path'],'bytes':size,'sha256':h.hexdigest(),'mode':format(stat.S_IMODE(fst.st_mode),'04o')}
class EvidenceV7(unittest.TestCase):
 def test_closure_and_distinct_producer_are_exact_pending_not_active(self):
  closure=json.loads((EVIDENCE/'source-closure-v7.json').read_text());producer=json.loads((EVIDENCE/'distinct-producer-verification-v7.json').read_text())
  self.assertEqual('P0_V10_RECLOSURE_REQUIRED',closure['p0_reclosure']);self.assertEqual('REQUIRED_NOT_YET_PERFORMED',closure['fresh_independent_review'])
  self.assertFalse(closure['activation']);self.assertFalse(closure['countable']);self.assertFalse(closure['private_map_content_disclosed']);self.assertFalse(closure['label_values_disclosed'])
  rows=closure['v7_runtime_bindings']+closure['v7_source_schema_test_and_design_bindings']
  self.assertEqual(len(rows),len({row['path'] for row in rows}));self.assertTrue(all(actual(row)==row for row in rows))
  self.assertNotIn('source-closure-v7.json',{Path(row['path']).name for row in rows});self.assertNotIn('distinct-producer-verification-v7.json',{Path(row['path']).name for row in rows})
  self.assertIn('REVOKED_BY_LATER_OPEN_REVIEW',{row['state'] for row in closure['review_history']});self.assertEqual('CURRENT_OPEN_BASELINE',closure['review_history'][-1]['state'])
  self.assertEqual('3a1d63397c2c5732ec1f4a5f9b92a620e5da93cb6ede31ec4826ceb8adeed084',closure['baseline_open_review']['sha256'])
  self.assertEqual('PRODUCER_CLEAN_PENDING_FRESH_REVIEW_AND_P0_V10_HUMAN_AUTHORITY',producer['status'])
  self.assertFalse(producer['activation']);self.assertFalse(producer['trusted']);self.assertFalse(producer['countable'])
  for row in producer['artifacts'].values():self.assertEqual(actual(row),row)
  self.assertEqual([f'OPEN-V6-{i:02d}' for i in range(1,5)],[row['id'] for row in producer['closed_findings']])
  self.assertEqual(('PASS','CLEAN',0),(producer['test_evidence']['authoritative_label_scan']['status'],producer['test_evidence']['authoritative_label_scan']['decision'],producer['test_evidence']['authoritative_label_scan']['matches']))
  self.assertEqual(('DIAGNOSTIC_ONLY',False),(producer['test_evidence']['workspace_hygiene_audit']['decision'],producer['test_evidence']['workspace_hygiene_audit']['can_establish_clean']))
if __name__=='__main__':unittest.main()
