"""Descriptor-safe, provider-free wheelhouse inspection and frozen-gate verification."""
from __future__ import annotations

import base64
import csv
from email import policy
from email.parser import BytesParser
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import unicodedata
import zipfile

SEAL_NAME = "seal-v4"
MAX_WHEELS = 30
MAX_ARCHIVE_BYTES = 160 * 1024 * 1024
MAX_MEMBERS_PER_WHEEL = 512
MAX_MEMBERS_TOTAL = 4096
MAX_MEMBER_EXPANDED = 320 * 1024 * 1024
MAX_TOTAL_EXPANDED = 384 * 1024 * 1024
MAX_EXPANSION_RATIO = 20
READ_CHUNK = 1024 * 1024
ALLOWED_TAGS = {
    "py3-none-any", "py3-none-macosx_11_0_arm64",
    "cp312-cp312-macosx_11_0_arm64", "cp311-abi3-macosx_11_0_arm64",
}
SINGLETON_METADATA = {
    "metadata-version", "name", "version", "requires-python", "license",
    "license-expression", "summary", "description-content-type",
}
SINGLETON_WHEEL = {"wheel-version", "root-is-purelib", "build"}
TARGET_ENV = {
    "implementation_name": "cpython", "implementation_version": "3.12.0",
    "os_name": "posix", "platform_machine": "arm64",
    "platform_python_implementation": "CPython", "platform_system": "Darwin",
    "python_full_version": "3.12.0", "python_version": "3.12",
    "sys_platform": "darwin", "extra": "",
}
NAME_RE = re.compile(r"[-_.]+")
REQ_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[([A-Za-z0-9_., -]+)\])?\s*(.*?)\s*$")
TOKEN_RE = re.compile(r'''\s*(?:(and|or|not|in)|([A-Za-z_][A-Za-z0-9_]*)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(==|!=|<=|>=|<|>)|(\()|(\)))''')
SPEC_RE = re.compile(r"^(===|==|!=|~=|<=|>=|<|>)([A-Za-z0-9.*+!_-]+)$")


def canonical_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", value):
        raise ValueError(f"invalid project name: {value!r}")
    return NAME_RE.sub("-", value).lower()


def normalized_version(value: str) -> str:
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*(?:[A-Za-z0-9.+_-]*)?", value):
        raise ValueError(f"unsupported version syntax: {value!r}")
    return value


def version_key(value: str) -> tuple:
    parts = re.split(r"[._+-]", value.lower())
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in parts)


def satisfies(version: str, specifiers: str) -> bool:
    if not specifiers:
        return True
    for raw in specifiers.split(","):
        match = SPEC_RE.fullmatch(re.sub(r"\s+", "", raw))
        if not match:
            raise ValueError(f"unsupported specifier: {raw!r}")
        op, wanted = match.groups()
        if wanted.endswith(".*"):
            prefix = wanted[:-2]
            equal = version == prefix or version.startswith(prefix + ".")
            ok = equal if op == "==" else not equal if op == "!=" else False
        else:
            left, right = version_key(version), version_key(wanted)
            ok = {"==": left == right, "===": version == wanted, "!=": left != right,
                  "<": left < right, "<=": left <= right, ">": left > right,
                  ">=": left >= right}.get(op)
            if op == "~=":
                nums = wanted.split(".")
                prefix = ".".join(nums[:-1] if len(nums) > 2 else nums[:1])
                ok = left >= right and (version == prefix or version.startswith(prefix + "."))
        if not ok:
            return False
    return True


def marker_tokens(text: str) -> list[tuple[str, str]]:
    result, pos = [], 0
    while pos < len(text):
        match = TOKEN_RE.match(text, pos)
        if not match:
            raise ValueError(f"unsupported marker syntax near {text[pos:]!r}")
        kind = ("word", "ident", "string", "op", "lpar", "rpar")[next(i for i, v in enumerate(match.groups()) if v is not None)]
        result.append((kind, next(v for v in match.groups() if v is not None)))
        pos = match.end()
    return result


