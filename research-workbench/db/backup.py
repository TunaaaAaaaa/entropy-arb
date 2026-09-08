"""Evidence backups: immutable manifest, SQLite online backup, fresh-directory restore."""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from datetime import datetime, timezone


def digest(path):
    with Path(path).open('rb') as fh:
        return hashlib.file_digest(fh, 'sha256').hexdigest()


def sqlite_counts(file):
    with sqlite3.connect(Path(file).resolve().as_uri() + '?mode=ro', uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('SQLite integrity check failed')
        names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {name: db.execute('SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0] for name in names}


def make_backup(root):
    root = Path(root).resolve()
    if (root / 'data/crawl/run.lock').exists():
        raise ValueError('Crawler is running; stop writers before backup')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = root / 'data/backups' / stamp
    target.mkdir(parents=True)
    dest_db = target / 'files/research-workbench/data/research.db'
    dest_db.parent.mkdir(parents=True)
    with sqlite3.connect((root / 'data/research.db').as_uri() + '?mode=ro', uri=True) as source:
        with sqlite3.connect(dest_db) as dest:
            source.backup(dest)
    candidates = [root / 'sources.json']
    for folder in ['data/snapshots', 'data/crawl/raw', 'data/crawl/documents', 'data/crawl/runs', 'data/manual', 'cases', 'hypotheses', 'experiments']:
        candidates.extend(p for p in (root / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    candidates.extend((root.parent / 'logs').rglob('*.csv'))
    for source in candidates:
        if not source.exists():
            continue
        relative = source.relative_to(root.parent)
        dest = target / 'files' / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        before = digest(source)
        shutil.copy2(source, dest)
        if before != digest(dest) or before != digest(source):
            raise ValueError(f'File changed during backup: {relative}')
    files = {p.relative_to(target / 'files').as_posix(): digest(p) for p in (target / 'files').rglob('*') if p.is_file()}
    manifest = {'at': stamp, 'files': files, 'sqlite_counts': sqlite_counts(dest_db)}
    (target / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')
    verify_backup(target)
    return target


def verify_backup(target):
    target = Path(target).resolve()
    manifest = json.loads((target / 'manifest.json').read_text(encoding='utf8'))
    for relative, expected in manifest['files'].items():
        file = (target / 'files' / relative).resolve()
        if not file.is_relative_to(target / 'files') or not file.is_file() or digest(file) != expected:
            raise ValueError(f'Backup missing or altered: {relative}')
    counts = sqlite_counts(target / 'files/research-workbench/data/research.db')
    if counts != manifest['sqlite_counts']:
        raise ValueError('Backup counts differ')
    return {'files_verified': len(manifest['files']), 'sqlite_counts': counts}


def restore_backup(target, destination):
    target, destination = Path(target).resolve(), Path(destination).resolve()
    verify_backup(target)
    if destination.exists():
        raise ValueError('Restore destination must not exist')
    shutil.copytree(target / 'files', destination)
    manifest = json.loads((target / 'manifest.json').read_text(encoding='utf8'))
    for relative, expected in manifest['files'].items():
        if digest(destination / relative) != expected:
            raise ValueError(f'Restore mismatch: {relative}')
    return {'restored_to': str(destination), 'files_verified': len(manifest['files']),
            'sqlite_counts': sqlite_counts(destination / 'research-workbench/data/research.db')}
