"""One bounded JSON request on stdin; registered actions only."""
import json
import sys
from .runtime import ActionError, MAX_REQUEST_BYTES, decode, dispatch, registry, resolve


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else 'catalog'
    if command == 'catalog':
        result = registry()
    elif command == 'resolve' and len(sys.argv) == 3:
        result = resolve(sys.argv[2])
    elif command == 'worker':
        try:
            envelope = decode(sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1))
            if type(envelope) is not dict or set(envelope) != {'request', 'output_directory'}:
                raise ActionError('ACTION_WORKER_ENVELOPE_INVALID')
            result = dispatch(envelope['request'], output_directory=envelope['output_directory'])
        except (ActionError, ValueError, TypeError):
            result = {'schema_version': 1, 'status': 'failure', 'data': None, 'execution_ref': None,
                      'error': {'code': 'ACTION_WORKER_INPUT_INVALID', 'effect_state': 'not_started', 'retryable': False}}
    else:
        raise SystemExit('Unknown registered action command')
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
