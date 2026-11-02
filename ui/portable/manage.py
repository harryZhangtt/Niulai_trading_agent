#!/usr/bin/env python3
"""Explicit owned skill publication, atomic upgrade, and rollback."""
import argparse
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import uuid
sys.dont_write_bytecode=True
from verify import verify,receipt_name,SUPPORTED_NAMES,read_file

NAME='ui-skill-router'

def require(value,code):
 if not value:raise ValueError(code)

def canonical_directory(path):
 path=Path(path).absolute();require(path.is_dir() and path.resolve()==path,'directory_unsafe');return path

def exclusive_rename(source,destination):
 libc=ctypes.CDLL(None,use_errno=True)
 if sys.platform=='darwin':
  function=libc.renamex_np;function.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint];result=function(os.fsencode(source),os.fsencode(destination),4)
 elif sys.platform.startswith('linux') and hasattr(libc,'renameat2'):
  function=libc.renameat2;function.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint];result=function(-100,os.fsencode(source),-100,os.fsencode(destination),1)
 else:raise ValueError('exclusive_rename_unavailable')
 if result:
  code=ctypes.get_errno()
  if code in {errno.EEXIST,errno.ENOTEMPTY}:raise ValueError('destination_exists')
  raise OSError(code,os.strerror(code))

def atomic_exchange(source,destination):
 """Swap two existing paths atomically without a missing-discovery window."""
 libc=ctypes.CDLL(None,use_errno=True)
 if sys.platform=='darwin' and hasattr(libc,'renamex_np'):
  function=libc.renamex_np;function.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint]
  arguments=(os.fsencode(source),os.fsencode(destination),2)
 elif sys.platform.startswith('linux') and hasattr(libc,'renameat2'):
  function=libc.renameat2;function.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
  arguments=(-100,os.fsencode(source),-100,os.fsencode(destination),2)
 else:raise ValueError('atomic_exchange_unavailable')
 function.restype=ctypes.c_int
 if function(*arguments):
  code=ctypes.get_errno();raise OSError(code,os.strerror(code))

class UpgradeError(ValueError):
 def __init__(self,code,**recovery):
  super().__init__(code);self.recovery=recovery

def owned_payload(path,name,installation_id):
 """Validate exact owned bytes and receipt before any publication mutation."""
 require(isinstance(installation_id,str) and len(installation_id)==32
         and all(c in '0123456789abcdef' for c in installation_id),'ownership_mismatch')
 path=canonical_directory(path)
 require(not verify(path),'owned_payload_changed_or_missing')
 require(json.loads(read_file(path/'manifest.json',path,2*1024*1024))['name']==name,'ownership_mismatch')
 receipt=json.loads(read_file(path/receipt_name(name),path,4096))
 require(receipt.get('installation_id')==installation_id,'ownership_mismatch')
 return {'inode':path.stat().st_ino,'device':path.stat().st_dev,'receipt':receipt,
         'receipt_bytes':read_file(path/receipt_name(name),path,4096)}

def same_owned_payload(path,name,installation_id,snapshot):
 current=owned_payload(path,name,installation_id)
 require(current==snapshot,'owned_payload_changed_during_exchange')

def exchange_owned(target,stage,name,current_id,staged_id,current,staged):
 """Restore both original locations if post-exchange validation fails."""
 same_owned_payload(target,name,current_id,current)
 same_owned_payload(stage,name,staged_id,staged)
 atomic_exchange(stage,target)
 try:
  same_owned_payload(stage,name,current_id,current)
  same_owned_payload(target,name,staged_id,staged)
 except BaseException as error:
  try:
   atomic_exchange(stage,target)
  except BaseException as recovery_error:
   raise UpgradeError('upgrade_exchange_recovery_failed',target=str(target),
                      preserved_path=str(stage),reconcile_before_retry=True) from recovery_error
  raise UpgradeError('upgrade_post_exchange_mismatch_restored',target=str(target),
                     preserved_path=str(stage),reconcile_before_retry=True) from error

