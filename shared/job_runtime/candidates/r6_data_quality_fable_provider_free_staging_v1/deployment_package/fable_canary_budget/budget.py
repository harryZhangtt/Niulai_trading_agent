"""Descriptor-owned provider-free campaign budget and one-shot claim ledger."""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal,InvalidOperation
import fcntl,hashlib,os,re,sqlite3,stat
from pathlib import Path
JOBS=("fable-5-1-dq-off","fable-5-1-dq-on");ARMS={JOBS[0]:"OFF",JOBS[1]:"ON"};CAMPAIGN="fable-5-1-dq-v1"
_NONCE=re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{7,127}\Z");_IDENTITY=re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,255}\Z")
class BudgetError(ValueError):pass
@dataclass(frozen=True)
class LedgerDescriptor:
 root:str;relative_path:str;deployment_id:str;campaign_id:str;sha256:str;bytes:int

def _money(value):
 try:amount=Decimal(str(value))
 except (InvalidOperation,ValueError):raise BudgetError("BUDGET_INVALID") from None
 if not amount.is_finite() or amount<=0 or amount>Decimal("0.02") or amount.as_tuple().exponent < -2:raise BudgetError("BUDGET_INVALID")
 return format(amount,".2f")
def _parents(path,root):
 current=path.parent
 while True:
  if current!=root and root not in current.parents:raise BudgetError("LEDGER_PATH_INVALID")
  yield current
  if current==root:break
  current=current.parent
def _regular(path):
 try:info=os.lstat(path)
 except OSError:raise BudgetError("LEDGER_CUSTODY_INVALID") from None
 if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1:raise BudgetError("LEDGER_CUSTODY_INVALID")
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC);before=os.fstat(fd);raw=b""
 try:
  while True:
   chunk=os.read(fd,65536)
   if not chunk:break
   raw+=chunk
  after=os.fstat(fd)
 finally:os.close(fd)
 if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise BudgetError("LEDGER_CUSTODY_INVALID")
 return raw

_TEST_HOOK=None
def _hook(phase,path):
 if _TEST_HOOK is not None:_TEST_HOOK(phase,Path(path))
