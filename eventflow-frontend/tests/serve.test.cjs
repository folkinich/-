'use strict';
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { spawn, execFileSync } = require('node:child_process');
const { once } = require('node:events');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
let child, base;
function launch(env = {}) {
  return new Promise((resolve, reject) => {
    const proc = spawn(process.execPath, ['scripts/serve.cjs'], { cwd: root,
      env: { ...process.env, HOST: '127.0.0.1', PORT: '0', BACKEND_URL: '', ...env }, stdio: ['ignore', 'pipe', 'pipe'] });
    let output = '';
    const timer = setTimeout(() => { proc.kill(); reject(new Error('Startup timed out')); }, 5000);
    proc.once('error', (error) => { clearTimeout(timer); reject(error); });
    proc.once('exit', (code) => { clearTimeout(timer); if (!output.includes('Frontend listening')) reject(new Error(`Server exited ${code}`)); });
    proc.stdout.on('data', (data) => {
      output += data;
      const port = output.match(/Frontend listening on [^\n]+:(\d+)/)?.[1];
      if (port) { clearTimeout(timer); resolve({ proc, url: `http://127.0.0.1:${port}` }); }
    });
  });
}
async function stop(proc) {
  if (proc.exitCode !== null) return;
  const exited = once(proc, 'exit'); proc.kill('SIGTERM'); await exited;
}
before(async () => {
  execFileSync(process.execPath, ['scripts/build.cjs'], { cwd: root, env: { ...process.env, API_BASE_URL: '' } });
  ({ proc: child, url: base } = await launch());
});
after(async () => { if (child) await stop(child); });

test('serves all pages and referenced frontend assets', async () => {
  for (const [file, type] of [['/','text/html'],['/login.html','text/html'],['/dashboard.html','text/html'],['/style.css','text/css'],['/dashboard.js','text/javascript'],['/store.js','text/javascript'],['/data.js','text/javascript'],['/api.js','text/javascript'],['/config.js','text/javascript'],['/login.js','text/javascript']]) {
    const response = await fetch(base + file);
    assert.equal(response.status, 200, file);
    assert.ok(response.headers.get('content-type').startsWith(type), file);
    assert.equal(response.headers.get('x-content-type-options'), 'nosniff');
    assert.ok((await response.text()).length > 0);
  }
});
test('healthcheck and HEAD requests work', async () => {
  assert.deepEqual(await (await fetch(base + '/health')).json(), { status: 'ok' });
  const response = await fetch(base + '/', { method: 'HEAD' });
  assert.equal(response.status, 200);
  assert.ok(Number(response.headers.get('content-length')) > 0);
  assert.equal(await response.text(), '');
});
test('does not publish source server files, secrets or unknown paths', async () => {
  for (const name of ['/package.json','/.env','/scripts/serve.cjs','/policy.yml','/not-found','/%2e%2e%2fpackage.json','/..%5cpackage.json']) {
    const response = await fetch(base + name);
    assert.ok([400,404].includes(response.status), name);
  }
});
test('rejects malformed paths and unsupported static methods', async () => {
  assert.equal((await fetch(base + '/%ZZ')).status, 400);
  const response = await fetch(base + '/', { method: 'POST', body: 'test' });
  assert.equal(response.status, 405);
  assert.equal(response.headers.get('allow'), 'GET, HEAD');
});
test('missing backend returns a readable error rather than a fake login', async () => {
  const response = await fetch(base + '/api/auth/login', { method: 'POST', body: '{}' });
  assert.equal(response.status, 503);
  assert.match((await response.json()).error, /Backend/);
});
test('build copies only the public allowlist and is repeatable', () => {
  const original = fs.readFileSync(path.join(root,'config.js'),'utf8');
  execFileSync(process.execPath,['scripts/build.cjs'],{cwd:root,env:{...process.env,API_BASE_URL:'https://api.example.test'}});
  assert.match(fs.readFileSync(path.join(root,'dist/config.js'),'utf8'),/https:\/\/api.example.test/);
  assert.equal(fs.readFileSync(path.join(root,'config.js'),'utf8'),original);
  execFileSync(process.execPath,['scripts/build.cjs'],{cwd:root,env:{...process.env,API_BASE_URL:''}});
  assert.equal(fs.readdirSync(path.join(root,'dist')).length,10);
  assert.match(fs.readFileSync(path.join(root,'dist/config.js'),'utf8'),/API_BASE_URL = ""/);
});
test('rejects unsafe build-time API addresses', () => {
  for (const value of ['javascript:alert(1)','https://user:password@example.test']) {
    assert.throws(() => execFileSync(process.execPath,['scripts/build.cjs'],{cwd:root,env:{...process.env,API_BASE_URL:value},stdio:'pipe'}));
  }
  execFileSync(process.execPath,['scripts/build.cjs'],{cwd:root,env:{...process.env,API_BASE_URL:''}});
});
test('optional API proxy preserves method, body and session cookie', async () => {
  const upstream = http.createServer((req,res) => {
    let body=''; req.on('data',(chunk)=>body+=chunk);
    req.on('end',()=>{
      res.writeHead(201,{'content-type':'application/json','set-cookie':'session=test-only; HttpOnly; SameSite=Lax; Path=/'});
      res.end(JSON.stringify({method:req.method,url:req.url,body,cookie:req.headers.cookie,forwarded:req.headers['x-forwarded-host']}));
    });
  });
  upstream.listen(0,'127.0.0.1'); await once(upstream,'listening');
  const proxy = await launch({BACKEND_URL:`http://127.0.0.1:${upstream.address().port}`});
  try {
    const response = await fetch(proxy.url+'/api/auth/login?test=1',{method:'POST',headers:{'Content-Type':'application/json',Cookie:'session=existing-test'},body:'{"login":"test"}'});
    assert.equal(response.status,201);
    assert.match(response.headers.get('set-cookie'),/HttpOnly/);
    const payload = await response.json();
    assert.equal(payload.url,'/api/auth/login?test=1');
    assert.equal(payload.body,'{"login":"test"}');
    assert.equal(payload.cookie,'session=existing-test');
    assert.equal(payload.forwarded,new URL(proxy.url).host);
  } finally { await stop(proxy.proc); await new Promise((resolve)=>upstream.close(resolve)); }
});
test('unreachable backend returns 502', async () => {
  const temporary = http.createServer(); temporary.listen(0,'127.0.0.1'); await once(temporary,'listening');
  const port = temporary.address().port;
  await new Promise((resolve)=>temporary.close(resolve));
  const proxy = await launch({BACKEND_URL:`http://127.0.0.1:${port}`});
  try { assert.equal((await fetch(proxy.url+'/api/auth/me')).status,502); }
  finally { await stop(proxy.proc); }
});
