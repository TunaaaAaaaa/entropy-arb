import fs from 'node:fs';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { CheerioCrawler } from '@crawlee/cheerio';
import { Configuration, GotScrapingHttpClient } from '@crawlee/core';
import { canonicalUrl, routeUrl, extractPost, extractArticle, EXTRACTOR_VERSION } from './extract.mjs';

const hash = value => createHash('sha256').update(value).digest('hex');
class BoundedHttpClient extends GotScrapingHttpClient {
  async stream(request, handleRedirect) {
    const response = await super.stream(request, handleRedirect);
    response.stream.on('downloadProgress', progress => {
      if (progress.transferred > 5 * 1024 * 1024)
        response.stream.destroy(new Error('Response exceeds 5 MiB'));
    });
    return response;
  }
}
export function readCache(root, url, ttlHours, now = Date.now()) {
  const file = path.join(root, 'data/crawl/cache', hash(url) + '.json');
  if (!fs.existsSync(file)) return null;
  const doc = JSON.parse(fs.readFileSync(file, 'utf8'));
  if (doc.url !== url || doc.extractor_version !== EXTRACTOR_VERSION ||
      !Number.isFinite(Date.parse(doc.fetched_at)) || now - Date.parse(doc.fetched_at) >= ttlHours * 3600000) return null;
  for (const [name, digest] of [[doc.raw_path, doc.raw_sha256], [doc.document_path, doc.document_sha256]]) {
    const resolved = path.resolve(root, name);
    if (!resolved.startsWith(path.resolve(root, 'data/crawl') + path.sep) ||
        hash(fs.readFileSync(resolved)) !== digest) throw new Error('Cached evidence missing or altered');
  }
  return doc;
}

function writeEvidence(root, url, fetchedUrl, payload, content, status) {
  const rawHash = hash(payload);
  const data = { ...content, url, fetched_url: fetchedUrl, fetched_at: new Date().toISOString(),
    http_status: status, extractor_version: EXTRACTOR_VERSION, raw_sha256: rawHash,
    snapshot_format: 'Crawlee response body; HTML may be decoded/re-encoded, not wire bytes',
    raw_path: `data/crawl/raw/${rawHash}.bin` };
  const bytes = JSON.stringify(data, null, 2);
  const documentHash = hash(bytes);
  const record = { ...data, document_sha256: documentHash,
    document_path: `data/crawl/documents/${documentHash}.json` };
  for (const [relative, value] of [[data.raw_path, payload], [record.document_path, bytes]]) {
    const file = path.join(root, relative); fs.mkdirSync(path.dirname(file), { recursive: true });
    if (fs.existsSync(file)) {
      if (hash(fs.readFileSync(file)) !== hash(value)) throw new Error('Existing evidence has been altered');
    } else fs.writeFileSync(file, value, { flag: 'wx' });
  }
  const file = path.join(root, 'data/crawl/cache', hash(url) + '.json');
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file + '.tmp', JSON.stringify(record)); fs.renameSync(file + '.tmp', file);
  return record;
}

export async function crawlUrls(inputs, { root, force = false, ttlHours = 24 } = {}) {
  if (!Number.isFinite(ttlHours) || ttlHours < 0) throw new Error('ttl-hours must be non-negative');
  if (inputs.length > 50) throw new Error('Supply at most 50 URLs per run');
  fs.mkdirSync(path.join(root, 'data/crawl'), { recursive: true });
  const lock = path.join(root, 'data/crawl/run.lock');
  const fd = fs.openSync(lock, 'wx');
  fs.writeFileSync(fd, JSON.stringify({ pid: process.pid, at: new Date().toISOString() }));
  const results = [];
  const runId = randomUUID();
  const startedAt = new Date().toISOString();
  const attempts = [];
  try {
    const pending = [];
    const seen = new Set();
    for (const input of inputs) {
      let url = input;
      try {
        url = canonicalUrl(input);
        if (seen.has(url)) continue;
        seen.add(url);
        const cached = !force && readCache(root, url, ttlHours);
        if (cached) { results.push({ status: 'cached', url, document: cached }); continue; }
        const route = routeUrl(url);
        pending.push({ url: route.fetchUrl, uniqueKey: url, userData: { original: url, adapter: route.adapter } });
      } catch (e) { results.push({ status: 'failed', url, error: e.message }); }
    }
    if (pending.length) {
      const crawler = new CheerioCrawler({
        maxConcurrency: 2, maxRequestRetries: 1, maxRequestsPerMinute: 30,
        maxRequestsPerCrawl: pending.length, requestHandlerTimeoutSecs: 40,
        navigationTimeoutSecs: 20, useSessionPool: false,
        httpClient: new BoundedHttpClient(),
        additionalMimeTypes: ['application/json'],
        preNavigationHooks: [async (_ctx, options) => {
          attempts.push({ id: randomUUID(), at: new Date().toISOString(), url: _ctx.request.userData.original,
            status: 'request-started', retry: _ctx.request.retryCount });
          options.headers = { ...options.headers, 'User-Agent': 'EntropyResearch/1.0 (public-document-research)' };
          options.retry = { limit: 0 };
        }],
        async requestHandler({ request, body, response, contentType }) {
          const payload = Buffer.isBuffer(body) ? body : Buffer.from(body);
          if (payload.length > 5 * 1024 * 1024) throw new Error('Response exceeds 5 MiB');
          const { original, adapter } = request.userData;
          if (adapter !== 'fxtwitter' && !['text/html', 'application/xhtml+xml'].includes(contentType.type))
            throw new Error('Only HTML articles and the X JSON adapter are supported');
          const text = typeof body === 'string' ? body : payload.toString(contentType.encoding || 'utf8');
          const content = adapter === 'fxtwitter' ? extractPost(text, original) : extractArticle(text, request.loadedUrl || request.url);
          const document = writeEvidence(root, original, request.loadedUrl || request.url, payload, content, response.statusCode);
          results.push({ status: 'fetched', url: original, document });
          attempts.push({ id: randomUUID(), at: new Date().toISOString(), url: original, status: 'request-succeeded' });
        },
        async errorHandler({ request }, error) {
          attempts.push({ id: randomUUID(), at: new Date().toISOString(), url: request.userData.original,
            status: 'request-error', error: error.message.slice(0, 1000), retry: request.retryCount });
        },
        async failedRequestHandler({ request }, error) {
          attempts.push({ id: randomUUID(), at: new Date().toISOString(), url: request.userData.original,
            status: 'request-failed', error: error.message.slice(0, 1000), retry: request.retryCount });
          results.push({ status: 'failed', url: request.userData.original, error: error.message.slice(0, 1000) });
        },
      }, new Configuration({ persistStorage: false, purgeOnStart: true, logLevel: 'OFF' }));
      await crawler.run(pending);
    }
    const run = { id: runId, started_at: startedAt, at: new Date().toISOString(), attempts, results };
    const dir = path.join(root, 'data/crawl/runs'); fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, run.id + '.json'), JSON.stringify(run, null, 2));
    return run;
  } finally { fs.closeSync(fd); fs.unlinkSync(lock); }
}