class _LockedConnection:
 def __init__(self,owner):self.owner=owner;self.root_fd=self.lock_fd=self.db_fd=-1;self.db=None
 def __enter__(self):
  o=self.owner;self.root_fd=os.open(o.root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC);self.lock_fd=os.open('.ledger.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=self.root_fd);os.fchmod(self.lock_fd,0o600);fcntl.flock(self.lock_fd,fcntl.LOCK_EX)
  self.db_fd=os.open('campaign-budget.sqlite',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=self.root_fd);held=os.fstat(self.db_fd);named=os.lstat(o.path)
  if (held.st_dev,held.st_ino)!=(named.st_dev,named.st_ino):raise BudgetError('LEDGER_PATH_SWAP')
  _hook('pre_open',o.path);self.db=sqlite3.connect(o.path,timeout=1,isolation_level=None);self.db.row_factory=sqlite3.Row;self.db.execute('PRAGMA journal_mode=DELETE');self.db.execute('PRAGMA synchronous=FULL');self.db.execute('PRAGMA foreign_keys=ON');_hook('post_open',o.path)
  named=os.lstat(o.path)
  if (held.st_dev,held.st_ino)!=(named.st_dev,named.st_ino):raise BudgetError('LEDGER_PATH_SWAP')
  return self.db
 def __exit__(self,typ,value,tb):
  try:
   if self.db is not None:
    _hook('precommit',self.owner.path)
    held=os.fstat(self.db_fd);named=os.lstat(self.owner.path)
    if (held.st_dev,held.st_ino)!=(named.st_dev,named.st_ino):
     self.db.rollback();raise BudgetError('LEDGER_PATH_SWAP')
    self.db.__exit__(typ,value,tb);self.db.close();self.db=None;_hook('post_close',self.owner.path)
    named=os.lstat(self.owner.path)
    if (held.st_dev,held.st_ino)!=(named.st_dev,named.st_ino):raise BudgetError('LEDGER_PATH_SWAP')
  finally:
   for fd in (self.db_fd,self.lock_fd,self.root_fd):
    if fd>=0:
     try:os.close(fd)
     except OSError:pass
  return False
class CampaignBudgetLedger:
 def __init__(self,path:Path,*,approved_root:Path|None=None,campaign_id=CAMPAIGN,create=True):
  supplied_path=Path(path).absolute();supplied_root=Path(approved_root or supplied_path.parent).absolute();self.campaign_id=campaign_id
  if supplied_path!=supplied_root/"campaign-budget.sqlite":raise BudgetError("LEDGER_PATH_INVALID")
  if create:supplied_root.mkdir(parents=True,exist_ok=True,mode=0o700);supplied_root.chmod(0o700)
  self.root=supplied_root.resolve(strict=True);self.path=self.root/"campaign-budget.sqlite"
  if create:self._init()
  self._custody();info=os.lstat(self.path);self._bound_identity=(info.st_dev,info.st_ino)
 def _db(self):return _LockedConnection(self)
 def _init(self):
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE")
   db.execute("CREATE TABLE IF NOT EXISTS campaign(id TEXT PRIMARY KEY,approved INTEGER NOT NULL,per_arm TEXT NOT NULL,aggregate TEXT NOT NULL)")
   db.execute("CREATE TABLE IF NOT EXISTS arms(job_id TEXT PRIMARY KEY,arm TEXT UNIQUE NOT NULL,cap TEXT NOT NULL)")
   db.executemany("INSERT OR IGNORE INTO arms VALUES(?,?,?)",[(JOBS[0],"OFF","0.02"),(JOBS[1],"ON","0.02")])
   db.execute("CREATE TABLE IF NOT EXISTS claims(job_id TEXT PRIMARY KEY,arm TEXT NOT NULL,nonce TEXT UNIQUE NOT NULL,reserved TEXT NOT NULL,outcome TEXT NOT NULL,claim_id TEXT UNIQUE NOT NULL,deployment_id TEXT NOT NULL,campaign_id TEXT NOT NULL,attempt_id TEXT NOT NULL,slot_id TEXT NOT NULL,operation_id TEXT NOT NULL,resolution_provider TEXT,resolution_operation_id TEXT,result_sha256 TEXT,resolution_sha256 TEXT)")
   rows=db.execute("SELECT * FROM campaign").fetchall()
   if not rows:db.execute("INSERT INTO campaign VALUES(?,1,'0.02','0.04')",(self.campaign_id,))
   elif len(rows)!=1 or dict(rows[0])!={"id":self.campaign_id,"approved":1,"per_arm":"0.02","aggregate":"0.04"}:raise BudgetError("CAMPAIGN_BINDING_INVALID")
  self.path.chmod(0o600)
 def _custody(self):
  root=self.root.resolve(strict=True)
  if self.path.parent.resolve(strict=True)!=root:raise BudgetError("LEDGER_PATH_INVALID")
  for parent in _parents(self.path,root):
   info=os.lstat(parent)
   if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o077:raise BudgetError("LEDGER_CUSTODY_INVALID")
  for suffix in ("-wal","-shm","-journal"):
   if Path(str(self.path)+suffix).exists() or Path(str(self.path)+suffix).is_symlink():raise BudgetError("LEDGER_SIDECAR_PRESENT")
  root_fd=-1;ledger_fd=-1
  try:
   root_fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
   root_info=os.fstat(root_fd)
   if root_info.st_uid!=os.getuid() or stat.S_IMODE(root_info.st_mode)&0o077:raise BudgetError("LEDGER_CUSTODY_INVALID")
   ledger_fd=os.open("campaign-budget.sqlite",os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=root_fd)
   opened=os.fstat(ledger_fd);named=os.lstat(self.path)
   if (opened.st_dev,opened.st_ino)!=(named.st_dev,named.st_ino):raise BudgetError("LEDGER_CUSTODY_INVALID")
  except OSError:raise BudgetError("LEDGER_CUSTODY_INVALID") from None
  finally:
   if ledger_fd>=0:os.close(ledger_fd)
   if root_fd>=0:os.close(root_fd)
  _regular(self.path)
  current=os.lstat(self.path)
  if hasattr(self,"_bound_identity") and (current.st_dev,current.st_ino)!=self._bound_identity:raise BudgetError("LEDGER_PATH_SWAP")
  holder=None;source=None;db=None
  try:
   holder=self._db();source=holder.__enter__();db=sqlite3.connect(":memory:");db.row_factory=sqlite3.Row;source.backup(db);active=holder;holder=None;active.__exit__(None,None,None);source=None
   if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok":raise BudgetError("LEDGER_INTEGRITY_INVALID")
   tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
   if tables!={"campaign","arms","claims"}:raise BudgetError("LEDGER_SCHEMA_INVALID")
   if db.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view')").fetchone():raise BudgetError("LEDGER_SCHEMA_INVALID")
   expected_sql={"campaign":"CREATE TABLE campaign(id TEXT PRIMARY KEY,approved INTEGER NOT NULL,per_arm TEXT NOT NULL,aggregate TEXT NOT NULL)","arms":"CREATE TABLE arms(job_id TEXT PRIMARY KEY,arm TEXT UNIQUE NOT NULL,cap TEXT NOT NULL)","claims":"CREATE TABLE claims(job_id TEXT PRIMARY KEY,arm TEXT NOT NULL,nonce TEXT UNIQUE NOT NULL,reserved TEXT NOT NULL,outcome TEXT NOT NULL,claim_id TEXT UNIQUE NOT NULL,deployment_id TEXT NOT NULL,campaign_id TEXT NOT NULL,attempt_id TEXT NOT NULL,slot_id TEXT NOT NULL,operation_id TEXT NOT NULL,resolution_provider TEXT,resolution_operation_id TEXT,result_sha256 TEXT,resolution_sha256 TEXT)"}
   if {r[0]:r[1] for r in db.execute("SELECT name,sql FROM sqlite_master WHERE type='table'")}!=expected_sql:raise BudgetError("LEDGER_SCHEMA_INVALID")
   expected_columns={"campaign":[("id","TEXT",0,1),("approved","INTEGER",1,0),("per_arm","TEXT",1,0),("aggregate","TEXT",1,0)],"arms":[("job_id","TEXT",0,1),("arm","TEXT",1,0),("cap","TEXT",1,0)],"claims":[("job_id","TEXT",0,1),("arm","TEXT",1,0),("nonce","TEXT",1,0),("reserved","TEXT",1,0),("outcome","TEXT",1,0),("claim_id","TEXT",1,0),("deployment_id","TEXT",1,0),("campaign_id","TEXT",1,0),("attempt_id","TEXT",1,0),("slot_id","TEXT",1,0),("operation_id","TEXT",1,0),("resolution_provider","TEXT",0,0),("resolution_operation_id","TEXT",0,0),("result_sha256","TEXT",0,0),("resolution_sha256","TEXT",0,0)]}
   for table,expected in expected_columns.items():
    actual=[(r[1],r[2],r[3],r[5]) for r in db.execute(f"PRAGMA table_info({table})")]
    if actual!=expected:raise BudgetError("LEDGER_SCHEMA_INVALID")
   expected_indexes={"campaign":[("sqlite_autoindex_campaign_1",1,"pk","id")],"arms":[("sqlite_autoindex_arms_2",1,"u","arm"),("sqlite_autoindex_arms_1",1,"pk","job_id")],"claims":[("sqlite_autoindex_claims_3",1,"u","claim_id"),("sqlite_autoindex_claims_2",1,"u","nonce"),("sqlite_autoindex_claims_1",1,"pk","job_id")]}
   for table,expected in expected_indexes.items():
    actual=[]
    for index in db.execute(f"PRAGMA index_list({table})"):
     columns=db.execute(f"PRAGMA index_info({index[1]})").fetchall()
     if len(columns)!=1:raise BudgetError("LEDGER_SCHEMA_INVALID")
     actual.append((index[1],index[2],index[3],columns[0][2]))
    if actual!=expected:raise BudgetError("LEDGER_SCHEMA_INVALID")
   rows=[tuple(r) for r in db.execute("SELECT id,approved,per_arm,aggregate FROM campaign").fetchall()]
   arms=[tuple(r) for r in db.execute("SELECT job_id,arm,cap FROM arms ORDER BY arm").fetchall()]
   if arms!=[(JOBS[0],"OFF","0.02"),(JOBS[1],"ON","0.02")]:raise BudgetError("LEDGER_ARMS_INVALID")
   typed_columns=("job_id","arm","nonce","reserved","outcome","claim_id","deployment_id","campaign_id","attempt_id","slot_id","operation_id")
   type_sql=",".join("typeof("+name+") AS type_"+name for name in typed_columns)
   claim_rows=db.execute("SELECT rowid,*,"+type_sql+" FROM claims ORDER BY rowid").fetchall();seen=[];total=Decimal("0")
   for claim in claim_rows:
    if any(claim["type_"+name]!="text" for name in typed_columns):raise BudgetError("CLAIM_ROW_TYPE_INVALID")
    expected_claim_id=CAMPAIGN+"/"+claim["job_id"]+"/"+claim["nonce"] if claim["job_id"] in JOBS and type(claim["nonce"]) is str else ""
    if claim["deployment_id"]!=CAMPAIGN or claim["campaign_id"]!=self.campaign_id or claim["job_id"] not in JOBS or claim["arm"]!=ARMS[claim["job_id"]] or any(_IDENTITY.fullmatch(claim[k]) is None for k in ("slot_id","attempt_id","operation_id")) or _NONCE.fullmatch(claim["nonce"]) is None or claim["claim_id"]!=expected_claim_id:raise BudgetError("CLAIM_ROW_INVALID")
    amount=_money(claim["reserved"])
    if claim["reserved"]!=amount or amount!="0.02":raise BudgetError("CLAIM_RESERVED_NONCANONICAL")
    total+=Decimal(amount)
    if claim["outcome"] not in ("UNKNOWN","VALID","INVALID"):raise BudgetError("CLAIM_ROW_INVALID")
    evidence=(claim["resolution_provider"],claim["resolution_operation_id"],claim["result_sha256"],claim["resolution_sha256"])
    if claim["outcome"]=="UNKNOWN" and evidence!=(None,None,None,None):raise BudgetError("CLAIM_RESOLUTION_INVALID")
    if claim["outcome"]!="UNKNOWN":
     if claim["resolution_provider"]!="claude_host" or claim["resolution_operation_id"]!=claim["operation_id"] or not re.fullmatch(r"[0-9a-f]{64}",claim["result_sha256"] or ""):raise BudgetError("CLAIM_RESOLUTION_INVALID")
     proof=hashlib.sha256((claim["claim_id"]+"|"+claim["outcome"]+"|"+claim["resolution_provider"]+"|"+claim["resolution_operation_id"]+"|"+claim["result_sha256"]).encode()).hexdigest()
     if claim["resolution_sha256"]!=proof:raise BudgetError("CLAIM_RESOLUTION_INVALID")
    seen.append(claim)
   if total>Decimal("0.04"):raise BudgetError("AGGREGATE_BUDGET_EXCEEDED")
   if any(c["job_id"]==JOBS[1] and not any(o["job_id"]==JOBS[0] and o["outcome"]=="VALID" and o["rowid"]<c["rowid"] for o in seen) for c in seen):raise BudgetError("OFF_NOT_VALID")
   if rows!=[(self.campaign_id,1,"0.02","0.04")]:raise BudgetError("CAMPAIGN_BINDING_INVALID")
  except sqlite3.Error:raise BudgetError("LEDGER_INTEGRITY_INVALID") from None
  finally:
   if db is not None:db.close()
   if holder is not None:holder.__exit__(None,None,None)
 def _custody_identity(self):
  self._custody();info=os.lstat(self.path);return (info.st_dev,info.st_ino)
 def assert_custody(self):self._custody();return True
 def descriptor(self):
  self._custody();raw=_regular(self.path);return LedgerDescriptor(str(self.root),"campaign-budget.sqlite",CAMPAIGN,self.campaign_id,hashlib.sha256(raw).hexdigest(),len(raw))
 def claim(self,job_id,nonce,amount,*,deployment_id=CAMPAIGN,attempt_id="fixture-attempt",slot_id="fixture-slot",operation_id="fixture-operation"):
  before=self._custody_identity()
  if job_id not in JOBS:raise BudgetError("JOB_NOT_WHITELISTED")
  if type(nonce) is not str or _NONCE.fullmatch(nonce) is None:raise BudgetError("NONCE_INVALID")
  if deployment_id!=CAMPAIGN or any(_IDENTITY.fullmatch(v) is None for v in (attempt_id,slot_id,operation_id)):raise BudgetError("CLAIM_BINDING_INVALID")
  reserved=_money(amount);claim_id=f"{CAMPAIGN}/{job_id}/{nonce}"
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE");prior=db.execute("SELECT * FROM claims WHERE nonce=?",(nonce,)).fetchone()
   if prior:
    if prior["job_id"]==job_id and prior["arm"]==ARMS[job_id] and prior["reserved"]==reserved=="0.02" and prior["claim_id"]==claim_id and prior["deployment_id"]==deployment_id==CAMPAIGN and prior["campaign_id"]==self.campaign_id and prior["attempt_id"]==attempt_id and prior["slot_id"]==slot_id and prior["operation_id"]==operation_id:return dict(prior)
    raise BudgetError("NONCE_REUSE_CONFLICT")
   if db.execute("SELECT 1 FROM claims WHERE outcome='UNKNOWN'").fetchone():raise BudgetError("UNRESOLVED_UNKNOWN")
   if db.execute("SELECT 1 FROM claims WHERE job_id=?",(job_id,)).fetchone():raise BudgetError("ONE_SHOT_ALREADY_CLAIMED")
   if job_id==JOBS[1]:
    off=db.execute("SELECT outcome FROM claims WHERE job_id=?",(JOBS[0],)).fetchone()
    if not off or off[0]!="VALID":raise BudgetError("OFF_NOT_VALID")
   total=sum((Decimal(r[0]) for r in db.execute("SELECT reserved FROM claims")),Decimal("0"))+Decimal(reserved)
   if total>Decimal("0.04"):raise BudgetError("AGGREGATE_BUDGET_EXCEEDED")
   db.execute("INSERT INTO claims VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(job_id,ARMS[job_id],nonce,reserved,"UNKNOWN",claim_id,deployment_id,self.campaign_id,attempt_id,slot_id,operation_id,None,None,None,None))
   row=dict(db.execute("SELECT * FROM claims WHERE job_id=?",(job_id,)).fetchone())
  self.path.chmod(0o600);self._custody()
  if self._custody_identity()!=before:raise BudgetError("LEDGER_PATH_SWAP")
  return row
 def resolve(self,claim_id,outcome,*,provider,operation_id,result_sha256):
  before=self._custody_identity()
  if outcome not in ("VALID","INVALID") or provider!="claude_host" or not re.fullmatch(r"[0-9a-f]{64}",result_sha256 or ""):raise BudgetError("OUTCOME_INVALID")
  with self._db() as db:
   db.execute("BEGIN IMMEDIATE");row=db.execute("SELECT * FROM claims WHERE claim_id=?",(claim_id,)).fetchone()
   if not row:raise BudgetError("CLAIM_NOT_FOUND")
   if operation_id!=row["operation_id"]:raise BudgetError("CLAIM_RESOLUTION_INVALID")
   proof=hashlib.sha256((claim_id+"|"+outcome+"|"+provider+"|"+operation_id+"|"+result_sha256).encode()).hexdigest()
   if row["outcome"]!="UNKNOWN":
    if row["outcome"]==outcome and row["resolution_sha256"]==proof:return dict(row)
    raise BudgetError("CLAIM_ALREADY_RESOLVED")
   db.execute("UPDATE claims SET outcome=?,resolution_provider=?,resolution_operation_id=?,result_sha256=?,resolution_sha256=? WHERE claim_id=?",(outcome,provider,operation_id,result_sha256,proof,claim_id));result=dict(db.execute("SELECT * FROM claims WHERE claim_id=?",(claim_id,)).fetchone())
  self.path.chmod(0o600);self._custody();
  if self._custody_identity()!=before:raise BudgetError("LEDGER_PATH_SWAP")
  return result
 def snapshot(self):
  self._custody()
  with self._db() as db:result={"campaign":dict(db.execute("SELECT * FROM campaign").fetchone()),"job_whitelist":list(JOBS),"claims":[dict(r) for r in db.execute("SELECT * FROM claims ORDER BY rowid")],"activation":False}
  self._custody();return result
