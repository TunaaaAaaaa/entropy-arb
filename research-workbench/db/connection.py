"""PostgreSQL adapter for the existing parameterized inbox queries."""
import json
import os
from pathlib import Path
import re
from datetime import datetime
import psycopg

TABLES = {'sources': 'ops.sources', 'items': 'ops.inbox_items', 'revisions': 'ops.item_revisions',
          'reviews': 'ops.review_events', 'source_fetches': 'ops.source_fetches', 'crawled_documents': 'ops.crawled_documents'}


def settings(root):
    if os.environ.get('RESEARCH_DATABASE_URL'):
        return os.environ['RESEARCH_DATABASE_URL']
    file = Path(root) / 'data/local/postgres.json'
    if not file.exists():
        raise ValueError('PostgreSQL not configured; run npm run db:setup')
    return json.loads(file.read_text(encoding='utf8'))


def raw_connect(root, *, database=None):
    config = settings(root)
    if isinstance(config, str):
        return psycopg.connect(config, **({'dbname': database} if database else {}))
    if database:
        config['dbname'] = database
    return psycopg.connect(**config)


def backend(root):
    explicit = os.environ.get('RESEARCH_BACKEND')
    file = Path(root) / 'data/local/backend.json'
    choice = explicit or (json.loads(file.read_text())['backend'] if file.exists() else 'sqlite')
    if choice not in ('sqlite', 'postgres'):
        raise ValueError('Unknown research backend')
    return choice


class Row:
    def __init__(self, names, values):
        self.names = names
        self.values = tuple(v.isoformat(timespec='seconds') if isinstance(v, datetime) else v for v in values)
    def keys(self):
        return self.names
    def __getitem__(self, key):
        return self.values[key if isinstance(key, int) else self.names.index(key)]
    def __iter__(self):
        return iter(self.values)


class Cursor:
    def __init__(self, cursor, returning=False):
        self.cursor = cursor
        self.lastrowid = cursor.fetchone()[0] if returning else None
    def fetchone(self):
        value = self.cursor.fetchone()
        return None if value is None else Row([d.name for d in self.cursor.description], value)
    def fetchall(self):
        return list(self)
    def __iter__(self):
        while (value := self.fetchone()) is not None:
            yield value


class PgConnection:
    dialect = 'postgres'
    def __init__(self, root):
        self.root = Path(root).resolve()
        try:
            self.raw = raw_connect(root)
        except psycopg.Error:
            raise ValueError('Cannot connect to PostgreSQL; check local configuration and database health') from None
    def execute(self, sql, parameters=()):
        # Only this application's static, parameterized legacy queries pass here.
        sql = re.sub(r'\b(' + '|'.join(TABLES) + r')\b', lambda m: TABLES[m[0]], sql)
        ignore = 'INSERT OR IGNORE' in sql
        sql = sql.replace('INSERT OR IGNORE', 'INSERT')
        if ignore:
            sql += ' ON CONFLICT DO NOTHING'
        sql = sql.replace('baseline=0 OR ?', 'baseline=0 OR ?=1').replace('?', '%s')
        returning = bool(re.match(r'\s*INSERT INTO ops.inbox_items\(', sql)) and 'RETURNING' not in sql
        if returning:
            sql += ' RETURNING id'
        return Cursor(self.raw.execute(sql, tuple(int(v) if isinstance(v, bool) else v for v in parameters)), returning)
    def lock(self, identity):
        self.raw.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (identity,))
    def commit(self):
        self.raw.commit()
    def rollback(self):
        self.raw.rollback()
    def close(self):
        self.raw.close()
    def __enter__(self):
        return self
    def __exit__(self, kind, value, trace):
        self.raw.rollback() if kind else self.raw.commit()
