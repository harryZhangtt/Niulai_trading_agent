from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import io
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import seal_wheelhouse
import offline_install_plan
import wheel_gate
from wheel_gate import (
    inspect_open_wheel,
    inspect_wheelhouse,
    lock_text,
    parse_requirement,
    sums_text,
    verify_frozen,
)


def record_digest(data: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def make_wheel(
    path: Path,
    *,
    name: str = "demo",
    version: str = "1.0",
    prefix: str | None = None,
    metadata_extra: str = "",
    entries: list[tuple[str, bytes, int | None]] | None = None,
    record_mode: str = "valid",
) -> None:
    dist = name.replace("-", "_")
    prefix = prefix or f"{dist}-{version}.dist-info"
    metadata = (
        f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n"
        f"Requires-Python: >=3.10\n{metadata_extra}\n"
    ).encode()
    wheel = b"Wheel-Version: 1.0\nGenerator: tests\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    payload = entries or [(f"{dist}/__init__.py", b"VALUE = 1\n", None)]
    files = [(f"{prefix}/METADATA", metadata, None), (f"{prefix}/WHEEL", wheel, None)] + payload
    rows = [[n, record_digest(d), str(len(d))] for n, d, _ in files]
    record_name = f"{prefix}/RECORD"
    if record_mode == "wrong-hash":
        rows[0][1] = "sha256=" + "A" * 43
    elif record_mode == "missing":
        rows.pop(0)
    elif record_mode == "duplicate":
        rows.append(list(rows[0]))
    rows.append([record_name, "", ""])
    if record_mode == "four-columns":
        rows[0].append("extra")
    record = "".join(",".join(row) + "\n" for row in rows).encode()
    files.append((record_name, record, None))
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, data, mode in files:
            info = zipfile.ZipInfo(filename)
            info.compress_type = zipfile.ZIP_DEFLATED
            if mode is not None:
                info.create_system = 3
                info.external_attr = mode << 16
            archive.writestr(info, data)


def inspect_one(path: Path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        return inspect_open_wheel(fd, path.name)
    finally:
        os.close(fd)


def seal_sha(root: Path) -> str:
    return hashlib.sha256((root / "seal-v4/seal.json").read_bytes()).hexdigest()


def make_candidate(root: Path) -> Path:
    wheelhouse = root / "wheelhouse"
    wheelhouse.mkdir()
    for index in range(30):
        name = f"pkg{index}"
        make_wheel(wheelhouse / f"{name}-1.0-py3-none-any.whl", name=name)
    artifacts, edges = inspect_wheelhouse(wheelhouse)
    for item in artifacts:
        item["source"] = {
            "filename": item["filename"],
            "artifact_sha256": item["sha256"],
            "yanked": False,
        }
    seal = root / "seal-v4"
    seal.mkdir()
    manifest = {"artifacts": artifacts, "dependency_edges": edges}
    (seal / "manifest.json").write_text(json.dumps(manifest) + "\n")
    core = [{k: v for k, v in item.items() if k != "source"} for item in artifacts]
    (seal / "requirements.lock.txt").write_text(lock_text(core))
    (seal / "SHA256SUMS").write_text(sums_text(core))
    controls={name:hashlib.sha256((seal/name).read_bytes()).hexdigest() for name in ("manifest.json","requirements.lock.txt","SHA256SUMS")}
    (seal / "seal.json").write_text(json.dumps({"schema_version":1,"control_sha256":controls})+"\n")
    return root


class WheelGateTests(unittest.TestCase):
    def test_real_frozen_candidate_is_read_only(self):
        controls = [HERE / "seal-v4/manifest.json", HERE / "seal-v4/requirements.lock.txt", HERE / "seal-v4/SHA256SUMS", HERE / "seal-v4/seal.json"]
        before = [(p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in controls]
        result = verify_frozen(HERE, seal_sha(HERE))
        after = [(p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in controls]
        self.assertEqual(result["status"], "READY_FOR_OFFLINE_INSTALL")
        self.assertEqual(before, after)

    def test_valid_synthetic_wheel_and_no_ambient_packaging(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "demo-1.0-py3-none-any.whl"
            make_wheel(path)
            self.assertEqual(inspect_one(path)["name"], "demo")
        self.assertNotIn("pip._vendor", (HERE / "wheel_gate.py").read_text())

    def test_record_strict_failures(self):
        for mode in ("wrong-hash", "missing", "duplicate", "four-columns"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as td:
                path = Path(td) / "demo-1.0-py3-none-any.whl"
                make_wheel(path, record_mode=mode)
                with self.assertRaises(ValueError):
                    inspect_one(path)

    def test_metadata_duplicate_defect_and_dist_info_identity(self):
        cases = [
            {"metadata_extra": "Name: other\n"},
            {"metadata_extra": "broken header without colon\n"},
            {"prefix": "other-1.0.dist-info"},
        ]
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as td:
                path = Path(td) / "demo-1.0-py3-none-any.whl"
                make_wheel(path, **case)
                with self.assertRaises(ValueError):
                    inspect_one(path)

    def test_member_path_unicode_casefold_and_special_type_rejected(self):
        cases = [
            [("pkg/A.py", b"a", None), ("pkg/a.py", b"b", None)],
            [("pkg/é.py", b"a", None)],
            [("../escape.py", b"a", None)],
            [("pkg/link", b"target", stat.S_IFLNK | 0o777)],
            [("pkg/privileged", b"x", stat.S_IFREG | stat.S_ISUID | 0o755)],
        ]
        for entries in cases:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as td:
                path = Path(td) / "demo-1.0-py3-none-any.whl"
                make_wheel(path, entries=entries)
                with self.assertRaises(ValueError):
                    inspect_one(path)

    def test_encryption_flag_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "demo-1.0-py3-none-any.whl"
            make_wheel(path)
            data = bytearray(path.read_bytes())
            for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
                start = 0
                while True:
                    index = data.find(signature, start)
                    if index < 0:
                        break
                    flags = int.from_bytes(data[index + offset:index + offset + 2], "little") | 1
                    data[index + offset:index + offset + 2] = flags.to_bytes(2, "little")
                    start = index + 4
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                inspect_one(path)

    def test_expansion_ratio_and_member_count_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "demo-1.0-py3-none-any.whl"
            make_wheel(path, entries=[("demo/zeros.bin", b"\0" * 1024 * 1024, None)])
            with self.assertRaises(ValueError):
                inspect_one(path)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "demo-1.0-py3-none-any.whl"
            entries = [(f"demo/f{i}.txt", b"x", None) for i in range(513)]
            make_wheel(path, entries=entries)
            with self.assertRaises(ValueError):
                inspect_one(path)

    def test_expanded_read_limits_are_enforced(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"demo-1.0-py3-none-any.whl"
            make_wheel(path)
            with mock.patch.object(wheel_gate,"MAX_MEMBER_EXPANDED",1):
                with self.assertRaises(ValueError): inspect_one(path)
        with tempfile.TemporaryDirectory() as td:
            root=make_candidate(Path(td))
            with mock.patch.object(wheel_gate,"MAX_TOTAL_EXPANDED",1):
                with self.assertRaises(ValueError): inspect_wheelhouse(root/"wheelhouse")

    def test_filesystem_symlink_hardlink_modes_and_directory_mode_rejected(self):
        for mutation in ("symlink", "hardlink", "mode", "directory-mode"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as td:
                root = make_candidate(Path(td))
                first = sorted((root / "wheelhouse").glob("*.whl"))[0]
                if mutation == "symlink":
                    saved = root / "saved.whl"
                    first.rename(saved)
                    first.symlink_to(saved)
                elif mutation == "hardlink":
                    os.link(first, root / "extra-hardlink")
                elif mutation == "mode":
                    first.chmod(0o664)
                else:
                    (root / "wheelhouse").chmod(0o777)
                with self.assertRaises((ValueError, OSError)):
                    inspect_wheelhouse(root / "wheelhouse")

    def test_frozen_control_symlink_hardlink_mode_and_set_rejected(self):
        for mutation in ("symlink","hardlink","mode","directory-mode","extra"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as td:
                root=make_candidate(Path(td));seal=root/"seal-v4";manifest=seal/"manifest.json"
                if mutation=="symlink":
                    saved=root/"saved-manifest.json";manifest.rename(saved);manifest.symlink_to(saved)
                elif mutation=="hardlink": os.link(manifest,root/"manifest-hardlink.json")
                elif mutation=="mode": manifest.chmod(0o664)
                elif mutation=="directory-mode": seal.chmod(0o777)
                else: (seal/"unexpected").write_text("x")
                with self.assertRaises((ValueError,OSError)): verify_frozen(root, seal_sha(root))

    def test_frozen_lock_sums_and_manifest_mutations_rejected(self):
        for filename in ("requirements.lock.txt", "SHA256SUMS", "manifest.json", "seal.json"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as td:
                root = make_candidate(Path(td))
                path = root / "seal-v4" / filename
                path.write_text(path.read_text() + "mutation\n")
                with self.assertRaises((ValueError, json.JSONDecodeError)):
                    verify_frozen(root, seal_sha(root))

    def test_marker_and_requirement_parser_for_target(self):
        self.assertEqual(parse_requirement("typing-extensions>=4.16; python_version < '3.15'"), ("typing-extensions", ">=4.16", set(), True))
        self.assertEqual(parse_requirement("pyjwt[crypto]>=2.10.1"), ("pyjwt", ">=2.10.1", {"crypto"}, True))
        manifest=json.loads((HERE/"seal-v4/manifest.json").read_text())
        self.assertIn({"from":"pyjwt","to":"cryptography","requirement":"cryptography>=3.4.0; extra == \"crypto\""}, manifest["dependency_edges"])
        self.assertEqual(parse_requirement("exceptiongroup>=1; python_version < '3.11'")[3], False)
        self.assertEqual(parse_requirement("trio; extra == 'trio'")[3], False)
        with self.assertRaises(ValueError):
            parse_requirement("demo @ https://example.invalid/demo.whl")

    def test_yanked_metadata_rejected_and_attestation_not_claimed(self):
        item = {"name": "demo", "version": "1.0", "filename": "demo-1.0-py3-none-any.whl", "sha256": "a" * 64}
        payload = {"urls": [{"filename": item["filename"], "digests": {"sha256": item["sha256"]}, "packagetype": "bdist_wheel", "yanked": True}]}
        with mock.patch.object(seal_wheelhouse, "fetch", return_value=(json.dumps(payload).encode(), {})):
            with self.assertRaises(ValueError):
                seal_wheelhouse.source_for(item, "now")
        manifest = json.loads((HERE / "seal-v4/manifest.json").read_text())
        source = next(a["source"] for a in manifest["artifacts"] if a["name"] == "claude-agent-sdk")
        self.assertEqual(source["provenance_attestation"]["status"], "unavailable")
        self.assertFalse(source["provenance_attestation"]["passed"])


    def test_coordinated_control_rewrite_rejected_by_external_anchor(self):
        with tempfile.TemporaryDirectory() as td:
            root=make_candidate(Path(td));reviewed=seal_sha(root);seal=root/"seal-v4"
            manifest=json.loads((seal/"manifest.json").read_text());manifest["coordinated_rewrite"]=True
            (seal/"manifest.json").write_text(json.dumps(manifest)+"\n")
            controls={name:hashlib.sha256((seal/name).read_bytes()).hexdigest() for name in ("manifest.json","requirements.lock.txt","SHA256SUMS")}
            (seal/"seal.json").write_text(json.dumps({"schema_version":1,"control_sha256":controls})+"\n")
            with self.assertRaisesRegex(ValueError,"external seal SHA256 mismatch"):
                verify_frozen(root,reviewed)
            with self.assertRaises(ValueError): verify_frozen(root,reviewed.upper())

    def test_output_name_validation_and_atomic_destination_race(self):
        for value in ("", ".", "..", "seal.v5", "/absolute", "a/b", "a\\b", "e\u0301"):
            with self.subTest(value=value), self.assertRaises(ValueError): seal_wheelhouse.validate_output_name(value)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/"seal-tmp-source";source.mkdir();(source/"source-marker").write_text("source")
            destination=root/"seal-race";destination.mkdir();(destination/"racer-marker").write_text("racer")
            parent_fd=os.open(root,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
            try:
                with self.assertRaises(OSError) as raised:
                    seal_wheelhouse.publish_no_replace(parent_fd,source.name,destination.name)
                self.assertEqual(raised.exception.errno,17)
            finally: os.close(parent_fd)
            self.assertEqual((destination/"racer-marker").read_text(),"racer")
            self.assertTrue((source/"source-marker").is_file())

    def test_offline_plan_binds_interpreter_and_ignores_hostile_ambient(self):
        python=Path("/Users/bytedance/Desktop/Trading Agent/.job-runtime/python/cpython-3.12.16-macos-aarch64-none/bin/python3.12")
        python_sha="7a427de7a538c033f821bae69d18dba1fcf01e1947f8fdfece0d9654f680a787"
        with tempfile.TemporaryDirectory() as td:
            argv=["offline_install_plan.py","--expected-seal-sha256",seal_sha(HERE),"--python",str(python),
                  "--expected-python-sha256",python_sha,"--expected-python-version","3.12.16",
                  "--venv",str(Path(td)/"venv"),"--receipt",str(Path(td)/"receipt.json")]
            hostile={"PIP_INDEX_URL":"https://evil.invalid/simple","PIP_FIND_LINKS":"/evil",
                     "HTTPS_PROXY":"http://evil.invalid:1","PIP_CONFIG_FILE":"/evil/pip.conf","UV_CACHE_DIR":"/evil/cache"}
            output=io.StringIO()
            with mock.patch.object(sys,"argv",argv),mock.patch.dict(os.environ,hostile,clear=False),contextlib.redirect_stdout(output):
                self.assertEqual(offline_install_plan.main(),0)
            plan=json.loads(output.getvalue())
            self.assertFalse(plan["execution_available"]);self.assertEqual(plan["interpreter"]["sha256"],python_sha)
            self.assertEqual(plan["interpreter"]["version"],"3.12.16")
            self.assertEqual(plan["environment"]["inherit"],[])
            self.assertTrue(set(hostile)-{"PIP_CONFIG_FILE"} <= set(plan["environment"]["unset"]))
            rendered=json.dumps(plan)
            self.assertNotIn("evil.invalid",rendered);self.assertNotIn("/evil/cache",rendered)
            flags=plan["network_policy"]["required_flags"]
            for flag in ("--isolated","--no-cache-dir","--disable-pip-version-check","--no-index","--require-hashes","--only-binary=:all:"):
                self.assertIn(flag,flags)
        with self.assertRaises(ValueError):
            offline_install_plan.inspect_interpreter(python,"0"*64,"3.12.16")

    def test_existing_seal_refuses_overwrite_before_fetch(self):
        with mock.patch.object(sys, "argv", ["seal_wheelhouse.py", "--candidate", str(HERE), "--output-name", "seal-v4"]):
            with mock.patch.object(seal_wheelhouse, "fetch") as fetch:
                with self.assertRaises(ValueError):
                    seal_wheelhouse.main()
                fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
