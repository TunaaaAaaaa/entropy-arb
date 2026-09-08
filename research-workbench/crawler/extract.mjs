import { Readability } from '@mozilla/readability';
import { parseHTML } from 'linkedom';
import TurndownService from 'turndown';

export const EXTRACTOR_VERSION = 1;
export function canonicalUrl(value) {
  const u = new URL(value);
  if (!['http:', 'https:'].includes(u.protocol) || u.username || u.password)
    throw new Error('Only HTTP(S) URLs without credentials are accepted');
  u.hash = '';
  for (const key of [...u.searchParams.keys()])
    if (/^(utm_.+|fbclid|gclid)$/.test(key)) u.searchParams.delete(key);
  if (['x.com', 'www.x.com', 'twitter.com', 'www.twitter.com', 'mobile.twitter.com'].includes(u.hostname)) {
    const match = u.pathname.match(/^\/([\w]+)\/status\/(\d+)\/?$/);
    if (!match) throw new Error('X input must be a single public status URL');
    return `https://x.com/${match[1]}/status/${match[2]}`;
  }
  return u.href;
}

export function routeUrl(url) {
  const u = new URL(url);
  return u.hostname === 'x.com'
    ? { fetchUrl: `https://api.fxtwitter.com${u.pathname}`, adapter: 'fxtwitter' }
    : { fetchUrl: url, adapter: 'readability' };
}

export function extractPost(payload, url) {
  const { tweet, code } = JSON.parse(payload);
  const match = new URL(url).pathname.match(/^\/([\w]+)\/status\/(\d+)$/);
  if (code !== 200 || !tweet || tweet.id !== match[2] ||
      tweet.author?.screen_name?.toLowerCase() !== match[1].toLowerCase())
    throw new Error('Mirror response identity mismatch or post unavailable');
  if (!tweet.text?.trim()) throw new Error('Mirror returned no post text');
  return {
    title: `@${tweet.author.screen_name}: ${tweet.text.replace(/\s+/g, ' ').slice(0, 90)}`,
    text: tweet.text, markdown: tweet.text, author: tweet.author.screen_name,
    published_at: tweet.created_at || null,
    provenance: 'third-party-mirror',
    warnings: ['第三方镜像，未直接验证 X 原页；未抓取完整线程、评论或图片文字。'],
    media: tweet.media || null,
    quoted_post: tweet.quote ? { url: tweet.quote.url, text: tweet.quote.text } : null,
  };
}

export function extractArticle(html, url) {
  const { document } = parseHTML(html);
  const title = document.querySelector('title')?.textContent || '';
  if (/^(just a moment|access denied|attention required|sign in|log in)/i.test(title.trim()) ||
      document.querySelector('#challenge-form, #cf-challenge-running'))
    throw new Error('Access challenge/login page; manual review required');
  const published = document.querySelector('meta[property="article:published_time"],meta[name="date"]')?.getAttribute('content');
  document.querySelectorAll('script,style,noscript,iframe,form,svg').forEach(n => n.remove());
  // Resolve links without running source scripts or fetching embedded resources.
  for (const a of document.querySelectorAll('a[href]')) {
    try {
      const target = new URL(a.getAttribute('href'), url);
      if (!['http:', 'https:'].includes(target.protocol) || target.username || target.password) a.removeAttribute('href');
      else a.setAttribute('href', target.href);
    } catch { a.removeAttribute('href'); }
  }
  const parsed = new Readability(document.cloneNode(true), { charThreshold: 100, maxElemsToParse: 50000 }).parse();
  const fallback = document.querySelector('article,main,[role="main"]');
  const content = parsed?.content || fallback?.innerHTML;
  const text = (parsed?.textContent || fallback?.textContent || '').trim();
  if (!content || text.length < 100) throw new Error('Insufficient article text; dynamic/login/PDF pages need another adapter');
  const td = new TurndownService({ headingStyle: 'atx', codeBlockStyle: 'fenced' });
  td.remove(['img', 'script', 'style', 'iframe']);
  return { title: parsed?.title || title || new URL(url).hostname,
    text, markdown: td.turndown(content), author: parsed?.byline || null,
    published_at: published || parsed?.publishedTime || null,
    provenance: 'direct-http', warnings: ['正文由规则提取，可能遗漏表格、图片、动态内容；不代表事实已经核实。'] };
}
