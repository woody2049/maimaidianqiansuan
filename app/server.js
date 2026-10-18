'use strict';

/**
 * 麦麦点前算 · 后端（零依赖）
 *
 * 1) 静态托管 index.html，并把运行时配置从环境变量注入页面
 * 2) 麦当劳 MCP 代理：浏览器直连 mcp.mcd.cn 会被 CORS / WAF 拦，所以由本服务转发
 *
 * 密钥策略：MCD_TOKEN 与云端 publishableKey 只从环境变量读，绝不写进仓库。
 * 配了 MCD_TOKEN 时，客户端传来的 token 一律忽略；没配时才退回「客户端自带 token」。
 */

const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const PORT = Number(process.env.PORT || 3000);
const MCD_ENDPOINT = process.env.MCD_ENDPOINT || 'https://mcp.mcd.cn';
const MCD_TOKEN = String(process.env.MCD_TOKEN || '').trim();
const ROOT = __dirname;
const PROTOCOLS = ['2025-06-18', '2024-11-05'];

/** 注入页面的运行时配置（不含 MCP 密钥；云端键需自备，属于客户端可见的公开键） */
const RUNTIME_CONFIG = {
  cloudResourceId: process.env.CLOUD_RESOURCE_ID || '',
  cloudEndpoint: process.env.CLOUD_ENDPOINT || '',
  cloudOauthRelayUrl: process.env.CLOUD_OAUTH_RELAY_URL || '',
  cloudPublishableKey: process.env.CLOUD_PUBLISHABLE_KEY || ''
};

/** token 摘要 -> { sessionId, protocol, at } */
const sessions = new Map();
const SESSION_TTL = 10 * 60 * 1000;

const sha = (s) => crypto.createHash('sha256').update(s).digest('hex').slice(0, 24);

function trimSessions() {
  const now = Date.now();
  for (const [k, v] of sessions) if (now - v.at > SESSION_TTL) sessions.delete(k);
}

class McdError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status || 502;
  }
}

/** 解析 SSE 或普通 JSON，返回 JSON-RPC 响应对象 */
function parseRpc(text, contentType) {
  const raw = String(text || '').trim();
  if (!raw) return null;
  if (contentType && contentType.includes('text/event-stream')) {
    const lines = raw.split(/\r?\n/);
    let last = null;
    for (const line of lines) {
      const s = line.trim();
      if (!s.startsWith('data:')) continue;
      const payload = s.slice(5).trim();
      if (!payload || payload === '[DONE]') continue;
      try { last = JSON.parse(payload); } catch (e) { /* 分片或心跳 */ }
    }
    if (last) return last;
  }
  try { return JSON.parse(raw); } catch (e) {
    for (const line of raw.split(/\r?\n/)) {
      const s = line.trim();
      if (!s.startsWith('data:')) continue;
      try { return JSON.parse(s.slice(5).trim()); } catch (e2) { /* ignore */ }
    }
  }
  return null;
}

async function mcdFetch(token, body, sessionId, protocol) {
  const headers = {
    'Content-Type': 'application/json',
    'Accept': 'application/json, text/event-stream',
    'Authorization': 'Bearer ' + token,
    'User-Agent': 'maimai-order-calc/1.0'
  };
  if (sessionId) headers['Mcp-Session-Id'] = sessionId;
  if (protocol) headers['MCP-Protocol-Version'] = protocol;

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 20000);
  let res;
  try {
    res = await fetch(MCD_ENDPOINT, { method: 'POST', headers, body: JSON.stringify(body), signal: ctrl.signal });
  } catch (e) {
    clearTimeout(timer);
    if (e.name === 'AbortError') throw new McdError('麦当劳服务响应超时，请稍后重试', 504);
    throw new McdError('连不上麦当劳服务：' + (e.message || '网络异常'), 502);
  }
  clearTimeout(timer);

  const text = await res.text();
  const ct = res.headers.get('content-type') || '';

  if (res.status === 401) throw new McdError('MCP Token 无效或已过期（检查环境变量 MCD_TOKEN）', 401);
  if (res.status === 429) throw new McdError('请求太频繁，麦当劳侧限流了（600 次/分钟），稍等再试', 429);
  if (res.status === 403) throw new McdError('麦当劳服务拒绝了这次请求（403），通常是 Token 无效或权限不足', 403);
  if (!res.ok) {
    const hint = (parseRpc(text, ct) || {}).error || {};
    throw new McdError('麦当劳服务返回 ' + res.status + (hint.message ? '：' + hint.message : ''), 502);
  }

  const rpc = parseRpc(text, ct);
  if (!rpc) throw new McdError('麦当劳服务返回了无法解析的内容', 502);
  if (rpc.error) throw new McdError(rpc.error.message || '麦当劳服务调用失败', 502);

  return { rpc, sessionId: res.headers.get('mcp-session-id') || sessionId };
}

