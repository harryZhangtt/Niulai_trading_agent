"""Read-only validation for the selected-disabled v5 activation contract."""
import argparse
import json
from pathlib import Path
from . import launcher


def validate_bundle(workspace: Path = launcher.EXPECTED_WORKSPACE):
    profile = launcher.validate_profile(launcher.load_json(launcher.PROFILE_PATH), workspace)
    return {"runtime-profile-v5.json": launcher.digest(profile)}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=launcher.EXPECTED_WORKSPACE)
    args = parser.parse_args(argv)
    try:
        hashes = validate_bundle(args.workspace)
    except (launcher.V5ContractError, OSError) as exc:
        print(f"INVALID {type(exc).__name__}")
        return 2
    print(json.dumps({"valid": True, "status": "selected-disabled", "runnable": False,
                      "apply_allowed": False, "sha256": hashes}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
