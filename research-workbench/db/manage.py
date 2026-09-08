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
    p = sub.add_parser('verify-backup'); p.add_argument('path')
    p = sub.add_parser('restore-backup'); p.add_argument('path'); p.add_argument('destination')
    args = parser.parse_args()
    if args.command == 'migrate':
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
