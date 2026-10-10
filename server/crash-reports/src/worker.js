// Kettle Linux crash report server (crash.kettlelinux.org): a Cloudflare Worker in front of an
// R2 bucket. The Crash Reports plugin uploads a report its user chose to share (already stripped
// of their details on the device, see packages/kettle-decky-plugins/crash/main.py); the server
// keeps it under a random id and serves a page for it, which links to a prefilled GitHub issue.
//
//   POST /v1/reports      gzipped JSON {version: 1, id, report, files}; answers {id, url}
//   GET  /r/<id>          the report's page
//   GET  /r/<id>.json     the report as kept
//   DELETE /v1/admin/reports/<id>   (Authorization: Bearer $ADMIN_TOKEN) a removal request
//
// Reports are deleted after 90 days by the bucket's lifecycle rule (setup-lifecycle.sh,
// docs/CRASH-REPORTS.md); older ones are never served, whatever the bucket still holds.

const MAX_UPLOAD = 1 << 20; // gzipped
const MAX_JSON = 8 << 20; // once unzipped: a bigger one is refused, not unpacked
const MAX_FILE = 256 << 10; // UTF-8 bytes: the end of a longer file is kept
const KEEP_S = 90 * 86400;
// uploads a day (UTC), per address and in all, counted in the COUNTS KV namespace
const DAY_PER_ADDRESS = 30;
const DAY_TOTAL = 400;
const FILES = ["backtrace.txt", "output.txt", "kernel.txt", "journal.txt", "environ.txt"];
const KINDS = ["coredump", "devcoredump", "game"];
const ISSUES = "https://github.com/kettlelinux/kettlelinux/issues/new";

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (url.pathname === "/v1/reports") {
      return req.method === "POST" ? upload(req, env, url) : text("POST only", 405);
    }
    let m = url.pathname.match(/^\/r\/([a-z2-7]{12})(\.json)?$/);
    if (m && (req.method === "GET" || req.method === "HEAD")) return view(env, m[1], !!m[2]);
    if ((m = url.pathname.match(/^\/v1\/admin\/reports\/([a-z2-7]{12})$/)))
      return req.method === "DELETE" ? remove(req, env, m[1]) : text("DELETE only", 405);
    if (url.pathname === "/") return Response.redirect("https://kettlelinux.org/", 302);
    return text("Not found", 404);
  },
};

function text(body, status = 200) {
  return new Response(body + "\n", {
    status,
    headers: { "Content-Type": "text/plain; charset=utf-8", "X-Content-Type-Options": "nosniff" },
  });
}

function json(body, status = 200, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "X-Content-Type-Options": "nosniff", ...headers },
  });
}

// 12 base32 characters: 60 random bits, not guessable
function newId() {
  const abc = "abcdefghijklmnopqrstuvwxyz234567";
  return Array.from(crypto.getRandomValues(new Uint8Array(12)), (b) => abc[b & 31]).join("");
}

async function readCapped(stream, max) {
  const reader = stream.getReader();
  const chunks = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > max) {
      reader.cancel().catch(() => {}); // the rest is never read
      return null;
    }
    chunks.push(value);
  }
  const out = new Uint8Array(size);
  let at = 0;
  for (const c of chunks) {
    out.set(c, at);
    at += c.byteLength;
  }
  return out;
}

async function gunzip(bytes, max) {
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
  return readCapped(stream, max);
}

