"""Container controller entrypoint; real RD-Agent phases remain fail-closed."""
import argparse
import json

IDENTITY = {"schema_version": 1, "role": "controller", "status": "blocked",
            "rdagent_revision": "484776c211e4fbbeef03e0ec00d6bbee7362a4f4",
            "code": "CONTROLLER_ADAPTER_UNIMPLEMENTED"}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("health", "prepare", "feedback"))
    parser.add_argument("--request"); parser.add_argument("--output")
    args = parser.parse_args()
    if args.command == "health":
        print(json.dumps({**IDENTITY, "status": "source-only"}, sort_keys=True)); return 0
    print(json.dumps(IDENTITY, sort_keys=True)); return 2

if __name__ == "__main__":
    raise SystemExit(main())
