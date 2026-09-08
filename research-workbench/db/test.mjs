import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const env={...process.env,PYTHONUTF8:'1',RUN_POSTGRES_TESTS:'1'};
delete env.RESEARCH_DATABASE_URL;
delete env.RESEARCH_BACKEND;
const child=spawnSync(process.env.RESEARCH_PYTHON || 'python', ['-m','unittest','discover','-s','tests','-v'],
  {cwd:fileURLToPath(new URL('..',import.meta.url)),stdio:'inherit',env});
process.exitCode=child.status??1;
