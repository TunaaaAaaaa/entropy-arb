import csv
import difflib
import json
from pathlib import Path
import re
from psycopg.types.json import Jsonb
from db.evidence import register_artifact, time_value, stable_hash


def save_record(conn, root, identity, kind, file, status='draft'):
    file=Path(file).resolve()
    body=file.read_text(encoding='utf8')
    artifact=register_artifact(conn,root,file)
    title=next((s.lstrip('# ').strip() for s in body.splitlines() if s.strip()),identity)
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('record:'+identity,))
    previous=conn.execute('SELECT status,current_version_id FROM research.records WHERE id=%s',(identity,)).fetchone()
    conn.execute('''INSERT INTO research.records(id,kind,title,status) VALUES(%s,%s,%s,%s)
                    ON CONFLICT(id) DO UPDATE SET title=excluded.title,status=excluded.status''',(identity,kind,title,status))
    actual_kind=conn.execute('SELECT kind FROM research.records WHERE id=%s',(identity,)).fetchone()[0]
    if actual_kind!=kind:
        raise ValueError('Research record kind cannot change')
    conn.execute('''INSERT INTO research.record_versions(record_id,body,content_hash,metadata)
                    VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING''',(identity,body,artifact,Jsonb({'source_artifact':artifact,'imported_file':file.relative_to(Path(root).parent).as_posix()})))
    vid=conn.execute('SELECT id FROM research.record_versions WHERE record_id=%s AND content_hash=%s',(identity,artifact)).fetchone()[0]
    conn.execute('UPDATE research.records SET current_version_id=%s WHERE id=%s',(vid,identity))
    if previous is None or previous!=(status,vid):
        conn.execute('INSERT INTO research.record_events(record_id,version_id,previous_status,status) VALUES(%s,%s,%s,%s)',
                     (identity,vid,previous[0] if previous else None,status))
    for url in set(re.findall(r'https?://[^\s<>\)\]`"，；、]+',body)):
        # Importing old prose cannot establish which version its author saw.
        conn.execute('''INSERT INTO research.evidence_links(record_version_id,unresolved_url,relation)
                        VALUES(%s,%s,'background') ON CONFLICT DO NOTHING''',(vid,url.rstrip('。.')))
    return {'record_id':identity,'version_id':vid,'content_hash':artifact}


def import_research(conn,root):
    root=Path(root).resolve(); result={'records':[],'datasets':[],'experiments':[]}
    for kind,folder in [('case','cases'),('hypothesis','hypotheses')]:
        for file in sorted((root/folder).glob('[0-9]*.md')):
            result['records'].append(save_record(conn,root,kind+':'+file.stem,kind,file))
    for file in sorted((root.parent/'logs').rglob('*.csv')):
        artifact=register_artifact(conn,root,file)
        with file.open(encoding='utf8',newline='') as fh:
            reader=csv.DictReader(fh);rows=list(reader);fields=reader.fieldnames
        meta={'path':file.relative_to(root.parent).as_posix(),'row_count':len(rows),'fields':fields,
              'first_time_raw':rows[0].get('time_utc') if rows else None,'last_time_raw':rows[-1].get('time_utc') if rows else None,
              'market_identity':None,'identity_note':'Directory names are hints only; exact market/config version unverified'}
        did='csv:'+artifact
        conn.execute('INSERT INTO research.datasets(id,kind,artifact,metadata) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                     (did,'minute-quotes' if fields and 'minute_ts' in fields else 'csv',artifact,Jsonb(meta)))
        result['datasets'].append({'id':did,'rows':len(rows)})
    for file in sorted((root/'experiments').glob('*/result.json')):
        folder=file.parent;inputs=folder/'events.json';code=folder/'replay.py'
        if not inputs.exists() or not code.exists():
            continue
        output=json.loads(file.read_text(encoding='utf8'))
        inp=register_artifact(conn,root,inputs,output.get('input_sha256'))
        out=register_artifact(conn,root,file);script=register_artifact(conn,root,code)
        did='experiment-input:'+inp;eid='experiment-result:'+out
        conn.execute('INSERT INTO research.datasets(id,kind,artifact,synthetic,metadata) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                     (did,'experiment-input',inp,output.get('synthetic_data') is True,Jsonb({'path':inputs.relative_to(root).as_posix()})))
        conn.execute('''INSERT INTO research.experiment_runs(id,dataset_id,result_artifact,code_artifact,ran_at,metadata)
                        VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
                     (eid,did,out,script,time_value(output.get('run_at_utc')),Jsonb({'result':output,'code_provenance':'current file at import; historical run code revision unverified'})))
        result['experiments'].append(eid)
    return result


def query(conn, text):
    pattern='%'+text.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
    docs=conn.execute('''SELECT v.id,d.canonical_url,v.title,v.provenance,v.published_at,
                        left(v.body,300) FROM evidence.document_versions v JOIN evidence.documents d ON d.id=v.document_id
                        WHERE v.title ILIKE %s OR v.body ILIKE %s OR COALESCE(v.author,'') ILIKE %s OR d.canonical_url ILIKE %s
                        ORDER BY v.id DESC LIMIT 30''',(pattern,)*4).fetchall()
    records=conn.execute('''SELECT r.id,v.id,r.title,r.status FROM research.records r JOIN research.record_versions v ON v.id=r.current_version_id
                           WHERE r.title ILIKE %s OR v.body ILIKE %s ORDER BY r.id LIMIT 30''',(pattern,pattern)).fetchall()
    links=conn.execute('''SELECT l.record_version_id,l.document_version_id,l.unresolved_url,l.relation
                         FROM research.evidence_links l JOIN research.record_versions v ON v.id=l.record_version_id
                         WHERE v.body ILIKE %s ORDER BY l.id LIMIT 100''',(pattern,)).fetchall()
    experiments=conn.execute('''SELECT l.record_version_id,l.experiment_id,e.dataset_id,e.metadata
        FROM research.experiment_links l JOIN research.record_versions v ON v.id=l.record_version_id
        JOIN research.experiment_runs e ON e.id=l.experiment_id WHERE v.body ILIKE %s LIMIT 30''',(pattern,)).fetchall()
    return {'document_versions':docs,'research_records':records,'evidence_links':links,'experiment_links':experiments}


def link(conn, record_version, document_version, relation):
    conn.execute('INSERT INTO research.evidence_links(record_version_id,document_version_id,relation) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',
                 (record_version,document_version,relation))
    return {'record_version':record_version,'document_version':document_version,'relation':relation}


def export_record(conn,root,identity):
    row=conn.execute('''SELECT v.id,v.body FROM research.records r JOIN research.record_versions v ON v.id=r.current_version_id WHERE r.id=%s''',(identity,)).fetchone()
    if not row: raise ValueError('Unknown record')
    folder=Path(root)/'data/research-exports';folder.mkdir(parents=True,exist_ok=True)
    file=folder/(stable_hash(identity)[:16]+f'-v{row[0]}.md')
    file.write_text(row[1],encoding='utf8')
    return {'path':str(file),'version_id':row[0]}


def diff_versions(conn,left,right):
    rows={r[0]:r for r in conn.execute('SELECT id,document_id,body FROM evidence.document_versions WHERE id IN (%s,%s)',(left,right))}
    if left not in rows or right not in rows: raise ValueError('Unknown document version')
    if rows[left][1]!=rows[right][1]: raise ValueError('Versions must belong to the same document')
    return {'diff':'\n'.join(difflib.unified_diff(rows[left][2].splitlines(),rows[right][2].splitlines(),fromfile=str(left),tofile=str(right)))}
