"""Pinned local dev CLI adapter: use only the explicitly requested port."""
import importlib.metadata
import sys


def exact_port(host, port):
    if host != '127.0.0.1' or type(port) is not int or not 1024 <= port <= 65535:
        raise SystemExit('ATOMIC_EXPLICIT_LOOPBACK_PORT_REQUIRED')
    # A race after the launcher's probe must fail at bind, never select a new port.
    return port


def main():
    if sys.argv[1:2] != ['dev'] or importlib.metadata.version('langgraph-api') != '0.18.0':
        raise SystemExit('ATOMIC_PINNED_DEV_RUNTIME_REQUIRED')
    import langgraph_api.cli
    langgraph_api.cli._resolve_port = exact_port
    from langgraph_cli.cli import cli
    cli()


if __name__ == '__main__': main()
