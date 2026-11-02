"""Private read-only replay of hash-verified execution receipts.

Allowlisted projection: no prompts, raw arguments or provider payloads in HTML.
Tool Strategy's case replay was read for recorded-state/unknown-state and per-step
disclosure patterns. No code or dependency was copied from that repository.
"""
from datetime import datetime, timezone
import html
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit

from shared.research_sources.artifacts import SourceError, read, save, require


def _text(value, limit=3000):
    if not isinstance(value, (str, int, float, bool)):
        return None
    value = str(value)[:limit]
    value = re.sub(r'(?i)\bBearer\s+\S+', 'Bearer [redacted]', value)
    value = re.sub(r'(?i)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|authorization|secret)\s*[:=]\s*[^\s,;]+', '[redacted]', value)
    return re.sub(r'\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{16,})\b', '[redacted]', value)


def _ref(value):
    if (isinstance(value, dict) and set(value) == {'path', 'sha256'} and isinstance(value['path'], str)
            and isinstance(value['sha256'], str) and re.fullmatch(r'[a-f0-9]{64}', value['sha256'])):
        return {'file': Path(value['path']).name, 'sha256': value['sha256']}
    return None


def _url(value):
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
            return None
        # Query credentials and tracking parameters never enter the projection.
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))
    except (ValueError, TypeError, AttributeError):
        return None


def _elapsed(start, end):
    try:
        first, last = (datetime.fromisoformat(x.replace('Z', '+00:00')) for x in (start, end))
        if first.tzinfo is None or last.tzinfo is None:
            return None
        duration = (last - first).total_seconds()
        return round(duration * 1000, 3) if duration >= 0 else None
    except (ValueError, TypeError, AttributeError):
        return None


