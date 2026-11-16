"""Cross-tree evidence-manifest verification for source, tests, and fixture."""
from __future__ import annotations
import hashlib, json, stat
from pathlib import Path
from .contracts import ContractError, digest, require

def _inventory(root:Path,exclude):
    result=[]
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.name in exclude:continue
        require(not path.is_symlink(),"EVIDENCE_MANIFEST_MISMATCH");info=path.stat();require(stat.S_ISREG(info.st_mode) and info.st_nlink==1,"EVIDENCE_MANIFEST_MISMATCH")
        raw=path.read_bytes();result.append({"path":path.relative_to(root).as_posix(),"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()})
    return result

def load_evidence_manifest(path=None):
    target=path or Path(__file__).with_name("evidence-manifest-v1.json")
    try:value=json.loads(target.read_text(encoding="ascii"))
    except (OSError,ValueError,UnicodeError):raise ContractError("EVIDENCE_MANIFEST_MISMATCH") from None
    require(type(value) is dict and set(value)=={"schema_version","algorithm","package","tests","fixtures","evidence_sha256"},"EVIDENCE_MANIFEST_MISMATCH")
    body=dict(value);claimed=body.pop("evidence_sha256");require(value["schema_version"]==1 and value["algorithm"]=="sha256-path-bytes-v1" and claimed==digest(body),"EVIDENCE_MANIFEST_MISMATCH")
    return value

def verify_evidence_manifest(workspace:Path,manifest):
    require(isinstance(workspace,Path) and workspace.is_absolute(),"EVIDENCE_MANIFEST_MISMATCH")
    package=workspace/"shared/job_runtime/candidates/claude_unanswered_question_v1";tests=workspace/"shared/job_runtime/tests/candidates/claude_unanswered_question_v1";fixtures=workspace/"shared/job_runtime/tests/fixtures/claude_unanswered_question_v1"
    require(manifest["package"]==_inventory(package,{"source-closure-v1.json","evidence-manifest-v1.json"}),"EVIDENCE_MANIFEST_MISMATCH")
    require(manifest["tests"]==_inventory(tests,set()),"EVIDENCE_MANIFEST_MISMATCH")
    require(manifest["fixtures"]==_inventory(fixtures,set()),"EVIDENCE_MANIFEST_MISMATCH")
    return manifest["evidence_sha256"]
