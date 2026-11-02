#!/usr/bin/env python3
"""Offline, read-only portable bundle integrity and local-resource validation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import unquote,urlsplit

RECEIPT='.ui-skill-router-owned.json'
SUPPORTED_NAMES=frozenset({'ui-skill-router','harry-ui-skill-set'})

def receipt_name(name):
 if name not in SUPPORTED_NAMES:raise ValueError('manifest_identity_invalid')
 return '.'+name+'-owned.json'

def read_file(path,root,maximum=16*1024*1024):
 if path.resolve()!=path or not path.is_relative_to(root):raise ValueError('escaped_or_symlink_resource')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 with os.fdopen(fd,'rb') as f:
  if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):raise ValueError('nonregular_resource')
  raw=f.read(maximum+1)
 if len(raw)>maximum:raise ValueError('resource_too_large')
 return raw

def verify(directory):
 root=Path(directory).absolute();errors=[]
 try:
  if root.resolve()!=root or not root.is_dir():return ['bundle_root_unsafe']
  manifest_raw=read_file(root/'manifest.json',root,2*1024*1024);manifest=json.loads(manifest_raw)
  name=manifest.get('name')
  if name not in SUPPORTED_NAMES or manifest.get('expert_count')!=22 or manifest.get('decision_count')!=23:return ['manifest_identity_invalid']
  owned_receipt=receipt_name(name)
  files=manifest['files'];actual=set();total=0
  for path in root.rglob('*'):
   mode=path.lstat().st_mode
   if stat.S_ISDIR(mode):continue
   if not stat.S_ISREG(mode):errors.append('nonregular_resource:'+str(path.relative_to(root)));continue
   actual.add(str(path.relative_to(root)));total+=path.stat().st_size
  if len(actual)>10000 or total>64*1024*1024:errors.append('bundle_size_limit')
  permitted=set(files)|{'manifest.json'}
  if owned_receipt in actual:
   receipt=json.loads(read_file(root/owned_receipt,root,4096))
   if receipt.get('name')!=name or receipt.get('manifest_sha256')!=hashlib.sha256(manifest_raw).hexdigest() or not re.fullmatch('[a-f0-9]{32}',receipt.get('installation_id','')):errors.append('ownership_receipt_invalid')
   permitted.add(owned_receipt)
  if actual!=permitted:errors.append('unexpected_or_missing_files:'+str(sorted(actual^permitted)[:8]))
  for relative,item in files.items():
   p=Path(relative)
   if p.is_absolute() or '..' in p.parts:errors.append('manifest_path_unsafe');continue
   raw=read_file(root/p,root)
   if hashlib.sha256(raw).hexdigest()!=item['sha256']:errors.append('digest_mismatch:'+relative)
  if [p for p in actual if Path(p).name=='SKILL.md']!=['SKILL.md']:errors.append('extra_discoverable_entrypoint')
  front=read_file(root/'SKILL.md',root,65536).decode()
  if not re.match(r'\A---\nname: '+re.escape(name)+r'\ndescription: .+\n---',front):errors.append('entrypoint_metadata_invalid')
  catalog=json.loads(read_file(root/'catalog.json',root,65536))
  if set(catalog['skills'])!={p.split('/')[1] for p in actual if re.fullmatch('experts/[^/]+/GUIDE.md',p)}:errors.append('expert_roster_mismatch')
  if hashlib.sha256(read_file(root/'ROUTING-CARD.md',root)).hexdigest()!=manifest['routing_card_sha256']:errors.append('routing_card_mismatch')
  for relative in actual:
   p=root/relative
   if p.suffix=='.md':
    content=read_file(p,root).decode();content=re.sub(r'```.*?```','',content,flags=re.S);content=re.sub(r'`[^`\n]+`','',content)
    for match in re.finditer(r'\]\(([^\s)]+)(?:\s+[^)]*)?\)',content):
     target=match.group(1).strip('<>');parts=urlsplit(target)
     if parts.scheme or not parts.path:continue
     selected=(p.parent/unquote(parts.path)).resolve()
     if not selected.is_relative_to(root):errors.append('escaped_link:'+relative)
     elif not selected.exists():errors.append('broken_link:'+relative+'->'+target)
   if p.suffix in {'.mjs','.js'}:
    content=read_file(p,root).decode()
    for target in re.findall(r"(?:from\s*|import\s*\()\s*['\"](\.{1,2}/[^'\"]+)['\"]",content):
     selected=(p.parent/target).resolve()
     if not selected.is_relative_to(root):errors.append('escaped_module:'+relative)
     elif not selected.exists():errors.append('missing_module:'+relative+'->'+target)
 except (OSError,ValueError,KeyError,TypeError,UnicodeError,RuntimeError):errors.append('bundle_unreadable_or_invalid')
 return errors

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('bundle');a=p.parse_args();errors=verify(a.bundle)
 print(json.dumps({'status':'UI_PORTABLE_FAILED' if errors else 'UI_PORTABLE_OK','errors':errors},indent=2));raise SystemExit(bool(errors))
