import errno,json,os,sqlite3,stat,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from shared.research_sources.artifacts import ROOT
from shared.research_sources.information_yield_v5_contracts import ArtifactRefV5,digest_v5
from ._v5_support import build_v5_batch,mutate_fresh_v5
from .evaluator_v5 import evaluate_fresh_eiy_evaluation_v5,evaluate_fresh_now_evaluation_v5
from . import cli_v5,publisher_v1 as publisher
from .publisher_v1 import CANONICAL_INFORMATION_YIELD_V5_ROOT,EiyPublisherV1Error,_safe_root,publish_eiy_result_v1,publish_now_diagnostic_v1
class PublisherV1Tests(unittest.TestCase):
 def root(self):
  base=ROOT/'investment/runtime';base.mkdir(parents=True,exist_ok=True,mode=0o700);tmp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(tmp.cleanup);return Path(tmp.name)
 def path(self,ref):return ArtifactRefV5.from_mapping(ref).resolve(ROOT)
 def issued(self):return evaluate_fresh_eiy_evaluation_v5(fresh_evaluation=build_v5_batch(self)[1])
 def test_atomic_bundle_relative_refs_and_idempotent_same_bytes(self):
  issued=self.issued();root=self.root();one=publish_eiy_result_v1(issued,publication_root=root);two=publish_eiy_result_v1(issued,publication_root=root);self.assertEqual(one,two);index_path=self.path(one['index_ref']);object_dir=self.path(one['custody_ref']).parent;index=json.loads(index_path.read_text());custody=json.loads(self.path(one['custody_ref']).read_text());self.assertEqual(index['custody_ref'],one['custody_ref']);[ArtifactRefV5.from_mapping(custody[k]) for k in ('evaluation_ref','custody_ref','context_ref','result_ref','canonical_policy_ref')];self.assertEqual(set(object_dir.iterdir()),{object_dir/x for x in ('context.json','result.json','custody.json')})
  for directory in (root,root/'objects',root/'index',object_dir,root/'index/.locks'):self.assertEqual((os.lstat(directory).st_uid,stat.S_IMODE(os.lstat(directory).st_mode)),(os.getuid(),0o700))
  for file in (object_dir/'context.json',object_dir/'result.json',object_dir/'custody.json',index_path,root/'index/.locks/eval-v3.lock'):
   observed=os.lstat(file);self.assertTrue(stat.S_ISREG(observed.st_mode));self.assertEqual((observed.st_uid,stat.S_IMODE(observed.st_mode),observed.st_nlink),(os.getuid(),0o600,1))
 def test_one_byte_partial_final_index_is_recovered(self):
  issued=self.issued();root=self.root();index=root/'index'/'eval-v3.json';index.parent.mkdir(parents=True,mode=0o700);index.write_bytes(b'x');index.chmod(0o600);result=publish_eiy_result_v1(issued,publication_root=root);self.assertEqual(self.path(result['index_ref']).read_bytes(),json.dumps(json.loads(self.path(result['index_ref']).read_text()),sort_keys=True,separators=(',',':')).encode()+b'\n')
 def test_partial_index_rename_unknown_is_reconciled(self):
  issued=self.issued();root=self.root();first=publish_eiy_result_v1(issued,publication_root=root);index=self.path(first['index_ref']);index.write_bytes(b'x');real=os.rename
  def fault(source,target):
   if Path(source)==index:real(source,target);raise OSError(errno.EIO,'/Users/private/rename')
   return real(source,target)
  with patch('tuning.evals.information_fetch.information_yield.publisher_v1.os.rename',side_effect=fault):again=publish_eiy_result_v1(issued,publication_root=root)
  self.assertEqual(self.path(again['index_ref']).read_bytes(),self.path(first['index_ref']).read_bytes())
 def test_index_fsync_unknown_after_link_is_reconciled(self):
  issued=self.issued();root=self.root();first=publish_eiy_result_v1(issued,publication_root=root);index=self.path(first['index_ref']);index.unlink();module='tuning.evals.information_fetch.information_yield.publisher_v1';from . import publisher_v1 as pub;real=pub._fsync
  def fault(path):
   if Path(path)==index.parent and index.exists():raise OSError('/Users/private/fsync')
   return real(path)
  with patch(module+'._fsync',side_effect=fault):again=publish_eiy_result_v1(issued,publication_root=root)
  self.assertTrue(self.path(again['index_ref']).is_file())
 def test_bundle_rename_unknown_reconciles(self):
  issued=self.issued();root=self.root();real=os.rename
  def fault(source,target):real(source,target);raise OSError(errno.EIO,'/Users/private/rename')
  with patch('tuning.evals.information_fetch.information_yield.publisher_v1.os.rename',side_effect=fault):result=publish_eiy_result_v1(issued,publication_root=root)
  self.assertEqual(publish_eiy_result_v1(issued,publication_root=root),result)
 def test_boundary_errors_are_fixed_and_private_markers_sanitized(self):
  issued=self.issued();marker='/Users/private/account.sqlite'
  with patch('tuning.evals.information_fetch.information_yield.publisher_v1._write_fd',side_effect=OSError(marker)):
   with self.assertRaises(EiyPublisherV1Error) as caught:publish_eiy_result_v1(issued,publication_root=self.root())
  self.assertEqual(str(caught.exception),'EIY_PUBLICATION_UNKNOWN');self.assertNotIn(marker,str(caught.exception))
  with patch('tuning.evals.information_fetch.information_yield.publisher_v1._safe_root',side_effect=sqlite3.OperationalError(marker)):
   with self.assertRaisesRegex(EiyPublisherV1Error,'^EIY_PUBLICATION_UNKNOWN$'):publish_eiy_result_v1(issued,publication_root=self.root())
 def test_symlink_and_dot_alias_roots_fixed_fail(self):
  issued=self.issued();base=self.root();real=base/'real';real.mkdir();alias=base/'alias';alias.symlink_to(real,target_is_directory=True)
  for root in (alias,str(base)+'/./dot'):
   with self.assertRaisesRegex(EiyPublisherV1Error,'EIY_PUBLICATION_CONFLICT'):publish_eiy_result_v1(issued,publication_root=root)
 def test_later_symlink_leaves_earlier_0755_ancestor_unchanged(self):
  issued=self.issued();base=self.root();early=base/'early';early.mkdir(mode=0o755);target=base/'target';target.mkdir();(early/'later').symlink_to(target,target_is_directory=True);before=stat.S_IMODE(os.lstat(early).st_mode)
  with self.assertRaisesRegex(EiyPublisherV1Error,'EIY_PUBLICATION_CONFLICT'):publish_eiy_result_v1(issued,publication_root=early/'later'/'missing')
  self.assertEqual((before,stat.S_IMODE(os.lstat(early).st_mode)),(0o755,0o755));self.assertFalse((target/'missing').exists())
 def test_repeated_and_trailing_separators_create_nothing(self):
  issued=self.issued();base=self.root()
  for raw in (str(base)+'/repeat//child',str(base)+'/trailing/'):
   with self.subTest(raw=raw):
    with self.assertRaisesRegex(EiyPublisherV1Error,'EIY_PUBLICATION_CONFLICT'):publish_eiy_result_v1(issued,publication_root=raw)
  self.assertFalse((base/'repeat').exists());self.assertFalse((base/'trailing').exists())
 def test_existing_unsafe_mode_fixed_fails_unchanged(self):
  issued=self.issued();base=self.root();unsafe=base/'unsafe';unsafe.mkdir(mode=0o700);unsafe.chmod(0o777)
  try:
   with self.assertRaisesRegex(EiyPublisherV1Error,'EIY_PUBLICATION_CONFLICT'):publish_eiy_result_v1(issued,publication_root=unsafe/'child')
   self.assertEqual(stat.S_IMODE(os.lstat(unsafe).st_mode),0o777);self.assertFalse((unsafe/'child').exists())
  finally:unsafe.chmod(0o700)
 def test_nominal_missing_suffix_created_private_and_durable(self):
  issued=self.issued();base=self.root();root=base/'new-a'/'new-b';publish_eiy_result_v1(issued,publication_root=root)
  self.assertEqual(stat.S_IMODE(os.lstat(base/'new-a').st_mode),0o700);self.assertEqual(stat.S_IMODE(os.lstat(root).st_mode),0o700);self.assertTrue((root/'index'/'eval-v3.json').is_file())
 def test_cli_admits_only_exact_canonical_root_before_checker(self):
  expected=ROOT/'tuning/runtime/information-yield-v5';self.assertEqual(CANONICAL_INFORMATION_YIELD_V5_ROOT,expected)
  with patch.object(cli_v5,'_load_ref',return_value={}) as load,patch.object(cli_v5,'check_eiy_evaluation_v5',return_value='fresh') as checker,patch.object(cli_v5,'evaluate_fresh_eiy_evaluation_v5',return_value='issued'),patch.object(cli_v5,'publish_eiy_result_v1',return_value={'status':'published'}) as publish,patch('builtins.print'):
   self.assertEqual(cli_v5.main(['--evaluation-ref','ignored.json','--publication-root',str(expected),'--mode','evaluation']),0)
  load.assert_called_once();checker.assert_called_once();publish.assert_called_once_with('issued',publication_root=expected)
 def test_cli_rejects_omitted_and_raw_alias_roots_before_checker(self):
  canonical=str(CANONICAL_INFORMATION_YIELD_V5_ROOT);variants=[None,canonical+'/',canonical.replace('/tuning/','//tuning/'),canonical.replace('/information-yield-v5','/./information-yield-v5'),str(Path(canonical).parent/'alias')]
  with patch.object(cli_v5,'_load_ref') as load,patch.object(cli_v5,'check_eiy_evaluation_v5') as checker:
   for value in variants:
    args=['--evaluation-ref','ignored.json','--mode','evaluation']
    if value is not None:args[2:2]=['--publication-root',value]
    with self.subTest(value=value):
     with self.assertRaisesRegex(cli_v5.InformationYieldV5CliError,'^EIY_PUBLICATION_ROOT_NOT_CANONICAL$'):cli_v5.main(args)
  load.assert_not_called();checker.assert_not_called()
 def test_existing_final_root_modes_fixed_fail_unchanged_without_children(self):
  issued=self.issued()
  for mode in (0o755,0o711,0o777):
   base=self.root();root=base/f'root-{mode:o}';root.mkdir(mode=0o700);root.chmod(mode)
   try:
    with self.subTest(mode=oct(mode)):
     with self.assertRaisesRegex(EiyPublisherV1Error,'EIY_PUBLICATION_CONFLICT'):publish_eiy_result_v1(issued,publication_root=root)
     self.assertEqual(stat.S_IMODE(os.lstat(root).st_mode),mode);self.assertFalse((root/'objects').exists());self.assertFalse((root/'index').exists())
   finally:root.chmod(0o700)
 def test_canonical_root_missing_suffix_created_under_temporary_workspace(self):
  base=self.root();workspace=base/'workspace';workspace.mkdir(mode=0o755);(workspace/'tuning').mkdir(mode=0o755);(workspace/'tuning/runtime').mkdir(mode=0o755);canonical=workspace/'tuning/runtime/information-yield-v5'
  with patch.object(publisher,'ROOT',workspace),patch.object(publisher,'CANONICAL_INFORMATION_YIELD_V5_ROOT',canonical):self.assertEqual(_safe_root(str(canonical)),canonical)
  self.assertEqual(stat.S_IMODE(os.lstat(canonical).st_mode),0o700);self.assertEqual(stat.S_IMODE(os.lstat(workspace/'tuning/runtime').st_mode),0o755)
 def test_internal_directory_modes_fixed_fail_unchanged(self):
  issued=self.issued();digest=issued.to_audit_mapping()['result_sha256']
  for location in ('objects','index','object','.locks'):
   for mode in (0o755,0o711,0o777):
    base=self.root()
    if location=='objects':target=base/'objects'
    elif location=='index':target=base/'index'
    elif location=='object':(base/'objects').mkdir(mode=0o700);target=base/'objects'/digest
    else:(base/'index').mkdir(mode=0o700);target=base/'index/.locks'
    target.mkdir(mode=0o700);target.chmod(mode)
    with self.subTest(location=location,mode=oct(mode)):
     with self.assertRaisesRegex(EiyPublisherV1Error,'EIY_PUBLICATION_CONFLICT'):publish_eiy_result_v1(issued,publication_root=base)
     self.assertEqual(stat.S_IMODE(os.lstat(target).st_mode),mode)
 def test_internal_directory_symlinks_fixed_fail_unchanged(self):
  issued=self.issued();digest=issued.to_audit_mapping()['result_sha256']
  for location in ('objects','index','object','.locks'):
   base=self.root();target=base/'target';target.mkdir(mode=0o700)
   if location=='objects':link=base/'objects'
   elif location=='index':link=base/'index'
   elif location=='object':(base/'objects').mkdir(mode=0o700);link=base/'objects'/digest
   else:(base/'index').mkdir(mode=0o700);link=base/'index/.locks'
   link.symlink_to(target,target_is_directory=True)
   with self.subTest(location=location):
    with self.assertRaisesRegex(EiyPublisherV1Error,'EIY_PUBLICATION_CONFLICT'):publish_eiy_result_v1(issued,publication_root=base)
    self.assertTrue(link.is_symlink());self.assertEqual(list(target.iterdir()),[])
 def test_idempotent_reuse_rejects_unsafe_artifact_files_unchanged(self):
  # Existing context mode 0644.
  issued=self.issued();root=self.root();published=publish_eiy_result_v1(issued,publication_root=root);context=self.path(published['custody_ref']).parent/'context.json';context.chmod(0o644)
  with self.assertRaisesRegex(EiyPublisherV1Error,'EIY_PUBLICATION_CONFLICT'):publish_eiy_result_v1(issued,publication_root=root)
  self.assertEqual(stat.S_IMODE(os.lstat(context).st_mode),0o644);context.chmod(0o600)
  # Existing result wrong-owner metadata (mocked named stat) is rejected before bytes are accepted.
  issued=self.issued();root=self.root();published=publish_eiy_result_v1(issued,publication_root=root);result_file=self.path(published['custody_ref']).parent/'result.json';real_stat=publisher.os.stat
  def wrong_owner(path,*args,**kwargs):
   observed=real_stat(path,*args,**kwargs)
   if path=='result.json' and kwargs.get('dir_fd') is not None:
    values=list(observed);values[4]=os.getuid()+1;return os.stat_result(values)
   return observed
  with patch.object(publisher.os,'stat',side_effect=wrong_owner):
   with self.assertRaisesRegex(EiyPublisherV1Error,'EIY_PUBLICATION_CONFLICT'):publish_eiy_result_v1(issued,publication_root=root)
  self.assertEqual(os.lstat(result_file).st_uid,os.getuid())
  # Existing custody hardlink (nlink 2) is rejected unchanged.
  issued=self.issued();root=self.root();published=publish_eiy_result_v1(issued,publication_root=root);custody=self.path(published['custody_ref']);other=root/'custody-hardlink';os.link(custody,other)
  with self.assertRaisesRegex(EiyPublisherV1Error,'EIY_PUBLICATION_CONFLICT'):publish_eiy_result_v1(issued,publication_root=root)
  self.assertEqual(os.lstat(custody).st_nlink,2);other.unlink()
  # Existing final index symlink is rejected unchanged.
  issued=self.issued();root=self.root();published=publish_eiy_result_v1(issued,publication_root=root);index=self.path(published['index_ref']);target=root/'index-target';index.rename(target);index.symlink_to(target)
  with self.assertRaisesRegex(EiyPublisherV1Error,'EIY_PUBLICATION_CONFLICT'):publish_eiy_result_v1(issued,publication_root=root)
  self.assertTrue(index.is_symlink())
 def test_lock_and_staging_files_require_private_metadata(self):
  issued=self.issued();root=self.root();published=publish_eiy_result_v1(issued,publication_root=root);lock=root/'index/.locks/eval-v3.lock';lock.chmod(0o644)
  with self.assertRaisesRegex(EiyPublisherV1Error,'EIY_PUBLICATION_CONFLICT'):publish_eiy_result_v1(issued,publication_root=root)
  self.assertEqual(stat.S_IMODE(os.lstat(lock).st_mode),0o644);lock.chmod(0o600)
  other=root/'lock-hardlink';os.link(lock,other)
  with self.assertRaisesRegex(EiyPublisherV1Error,'EIY_PUBLICATION_CONFLICT'):publish_eiy_result_v1(issued,publication_root=root)
  self.assertEqual(os.lstat(lock).st_nlink,2);other.unlink()
  class FixedUuid:hex='fixed'
  staging=root/'index/.index-pending-fixed';staging.write_bytes(b'x');staging.chmod(0o644)
  with patch.object(publisher.uuid,'uuid4',return_value=FixedUuid()):
   with self.assertRaisesRegex(EiyPublisherV1Error,'EIY_PUBLICATION_CONFLICT'):publish_eiy_result_v1(issued,publication_root=root)
  self.assertEqual((staging.read_bytes(),stat.S_IMODE(os.lstat(staging).st_mode)),(b'x',0o644))
 def test_private_key_and_absolute_embedded_ref_rejected(self):
  marker='/Users/private/key';issued=self.issued();issued._result['private_key']=marker;issued._result['result_sha256']=digest_v5({k:v for k,v in issued._result.items() if k!='result_sha256'})
  with self.assertRaises(EiyPublisherV1Error) as caught:publish_eiy_result_v1(issued,publication_root=self.root())
  self.assertEqual(str(caught.exception),'EIY_V5_RESULT_INVALID');self.assertNotIn(marker,str(caught.exception))
  issued=self.issued();issued._envelope['evaluation_ref']={'path':marker,'sha256':'0'*64}
  with self.assertRaisesRegex(EiyPublisherV1Error,'^EIY_V5_RESULT_INVALID$'):publish_eiy_result_v1(issued,publication_root=self.root())
 def test_conflicting_valid_index_and_v3_v4_rejected(self):
  _f,fresh,_,_=build_v5_batch(self);root=self.root();first=evaluate_fresh_eiy_evaluation_v5(fresh_evaluation=fresh);publish_eiy_result_v1(first,publication_root=root)
  def hard(data):
   row=next(f for f in data['facts'] if f['split']=='development');chain=row['arms']['F']['canonical_units'][0]['chain_ids'][0];row['hard_failures']=[{'code':'MISSING_TRACE','chain_ids':[chain]}]
  second=evaluate_fresh_eiy_evaluation_v5(fresh_evaluation=mutate_fresh_v5(fresh,hard))
  with self.assertRaisesRegex(EiyPublisherV1Error,'EIY_INDEX_CONFLICT'):publish_eiy_result_v1(second,publication_root=root)
  for version,code in [('information-yield-result-3','EIY_V3_PUBLICATION_REJECTED'),('information-yield-result-4','EIY_V4_PUBLICATION_REJECTED')]:
   with self.assertRaisesRegex(EiyPublisherV1Error,code):publish_eiy_result_v1({'schema_version':version},publication_root=root)
 def test_now_uses_separate_issued_type_and_publisher(self):
  issued=evaluate_fresh_now_evaluation_v5(fresh_evaluation=build_v5_batch(self,confirmation=0,development=0,mode='now_diagnostic')[1]);root=self.root();self.assertEqual(publish_now_diagnostic_v1(issued,publication_root=root)['status'],'published')
  with self.assertRaisesRegex(EiyPublisherV1Error,'ACQ_EIY_V5_NOW_BOUNDARY'):publish_eiy_result_v1(issued,publication_root=root)
if __name__=='__main__':unittest.main()