def boundaries(skills_root,stage_parent,allowed_root,allow_user_scope):
 skills_root=canonical_directory(skills_root);stage_parent=canonical_directory(stage_parent);allowed_root=canonical_directory(allowed_root)
 require(not stage_parent.is_relative_to(skills_root) and not skills_root.is_relative_to(stage_parent),'staging_must_be_outside_discovery_root')
 require(skills_root.stat().st_dev==stage_parent.stat().st_dev,'atomic_rename_requires_same_filesystem')
 if not allow_user_scope:require(skills_root.is_relative_to(allowed_root) and stage_parent.is_relative_to(allowed_root),'external_write_not_authorized')
 return skills_root,stage_parent

def install(bundle,skills_root,stage_parent,*,allowed_root,allow_user_scope=False):
 bundle=canonical_directory(bundle);require(not verify(bundle),'source_bundle_invalid')
 name=json.loads((bundle/'manifest.json').read_bytes())['name'];owned_receipt=receipt_name(name)
 skills_root,stage_parent=boundaries(skills_root,stage_parent,allowed_root,allow_user_scope);target=skills_root/name
 require(not target.exists() and not target.is_symlink(),'destination_exists')
 stage=Path(tempfile.mkdtemp(prefix=name+'-stage-',dir=stage_parent));shutil.rmtree(stage)
 try:
  shutil.copytree(bundle,stage,symlinks=False)
  require(not verify(stage),'staged_bundle_invalid')
  require(json.loads((stage/'manifest.json').read_bytes())['name']==name,'staged_identity_changed')
  identity=uuid.uuid4().hex;manifest_sha=hashlib.sha256((stage/'manifest.json').read_bytes()).hexdigest()
  receipt={'name':name,'installation_id':identity,'manifest_sha256':manifest_sha,'ownership':'this exact published payload only'}
  require(not (stage/owned_receipt).exists(),'source_contains_install_receipt')
  (stage/owned_receipt).write_text(json.dumps(receipt,sort_keys=True)+'\n');(stage/owned_receipt).chmod(0o600)
  require(not verify(stage),'ownership_receipt_invalid')
  exclusive_rename(stage,target)
  return {'status':'installed','target':str(target),**receipt}
 finally:
  if stage.exists():shutil.rmtree(stage)

def rollback(skills_root,stage_parent,installation_id,*,allowed_root,allow_user_scope=False,name=NAME):
 owned_receipt=receipt_name(name)
 skills_root,stage_parent=boundaries(skills_root,stage_parent,allowed_root,allow_user_scope);target=skills_root/name
 require(not verify(target),'owned_payload_changed_or_missing')
 require(json.loads((target/'manifest.json').read_bytes())['name']==name,'ownership_mismatch')
 receipt=json.loads((target/owned_receipt).read_bytes());require(receipt.get('installation_id')==installation_id,'ownership_mismatch')
 quarantine=stage_parent/(name+'-rollback-'+uuid.uuid4().hex)
 identity=target.stat().st_ino;exclusive_rename(target,quarantine)
 try:
  require(quarantine.stat().st_ino==identity and not verify(quarantine),'owned_payload_changed_during_rollback')
 except Exception:
  exclusive_rename(quarantine,target);raise
 shutil.rmtree(quarantine)
 return {'status':'removed_owned_payload','installation_id':installation_id}

