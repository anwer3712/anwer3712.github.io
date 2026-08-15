/*
 * cf-worker 離線自檢。不需要 wrangler、不連網、不碰 Cloudflare 帳號。
 * 執行：node cf-worker/worker.test.mjs
 *
 * 這支盯的是「主機關機時那張單有沒有被收下」——也就是 2026-08-15 查到的原始 bug：
 * 舊路徑下 origin 530 → 前台 throw → 單子消失，沒有任何地方留下紀錄。
 */
import assert from 'node:assert/strict';
import worker from './worker.js';

const KEY = 'test-drain-key';

function fakeKV() {
  const m = new Map();
  return {
    m,
    async put(k, v) { m.set(k, v); },
    async get(k) { return m.has(k) ? m.get(k) : null; },
    async delete(k) { m.delete(k); },
    async list({ prefix, limit }) {
      const keys = [...m.keys()].filter((k) => k.startsWith(prefix)).sort().slice(0, limit).map((name) => ({ name }));
      return { keys };
    },
  };
}

// 把 global fetch 換成假的 origin。mode: 'up' | 'down' | 'throw' | 'bad'
let calls = 0;
function stubOrigin(mode) {
  calls = 0;
  globalThis.fetch = async () => {
    calls++;
    if (mode === 'throw') throw new Error('tunnel down');
    if (mode === 'down') return new Response('error code: 1033', { status: 530 });
    if (mode === 'bad') return new Response(JSON.stringify({ message: 'bad token' }), { status: 400 });
    return new Response(JSON.stringify({ ok: true, order_no: 'S20260815-0001' }), {
      status: 200, headers: { 'content-type': 'application/json' },
    });
  };
}

const ORDER = JSON.stringify({ token: 'pps_x', order: { temp_id: 'T20260815-ABC', A: { name: '小王' }, contact: '0912345678' } });
const post = (path, body, headers = {}) =>
  new Request('https://n8n.anwer3712.com' + path, { method: 'POST', headers: { 'content-type': 'application/json', ...headers }, body });

let pass = 0;
const ok = (msg) => { pass++; console.log('  ✔ ' + msg); };

/* ── 1. 主機開著：原樣轉發，不進佇列 ─────────────────────────── */
{
  const env = { PPSQ: fakeKV(), DRAIN_KEY: KEY };
  stubOrigin('up');
  const res = await worker.fetch(post('/webhook/pps-intake', ORDER), env);
  const body = await res.json();
  assert.equal(body.order_no, 'S20260815-0001', '主機開著時要拿到 n8n 發的真編號');
  assert.equal(env.PPSQ.m.size, 0, '主機開著不該有東西進佇列');
  ok('origin 200 → 原樣回傳，佇列空');
}

/* ── 2. 主機關機（Cloudflare 530）：收進佇列 ──────────────────── */
{
  const env = { PPSQ: fakeKV(), DRAIN_KEY: KEY };
  stubOrigin('down');
  const res = await worker.fetch(post('/webhook/pps-intake', ORDER), env);
  const body = await res.json();
  assert.equal(res.status, 200, '要回 200，否則前台 api() 會 throw 進 catch');
  assert.equal(body.queued, true);
  assert.equal(env.PPSQ.m.size, 1, '這就是原始 bug：關機時那張單必須留下來');
  assert.equal([...env.PPSQ.m.values()][0], ORDER, '存的要是原始 payload，一個字都不能改');
  assert.ok([...env.PPSQ.m.keys()][0].startsWith('qi:'), '訂製問卷要用 qi: 前綴——n8n 靠它決定灌回哪支 webhook');
  assert.equal(res.headers.get('access-control-allow-origin'), '*', '跨網域回應少了 CORS 標頭，瀏覽器會當作失敗');
  ok('origin 530 → 進佇列，回 queued');
}

/* ── 2b. 現貨結帳同樣要收（2026-08-15 擴充）──────────────────── */
{
  const env = { PPSQ: fakeKV(), DRAIN_KEY: KEY };
  stubOrigin('down');
  const SHOP = JSON.stringify({ token: 'pps_x', order: { temp_id: 'S20260815-ZZZ', items: [{ id: 3, qty: 1 }] } });
  const res = await worker.fetch(post('/webhook/pps2-shop-order', SHOP), env);
  assert.equal((await res.json()).queued, true);
  const k = [...env.PPSQ.m.keys()][0];
  assert.ok(k.startsWith('qs:'), '現貨要用 qs: 前綴，跟訂製分流');
  assert.equal(env.PPSQ.m.get(k), SHOP);
  ok('現貨結帳 origin 530 → 進佇列（qs: 前綴）');
}

/* ── 2c. 沒在緩衝名單上的路徑：原樣放行，不進佇列 ──────────── */
{
  const env = { PPSQ: fakeKV(), DRAIN_KEY: KEY };
  stubOrigin('down');
  const res = await worker.fetch(post('/webhook/pps-status', '{"op":"get"}'), env);
  assert.equal(res.status, 530, '沒列入緩衝的路徑要原樣把 origin 的回應送回去');
  assert.equal(env.PPSQ.m.size, 0, '進度查詢這種讀取型請求不該被排隊（客戶重試就好）');
  ok('非緩衝路徑 → 原樣放行');
}

