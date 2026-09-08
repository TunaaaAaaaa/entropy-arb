from hashlib import sha256
from pathlib import Path
from db.connection import raw_connect


def migrate(root, database=None):
    applied = []
    with raw_connect(root, database=database) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(82641001)')
        conn.execute('CREATE TABLE IF NOT EXISTS public.schema_migrations(version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())')
        for file in sorted((Path(__file__).parent / 'migrations').glob('*.sql')):
            checksum = sha256(file.read_bytes()).hexdigest()
            old = conn.execute('SELECT checksum FROM public.schema_migrations WHERE version=%s', (file.name,)).fetchone()
            if old:
                if old[0] != checksum:
                    raise ValueError(f'Applied migration changed: {file.name}')
                continue
            conn.execute(file.read_text(encoding='utf8'))
            conn.execute('INSERT INTO public.schema_migrations(version,checksum) VALUES(%s,%s)', (file.name, checksum))
            applied.append(file.name)
    return {'applied': applied}
