"""Project-local candidate CLI; does not change browser or Codex defaults."""
import argparse
import json
from pathlib import Path
from shared.research_sources.artifacts import SourceError
from .policy import DEFAULT_CONFIG, Session, load_config
from .egolite import doctor, read


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('doctor', 'plan', 'read'))
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--url')
    parser.add_argument('--operation', choices=('discover', 'read'), default='read')
    parser.add_argument('--interactive', action='store_true')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.command == 'doctor':
            result = doctor(config)
        else:
            session = Session(config)
            result = session.plan(operation=args.operation, url=args.url, interactive=args.interactive)
            if args.command == 'read':
                if result['route'] == 'egolite' and args.out:
                    result = read(config, result, output_directory=args.out)
                else:
                    result = {'status': 'blocked', 'code': 'HOST_TOOL_OR_CONFIGURATION_REQUIRED', 'decision': result}
        print(json.dumps(result, allow_nan=False))
        return 2 if result.get('status') == 'blocked' else 0
    except Exception as error:
        print(json.dumps({'status': 'blocked', 'code': str(error) if isinstance(error, SourceError) else 'WEB_REQUEST_FAILED'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
