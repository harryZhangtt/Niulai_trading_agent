"""Render inspectable evidence from a real scheduled Codex completion."""
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import sqlite3


def build(workspace):
    root=Path(workspace).resolve();state=root/'.job-runtime';folder=state/'proof'
    folder.mkdir(mode=0o700,exist_ok=True)
    challenge=json.loads((state/'config/proof-challenge.json').read_text())
    with sqlite3.connect(state/'engine/schedule.sqlite') as db:
        db.row_factory=sqlite3.Row
        row=db.execute('SELECT a.*,s.job_id,s.scheduled_at FROM attempts a JOIN slots s USING(slot_id) WHERE s.job_id=? ORDER BY a.started_at DESC LIMIT 1',(challenge['job_id'],)).fetchone()
        if row is None or row['status']!='succeeded':raise ValueError('PROOF_NOT_COMPLETED')
        row=dict(row);receipt=json.loads(row.pop('receipt'))
        counts={r['job_id']:r['n'] for r in db.execute('SELECT s.job_id,count(*) n FROM attempts a JOIN slots s USING(slot_id) GROUP BY s.job_id')}
    response_path=root/receipt['response_path']
    if not response_path.resolve().is_relative_to(state):raise ValueError('RESPONSE_OUTSIDE_STATE')
    response=response_path.read_text();parsed=json.loads(response)
    assert parsed.get('verification_phrase')==challenge['phrase']
    assert parsed.get('slot_id')==row['slot_id']
    assert receipt['turn_completed'] and receipt['exit_code']==0
    assert hashlib.sha256(response.encode()).hexdigest()==receipt['response_sha256']
    current=json.loads((state/'status.json').read_text());before=json.loads((state/'config/pre-restart-status.json').read_text())
    assert current['pid']!=before['pid']
    assert counts.get('runtime.scheduled-wake-proof.v1')==1 and counts.get(challenge['job_id'])==1
    def stamp(value):return datetime.fromtimestamp(value,timezone.utc).isoformat()
    evidence={'generated_at':datetime.now(timezone.utc).isoformat(),'status':'PASS','verification_phrase':challenge['phrase'],
              'scheduled_at':stamp(row['scheduled_at']),'started_at':stamp(row['started_at']),'ended_at':stamp(row['ended_at']),
              'start_delay_seconds':round(row['started_at']-row['scheduled_at'],3),'slot_id':row['slot_id'],
              'attempt_count':counts[challenge['job_id']],'codex_response':parsed,'transport_receipt':receipt,
              'restart_verified':{'previous_pid':before['pid'],'current_pid':current['pid'],'prior_completed_job_attempts':counts['runtime.scheduled-wake-proof.v1']},
              'scope':'Timed Codex readiness execution; not scheduled market-data collection or email delivery.'}
    (folder/'scheduled-wake-proof.json').write_text(json.dumps(evidence,indent=2))
    pairs=[('Result','PASS — scheduled Codex run completed'),('Verification phrase',challenge['phrase']),
           ('Scheduled time (UTC)',evidence['scheduled_at']),('Actual start (UTC)',evidence['started_at']),
           ('Start delay',str(evidence['start_delay_seconds'])+' seconds'),('Completion (UTC)',evidence['ended_at']),
           ('Attempts',str(evidence['attempt_count'])),('Requested model',receipt['requested_model']),
           ('CLI thread ID',receipt['thread_id']),('Scheduler restart',str(before['pid'])+' → '+str(current['pid'])),
           ('Duplicate check','Original and new proof jobs each have exactly one attempt')]
    table=''.join('<tr><th>'+html.escape(k)+'</th><td>'+html.escape(v)+'</td></tr>' for k,v in pairs)
    document='<!doctype html><html lang="en"><meta charset="utf-8"><title>Codex scheduled wake proof</title><style>body{font:16px/1.55 system-ui;max-width:1000px;margin:40px auto;padding:0 20px;color:#182535}th,td{text-align:left;vertical-align:top;padding:10px;border-bottom:1px solid #ddd}th{width:230px}pre{white-space:pre-wrap;background:#f3f5f7;padding:16px;overflow-wrap:anywhere}</style><h1>Codex scheduled wake: verified</h1><p>The launchd-managed scheduler started this run after a future time was assigned. The phrase below was returned by the model. Completion was checked against the CLI transport event and durable attempt record.</p><table>'+table+'</table><h2>Actual Codex response</h2><pre>'+html.escape(response)+'</pre><h2>Transport receipt</h2><pre>'+html.escape(json.dumps(receipt,indent=2))+'</pre><p>The CLI confirms a real completed turn. The model name is the explicit request; this event stream did not separately report a backend model name. This proof covers waking and executing Codex, plus restart and duplicate protection. It does not prove future punctuality, price collection or automatic email delivery.</p></html>'
    (folder/'scheduled-wake-proof.html').write_text(document)
    return evidence


if __name__=='__main__':
    os.umask(0o077);result=build(Path.cwd())
    print(json.dumps({k:result[k] for k in ('status','verification_phrase','start_delay_seconds','attempt_count','restart_verified')}))
