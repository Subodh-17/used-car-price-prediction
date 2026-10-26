// Parses every JS module with `node --check` (no TypeScript compiler is available offline; types are JSDoc only).
import { execFileSync } from 'node:child_process';
import { readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
const walk = (d) => readdirSync(d).flatMap((f) => (statSync(join(d, f)).isDirectory() ? walk(join(d, f)) : [join(d, f)]));
const files = walk(fileURLToPath(new URL('../js', import.meta.url))).filter((f) => f.endsWith('.js'));
for (const f of files) execFileSync(process.execPath, ['--check', f]);
console.log(`syntax OK: ${files.length} modules`);
