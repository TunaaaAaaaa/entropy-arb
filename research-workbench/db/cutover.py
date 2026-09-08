import json
from pathlib import Path
from db.connection import raw_connect
from db.pg_backup import inventory
from db.backup import digest


def activate(root, backup):
    root=Path(root).resolve();backup=Path(backup).resolve()
    manifest=json.loads((backup/'manifest.json').read_text(encoding='utf8'))
    restored=json.loads((backup/'restore-result.json').read_text(encoding='utf8'))
    if digest(backup/'database.dump')!=manifest['dump_sha256']:
        raise ValueError('Backup dump changed')
    for relative,sha in manifest['files'].items():
        file=(backup/'files'/relative).resolve()
        if not file.is_relative_to(backup/'files') or digest(file)!=sha:
            raise ValueError('Backup evidence changed')
    if restored['tables_verified']!=len(manifest['inventory']) or restored['files_verified']!=len(manifest['files']):
        raise ValueError('Restore drill incomplete')
    with raw_connect(root) as conn:
        if conn.info.dbname!=manifest['database'] or inventory(conn)!=manifest['inventory']:
            raise ValueError('Database changed since verified backup; take a fresh backup and restore it')
        if not conn.execute('SELECT 1 FROM ops.migration_runs WHERE finished_at IS NOT NULL LIMIT 1').fetchone():
            raise ValueError('Legacy migration has not completed')
    local=root/'data/local';local.mkdir(parents=True,exist_ok=True)
    value={'backend':'postgres','verified_backup':str(backup),'database':manifest['database']}
    temp=local/'backend.json.tmp';temp.write_text(json.dumps(value,indent=2),encoding='utf8');temp.replace(local/'backend.json')
    return value