def evaluate_marker(text: str, *, extra: str = "") -> bool:
    tokens, index = marker_tokens(text), 0
    environment = dict(TARGET_ENV); environment["extra"] = extra
    def peek(value=None):
        if index >= len(tokens): return False
        return tokens[index] if value is None else tokens[index][1] == value
    def take(value=None):
        nonlocal index
        if index >= len(tokens) or (value is not None and tokens[index][1] != value):
            raise ValueError(f"invalid marker near token {index}: {text!r}")
        token = tokens[index]; index += 1; return token
    def operand():
        kind, value = take()
        if kind == "ident":
            if value not in environment: raise ValueError(f"unknown marker variable: {value}")
            return environment[value], value
        if kind == "string":
            return bytes(value[1:-1], "utf-8").decode("unicode_escape"), None
        raise ValueError("marker operand required")
    def comparison():
        left, left_name = operand()
        first = take()[1]
        if first == "not": take("in"); op = "not in"
        elif first == "in": op = "in"
        elif first in {"==", "!=", "<", "<=", ">", ">="}: op = first
        else: raise ValueError(f"invalid marker operator: {first}")
        right, right_name = operand()
        version_compare = any(name and name.endswith("version") for name in (left_name, right_name))
        a, b = (version_key(left), version_key(right)) if version_compare else (left, right)
        return {"==": a == b, "!=": a != b, "<": a < b, "<=": a <= b,
                ">": a > b, ">=": a >= b, "in": str(a) in str(b),
                "not in": str(a) not in str(b)}[op]
    def atom():
        if peek("("):
            take("("); value = expression(); take(")"); return value
        return comparison()
    def conjunction():
        value = atom()
        while peek("and"):
            take("and"); right = atom(); value = value and right
        return value
    def expression():
        value = conjunction()
        while peek("or"):
            take("or"); right = conjunction(); value = value or right
        return value
    value = expression()
    if index != len(tokens): raise ValueError(f"trailing marker tokens: {text!r}")
    return value


def parse_requirement(raw: str, *, active_extras: set[str] | None = None) -> tuple[str, str, set[str], bool]:
    if "@" in raw.split(";", 1)[0]: raise ValueError(f"URL requirement rejected: {raw}")
    requirement, marker = (raw.split(";", 1) + [""])[:2]
    match = REQ_RE.fullmatch(requirement)
    if not match: raise ValueError(f"unsupported requirement: {raw}")
    name, extras_text, specs = match.groups()
    extras={canonical_name(x.strip()) for x in extras_text.split(",")} if extras_text else set()
    contexts=active_extras or {""}
    active=any(evaluate_marker(marker.strip(),extra=extra) for extra in contexts) if marker.strip() else True
    if specs and not all(SPEC_RE.fullmatch(re.sub(r"\s+", "", x)) for x in specs.split(",")):
        raise ValueError(f"unsupported requirement specifier: {raw}")
    return canonical_name(name), specs, extras, active


def sha256_bytes(data: bytes) -> str: return hashlib.sha256(data).hexdigest()


def read_fd_all(fd: int, max_bytes: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET); chunks=[]; total=0
    while True:
        chunk=os.read(fd, min(READ_CHUNK, max_bytes-total+1))
        if not chunk: break
        total += len(chunk)
        if total > max_bytes: raise ValueError("file exceeds read limit")
        chunks.append(chunk)
    return b"".join(chunks)


