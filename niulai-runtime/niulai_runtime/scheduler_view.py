"""Read-only presentation of Niulai send eligibility and persisted mail outputs."""
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json

from shared.job_runtime.dashboard import database, read_json, require, scrub


@lru_cache(maxsize=1)
def calendar():
    import exchange_calendars
    return exchange_calendars.get_calendar('XNYS')


def describe(root, job, at, *, next_tick, detail=False, output_id=None):
    options = job.get('adapter_config') or {}
    target = options.get('target')
    scheduled = target == 'schedule'
    recovery = target == 'recovery'
    title = 'Daily price and holdings report' if scheduled else 'Missing-data recovery' if recovery else job['id']
    mode = 'scheduled' if scheduled else 'conditional' if recovery else 'test'
    due = None
    note = 'Starts on NYSE trading days; delivery follows data collection and verification.' if scheduled else 'Checks pending work; sends a correction only when missing data has recovered.' if recovery else 'Isolated acceptance job; not a production delivery.'
    if scheduled and job['enabled']:
        due = next_tick(job['schedule'], at, lambda day: calendar().is_session(str(day)))
    outputs, body = [], None
    path = root / '.niulai-state/databases/outbox.sqlite'
    if path.exists() and (scheduled or recovery) and detail:
        with database(root, path) as db:
            # Only production work belonging to this policy; never join arbitrary
            # manual sends, acceptance summaries or test namespaces into the page.
            policy = read_json(root, root / options['policy'])
            prefix = 'portfolio-email:' + policy['automation_id'] + ':'
            rows = db.execute('''SELECT o.key,o.status,o.prepared_at,o.updated_at,o.verified_at,
                json_extract(o.payload,'$.subject') AS subject,
                w.initial_key,w.correction_key
                FROM digest_work w JOIN outbox o ON o.key=w.initial_key OR o.key=w.correction_key
                WHERE json_extract(w.meta,'$.purpose')='production'
                AND json_extract(w.meta,'$.recipient')=? AND substr(w.logical_key,1,?)=?
                ORDER BY o.prepared_at DESC LIMIT 30''', (policy['recipient'], len(prefix), prefix)).fetchall()
            for row in rows:
                identity = hashlib.sha256(row['key'].encode()).hexdigest()
                kind = 'correction' if row['key'] == row['correction_key'] else 'initial'
                if recovery and kind != 'correction':
                    continue
                outputs.append({'id': identity, 'subject': scrub(row['subject'] or 'Saved report'),
                                'status': row['status'], 'verified': bool(row['verified_at']),
                                'created_at': row['prepared_at'], 'verified_at': row['verified_at'], 'kind': kind})
                if output_id == identity:
                    raw = db.execute('SELECT payload FROM outbox WHERE key=?', (row['key'],)).fetchone()[0]
                    require(len(raw) <= 16 * 1024 * 1024, 'DASHBOARD_OUTPUT_LIMIT')
                    payload = json.loads(raw)
                    parts, html, attachments = [payload.get('payload', {})], [], []
                    count = 0
                    while parts:
                        count += 1
                        part = parts.pop()
                        require(isinstance(part, dict) and count <= 100 and len(parts) < 100, 'DASHBOARD_OUTPUT_INVALID')
                        if part.get('mime_type') == 'text/html':
                            html.append(part.get('body', {}).get('content', ''))
                        if part.get('filename'):
                            attachments.append({'name': str(part['filename'])[:120], 'type': part.get('mime_type')})
                        parts.extend(part.get('parts', []))
                    content = scrub('\n'.join(html))
                    require(len(content) <= 1024 * 1024, 'DASHBOARD_OUTPUT_LIMIT')
                    body = {'id': identity, 'subject': scrub(payload.get('subject', 'Saved report')),
                            'html': content, 'attachments': attachments}
    require(output_id is None or body is not None, 'DASHBOARD_OUTPUT_NOT_FOUND')
    result = {'title': title, 'description': 'Combined price rules and portfolio email.' if scheduled else note,
              'delivery': {'mode': mode, 'next_send_at': due, 'note': note, 'calendar': 'XNYS' if scheduled else None},
              'outputs': outputs}
    if body is not None:
        result['output'] = body
    return result
