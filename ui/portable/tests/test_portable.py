"""Copied-bundle checks; UI_SKILL_BUNDLE selects a fresh named candidate."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

AREA=Path(__file__).resolve().parents[1]
BUNDLE=Path(os.environ.get('UI_SKILL_BUNDLE',str(AREA/'candidate/ui-skill-router'))).absolute()
TEST_RUNTIME=Path(os.environ.get('UI_SKILL_TEST_RUNTIME',str(AREA/'runtime'))).absolute()
sys.path.insert(0,str(AREA))
from verify import verify,receipt_name,SUPPORTED_NAMES
from manage import install,rollback,exclusive_rename
from package import adapt_script


def load_resolver(root):
 spec=importlib.util.spec_from_file_location('portable_resolver',root/'scripts/resolve.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


class PortableTests(unittest.TestCase):
 def setUp(self):
  TEST_RUNTIME.mkdir(parents=True,exist_ok=True)
  self.tmp=tempfile.TemporaryDirectory(dir=TEST_RUNTIME);self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.foreign=self.root/'foreign';self.foreign.mkdir()
  self.router=load_resolver(BUNDLE)
  self.name=json.loads((BUNDLE/'manifest.json').read_bytes())['name']

 def cli(self,*arguments,cwd=None,bundle=BUNDLE):
  result=subprocess.run([sys.executable,'-I','-B',str(bundle/'scripts/resolve.py'),*arguments],cwd=cwd or self.foreign,capture_output=True,text=True,timeout=10)
  return result,json.loads(result.stdout)

 def test_aliases_dependencies_authorities_and_missing_pencil(self):
  value=self.router.resolve(requested=['uiux','taste','gsap-react'])
  self.assertEqual([item['skill'] for item in value['selected']],['ui-ux-pro-max','design-taste-frontend','gsap-core','gsap-react'])
  self.assertEqual(self.router.resolve(decisions=['taste-design','cinematic'])['errors'],['conflicting_visual_authorities'])
  self.assertEqual(self.router.resolve(decisions=['backend-only'])['selected'],[])
  self.assertEqual(self.router.resolve(decisions=['backend-only','layout'])['errors'],['non_ui_conflict'])
  blocked=self.router.resolve(decisions=['pencil-design']);self.assertEqual(blocked['status'],'UI_ROUTE_BLOCKED');self.assertEqual(blocked['missing_tools'],['pencil'])
  guidance=self.router.resolve(decisions=['pencil-design'],guidance_only=True);self.assertEqual(guidance['status'],'UI_ROUTE_OK');self.assertFalse(guidance['declared_tools_satisfied'])

 def test_all_selectors_work_and_only_pencil_requires_declared_tool(self):
  catalog=json.loads((BUNDLE/'catalog.json').read_bytes());self.assertEqual(len(catalog['decisions']),23)
  for decision in catalog['decisions']:
   with self.subTest(decision=decision):
    result=self.router.resolve(decisions=[decision],available_tools=['pencil']);self.assertEqual(result['status'],'UI_ROUTE_OK')
    self.assertTrue(all(Path(item['path']).is_absolute() and Path(item['path']).is_relative_to(BUNDLE) and Path(item['path']).name=='GUIDE.md' for item in result['selected']))

 def test_copied_bundle_runs_from_foreign_cwd_without_source_or_history(self):
  copied=self.root/'self-contained';shutil.copytree(BUNDLE,copied)
  (self.foreign/'catalog.json').write_text('poisoned ambient catalog')
  history=self.foreign/'.taste-skill';history.mkdir();(history/'history.json').write_text('poisoned ambient history')
  before={str(p.relative_to(copied)):(p.stat().st_mtime_ns,p.read_bytes()) for p in copied.rglob('*') if p.is_file()}
  result,value=self.cli('--decision','async-state','--decision','react-performance',bundle=copied)
  self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(value['execution_cwd'],str(self.foreign));self.assertEqual(value['bundle_root'],str(copied))
  self.assertTrue(all(Path(item['path']).is_relative_to(copied) for item in value['selected']))
  self.assertNotIn(str(BUNDLE),json.dumps(value))
  self.assertEqual(before,{str(p.relative_to(copied)):(p.stat().st_mtime_ns,p.read_bytes()) for p in copied.rglob('*') if p.is_file()})
  self.assertEqual((history/'history.json').read_text(),'poisoned ambient history')

 def test_manifest_closure_single_entrypoint_and_source_hashes(self):
  self.assertEqual(verify(BUNDLE),[])
  self.assertEqual([str(p.relative_to(BUNDLE)) for p in BUNDLE.rglob('SKILL.md')],['SKILL.md'])
  manifest=json.loads((BUNDLE/'manifest.json').read_bytes())
  # Frozen legacy receipts remain valid even after maintained source changes.
  # A selected fresh candidate must additionally match today's source provenance.
  if 'UI_SKILL_BUNDLE' in os.environ:
   for path,item in manifest['files'].items():
    if 'source_sha256' not in item:continue
    source=AREA.parent.parent/item['source_path']
    self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),item['source_sha256'],path)

 def test_escaped_guide_symlink_and_escaped_link_fail_closed(self):
  copied=self.root/'corrupt';shutil.copytree(BUNDLE,copied)
  guide=copied/'experts/frontend-design/GUIDE.md';guide.unlink();guide.symlink_to(self.foreign/'outside.md');(self.foreign/'outside.md').write_text('untrusted')
  result=load_resolver(copied).resolve(decisions=['visual-direction']);self.assertEqual(result['status'],'UI_ROUTE_FAILED')
  self.assertTrue(verify(copied))
  guide.unlink();guide.write_text((BUNDLE/'experts/frontend-design/GUIDE.md').read_text()+'\n[escape](../../../foreign/outside.md)\n')
  manifest=json.loads((copied/'manifest.json').read_bytes());manifest['files']['experts/frontend-design/GUIDE.md']['sha256']=hashlib.sha256(guide.read_bytes()).hexdigest();(copied/'manifest.json').write_text(json.dumps(manifest))
  self.assertIn('escaped_link:experts/frontend-design/GUIDE.md',verify(copied))

 def test_stdlib_search_resources_work_from_unrelated_directory(self):
  command=[sys.executable,'-B',str(BUNDLE/'experts/ui-ux-pro-max/scripts/search.py'),'keyboard focus modal','--domain','ux']
  result=subprocess.run(command,cwd=self.foreign,capture_output=True,text=True,timeout=15)
  self.assertEqual(result.returncode,0,result.stderr);self.assertIn('UI Pro Max Search Results',result.stdout)

 def test_target_tool_missing_has_no_global_fallback_or_writes(self):
  before=list(self.foreign.iterdir())
  result=subprocess.run([sys.executable,'-I','-B',str(BUNDLE/'scripts/tools.py'),'playwright','--project',str(self.foreign),'--describe'],cwd=self.root,capture_output=True,text=True,timeout=10)
  self.assertEqual(result.returncode,2);self.assertEqual(json.loads(result.stdout)['code'],'target_local_tool_missing');self.assertEqual(before,list(self.foreign.iterdir()))

 def test_atomic_no_overwrite_and_owned_rollback_only(self):
  skills=self.root/'skills';stage=self.root/'staging';skills.mkdir();stage.mkdir()
  receipt=install(BUNDLE,skills,stage,allowed_root=self.root)
  target=skills/self.name
  self.assertEqual(verify(target),[]);self.assertEqual(list(stage.iterdir()),[])
  with self.assertRaisesRegex(ValueError,'destination_exists'):install(BUNDLE,skills,stage,allowed_root=self.root)
  with self.assertRaisesRegex(ValueError,'ownership_mismatch'):rollback(skills,stage,'not-the-owner',allowed_root=self.root,name=self.name)
  (target/'user-added.txt').write_text('preserve user changes')
  with self.assertRaisesRegex(ValueError,'owned_payload_changed'):rollback(skills,stage,receipt['installation_id'],allowed_root=self.root,name=self.name)
  (target/'user-added.txt').unlink()
  rollback(skills,stage,receipt['installation_id'],allowed_root=self.root,name=self.name)
  self.assertFalse(target.exists())
  source=self.root/'source';existing=self.root/'existing';source.mkdir();existing.mkdir();(source/'owned.txt').write_text('owned')
  with self.assertRaisesRegex(ValueError,'destination_exists'):exclusive_rename(source,existing)
  self.assertTrue((source/'owned.txt').exists());self.assertEqual(list(existing.iterdir()),[])

 def test_staging_inside_discovery_and_external_write_are_rejected(self):
  skills=self.root/'skills';skills.mkdir();stage=skills/'hidden-stage';stage.mkdir()
  with self.assertRaisesRegex(ValueError,'staging_must_be_outside'):install(BUNDLE,skills,stage,allowed_root=self.root)
  stage=self.root/'stage';stage.mkdir();allowed=self.root/'allowed';allowed.mkdir()
  with self.assertRaisesRegex(ValueError,'external_write_not_authorized'):install(BUNDLE,skills,stage,allowed_root=allowed)
  self.assertFalse((skills/self.name).exists())

 def test_supported_identity_publication_and_matching_receipt(self):
  skills=self.root/'skills';stage=self.root/'stage';skills.mkdir();stage.mkdir()
  for name in sorted(SUPPORTED_NAMES):
   with self.subTest(name=name):
    copied=self.root/name;shutil.copytree(BUNDLE,copied)
    manifest=json.loads((copied/'manifest.json').read_bytes());manifest['name']=name
    entry=copied/'SKILL.md';entry.write_text(entry.read_text().replace('name: '+self.name+'\n','name: '+name+'\n',1))
    manifest['files']['SKILL.md']['sha256']=hashlib.sha256(entry.read_bytes()).hexdigest()
    (copied/'manifest.json').write_text(json.dumps(manifest))
    self.assertEqual(verify(copied),[])
    receipt=install(copied,skills,stage,allowed_root=self.root)
    self.assertEqual(receipt['target'],str(skills/name));self.assertEqual(receipt['name'],name)
    self.assertTrue((skills/name/receipt_name(name)).is_file())
    # Receipt identity must agree with the manifest, even if its digest is valid.
    owned=skills/name/receipt_name(name);raw=owned.read_bytes();altered=json.loads(raw);altered['name']='other-package';owned.write_text(json.dumps(altered))
    self.assertIn('ownership_receipt_invalid',verify(skills/name));owned.write_bytes(raw)
    options={} if name=='ui-skill-router' else {'name':name}
    rollback(skills,stage,receipt['installation_id'],allowed_root=self.root,**options)
    self.assertFalse((skills/name).exists())

 def adapted_expert(self,name,relative):
  copied=self.root/name;shutil.copytree(BUNDLE/'experts'/name,copied)
  source=AREA.parent/'skills'/name/relative
  adapted=adapt_script(source.read_text(),name+'/'+relative)
  if 'UI_SKILL_BUNDLE' in os.environ:
   self.assertEqual((BUNDLE/'experts'/name/relative).read_text(),adapted)
  (copied/relative).write_text(adapted)
  return copied/relative

 def test_hallmark_index_and_missing_index_do_not_write_package(self):
  script=self.adapted_expert('hallmark','scripts/theme.mjs')
  expert=script.parent.parent
  before={str(p.relative_to(expert)):(p.stat().st_mtime_ns,p.read_bytes()) for p in expert.rglob('*') if p.is_file()}
  result=subprocess.run(['node',str(script),'index'],cwd=self.foreign,capture_output=True,text=True,timeout=10)
  self.assertNotEqual(result.returncode,0);self.assertIn('PORTABLE_PACKAGE_READ_ONLY',result.stderr)
  self.assertEqual(before,{str(p.relative_to(expert)):(p.stat().st_mtime_ns,p.read_bytes()) for p in expert.rglob('*') if p.is_file()})
  index=expert/'references/themes/index.json';index.unlink()
  result=subprocess.run(['node',str(script),'list'],cwd=self.foreign,capture_output=True,text=True,timeout=10)
  self.assertNotEqual(result.returncode,0);self.assertIn('PORTABLE_PACKAGE_READ_ONLY',result.stderr);self.assertFalse(index.exists())

 def test_design_md_missing_target_and_foreign_dependency_fail_closed(self):
  script=self.adapted_expert('design-md-chrome','scripts/extract.mjs')
  missing=self.root/'missing-project'
  env=dict(os.environ,UI_SKILL_PROJECT=str(missing))
  result=subprocess.run(['node',str(script),'--url','https://example.com/'],cwd=self.foreign,env=env,capture_output=True,text=True,timeout=10)
  self.assertEqual(result.returncode,1);self.assertEqual(result.stdout,'')
  self.assertEqual(json.loads(result.stderr),{'status':'DESIGN_MD_FAILED','code':'DEPENDENCY_OR_PAGE'})
  self.assertFalse(missing.exists())
  foreign=self.root/'foreign-dependency.mjs';foreign.write_text("console.log('FOREIGN_DEPENDENCY_EXECUTED'); export const chromium={};\n")
  local_link=self.foreign/'external-link.mjs';local_link.symlink_to(foreign)
  for dependency in (foreign,local_link):
   with self.subTest(dependency=dependency.name):
    env.update(UI_SKILL_PROJECT=str(self.foreign),UI_SKILL_PLAYWRIGHT=str(dependency))
    result=subprocess.run(['node',str(script),'--url','https://example.com/'],cwd=self.foreign,env=env,capture_output=True,text=True,timeout=10)
    self.assertEqual(result.returncode,1);self.assertNotIn('FOREIGN_DEPENDENCY_EXECUTED',result.stdout)
    self.assertEqual(json.loads(result.stderr)['status'],'DESIGN_MD_FAILED')

 @unittest.skipUnless((BUNDLE/'scripts/activate.py').is_file(),'legacy bundle predates explicit session activation')
 def test_activation_keeps_bundle_read_only_and_bounds_target_state(self):
  copied=self.root/'activation-bundle';shutil.copytree(BUNDLE,copied)
  durable=(copied/'scripts/session.py').is_file()
  def snapshot():
   return {str(p.relative_to(copied)):(p.stat().st_mtime_ns,p.read_bytes()) for p in copied.rglob('*') if p.is_file()}
  def activate():
   env=dict(os.environ,CODEX_THREAD_ID='portable-test-thread-1',CODEX_SESSION_ID='shared-tree-is-not-identity')
   result=subprocess.run([sys.executable,'-B',str(copied/'scripts/activate.py'),'--project',str(self.foreign)],cwd=self.foreign,env=env,capture_output=True,text=True,timeout=15)
   return result,json.loads(result.stdout)
  before=snapshot();result,value=activate()
  self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(value['status'],'HARRY_UI_SESSION_ENABLED')
  if durable:
   self.assertEqual(value['persistence'],'native-thread')
   self.assertTrue(value['record_ref'].startswith('.ui-skill-runtime/harry-ui-sessions/'))
   record=self.foreign/value['record_ref'];self.assertTrue(record.is_file())
   self.assertEqual(record.stat().st_mode&0o777,0o600)
  else:
   self.assertEqual(value['expert_count'],22);self.assertEqual(value['target_project'],str(self.foreign))
   self.assertFalse(value['persistent_state_written']);self.assertFalse(value['full_expert_bodies_loaded'])
   self.assertEqual(list(self.foreign.iterdir()),[])
  self.assertEqual(value['bundle_fingerprint'],hashlib.sha256((copied/'manifest.json').read_bytes()).hexdigest())
  self.assertEqual(before,snapshot())
  target_before={str(p.relative_to(self.foreign)):p.read_bytes() for p in self.foreign.rglob('*') if p.is_file()}
  guide=copied/'experts/frontend-design/GUIDE.md';guide.write_text(guide.read_text()+'\ncorrupt fixture\n')
  before=snapshot();result,value=activate()
  self.assertEqual(result.returncode,1);self.assertEqual(value['status'],'HARRY_UI_SESSION_FAILED')
  self.assertEqual(value['code'],'bundle_verification_failed' if durable else 'bundle_or_target_validation_failed')
  self.assertEqual(before,snapshot())
  self.assertEqual(target_before,{str(p.relative_to(self.foreign)):p.read_bytes() for p in self.foreign.rglob('*') if p.is_file()})

if __name__=='__main__':unittest.main()
