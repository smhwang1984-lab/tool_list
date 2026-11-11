// assembly/ (AssemblyScript) → src/sim/wasm/simKernels.ts (base64). 사용: npm run build:wasm
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync, rmSync } from 'node:fs';
mkdirSync('src/sim/wasm', { recursive: true });
const tmp = 'src/sim/wasm/_kernels.wasm';
execFileSync('npx', ['asc', 'assembly/index.ts', '-o', tmp, '--importMemory', '--runtime', 'stub', '--noAssert', '-O3', '--enable', 'nontrapping-f2i'], { stdio: 'inherit', shell: true });
const b64 = readFileSync(tmp).toString('base64');
rmSync(tmp);
writeFileSync('src/sim/wasm/simKernels.ts', `// 자동 생성 — tools/build_wasm.mjs (assembly/*.ts). 직접 고치지 않는다.\nexport const SIM_KERNELS_B64 =\n  '${b64}';\n`);
console.log('simKernels.ts', Math.round((b64.length * 3) / 4), 'bytes');
