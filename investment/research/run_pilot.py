"""Foreground application-controlled pilot with the existing Codex adapter.

Model reasoning returns structured proposals; application code dispatches the
registered actions and owns publication. No production sender or broker path.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from shared.job_runtime.model import run_codex
from shared.job_runtime.service import atomic
from shared.research_sources.artifacts import ROOT, SOURCE_STATE, SourceError, private_path, read, require, save, digest
from shared.actions.runtime import decode
from .execution import run
from .report import export_run, render


def configuration(pilot=None, path=None):
    """Load the reviewed JSON recipe; the domain finalizer owns meaning."""
    from .execution import CONFIG_SCHEMA, _validate
    selected = Path(path or ROOT / 'investment/research/examples/earnings-query.pipeline.json').resolve()
    require(selected.is_relative_to(ROOT), 'PILOT_CONFIG_OUTSIDE_WORKSPACE')
    value = decode(selected.read_bytes())
    _validate(CONFIG_SCHEMA, value, 'PIPELINE_CONFIG_INVALID')
    return value


def execute(output_directory, *, source_ref=None, model_callback=None, checkpoint_ref=None, pause_after_phase=None, pipeline_config=None, audit_directory=None):
    from .pilot import prepare, Pilot
    directory = private_path(output_directory, create=True)
    from .audit import Audit
    diagnostics = []
    def observe(operation, callback):
        try:
            return callback()
        except Exception as error:
            # Optional telemetry must not alter domain completion or replay.
            diagnostics.append({'operation': operation, 'code': 'OBSERVABILITY_UNAVAILABLE',
                                'error_type': type(error).__name__})
            return None
    audit = observe('audit.open', lambda: Audit(audit_directory))
    # The reviewed fixture defines the fact/period/precision before acquisition.
    fixture = ROOT / 'investment/research/examples/nvda-revenue-pilot.json'
    if checkpoint_ref is not None:
        require(source_ref is None, 'PILOT_RESUME_SOURCE_OVERRIDE_FORBIDDEN')
        checkpoint = read(checkpoint_ref)
        require(checkpoint.get('kind') == 'ordered_pipeline_checkpoint', 'PILOT_CHECKPOINT_INVALID')
        pilot = Pilot(directory, read(checkpoint['report']['input_manifest']['request_ref']))
        execution_id = checkpoint['report']['run_id']
        configured = configuration(path=pipeline_config) if pipeline_config else read(checkpoint['report']['input_manifest']['config_ref'])
        if audit:
            observe('audit.lookup', lambda: audit.lookup(execution_id))
    else:
        execution_id = str(uuid.uuid4())
        configured = configuration(path=pipeline_config)
        if audit:
            observe('audit.start', lambda: audit.start(execution_id, output_directory=directory, config_ref=save(directory, configured),
                    query='What revenue did NVIDIA report for Q1 FY2025, and do its headline and GAAP table reconcile?'))
        try:
            pilot = prepare(fixture, directory, source_ref=source_ref)
        except Exception as error:
            code = str(error) if isinstance(error, SourceError) and str(error).replace('_', '').isalnum() else 'PILOT_PREPARATION_FAILED'
            if audit:
                observe('audit.failure', lambda: audit.failure(execution_id, code))
            raise
    model_receipts = []
    if checkpoint_ref is not None:
        journal = directory / '.pilot-host' / checkpoint['report']['run_id'] / 'model-receipts.json'
        if journal.exists():
            saved = decode(journal.read_bytes())
            require(saved['request_sha256'] == digest(pilot.request), 'PILOT_MODEL_JOURNAL_INPUT_CHANGED')
            model_receipts = saved['refs']
            for ref in model_receipts:
                read(ref)
    if model_callback is None:
        config = decode((ROOT / '.job-runtime/config/runtime.json').read_bytes())
        profile = config['model_profiles']['default']
        session_root = ROOT / '.job-runtime/runs' / ('evidence-pilot-' + uuid.uuid4().hex)
        def model_callback(prompt, schema):
            context = decode(prompt)
            remaining = min(float(context['remaining_seconds']), float(profile['timeout_seconds']))
            require(remaining > 1, 'PILOT_MODEL_DEADLINE')
            result = run_codex(dict(profile, timeout_seconds=remaining), prompt, ROOT,
                               session_root / str(len(model_receipts)), context={'response_schema': schema})
            ref = save(directory, result)
            model_receipts.append(ref)
            journal_directory = private_path(directory / '.pilot-host' / context['run_id'], create=True)
            atomic(journal_directory / 'model-receipts.json',
                   {'request_sha256': digest(pilot.request), 'refs': model_receipts})
            require(result['status'] == 'succeeded', result['code'])
            response = ROOT / result['receipt']['response_path']
            require(response.is_file(), 'PILOT_MODEL_RESPONSE_MISSING')
            return decode(response.read_bytes())
    result = run(configured, pilot.request, output_directory=directory,
                 model_callback=model_callback, critical_guard=pilot.critical_guard, finalizer=pilot.finalizer,
                 checkpoint_ref=checkpoint_ref, pause_after_phase=pause_after_phase,
                 release_directory=SOURCE_STATE / 'action-releases', execution_id=execution_id)
    result['model_execution_refs'] = model_receipts
    result['completion_scope'] = 'evidence_resolution_pilot'
    result['semantic_scope'] = 'reported same-release extraction/rounding; no full-company conclusion or alpha claim'
    result['model_usage_observed'] = [read(x).get('receipt', {}).get('usage') for x in model_receipts]
    result['finished_at'] = datetime.now(timezone.utc).isoformat()
    result['observability_diagnostics'] = list(diagnostics)
    # Rebind the complete report, then render its read-only projection.
    result.pop('report_ref', None)
    report_ref = save(directory, result)
    view_ref = observe('replay.export', lambda: export_run(report_ref, output_directory=directory))
    html_ref = observe('replay.render', lambda: render(view_ref, output_directory=directory)) if view_ref else None
    result_pointer = {'status': result['status'], 'reason': result.get('reason'), 'report_ref': report_ref,
            'view_ref': view_ref, 'html_ref': html_ref, 'request_ref': save(directory, pilot.request),
            'checkpoint_ref': result.get('checkpoint_ref')}
    audit_ref = observe('audit.record', lambda: audit.record(execution_id, result_pointer)) if audit else None
    return {**result_pointer, 'execution_id': execution_id, 'audit_ref': audit_ref,
            'observability_diagnostics': diagnostics}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', required=True)
    p.add_argument('--source-ref', help='Path to a JSON source-reference artifact for explicit cache reuse')
    p.add_argument('--pipeline-config', help='Workspace-local ordered phase JSON recipe')
    p.add_argument('--resume', help='JSON artifact-reference file for the latest safe accepted-phase checkpoint')
    p.add_argument('--pause-after', help='Stop at an accepted phase boundary without resetting budgets')
    args = p.parse_args()
    source = decode(Path(args.source_ref).read_bytes()) if args.source_ref else None
    checkpoint = decode(Path(args.resume).read_bytes()) if args.resume else None
    result = execute(args.out, source_ref=source, checkpoint_ref=checkpoint, pause_after_phase=args.pause_after, pipeline_config=args.pipeline_config)
    print(json.dumps(result))
    if result['status'] not in ('completed', 'paused'):
        raise SystemExit(2)


if __name__ == '__main__':
    main()
