"""Read a legacy Niulai research catalog without executing jobs or trusting pointers.

Reports, section metadata, evidence notes and assessments retain distinct types.
The preserved database is opened read-only. Referenced report paths are not opened.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from shared.research_sources.artifacts import ROOT, digest, encoded, private_path, require, save
from shared.research_sources.indexing import RecordIndex, VERSION


def records_from_database(path, *, namespace='niulai-research-catalog', excluded_symbols=('AER',)):
    path = Path(path).absolute()
    require(path.is_file() and path.is_relative_to(ROOT) and not path.is_symlink(), 'CATALOG_DATABASE_INVALID')
    require(path.resolve().is_relative_to(ROOT), 'CATALOG_DATABASE_INVALID')
    blocked = {s.upper() for s in excluded_symbols}
    records, excluded = [], []
    # One read transaction gives a consistent roster, including its relations.
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.execute('BEGIN')
        artifacts = {r[0]: (r[1], r[2], r[3], r[4]) for r in db.execute(
            'SELECT library_file_id,version,filename,status,payload FROM artifacts')}
        rels = list(db.execute('SELECT security_symbol,artifact_id,section_id FROM security_artifact_relations'))
        legacy_rels = list(db.execute('SELECT symbol,library_file_id FROM artifact_securities'))
        securities = {r[0].upper() for r in db.execute('SELECT symbol FROM securities')}
        artifact_symbols, section_symbols = {}, {}
        for symbol, aid, sid in rels:
            artifact_symbols.setdefault(aid, set()).add(symbol.upper())
            if sid: section_symbols.setdefault(sid, set()).add(symbol.upper())
        for symbol, aid in legacy_rels:
            artifact_symbols.setdefault(aid, set()).add(symbol.upper())

        def emit(table, rid, entities, kind, title, content, family=None):
            entities = {x.upper() for x in entities if isinstance(x, str) and x.strip()}
            if entities & blocked or any(word in (title + ' ' + str(rid)).casefold()
                                         for word in ('holdout', 'protected', 'aercap')):
                excluded.append({'table': table, 'record_id_hash': digest(rid), 'reason': 'protected_scope'}); return
            for entity in sorted(entities or {'UNMAPPED'}):
                records.append({'namespace': namespace, 'record_id': table + ':' + str(rid), 'entity': entity,
                    'kind': kind, 'title': title, 'source_family': family or namespace + ':unknown_upstream',
                    'available_at': None,
                    'content_access': 'metadata_only' if kind in {'catalog_metadata', 'section_metadata'} else 'secondary_note',
                    'content': content})

        for aid, (version, filename, status, raw) in sorted(artifacts.items()):
            emit('artifacts', aid, artifact_symbols.get(aid, set()), 'catalog_metadata', filename or aid,
                {'library_file_id': aid, 'version': version, 'status': status, 'catalog_record': json.loads(raw),
                 'access_note': 'Legacy catalog assertions only; local_working_copy paths are not opened.'},
                 family=namespace + ':artifact:' + aid)
        for sid, aid, raw in db.execute('SELECT id,artifact_id,payload FROM research_sections ORDER BY id'):
            emit('research_sections', sid, section_symbols.get(sid, artifact_symbols.get(aid, set())),
                 'section_metadata', sid, {'artifact_id': aid, 'section_record': json.loads(raw)},
                 family=namespace + ':artifact:' + aid)
        for rid, revision, ticker, kind, state, raw in db.execute('''SELECT r.id,r.revision,r.ticker,r.kind,r.state,r.payload
                FROM research_store_revisions r JOIN research_store_heads h ON r.id=h.id AND r.revision=h.revision ORDER BY r.id'''):
            if state != 'active':
                excluded.append({'table': 'research_store_revisions', 'record_id_hash': digest(rid), 'reason': 'inactive'}); continue
            if ticker and ticker.upper() in blocked:
                excluded.append({'table': 'research_store_revisions', 'record_id_hash': digest(rid), 'reason': 'protected_scope'}); continue
            require(kind in {'evidence', 'assessment'}, 'CATALOG_RECORD_KIND_UNSUPPORTED')
            emit('research_store_revisions', rid, {ticker} if ticker else set(),
                 'evidence_note' if kind == 'evidence' else 'assessment_note', rid,
                 {'legacy_revision': revision, 'legacy_kind': kind, 'note': json.loads(raw),
                  'access_note': 'A stored note is not the original cited source, even if that source has a URL.'})
    return {'version': VERSION, 'records': records, 'excluded': excluded,
            'securities': sorted(securities - blocked), 'source_path': str(path),
            'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'counts': dict(Counter(r['kind'] for r in records)),
            'limitations': ['Unknown original availability retained as null.',
                'No report bodies fetched, legacy review authenticated, protected data or queued tasks executed.']}


def import_catalog(path, out):
    roster = records_from_database(path)
    out = private_path(out, create=True)
    # An index output belongs to one frozen corpus. Repeating the same import is
    # safe; a changed/deleted roster requires a new output, not stale old heads.
    context = {'version': VERSION, 'record_roster_sha256': digest(roster['records'])}
    context_ref = save(out / 'inputs', context)
    marker = out / 'corpus.json'
    try:
        os.link(context_ref['path'], marker)
        fd = os.open(out, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except FileExistsError:
        require(not marker.is_symlink() and marker.read_bytes() == encoded(context),
                'CATALOG_NEW_CORPUS_REQUIRES_NEW_OUTPUT')
    index = RecordIndex(out / 'index')
    roster_ref = save(Path(out) / 'inputs', roster)
    outcomes = [index.put(record) for record in roster['records']]
    result = {'roster_ref': roster_ref, 'outcomes': outcomes, 'indexed': len(outcomes),
              'routes': dict(Counter(row['route'] for row in outcomes)), 'scope': 'catalog_and_notes_only',
              'unregistered_entities': sorted({r['entity'] for r in roster['records']} - set(roster['securities'])),
              'semantic_verification': 'not_performed', 'production_modified': False}
    return save(Path(out) / 'results', result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    print(json.dumps(import_catalog(args.database, Path(args.out).absolute())))


if __name__ == '__main__':
    main()
