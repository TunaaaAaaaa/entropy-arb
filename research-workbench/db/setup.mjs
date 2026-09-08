import fs from 'node:fs';
import { randomBytes } from 'node:crypto';
const dir = new URL('../data/local/', import.meta.url);
fs.mkdirSync(dir, { recursive: true });
const secret = new URL('pg_password', dir);
if (!fs.existsSync(secret)) fs.writeFileSync(secret, randomBytes(32).toString('hex'), { flag: 'wx', mode: 0o600 });
const config = new URL('postgres.json', dir);
if (!fs.existsSync(config)) fs.writeFileSync(config, JSON.stringify({
  host: '127.0.0.1', port: 55432, dbname: 'entropy_research', user: 'entropy_owner',
  password: fs.readFileSync(secret, 'utf8').trim(), connect_timeout: 5,
}), { flag: 'wx', mode: 0o600 });
console.log('Local PostgreSQL connection configured; credentials are excluded from Git.');
