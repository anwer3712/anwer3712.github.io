/**
 * pps-intake-buffer — 訂製問卷的邊緣緩衝區
 *
 * ── 為什麼會有這支 ───────────────────────────────────────────────
 * 2026-08-15 查明：家用主機關機時，訂製問卷**不是「累積在某處等處理」，是當場消失**。
 * 原本的路徑是 瀏覽器 → n8n.anwer3712.com（Cloudflare Tunnel）→ 家裡 Docker 的 n8n。
 * 主機關機 = 隧道斷 = Cloudflare 回 530，index.html 的 api() 看到 !r.ok 就 throw，
 * 前台退化成「已為你整理好訂單內容 + 複製到 LINE」。客戶沒複製 → 那張單沒有留在任何地方，
 * 開機後也沒有東西可以「跳出來處理」。老闆完全不會知道有人填過。
 *
 * 這支 Worker 跑在 Cloudflare 邊緣（永遠在線），夾在中間：
 *   主機開著 → 原樣轉給 n8n，回應也原樣送回（行為與今天完全相同）
 *   主機關著 → 把 payload 收進 KV，回 { ok:false, queued:true }
 * 開機後由 n8n 的「INTAKE_DRAIN」排程（每 5 分鐘）取回、灌回 /webhook/pps-intake、再回報刪除。
 *
 * 刻意回 ok:false：前台不改一行、不用重新 push GitHub Pages，客戶看到的還是既有的
 * 「複製到 LINE」畫面（多一條人工路徑不是壞事）。要改成「已收到，稍後通知編號」的話，
 * 前台讀 queued 這個欄位就好。
 */

const MAX_BODY = 32 * 1024;        // 超過就不收（驗證正規化 那層本來就擋 6000 字的 order）
const TTL = 60 * 60 * 24 * 30;     // KV 保 30 天；主機一個月沒開，那張單也早就過期了
const DRAIN_LIMIT = 50;            // 一次最多吐 50 張，避免單次 drain 打爆 n8n

/* 要緩衝的路徑 → KV key 前綴。前綴就是「這張單該灌回哪裡」的唯一記號：
   drain 用 prefix 'q' 一次撈完兩種，n8n 那邊看前綴決定灌回 pps-intake 還是 pps2-shop-order。
   （不把路徑寫進 value：value 必須是客戶原始 payload 的逐字拷貝，多包一層就多一個會走鐘的格式。）
   舊的 'q:' 前綴＝訂製問卷，保留相容。 */
const BUFFERED = {
  '/webhook/pps-intake': 'qi:',
  '/webhook/pps2-shop-order': 'qs:',
};

export default {
  async fetch(request, env) {
    const path = new URL(request.url).pathname;
    if (path === '/webhook/pps-queue-drain') return drain(request, env);
    if (path === '/webhook/pps-queue-ack') return ack(request, env);
    if (BUFFERED[path]) return intake(request, env, BUFFERED[path]);
    return fetch(request);           // route 沒綁到的路徑：原樣放行（保險）
  },
};

/* ── 前台送單（訂製問卷／現貨結帳共用）───────────────────────── */
async function intake(request, env, prefix) {
  // CORS 預檢由 Worker 自己回，**不能**轉給 origin。
  // 前台是 anwer3712.github.io（跨網域）且送 Content-Type: application/json，
  // 瀏覽器一定會先發 OPTIONS；主機關機時這個 OPTIONS 也會 530 → 瀏覽器根本不會送出 POST，
  // 我們就永遠收不到那張單。回應內容比照 n8n webhook 的預設（Allow-Origin: *），行為不變。
  if (request.method === 'OPTIONS') {
    return new Response(null, {
      status: 204,
      headers: {
        'access-control-allow-origin': '*',
        'access-control-allow-methods': 'POST, OPTIONS',
        'access-control-allow-headers': 'content-type',
        'access-control-max-age': '86400',
      },
    });
  }
  if (request.method !== 'POST') return fetch(request);

  // 迴圈保險。Cloudflare 對「Worker 打到自己 route」的子請求會直接送 origin、不再進 Worker，
  // 但那是平台行為不是我們控制的；帶一個深度標記，就算哪天行為變了也保證第二層直接放行。
  if (Number(request.headers.get('x-pps-buf') || 0) >= 1) return fetch(request);

  const body = await request.text();
  const headers = new Headers(request.headers);
  headers.set('x-pps-buf', '1');

  let res = null;
  try {
    res = await fetch(new Request(request.url, { method: 'POST', headers, body }));
  } catch (_) {
    res = null;                      // 連不上 origin，等同關機
  }

  // 4xx 是客戶端自己的錯（token 不對、缺必填）——原樣回去。
  // 排進佇列只會讓同一個錯在開機後再犯一次，而且老闆還得手動清。
  if (res && res.status < 500) return res;

  if (body.length > MAX_BODY) return json({ ok: false, msg: '訂單內容過長' });

  // key 帶時間戳 → KV 的 list 是字典序，天然就是先進先出。
  const key = prefix + new Date().toISOString() + ':' + crypto.randomUUID();
  await env.PPSQ.put(key, body, { expirationTtl: TTL });
  return json({ ok: false, queued: true, msg: '已收下，主機開機後自動處理' });
}

/* ── n8n 排程取回 ─────────────────────────────────────────────── */
async function drain(request, env) {
  if (!authed(request, env)) return json({ ok: false, error: 'unauthorized' }, 401);
  // prefix 'q' 一次撈完 qi:（訂製）與 qs:（現貨），連舊的 q: 也涵蓋
  const list = await env.PPSQ.list({ prefix: 'q', limit: DRAIN_LIMIT });
  const items = [];
  for (const k of list.keys) {
    const body = await env.PPSQ.get(k.name);
    if (body === null) continue;     // 剛好在 list 與 get 之間過期
    items.push({ key: k.name, body });
  }
  return json({ ok: true, count: items.length, items });
}

/* ── n8n 灌回成功後回報刪除 ───────────────────────────────────── */
async function ack(request, env) {
  if (!authed(request, env)) return json({ ok: false, error: 'unauthorized' }, 401);
  let keys = [];
  try {
    const b = await request.json();
    keys = Array.isArray(b && b.keys) ? b.keys : [];
  } catch (_) { /* 壞 JSON 當成沒有要刪的 */ }
  // 只准刪佇列前綴的 key，避免這支被拿去清別的東西
  const del = keys.filter((k) => typeof k === 'string' && /^q[is]?:/.test(k));
  await Promise.all(del.map((k) => env.PPSQ.delete(k)));
  return json({ ok: true, deleted: del.length });
}

/* ── 小工具 ───────────────────────────────────────────────────── */
function authed(request, env) {
  const got = request.headers.get('x-pps-drain-key') || '';
  const want = env.DRAIN_KEY || '';
  // 長度不同直接否決；相同長度逐字元 XOR 累加，避免早退洩漏前綴
  if (!want || got.length !== want.length) return false;
  let diff = 0;
  for (let i = 0; i < want.length; i++) diff |= got.charCodeAt(i) ^ want.charCodeAt(i);
  return diff === 0;
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', 'access-control-allow-origin': '*' },
  });
}

// 測試用（worker.test.mjs）。Cloudflare 只認 default export，多掛具名匯出不影響部署。
export { intake, drain, ack, authed };
