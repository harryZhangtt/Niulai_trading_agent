#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
WORKSPACE=$(CDPATH= cd -- "$SCRIPT_DIR/../../../.." && pwd)
OUTPUT_ROOT="$WORKSPACE/.job-runtime/tests/macos-vm-build"
CACHE_ROOT="$WORKSPACE/.job-runtime/tests/swift-module-cache"

mkdir -p "$OUTPUT_ROOT" "$CACHE_ROOT"
export CLANG_MODULE_CACHE_PATH="$CACHE_ROOT"
export SWIFT_MODULECACHE_PATH="$CACHE_ROOT"

# Compilation only. This script does not sign, install, register, or launch the helper.
FLAGS='-parse-as-library -framework Virtualization -framework Security'
SWIFTC=$(xcrun --find swiftc)
TOOLCHAIN=$($SWIFTC -version 2>&1 | tr '\r\n' '  ' | tr -s ' ')
LOCK="$SCRIPT_DIR/toolchain-lock.json"
# Refuse toolchain, flags, or source drift before producing any output.
python3 - "$LOCK" "$SWIFTC" "$TOOLCHAIN" "$FLAGS" \
  "$SCRIPT_DIR/Protocol.swift" "$SCRIPT_DIR/ContainmentHost.swift" <<'PY'
import hashlib, json, pathlib, sys
lock_path, compiler, version, flags, protocol, host = sys.argv[1:]
lock = json.loads(pathlib.Path(lock_path).read_text())
def digest(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
actual = {"compilerPath": compiler, "compilerVersion": version, "flags": flags.split(),
          "sources": {"Protocol.swift": digest(protocol), "ContainmentHost.swift": digest(host)}}
for key, value in actual.items():
    if lock.get(key) != value:
        raise SystemExit("toolchain-lock-mismatch:" + key)
if lock.get("outputDigestAlgorithm") != "sha256":
    raise SystemExit("toolchain-lock-mismatch:outputDigestAlgorithm")
PY
xcrun swiftc \
  -parse-as-library \
  -module-cache-path "$CACHE_ROOT" \
  -framework Virtualization \
  -framework Security \
  "$SCRIPT_DIR/Protocol.swift" \
  "$SCRIPT_DIR/ContainmentHost.swift" \
  -o "$OUTPUT_ROOT/containment-host"

# Attest the exact compiler, source bytes, stable flags, and unsigned output.
python3 - "$OUTPUT_ROOT/build-manifest.json" "$SWIFTC" "$TOOLCHAIN" "$FLAGS" \
  "$SCRIPT_DIR/Protocol.swift" "$SCRIPT_DIR/ContainmentHost.swift" \
  "$OUTPUT_ROOT/containment-host" <<'PY'
import hashlib, json, pathlib, sys
manifest, compiler, version, flags, protocol, host, output = sys.argv[1:]
def digest(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
value = {"manifestVersion": 1, "compilerPath": compiler, "compilerVersion": version,
         "flags": flags.split(), "sources": {"Protocol.swift": digest(protocol),
         "ContainmentHost.swift": digest(host)}, "outputSHA256": digest(output),
         "signed": False, "launched": False}
pathlib.Path(manifest).write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
PY

printf '%s\n' "Unsigned attested build written inside workspace; do not run before entitlement review and canary acceptance."