def export_run(report_ref, *, output_directory):
    report = read(report_ref)
    require(report.get('schema_version') == 1 and isinstance(report.get('phases'), dict), 'RUN_REPORT_INVALID')
    warnings = []

    def load(ref, label):
        if ref is None:
            return {}
        try:
            value = read(ref)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (SourceError, OSError, ValueError, TypeError):
            warnings.append(label + ' receipt could not be verified; its contents are not displayed.')
            return {}

    manifest = report.get('input_manifest') or {}
    config = load(manifest.get('config_ref'), 'Configuration')
    request = load(manifest.get('request_ref'), 'Request')
    configured = {p['id']: p for p in config.get('phases', []) if isinstance(p, dict) and isinstance(p.get('id'), str)}
    phase_ids = list(configured) + [p for p in report['phases'] if p not in configured]
    events, phase_events, call_phases = [], {}, {}
    current_phase = None
    for event in report.get('events', []):
        if not isinstance(event, dict):
            continue
        if event.get('event_type') == 'phase_started':
            current_phase = event.get('phase_id')
        phase_id = event.get('phase_id', current_phase)
        if event.get('call_id'):
            call_phases[event['call_id']] = phase_id
        events.append({k: _text(event.get(k)) for k in ('event_type', 'sequence', 'occurred_at', 'phase_id', 'call_id', 'action', 'code')})
        if phase_id:
            phase_events.setdefault(phase_id, []).append(event)

    def action_row(record, phase_id):
        execution = load(record.get('execution_ref'), 'Action execution')
        outcome = load(record.get('outcome_ref'), 'Action outcome')
        error = execution.get('error') or outcome.get('error') or {}
        return {'phase_id': _text(phase_id), 'call_id': _text(record.get('call_id')),
                'action': _text(record.get('action') or execution.get('action_id')),
                'status': _text(execution.get('status') or outcome.get('status')),
                'started_at': _text(execution.get('started_at')), 'finished_at': _text(execution.get('finished_at')),
                'duration_ms': execution.get('duration_ms') if isinstance(execution.get('duration_ms'), (int, float)) else _elapsed(execution.get('started_at'), execution.get('finished_at')),
                'release_sha256': _text(execution.get('release_sha256')),
                'error_code': _text(error.get('code')) if isinstance(error, dict) else None,
                'execution_ref': _ref(record.get('execution_ref')), 'record_ref': _ref(record.get('record_ref'))}

    actions = [action_row(record, call_phases.get(record.get('call_id'))) for record in report.get('action_records', []) if isinstance(record, dict)]
    phases = []
    for phase_id in phase_ids:
        phase, outcome = configured.get(phase_id, {}), report['phases'].get(phase_id, {})
        data = outcome.get('data') if isinstance(outcome.get('data'), dict) else {}
        observed = phase_events.get(phase_id, [])
        start = next((e.get('occurred_at') for e in observed if e.get('event_type') == 'phase_started'), None)
        end = next((e.get('occurred_at') for e in reversed(observed) if e.get('event_type') == 'phase_accepted'), None)
        state = 'accepted' if outcome else ('incomplete' if start else 'not_run')
        phases.append({'phase_id': _text(phase_id), 'objective': _text(phase.get('objective')),
                       'mode': _text(phase.get('mode')), 'gate': _text(phase.get('gate')),
                       'status': _text(outcome.get('status')) or state, 'completion': state,
                       'started_at': _text(start), 'finished_at': _text(end), 'duration_ms': _elapsed(start, end),
                       'configured_actions': [_text(x) for x in ([phase['action']] if phase.get('action') else phase.get('permitted_actions', []))],
                       'result_status': _text(data.get('status')), 'conclusion': _text(data.get('conclusion')),
                       'explanation': _text(data.get('explanation')),
                       'unresolved_gaps': [_text(x, 500) for x in data.get('unresolved_gaps', [])[:12]] if isinstance(data.get('unresolved_gaps'), list) else [],
                       'phase_ref': _ref(report.get('phase_refs', {}).get(phase_id)), 'execution_ref': _ref(outcome.get('execution_ref'))})
    acquisition = request.get('acquisition') or {}
    if acquisition.get('execution_ref'):
        acquire_request = load(acquisition.get('request_ref'), 'Acquisition request')
        actions.insert(0, action_row({**acquisition, 'call_id': 'acquisition', 'action': acquire_request.get('action')}, 'acquisition'))
    source = load(request.get('source_ref'), 'Evidence source')
    evidence = []
    if request.get('source_ref'):
        evidence.append({'source_ref': _ref(request.get('source_ref')), 'provider': _text(source.get('provider')),
                         'source_url': _url(source.get('source_url')), 'access_level': _text(source.get('access_level')),
                         'acquisition': _text(acquisition.get('mode')), 'retrieved_at': _text(source.get('retrieved_at')),
                         'available_at': _text(source.get('available_at')), 'availability_basis': _text(source.get('availability_basis')),
                         'raw_ref': _ref(source.get('raw'))})
    usages = [{k: u.get(k) for k in ('input_tokens', 'cached_input_tokens', 'output_tokens') if isinstance(u, dict) and isinstance(u.get(k), int)} or None for u in report.get('model_usage_observed', [])]
    view = {'schema_version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(),
            'run_id': _text(report.get('run_id')), 'pipeline_id': _text(report.get('pipeline_id')),
            'pipeline_version': _text(report.get('pipeline_version')), 'execution_status': _text(report.get('status')),
            'reason': _text(report.get('reason')), 'completion_scope': _text(report.get('completion_scope')),
            'semantic_scope': _text(report.get('semantic_scope')), 'runtime_acceptance': 'unverified',
            'started_at': _text(report.get('started_at')), 'finished_at': _text(report.get('finished_at')),
            'duration_ms': _elapsed(report.get('started_at'), report.get('finished_at')),
            'input_manifest': {k: _ref(manifest.get(k)) for k in ('config_ref', 'request_ref')},
            'phases': phases, 'actions': actions, 'evidence': evidence,
            'counts': {k: v for k, v in report.get('counts', {}).items() if k in ('actions', 'model_turns') and isinstance(v, int)},
            'events': events, 'final_ref': _ref(report.get('final_ref')), 'warnings': warnings,
            'observed_model_usage': usages, 'authoritative_report_ref': _ref(report_ref)}
    return save(output_directory, view)


