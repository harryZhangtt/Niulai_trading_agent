"""Strict data contracts for the additive EIY v5 authority chain."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, Mapping

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")

class InformationYieldV5ContractError(ValueError):
    pass

def canonical_v5(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()

def digest_v5(value: Any) -> str:
    return hashlib.sha256(canonical_v5(value)).hexdigest()

def _need(ok: bool, code: str) -> None:
    if not ok: raise InformationYieldV5ContractError(code)

def _exact(value: Any, keys: set[str], code: str) -> Mapping[str, Any]:
    _need(isinstance(value, Mapping) and set(value) == keys, code); return value

def _identifier(value: Any, code: str) -> str:
    _need(isinstance(value, str) and bool(_ID.fullmatch(value)), code); return value

def _sha(value: Any, code: str) -> str:
    _need(isinstance(value, str) and bool(_SHA.fullmatch(value)), code); return value

def canonical_relative_path_v5(value: Any, code: str = "EIY_V5_ARTIFACT_REF") -> str:
    _need(isinstance(value, str) and value and "\x00" not in value and "\\" not in value, code)
    path=PurePosixPath(value)
    _need(not path.is_absolute() and path.as_posix()==value and all(part not in {"", ".", "..", "niulai-private"} and not part.startswith(".") for part in path.parts),code)
    return value

def resolve_workspace_path_v5(value: str, workspace_root: Path, code: str = "EIY_V5_ARTIFACT_REF") -> Path:
    relative=canonical_relative_path_v5(value,code)
    try: root=workspace_root.resolve(strict=True)
    except OSError: raise InformationYieldV5ContractError(code) from None
    candidate=root.joinpath(*PurePosixPath(relative).parts)
    current=root
    try:
        for part in PurePosixPath(relative).parts:
            current=current/part
            if current.exists() or current.is_symlink():
                _need(not stat.S_ISLNK(os.lstat(current).st_mode),code)
    except OSError: raise InformationYieldV5ContractError(code) from None
    _need(candidate.is_relative_to(root),code)
    return candidate

@dataclass(frozen=True)
class ArtifactRefV5:
    path: str
    sha256: str
    def __post_init__(self) -> None:
        canonical_relative_path_v5(self.path); _sha(self.sha256,"EIY_V5_ARTIFACT_REF")
    @classmethod
    def from_mapping(cls,value:Mapping[str,Any],code:str="EIY_V5_ARTIFACT_REF")->"ArtifactRefV5":
        try:
            row=_exact(value,{"path","sha256"},code);return cls(canonical_relative_path_v5(row["path"],code),_sha(row["sha256"],code))
        except (KeyError,TypeError,InformationYieldV5ContractError): raise InformationYieldV5ContractError(code) from None
    def to_mapping(self)->dict[str,str]:return {"path":self.path,"sha256":self.sha256}
    def resolve(self,workspace_root:Path)->Path:return resolve_workspace_path_v5(self.path,workspace_root)

@dataclass(frozen=True)
class CheckedEiyV5Request:
    schema_version:str; evaluation_id:str; mode:str; canonical_policy_ref:ArtifactRefV5; case_request_ref:ArtifactRefV5; request_sha256:str
    @classmethod
    def from_mapping(cls,value:Mapping[str,Any])->"CheckedEiyV5Request":
        keys={"schema_version","evaluation_id","mode","canonical_policy_ref","case_request_ref","request_sha256"};row=_exact(value,keys,"ACQ_EIY_V5_REQUEST_FIELDS")
        _need(row["schema_version"]=="information-yield-check-request-5","ACQ_EIY_V5_REQUEST_VERSION");_identifier(row["evaluation_id"],"ACQ_EIY_V5_REQUEST_ID");_need(row["mode"] in {"evaluation","now_diagnostic"},"ACQ_EIY_V5_REQUEST_MODE")
        policy=ArtifactRefV5.from_mapping(row["canonical_policy_ref"],"ACQ_EIY_POLICY_NOT_CANONICAL");case=ArtifactRefV5.from_mapping(row["case_request_ref"],"ACQ_EIY_V5_CASE_REQUEST_REF")
        unsigned={key:row[key] for key in keys if key!="request_sha256"};_need(_sha(row["request_sha256"],"ACQ_EIY_V5_REQUEST_DIGEST")==digest_v5(unsigned),"ACQ_EIY_V5_REQUEST_DIGEST")
        return cls(row["schema_version"],row["evaluation_id"],row["mode"],policy,case,row["request_sha256"])
    def to_mapping(self)->dict[str,Any]:return {"schema_version":self.schema_version,"evaluation_id":self.evaluation_id,"mode":self.mode,"canonical_policy_ref":self.canonical_policy_ref.to_mapping(),"case_request_ref":self.case_request_ref.to_mapping(),"request_sha256":self.request_sha256}

@dataclass(frozen=True)
class EvaluationCustodyV5:
    schema_version:str;evaluation_id:str;mode:str;canonical_policy_ref:ArtifactRefV5;case_roster_ref:ArtifactRefV5;allocation_ref:ArtifactRefV5;baseline_ref:ArtifactRefV5;reference_set_ref:ArtifactRefV5;required_fields_ref:ArtifactRefV5;freshness_targets_ref:ArtifactRefV5;financial_element_roster_ref:ArtifactRefV5;source_closure_ref:ArtifactRefV5;request_refs:tuple[ArtifactRefV5,...];custody_sha256:str
    @classmethod
    def from_mapping(cls,value:Mapping[str,Any])->"EvaluationCustodyV5":
        names=("canonical_policy_ref","case_roster_ref","allocation_ref","baseline_ref","reference_set_ref","required_fields_ref","freshness_targets_ref","financial_element_roster_ref","source_closure_ref");keys={"schema_version","evaluation_id","mode",*names,"request_refs","custody_sha256"};row=_exact(value,keys,"ACQ_EIY_V5_CUSTODY_FIELDS")
        _need(row["schema_version"]=="information-yield-evaluation-custody-5","ACQ_EIY_V5_CUSTODY_VERSION");_identifier(row["evaluation_id"],"ACQ_EIY_V5_CUSTODY_ID");_need(row["mode"] in {"evaluation","now_diagnostic"},"ACQ_EIY_V5_CUSTODY_VERSION")
        refs={name:ArtifactRefV5.from_mapping(row[name],"ACQ_EIY_V5_CUSTODY_REF") for name in names};_need(isinstance(row["request_refs"],list) and 0<len(row["request_refs"])<=64,"ACQ_EIY_V5_FACT_SET_MISMATCH")
        requests=tuple(ArtifactRefV5.from_mapping(x,"ACQ_EIY_V5_REQUEST_REF") for x in row["request_refs"]);_need(len({(r.path,r.sha256) for r in requests})==len(requests),"ACQ_EIY_V5_FACT_SET_MISMATCH")
        unsigned={key:row[key] for key in keys if key!="custody_sha256"};_need(_sha(row["custody_sha256"],"ACQ_EIY_V5_CUSTODY_DIGEST")==digest_v5(unsigned),"ACQ_EIY_V5_CUSTODY_DIGEST")
        return cls(row["schema_version"],row["evaluation_id"],row["mode"],*(refs[n] for n in names),requests,row["custody_sha256"])
    def to_mapping(self)->dict[str,Any]:
        row={"schema_version":self.schema_version,"evaluation_id":self.evaluation_id,"mode":self.mode,"request_refs":[r.to_mapping() for r in self.request_refs],"custody_sha256":self.custody_sha256}
        for name in ("canonical_policy_ref","case_roster_ref","allocation_ref","baseline_ref","reference_set_ref","required_fields_ref","freshness_targets_ref","financial_element_roster_ref","source_closure_ref"):row[name]=getattr(self,name).to_mapping()
        return row

@dataclass(frozen=True)
class CheckedEiyEvaluationManifestV5:
    schema_version:str;evaluation_custody_ref:ArtifactRefV5;manifest_sha256:str
    @classmethod
    def from_mapping(cls,value:Mapping[str,Any])->"CheckedEiyEvaluationManifestV5":
        row=_exact(value,{"schema_version","evaluation_custody_ref","manifest_sha256"},"ACQ_EIY_V5_MANIFEST_FIELDS");_need(row["schema_version"]=="information-yield-evaluation-manifest-5","ACQ_EIY_V5_MANIFEST_VERSION")
        ref=ArtifactRefV5.from_mapping(row["evaluation_custody_ref"],"ACQ_EIY_V5_CUSTODY_REF");unsigned={"schema_version":row["schema_version"],"evaluation_custody_ref":ref.to_mapping()};_need(_sha(row["manifest_sha256"],"ACQ_EIY_V5_MANIFEST_DIGEST")==digest_v5(unsigned),"ACQ_EIY_V5_MANIFEST_DIGEST")
        return cls(row["schema_version"],ref,row["manifest_sha256"])

@dataclass(frozen=True)
class EvaluationContextV5:
    value:Mapping[str,Any]
    @classmethod
    def from_mapping(cls,value:Mapping[str,Any])->"EvaluationContextV5":
        required={"schema_version","evaluation_id","mode","planned_cases","split_counts","populations","common_hashes","policy","policy_sha256","gate_authority_sha256","source_closure_sha256","fact_bindings","fact_set_sha256","context_sha256"};row=_exact(value,required,"ACQ_EIY_V5_CONTEXT_FIELDS")
        _need(row["schema_version"]=="information-yield-evaluation-context-5","ACQ_EIY_V5_CONTEXT_VERSION");_identifier(row["evaluation_id"],"ACQ_EIY_V5_CONTEXT_ID");_need(row["mode"] in {"evaluation","now_diagnostic"},"ACQ_EIY_V5_NOW_BOUNDARY")
        core={k:row[k] for k in required if k not in {"context_sha256","fact_set_sha256","fact_bindings"}};_need(_sha(row["context_sha256"],"ACQ_EIY_V5_CONTEXT_DIGEST")==digest_v5(core),"ACQ_EIY_V5_CONTEXT_DIGEST")
        _need(isinstance(row["fact_bindings"],list) and digest_v5(row["fact_bindings"])==row["fact_set_sha256"],"ACQ_EIY_V5_FACT_SET_MISMATCH")
        return cls(dict(row))
