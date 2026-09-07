#!/usr/bin/env python3
"""Public-information research inbox. Standard library only; no trading actions."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
import sys
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

DEFAULT_ROOT = Path(__file__).resolve().parent
MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 15
MAX_ENTRIES = 500
SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, url TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 1, tags TEXT NOT NULL DEFAULT '[]',
 cadence_hours REAL NOT NULL DEFAULT 24, initialized_at TEXT,
 last_checked TEXT, last_success TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS items (
 id INTEGER PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
 source_kind TEXT NOT NULL, identity TEXT NOT NULL, title TEXT NOT NULL,
 url TEXT NOT NULL, published_at TEXT, observed_at TEXT NOT NULL,
 updated_at TEXT NOT NULL, summary TEXT NOT NULL, content_hash TEXT NOT NULL,
 baseline INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','shortlist','archive')),
 review_note TEXT NOT NULL DEFAULT '', reviewed_at TEXT,
 UNIQUE(source_id, identity)
);
CREATE TABLE IF NOT EXISTS revisions (
 id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES items(id),
 observed_at TEXT NOT NULL, change_kind TEXT NOT NULL,
 title TEXT NOT NULL, url TEXT NOT NULL, published_at TEXT, summary TEXT NOT NULL,
 content_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
 id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES items(id),
 reviewed_at TEXT NOT NULL, old_status TEXT NOT NULL, new_status TEXT NOT NULL,
 note TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_fetches (
 id INTEGER PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
 observed_at TEXT NOT NULL, content_hash TEXT NOT NULL,
 relative_path TEXT NOT NULL, charset TEXT NOT NULL
);
"""


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(root):
    root = Path(root).resolve()
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "reports").mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "data" / "research.db")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    return db


class VisibleHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden.append(tag)
        elif not self.hidden:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if self.hidden and tag == self.hidden[-1]:
            self.hidden.pop()
        elif not self.hidden:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def clean_text(value, *, html=True):
    if html:
        parser = VisibleHTML()
        parser.feed(value or "")
        value = " ".join(parser.parts)
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value or "")
    return " ".join(value.split())


def web_url(value, base=""):
    value = urljoin(base, (value or "").strip())
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return ""
        if parsed.username is not None or parsed.password is not None:
            return ""
        return value[:4096]
    except ValueError:
        return ""


def normalize_date(value):
    value = clean_text(value, html=False)
    if not value:
        return None
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return value[:100]
    if date.tzinfo is None:
        return value[:100] + " [timezone unspecified]"
    return date.astimezone(timezone.utc).isoformat(timespec="seconds")


def local_name(node):
    return node.tag.rsplit("}", 1)[-1].lower()


def child(node, *names):
    return next((n for n in node if local_name(n) in names), None)


def node_text(node):
    return "" if node is None else "".join(node.itertext())


def parse_feed(payload, base_url):
    if len(payload) > MAX_BYTES:
        raise ValueError("feed exceeds 2 MiB limit")
    # Feeds need no DTD; reject entity definitions rather than expanding them.
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", payload, re.I):
        raise ValueError("DTD/entity declarations are not accepted")
    root = ET.fromstring(payload)
    if local_name(root) not in {"rss", "feed", "rdf"}:
        raise ValueError("response is not RSS/Atom")
    entries = [n for n in root.iter() if local_name(n) in {"item", "entry"}]
    result = []
    for entry in entries[:MAX_ENTRIES]:
        title = clean_text(node_text(child(entry, "title")))[:1000] or "Untitled"
        link = ""
        for element in entry:
            if local_name(element) == "link":
                candidate = element.attrib.get("href", node_text(element))
                if element.attrib.get("rel", "alternate") == "alternate":
                    link = web_url(candidate, base_url)
                    if link:
                        break
        identity = node_text(child(entry, "guid", "id")).strip() or link
        identity = identity or "title:" + sha256(title.encode()).hexdigest()
        description = child(entry, "encoded", "content", "description", "summary")
        summary = clean_text(node_text(description))
        result.append({"identity": identity[:4096], "title": title,
                       "url": link or base_url,
                       "published_at": normalize_date(node_text(child(
                           entry, "published", "pubdate", "date", "updated"))),
                       "summary": summary})
    return result


