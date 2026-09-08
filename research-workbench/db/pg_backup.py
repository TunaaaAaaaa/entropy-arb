import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from datetime import datetime,timezone
from uuid import uuid4
from psycopg import sql
from db.connection import raw_connect,settings
from db.backup import digest


def inventory(conn):
    result={}
    tables=conn.execute("SELECT schemaname,tablename FROM pg_tables WHERE schemaname IN ('ops','evidence','research') OR (schemaname='public' AND tablename='schema_migrations') ORDER BY 1,2").fetchall()
    for schema,table in tables:
        rows=conn.execute(sql.SQL('SELECT to_jsonb(t)::text FROM {} t ORDER BY to_jsonb(t)::text').format(sql.Identifier(schema,table))).fetchall()
        result[schema+'.'+table]={'count':len(rows),'sha256':hashlib.sha256('\n'.join(r[0] for r in rows).encode()).hexdigest()}
    return result


def backup_postgres(root):
    root=Path(root).resolve()
    target=root/'data/pg-backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target.mkdir(parents=True)
    with raw_connect(root) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        snapshot=conn.execute('SELECT pg_export_snapshot()').fetchone()[0]
        dbname=conn.info.dbname;user=conn.info.user
        stats=inventory(conn)
        command=['docker','compose','-f',str(root/'compose.yaml'),'exec','-T','postgres','pg_dump','-U',user,'-d',dbname,'-Fc','--snapshot',snapshot]
        with (target/'database.dump').open('wb') as fh:
            proc=subprocess.run(command,stdout=fh,stderr=subprocess.PIPE)
        if proc.returncode: raise ValueError(proc.stderr.decode(errors='replace'))
        files={};unavailable_aliases=[]
        for (sha,) in conn.execute('SELECT sha256 FROM evidence.artifacts'):
            found=False
            for (relative,) in conn.execute('SELECT path FROM evidence.artifact_locations WHERE sha256=%s',(sha,)):
                source=(root.parent/relative).resolve()
                if not source.is_relative_to(root.parent): raise ValueError('Artifact path outside workspace')
                if not source.exists() or digest(source)!=sha:
                    unavailable_aliases.append(relative);continue
                dest=target/'files'/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
                if digest(dest)!=sha: raise ValueError('Backup file changed while copying')
                files[relative]=sha;found=True
            if not found: raise ValueError(f'No intact copy of artifact {sha}')
    manifest={'at':datetime.now(timezone.utc).isoformat(),'database':dbname,'inventory':stats,
              'dump_sha256':digest(target/'database.dump'),'files':files,'unavailable_aliases':unavailable_aliases}
    (target/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    return {'backup':str(target),'tables':len(stats),'files':len(files),'unavailable_aliases':unavailable_aliases}


def restore_postgres(root,backup):
    root=Path(root).resolve();backup=Path(backup).resolve()
    manifest=json.loads((backup/'manifest.json').read_text(encoding='utf8'))
    if digest(backup/'database.dump')!=manifest['dump_sha256']: raise ValueError('Dump hash mismatch')
    for relative,sha in manifest['files'].items():
        file=(backup/'files'/relative).resolve()
        if not file.is_relative_to(backup/'files') or digest(file)!=sha: raise ValueError('Backup evidence mismatch')
    name='entropy_restore_'+uuid4().hex[:12]
    with raw_connect(root) as admin:
        admin.autocommit=True
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        user=admin.info.user
    with (backup/'database.dump').open('rb') as fh:
        proc=subprocess.run(['docker','compose','-f',str(root/'compose.yaml'),'exec','-T','postgres','pg_restore','-U',user,'-d',name,'--exit-on-error','--single-transaction'],stdin=fh,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if proc.returncode: raise ValueError(proc.stderr.decode(errors='replace'))
    destination=root/'data/pg-restores'/name
    shutil.copytree(backup/'files',destination)
    for relative,sha in manifest['files'].items():
        if digest(destination/relative)!=sha: raise ValueError('Restored evidence mismatch')
    with raw_connect(root,database=name) as conn:
        restored=inventory(conn)
        if restored!=manifest['inventory']: raise ValueError('Restored database row hashes differ')
    result={'database':name,'files_directory':str(destination),'tables_verified':len(restored),'files_verified':len(manifest['files'])}
    (backup/'restore-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return result
