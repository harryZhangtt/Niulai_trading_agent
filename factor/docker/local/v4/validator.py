"""Read-only CLI for the selected-disabled Colima v4 preflight contract."""
import argparse
import json
from pathlib import Path

from . import launcher


def validate_bundle(workspace: Path = launcher.EXPECTED_WORKSPACE) -> dict[str, str]:
    profile = launcher.validate_profile(launcher.load_json(launcher.PROFILE_PATH), workspace)
    command = launcher.validate_command(launcher.load_json(launcher.COMMAND_PATH), workspace)
    return {"runtime-profile-v4.json": launcher.digest(profile),
            "activation-command-v4.json": launcher.digest(command)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate disabled Colima v4 preflight")
    parser.add_argument("--workspace", type=Path, default=launcher.EXPECTED_WORKSPACE)
    args = parser.parse_args(argv)
    try:
        hashes = validate_bundle(args.workspace)
    except launcher.V4ContractError as exc:
        print(f"INVALID {exc}")
        return 2
    print(json.dumps({"valid": True, "status": "selected-disabled", "runnable": False,
                      "apply_allowed": False, "sha256": hashes}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