def fetch(url):
    if not web_url(url):
        raise ValueError("source URL must be HTTP(S), without credentials")
    request = Request(url, headers={"User-Agent": "ResearchWorkbench/1.0 (public research)",
                                    "Accept": "application/atom+xml, application/rss+xml, text/html, */*;q=0.1"})
    with urlopen(request, timeout=TIMEOUT) as response:
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_BYTES:
            raise ValueError("response exceeds 2 MiB limit")
        payload = response.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            raise ValueError("response exceeds 2 MiB limit")
        charset = response.headers.get_content_charset() or "utf-8"
        return payload, charset


def load_sources(root):
    path = Path(root) / "sources.json"
    if not path.exists():
        raise ValueError(f"missing source configuration: {path}")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        raise ValueError("sources.json must contain a sources array")
    result, seen = [], set()
    for raw in data["sources"]:
        if not isinstance(raw, dict):
            raise ValueError("every source must be an object")
        source = dict(raw)
        sid = source.get("id")
        if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", sid):
            raise ValueError("source id must use 1–100 ASCII letters, digits, _, . or -")
        if sid in seen or sid == "manual-user":
            raise ValueError(f"duplicate or reserved source id: {sid}")
        seen.add(sid)
        if source.get("kind") not in {"feed", "page", "manual"}:
            raise ValueError(f"invalid kind: {sid}")
        source["name"] = str(source.get("name") or sid)
        source["url"] = str(source.get("url") or "")
        if source["kind"] != "manual" and not web_url(source["url"]):
            raise ValueError(f"invalid HTTP(S) URL: {sid}")
        source["enabled"] = source.get("enabled", True)
        if not isinstance(source["enabled"], bool):
            raise ValueError(f"enabled must be boolean: {sid}")
        source["tags"] = source.get("tags", [])
        if not isinstance(source["tags"], list) or not all(isinstance(t, str) for t in source["tags"]):
            raise ValueError(f"tags must be a string array: {sid}")
        source["cadence_hours"] = float(source.get("cadence_hours", 24))
        if not 0 < source["cadence_hours"] <= 8760:
            raise ValueError(f"cadence_hours must be > 0 and <= 8760: {sid}")
        result.append(source)
    return result


def sync_sources(db, sources):
    db.execute("UPDATE sources SET enabled=0 WHERE id != 'manual-user'")
    for source in sources:
        previous = db.execute("SELECT kind,url FROM sources WHERE id=?", (source["id"],)).fetchone()
        db.execute("""INSERT INTO sources(id,name,kind,url,enabled,tags,cadence_hours)
                    VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,kind=excluded.kind,url=excluded.url,
                    enabled=excluded.enabled,tags=excluded.tags,cadence_hours=excluded.cadence_hours""",
                   (source["id"], source["name"], source["kind"], source["url"],
                    source["enabled"], json.dumps(source["tags"], ensure_ascii=False), source["cadence_hours"]))
        if previous and (previous["kind"] != source["kind"] or previous["url"] != source["url"]):
            db.execute("""UPDATE sources SET initialized_at=NULL,last_checked=NULL,
                        last_success=NULL,error=NULL WHERE id=?""", (source["id"],))
    db.commit()


