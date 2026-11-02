import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from investment.research.catalog import records_from_database, import_catalog
from shared.research_sources.artifacts import SOURCE_STATE, SourceError, read


class CatalogTests(unittest.TestCase):
    def test_secondary_notes_and_pointers_never_become_report_bodies(self):
        parent=SOURCE_STATE/'tmp';parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as tmp:
            path=Path(tmp)/'fixture.sqlite'
            with sqlite3.connect(path) as db:
                db.executescript('''CREATE TABLE artifacts(library_file_id,version,filename,status,payload);
                CREATE TABLE securities(symbol);CREATE TABLE artifact_securities(symbol,library_file_id);
                CREATE TABLE security_artifact_relations(security_symbol,artifact_id,section_id);
                CREATE TABLE research_sections(id,artifact_id,payload);
                CREATE TABLE research_store_revisions(id,revision,ticker,kind,state,payload);
                CREATE TABLE research_store_heads(id,revision);''')
                db.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)',('r',1,'Synthetic.pdf','complete',
                    json.dumps({'content_access':'full_text_read','local_working_copy':{'path':'/missing.pdf'}})))
                db.execute('INSERT INTO securities VALUES(?)',('SYNTH',))
                db.execute('INSERT INTO security_artifact_relations VALUES(?,?,?)',('SYNTH','r','s'))
                db.execute('INSERT INTO research_sections VALUES(?,?,?)',('s','r','{}'))
                db.execute('INSERT INTO research_store_revisions VALUES(?,?,?,?,?,?)',('e',1,'SYNTH','evidence','active',
                    json.dumps({'claim':'Synthetic revenue','source_url':'https://example.com/not-read'})))
                db.execute('INSERT INTO research_store_heads VALUES(?,?)',('e',1))
            result=records_from_database(path)
            self.assertEqual(len(result['records']),3)
            self.assertEqual({r['content_access'] for r in result['records']},{'metadata_only','secondary_note'})
            self.assertTrue(all(r['available_at'] is None for r in result['records']))
            families={r['source_family'] for r in result['records'] if r['kind'].endswith('metadata')}
            self.assertEqual(len(families),1)
            self.assertEqual(records_from_database(path,excluded_symbols=('SYNTH',))['records'],[])
            out=Path(tmp)/'import'
            first=read(import_catalog(path,out));second=read(import_catalog(path,out))
            self.assertEqual(first['routes'],{'created':3})
            self.assertEqual(second['routes'],{'reused':3})
            with sqlite3.connect(path) as db:
                db.execute('DELETE FROM research_sections')
            with self.assertRaisesRegex(SourceError,'CATALOG_NEW_CORPUS_REQUIRES_NEW_OUTPUT'):
                import_catalog(path,out)
            fresh=read(import_catalog(path,Path(tmp)/'new-roster'))
            self.assertEqual(fresh['indexed'],2)


if __name__=='__main__': unittest.main()
