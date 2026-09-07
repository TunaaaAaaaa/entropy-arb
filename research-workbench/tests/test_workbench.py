import importlib.util
import json
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "workbench.py"
spec = importlib.util.spec_from_file_location("workbench", SCRIPT)
wb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wb)

T0 = "2026-09-07T00:00:00+00:00"
T1 = "2026-09-08T00:00:00+00:00"
T2 = "2026-09-09T00:00:00+00:00"


class LinkTests(unittest.TestCase):
    def test_web_links_escape_source_markup(self):
        rendered = wb.md_link('[title]', 'https://example.com/a(b)<c>\n')
        self.assertIn('%28b%29%3Cc%3E%0A', rendered)
        self.assertTrue(rendered.startswith('[\\[title\\]]('))

    def test_non_web_and_credential_links_are_inert(self):
        for url in ['javascript:alert(1)', 'file:///secret', 'https://user:pass@example.com', '//example.com', 'https://[']:
            self.assertEqual(wb.md_link('source', url), 'source')


def source(sid="news", kind="feed"):
    return {"id": sid, "name": sid, "kind": kind,
            "url": "https://example.com/" + sid,
            "enabled": True, "tags": ["research"], "cadence_hours": 24}


def rss(entries):
    return ("<rss><channel>" + "".join(
        f"<item><guid>{identity}</guid><title>{title}</title><link>https://example.com/{identity}</link>"
        f"<description>{summary}</description><pubDate>Mon, 07 Sep 2026 00:00:00 GMT</pubDate></item>"
        for identity, title, summary in entries) + "</channel></rss>").encode()


