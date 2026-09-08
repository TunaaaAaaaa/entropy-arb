import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { canonicalUrl, extractArticle, extractPost } from '../extract.mjs';
import { crawlUrls, readCache } from '../engine.mjs';

const paragraph = 'Protocol settlement waits for confirmation. Fees and withdrawal delays must be counted before evaluating any spread. ';
const html = `<html><head><title>Settlement rules</title><meta property="article:published_time" content="2026-09-08"></head><body><nav>MENU NOISE</nav><article><h1>Settlement rules</h1><p>${paragraph.repeat(8)}</p><p><a href="/rules">Details</a></p><script>steal()</script></article></body></html>`;

test('canonical URLs remove tracking, unify X links and reject credentials', () => {
  assert.equal(canonicalUrl('https://twitter.com/Web3Feng/status/123?s=20#x'), 'https://x.com/Web3Feng/status/123');
  assert.equal(canonicalUrl('https://example.com/a?utm_source=x&id=3#s'), 'https://example.com/a?id=3');
  assert.throws(() => canonicalUrl('file:///tmp/a'));
  assert.throws(() => canonicalUrl('https://user:pass@example.com'));
  assert.throws(() => canonicalUrl('https://x.com/Web3Feng'));
});

test('article extraction preserves evidence and drops script/navigation', () => {
  const d = extractArticle(html, 'https://example.com/article');
  assert.match(d.text, /withdrawal delays/);
  assert.doesNotMatch(d.text, /steal\(\)|MENU NOISE/);
  assert.match(d.markdown, /https:\/\/example.com\/rules/);
  assert.equal(d.published_at, '2026-09-08');
  assert.throws(() => extractArticle('<title>Just a moment...</title><main>wait</main>', 'https://example.com'));
  assert.throws(() => extractArticle('<html><body>Enable JavaScript</body></html>', 'https://example.com'));
});

test('X adapter verifies identity and labels mirror evidence', () => {
  const data = {code: 200, tweet: {id: '123', author: {screen_name: 'Web3Feng'}, text: '一条研究观点', created_at: 'Mon Sep 07 16:44:08 +0000 2026'}};
  const d = extractPost(JSON.stringify(data), 'https://x.com/Web3Feng/status/123');
  assert.equal(d.provenance, 'third-party-mirror');
  assert.equal(d.text, '一条研究观点');
  data.tweet.id = '456';
  assert.throws(() => extractPost(JSON.stringify(data), 'https://x.com/Web3Feng/status/123'));
});

test('real crawler: retries, partial failures, cache, force and evidence integrity', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'entropy-crawl-'));
  let calls = 0, retryCalls = 0;
  const server = http.createServer((req, res) => {
    if (req.url === '/fail') { res.writeHead(503); return res.end('unavailable'); }
    if (req.url === '/oversize') { res.writeHead(200, {'content-type': 'text/html'}); return res.end('x'.repeat(6 * 1024 * 1024)); }
    if (req.url === '/retry' && retryCalls++ === 0) { res.writeHead(503); return res.end('try again'); }
    calls++; res.writeHead(200, {'content-type': 'text/html; charset=utf-8'}); res.end(html);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const first = await crawlUrls([base + '/ok', base + '/retry', base + '/fail'], {root});
    assert.equal(first.results.filter(r => r.status === 'fetched').length, 2);
    assert.equal(first.results.filter(r => r.status === 'failed').length, 1);
    assert.equal(retryCalls, 2);
    const before = calls;
    const cached = await crawlUrls([base + '/ok'], {root});
    assert.equal(cached.results[0].status, 'cached'); assert.equal(calls, before);
    const forced = await crawlUrls([base + '/ok'], {root, force: true});
    assert.equal(forced.results[0].status, 'fetched'); assert.equal(calls, before + 1);
    assert.equal(readCache(root, base + '/ok', 0), null);
    const oversized = await crawlUrls([base + '/oversize'], {root});
    assert.equal(oversized.results[0].status, 'failed');
    assert.match(oversized.results[0].error, /5 MiB/);
    const doc = forced.results[0].document;
    fs.appendFileSync(path.join(root, doc.raw_path), 'tampered');
    assert.throws(() => readCache(root, base + '/ok', 24), /altered/);
  } finally {
    await new Promise(resolve => server.close(resolve));
    fs.rmSync(root, {recursive: true, force: true});
  }
});

test('empty queue is a successful no-op and active lock is not removed', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'entropy-lock-'));
  try {
    assert.deepEqual((await crawlUrls([], {root})).results, []);
    const lock = path.join(root, 'data/crawl/run.lock');
    fs.writeFileSync(lock, 'another process');
    await assert.rejects(crawlUrls([], {root}), /EEXIST/);
    assert.equal(fs.readFileSync(lock, 'utf8'), 'another process');
  } finally { fs.rmSync(root, {recursive: true, force: true}); }
});
