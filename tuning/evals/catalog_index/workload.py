"""Bounded shadow-catalog conformance and I/O workload; no model or network.

Repeated real records measure durable-index reuse, not 20k unique report ingest.
Concurrent and revision probes use separate stores and label modified data synthetic.
"""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

from shared.research_sources.artifacts import ROOT, digest, read, save, SourceError
from shared.research_sources.indexing import RecordIndex
from investment.research.catalog import import_catalog


def execute(roster_ref, out, source_path, source_sha256):
    out=Path(out);roster=read(roster_ref);records=roster['records'];started=time.perf_counter()
    timings={};t=time.perf_counter()
    import_ref=import_catalog(roster['source_path'],out/'catalog')
    initial=read(import_ref)['outcomes'];index=RecordIndex(out/'catalog/index')
    timings['initial']=time.perf_counter()-t
    base=digest({'source':roster_ref,'question':'legacy report discovery, no semantic admission'})
    queries=[];t=time.perf_counter()
    for entity in sorted({r['entity'] for r in records}):
        selected=index.select(entity=entity,baseline_hash=base,requirement_id='catalog:'+entity,
            cutoff='2026-10-31T23:59:59Z',limit=128)
        checkpoint=index.checkpoint('catalog-snapshot:'+digest(selected['context']),selected)
        queries.append({'entity':entity,'selection_ref':save(out/'queries',selected),
                        'snapshot_id':checkpoint['snapshot_id']})
    timings['queries_and_snapshots']=time.perf_counter()-t
    t=time.perf_counter();replay=[index.put(r) for r in records];timings['replay']=time.perf_counter()-t
    t=time.perf_counter();routes=Counter()
    for i in range(20000): routes[index.put(records[i%len(records)])['route']]+=1
    timings['stress_20000_replays']=time.perf_counter()-t
    # Actual process contention, isolated from the source-derived index.
    subset=records[:32];subset_ref=save(out/'inputs',subset)
    concurrent=RecordIndex(out/'concurrent')
    code='''import sys,json
from collections import Counter
from shared.research_sources.artifacts import read
from shared.research_sources.indexing import RecordIndex
rows=read(json.loads(sys.argv[2]));idx=RecordIndex(sys.argv[1]);counts=Counter()
for row in rows:counts[idx.put(row)['route']]+=1
print(json.dumps(dict(counts)))'''
    t=time.perf_counter()
    children=[subprocess.Popen([sys.executable,'-c',code,str(out/'concurrent'),json.dumps(subset_ref)],
        cwd=ROOT,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,text=True) for _ in range(4)]
    child_results=[]
    try:
        for child in children:
            try: stdout,stderr=child.communicate(timeout=45)
            except subprocess.TimeoutExpired:
                child.kill();stdout,stderr=child.communicate()
            child_results.append({'returncode':child.returncode,'routes':json.loads(stdout) if child.returncode==0 else None,
                                  'stderr_present':bool(stderr)})
    finally:
        for child in children:
            if child.poll() is None:
                child.kill();child.communicate(timeout=5)
    timings['concurrent']=time.perf_counter()-t
    # Revisions are explicitly synthetic and never replace a real indexed note.
    probe=RecordIndex(out/'revision-probe');first=probe.put(records[0]);
    selected=probe.select(entity=records[0]['entity'],baseline_hash=base,requirement_id='synthetic-race',
        cutoff='2026-10-31T23:59:59Z')
    original_snapshot=probe.checkpoint('before-revision',selected)
    modified={**records[0],'content':{'synthetic_mutation_for_test':True,'original':records[0]['content']}}
    second=probe.put(modified,expected_revision=1)
    try: probe.checkpoint('stale',selected);race_error=None
    except SourceError as exc:race_error=str(exc)
    future={**records[0],'record_id':'synthetic-future','available_at':'2099-01-01T00:00:00Z'}
    probe.put(future)
    timed=probe.select(entity=records[0]['entity'],baseline_hash=base,requirement_id='synthetic-time',
        cutoff='2026-10-31T23:59:59Z')
    peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform!='darwin':peak*=1024
    result={'roster_ref':roster_ref,'import_result_ref':import_ref,
        'index_directory':str(out/'catalog/index'),'initial':initial,'replay':replay,
        'queries':queries,'stress':{'operations':20000,'routes':dict(routes),'unique_input_records':len(records)},
        'concurrent':{'directory':str(out/'concurrent'),'expected_records_ref':subset_ref,'children':child_results},
        'revision_probe':{'directory':str(out/'revision-probe'),'first':first,'second':second,
            'original_snapshot':original_snapshot,'stale_error':race_error,'temporal_selection':timed},
        'source_path':str(source_path),'source_sha256_before':source_sha256,
        'source_sha256_after':hashlib.sha256(Path(source_path).read_bytes()).hexdigest(),
        'timings':timings,'elapsed_seconds':time.perf_counter()-started,'peak_rss_bytes':peak,
        'provider_calls':0,'model_calls':0,'model_tokens':None,'model_cost':None,
        'scope':'isolated_existing_catalog_component','semantic_quality_tested':False,'runtime_accepted':False}
    return save(out/'results',result)
