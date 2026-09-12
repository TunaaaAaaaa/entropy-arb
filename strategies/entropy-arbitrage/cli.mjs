import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const commands = {
  help: ['main.py', '--help'],
  record: ['main.py', '--record-only'],
  analyze: ['tools/analyze.py'],
  test: ['-m', 'pytest', 'tests', '-q'],
};
const [command = 'help', ...args] = process.argv.slice(2);
if (!Object.hasOwn(commands, command)) {
  console.error('Choose help, record, analyze or test. This is a learning demo.');
  process.exitCode = 2;
} else {
  const child = spawnSync(process.env.RESEARCH_PYTHON || 'python', [...commands[command], ...args], {
    cwd: fileURLToPath(new URL('.', import.meta.url)),
    stdio: 'inherit', env: { ...process.env, PYTHONUTF8: '1' },
  });
  if (child.error) console.error(child.error.message);
  process.exitCode = child.status ?? 1;
}