async function ensureSession(token) {
  trimSessions();
  const key = sha(token);
  const hit = sessions.get(key);
  if (hit && Date.now() - hit.at < SESSION_TTL) return hit;

  let lastErr = null;
  for (const protocol of PROTOCOLS) {
    try {
      const { sessionId } = await mcdFetch(token, {
        jsonrpc: '2.0',
        id: 1,
        method: 'initialize',
        params: {
          protocolVersion: protocol,
          capabilities: {},
          clientInfo: { name: 'maimai-order-calc', version: '1.0.0' }
        }
      }, null, protocol);

      const sid = sessionId || null;
      if (sid) {
        await fetch(MCD_ENDPOINT, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/event-stream',
            'Authorization': 'Bearer ' + token,
            'Mcp-Session-Id': sid,
            'MCP-Protocol-Version': protocol
          },
          body: JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' })
        }).catch(() => {});
      }

      const s = { sessionId: sid, protocol, at: Date.now() };
      sessions.set(key, s);
      return s;
    } catch (e) {
      lastErr = e;
      if (e.status === 401 || e.status === 403 || e.status === 429) throw e;
    }
  }
  throw lastErr || new McdError('初始化麦当劳 MCP 会话失败', 502);
}

async function callTool(token, name, args) {
  const run = async (force) => {
    const s = force ? { sessionId: null, protocol: PROTOCOLS[0], at: 0 } : await ensureSession(token);
    return mcdFetch(token, {
      jsonrpc: '2.0',
      id: Date.now() % 100000,
      method: 'tools/call',
      params: { name, arguments: args || {} }
    }, s.sessionId, s.protocol);
  };

  let out;
  try {
    out = await run(false);
  } catch (e) {
    if (e.status === 401 || e.status === 403) throw e;
    sessions.delete(sha(token));
    out = await run(true);
  }

  const rpc = out.rpc;
  const result = rpc.result || {};
  if (result.isError) {
    const msg = (result.content || []).map((c) => c.text).filter(Boolean).join(' ') || '麦当劳服务返回错误';
    throw new McdError(msg, 502);
  }
  const content = Array.isArray(result.content) ? result.content : [];
  const text = content.map((c) => (typeof c.text === 'string' ? c.text : JSON.stringify(c))).join('\n');
  const structured = result.structuredContent || null;
  sessions.get(sha(token)) && (sessions.get(sha(token)).at = Date.now());
  return { tool: name, text, structured, raw: result };
}

async function listTools(token) {
  const s = await ensureSession(token);
  const { rpc } = await mcdFetch(token, { jsonrpc: '2.0', id: 2, method: 'tools/list', params: {} }, s.sessionId, s.protocol);
  return rpc.result || {};
}

function send(res, status, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
    'Content-Length': Buffer.byteLength(body)
  });
  res.end(body);
}

function readBody(req, limit) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', (c) => {
      size += c.length;
      if (size > limit) { reject(new McdError('请求体过大', 413)); req.destroy(); return; }
      chunks.push(c);
    });
    req.on('end', () => {
      try { resolve(chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf8')) : {}); }
      catch (e) { reject(new McdError('请求参数不是合法 JSON', 400)); }
    });
    req.on('error', reject);
  });
}

