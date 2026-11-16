#!/usr/bin/env python3
"""Explicitly fetch PyPI metadata and atomically create a new immutable seal directory."""
from __future__ import annotations
import argparse, ctypes, datetime, errno, hashlib, json, os, re, unicodedata
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tempfile
import urllib.error, urllib.request
from wheel_gate import inspect_wheelhouse, lock_text, sums_text

INDEX="https://pypi.org/simple"
RENAME_EXCL=0x00000004
SAFE_OUTPUT=re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")

def validate_output_name(value: str) -> str:
    if (not value or value in {".",".."} or unicodedata.normalize("NFC",value)!=value
            or os.path.isabs(value) or "/" in value or "\\" in value or not SAFE_OUTPUT.fullmatch(value)):
        raise ValueError("output_name must be one NFC safe basename")
    return value

def publish_no_replace(parent_fd: int, source_name: str, output_name: str) -> None:
    validate_output_name(source_name);validate_output_name(output_name)
    libc=ctypes.CDLL(None,use_errno=True)
    function=getattr(libc,"renameatx_np",None)
    if function is None: raise RuntimeError("Darwin renameatx_np is required for atomic no-replace publication")
    function.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
    function.restype=ctypes.c_int
    result=function(parent_fd,os.fsencode(source_name),parent_fd,os.fsencode(output_name),RENAME_EXCL)
    if result!=0:
        error=ctypes.get_errno()
        raise OSError(error,os.strerror(error),output_name)
    os.fsync(parent_fd)


def fetch(url: str) -> tuple[bytes,dict]:
    request=urllib.request.Request(url,headers={"User-Agent":"trading-agent-offline-wheel-gate/2"})
    with urllib.request.urlopen(request,timeout=30) as response:
        return response.read(),{"date":response.headers.get("Date"),"etag":response.headers.get("ETag"),"last_modified":response.headers.get("Last-Modified")}

def source_for(item: dict, fetched_at: str) -> dict:
    project_url=f"https://pypi.org/pypi/{item['name']}/{item['version']}/json"
    raw,headers=fetch(project_url); payload=json.loads(raw)
    matches=[x for x in payload.get("urls",[]) if x.get("filename")==item["filename"] and x.get("digests",{}).get("sha256")==item["sha256"]]
    if len(matches)!=1: raise ValueError(f"PyPI filename+digest mismatch: {item['filename']}")
    entry=matches[0]
    if entry.get("packagetype")!="bdist_wheel": raise ValueError("non-wheel source rejected")
    if entry.get("yanked") is not False: raise ValueError("yanked artifact rejected")
    result={"index":INDEX,"project_json":project_url,"project_json_sha256":hashlib.sha256(raw).hexdigest(),
            "project_json_bytes":len(raw),"snapshot_fetched_at_utc":fetched_at,"response_headers":headers,
            "artifact_url":entry["url"],"artifact_sha256":item["sha256"],"filename":item["filename"],
            "packagetype":"bdist_wheel","upload_time_iso_8601":entry.get("upload_time_iso_8601"),
            "yanked":False,"yanked_reason":None}
    if item["name"]=="claude-agent-sdk":
        endpoint=f"https://pypi.org/integrity/{item['name']}/{item['version']}/{item['filename']}/provenance"
        try:
            body,_=fetch(endpoint)
        except urllib.error.HTTPError as exc:
            if exc.code!=404: raise
            result["provenance_attestation"]={"status":"unavailable","available":False,"http_status":404,"endpoint":endpoint,"passed":False}
        else:
            result["provenance_attestation"]={"status":"available_unreviewed","available":True,"http_status":200,"endpoint":endpoint,
                                               "passed":False,"snapshot_sha256":hashlib.sha256(body).hexdigest()}
    return result

def atomic_write(path: Path, data: bytes) -> None:
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o644)
    try:
        with os.fdopen(fd,"wb",closefd=False) as stream: stream.write(data);stream.flush();os.fsync(stream.fileno())
    finally: os.close(fd)

def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate",type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument("--output-name",default="seal-v5")
    args=parser.parse_args();output_name=validate_output_name(args.output_name);candidate=args.candidate.resolve();final=candidate/output_name
    parent_fd=os.open(candidate,os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0))
    try:
        os.stat(output_name,dir_fd=parent_fd,follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        os.close(parent_fd);raise ValueError("seal output already exists; refusing overwrite")
    artifacts,edges=inspect_wheelhouse(candidate/"wheelhouse")
    fetched_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
    for item in artifacts: item["source"]=source_for(item,fetched_at)
    manifest={"schema_version":2,"status":"READY_FOR_OFFLINE_INSTALL","direct_requirement":"claude-agent-sdk==0.2.179",
              "target":{"python_implementation":"CPython","python_version":"3.12","platform":"macOS","architecture":"arm64"},
              "resolution":{"index":INDEX,"resolver":"uv 0.13.7","strategy":"highest compatible, wheels only, no extras",
                            "package_count":len(artifacts),"sdists_allowed":False,"parser":"candidate wheel_gate.py stdlib-only bounded parser",
                            "complete_transitive_closure_verified_from_wheel_metadata":True},
              "security":{"installed":False,"imported_or_executed_downloaded_code":False,"archive_extracted":False,
                          "provider_calls":False,"provider_spend_usd":0,"package_metadata_network_used_during_seal":True,"descriptor_relative_no_follow":True,
                          "record_hashes_and_sizes_verified":True,"frozen_gate_read_only":True},
              "limits":{"max_wheels":30,"max_members_per_wheel":512,"max_members_total":4096,
                        "max_archive_bytes":160*1024*1024,"max_member_expanded_bytes":320*1024*1024,
                        "max_total_expanded_bytes":384*1024*1024,"max_expansion_ratio":20},
              "record_tree_digest_plan":{"offline_install":"Use offline_install.py only after separate authorization; it hardcodes no-index/find-links/require-hashes/only-binary.",
                 "post_install_record":"Hash installed .dist-info/RECORD and review installer-added entries.",
                 "post_install_tree":"Compute shared.job_runtime.claude_sdk_preflight tree semantics in the isolated CPython 3.12 environment.",
                 "activation":"A separate reviewed change may update the production lock; this candidate does not."},
              "dependency_edges":edges,"artifacts":artifacts}
    temp=Path(tempfile.mkdtemp(prefix="seal-tmp-",dir=candidate))
    try:
        controls={"manifest.json":(json.dumps(manifest,indent=2,sort_keys=True)+"\n").encode(),
                  "requirements.lock.txt":lock_text(artifacts).encode(),"SHA256SUMS":sums_text(artifacts).encode()}
        for name,data in controls.items(): atomic_write(temp/name,data)
        seal_record={"schema_version":1,"control_sha256":{name:hashlib.sha256(data).hexdigest() for name,data in controls.items()}}
        atomic_write(temp/"seal.json",(json.dumps(seal_record,indent=2,sort_keys=True)+"\n").encode())
        os.chmod(temp,0o755);publish_no_replace(parent_fd,temp.name,output_name)
    except Exception:
        for p in temp.iterdir(): p.unlink()
        temp.rmdir();raise
    finally:
        os.close(parent_fd)
    print(json.dumps({"status":"SEALED","output":str(final),"artifacts":len(artifacts)},sort_keys=True))
    return 0

if __name__=="__main__": raise SystemExit(main())
