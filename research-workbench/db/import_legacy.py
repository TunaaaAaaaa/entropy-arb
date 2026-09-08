import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from psycopg import sql
from psycopg.types.json import Jsonb
from db.connection import raw_connect, TABLES
from db.evidence import ingest_run, ingest_document, ingest_feed, register_artifact, document_id, time_value
from db.backup import digest


def canonical_value(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return value


def verify_legacy(conn, old):
    result = {}
    for name, table in TABLES.items():
        source = old.execute(f'SELECT * FROM {name}').fetchall()
        columns = [d[0] for d in old.execute(f'SELECT * FROM {name} LIMIT 0').description]
        key = 'url' if name == 'crawled_documents' else 'id'
        for row in source:
            dest = conn.execute(sql.SQL('SELECT {} FROM {} WHERE {}=%s').format(
                sql.SQL(',').join(map(sql.Identifier,columns)),sql.Identifier(*table.split('.')),sql.Identifier(key)), (row[key],)).fetchone()
            if dest is None:
                raise ValueError(f'Missing migrated row: {name}/{row[key]}')
            for column, original, migrated in zip(columns, row, dest):
                if isinstance(migrated,datetime):
                    original = time_value(original)
                if original != migrated:
                    raise ValueError(f'Migration mismatch: {name}/{row[key]}/{column}')
        result[name] = len(source)
    return result


def import_legacy(root, snapshot=None):
    root = Path(root).resolve()
    dbfile = Path(snapshot).resolve() if snapshot else root/'data/research.db'
    old = sqlite3.connect(dbfile.as_uri()+'?mode=ro',uri=True)
    old.row_factory = sqlite3.Row
    import_id = 'sqlite:' + digest(dbfile)
    try:
        with raw_connect(root) as conn:
            conn.execute('SELECT pg_advisory_xact_lock(82641002)')
            conn.execute('INSERT INTO ops.migration_runs(id) VALUES(%s) ON CONFLICT DO NOTHING',(import_id,))
            for name,table in TABLES.items():
                for row in old.execute(f'SELECT * FROM {name}'):
                    columns = row.keys()
                    query = sql.SQL('INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING').format(
                        sql.Identifier(*table.split('.')),sql.SQL(',').join(map(sql.Identifier,columns)),
                        sql.SQL(',').join(sql.Placeholder() for _ in columns))
                    conn.execute(query,tuple(row))
                if name not in ('sources','crawled_documents'):
                    conn.execute(sql.SQL("SELECT setval(pg_get_serial_sequence(%s,'id'),COALESCE(MAX(id),1),MAX(id) IS NOT NULL) FROM {}").format(sql.Identifier(*table.split('.'))),(table,))
            counts = verify_legacy(conn,old)
            for row in old.execute('SELECT * FROM source_fetches'):
                ingest_feed(conn,root,row['source_id'],row['content_hash'],row['relative_path'],row['observed_at'],f"legacy-feed:{row['id']}")
            runs = [json.loads(p.read_text(encoding='utf8')) for p in (root/'data/crawl/runs').glob('*.json')]
            for run in sorted(runs,key=lambda r:r['at']):
                ingest_run(conn,root,run)
            for file in (root/'data/crawl/documents').glob('*.json'):
                sha = digest(file)
                if conn.execute('SELECT 1 FROM evidence.observations WHERE document_artifact=%s',(sha,)).fetchone():
                    continue
                doc = json.loads(file.read_text(encoding='utf8'))
                doc.update(document_path=file.relative_to(root).as_posix(),document_sha256=sha)
                did,vid,raw,manifest = ingest_document(conn,root,doc)
                conn.execute('''INSERT INTO evidence.observations(id,document_id,version_id,observed_at,status,raw_artifact,document_artifact)
                    VALUES(%s,%s,%s,%s,'legacy-document',%s,%s) ON CONFLICT DO NOTHING''',('legacy-document:'+sha,did,vid,time_value(doc['fetched_at']),raw,manifest))
            for folder in (root/'data/manual').glob('*'):
                if not (folder/'metadata.json').exists():
                    continue
                meta=json.loads((folder/'metadata.json').read_text(encoding='utf8'))
                raw=register_artifact(conn,root,folder/'response.json',meta['sha256'])
                manifest=register_artifact(conn,root,folder/'metadata.json')
                did=document_id(conn,meta['original_url'])
                conn.execute('''INSERT INTO evidence.observations(id,document_id,observed_at,status,raw_artifact,document_artifact,metadata)
                    VALUES(%s,%s,%s,'legacy-manual',%s,%s,%s) ON CONFLICT DO NOTHING''',
                    ('legacy-manual:'+manifest,did,time_value(meta['retrieved_at']),raw,manifest,Jsonb(meta)))
            # Preserve latest-only states even if their original run receipt has been lost.
            for row in old.execute('SELECT * FROM crawled_documents'):
                did=document_id(conn,row['url'])
                conn.execute('''INSERT INTO evidence.inbox_document_links(item_id,document_id)
                    SELECT id,%s FROM ops.inbox_items WHERE url=%s ON CONFLICT DO NOTHING''',(did,row['url']))
                if not conn.execute('SELECT 1 FROM evidence.observations WHERE document_id=%s AND attempted_at=%s AND status=%s',
                    (did,time_value(row['last_attempt']),row['status'])).fetchone():
                    conn.execute('''INSERT INTO evidence.observations(id,document_id,attempted_at,observed_at,status,metadata)
                        VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
                        ('legacy-latest:'+__import__('hashlib').sha256(row['url'].encode()).hexdigest(),did,time_value(row['last_attempt']),time_value(row['fetched_at']),row['status'],Jsonb({'error':row['error'],'legacy_latest_only':True})))
            from workbench import load_sources
            diffs=[]
            for source in load_sources(root):
                row=old.execute('SELECT * FROM sources WHERE id=?',(source['id'],)).fetchone()
                for k in ('name','kind','url','enabled','cadence_hours'):
                    if row and row[k]!=source[k]:
                        diffs.append({'source':source['id'],'field':k,'database':row[k],'config':source[k]})
                conn.execute('UPDATE ops.sources SET name=%s,kind=%s,url=%s,enabled=%s,tags=%s,cadence_hours=%s WHERE id=%s',
                             (source['name'],source['kind'],source['url'],int(source['enabled']),json.dumps(source['tags'],ensure_ascii=False),source['cadence_hours'],source['id']))
            report={'legacy_rows_verified':counts,'source_config_differences':diffs,'snapshot_sha256':digest(dbfile)}
            conn.execute('UPDATE ops.migration_runs SET finished_at=now(),report=%s WHERE id=%s',(Jsonb(report),import_id))
        dest=root/'data/migration';dest.mkdir(parents=True,exist_ok=True)
        (dest/'import-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        return report
    finally:
        old.close()
