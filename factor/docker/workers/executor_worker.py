"""Container executor entrypoint; generated-code execution remains fail-closed."""
import argparse
import json

IDENTITY = {"schema_version": 1, "role": "executor", "status": "blocked",
            "qlib_revision": "2fb9380b342556ddb50a4b24e4fe8655d548b2b8",
            "code": "EXECUTOR_ADAPTER_UNIMPLEMENTED"}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("health", "execute"))
    parser.add_argument("--request"); parser.add_argument("--bundle")
    parser.add_argument("--dataset"); parser.add_argument("--output")
    args = parser.parse_args()
    if args.command == "health":
        print(json.dumps({**IDENTITY, "status": "source-only"}, sort_keys=True)); return 0
    print(json.dumps(IDENTITY, sort_keys=True)); return 2

if __name__ == "__main__":
    raise SystemExit(main())
