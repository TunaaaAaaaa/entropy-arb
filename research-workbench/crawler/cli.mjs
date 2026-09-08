import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { spawnSync } from 'node:child_process';
import { crawlUrls } from './engine.mjs';

try {
  const { values, positionals } = parseArgs({ allowPositionals: true, options: {
    file: { type: 'string' }, root: { type: 'string' }, force: { type: 'boolean', default: false },
    'ttl-hours': { type: 'string', default: '24' }, help: { type: 'boolean' },
    'inbox-limit': { type: 'string' },
  } });
  if (values.help) {
    console.log('npm run crawl -- URL [URL...] [--file urls.txt] [--inbox-limit 5] [--force] [--ttl-hours 24]\nOnly supplied/inbox URLs; no recursive crawling. Full evidence is local; stdout contains a compact receipt.');
  } else {
    const root = path.resolve(values.root || fileURLToPath(new URL('..', import.meta.url)));
    const urls = [...positionals];
    const bridge = fileURLToPath(new URL('import_documents.py', import.meta.url));
    if (values['inbox-limit']) {
      const queue = spawnSync(process.env.RESEARCH_PYTHON || 'python', [bridge, root, values['inbox-limit']],
        { encoding: 'utf8', env: { ...process.env, PYTHONUTF8: '1' } });
      if (queue.status !== 0) throw new Error(queue.stderr || 'Cannot read inbox');
      urls.push(...JSON.parse(queue.stdout));
    }
    if (values.file) urls.push(...fs.readFileSync(values.file, 'utf8').split(/\r?\n/).map(s => s.trim()).filter(s => s && !s.startsWith('#')));
    if (!urls.length && !values['inbox-limit']) throw new Error('Supply a URL, --file, or --inbox-limit');
    const run = await crawlUrls(urls, { root, force: values.force, ttlHours: Number(values['ttl-hours']) });
    const imported = spawnSync(process.env.RESEARCH_PYTHON || 'python', [bridge, root], {
      input: JSON.stringify(run), encoding: 'utf8', maxBuffer: 2 * 1024 * 1024,
      env: { ...process.env, PYTHONUTF8: '1' },
    });
    if (imported.status !== 0) throw new Error(imported.stderr || imported.error?.message || 'Database import failed; evidence remains in data/crawl/runs');
    console.log(imported.stdout.trim());
    process.exitCode = run.results.some(r => r.status === 'failed') ? 1 : 0;
  }
} catch (e) { console.error(e.message); process.exitCode = 2; }
