'use strict';
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const out = path.join(root, 'dist');
const files = [
  'index.html', 'login.html', 'dashboard.html', 'style.css',
  'config.js', 'api.js', 'data.js', 'store.js', 'login.js', 'dashboard.js',
];
for (const file of files) {
  if (!fs.statSync(path.join(root, file)).isFile()) throw new Error(`Missing frontend file: ${file}`);
}
// Copy only public assets: .env, policy, package metadata and scripts never enter dist.
fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(out, { recursive: true });
for (const file of files) fs.copyFileSync(path.join(root, file), path.join(out, file));
if (process.env.API_BASE_URL !== undefined) {
  const base = process.env.API_BASE_URL.trim().replace(/\/$/, '');
  if (base) {
    const url = new URL(base);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
      throw new Error('API_BASE_URL must be a public HTTP(S) URL without credentials, query or fragment.');
    }
  }
  fs.writeFileSync(path.join(out, 'config.js'), `window.EVENTFLOW_API_BASE_URL = ${JSON.stringify(base)};\n`);
}
console.log(`Built ${files.length} public files in dist/`);
