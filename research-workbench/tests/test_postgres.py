"""Real PostgreSQL tests in disposable, uniquely named databases; opt-in only."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from workbench import SCHEMA,add_item,review_item,collect,report,inbox
from db.connection import raw_connect,settings,PgConnection
from db.migrate import migrate
from db.evidence import ingest_run,digest,time_value
from db.research import save_record,link,diff_versions
from db.import_legacy import import_legacy


@unittest.skipUnless(os.environ.get('RUN_POSTGRES_TESTS')=='1','set RUN_POSTGRES_TESTS=1 for isolated PostgreSQL tests')
class PostgresTests(unittest.TestCase):
    def setUp(self):
        self.name='entropy_test_'+uuid4().hex[:12]
        self.admin=raw_connect(ROOT);self.admin.autocommit=True
        self.admin.execute('CREATE DATABASE '+self.name)
        (ROOT/'data/pgtests').mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'data/pgtests')
        self.root=Path(self.temp.name)/'research-workbench';(self.root/'data/local').mkdir(parents=True)
        config=settings(ROOT);config['dbname']=self.name
        (self.root/'data/local/postgres.json').write_text(json.dumps(config))
        (self.root/'data/local/backend.json').write_text('{"backend":"postgres"}')
        (self.root/'sources.json').write_text('{"version":1,"sources":[]}')
        migrate(self.root)

    def tearDown(self):
        if not self.name.startswith('entropy_test_'): raise AssertionError('Unsafe database name')
        self.admin.execute('DROP DATABASE '+self.name+' WITH (FORCE)')
        self.admin.close();self.temp.cleanup()

    def doc(self,body='First version',at='2026-09-08T00:00:00Z'):
        folder=self.root/'data/crawl';(folder/'raw').mkdir(parents=True,exist_ok=True);(folder/'documents').mkdir(exist_ok=True)
        raw=folder/'raw'/('payload-'+uuid4().hex+'.bin');raw.write_text(body)
        doc={'url':'https://example.com/post','title':'中文规则','text':body,'markdown':body,'author':'author',
             'published_at':'2026-09-08 08:00:00','fetched_at':at,'provenance':'direct-http','extractor_version':1,
             'raw_path':raw.relative_to(self.root).as_posix(),'raw_sha256':digest(raw),'warnings':[]}
        file=folder/'documents'/(uuid4().hex+'.json');file.write_text(json.dumps(doc),encoding='utf8')
        doc.update(document_path=file.relative_to(self.root).as_posix(),document_sha256=digest(file))
        return doc

    def test_existing_inbox_collect_review_and_report(self):
        with closing(PgConnection(self.root)) as db:
            item,_=add_item(db,'中文','https://example.com/a','保留分析')
            review_item(db,item,'shortlist','人工备注')
            sources=[{'id':'feed','name':'Feed','kind':'feed','url':'https://example.com/rss','enabled':True,'tags':[],'cadence_hours':24}]
            fetch=lambda _: (b'<rss><channel><item><guid>1</guid><title>one</title></item></channel></rss>','utf8')
            self.assertEqual(collect(db,sources,fetcher=fetch,now='2026-09-08T00:00:00Z')[0]['baseline'],1)
            self.assertEqual(len(inbox(db)),0)
            self.assertEqual(len(inbox(db,include_baseline=True)),1)
            self.assertEqual(db.raw.execute('SELECT count(*) FROM evidence.observations').fetchone()[0],1)
            self.assertIn('人工备注',report(db,self.root).read_text(encoding='utf8'))

    def test_versions_observations_and_pinned_research(self):
        d1=self.doc();d2=self.doc('Changed version','2026-09-09T00:00:00Z')
        with raw_connect(self.root) as conn:
            run={'id':'run1','at':'2026-09-08T01:00:00Z','results':[{'url':d1['url'],'status':'fetched','document':d1}]}
            ingest_run(conn,self.root,run);ingest_run(conn,self.root,run)
            first=conn.execute('SELECT current_version_id FROM evidence.documents').fetchone()[0]
            file=self.root/'case.md';file.write_text('## 中文案例\nEvidence from the first version',encoding='utf8')
            record=save_record(conn,self.root,'case:test','case',file)
            link(conn,record['version_id'],first,'supports')
            ingest_run(conn,self.root,{'id':'run2','at':'2026-09-09T01:00:00Z','results':[{'url':d2['url'],'status':'fetched','document':d2}]})
            ingest_run(conn,self.root,{'id':'run3','at':'2026-09-10T01:00:00Z','results':[{'url':d1['url'],'status':'cached','document':d1}]})
            self.assertEqual(conn.execute('SELECT count(*) FROM evidence.document_versions').fetchone()[0],2)
            self.assertEqual(conn.execute('SELECT count(*) FROM evidence.observations').fetchone()[0],3)
            current=conn.execute('SELECT current_version_id FROM evidence.documents').fetchone()[0]
            self.assertNotEqual(first,current)
            self.assertIsNone(conn.execute('SELECT published_at FROM evidence.document_versions LIMIT 1').fetchone()[0])
            self.assertEqual(conn.execute('SELECT document_version_id FROM research.evidence_links WHERE document_version_id IS NOT NULL').fetchone()[0],first)
            self.assertIn('Changed version',diff_versions(conn,first,current)['diff'])
            file.write_text('## 中文案例\nRevised conclusion',encoding='utf8');save_record(conn,self.root,'case:test','case',file)
            self.assertEqual(conn.execute('SELECT count(*) FROM research.record_versions').fetchone()[0],2)
        with raw_connect(self.root) as conn:
            with self.assertRaises(Exception):
                with conn.transaction(): conn.execute("UPDATE evidence.document_versions SET body='overwrite'")
            self.assertEqual(conn.execute('SELECT count(*) FROM evidence.document_versions').fetchone()[0],2)

    def test_concurrent_item_creation_is_unique(self):
        def create(_):
            with closing(PgConnection(self.root)) as db:
                return add_item(db,'same','https://example.com/same','body')[0]
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids=list(pool.map(create,range(4)))
        self.assertEqual(len(set(ids)),1)

    def test_missing_and_altered_evidence_rolls_back(self):
        doc=self.doc();(self.root/doc['raw_path']).write_text('changed')
        with raw_connect(self.root) as conn:
            with self.assertRaises(ValueError):
                with conn.transaction(): ingest_run(conn,self.root,{'id':'bad','at':'2026-09-08T00:00:00Z','results':[{'url':doc['url'],'status':'fetched','document':doc}]})
            self.assertEqual(conn.execute('SELECT count(*) FROM ops.crawl_jobs').fetchone()[0],0)
            (self.root/doc['raw_path']).unlink()
            with self.assertRaises(FileNotFoundError):
                with conn.transaction(): ingest_run(conn,self.root,{'id':'missing','at':'2026-09-08T00:00:00Z','results':[{'url':doc['url'],'status':'fetched','document':doc}]})

    def test_legacy_import_is_idempotent_and_preserves_notes(self):
        db=sqlite3.connect(self.root/'data/research.db');db.row_factory=sqlite3.Row;db.executescript(SCHEMA)
        item,_=add_item(db,'old','https://example.com/old','old note');review_item(db,item,'archive','reason');db.close()
        first=import_legacy(self.root);second=import_legacy(self.root)
        self.assertEqual(first,second)
        with raw_connect(self.root) as conn:
            self.assertEqual(conn.execute('SELECT summary,status,review_note FROM ops.inbox_items').fetchone(),('old note','archive','reason'))
            self.assertEqual(conn.execute('SELECT count(*) FROM ops.review_events').fetchone()[0],1)
        self.assertEqual(migrate(self.root)['applied'],[])

    def test_crawler_bridge_preserves_notes_links_multiple_sources_and_failure(self):
        spec=importlib.util.spec_from_file_location('pg_crawler_import',ROOT/'crawler/import_documents.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        d=self.doc()
        with closing(PgConnection(self.root)) as db:
            item,_=add_item(db,'manual',d['url'],'analysis')
            review_item(db,item,'shortlist','review')
            with db:
                db.execute("INSERT INTO sources(id,name,kind,url,enabled) VALUES('second','second','feed','https://example.com/rss',1)")
                from workbench import save_item
                save_item(db,{'id':'second','kind':'feed'},{'identity':'item','url':d['url'],'title':'feed','summary':'summary','published_at':None},'2026-09-08T00:00:00Z')
        run={'id':'bridge','at':'2026-09-08T01:00:00Z','results':[{'url':d['url'],'status':'fetched','document':d}]}
        module.import_run(self.root,run);module.import_run(self.root,run)
        module.import_run(self.root,{'id':'failed','at':'2026-09-09T00:00:00Z','results':[{'url':d['url'],'status':'failed','error':'503'}]})
        with raw_connect(self.root) as conn:
            self.assertEqual(conn.execute('SELECT summary,status,review_note FROM ops.inbox_items WHERE id=%s',(item,)).fetchone(),('analysis','shortlist','review'))
            self.assertEqual(conn.execute('SELECT count(*) FROM evidence.inbox_document_links').fetchone()[0],2)
            latest=conn.execute('SELECT status,document_path FROM ops.crawled_documents').fetchone()
            self.assertEqual(latest[0],'failed');self.assertIsNotNone(latest[1])
