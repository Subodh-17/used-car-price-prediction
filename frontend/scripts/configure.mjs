// Writes API_BASE_URL into index.html (<meta name="api-base">). Usage: API_BASE_URL=https://api.example.com npm run configure
import { readFileSync, writeFileSync } from 'node:fs';
const file = new URL('../index.html', import.meta.url);
const base = (process.env.API_BASE_URL ?? '').replace(/\/+$/, '');
if (base && !/^https?:\/\/[^\s"<>]+$/.test(base)) { console.error('API_BASE_URL must be an http(s) URL'); process.exit(1); }
const out = readFileSync(file, 'utf8').replace(/<meta name="api-base" content="[^"]*">/, `<meta name="api-base" content="${base}">`);
writeFileSync(file, out);
console.log(`api-base set to "${base || '(same origin)'}"`);
