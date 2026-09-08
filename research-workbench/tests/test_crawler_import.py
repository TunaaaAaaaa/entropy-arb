import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from workbench import connect, add_item, review_item
spec = importlib.util.spec_from_file_location('crawler_import', ROOT / 'crawler/import_documents.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ImportTests(unittest.TestCase):
    def test_attach_preserves_manual_notes_and_review_failure_retains_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            db = connect(root)
            item, _ = add_item(db, 'manual title', 'https://example.com/a', 'my original analysis')
            review_item(db, item, 'shortlist', 'keep this review')
            db.close()
            doc = {'title': 'extracted title', 'text': 'extracted body', 'fetched_at': '2026-09-08T00:00:00Z',
                   'published_at': None, 'provenance': 'direct-http', 'document_path': 'data/crawl/documents/test.json', 'warnings': []}
            run = {'at': '2026-09-08T00:01:00Z', 'results': [{'url': 'https://example.com/a', 'status': 'fetched', 'document': doc}]}
            module.import_run(root, run)
            module.import_run(root, run)
            run['results'] = [{'url': 'https://example.com/a', 'status': 'failed', 'error': 'HTTP 503'}]
            module.import_run(root, run)
            db = connect(root)
            row = db.execute('SELECT * FROM items WHERE id=?', (item,)).fetchone()
            self.assertEqual(row['summary'], 'my original analysis')
            self.assertEqual(row['review_note'], 'keep this review')
            self.assertEqual(row['status'], 'shortlist')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM items').fetchone()[0], 1)
            state = db.execute('SELECT * FROM crawled_documents').fetchone()
            self.assertEqual(state['status'], 'failed')
            self.assertEqual(state['document_path'], doc['document_path'])
            db.close()
