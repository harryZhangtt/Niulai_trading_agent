"""Execution-ID lookup over immutable receipts; no second research database.

The latest pointer is atomically replaced under an execution-scoped lock. A
read-only lookup can expose the current runner checkpoint while work is active.
This is an integrity/debugging log, not a signed or adversary-proof audit ledger.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import uuid

from shared.job_runtime.service import atomic
from shared.research_sources.artifacts import INVESTMENT_STATE, private_path, read, require, save


class Audit:
    def __init__(self, directory=None):
        self.directory = private_path(directory or INVESTMENT_STATE / 'executions', create=True)

    def _folder(self, execution_id, create=False):
        try:
            valid = str(uuid.UUID(execution_id)) == execution_id
        except (ValueError, TypeError, AttributeError):
            valid = False
        require(valid, 'AUDIT_EXECUTION_ID_INVALID')
        return private_path(self.directory / execution_id, create=create)

    def _write(self, execution_id, change, *, initial=None, expected_ref=None):
        folder = self._folder(execution_id, create=True)
        fd = os.open(folder / 'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('AUDIT_BUSY') from None
            head = folder / 'latest.json'
            require(not head.is_symlink(), 'AUDIT_HEAD_UNSAFE')
            previous_ref = json.loads(head.read_bytes()) if head.exists() else None
            if expected_ref is not None:
                require(previous_ref == expected_ref, 'AUDIT_CONCURRENT_UPDATE')
            previous = read(previous_ref) if previous_ref else None
            if initial is not None:
                require(previous is None, 'AUDIT_EXECUTION_EXISTS')
                state = initial
            else:
                require(previous is not None, 'AUDIT_EXECUTION_UNKNOWN')
                state = dict(previous)
            state.update(change)
            state.update(schema_version=1, execution_id=execution_id,
                         sequence=(previous['sequence'] if previous else 0) + 1,
                         previous_ref=previous_ref, updated_at=datetime.now(timezone.utc).isoformat())
            ref = save(folder, state)
            atomic(head, ref)
            return ref
        finally:
            os.close(fd)

    def start(self, execution_id, *, output_directory, config_ref, query):
        config = read(config_ref)
        out = private_path(output_directory, create=True)
        return self._write(execution_id, {}, initial={
            'status': 'preparing', 'pipeline_id': config['pipeline_id'],
            'pipeline_version': config['pipeline_version'], 'config_ref': config_ref,
            'query': query, 'output_directory': str(out), 'result': None})

    def record(self, execution_id, result):
        report = read(result['report_ref'])
        current = self.lookup(execution_id, live=False)
        require(report.get('run_id') == execution_id, 'AUDIT_REPORT_ID_MISMATCH')
        require(report['input_manifest']['config_ref'] == current['config_ref'], 'AUDIT_CONFIG_CHANGED')
        require(Path(result['report_ref']['path']).parent == Path(current['output_directory']), 'AUDIT_OUTPUT_CHANGED')
        # A failed resume must not replace the authoritative latest checkpoint.
        checkpoint_ref = result.get('checkpoint_ref')
        if checkpoint_ref:
            checkpoint = read(checkpoint_ref)
            head = Path(current['output_directory']) / '.pipeline' / execution_id / 'head.json'
            require(json.loads(head.read_bytes())['checkpoint_ref'] == checkpoint_ref, 'AUDIT_STALE_CHECKPOINT')
            require(checkpoint['report']['run_id'] == execution_id, 'AUDIT_CHECKPOINT_ID_MISMATCH')
        return self._write(execution_id, {'status': result['status'], 'result': result}, expected_ref=current['audit_ref'])

    def failure(self, execution_id, code):
        # Only stable codes, never raw provider exception bodies or credentials.
        require(isinstance(code, str) and code.replace('_', '').isalnum() and len(code) <= 100, 'AUDIT_ERROR_CODE_INVALID')
        return self._write(execution_id, {'status': 'blocked', 'reason': code})

    def lookup(self, execution_id, *, live=True):
        folder = self._folder(execution_id)
        head = folder / 'latest.json'
        require(head.is_file() and not head.is_symlink(), 'AUDIT_EXECUTION_UNKNOWN')
        ref = json.loads(head.read_bytes()); state = read(ref)
        require(state.get('execution_id') == execution_id, 'AUDIT_ID_MISMATCH')
        result = {**state, 'audit_ref': ref}
        if live:
            runner_head = Path(state['output_directory']) / '.pipeline' / execution_id / 'head.json'
            if runner_head.exists():
                require(not runner_head.is_symlink(), 'AUDIT_HEAD_UNSAFE')
                checkpoint_ref = json.loads(runner_head.read_bytes())['checkpoint_ref']
                checkpoint = read(checkpoint_ref)
                require(checkpoint['report']['run_id'] == execution_id
                        and checkpoint['report']['input_manifest']['config_ref'] == state['config_ref'], 'AUDIT_LIVE_BINDING_MISMATCH')
                result['live_checkpoint_ref'] = checkpoint_ref
                result['live_status'] = checkpoint['report']['status']
                result['pending'] = checkpoint['pending']
        return result

    def list(self, *, limit=20):
        require(type(limit) is int and 1 <= limit <= 100, 'AUDIT_LIMIT_INVALID')
        rows = []
        for folder in self.directory.iterdir():
            if folder.is_dir() and not folder.is_symlink() and (folder / 'latest.json').is_file():
                state = self.lookup(folder.name, live=False)
                rows.append({key: state[key] for key in ('execution_id', 'pipeline_id', 'pipeline_version', 'status', 'updated_at', 'query', 'audit_ref')})
        return sorted(rows, key=lambda row: row['updated_at'], reverse=True)[:limit]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('list', 'show'))
    parser.add_argument('--execution-id')
    args = parser.parse_args()
    audit = Audit()
    print(json.dumps(audit.list() if args.command == 'list' else audit.lookup(args.execution_id), indent=2))


if __name__ == '__main__':
    main()
