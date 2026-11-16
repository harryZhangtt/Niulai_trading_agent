import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "shared" / "job_runtime" / "vm_assets" / "macos"
HOST = (HELPER / "ContainmentHost.swift").read_text(encoding="utf-8")
PROTOCOL = (HELPER / "Protocol.swift").read_text(encoding="utf-8")
SWIFT = HOST + "\n" + PROTOCOL


class MacOSVMHelperStaticTests(unittest.TestCase):
    def test_expected_source_only_files_and_reserved_guest_absence(self):
        self.assertTrue((HELPER / "request.schema.json").is_file())
        self.assertTrue((HELPER / "network-profile.schema.json").is_file())
        self.assertTrue((HELPER / "README.md").is_file())
        self.assertTrue((HELPER / "toolchain-lock.json").is_file())

    def test_exact_cli_has_only_request_file(self):
        self.assertIn('CommandLine.arguments.count == 3', HOST)
        self.assertIn('CommandLine.arguments[1] == "--request-file"', HOST)
        self.assertNotRegex(HOST, r'CommandLine\.arguments\[[23]\].*(nonce|prompt|digest)')
        self.assertNotIn('ArgumentParser', SWIFT)

    def test_no_host_subprocess_shell_network_client_or_logging_api(self):
        forbidden = [
            r'\bProcess\s*\(', r'\bNSTask\b', r'\bsystem\s*\(', r'\bpopen\s*\(',
            r'\bposix_spawn\b', r'\bexec[lvpe]*\s*\(', r'\bURLSession\b',
            r'\bNSLog\s*\(', r'\bos_log\s*\(', r'\bLogger\s*\(', r'\bprint\s*\('
        ]
        for pattern in forbidden:
            self.assertNotRegex(SWIFT, pattern)
        self.assertEqual(HOST.count("FileHandle.standardError.write"), 1)
        self.assertIn('"containment-host:" + code', HOST)

    def test_no_absolute_global_or_user_paths_in_swift(self):
        for fragment in ["/Users/", "/home/", "/var/", "/tmp/", "/usr/", "/bin/"]:
            self.assertNotIn(fragment, SWIFT)

    def test_nofollow_owner_mode_size_and_digest_checks_are_present(self):
        for token in [
            "O_NOFOLLOW", "metadata.st_uid == geteuid()", "metadata.st_mode & 0o077",
            "maximumRequestBytes = 65_536", "SHA256", '"digest_mismatch"'
        ]:
            self.assertIn(token, PROTOCOL)
        for token in ["openat(rootDescriptor", "O_DIRECTORY | O_NOFOLLOW", "fstatat(parent",
                      'URL(fileURLWithPath: "/dev/fd/', "pinExisting", "pinNew"]:
            self.assertIn(token, HOST)
        self.assertNotIn("resolvingSymlinksInPath", HOST)
        self.assertIn("DuplicateKeyRejector", PROTOCOL)
        self.assertIn('"duplicate_json_key"', PROTOCOL)
        self.assertIn('request.nonce.range(of: "^[0-9a-f]{64}$"', HOST)

    def test_held_dirfd_model_survives_intermediate_ancestor_swap(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            authority = root / "artifacts"
            authority.mkdir(mode=0o700)
            (authority / "kernel").write_bytes(b"pinned")
            descriptor = os.open(authority, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                authority.rename(root / "moved")
                (root / "replacement").mkdir()
                authority.symlink_to(root / "replacement", target_is_directory=True)
                (root / "replacement" / "kernel").write_bytes(b"attacker")
                child = os.open("kernel", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=descriptor)
                try:
                    self.assertEqual(os.read(child, 16), b"pinned")
                finally:
                    os.close(child)
            finally:
                os.close(descriptor)

    def test_swift_rejects_duplicate_and_secret_like_environment_references(self):
        for token in ["environmentNames.insert", "environment_contract", "secretLike", "tokenLike",
                      "^[A-Z][A-Z0-9_]{0,63}$"]:
            self.assertIn(token, HOST)

    def test_dev_fd_cow_is_writable_while_boot_artifact_is_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            boot, cow = root / "kernel", root / "cow"
            boot.write_bytes(b"boot"); cow.write_bytes(b"cow0")
            boot.chmod(0o600); cow.chmod(0o600)
            boot_fd = os.open(boot, os.O_RDONLY)
            cow_fd = os.open(cow, os.O_RDWR)
            try:
                cow_view = os.open(f"/dev/fd/{cow_fd}", os.O_RDWR)
                try:
                    os.lseek(cow_view, 0, os.SEEK_SET); os.write(cow_view, b"C")
                finally:
                    os.close(cow_view)
                with self.assertRaises(OSError):
                    os.open(f"/dev/fd/{boot_fd}", os.O_RDWR)
                self.assertEqual(cow.read_bytes()[:1], b"C")
            finally:
                os.close(boot_fd); os.close(cow_fd)
        self.assertIn('(role == "cow") == writable', HOST)
        self.assertIn('writable: role == "cow"', HOST)
        self.assertIn('let access = writable ? O_RDWR : O_RDONLY', HOST)

    def test_single_vm_owner_and_fixed_virtual_devices(self):
        self.assertEqual(HOST.count("VZVirtualMachine(configuration:"), 1)
        for token in [
            "VZLinuxBootLoader", "VZDiskImageStorageDeviceAttachment",
            "VZVirtioSocketDeviceConfiguration", "VZVirtioConsoleDeviceConfiguration",
            "VZVirtioFileSystemDeviceConfiguration", "VZNATNetworkDeviceAttachment"
        ]:
            self.assertIn(token, HOST)
        self.assertIn("mount.readOnly", HOST)
        self.assertIn("fclonefileat", HOST)
        self.assertIn("mkdirat(rootDescriptor", HOST)
        self.assertIn("unlinkat(rootDescriptor", HOST)
        self.assertIn('identities.insert("\\(metadata.st_dev):\\(metadata.st_ino)")', HOST)
        self.assertIn('request.network.mode == "unrestrictedNat"', HOST)
        self.assertIn("configuration.networkDevices = []", HOST)

    def test_framing_stop_ack_and_bounded_teardown_are_explicit(self):
        self.assertIn("UInt32(payload.count).bigEndian", HOST)
        self.assertIn("F_SETNOSIGPIPE", HOST)
        self.assertIn('framePoweroff: // FRAME_POWEROFF / stop_ack', HOST)
        self.assertIn('send(type: frameCancel)', HOST)
        self.assertIn("ExactSchema.validateGuestFrame", HOST)
        for binding in ["request_sha256", "artifact_generation", "nonce_digest", "request_id"]:
            self.assertIn('"' + binding + '"', HOST)
            self.assertIn('"' + binding + '"', PROTOCOL)
        self.assertIn("request.resources.maxRuntimeSeconds", HOST)
        self.assertIn("request.resources.shutdownGraceSeconds", HOST)
        self.assertIn("stopAcknowledged", PROTOCOL)
        self.assertIn("teardownConfirmed", PROTOCOL)
        self.assertIn('"teardown_unknown"', HOST)
        self.assertIn("vm.stop", HOST)
        self.assertIn("DispatchSource.makeSignalSource", HOST)
        self.assertIn("CancellationState", HOST)
        self.assertIn('runtime("cancelled")', HOST)

    def test_outputs_publish_atomically_without_overwrite(self):
        for token in ["openat", "renameatx_np", "RENAME_EXCL", "fsync(parent)"]:
            self.assertIn(token, PROTOCOL)
        self.assertIn("request.io.outputPath != request.receiptPath", HOST)

    def test_receipt_schema_excludes_sensitive_values(self):
        match = re.search(r"struct TeardownReceipt: Codable \{(?P<body>.*?)\n\}", PROTOCOL, re.S)
        self.assertIsNotNone(match)
        body = match.group("body")
        for forbidden in ["prompt", "path", "outputData"]:
            self.assertNotIn(forbidden, body)
        for binding in ["nonceDigest", "requestSHA256", "artifactGeneration", "exitCode",
                        "terminationSignal", "errorCode"]:
            self.assertIn(binding, body)

    def test_request_schema_is_closed_and_has_no_host_socket_paths(self):
        schema = json.loads((HELPER / "request.schema.json").read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["protocolVersion"]["const"], 1)
        mount_variants = schema["properties"]["mounts"]["items"]["oneOf"]
        self.assertEqual(mount_variants[0]["properties"]["role"]["const"], "input")
        self.assertIs(mount_variants[0]["properties"]["readOnly"]["const"], True)
        self.assertEqual(set(mount_variants[1]["properties"]["role"]["enum"]), {"auth", "run", "output"})
        self.assertIs(mount_variants[1]["properties"]["readOnly"]["const"], False)
        self.assertEqual(set(schema["properties"]["sockets"]["properties"]), {"controlPort", "stdioPort"})
        serialized = json.dumps(schema).lower()
        self.assertNotIn("socketpath", serialized)
        self.assertNotIn("workspace", serialized)
        self.assertNotIn("home", serialized)

        def assert_closed(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertIs(node.get("additionalProperties"), False)
                for value in node.values():
                    assert_closed(value)
            elif isinstance(node, list):
                for value in node:
                    assert_closed(value)

        assert_closed(schema)

    def test_build_recipe_is_workspace_local_and_nonexecuting(self):
        script = (HELPER / "build-source.sh").read_text(encoding="utf-8")
        self.assertIn('.job-runtime/tests/', script)
        self.assertIn("xcrun swiftc", script)
        self.assertIn("toolchain-lock.json", script)
        self.assertIn("toolchain-lock-mismatch", script)
        lock = json.loads((HELPER / "toolchain-lock.json").read_text())
        self.assertEqual(lock["outputDigestAlgorithm"], "sha256")
        self.assertEqual(set(lock["sources"]), {"Protocol.swift", "ContainmentHost.swift"})
        for forbidden in ["codesign", "launchctl", "containment-host --request-file", "curl ", "wget "]:
            self.assertNotIn(forbidden, script)

    def test_build_recipe_rejects_fake_toolchain_before_compile(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fake_swift = root / "swiftc"
            fake_swift.write_text("#!/bin/sh\nprintf 'wrong toolchain\\n'\n")
            fake_swift.chmod(0o700)
            marker = root / "compile-called"
            xcrun = root / "xcrun"
            xcrun.write_text(
                "#!/bin/sh\nif [ \"$1\" = --find ]; then printf '%s\\n' '" + str(fake_swift) +
                "'; else : > '" + str(marker) + "'; exit 99; fi\n")
            xcrun.chmod(0o700)
            environment = dict(os.environ, PATH=str(root) + os.pathsep + os.environ.get("PATH", ""))
            result = subprocess.run([str(HELPER / "build-source.sh")], env=environment,
                                    text=True, capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("toolchain-lock-mismatch", result.stderr)
            self.assertFalse(marker.exists())

    def test_readme_labels_runtime_behavior_unexecuted(self):
        readme = (HELPER / "README.md").read_text(encoding="utf-8")
        self.assertIn("The VM behavior is unexecuted and unaccepted.", readme)
        self.assertIn("source-contract evidence only", readme)
        self.assertIn("guest_agent.py", readme)


if __name__ == "__main__":
    unittest.main()
