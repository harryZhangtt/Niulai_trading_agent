"""Command-line interface for the deterministic factor experiment guard."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import stat

if __package__:
    from . import guard
else:
    module_path = Path(__file__).resolve().with_name("guard.py")
    spec = importlib.util.spec_from_file_location("factor_mining_guard", module_path)
    if spec is None or spec.loader is None:
        raise SystemExit("FACTOR_GUARD_IMPORT_FAILED")
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)


def read_json(path):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise guard.GuardError("FACTOR_INPUT_INVALID") from None
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or not 0 < details.st_size <= guard.MAX_PROTOCOL_BYTES:
            raise guard.GuardError("FACTOR_INPUT_INVALID")
        raw = b""
        while len(raw) < details.st_size:
            chunk = os.read(descriptor, min(65536, details.st_size - len(raw)))
            if not chunk:
                raise guard.GuardError("FACTOR_INPUT_INVALID")
            raw += chunk
    finally:
        os.close(descriptor)
    value = guard.loads_strict(raw)
    if not isinstance(value, (dict, list)):
        raise guard.GuardError("FACTOR_INPUT_INVALID")
    return value


class StableParser(argparse.ArgumentParser):
    def error(self, message):
        raise guard.GuardError("FACTOR_ARGUMENTS_INVALID")


def parser():
    result = StableParser(description=__doc__)
    result.add_argument("--state", required=True)
    commands = result.add_subparsers(dest="command", required=True)
    seal = commands.add_parser("seal"); seal.add_argument("--protocol", required=True)
    inspect = commands.add_parser("inspect"); inspect.add_argument("--protocol-sha256", required=True)
    begin = commands.add_parser("begin"); begin.add_argument("--protocol-sha256", required=True); begin.add_argument("--variant-id", required=True); begin.add_argument("--configuration", required=True); begin.add_argument("--split", action="append", required=True)
    finish = commands.add_parser("finish"); finish.add_argument("--protocol-sha256", required=True); finish.add_argument("--variant-id", required=True); finish.add_argument("--result", required=True); finish.add_argument("--evidence-sha256", required=True)
    complete = commands.add_parser("complete"); complete.add_argument("--protocol-sha256", required=True); complete.add_argument("--evidence-sha256", required=True)
    quarantine = commands.add_parser("quarantine"); quarantine.add_argument("--protocol-sha256", required=True); quarantine.add_argument("--observations", required=True); quarantine.add_argument("--evidence-sha256", required=True)
    promote = commands.add_parser("promote"); promote.add_argument("--protocol-sha256", required=True); promote.add_argument("--gate-report", required=True); promote.add_argument("--independent-check-sha256", required=True)
    reject = commands.add_parser("reject"); reject.add_argument("--protocol-sha256", required=True); reject.add_argument("--evidence-sha256", required=True); reject.add_argument("--reason", required=True)
    authorize = commands.add_parser("authorize"); authorize.add_argument("--protocol-sha256", action="append", required=True); authorize.add_argument("--purpose", required=True); authorize.add_argument("--evidence-sha256", required=True)
    return result


def run(args):
    if args.command == "seal": return guard.seal(args.protocol, args.state)
    if args.command == "inspect": return guard.inspect_state(args.state, args.protocol_sha256)
    if args.command == "begin": return guard.begin_attempt(args.state, args.protocol_sha256, args.variant_id, read_json(args.configuration), args.split)
    if args.command == "finish": return guard.finish_attempt(args.state, args.protocol_sha256, args.variant_id, args.result, args.evidence_sha256)
    if args.command == "complete": return guard.complete_testing(args.state, args.protocol_sha256, args.evidence_sha256)
    if args.command == "quarantine": return guard.quarantine(args.state, args.protocol_sha256, read_json(args.observations), args.evidence_sha256)
    if args.command == "promote": return guard.promote(args.state, args.protocol_sha256, read_json(args.gate_report), args.independent_check_sha256)
    if args.command == "reject": return guard.reject(args.state, args.protocol_sha256, args.evidence_sha256, args.reason)
    if args.command == "authorize": return guard.authorize_use(args.state, args.protocol_sha256, args.purpose, args.evidence_sha256)
    raise guard.GuardError("FACTOR_COMMAND_INVALID")


def main():
    try:
        args = parser().parse_args()
        output = run(args)
    except Exception as error:
        code = str(error) if isinstance(error, guard.GuardError) else "FACTOR_GUARD_FAILED"
        print(json.dumps({"status": "failed", "code": code}))
        return 2
    print(json.dumps({"status": "ok", "result": output}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