def render(view_ref, *, output_directory):
    view = read(view_ref)
    require(view.get('schema_version') == 1, 'RUN_VIEW_INVALID')
    esc = lambda value: html.escape(str(value if value is not None else 'Not recorded'), quote=True)

    def fields(items):
        return '<dl class="fields">' + ''.join('<div><dt>' + esc(k) + '</dt><dd>' + esc(v) + '</dd></div>' for k, v in items) + '</dl>'

    def duration(value):
        return ('%.3f s' % (value / 1000)) if isinstance(value, (int, float)) else None

    def badge(status):
        tone = 'good' if status in ('completed', 'accepted', 'success') else 'warn' if status in ('paused', 'not_run', 'unverified') else 'bad' if status in ('blocked', 'failure', 'incomplete') else ''
        return '<span class="badge ' + tone + '">' + esc(str(status).replace('_', ' ') if status is not None else None) + '</span>'

    def refs(items):
        rows = [(label, ref['sha256']) for label, ref in items if isinstance(ref, dict) and ref.get('sha256')]
        return '<details class="receipts"><summary>Receipts</summary>' + fields(rows) + '</details>' if rows else '<p class="muted">Receipt not recorded.</p>'

    phase_html, phase_nav = [], []
    for index, item in enumerate(view['phases']):
        anchor = 'phase-' + str(index)
        phase_nav.append('<li><a href="#' + anchor + '">' + esc(item['phase_id']) + '</a>' + badge(item.get('completion')) + '</li>')
        finding, gaps = item.get('conclusion') or item.get('result_status'), item.get('unresolved_gaps') or []
        phase_html.append('<section class="phase" id="' + anchor + '"><div class="section-heading"><h3>' + esc(item['phase_id']) + '</h3>' + badge(item.get('completion')) + '</div><p>' + esc(item.get('objective')) + '</p>' +
            fields([('Mode / gate', ' / '.join(str(x) for x in (item.get('mode') or 'Unknown', item.get('gate') or 'Unknown'))),
                    ('Started (UTC)', item.get('started_at')), ('Wall time', duration(item.get('duration_ms'))),
                    ('Configured scripts', ', '.join(item.get('configured_actions', [])) or 'None recorded'), ('Recorded finding', finding)]) +
            ('<p class="explanation">' + esc(item['explanation']) + '</p>' if item.get('explanation') else '') +
            ('<h4>Unresolved gaps</h4><ul class="gaps">' + ''.join('<li>' + esc(g) + '</li>' for g in gaps) + '</ul>' if gaps else '<p class="muted">No gaps listed in this phase output; this is not an independent completeness check.</p>') +
            refs([('Phase SHA-256', item.get('phase_ref')), ('Execution SHA-256', item.get('execution_ref'))]) + '</section>')
    action_rows = []
    for item in view.get('actions', []):
        action_rows.append('<tr><th scope="row">' + esc(item.get('action')) + '<small>' + esc(item.get('call_id')) + '</small></th><td>' + esc(item.get('phase_id')) + '</td><td>' + badge(item.get('status')) +
            ('<small>' + esc(item['error_code']) + '</small>' if item.get('error_code') else '') + '</td><td class="number">' + esc(duration(item.get('duration_ms'))) + '</td><td><details><summary>Call details</summary>' +
            fields([('Started (UTC)', item.get('started_at')), ('Finished (UTC)', item.get('finished_at')), ('Pinned release SHA-256', item.get('release_sha256'))]) +
            refs([('Execution SHA-256', item.get('execution_ref')), ('Call record SHA-256', item.get('record_ref'))]) + '</details></td></tr>')
    evidence_html = []
    origins = {'registered_action': 'Fetched through a registered action', 'cached_source': 'Reused an explicit cached source', 'injected_getter': 'Injected retrieval (test path)'}
    for source in view.get('evidence', []):
        url = source.get('source_url')
        evidence_html.append('<article class="evidence"><h3>' + esc(source.get('provider')) + '</h3>' +
            ('<p><a href="' + esc(url) + '" rel="noopener noreferrer">' + esc(url) + '</a></p>' if url else '<p>Source URL not recorded or not safe to display.</p>') +
            fields([('Retrieval origin', origins.get(source.get('acquisition'), 'Unknown')), ('Access', source.get('access_level')),
                    ('Retrieved (UTC)', source.get('retrieved_at')), ('Available (UTC)', source.get('available_at')), ('Availability basis', source.get('availability_basis'))]) +
            refs([('Source SHA-256', source.get('source_ref')), ('Original payload SHA-256', source.get('raw_ref'))]) + '</article>')
    timeline = []
    for event in view.get('events', []):
        detail = ' · '.join(str(event[k]) for k in ('phase_id', 'action', 'call_id', 'code') if event.get(k) is not None)
        timeline.append('<li><div><strong>' + esc(event.get('event_type')) + '</strong><time>' + esc(event.get('occurred_at')) + '</time></div><p>' + esc(detail or 'Pipeline event') + '</p></li>')
    counts, usage_items = view.get('counts', {}), []
    for index, usage in enumerate(view.get('observed_model_usage', [])):
        usage_items.append('<li>Model call ' + str(index + 1) + ': ' + (', '.join(esc(k.replace('_', ' ')) + ' ' + esc(v) for k, v in usage.items()) if usage else 'Token usage not recorded') + '</li>')
    warnings = ''.join('<li>' + esc(x) + '</li>' for x in view.get('warnings', []))
    css = Path(__file__).with_name('report.css').read_text()
    content = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; style-src &#39;unsafe-inline&#39;; base-uri &#39;none&#39;; form-action &#39;none&#39;">'
        '<title>Execution replay | ' + esc(view.get('pipeline_id')) + '</title><style>' + css + '</style></head><body><a class="skip" href="#phases">Skip to phases</a><main>'
        '<header><h1>Execution replay</h1><div class="section-heading"><p class="pipeline">' + esc(view.get('pipeline_id')) + ' <span>' + esc(view.get('pipeline_version')) + '</span></p>' + badge(view.get('execution_status')) + '</div>' +
        '<p class="muted">Saved execution record. Expanding a step inspects recorded activity; it does not run scripts again.</p></header>' +
        ('<aside class="notice"><strong>Execution stopped:</strong> ' + esc(view['reason']) + '</aside>' if view.get('reason') else '') +
        ('<aside class="notice"><h2>Incomplete audit data</h2><ul>' + warnings + '</ul></aside>' if warnings else '') +
        fields([('Execution ID', view.get('run_id')), ('Started (UTC)', view.get('started_at')), ('Finished (UTC)', view.get('finished_at')), ('Wall time', duration(view.get('duration_ms'))),
                ('Scope', view.get('completion_scope')), ('Runtime acceptance', view.get('runtime_acceptance'))]) +
        ('<p class="scope">' + esc(view['semantic_scope']) + '</p>' if view.get('semantic_scope') else '') +
        '<section id="phases"><h2>Configured phases</h2><nav aria-label="Phase results"><ol class="phase-nav">' + ''.join(phase_nav) + '</ol></nav>' +
        (''.join(phase_html) or '<p>No phase results were recorded.</p>') + '</section>' +
        '<section><h2>Script calls</h2><p class="muted">Version selectors and pinned release digests identify the code used. Acquisition calls are shown separately from pipeline action counts.</p>' +
        ('<div class="table-wrap" role="region" aria-label="Script calls" tabindex="0"><table><thead><tr><th scope="col">Script / call ID</th><th scope="col">Phase</th><th scope="col">Status</th><th scope="col">Duration</th><th scope="col">Details</th></tr></thead><tbody>' + ''.join(action_rows) + '</tbody></table></div>' if action_rows else '<p>No script execution receipts were recorded.</p>') + '</section>' +
        '<section><h2>Evidence used</h2>' + (''.join(evidence_html) or '<p>No source receipt was recorded. Evidence coverage is unknown.</p>') + '</section>' +
        '<section><h2>Runtime metrics</h2>' + fields([('Pipeline actions', counts.get('actions')), ('Model turns', counts.get('model_turns')), ('Recorded script calls', len(view.get('actions', []))), ('Provider charges', 'Not recorded')]) +
        ('<ul>' + ''.join(usage_items) + '</ul>' if usage_items else '<p>Token usage not recorded.</p>') + '</section>' +
        '<section><details class="timeline"><summary>Attempt timeline (' + str(len(timeline)) + ' recorded events)</summary>' + ('<ol>' + ''.join(timeline) + '</ol>' if timeline else '<p>No events were recorded.</p>') + '</details></section>' +
        '<footer><h2>Audit boundary</h2><p>Script success, evidence support and runtime acceptance are separate. Missing observations remain unknown. This saved view does not establish source truth or investment alpha.</p>' +
        refs([('Authoritative report SHA-256', view.get('authoritative_report_ref')), ('Configuration SHA-256', view.get('input_manifest', {}).get('config_ref')), ('Request SHA-256', view.get('input_manifest', {}).get('request_ref')), ('Final result SHA-256', view.get('final_ref'))]) +
        '<p class="muted">Generated ' + esc(view.get('generated_at')) + '</p></footer></main></body></html>')
    return save(output_directory, content.encode(), suffix='html')
