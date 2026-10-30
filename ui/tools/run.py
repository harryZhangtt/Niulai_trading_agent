"""Invoke pinned UI CLIs with workspace-owned caches and bounded execution."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import signal
import json

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "ui"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("tool", choices=["shadcn", "playwright-cli", "playwright"])
    parser.add_argument("--project", default="ui/verification")
    args, extra = parser.parse_known_args()
    project = (ROOT / args.project).resolve()
    if not project.is_relative_to(ROOT) or not project.is_dir():
        parser.error("project must be an existing directory inside this workspace")
    base = UI / "runtime"
    paths = {"TMPDIR": base / "tmp", "XDG_CACHE_HOME": base / "cache",
             "XDG_CONFIG_HOME": base / "config", "NPM_CONFIG_CACHE": base / "npm-cache",
             "NPM_CONFIG_LOGS_DIR": base / "npm-logs",
             "PLAYWRIGHT_BROWSERS_PATH": base / "browsers",
             "PWTEST_DAEMON_SESSION_DIR": base / "daemon",
             "PLAYWRIGHT_MCP_OUTPUT_DIR": base / "browser-output"}
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, **{k: str(v) for k, v in paths.items()},
                       PYTHONDONTWRITEBYTECODE="1", CI="1")
    command = UI / "verification/node_modules/.bin" / args.tool
    if not command.exists():
        parser.error("local dependencies missing; follow docs/deployment/frontend.md")
    # Browser session artifacts are never created in a target application's source.
    if args.tool == "playwright-cli":
        project = base / "browser-session"
        project.mkdir(parents=True, exist_ok=True)
        if "open" in extra and not any(x.startswith("--config") for x in extra):
            # CLI's pinned alpha engine and the stable test runner resolve
            # different browser revisions. Use the tested full browser explicitly.
            executable = subprocess.check_output(
                ["node", "-e", "process.stdout.write(require('@playwright/test').chromium.executablePath())"],
                cwd=UI / "verification", env=environment, text=True, timeout=10)
            config = base / "playwright-cli.json"
            config.write_text(json.dumps({"browser": {"browserName": "chromium", "launchOptions": {
                "executablePath": executable, "headless": True}}}) + "\n")
            extra += ["--config=" + str(config), "--idle-timeout=30000"]
    process = subprocess.Popen([str(command), *extra], cwd=project, env=environment,
                               start_new_session=True)
    try:
        return process.wait(timeout=180)
    except subprocess.TimeoutExpired:
        # Stop this invocation's group, including its test webserver/children.
        # Successful interactive browser sessions have an explicit close lifecycle.
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=2)
        print("UI_TOOL_TIMEOUT", file=sys.stderr)
        return 124


if __name__ == "__main__":
    raise SystemExit(main())

