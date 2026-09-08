import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db.backup import make_backup, verify_backup, restore_backup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('backup')
    sub.add_parser('migrate')
    sub.add_parser('status')
    p = sub.add_parser('import-legacy'); p.add_argument('--snapshot')
    sub.add_parser('import-research')
    sub.add_parser('backup-pg')
    p = sub.add_parser('restore-pg'); p.add_argument('path')
    p = sub.add_parser('activate'); p.add_argument('--verified-backup',required=True)
    p = sub.add_parser('document'); p.add_argument('version',type=int)
    p = sub.add_parser('link-experiment'); p.add_argument('record_version',type=int); p.add_argument('experiment')
    p = sub.add_parser('search'); p.add_argument('query')
    p = sub.add_parser('save-record'); p.add_argument('id'); p.add_argument('file'); p.add_argument('--kind', choices=['case','hypothesis'], required=True); p.add_argument('--status',default='draft')
    p = sub.add_parser('export-record'); p.add_argument('id')
    p = sub.add_parser('link'); p.add_argument('record_version',type=int); p.add_argument('document_version',type=int); p.add_argument('--relation',choices=['supports','refutes','background'],required=True)
    p = sub.add_parser('diff'); p.add_argument('left',type=int); p.add_argument('right',type=int)
    p = sub.add_parser('verify-backup'); p.add_argument('path')
    p = sub.add_parser('restore-backup'); p.add_argument('path'); p.add_argument('destination')
    args = parser.parse_args()
    if args.command=='activate':
        from db.cutover import activate
        result=activate(args.root,args.verified_backup)
    elif args.command in ('backup-pg','restore-pg'):
        from db.pg_backup import backup_postgres,restore_postgres
        result=backup_postgres(args.root) if args.command=='backup-pg' else restore_postgres(args.root,args.path)
    elif args.command in ('import-research','search','save-record','export-record','link','diff','document','link-experiment'):
        from db.connection import raw_connect
        from db import research
        with raw_connect(args.root) as conn:
            if args.command=='document':
                row=conn.execute('SELECT to_jsonb(v) FROM evidence.document_versions v WHERE id=%s',(args.version,)).fetchone()
                if not row: raise ValueError('Unknown version')
                result=row[0]
            elif args.command=='link-experiment':
                conn.execute('INSERT INTO research.experiment_links(record_version_id,experiment_id) VALUES(%s,%s) ON CONFLICT DO NOTHING',(args.record_version,args.experiment))
                result={'linked':True}
            elif args.command=='import-research': result=research.import_research(conn,args.root)
            elif args.command=='search': result=research.query(conn,args.query)
            elif args.command=='save-record': result=research.save_record(conn,args.root,args.id,args.kind,args.file,args.status)
            elif args.command=='export-record': result=research.export_record(conn,args.root,args.id)
            elif args.command=='link': result=research.link(conn,args.record_version,args.document_version,args.relation)
            else: result=research.diff_versions(conn,args.left,args.right)
    elif args.command == 'import-legacy':
        from db.import_legacy import import_legacy
        result = import_legacy(args.root,args.snapshot)
    elif args.command == 'migrate':
        from db.migrate import migrate
        result = migrate(args.root)
    elif args.command == 'status':
        from db.connection import raw_connect, backend
        with raw_connect(args.root) as conn:
            result = {'backend': backend(args.root), 'postgres_version': conn.execute('SELECT version()').fetchone()[0]}
    elif args.command == 'backup':
        result = {'backup': str(make_backup(args.root))}
    elif args.command == 'verify-backup':
        result = verify_backup(args.path)
    else:
        result = restore_backup(args.path, args.destination)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