def stable_identity(st: os.stat_result) -> tuple:
    return (st.st_dev, st.st_ino, st.st_mode, st.st_uid, st.st_gid, st.st_nlink,
            st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def validate_owned(st: os.stat_result, *, directory: bool) -> None:
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(st.st_mode): raise ValueError("wrong filesystem object type")
    if st.st_uid != os.geteuid(): raise ValueError("object owner mismatch")
    if st.st_mode & 0o022: raise ValueError("group/other-writable object rejected")
    if not directory and st.st_nlink != 1: raise ValueError("wheel link count must be one")


def safe_path(name: str) -> str:
    if not name or "\\" in name or "\x00" in name or unicodedata.normalize("NFC", name) != name:
        raise ValueError(f"unsafe/non-NFC member path: {name!r}")
    path=PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError(f"unsafe member path: {name!r}")
    normalized="/".join(path.parts) + ("/" if name.endswith("/") else "")
    if normalized != name: raise ValueError(f"non-normalized member path: {name!r}")
    return name


def strict_message(data: bytes, *, wheel: bool=False):
    message=BytesParser(policy=policy.default).parsebytes(data)
    if message.defects: raise ValueError(f"metadata parser defects: {message.defects}")
    singleton=SINGLETON_WHEEL if wheel else SINGLETON_METADATA
    for key in singleton:
        if len(message.get_all(key, [])) > 1: raise ValueError(f"duplicate singleton metadata field: {key}")
    required=("Wheel-Version","Root-Is-Purelib","Tag") if wheel else ("Metadata-Version","Name","Version")
    for key in required:
        if not message.get_all(key): raise ValueError(f"missing metadata field: {key}")
    return message


def read_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    if info.file_size > MAX_MEMBER_EXPANDED: raise ValueError("member expanded size exceeds limit")
    chunks=[]; total=0
    with archive.open(info, "r") as stream:
        while True:
            chunk=stream.read(min(READ_CHUNK, info.file_size-total+1))
            if not chunk: break
            total += len(chunk)
            if total > info.file_size or total > MAX_MEMBER_EXPANDED: raise ValueError("member read exceeds declared/allowed size")
            chunks.append(chunk)
    if total != info.file_size: raise ValueError("member read size mismatch")
    return b"".join(chunks)


def inspect_open_wheel(fd: int, filename: str) -> dict:
    before=os.fstat(fd); validate_owned(before, directory=False)
    if before.st_size > MAX_ARCHIVE_BYTES: raise ValueError("wheel archive exceeds limit")
    wheel_sha=sha256_bytes(read_fd_all(fd, MAX_ARCHIVE_BYTES))
    os.lseek(fd,0,os.SEEK_SET)
    with os.fdopen(os.dup(fd), "rb", closefd=True) as stream, zipfile.ZipFile(stream) as archive:
        infos=archive.infolist()
        if not infos or len(infos)>MAX_MEMBERS_PER_WHEEL: raise ValueError("wheel member count exceeds limit")
        names=set(); folded=set(); total_expanded=0
        for info in infos:
            name=safe_path(info.filename); key=unicodedata.normalize("NFC",name).casefold()
            if name in names or key in folded: raise ValueError(f"duplicate/colliding member path: {name}")
            names.add(name); folded.add(key)
            if info.flag_bits & 1: raise ValueError("encrypted wheel member rejected")
            mode=info.external_attr >> 16; kind=stat.S_IFMT(mode)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR): raise ValueError("special archive member rejected")
            if mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX): raise ValueError("special archive permission bits rejected")
            if name.endswith("/") and kind not in (0,stat.S_IFDIR): raise ValueError("directory type mismatch")
            if not name.endswith("/") and kind==stat.S_IFDIR: raise ValueError("file type mismatch")
            if info.file_size > MAX_MEMBER_EXPANDED: raise ValueError("member expanded size exceeds limit")
            if info.file_size > MAX_EXPANSION_RATIO*max(info.compress_size,1): raise ValueError("member expansion ratio exceeds limit")
            total_expanded += info.file_size
        if total_expanded > MAX_TOTAL_EXPANDED: raise ValueError("wheel expanded size exceeds total limit")
        file_infos={i.filename:i for i in infos if not i.is_dir()}
        metadata_names=[n for n in file_infos if n.endswith(".dist-info/METADATA")]
        wheel_names=[n for n in file_infos if n.endswith(".dist-info/WHEEL")]
        record_names=[n for n in file_infos if n.endswith(".dist-info/RECORD")]
        if not (len(metadata_names)==len(wheel_names)==len(record_names)==1): raise ValueError("wheel must have one METADATA/WHEEL/RECORD")
        metadata_name,wheel_name,record_name=metadata_names[0],wheel_names[0],record_names[0]
        prefixes={x.rsplit("/",1)[0] for x in (metadata_name,wheel_name,record_name)}
        if len(prefixes)!=1: raise ValueError("dist-info identity mismatch")
        metadata_bytes=read_member(archive,file_infos[metadata_name]); wheel_bytes=read_member(archive,file_infos[wheel_name]); record_bytes=read_member(archive,file_infos[record_name])
        cached_members={metadata_name:metadata_bytes,wheel_name:wheel_bytes,record_name:record_bytes}
        metadata=strict_message(metadata_bytes); wheel_meta=strict_message(wheel_bytes,wheel=True)
        name=canonical_name(str(metadata["Name"])); version=normalized_version(str(metadata["Version"]))
        stem=filename[:-4]
        parts=stem.split("-")
        if len(parts) not in (5,6): raise ValueError("unsupported wheel filename shape")
        dist_field,version_field=parts[0],parts[1]
        tags="-".join(parts[-3:])
        if tags not in ALLOWED_TAGS: raise ValueError(f"wheel tag not accepted: {tags}")
        if canonical_name(dist_field)!=name or normalized_version(version_field)!=version: raise ValueError("filename metadata identity mismatch")
        expected_prefix=f"{dist_field}-{version_field}.dist-info"
        if next(iter(prefixes)) != expected_prefix: raise ValueError("dist-info normalized project/version identity mismatch")
        metadata_tags=wheel_meta.get_all("Tag",[])
        if metadata_tags != [tags]: raise ValueError("WHEEL tag mismatch/duplicate")
        requires_python=metadata.get("Requires-Python")
        if requires_python and not satisfies("3.12.0", str(requires_python)): raise ValueError("Requires-Python excludes 3.12")
        rows=list(csv.reader(io.StringIO(record_bytes.decode("utf-8",errors="strict"))))
        if any(len(row)!=3 for row in rows): raise ValueError("RECORD row must have exactly 3 columns")
        record_map={}; record_folded=set()
        for path,digest,size in rows:
            safe_path(path); key=unicodedata.normalize("NFC",path).casefold()
            if path in record_map or key in record_folded: raise ValueError("duplicate/colliding RECORD path")
            record_map[path]=(digest,size);record_folded.add(key)
        if set(record_map)!=set(file_infos): raise ValueError("RECORD membership must exactly match non-directory members")
        tree_rows=[]
        for path,info in file_infos.items():
            data = cached_members[path] if path in cached_members else read_member(archive,info)
            digest,size=record_map[path]
            if path==record_name:
                if digest or size: raise ValueError("RECORD self-entry must be unhashed")
            else:
                try: algorithm,encoded=digest.split("=",1)
                except ValueError: raise ValueError("malformed RECORD digest")
                expected=base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
                if algorithm!="sha256" or encoded!=expected or not size.isdigit() or int(size)!=len(data): raise ValueError("RECORD digest/size mismatch")
            tree_rows.append((path,sha256_bytes(data)))
    after=os.fstat(fd)
    if stable_identity(before)!=stable_identity(after): raise ValueError("wheel identity changed during inspection")
    dependencies=metadata.get_all("Requires-Dist",[]) or []
    return {"name":name,"version":version,"filename":filename,"sha256":wheel_sha,"size":before.st_size,
            "wheel_tags":[tags],"requires_python":str(requires_python) if requires_python else None,
            "requires_dist":[str(x) for x in dependencies],
            "licenses":{"expression":str(metadata.get("License-Expression")) if metadata.get("License-Expression") else None,
                        "legacy":str(metadata.get("License")) if metadata.get("License") else None,
                        "classifiers":[str(x) for x in metadata.get_all("Classifier",[]) if str(x).startswith("License ::")],
                        "files":[str(x) for x in metadata.get_all("License-File",[]) or []]},
            "record":{"member":record_name,"sha256":sha256_bytes(record_bytes),
                      "archive_tree_sha256":hashlib.sha256(json.dumps(sorted(tree_rows),separators=(",",":")).encode()).hexdigest(),
                      "validated_members":len(file_infos)},
            "archive":{"member_count":len(infos),"expanded_size":total_expanded}}