/* ── 3. 連不上（fetch throw）：一樣收進佇列 ──────────────────── */
{
  const env = { PPSQ: fakeKV(), DRAIN_KEY: KEY };
  stubOrigin('throw');
  await worker.fetch(post('/webhook/pps-intake', ORDER), env);
  assert.equal(env.PPSQ.m.size, 1);
  ok('origin 連不上 → 進佇列');
}

/* ── 4. 4xx 是客戶端的錯：原樣回，不進佇列 ──────────────────── */
{
  const env = { PPSQ: fakeKV(), DRAIN_KEY: KEY };
  stubOrigin('bad');
  const res = await worker.fetch(post('/webhook/pps-intake', ORDER), env);
  assert.equal(res.status, 400);
  assert.equal(env.PPSQ.m.size, 0, '缺必填／token 錯排進佇列，開機後只會再錯一次');
  ok('origin 400 → 原樣回，不進佇列');
}

/* ── 5. CORS 預檢由 Worker 自己回，不能倚賴 origin ───────────── */
{
  const env = { PPSQ: fakeKV(), DRAIN_KEY: KEY };
  stubOrigin('down');
  const res = await worker.fetch(new Request('https://n8n.anwer3712.com/webhook/pps-intake', { method: 'OPTIONS' }), env);
  assert.equal(res.status, 204);
  assert.equal(res.headers.get('access-control-allow-origin'), '*');
  assert.equal(calls, 0, '預檢轉給 origin 的話，關機時瀏覽器連 POST 都不會送出');
  ok('OPTIONS 預檢本地回應，關機時仍成立');
}

/* ── 6. 迴圈保險 ─────────────────────────────────────────────── */
{
  const env = { PPSQ: fakeKV(), DRAIN_KEY: KEY };
  stubOrigin('up');
  await worker.fetch(post('/webhook/pps-intake', ORDER, { 'x-pps-buf': '1' }), env);
  assert.equal(calls, 1, '帶了深度標記就該直接放行，不能再包一層');
  ok('x-pps-buf → 直接放行');
}

/* ── 7. drain / ack ─────────────────────────────────────────── */
{
  const env = { PPSQ: fakeKV(), DRAIN_KEY: KEY };
  stubOrigin('down');
  await worker.fetch(post('/webhook/pps-intake', ORDER), env);

  const noKey = await worker.fetch(new Request('https://n8n.anwer3712.com/webhook/pps-queue-drain', { method: 'POST' }), env);
  assert.equal(noKey.status, 401, 'drain 沒帶金鑰要擋掉——不然客戶資料任何人都撈得到');
  ok('drain 無金鑰 → 401');

  const wrongLen = await worker.fetch(
    new Request('https://n8n.anwer3712.com/webhook/pps-queue-drain', { method: 'POST', headers: { 'x-pps-drain-key': KEY + 'x' } }), env);
  assert.equal(wrongLen.status, 401);
  ok('drain 金鑰錯 → 401');

  const res = await worker.fetch(
    new Request('https://n8n.anwer3712.com/webhook/pps-queue-drain', { method: 'POST', headers: { 'x-pps-drain-key': KEY } }), env);
  const got = await res.json();
  assert.equal(got.count, 1);
  assert.equal(got.items[0].body, ORDER);
  ok('drain 帶金鑰 → 取回 payload');

  // 沒 ack 之前不能消失：drain 只讀不刪，灌回失敗才有得重來
  const again = await worker.fetch(
    new Request('https://n8n.anwer3712.com/webhook/pps-queue-drain', { method: 'POST', headers: { 'x-pps-drain-key': KEY } }), env);
  assert.equal((await again.json()).count, 1, 'drain 不該刪除——n8n 灌回失敗時要能再取一次');
  ok('drain 不刪資料，可重取');

  const bad = await worker.fetch(new Request('https://n8n.anwer3712.com/webhook/pps-queue-ack', {
    method: 'POST', headers: { 'x-pps-drain-key': KEY, 'content-type': 'application/json' },
    body: JSON.stringify({ keys: ['not-a-queue-key'] }),
  }), env);
  assert.equal((await bad.json()).deleted, 0, 'ack 只准刪 q: 前綴');
  assert.equal(env.PPSQ.m.size, 1);
  ok('ack 拒刪非佇列 key');

  const acked = await worker.fetch(new Request('https://n8n.anwer3712.com/webhook/pps-queue-ack', {
    method: 'POST', headers: { 'x-pps-drain-key': KEY, 'content-type': 'application/json' },
    body: JSON.stringify({ keys: [got.items[0].key] }),
  }), env);
  assert.equal((await acked.json()).deleted, 1);
  assert.equal(env.PPSQ.m.size, 0);
  ok('ack → 刪除');
}

console.log(`\ncf-worker 自檢通過：${pass} 項`);