class ParseTests(unittest.TestCase):
    def test_rss_cleans_html_and_normalizes_dates(self):
        payload = rss([("1", "News", "&lt;p&gt;Hello&lt;/p&gt;&lt;script&gt;secret()&lt;/script&gt;")])
        rows = wb.parse_feed(payload, "https://example.com/feed")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["identity"], "1")
        self.assertEqual(rows[0]["summary"], "Hello")
        self.assertEqual(rows[0]["published_at"], T0)

    def test_atom_uses_namespace_and_alternate_link(self):
        payload = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <id>tag:example,2026:1</id><title>Atom entry</title>
        <link rel="self" href="/api/1"/><link rel="alternate" href="/post/1"/>
        <summary type="html">&lt;p&gt;A &amp;amp; B&lt;/p&gt;</summary>
        <updated>2026-09-07T08:00:00+08:00</updated></entry></feed>'''
        row = wb.parse_feed(payload, "https://example.com/feed")[0]
        self.assertEqual(row["url"], "https://example.com/post/1")
        self.assertEqual(row["identity"], "tag:example,2026:1")
        self.assertEqual(row["summary"], "A & B")
        self.assertEqual(row["published_at"], T0)

    def test_rejects_html_error_page_entities_and_oversize(self):
        for payload in (b"<html><body>Login</body></html>",
                        b'<!DOCTYPE rss [<!ENTITY x "test">]><rss/>', b"x" * (wb.MAX_BYTES + 1)):
            with self.subTest(payload=payload[:60]):
                with self.assertRaises(ValueError):
                    wb.parse_feed(payload, "https://example.com/feed")

    def test_visible_text_hides_scripts_and_style(self):
        self.assertEqual(wb.clean_text("<h1>Title</h1><style>body{}</style><script>alert(1)</script><p>Body</p>"),
                         "Title Body")

    def test_date_without_timezone_is_not_silently_utc(self):
        self.assertEqual(wb.normalize_date("2026-09-07T08:00:00"),
                         "2026-09-07T08:00:00 [timezone unspecified]")
        self.assertEqual(wb.normalize_date("7 Sep 2026 08:00:00"),
                         "7 Sep 2026 08:00:00 [timezone unspecified]")


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = wb.connect(self.root)
        self.sources = [source()]

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def collect(self, entries, now=T0, force=False):
        return wb.collect(self.db, self.sources, now=now, force=force,
                          fetcher=lambda url: (rss(entries), "utf-8"))

    def test_baseline_dedup_then_new_and_changed(self):
        first = self.collect([("1", "Old", "Original")])
        self.assertEqual(first[0]["baseline"], 1)
        self.assertEqual(wb.inbox(self.db), [])
        self.assertEqual(len(wb.inbox(self.db, include_baseline=True)), 1)
        second = self.collect([("1", "Old", "Original")], T1)
        self.assertEqual(second[0]["unchanged"], 1)
        third = self.collect([("1", "Old", "Revised"), ("2", "New", "New content")], T2)
        self.assertEqual(third[0]["changed"], 1)
        self.assertEqual(third[0]["new"], 1)
        self.assertEqual(len(wb.inbox(self.db)), 2)
        old = self.db.execute("SELECT * FROM items WHERE identity='1'").fetchone()
        self.assertEqual(old["observed_at"], T0)
        self.assertEqual(old["updated_at"], T2)
        self.assertEqual(old["baseline"], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM revisions").fetchone()[0], 3)

    def test_review_survives_change_and_note_is_preserved_if_omitted(self):
        self.collect([("1", "Original", "Text")])
        item_id = self.db.execute("SELECT id FROM items").fetchone()[0]
        wb.review_item(self.db, item_id, "archive", "已核实，无优势", now=T0)
        self.collect([("1", "Updated", "Changed")], T1)
        row = self.db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        self.assertEqual(row["status"], "archive")
        self.assertEqual(row["review_note"], "已核实，无优势")
        self.assertEqual(wb.inbox(self.db), [])
        wb.review_item(self.db, item_id, "shortlist", now=T2)
        row = self.db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        self.assertEqual(row["review_note"], "已核实，无优势")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM reviews").fetchone()[0], 2)

    def test_single_source_failure_does_not_stop_others(self):
        sources = [source("bad"), source("good"), source("social", "manual")]
        def fake_fetch(url):
            if url.endswith("bad"):
                raise TimeoutError("timed out")
            if url.endswith("social"):
                self.fail("manual source must never be fetched")
            return rss([("1", "Good", "Body")]), "utf-8"
        results = wb.collect(self.db, sources, now=T0, fetcher=fake_fetch)
        self.assertEqual([r["status"] for r in results], ["failed", "ok", "manual"])
        failed = self.db.execute("SELECT * FROM sources WHERE id='bad'").fetchone()
        self.assertEqual(failed["last_checked"], T0)
        self.assertIsNone(failed["last_success"])
        self.assertIsNone(failed["initialized_at"])
        self.assertIn("TimeoutError", failed["error"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM items").fetchone()[0], 1)

    def test_failure_retains_previous_success_and_recovery_clears_error(self):
        self.collect([("1", "Old", "Body")])
        def fail(url):
            raise OSError("offline")
        wb.collect(self.db, self.sources, now=T1, fetcher=fail)
        state = self.db.execute("SELECT * FROM sources").fetchone()
        self.assertEqual(state["last_success"], T0)
        self.assertEqual(state["last_checked"], T1)
        self.assertIn("offline", state["error"])
        self.collect([("1", "Old", "Body")], T2)
        state = self.db.execute("SELECT * FROM sources").fetchone()
        self.assertIsNone(state["error"])
        self.assertEqual(state["last_success"], T2)

    def test_cadence_and_force(self):
        self.collect([("1", "Old", "Body")])
        def must_not_fetch(url):
            self.fail("source is not due")
        result = wb.collect(self.db, self.sources, now="2026-09-07T01:00:00+00:00", fetcher=must_not_fetch)
        self.assertEqual(result[0]["status"], "not_due")
        forced = self.collect([("1", "New", "Body")], "2026-09-07T01:00:00+00:00", force=True)
        self.assertEqual(forced[0]["changed"], 1)

    def test_page_baseline_and_static_text_changes(self):
        sources = [source("page", "page")]
        for now, body in [(T0, b"<h1>Page</h1><script>one()</script><p>Rule A</p>"),
                          (T1, b"<h1>Page</h1><script>two()</script><p>Rule A</p>"),
                          (T2, b"<h1>Page</h1><p>Rule B</p>")]:
            result = wb.collect(self.db, sources, now=now, fetcher=lambda url: (body, "utf-8"))
            expected = {T0: "baseline", T1: "unchanged", T2: "changed"}[now]
            self.assertEqual(result[0][expected], 1)
        self.assertEqual(wb.inbox(self.db)[0]["summary"], "Page Rule B")

    def test_manual_add_is_immediately_reviewable_and_deduplicated(self):
        item_id, change = wb.add_item(self.db, "Case", "https://example.com/case", "Hypothesis", now=T0)
        self.assertEqual(change, "new")
        self.assertEqual(len(wb.inbox(self.db)), 1)
        same_id, change = wb.add_item(self.db, "Case", "https://example.com/case", "Hypothesis", now=T1)
        self.assertEqual((same_id, change), (item_id, "unchanged"))
        with self.assertRaises(ValueError):
            wb.add_item(self.db, "Bad", "javascript:alert(1)", "")

    def test_report_coverage_failure_manual_and_untrusted_markup(self):
        sources = [source("bad"), source("social", "manual"), source("good", "page")]
        def fake_fetch(url):
            if url.endswith("bad"):
                raise OSError("network unavailable")
            return b"<h1>Page</h1><p>Baseline only</p>", "utf-8"
        wb.collect(self.db, sources, now=T0, fetcher=fake_fetch)
        item_id, _ = wb.add_item(self.db, "[bait](javascript:bad) <img src=x>",
                                "https://example.com/case", "# injected\n<script>x</script>", now=T0)
        wb.review_item(self.db, item_id, "shortlist", "|bad|", now=T1)
        output = wb.report(self.db, self.root, now=T2).read_text(encoding="utf-8")
        self.assertIn("不是交易信号", output)
        self.assertIn("必须人工查看的来源", output)
        self.assertIn("network unavailable", output)
        self.assertIn("不能视为没有新消息", output)
        self.assertIn("最近成功 UTC", output)
        self.assertIn("当前基线条目=1", output)
        self.assertNotIn("<img", output)
        self.assertNotIn("[bait](javascript:bad)", output)
        self.assertNotIn("<script>", output)
        self.assertIn("\\|bad\\|", output)

    def test_source_url_change_resets_baseline_and_removed_source_disabled(self):
        self.collect([("1", "Old", "Body")])
        self.sources[0]["url"] = "https://example.com/replacement"
        result = self.collect([("2", "Other", "Content")], T1)
        self.assertEqual(result[0]["baseline"], 1)
        wb.sync_sources(self.db, [])
        self.assertEqual(self.db.execute("SELECT enabled FROM sources WHERE id='news'").fetchone()[0], 0)

    def test_snapshots_preserve_bytes_dedup_and_record_each_observation(self):
        entries = [("1", "Case", "&lt;p&gt;Original HTML&lt;/p&gt;")]
        payload = rss(entries)
        self.collect(entries, T0)
        self.collect(entries, T1)
        rows = self.db.execute("SELECT * FROM source_fetches ORDER BY id").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual([row["observed_at"] for row in rows], [T0, T1])
        self.assertEqual(rows[0]["relative_path"], rows[1]["relative_path"])
        self.assertEqual(rows[0]["content_hash"], sha256(payload).hexdigest())
        self.assertEqual((self.root / rows[0]["relative_path"]).read_bytes(), payload)
        self.assertEqual(len(list((self.root / "data" / "snapshots").glob("*.bin"))), 1)
        report = wb.report(self.db, self.root).read_text(encoding="utf-8")
        self.assertIn(rows[0]["content_hash"], report)
        self.assertIn("timezone unspecified", report)

    def test_corrupted_snapshot_is_reported_as_failure(self):
        entries = [("1", "Case", "Body")]
        self.collect(entries, T0)
        stored = self.db.execute("SELECT relative_path FROM source_fetches").fetchone()[0]
        (self.root / stored).write_bytes(b"modified externally")
        result = self.collect(entries, T1)
        self.assertEqual(result[0]["status"], "failed")
        self.assertIn("snapshot has been altered", result[0]["error"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM source_fetches").fetchone()[0], 1)

    def test_load_sources_rejects_invalid_config(self):
        path = self.root / "sources.json"
        path.write_text(json.dumps({"sources": [source()]}), encoding="utf-8")
        self.assertEqual(wb.load_sources(self.root)[0]["id"], "news")
        for sources in ([source(), source()], [{**source(), "url": "file:///etc/passwd"}],
                        [{**source(), "cadence_hours": 0}], [{**source(), "enabled": "false"}]):
            path.write_text(json.dumps({"sources": sources}), encoding="utf-8")
            with self.assertRaises(ValueError):
                wb.load_sources(self.root)


if __name__ == "__main__":
    unittest.main()