def inspect_wheelhouse_at(parentfd: int, dirname: str) -> tuple[list[dict], list[dict]]:
    if dirname != "wheelhouse": raise ValueError("wheelhouse basename binding mismatch")
    flags=os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0)
    dirfd=os.open(dirname,flags,dir_fd=parentfd)
    try:
        before=os.fstat(dirfd);validate_owned(before,directory=True)
        names=sorted(os.listdir(dirfd))
        if len(names)!=MAX_WHEELS or any(not n.endswith(".whl") or "/" in n for n in names): raise ValueError("wheelhouse must contain exactly 30 wheel files")
        artifacts=[];total_members=0;total_expanded=0
        for name in names:
            fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0),dir_fd=dirfd)
            try: item=inspect_open_wheel(fd,name)
            finally: os.close(fd)
            artifacts.append(item);total_members+=item["archive"]["member_count"];total_expanded+=item["archive"]["expanded_size"]
        after=os.fstat(dirfd)
        if stable_identity(before)!=stable_identity(after): raise ValueError("wheelhouse identity changed during inspection")
        if total_members>MAX_MEMBERS_TOTAL or total_expanded>MAX_TOTAL_EXPANDED: raise ValueError("wheelhouse aggregate limits exceeded")
    finally: os.close(dirfd)
    if len({a["name"] for a in artifacts})!=len(artifacts): raise ValueError("duplicate normalized distribution")
    versions={a["name"]:a["version"] for a in artifacts};contexts={name:{""} for name in versions};edge_rows=set()
    changed=True
    while changed:
        changed=False
        for item in artifacts:
            for raw in item["requires_dist"]:
                dep,specs,requested_extras,active=parse_requirement(raw,active_extras=contexts[item["name"]])
                if not active: continue
                if dep not in versions or not satisfies(versions[dep],specs): raise ValueError(f"unsatisfied dependency: {item['name']} -> {raw}")
                edge_rows.add((item["name"],dep,raw))
                before=len(contexts[dep]);contexts[dep].update(requested_extras)
                if len(contexts[dep])!=before: changed=True
    edges=[{"from":source,"to":target,"requirement":requirement} for source,target,requirement in sorted(edge_rows)]
    return sorted(artifacts,key=lambda x:x["name"]),edges


