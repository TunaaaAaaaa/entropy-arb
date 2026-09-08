import hashlib
import json
from pathlib import Path
import shutil
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from psycopg.types.json import Jsonb
from db.backup import digest


def time_value(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else None
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        try:
            date = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    return date.astimezone(timezone.utc) if date.tzinfo else None


def stable_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def register_artifact(conn, root, file, expected=None):
    root, file = Path(root).resolve(), Path(file).resolve()
    if not file.is_relative_to(root.parent):
        raise ValueError('Artifact must be inside project workspace')
    actual = digest(file)
    if expected and expected != actual:
        raise ValueError(f'Artifact hash mismatch: {file.name}')
    relative = file.relative_to(root.parent).as_posix()
    # Case and dataset source paths may be edited later; preserve a content-addressed copy.
    store = root / 'data/artifacts' / actual
    store.parent.mkdir(parents=True, exist_ok=True)
    if store.exists():
        if digest(store) != actual:
            raise ValueError('Immutable artifact store has been altered')
    else:
        shutil.copyfile(file, store)
        if digest(store) != actual:
            raise ValueError('Artifact changed while archiving')
    conn.execute('INSERT INTO evidence.artifacts(sha256,bytes,format) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',
                 (actual, file.stat().st_size, file.suffix.lstrip('.') or 'binary'))
    conn.execute('INSERT INTO evidence.artifact_locations(sha256,path) VALUES(%s,%s) ON CONFLICT DO NOTHING', (actual, relative))
    conn.execute('INSERT INTO evidence.artifact_locations(sha256,path) VALUES(%s,%s) ON CONFLICT DO NOTHING', (actual, store.relative_to(root.parent).as_posix()))
    return actual


def document_id(conn, url):
    conn.execute('INSERT INTO evidence.documents(canonical_url,original_url) VALUES(%s,%s) ON CONFLICT DO NOTHING', (url,url))
    return conn.execute('SELECT id FROM evidence.documents WHERE canonical_url=%s', (url,)).fetchone()[0]


def ingest_document(conn, root, doc):
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('document:' + doc['url'],))
    raw = register_artifact(conn, root, Path(root) / doc['raw_path'], doc['raw_sha256'])
    manifest = register_artifact(conn, root, Path(root) / doc['document_path'], doc.get('document_sha256'))
    saved = json.loads((Path(root) / doc['document_path']).read_text(encoding='utf8'))
    for key in ('text','title','url','raw_sha256','fetched_at'):
        if saved.get(key) != doc.get(key):
            raise ValueError(f'Document payload differs from immutable evidence: {key}')
    did = document_id(conn, doc['url'])
    content = {k: doc.get(k) for k in ['title','text','markdown','author','published_at','provenance','extractor_version','media','quoted_post']}
    chash = stable_hash(content)
    conn.execute('''INSERT INTO evidence.document_versions(document_id,content_hash,title,body,markdown,author,
                    published_at,published_at_raw,provenance,extractor_version,metadata)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
                 (did,chash,doc['title'],doc['text'],doc.get('markdown',doc['text']),doc.get('author'),
                  time_value(doc.get('published_at')),doc.get('published_at'),doc['provenance'],str(doc.get('extractor_version','unknown')),
                  Jsonb({k:doc.get(k) for k in ('media','quoted_post','warnings')})))
    vid = conn.execute('SELECT id FROM evidence.document_versions WHERE document_id=%s AND content_hash=%s', (did,chash)).fetchone()[0]
    # Old/cached replay must not move the current pointer behind a newer observed version.
    latest = conn.execute('SELECT MAX(observed_at) FROM evidence.observations WHERE document_id=%s', (did,)).fetchone()[0]
    observed = time_value(doc['fetched_at'])
    if latest is None or (observed and observed >= latest):
        conn.execute('UPDATE evidence.documents SET current_version_id=%s WHERE id=%s', (vid,did))
    conn.execute('''INSERT INTO evidence.inbox_document_links(item_id,document_id)
                    SELECT id,%s FROM ops.inbox_items WHERE url=%s ON CONFLICT DO NOTHING''', (did,doc['url']))
    return did, vid, raw, manifest


def ingest_run(conn, root, run):
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('run:' + run['id'],))
    runfile = Path(root) / 'data/crawl/runs' / (run['id'] + '.json')
    artifact = register_artifact(conn, root, runfile) if runfile.exists() else None
    conn.execute('''INSERT INTO ops.crawl_jobs(id,status,started_at,finished_at,result_artifact)
                    VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
                 (run['id'],'failed' if any(r['status']=='failed' for r in run['results']) else 'complete',
                  time_value(run.get('started_at',run['at'])),time_value(run['at']),artifact))
    for i, result in enumerate(run['results']):
        rid = f"{run['id']}:{i}"
        if conn.execute('SELECT 1 FROM evidence.observations WHERE id=%s', (rid,)).fetchone():
            continue
        did = document_id(conn, result['url'])
        vid = raw = manifest = observed = None
        if result['status'] != 'failed':
            did,vid,raw,manifest = ingest_document(conn,root,result['document'])
            observed = time_value(result['document']['fetched_at'])
        conn.execute('''INSERT INTO evidence.observations(id,document_id,version_id,attempted_at,observed_at,status,
                        raw_artifact,document_artifact,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                     (rid,did,vid,time_value(run['at']),observed,result['status'],raw,manifest,
                      Jsonb({'error':result.get('error'),'run_id':run['id'],'fetched_url':result.get('document',{}).get('fetched_url')})))
        conn.execute('''INSERT INTO ops.job_events(id,job_id,at,url,status,details) VALUES(%s,%s,%s,%s,%s,%s)
                        ON CONFLICT DO NOTHING''', (rid,run['id'],time_value(run['at']),result['url'],result['status'],Jsonb({'error':result.get('error')})))
    for event in run.get('attempts',[]):
        conn.execute('INSERT INTO ops.job_events(id,job_id,at,url,status,details) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                     (event['id'],run['id'],time_value(event['at']),event['url'],event['status'],Jsonb(event)))


def ingest_feed(conn, root, source_id, payload_hash, relative_path, at, key):
    artifact = register_artifact(conn, root, Path(root)/relative_path, payload_hash)
    conn.execute('''INSERT INTO evidence.observations(id,source_id,attempted_at,observed_at,status,raw_artifact)
                    VALUES(%s,%s,%s,%s,'feed',%s) ON CONFLICT DO NOTHING''', (key,source_id,time_value(at),time_value(at),artifact))