def upgrade(bundle,skills_root,stage_parent,installation_id,*,allowed_root,allow_user_scope=False,name=None):
 bundle=canonical_directory(bundle);require(not verify(bundle),'source_bundle_invalid')
 candidate_name=json.loads(read_file(bundle/'manifest.json',bundle,2*1024*1024))['name']
 require(name is None or name==candidate_name,'upgrade_identity_mismatch');name=candidate_name
 owned_receipt=receipt_name(name)
 require(not (bundle/owned_receipt).exists() and not (bundle/owned_receipt).is_symlink(),
         'source_contains_install_receipt')
 skills_root,stage_parent=boundaries(skills_root,stage_parent,allowed_root,allow_user_scope)
 target=skills_root/name;current=owned_payload(target,name,installation_id)
 stage=Path(tempfile.mkdtemp(prefix=name+'-upgrade-',dir=stage_parent));shutil.rmtree(stage)
 preserve=False
 try:
  shutil.copytree(bundle,stage,symlinks=False)
  require(not verify(stage),'staged_bundle_invalid')
  require(json.loads(read_file(stage/'manifest.json',stage,2*1024*1024))['name']==name,'staged_identity_changed')
  identity=uuid.uuid4().hex
  receipt={'name':name,'installation_id':identity,
           'manifest_sha256':hashlib.sha256(read_file(stage/'manifest.json',stage,2*1024*1024)).hexdigest(),
           'ownership':'this exact published payload only'}
  (stage/owned_receipt).write_text(json.dumps(receipt,sort_keys=True)+'\n');(stage/owned_receipt).chmod(0o600)
  staged=owned_payload(stage,name,identity)
  same_owned_payload(target,name,installation_id,current)
  same_owned_payload(stage,name,identity,staged)
  # After this point a signal or unexpected exception must never delete a
  # directory which may now contain the prior published payload.
  preserve=True
  try:
   exchange_owned(target,stage,name,installation_id,identity,current,staged)
  except UpgradeError:
   raise
  except BaseException as error:
   raise UpgradeError('upgrade_exchange_outcome_requires_reconciliation',target=str(target),
                      preserved_path=str(stage),reconcile_before_retry=True) from error
  return {'status':'upgraded','target':str(target),**receipt,
          'rollback_path':str(stage),'rollback_installation_id':installation_id,
          'rollback_manifest_sha256':current['receipt']['manifest_sha256']}
 finally:
  if not preserve and stage.exists():shutil.rmtree(stage)

def restore_upgrade(skills_root,stage_parent,installation_id,rollback_path,rollback_installation_id,
                    *,allowed_root,allow_user_scope=False,name=NAME):
 receipt_name(name)
 skills_root,stage_parent=boundaries(skills_root,stage_parent,allowed_root,allow_user_scope)
 previous=canonical_directory(rollback_path)
 require(previous.parent==stage_parent and previous.name.startswith(name+'-upgrade-'),
         'rollback_path_not_owned_stage')
 target=skills_root/name
 current=owned_payload(target,name,installation_id)
 retained=owned_payload(previous,name,rollback_installation_id)
 exchange_owned(target,previous,name,installation_id,rollback_installation_id,current,retained)
 return {'status':'restored_previous_payload','target':str(target),**retained['receipt'],
         'rollback_path':str(previous),'rollback_installation_id':installation_id,
         'rollback_manifest_sha256':current['receipt']['manifest_sha256']}

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['install','rollback','upgrade','restore-upgrade']);p.add_argument('--bundle');p.add_argument('--skills-root',required=True);p.add_argument('--stage-parent',required=True);p.add_argument('--allowed-root',required=True);p.add_argument('--installation-id');p.add_argument('--rollback-path');p.add_argument('--rollback-installation-id');p.add_argument('--allow-user-scope',action='store_true');p.add_argument('--name',choices=sorted(SUPPORTED_NAMES));a=p.parse_args()
 try:
  options={'allowed_root':a.allowed_root,'allow_user_scope':a.allow_user_scope}
  if a.command in {'install','upgrade'}:require(a.bundle is not None,'bundle_required')
  if a.command!='install':require(a.installation_id is not None,'installation_id_required')
  if a.command=='install':result=install(a.bundle,a.skills_root,a.stage_parent,**options)
  elif a.command=='rollback':result=rollback(a.skills_root,a.stage_parent,a.installation_id,name=a.name or NAME,**options)
  elif a.command=='upgrade':result=upgrade(a.bundle,a.skills_root,a.stage_parent,a.installation_id,name=a.name,**options)
  else:
   require(a.rollback_path is not None and a.rollback_installation_id is not None,'rollback_identity_required')
   result=restore_upgrade(a.skills_root,a.stage_parent,a.installation_id,a.rollback_path,a.rollback_installation_id,name=a.name or NAME,**options)
  print(json.dumps(result,indent=2))
 except (OSError,ValueError) as error:print(json.dumps({'status':'UI_PORTABLE_MANAGEMENT_BLOCKED','code':str(error),**getattr(error,'recovery',{})}));raise SystemExit(2)
