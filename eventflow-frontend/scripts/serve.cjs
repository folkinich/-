'use strict';
const http = require('node:http');
const https = require('node:https');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..', 'dist');
if (!fs.existsSync(path.join(root, 'index.html'))) {
  console.error('dist/index.html is missing. Run npm run build first.');
  process.exit(1);
}
const port = Number(process.env.PORT || 3000);
const host = process.env.HOST || '0.0.0.0';
if (!Number.isInteger(port) || port < 0 || port > 65535) throw new Error('Invalid PORT');
let backend;
if (process.env.BACKEND_URL) {
  backend = new URL(process.env.BACKEND_URL);
  if (!['http:', 'https:'].includes(backend.protocol) || backend.username || backend.password || backend.search || backend.hash) {
    throw new Error('BACKEND_URL must be an HTTP(S) URL without credentials, query or fragment.');
  }
}
const mime = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8' };
const hopHeaders = new Set(['connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'te', 'trailer', 'transfer-encoding', 'upgrade']);
function cleanHeaders(headers) {
  const skip = new Set([...hopHeaders, ...(headers.connection || '').split(',').map((name) => name.trim().toLowerCase())]);
  return Object.fromEntries(Object.entries(headers).filter(([name]) => !skip.has(name.toLowerCase())));
}
function json(res, status, body) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
  res.end(JSON.stringify(body));
}
function proxy(req, res, url) {
  if (!backend) return json(res, 503, { error: 'Backend ещё не подключён. Для просмотра интерфейса откройте демоверсию.' });
  const target = new URL(backend);
  target.pathname = backend.pathname.replace(/\/$/, '') + url.pathname;
  target.search = url.search;
  const headers = cleanHeaders(req.headers);
  headers.host = target.host;
  headers['x-forwarded-host'] = req.headers.host || '';
  headers['x-forwarded-for'] = req.socket.remoteAddress || '';
  const transport = target.protocol === 'https:' ? https : http;
  const upstream = transport.request(target, { method: req.method, headers }, (response) => {
    res.writeHead(response.statusCode, cleanHeaders(response.headers));
    response.pipe(res);
    response.on('error', () => res.destroy());
  });
  upstream.setTimeout(20000, () => upstream.destroy(new Error('Upstream timeout')));
  upstream.on('error', () => {
    if (!res.headersSent) json(res, 502, { error: 'Backend временно недоступен. Попробуйте позже.' });
    else res.destroy();
  });
  req.on('aborted', () => upstream.destroy());
  req.pipe(upstream);
}
const server = http.createServer((req, res) => {
  let url;
  let pathname;
  try {
    // Prefixing prevents a request target beginning // from choosing a different origin.
    url = new URL('http://localhost' + req.url);
    pathname = decodeURIComponent(url.pathname);
    if (pathname.includes('\0') || pathname.includes('\\')) throw new Error('Invalid path');
  } catch { return json(res, 400, { error: 'Некорректный адрес.' }); }
  if (url.pathname === '/api' || url.pathname.startsWith('/api/')) return proxy(req, res, url);
  if (!['GET', 'HEAD'].includes(req.method)) {
    res.setHeader('Allow', 'GET, HEAD');
    return json(res, 405, { error: 'Метод не поддерживается.' });
  }
  if (pathname === '/health' || pathname === '/healthz') return json(res, 200, { status: 'ok' });
  if (pathname === '/') pathname = '/index.html';
  if (pathname === '/login') pathname = '/login.html';
  if (pathname === '/dashboard') pathname = '/dashboard.html';
  const file = path.resolve(root, '.' + pathname);
  if (!file.startsWith(root + path.sep)) return json(res, 404, { error: 'Страница не найдена.' });
  fs.stat(file, (error, stat) => {
    if (error || !stat.isFile()) return json(res, 404, { error: 'Страница не найдена.' });
    res.writeHead(200, {
      'Content-Type': mime[path.extname(file)] || 'application/octet-stream',
      'Content-Length': stat.size,
      'Cache-Control': 'no-cache',
      'X-Content-Type-Options': 'nosniff',
      'Referrer-Policy': 'strict-origin-when-cross-origin',
    });
    if (req.method === 'HEAD') return res.end();
    const stream = fs.createReadStream(file);
    stream.on('error', () => res.destroy());
    stream.pipe(res);
  });
});
server.on('error', (error) => { console.error(`Frontend server failed: ${error.code || error.name}`); process.exit(1); });
server.listen(port, host, () => console.log(`Frontend listening on ${host}:${server.address().port}`));
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => {
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 5000).unref();
});