async function handleApi(req, res, url) {
  if (req.method === 'GET' && url.pathname === '/api/health') {
    return send(res, 200, { ok: true, endpoint: MCD_ENDPOINT, mcdConfigured: !!MCD_TOKEN, ts: Date.now() });
  }
  if (req.method !== 'POST') return send(res, 405, { ok: false, error: '只支持 POST' });

  let body;
  try { body = await readBody(req, 64 * 1024); } catch (e) { return send(res, e.status || 400, { ok: false, error: e.message }); }

  /* 服务端配了 MCD_TOKEN 就只用它，客户端传什么都忽略（避免公开部署时 token 泄漏在前端） */
  const token = MCD_TOKEN || String(body.token || '').trim();
  if (!token) {
    return send(res, 400, {
      ok: false,
      error: '还没有配置麦当劳 MCP Token：设置环境变量 MCD_TOKEN 后重启服务',
      code: 'NO_TOKEN'
    });
  }

  try {
    if (url.pathname === '/api/mcd/tools') {
      const data = await listTools(token);
      const tools = (data.tools || []).map((t) => ({ name: t.name, description: (t.description || '').slice(0, 200) }));
      return send(res, 200, { ok: true, tools });
    }
    if (url.pathname === '/api/mcd/call') {
      const name = String(body.tool || '').trim();
      if (!name) return send(res, 400, { ok: false, error: '缺少 tool 参数' });
      const out = await callTool(token, name, body.args || {});
      return send(res, 200, { ok: true, tool: out.tool, text: out.text, structured: out.structured });
    }
    return send(res, 404, { ok: false, error: '没有这个接口' });
  } catch (e) {
    const status = e.status || 502;
    console.warn('[mcd] ' + url.pathname + ' 失败: ' + e.message);
    return send(res, status, { ok: false, error: e.message, code: status === 401 ? 'BAD_TOKEN' : 'MCD_ERROR' });
  }
}

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.json': 'application/json; charset=utf-8'
};

/** 把运行时配置注入页面（只注入配置，不注入任何密钥） */
function injectRuntime(html) {
  const tag = '<script>window.__RUNTIME_CONFIG__=' + JSON.stringify(RUNTIME_CONFIG) + ';</script>';
  return html.includes('</head>') ? html.replace('</head>', tag + '</head>') : tag + html;
}

function serveStatic(req, res, url) {
  let rel = decodeURIComponent(url.pathname);
  if (rel === '/' || rel === '') rel = '/index.html';
  const file = path.join(ROOT, path.normalize(rel).replace(/^([/\\])+/, ''));
  if (!file.startsWith(ROOT)) { res.writeHead(403); return res.end('forbidden'); }
  const ext = path.extname(file).toLowerCase();
  fs.readFile(file, (err, buf) => {
    if (err) { res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' }); return res.end('not found'); }
    if (ext === '.html') {
      const body = injectRuntime(buf.toString('utf8'));
      res.writeHead(200, { 'Content-Type': TYPES['.html'], 'Cache-Control': 'no-store' });
      return res.end(body);
    }
    res.writeHead(200, { 'Content-Type': TYPES[ext] || 'application/octet-stream', 'Cache-Control': 'public, max-age=300' });
    res.end(buf);
  });
}

http.createServer((req, res) => {
  const url = new URL(req.url, 'http://' + (req.headers.host || 'localhost'));
  if (url.pathname.startsWith('/api/')) {
    handleApi(req, res, url).catch((e) => send(res, 500, { ok: false, error: e.message }));
    return;
  }
  serveStatic(req, res, url);
}).listen(PORT, '0.0.0.0', () => {
  console.log('麦麦点前算 running on http://0.0.0.0:' + PORT
    + ' (mcd=' + MCD_ENDPOINT + ', token=' + (MCD_TOKEN ? 'env' : '未配置') + ')');
});