def inspect_wheelhouse(path: Path) -> tuple[list[dict], list[dict]]:
    path=path.resolve(strict=True)
    parentfd=os.open(path.parent,os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0))
    try: return inspect_wheelhouse_at(parentfd,path.name)
    finally: os.close(parentfd)


def lock_text(artifacts: list[dict]) -> str:
    lines=["# Exact CPython 3.12 macOS arm64 wheel lock; one sealed artifact per package.",
           "# Offline install requires --no-index --find-links --require-hashes --only-binary=:all:.","--only-binary=:all:"]
    for a in artifacts: lines.append(f"{a['name']}=={a['version']} --hash=sha256:{a['sha256']}  # {a['filename']}")
    return "\n".join(lines)+"\n"


def sums_text(artifacts: list[dict]) -> str:
    return "".join(f"{a['sha256']}  {a['filename']}\n" for a in sorted(artifacts,key=lambda x:x["filename"]))


def read_frozen_controls_at(rootfd: int, expected_seal_sha256: str) -> tuple[dict[str, bytes], dict[str, str]]:
    if not re.fullmatch(r"[0-9a-f]{64}",expected_seal_sha256): raise ValueError("expected seal SHA256 must be 64 lowercase hex characters")
    flags=os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0)
    dirfd=os.open(SEAL_NAME,flags,dir_fd=rootfd)
    try:
        before=os.fstat(dirfd);validate_owned(before,directory=True)
        expected={"manifest.json","requirements.lock.txt","SHA256SUMS","seal.json"}
        if set(os.listdir(dirfd))!=expected: raise ValueError("frozen seal file set mismatch")
        payload={};identities={}
        seal_fd=os.open("seal.json",os.O_RDONLY|getattr(os,"O_NOFOLLOW",0),dir_fd=dirfd)
        try:
            first=os.fstat(seal_fd);validate_owned(first,directory=False)
            seal_data=read_fd_all(seal_fd,2*1024*1024)
            if stable_identity(first)!=stable_identity(os.fstat(seal_fd)): raise ValueError("seal anchor changed during read")
        finally: os.close(seal_fd)
        seal_digest=sha256_bytes(seal_data)
        if seal_digest!=expected_seal_sha256: raise ValueError("external seal SHA256 mismatch")
        payload["seal.json"]=seal_data;identities["seal.json"]=seal_digest
        for name in sorted(expected-{"seal.json"}):
            fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0),dir_fd=dirfd)
            try:
                first=os.fstat(fd);validate_owned(first,directory=False)
                data=read_fd_all(fd,2*1024*1024)
                if stable_identity(first)!=stable_identity(os.fstat(fd)): raise ValueError("frozen control changed during read")
                payload[name]=data;identities[name]=sha256_bytes(data)
            finally: os.close(fd)
        if stable_identity(before)!=stable_identity(os.fstat(dirfd)): raise ValueError("frozen seal directory changed during read")
        return payload,identities
    finally: os.close(dirfd)


