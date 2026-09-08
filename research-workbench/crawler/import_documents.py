"""Import crawler receipts via stdin; reuse the existing inbox and review history."""
import json
from pathlib import Path
import sys
from contextlib import closing

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench import connect, save_item, clean_text, normalize_date, report


def import_run(root, run):
    receipts = []
    with closing(connect(root)) as db:
        with db:
            db.execute("""INSERT OR IGNORE INTO sources(id,name,kind,url,enabled)
                          VALUES('manual-user','人工录入','manual','',1)""")
            for result in run['results']:
                url, status = result['url'], result['status']
                if status == 'failed':
                    db.execute("""INSERT INTO crawled_documents(url,last_attempt,status,error)
                                  VALUES(?,?,?,?) ON CONFLICT(url) DO UPDATE SET
                                  last_attempt=excluded.last_attempt,status=excluded.status,error=excluded.error""",
                               (url, run['at'], status, clean_text(result['error'], html=False)))
                    receipts.append({'url': url, 'status': status, 'error': result['error']})
                    continue
                doc = result['document']
                # Separate body evidence from manually saved notes/analysis: never replace an existing item's text.
                old = db.execute("SELECT id FROM items WHERE url=? ORDER BY CASE WHEN source_id='manual-user' THEN 0 ELSE 1 END,id LIMIT 1", (url,)).fetchone()
                if old:
                    item_id, change = old['id'], 'attached'
                else:
                    summary = f"[{doc['provenance']}] " + clean_text(doc['text'], html=False)
                    item_id, change = save_item(db, {'id': 'manual-user', 'kind': 'manual'},
                        {'identity': url, 'url': url, 'title': clean_text(doc['title'], html=False)[:1000],
                         'published_at': normalize_date(doc.get('published_at')), 'summary': summary}, doc['fetched_at'])
                db.execute("""INSERT INTO crawled_documents
                              (url,item_id,last_attempt,fetched_at,document_path,provenance,status,error)
                              VALUES(?,?,?,?,?,?,?,NULL) ON CONFLICT(url) DO UPDATE SET
                              item_id=excluded.item_id,last_attempt=excluded.last_attempt,
                              fetched_at=excluded.fetched_at,document_path=excluded.document_path,
                              provenance=excluded.provenance,status=excluded.status,error=NULL""",
                           (url, item_id, run['at'], doc['fetched_at'], doc['document_path'], doc['provenance'], status))
                receipts.append({'url': url, 'status': status, 'item_id': item_id, 'change': change,
                                 'title': doc['title'], 'characters': len(doc['text']),
                                 'document_path': doc['document_path'], 'warnings': doc['warnings']})
        report(db, root)
    return receipts


if __name__ == '__main__':
    root = Path(sys.argv[1]).resolve()
    if len(sys.argv) == 3:
        limit = int(sys.argv[2])
        if not 1 <= limit <= 50:
            raise ValueError('inbox-limit must be 1..50')
        with closing(connect(root)) as db:
            urls = [row[0] for row in db.execute("""SELECT DISTINCT i.url FROM items i
                LEFT JOIN crawled_documents d ON d.url=i.url
                WHERE i.baseline=0 AND i.status IN ('new','shortlist')
                AND d.document_path IS NULL ORDER BY i.updated_at DESC LIMIT ?""", (limit,))]
        print(json.dumps(urls))
    else:
        print(json.dumps(import_run(root, json.load(sys.stdin)), ensure_ascii=False, indent=2))
