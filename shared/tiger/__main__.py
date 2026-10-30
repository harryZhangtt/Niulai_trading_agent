"""Hidden-input launcher for the isolated shared MCP query portal."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess

from .bridge import hidden_input, load_policy, private_directory, require, safe_failure, validate_site
from .queries import TOOLS, validate_query

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=ROOT / ".niulai-state/config/tiger.json")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tool", choices=TOOLS, default="snapshot")
    parser.add_argument("--args", default="{}", help="Public query arguments only; no credentials or account IDs")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        query = validate_query({"tool": args.tool, "arguments": json.loads(args.args)}, require)
        load_policy(args.policy, ROOT)
        out = Path(os.path.abspath(args.out))
        require(out.is_relative_to(ROOT / ".niulai-state")
                and out.resolve().is_relative_to(ROOT / ".niulai-state"), "OUTPUT_NOT_PRIVATE_STATE")
        node = shutil.which("node")
        require(node is not None, "TIGER_PORTAL_SETUP_REQUIRED")
        tmp = private_directory(ROOT / ".niulai-state/tmp", ROOT)
        node_cache = private_directory(tmp / "node-compile-cache", ROOT)
        site = hidden_input()
        validate_site(site, load_policy(args.policy, ROOT))
        context = {"site": site, "policy": str(args.policy.resolve()), "out": str(out), "query": query}
        # A pipe, never argv/env/temp files. No child diagnostics are forwarded.
        child = subprocess.Popen([node, str(ROOT / "shared/market_data_mcp/tiger-query.mjs")],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 text=True, cwd=ROOT, start_new_session=True,
                                 env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
                                          TMPDIR=str(tmp), NODE_COMPILE_CACHE=str(node_cache)))
        try:
            stdout, _ = child.communicate(json.dumps(context), timeout=125)
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
        result = json.loads(stdout)
        print(json.dumps(result))
        return 0 if child.returncode == 0 and result.get("status") == "queried" else 2
    except Exception as exc:
        print(json.dumps(safe_failure(exc)))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
