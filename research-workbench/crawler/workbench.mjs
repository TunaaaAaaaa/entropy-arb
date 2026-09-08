import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const script = fileURLToPath(new URL('../workbench.py', import.meta.url));
const child = spawnSync(process.env.RESEARCH_PYTHON || 'python', [script, ...process.argv.slice(2)],
  { stdio: 'inherit', env: { ...process.env, PYTHONUTF8: '1' } });
if (child.error) console.error(child.error.message);
process.exitCode = child.status ?? 1;
