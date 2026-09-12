import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('.', import.meta.url));
const venvPython = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const run = (python, args) => {
  const child = spawnSync(python, args, {
    cwd: root, stdio: 'inherit', env: { ...process.env, PYTHONUTF8: '1' },
  });
  if (child.error) console.error(child.error.message);
  return child.status ?? 1;
};
const [command = 'help', ...args] = process.argv.slice(2);
if (command === 'setup') {
  const code = existsSync(venvPython) ? 0 : run(process.env.RESEARCH_PYTHON || 'python', ['-m', 'venv', '.venv']);
  process.exitCode = code || run(venvPython, ['-m', 'pip', 'install', '-r', 'requirements.txt']);
} else {
  const commands = {
    help: ['main.py', '--help'], start: ['main.py'], once: ['main.py', '--once'],
    smoke: ['smoke_test.py'], verify: ['live_verify.py'], wecom: ['wecom_tool.py'], test: ['-m', 'pytest', 'tests', '-q'],
  };
  if (!Object.hasOwn(commands, command)) {
    console.error('Commands: setup, help, start, once, smoke, verify, wecom, test');
    process.exitCode = 2;
  } else {
    const python = process.env.NEWS_BOT_PYTHON || (existsSync(venvPython) ? venvPython : process.env.RESEARCH_PYTHON || 'python');
    process.exitCode = run(python, [...commands[command], ...args]);
  }
}
