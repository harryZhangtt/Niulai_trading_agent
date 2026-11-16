"""Standard-library-only health worker; scientific execution is unavailable."""
import argparse
import json

IDENTITY = {
    "schema_version": 1,
    "kind": "factor_local_health_worker",
    "role": "executor",
    "status": "health-only",
    "code": "SCIENTIFIC_EXECUTION_UNAVAILABLE",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("health", "execute"))
    args = parser.parse_args()
    print(json.dumps(IDENTITY, sort_keys=True, separators=(",", ":")))
    return 0 if args.command == "health" else 2


if __name__ == "__main__":
    raise SystemExit(main())