async function gzip(bytes) {
  const stream = new Blob([bytes]).stream().pipeThrough(new CompressionStream("gzip"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

const plain = (v) => v !== null && typeof v === "object" && !Array.isArray(v);

// The end of a text, at most max UTF-8 bytes of it (cut on a character boundary)
function tail(s, max) {
  const bytes = new TextEncoder().encode(s);
  if (bytes.length <= max) return s;
  let at = bytes.length - max;
  while (at < bytes.length && (bytes[at] & 0xc0) === 0x80) at++;
  return new TextDecoder().decode(bytes.subarray(at));
}

// What kettle-crashd writes to report.json (packages/kettle-crash/kettle-crashd) and the plugin
// shares: each field's type and size. Anything else is dropped, not refused, so an older or newer
// plugin's report still goes through.
const S = (max) => (v) => (typeof v === "string" ? v.slice(0, max) : undefined);
const N = (v) => (Number.isFinite(v) ? v : undefined);
const B = (v) => (typeof v === "boolean" ? v : undefined);
const L = (item, max) => (v) => (Array.isArray(v) ? v.slice(0, max).map(item).filter((x) => x !== undefined) : undefined);
const O = (shape) => (v) => {
  if (!plain(v)) return undefined;
  const out = {};
  for (const [k, check] of Object.entries(shape)) {
    const x = check(v[k]);
    if (x !== undefined) out[k] = x;
  }
  return out;
};
const PACKAGES = (v) =>
  plain(v)
    ? Object.fromEntries(Object.entries(v).filter(([k, x]) => /^[a-z0-9@._+-]{1,64}$/.test(k) && typeof x === "string")
        .slice(0, 32).map(([k, x]) => [k, x.slice(0, 128)]))
    : undefined;
const REPORT = O({
  kind: S(16),
  time_us: N,
  last_time_us: N,
  count: N,
  exe: S(1024),
  comm: S(64),
  cmdline: S(4096),
  signal: S(32),
  unit: S(256),
  reason: S(16),
  what: S(256),
  line: S(1024),
  app_id: N,
  device: S(256),
  driver: S(64),
  error: S(512),
  dump_skipped: S(64),
  dump_bytes: N,
  game: O({
    app_id: N,
    name: S(256),
    installdir: S(256),
    engine: O({ engine: S(32), platform: S(16), arch: S(16), exe: S(512), anticheat: L(S(32), 16) }),
    kettle_features: L(S(32), 16),
  }),
  game_process: B,
  compat_tool: S(128),
  system: O({
    os: O({ name: S(64), version_id: S(64), build_id: S(64), variant: S(64), variant_id: S(64) }),
    model: S(128),
    kernel: S(128),
    slot: S(16),
    uptime_s: N,
    packages: PACKAGES,
  }),
});

// A Kettle crash report in the shape the plugin sends, cut down to that shape; null if it isn't one
function sanitize(b) {
  if (!plain(b) || b.version !== 1 || !plain(b.report) || !plain(b.files)) return null;
  if (!KINDS.includes(b.report.kind) || b.report.system?.os?.name !== "Kettle Linux") return null;
  const files = {};
  for (const [name, body] of Object.entries(b.files)) {
    if (!FILES.includes(name) || typeof body !== "string") return null;
    // the plugin keeps the last 256 KB; older ones cut by characters, so a little over is trimmed
    files[name] = tail(body, MAX_FILE);
  }
  return { version: 1, id: S(64)(b.id) ?? "", report: REPORT(b.report), files };
}

// one more upload today from this address, and in all; false once either is at its cap
async function underDailyCap(env, ip) {
  if (!env.COUNTS) return true;
  const day = new Date().toISOString().slice(0, 10);
  const keys = [`ip:${await sha256(`${ip} ${day}`)}`, `all:${day}`];
  const counts = await Promise.all(keys.map((k) => env.COUNTS.get(k).then((v) => Number(v) || 0)));
  if (counts[0] >= DAY_PER_ADDRESS || counts[1] >= DAY_TOTAL) return false;
  // KV is eventually consistent: a burst can go a little over, which is fine for a cap like this
  await Promise.all(keys.map((k, i) => env.COUNTS.put(k, String(counts[i] + 1), { expirationTtl: 2 * 86400 })));
  return true;
}

async function sha256(s) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return Array.from(new Uint8Array(d), (b) => b.toString(16).padStart(2, "0")).join("");
}

async function upload(req, env, url) {
  const ip = req.headers.get("CF-Connecting-IP") || "";
  if (env.UPLOADS) {
    const { success } = await env.UPLOADS.limit({ key: ip });
    if (!success) return text("Too many reports, try again in a minute", 429);
  }
  const gz = await readCapped(req.body ?? new Blob().stream(), MAX_UPLOAD);
  if (!gz) return text("Report too big", 413);
  let bundle;
  try {
    const raw = await gunzip(gz, MAX_JSON);
    if (!raw) return text("Report too big", 413);
    bundle = JSON.parse(new TextDecoder().decode(raw));
  } catch {
    return text("Not a gzipped JSON report", 400);
  }
  bundle = sanitize(bundle);
  if (!bundle) return text("Not a Kettle crash report", 400);
  if (!(await underDailyCap(env, ip))) return text("Too many reports today, try again tomorrow", 429);
  const id = newId();
  const r = bundle.report;
  // what was checked is what's kept, not the upload as sent
  await env.REPORTS.put(`reports/${id}.json.gz`, await gzip(new TextEncoder().encode(JSON.stringify(bundle))), {
    httpMetadata: { contentType: "application/json", contentEncoding: "gzip" },
    customMetadata: {
      kind: r.kind,
      app: String(r.game?.app_id ?? ""),
      build: String(r.system?.os?.build_id ?? ""),
      variant: String(r.system?.os?.variant_id ?? ""),
    },
  });
  return json({ id, url: `${env.PUBLIC_URL ?? url.origin}/r/${id}` }, 201);
}

async function load(env, id) {
  const obj = await env.REPORTS.get(`reports/${id}.json.gz`);
  // past its 90 days: gone, even before the lifecycle rule gets to it
  if (!obj || Date.now() - obj.uploaded.getTime() > KEEP_S * 1000) return null;
  const raw = await gunzip(new Uint8Array(await obj.arrayBuffer()), MAX_JSON);
  return raw && JSON.parse(new TextDecoder().decode(raw));
}

// unlisted, and not kept in shared caches, so a removed report is gone at once
const VIEW_HEADERS = {
  "X-Robots-Tag": "noindex",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "Cache-Control": "private, max-age=300",
};

async function view(env, id, asJson) {
  const b = await load(env, id);
  if (!b) return text("No such report (reports are kept for 90 days)", 404);
  if (asJson) return json(b, 200, VIEW_HEADERS);
  return new Response(page(env, id, b), {
    headers: {
      ...VIEW_HEADERS,
      "Content-Type": "text/html; charset=utf-8",
      "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
    },
  });
}

async function authorized(req, env) {
  const want = env.ADMIN_TOKEN;
  const got = (req.headers.get("Authorization") || "").replace(/^Bearer /, "");
  if (!want || !got) return false;
  const [a, b] = await Promise.all([sha256(want), sha256(got)]);
  return crypto.subtle.timingSafeEqual(new TextEncoder().encode(a), new TextEncoder().encode(b));
}

// a removal request (kettlelinux.org/legal.html): the report is deleted for good
async function remove(req, env, id) {
  if (!(await authorized(req, env))) {
    // wrong tokens count against the address's upload limit
    if (env.UPLOADS && !(await env.UPLOADS.limit({ key: req.headers.get("CF-Connecting-IP") || "" })).success)
      return text("Too many requests, try again in a minute", 429);
    return text("Unauthorized", 401);
  }
  const key = `reports/${id}.json.gz`;
  if (!(await env.REPORTS.head(key))) return text("No such report", 404);
  await env.REPORTS.delete(key);
  return json({ ok: true });
}

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function title(r) {
  const game = r.game?.name ?? (r.game ? `App ${r.game.app_id}` : null);
  if (r.kind === "devcoredump") return `${r.driver === "msm" ? "GPU" : r.driver || "Device"} crash`;
  if (r.kind === "game") return `${game ?? "Game"}: ${r.reason === "gpu" ? "GPU lost" : "Windows exception"}`;
  return `${(r.game_process && game) || r.comm || "Program"} crashed (${r.signal ?? "signal"})`;
}

function facts(r) {
  const s = r.system ?? {};
  const p = s.packages ?? {};
  const mesa = Object.entries(p).find(([k]) => k.includes("mesa"));
  return [
    ["When", r.time_us ? new Date(r.time_us / 1000).toISOString().replace("T", " ").slice(0, 19) + " UTC" : ""],
    ["Device", s.model],
    ["Kettle", `${s.os?.version_id ?? ""} build ${s.os?.build_id ?? "?"} (${s.os?.variant_id ?? "?"}), slot ${s.slot ?? "?"}`],
    ["Kernel", s.kernel],
    ["Program", r.exe],
    ["Signal", r.signal],
    ["Error", r.what],
    ["Device driver", r.driver ? `${r.driver} (${r.device})` : ""],
    [r.game_process ? "Game" : "Game running", r.game ? `${r.game.name ?? "?"} (app ${r.game.app_id})` : ""],
    ["Compatibility tool", r.compat_tool],
    ["Kettle features", r.game ? (r.game.kettle_features ?? []).join(", ") || "none" : ""],
    ["Times", r.count > 1 ? String(r.count) : ""],
    ["Mesa", mesa?.[1]],
    ["FEX", p["fex-emu-wine"]],
    ["gamescope", p["gamescope"]],
    ["Steam", p["steam"]],
  ].filter(([, v]) => v);
}

function issueUrl(env, id, b) {
  const r = b.report;
  const body =
    `Crash report: ${env.PUBLIC_URL ?? ""}/r/${id}\n\n` +
    facts(r).map(([k, v]) => `- **${k}:** ${v}`).join("\n") +
    "\n\n**What were you doing when it crashed?**\n\n";
  const q = new URLSearchParams({ title: `Crash: ${title(r)}`, body, labels: "crash" });
  return `${ISSUES}?${q}`;
}

function page(env, id, b) {
  const r = b.report;
  const rows = facts(r).map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join("");
  const sections = [
    ["Stack trace", "backtrace.txt"],
    ["Game output", "output.txt"],
    ["Kernel log", "kernel.txt"],
    ["System log", "journal.txt"],
    ["Environment", "environ.txt"],
  ]
    .filter(([, f]) => b.files?.[f]?.trim())
    .map(([t, f]) => `<details${f === "backtrace.txt" || f === "output.txt" ? " open" : ""}><summary>${esc(t)}</summary><pre>${esc(b.files[f])}</pre></details>`)
    .join("");
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title(r))} · Kettle crash report</title>
<style>
:root{--bg:#f6f6f4;--fg:#1d1d1b;--muted:#666;--card:#fff;--line:#ddd;--accent:#c4512b}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--fg:#ecebe6;--muted:#9a9a95;--card:#1f1f1d;--line:#333;--accent:#e2794f}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}
main{max-width:900px;margin:0 auto;padding:24px 16px}
h1{font-size:1.4rem;margin:0 0 4px}.sub{color:var(--muted);margin:0 0 20px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden}
th,td{text-align:left;padding:8px 12px;border-bottom:1px solid var(--line);vertical-align:top;word-break:break-word}
th{width:30%;color:var(--muted);font-weight:500;word-break:normal;overflow-wrap:normal}
.actions{margin:20px 0;display:flex;gap:12px;flex-wrap:wrap}
.btn{display:inline-block;padding:10px 16px;border-radius:8px;background:var(--accent);color:#fff;text-decoration:none;font-weight:600}
.btn.alt{background:transparent;color:var(--fg);border:1px solid var(--line)}
details{margin:12px 0;background:var(--card);border:1px solid var(--line);border-radius:8px}
summary{cursor:pointer;padding:10px 12px;font-weight:600}
pre{margin:0;padding:12px;overflow-x:auto;font-size:12px;line-height:1.4;border-top:1px solid var(--line);white-space:pre-wrap;word-break:break-all}
</style></head><body><main>
<h1>${esc(title(r))}</h1>
<p class="sub">Kettle Linux crash report <code>${esc(id)}</code>, shared from the device. Personal details were removed before upload. Kept for 90 days.</p>
<table>${rows}</table>
<div class="actions"><a class="btn" href="${esc(issueUrl(env, id, b))}">Report on GitHub</a><a class="btn alt" href="/r/${esc(id)}.json">Raw report</a></div>
${sections}
</main></body></html>`;
}