def save_item(db, source, entry, observed_at, baseline=False):
    packed = json.dumps({k: entry.get(k) for k in ("title", "url", "published_at", "summary")},
                        ensure_ascii=False, sort_keys=True)
    digest = sha256(packed.encode()).hexdigest()
    old = db.execute("SELECT * FROM items WHERE source_id=? AND identity=?",
                     (source["id"], entry["identity"])).fetchone()
    if old and old["content_hash"] == digest:
        return old["id"], "unchanged"
    values = (entry["title"], entry["url"], entry.get("published_at"), observed_at,
              entry["summary"][:12000], digest, int(baseline))
    if old:
        item_id, change = old["id"], "changed"
        db.execute("""UPDATE items SET title=?,url=?,published_at=?,updated_at=?,summary=?,
                    content_hash=?,baseline=? WHERE id=?""", (*values, item_id))
    else:
        change = "baseline" if baseline else "new"
        cursor = db.execute("""INSERT INTO items(source_id,source_kind,identity,observed_at,
                            title,url,published_at,updated_at,summary,content_hash,baseline)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                            (source["id"], source["kind"], entry["identity"], observed_at, *values))
        item_id = cursor.lastrowid
    db.execute("""INSERT INTO revisions(item_id,observed_at,change_kind,title,url,published_at,
                summary,content_hash) VALUES(?,?,?,?,?,?,?,?)""",
               (item_id, observed_at, "baseline" if baseline else change, entry["title"], entry["url"],
                entry.get("published_at"), entry["summary"][:12000], digest))
    return item_id, "baseline" if baseline else change


def save_snapshot(db, source_id, payload, charset, observed_at):
    digest = sha256(payload).hexdigest()
    db_file = next(row[2] for row in db.execute("PRAGMA database_list") if row[1] == "main")
    root = Path(db_file).resolve().parent.parent
    relative = Path("data") / "snapshots" / (digest + ".bin")
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        temporary = destination.with_suffix(".tmp")
        temporary.write_bytes(payload)
        temporary.replace(destination)
    elif sha256(destination.read_bytes()).hexdigest() != digest:
        raise ValueError(f"existing snapshot has been altered: {relative.as_posix()}")
    db.execute("""INSERT INTO source_fetches(source_id,observed_at,content_hash,relative_path,charset)
                VALUES(?,?,?,?,?)""", (source_id, observed_at, digest, relative.as_posix(), charset))


def collect(db, sources, *, force=False, fetcher=fetch, now=None):
    now = now or utcnow()
    sync_sources(db, sources)
    outcomes = []
    for source in sources:
        sid = source["id"]
        state = db.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone()
        if not source["enabled"] or source["kind"] == "manual":
            outcomes.append({"id": sid, "status": "disabled" if not source["enabled"] else "manual"})
            continue
        if not force and state["last_checked"]:
            due = datetime.fromisoformat(state["last_checked"]) + timedelta(hours=source["cadence_hours"])
            if datetime.fromisoformat(now) < due:
                outcomes.append({"id": sid, "status": "not_due", "previous_error": state["error"]})
                continue
        try:
            payload, charset = fetcher(source["url"])
            if len(payload) > MAX_BYTES:
                raise ValueError("response exceeds 2 MiB limit")
            if source["kind"] == "feed":
                entries = parse_feed(payload, source["url"])
            else:
                content = clean_text(payload.decode(charset, errors="replace"))
                if not content:
                    raise ValueError("page has no readable text; may require JavaScript/manual review")
                entries = [{"identity": source["url"], "title": source["name"], "url": source["url"],
                            "summary": content, "published_at": None}]
            baseline = state["initialized_at"] is None
            counts = {"baseline": 0, "new": 0, "changed": 0, "unchanged": 0}
            with db:
                save_snapshot(db, sid, payload, charset, now)
                for entry in entries:
                    _, change = save_item(db, source, entry, now, baseline=baseline)
                    counts[change] += 1
                db.execute("""UPDATE sources SET last_checked=?,last_success=?,error=NULL,
                            initialized_at=COALESCE(initialized_at,?) WHERE id=?""", (now, now, now, sid))
            outcomes.append({"id": sid, "status": "ok", **counts})
        except Exception as error:
            message = clean_text(f"{type(error).__name__}: {error}", html=False)[:1000]
            with db:
                db.execute("UPDATE sources SET last_checked=?,error=? WHERE id=?", (now, message, sid))
            outcomes.append({"id": sid, "status": "failed", "error": message})
    return outcomes


def add_item(db, title, url, note, now=None):
    now = now or utcnow()
    url = web_url(url)
    if not url:
        raise ValueError("--url must be an HTTP(S) URL without credentials")
    title = clean_text(title, html=False)[:1000]
    if not title:
        raise ValueError("title must not be empty")
    source = {"id": "manual-user", "kind": "manual"}
    with db:
        db.execute("""INSERT OR IGNORE INTO sources(id,name,kind,url,enabled)
                    VALUES('manual-user','人工录入','manual','',1)""")
        result = save_item(db, source, {"identity": url, "title": title, "url": url,
                          "summary": clean_text(note, html=False), "published_at": None}, now)
    return result


def review_item(db, item_id, status, note=None, now=None):
    if status not in {"new", "shortlist", "archive"}:
        raise ValueError("invalid review status")
    now = now or utcnow()
    row = db.execute("SELECT status,review_note FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        raise ValueError(f"item {item_id} does not exist")
    note = row["review_note"] if note is None else clean_text(note, html=False)
    with db:
        db.execute("UPDATE items SET status=?,review_note=?,reviewed_at=? WHERE id=?", (status, note, now, item_id))
        db.execute("INSERT INTO reviews(item_id,reviewed_at,old_status,new_status,note) VALUES(?,?,?,?,?)",
                   (item_id, now, row["status"], status, note))


def inbox(db, limit=20, include_baseline=False):
    return db.execute("""SELECT * FROM items WHERE status='new' AND (baseline=0 OR ?)
                      ORDER BY updated_at DESC,id DESC LIMIT ?""", (int(include_baseline), limit)).fetchall()


def md(value, limit=1500):
    # No active Markdown/HTML from scraped titles, URLs, notes, or summaries.
    value = clean_text(str(value or ""), html=False)[:limit]
    value = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([\\`*_{}\[\]()#+.!|~\-])", r"\\\1", value)


def md_link(label, url):
    """Render only ordinary public web links; keep source markup inert."""
    label = md(label, 500)
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            return label
        target = quote(url, safe=":/?#[]@!$&'*+,;=%~.-_")
    except (ValueError, TypeError):
        return label
    return f"[{label}]({target})"


def report(db, root, now=None):
    now = now or utcnow()
    lines = ["## 机制研究收件箱", f"生成时间（UTC）：{md(now)}",
             "以下都是待人工验证的研究线索，不是交易信号；本工具不连接钱包、不下单、不执行来源内容。",
             "## 自动覆盖范围与来源健康",
             "feed：当前公开 RSS/Atom 返回的至多 500 条；page：静态可读文本变更，不运行 JavaScript。首次成功抓取仅建立基线。",
             "无法保证覆盖历史全文、已删除内容、付费/登录页面、社交平台动态与所有公告。网页模板变化也可能产生线索。",
             "发布时间来自来源自身；timezone unspecified 表示原文未提供时区，不能据此认定 UTC 时间或精确事件先后。",
             "没有新条目不代表没有事件；未到采集时间或抓取失败时，覆盖不完整。",
             "| 来源 | 类型/状态 | 最近检查 UTC | 最近成功 UTC | 最近错误 |",
             "|---|---|---|---|---|"]
    source_rows = db.execute("SELECT * FROM sources ORDER BY id").fetchall()
    for s in source_rows:
        state = "启用" if s["enabled"] else "禁用/已移除"
        lines.append(f"| {md_link(s['name'],s['url'])} ({md(s['id'],100)}) | {md(s['kind'])}/{state} | "
                     f"{md(s['last_checked'] or '未检查')} | {md(s['last_success'] or '未成功')} | {md(s['error'] or '无已记录错误',500)} |")
    if not source_rows:
        lines.append("| 尚无来源记录，请先 collect | — | — | — | — |")
    lines += ["## 原始来源快照",
              "每次成功解析的公开 feed/page 响应按 SHA256 保存到 data/snapshots/<hash>.bin；相同字节只存一份，source_fetches 保存每次观察时间。",
              "快照仅证明本工具当时观察到的响应内容；feed 摘要不等于文章全文，不额外抓取每篇文章。原始字节只作证据数据，不执行。"]
    snapshots = db.execute("""SELECT f.* FROM source_fetches f JOIN
                              (SELECT source_id,MAX(id) latest FROM source_fetches GROUP BY source_id) x
                              ON f.id=x.latest ORDER BY f.source_id""").fetchall()
    lines += [f"- {md(s['source_id'])}；{md(s['observed_at'])}；{md(s['relative_path'],500)}；字符集：{md(s['charset'])}。" for s in snapshots] or ["暂无成功抓取的原始快照。"]
    lines.append("## 必须人工查看的来源")
    manual = [s for s in source_rows if s["kind"] == "manual" and s["enabled"]]
    for s in manual:
        lines.append(f"- {md_link(s['name'],s['url'])}；未自动抓取。")
    if not manual:
        lines.append("未配置人工来源；社交平台等自动覆盖盲区仍需自行查看。")
    failures = [s for s in source_rows if s["error"] and s["enabled"]]
    lines.append("## 失败来源")
    lines += [f"- {md(s['id'])}：{md(s['error'],500)}；不能视为没有新消息。" for s in failures] or ["当前启用来源没有已记录的抓取失败。"]
    counts = dict(db.execute("SELECT status,COUNT(*) FROM items GROUP BY status").fetchall())
    baseline_count = db.execute("SELECT COUNT(*) FROM items WHERE baseline=1").fetchone()[0]
    lines += ["## 审阅概况", f"new={counts.get('new',0)}；shortlist={counts.get('shortlist',0)}；archive={counts.get('archive',0)}；当前基线条目={baseline_count}。",
              "new 数量包含基线；基线默认不进入待研读清单，可用 inbox --include-baseline 查看。",
              "来源内容变化保留人工状态和审阅笔记；修订保存在 revisions，审阅历史保存在 reviews。",
              "## 待研读与候选"]
    rows = db.execute("""SELECT * FROM items WHERE status='shortlist' OR (status='new' AND baseline=0)
                         ORDER BY updated_at DESC,id DESC LIMIT 100""").fetchall()
    if not rows:
        lines.append("暂无待研读的新线索；请同时检查上面的覆盖范围、失败来源和人工来源。")
    for row in rows:
        lines += [f"### [{row['id']}] {md(row['title'],500)}",
                  f"状态：{row['status']}；来源：{md(row['source_id'])} ({row['source_kind']})；当前内容基线：{'是' if row['baseline'] else '否'}",
                  f"首次观察 UTC：{md(row['observed_at'])}；最近内容变更 UTC：{md(row['updated_at'])}；来源发布时间：{md(row['published_at'] or '未知')}",
                  f"原始来源：{md_link('查看原文',row['url'])}",
                  f"摘要：{md(row['summary'],1500)}",
                  f"人工笔记：{md(row['review_note'],1500) or '待填写：错误假设、收益来源、可反证条件、结算路径。'}"]
    changes = db.execute("""SELECT r.*,i.status FROM revisions r JOIN items i ON i.id=r.item_id
                            WHERE r.change_kind='changed' ORDER BY r.id DESC LIMIT 30""").fetchall()
    lines.append("## 最近内容修订（含已归档条目）")
    lines += [f"- [{r['item_id']}] {md(r['title'],300)}；{md(r['observed_at'])}；保留状态：{r['status']}；修订号：{r['id']}。" for r in changes] or ["暂无非基线修订。"]
    path = Path(root).resolve() / "reports" / "latest.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create the local database and output directories")
    p = sub.add_parser("collect", help="collect configured public sources")
    p.add_argument("--force", action="store_true", help="ignore cadence; failed sources are otherwise retried at cadence")
    p = sub.add_parser("add", help="manually save a public research reference")
    p.add_argument("--title", required=True)
    p.add_argument("--url", required=True)
    p.add_argument("--note", default="")
    p = sub.add_parser("inbox", help="show unreviewed observations")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--include-baseline", action="store_true")
    p = sub.add_parser("review", help="record a human research decision")
    p.add_argument("id", type=int)
    p.add_argument("--status", choices=("shortlist", "archive", "new"), required=True)
    p.add_argument("--note", default=None)
    sub.add_parser("report", help="write reports/latest.md")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        with closing(connect(root)) as db:
            if args.command == "init":
                print(f"Initialized: {root / 'data' / 'research.db'}")
            elif args.command == "collect":
                outcomes = collect(db, load_sources(root), force=args.force)
                for outcome in outcomes:
                    print(json.dumps(outcome, ensure_ascii=False))
                return 1 if any(o["status"] == "failed" for o in outcomes) else 0
            elif args.command == "add":
                item_id, change = add_item(db, args.title, args.url, args.note)
                print(f"Item {item_id}: {change}")
            elif args.command == "inbox":
                if not 1 <= args.limit <= 1000:
                    raise ValueError("--limit must be between 1 and 1000")
                for row in inbox(db, args.limit, args.include_baseline):
                    print(f"[{row['id']}] {row['status']} {'BASELINE ' if row['baseline'] else ''}{row['title']}\n  {row['url']}\n  {row['summary'][:300]}")
                print("Source health:")
                for s in db.execute("SELECT * FROM sources WHERE enabled=1 ORDER BY id"):
                    print(f"  {s['id']} [{s['kind']}] checked={s['last_checked'] or 'never'} success={s['last_success'] or 'never'} error={s['error'] or '-'}")
            elif args.command == "review":
                review_item(db, args.id, args.status, args.note)
                print(f"Item {args.id}: {args.status}")
            elif args.command == "report":
                # Synchronize configuration so the report shows manual/disabled coverage before collection.
                if (root / "sources.json").exists():
                    sync_sources(db, load_sources(root))
                print(report(db, root))
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
