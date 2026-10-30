#!/usr/bin/env python3
"""Read-only export audit. Never prints suspected credential values.

Designed for a selected export tree only. No home/profile traversal.
This is a bounded detector, not proof that every possible secret is absent.
"""
import argparse, json, re, hashlib
from pathlib import Path

PATTERNS = {
    'private_key': rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',
    'openai_api_key': rb'\bsk-(?:proj-)?[A-Za-z0-9_-]{30,}',
    'github_token': rb'\bgh[pousr]_[A-Za-z0-9]{30,}',
    'github_pat': rb'\bgithub_pat_[A-Za-z0-9_]{40,}',
    'aws_access_id': rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
    'jwt': rb'\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{15,}',
    'authenticated_url': rb'https?://[^\s/:@]{3,}:[^\s/@]{5,}@',
}
DENIED_NAMES = {'holdings_latest.json', 'assets_latest.json', 'analytics_latest.json',
                'research.sqlite', 'alerts.sqlite', 'workflow.json', 'alerts.json',
                'project_checkpoint.json', 'token.json', 'tokens.json', 'credentials.json',
                'account-refs.json', 'email_payload.json', 'combined_email.json'}
SECRET_FIELDS = re.compile(r'(?i)^(?:access_token|refresh_token|id_token|client_secret|api_key|private_key|siwc_bypass_bearer_token|bearer)$')
PLACEHOLDER = re.compile(r'(?i)(?:placeholder|example|dummy|fake|test|redacted|changeme|your[_ -]|\$\{|<|^null$|^none$)')

def scan(root):
    root=Path(root).resolve(); findings=[]; files=[]; skipped=[]
    for p in sorted(root.rglob('*')):
        if '.git' in p.relative_to(root).parts: continue
        rel=str(p.relative_to(root))
        if p.is_symlink():
            findings.append({'path':rel,'kind':'symlink_not_scanned'}); continue
        if not p.is_file(): continue
        b=p.read_bytes(); files.append({'path':rel,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
        if p.name in DENIED_NAMES or p.suffix.lower() in {'.sqlite','.db','.pem','.p12','.pfx','.key'}:
            findings.append({'path':rel,'kind':'private_runtime_or_key_filename'})
        if p.name=='.env' or (p.name.startswith('.env.') and p.name not in {'.env.example','.env.template'}):
            findings.append({'path':rel,'kind':'environment_file'})
        if p.suffix.lower() in {'.zip','.tar','.gz','.7z'}:
            findings.append({'path':rel,'kind':'nested_archive_requires_separate_inspection'})
        for kind,pattern in PATTERNS.items():
            if re.search(pattern,b): findings.append({'path':rel,'kind':kind})
        if p.suffix.lower()=='.json':
            try: data=json.loads(b)
            except (ValueError,UnicodeError): continue
            def walk(x,path='$'):
                if isinstance(x,dict):
                    for k,v in x.items():
                        if SECRET_FIELDS.match(k) and isinstance(v,str) and len(v)>16 and not PLACEHOLDER.search(v):
                            findings.append({'path':rel,'kind':'credential_field_nonplaceholder','json_path':path+'.'+k})
                        walk(v,path+'.'+k)
                elif isinstance(x,list):
                    for i,v in enumerate(x): walk(v,path+'['+str(i)+']')
            walk(data)
    return {'root':str(root),'file_count':len(files),'status':'PASS_BOUNDED_SCAN' if not findings else 'REVIEW_REQUIRED',
            'findings':findings,'files':files,'limitations':['Selected export tree only; no credential locations accessed.',
            'Pattern scan cannot certify absence of every credential or private narrative.',
            'Source literals may be dummy test strings; review findings without publishing values.',
            'Repository may retain user-specific emails/origins; use private GitHub unless separately sanitized.']}

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('root');ap.add_argument('--output',required=True);a=ap.parse_args()
    result=scan(a.root);Path(a.output).write_text(json.dumps(result,indent=2))
    print(json.dumps({k:result[k] for k in ['status','file_count','findings']}))
