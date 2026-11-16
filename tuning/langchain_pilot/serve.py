"""Run the stock dev server with all pilot state confined to the workspace."""
import argparse
import os
import sys
import socket
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=2024)
    parser.add_argument("--allow-blocking", action="store_true")
    parser.add_argument("--atomic", action="store_true", help="Isolated public-fixture Studio graphs")
    parser.add_argument("--cloud-tracing", action="store_true", help="Opt in to admitted synthetic capability traces")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        raise SystemExit("unprivileged port required")
    private = ROOT / ".langchain-pilot"
    if args.cloud_tracing and not args.atomic:
        raise SystemExit("cloud tracing requires the closed atomic fixture entry point")
    if args.atomic:
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', args.port))
            except OSError:
                raise SystemExit('ATOMIC_PORT_OCCUPIED: no automatic port fallback') from None
    server_state = "runtime/atomic-server" if args.atomic else "runtime/server"
    for name in (server_state, "cache", "tmp"):
        (private / name).mkdir(parents=True, exist_ok=True, mode=0o700)
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1",
           "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false",
           "XDG_CACHE_HOME": str(private / "cache"), "TMPDIR": str(private / "tmp"),
           "ATOMIC_CLOUD_TRACING": "1" if args.cloud_tracing else "0",
           "LANGGRAPH_CLI_NO_ANALYTICS": "1"}
    command = [str(private / ".venv/bin/langgraph"), "dev", "--no-browser", "--no-reload",
               "--host", "127.0.0.1", "--port", str(args.port), "--n-jobs-per-worker", "1",
               "--server-log-level", "WARNING", "--config", str(Path(__file__).with_name(
                   "atomic-langgraph.json" if args.atomic else "langgraph.json"))]
    if args.allow_blocking:
        command.append("--allow-blocking")
    if args.atomic:
        command = [str(private / '.venv/bin/python'), '-B', '-m',
                   'tuning.langchain_pilot.strict_cli', *command[1:]]
    os.chdir(private / server_state)
    os.execve(command[0], command, env)


if __name__ == "__main__":
    main()
