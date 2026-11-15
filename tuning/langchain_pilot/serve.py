"""Run the stock dev server with all pilot state confined to the workspace."""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=2024)
    parser.add_argument("--allow-blocking", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        raise SystemExit("unprivileged port required")
    private = ROOT / ".langchain-pilot"
    for name in ("runtime/server", "cache", "tmp"):
        (private / name).mkdir(parents=True, exist_ok=True, mode=0o700)
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1",
           "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false",
           "XDG_CACHE_HOME": str(private / "cache"), "TMPDIR": str(private / "tmp")}
    command = [str(private / ".venv/bin/langgraph"), "dev", "--no-browser", "--no-reload",
               "--host", "127.0.0.1", "--port", str(args.port), "--n-jobs-per-worker", "1",
               "--server-log-level", "WARNING", "--config", str(Path(__file__).with_name("langgraph.json"))]
    if args.allow_blocking:
        command.append("--allow-blocking")
    os.chdir(private / "runtime/server")
    os.execve(command[0], command, env)


if __name__ == "__main__":
    main()