def verify_frozen(candidate: Path, expected_seal_sha256: str) -> dict:
    flags=os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0)
    rootfd=os.open(candidate,flags)
    try:
        root_before=os.fstat(rootfd);validate_owned(root_before,directory=True)
        control_bytes,control_hashes=read_frozen_controls_at(rootfd,expected_seal_sha256)
        frozen_seal=json.loads(control_bytes["seal.json"])
        expected_hashes={name:digest for name,digest in control_hashes.items() if name!="seal.json"}
        if frozen_seal.get("control_sha256")!=expected_hashes: raise ValueError("frozen control digest mismatch")
        manifest=json.loads(control_bytes["manifest.json"])
        artifacts,edges=inspect_wheelhouse_at(rootfd,"wheelhouse")
        if stable_identity(root_before)!=stable_identity(os.fstat(rootfd)): raise ValueError("candidate root changed during verification")
    finally: os.close(rootfd)
    frozen=manifest.get("artifacts",[])
    if len(frozen)!=len(artifacts): raise ValueError("manifest artifact count mismatch")
    for actual,expected in zip(artifacts,frozen):
        core={k:v for k,v in expected.items() if k!="source"}
        if actual!=core: raise ValueError(f"frozen manifest mismatch: {actual['filename']}")
        source=expected.get("source",{})
        if source.get("artifact_sha256")!=actual["sha256"] or source.get("filename")!=actual["filename"]: raise ValueError("source binding mismatch")
        if source.get("yanked") is not False: raise ValueError("yanked/unknown source rejected")
    if edges!=manifest.get("dependency_edges"): raise ValueError("dependency edge mismatch")
    if control_bytes["requirements.lock.txt"].decode()!=lock_text(artifacts): raise ValueError("exact lock mismatch")
    if control_bytes["SHA256SUMS"].decode()!=sums_text(artifacts): raise ValueError("SHA256SUMS mismatch")
    return {"status":"READY_FOR_OFFLINE_INSTALL","artifacts":len(artifacts),"dependency_edges":len(edges),
            "expected_seal_sha256":expected_seal_sha256,"wheelhouse_sha256":sha256_bytes(sums_text(artifacts).encode()),
            "control_sha256":control_hashes,"read_only":True,"provider_calls":False,"provider_spend_usd":0}
