"""Private durable OAuth profile bridge. Credentials enter through hidden stdin only."""
import argparse,json,os,re,shutil,subprocess,sys,tempfile,time,uuid
from pathlib import Path
from urllib import request,error,parse
import niulai_tiger as n
ORIGIN='https://private-credential-store.example.invalid'

class NoRedirect(request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None

def rpc(session,path,body=None):
 origin=session['origin'].rstrip('/');u=parse.urlsplit(origin)
 n.require(origin==ORIGIN and u.scheme=='https' and not u.query and not u.fragment,'PRIVATE_ORIGIN_REJECTED')
 raw=json.dumps(body).encode() if body is not None else None
 req=request.Request(origin+path,data=raw,headers={'OAI-Sites-Authorization':'Bearer '+session['bearer'],'Content-Type':'application/json'},method='POST' if body is not None else 'GET')
 for attempt in range(3):
  try:
   with request.build_opener(NoRedirect()).open(req,timeout=15) as response:return json.load(response)
  except error.HTTPError as e:
   if e.code in (408,429,500,502,503,504) and attempt<2:time.sleep(attempt+1);continue
   raise n.ReadOnlyError('PRIVATE_STORE_HTTP_'+str(e.code)) from None
  except (error.URLError,TimeoutError):
   if attempt<2:time.sleep(attempt+1);continue
   raise n.ReadOnlyError('PRIVATE_STORE_NETWORK_FAILED') from None

def collect(profile):
 files={}
 for p in Path(profile).rglob('*.json'):
  rel=p.relative_to(profile)
  if len(rel.parts)==1 and p.name not in ('account-refs.json','account-pin.json'):continue
  if len(rel.parts)>1 and rel.parts[0] not in ('tokens','clients'):continue
  n.require(not p.is_symlink() and p.is_file(),'PROFILE_SYMLINK_REJECTED');text=p.read_text();json.loads(text);files[str(rel)]=text
 n.require(files,'PROFILE_EMPTY');return {'files':files}

def restore(profile,value):
 n.require(isinstance(value,dict) and isinstance(value.get('files'),dict),'PRIVATE_PROFILE_EMPTY')
 root=Path(profile);root.mkdir(mode=0o700,parents=True,exist_ok=True);root.chmod(0o700)
 for rel,text in value['files'].items():
  path=Path(rel);n.require(not path.is_absolute() and '..' not in path.parts and re.fullmatch(r'[A-Za-z0-9_./-]+\.json',rel),'PRIVATE_PROFILE_PATH_REJECTED')
  n.write_private(root/path,json.loads(text))

def checkpoint(profile,session,release=False):
 result=rpc(session,'/lease/checkpoint',{'lease_id':session['lease_id'],'commit_id':str(uuid.uuid4()),'profile':collect(profile),'release':release})
 n.require(result.get('committed') is True,'PRIVATE_COMMIT_UNCONFIRMED');return result

def checkpoint_from_environment(profile):
 value=os.environ.get('NIULAI_PROFILE_SESSION_JSON')
 if value:checkpoint(profile,json.loads(value))

def verify_remote_context(profile):
 value=os.environ.get('NIULAI_PROFILE_SESSION_JSON');n.require(bool(value),'PRIVATE_STORE_REQUIRED');session=json.loads(value)
 remote=rpc(session,'/lease/acquire',{'request_id':session['lease_id']});n.require(remote.get('lease_id')==session['lease_id'] and remote.get('profile'),'PRIVATE_LEASE_UNVERIFIED')
 canonical=lambda x:{k:json.loads(v) for k,v in x['files'].items()}
 n.require(canonical(remote['profile'])==canonical(collect(profile)),'PRIVATE_PROFILE_SOURCE_MISMATCH');return {'origin':session['origin'],'revision':remote['revision'],'lease_verified':True}

def hidden_session():
 import termios
 old=termios.tcgetattr(sys.stdin);new=list(old);new[3]&=~termios.ECHO;termios.tcsetattr(sys.stdin,termios.TCSANOW,new)
 try:
  print('Ready for private service session JSON on stdin (input is hidden).',flush=True)
  value=json.loads(sys.stdin.readline());n.require(isinstance(value.get('bearer'),str) and value['bearer'],'PRIVATE_SERVICE_ACCESS_REQUIRED');return value
 finally:termios.tcsetattr(sys.stdin,termios.TCSANOW,old)

def main():
 a=argparse.ArgumentParser();a.add_argument('--mode',choices=['seed','replace','run','verify'],required=True);a.add_argument('--profile',type=Path);a.add_argument('--out',required=True,type=Path);a.add_argument('--rotate-test',action='store_true');args=a.parse_args();args.out.mkdir(parents=True,exist_ok=True)
 session=hidden_session();lease=rpc(session,'/lease/acquire',{'request_id':str(uuid.uuid4())});session['lease_id']=lease['lease_id'];released=False;profile=None
 result={'source':'owner_private_encrypted_store','mode':args.mode,'new_empty_profile':args.mode!='seed','authorization_prompted':False,'cross_environment_durability_claimed':False}
 try:
  if args.mode in ('seed','replace'):
   n.require(args.profile is not None and args.profile.is_dir() and (args.mode=='replace' or lease.get('profile') is None),'INITIAL_SEED_ONLY')
   with n.profile_lock(args.profile):result['commit']=checkpoint(args.profile,session,True)
   released=True
  else:
   profile=Path(tempfile.mkdtemp(prefix='niulai-private-profile-'));restore(profile,lease.get('profile'))
   if args.mode=='verify':
    os.environ['NIULAI_PROFILE_SESSION_JSON']=json.dumps(session)
    with n.profile_lock(profile):
     Session,make=n.sdk_classes(include_quotes=True);sdk=Session(issuer=n.ISSUER,home=str(profile),surface=n.SURFACE,client_name=n.CLIENT_NAME);before=sdk.status();n.validate_token(before,require_quotes=True)
     if args.rotate_test:
      after=sdk.refresh_after_unauthorized(before.access_token);n.validate_token(after,require_quotes=True);result['manual_refresh_succeeded']=True;result['token_rotated']=before.access_token!=after.access_token;checkpoint(profile,session)
     client=make(sdk);accounts=client.get_managed_accounts();standard=[a for a in accounts if a.account_type=='STANDARD'];n.require(len(standard)==1,'STANDARD_ACCOUNT_AMBIGUOUS');refs=n.account_refs(profile,accounts);a=standard[0]
     holdings=n.fetch_account(client,{'account':a.account,'ref':refs[a.account]},n.DEFAULT_SECURITY_TYPES);assets=n.fetch_assets_account(client,{'account':a.account,'ref':refs[a.account]})
     n.require(holdings['ok'] and assets['ok'],'INDEPENDENT_PRIVATE_READ_FAILED');result.update(holdings_read=True,holdings_count=len(holdings['positions']),assets_read=True,account_identity_verified=True)
   else:
    env=dict(os.environ,NIULAI_PROFILE_SESSION_JSON=json.dumps(session));cp=subprocess.run([sys.executable,str(Path(__file__).with_name('daily_compact_pipeline.py')),'--profile',str(profile),'--out',str(args.out/'daily')],env=env,timeout=540,capture_output=True,text=True)
    (args.out/'pipeline.log').write_text(cp.stdout);result.update(pipeline_exit_code=cp.returncode,pipeline_status=json.loads((args.out/'daily/status.json').read_text()))
   result['commit']=checkpoint(profile,session,True);released=True
  result['credential_restore']='verified';result['status']='verified' if args.mode!='run' else 'completed' if result['pipeline_exit_code']==0 and result['pipeline_status']['status']=='rendered' else 'partial';(args.out/'private_store_status.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));return 0 if result['status'] in ('verified','completed') else 2
 finally:
  if not released:
   if profile is not None:checkpoint(profile,session,True)
   else:rpc(session,'/lease/release',{'lease_id':session['lease_id']})
  if profile is not None:shutil.rmtree(profile)

def save_failure(code):
 result={'source':'owner_private_encrypted_store','status':'failed','credential_restore':'unconfirmed','error':code,'authorization_prompted':False,'reauthorization_assumed_required':False}
 if '--out' in sys.argv:
  out=Path(sys.argv[sys.argv.index('--out')+1]);out.mkdir(parents=True,exist_ok=True);(out/'private_store_status.json').write_text(json.dumps(result,indent=2))
 print(json.dumps(result))

if __name__=='__main__':
 try:raise SystemExit(main())
 except n.ReadOnlyError as e:save_failure(n.safe_error(e));raise SystemExit(2)
 except Exception:save_failure('PRIVATE_PROFILE_OPERATION_FAILED');raise SystemExit(2)
