// Kettle Linux game database (games.kettlelinux.org): a Cloudflare Worker in front of a D1
// database. Players share settings that made a game work from the Game Settings plugin
// (packages/kettle-decky-plugins/game-settings), after playing with them; others apply them and
// say whether they worked for them too. The Kettle team approves entries (verified) in the admin
// page. The public pages are on kettlelinux.org (site/games.html), which reads the API here.
//
// Public (readable from any site):
//   GET  /v1/catalog               the options Game Settings offers (shared/game-options.json)
//   GET  /v1/games                 games with entries: [{app_id, game, approved, pending, variants, updated}]
//   GET  /v1/games/<app id>        a game's entries, verified first, and its engine
//   POST /v1/profiles              share settings: answers {id, url}
//   POST /v1/profiles/<id>/votes   {install_id, works, device, variant, build, engine?}
//   GET  /, /g/<app id>            redirect to the site's pages
//
// Admin (Authorization: Bearer $ADMIN_TOKEN, a wrangler secret); the page at /admin uses these:
//   GET    /v1/admin/stats
//   GET    /v1/admin/engines                per engine: games, entries, and how the settings in them fared
//   GET    /v1/admin/profiles?status=pending|approved|rejected|all&q=<game or app id>&offset=
//   GET    /v1/admin/profiles/<id>          the entry and its votes
//   POST   /v1/admin/profiles/<id>          {status?, notes?, rating?}
//   DELETE /v1/admin/profiles/<id>
//   POST   /v1/admin/bulk                   {ids: [...], status} or {ids: [...], delete: true}
//   GET    /v1/admin/bans
//   POST   /v1/admin/bans                   {submitter, reason}: rejects their entries, drops their votes
//   DELETE /v1/admin/bans/<submitter>
//
// Every setting is checked against the plugin's own catalog (shared/game-options.json), so an
// entry can only hold options Game Settings offers, never arbitrary launch options.
//
// A share or a vote can say which engine the device found the game built on ({engine, platform,
// arch, anticheat}, ids from shared/engines.json): kept per game and device in engine_reports, so what
// works can be told apart by engine. One the server doesn't know is left out, never refused.
import catalog from "../../../packages/kettle-decky-plugins/shared/game-options.json";
import engines from "../../../packages/kettle-decky-plugins/shared/engines.json";
import ADMIN_HTML from "./admin/admin.html";
import ADMIN_JS from "./admin/admin.client.js";

const MAX_BODY = 16 << 10;
const RATINGS = ["great", "playable"];
const STATUSES = ["pending", "approved", "rejected"];
// community entries this much more often reported broken than confirmed are hidden
const HIDE_BROKEN = 3;
const PAGE = 50;

const CHOICES = new Map(catalog.options.map((o) => [o.id, new Set(o.choices.map((c) => c.value))]));
const MANAGED = new Set([
  ...catalog.custom.env_reserved,
  ...catalog.options.map((o) => o.target.env ?? o.target.flags ?? "DXVK_CONFIG"),
]);
const ENV_NAME = new RegExp(catalog.custom.env_name);
const ENV_VALUE = new RegExp(catalog.custom.env_value);
const DLL_NAME = new RegExp(catalog.custom.dll_name);
const DLL_MODES = new Set(catalog.custom.dll_modes.map((m) => m.value));
const ENGINES = new Set(engines.engines.map((e) => e.id));
const PLATFORMS = new Set(engines.platforms.map((p) => p.id));
const ARCHS = new Set(engines.archs.map((a) => a.id));
const ANTICHEAT = new Set(engines.anticheat.map((a) => a.id));
// what the site and the admin page need to describe entries
const PUBLIC_CATALOG = {
  sections: catalog.sections,
  options: catalog.options.map(({ id, section, label, target, choices }) => ({ id, section, label, target, choices })),
  dll_modes: catalog.custom.dll_modes,
};

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const p = url.pathname;
    const site = env.SITE_URL ?? "https://kettlelinux.org";
    let m;
    try {
      if (p.startsWith("/v1/admin/")) return await admin(req, env, url);
      if (req.method === "OPTIONS" && p.startsWith("/v1/")) return cors(new Response(null, { status: 204 }));
      if (p === "/v1/catalog" && req.method === "GET") return cors(json(PUBLIC_CATALOG, 200, 3600));
      if (p === "/v1/games" && req.method === "GET") return cors(json({ games: await index(env) }, 200, 120));
      if ((m = p.match(/^\/v1\/games\/(\d{1,10})$/)) && req.method === "GET")
        return cors(json({
          app_id: Number(m[1]),
          engine: await gameEngine(env, Number(m[1])),
          profiles: await forGame(env, Number(m[1])),
        }, 200, 60));
      if (p === "/v1/profiles") return req.method === "POST" ? await submit(req, env, url) : text("POST only", 405);
      if ((m = p.match(/^\/v1\/profiles\/([a-z2-7]{12})\/votes$/)))
        return req.method === "POST" ? await vote(req, env, m[1]) : text("POST only", 405);
      if (p === "/admin" || p === "/admin/") return adminPage(ADMIN_HTML, "text/html; charset=utf-8");
      if (p === "/admin/admin.js") return adminPage(ADMIN_JS, "text/javascript; charset=utf-8");
      if (p === "/") return Response.redirect(`${site}/games.html`, 302);
      if ((m = p.match(/^\/g\/(\d{1,10})$/))) return Response.redirect(`${site}/games.html?app=${m[1]}`, 302);
    } catch (e) {
      if (e instanceof Refused) return text(e.message, e.status);
      throw e;
    }
    return text("Not found", 404);
  },
};

class Refused extends Error {
  constructor(message, status = 400) {
    super(message);
    this.status = status;
  }
}

function text(body, status = 200) {
  return new Response(body + "\n", { status, headers: { "Content-Type": "text/plain; charset=utf-8" } });
}

function json(body, status = 200, maxAge = 0) {
  const headers = { "Content-Type": "application/json" };
  headers["Cache-Control"] = maxAge ? `public, max-age=${maxAge}` : "no-store";
  return new Response(JSON.stringify(body), { status, headers });
}

// public, read-only data: any site may read it (kettlelinux.org's Games page does)
function cors(res) {
  res.headers.set("Access-Control-Allow-Origin", "*");
  res.headers.set("Access-Control-Allow-Methods", "GET, OPTIONS");
  res.headers.set("Access-Control-Max-Age", "86400");
  return res;
}

function adminPage(body, type) {
  return new Response(body, {
    headers: {
      "Content-Type": type,
      "Content-Security-Policy":
        "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; " +
        "img-src https://cdn.cloudflare.steamstatic.com; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
      "X-Robots-Tag": "noindex",
      "Referrer-Policy": "no-referrer",
      "Cache-Control": "no-cache",
    },
  });
}

function newId() {
  const abc = "abcdefghijklmnopqrstuvwxyz234567";
  return Array.from(crypto.getRandomValues(new Uint8Array(12)), (b) => abc[b & 31]).join("");
}

async function sha256(s) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return Array.from(new Uint8Array(d), (b) => b.toString(16).padStart(2, "0")).join("");
}

async function body(req) {
  const raw = await req.text();
  if (raw.length > MAX_BODY) throw new Refused("Too big", 413);
  try {
    return JSON.parse(raw);
  } catch {
    throw new Refused("Not JSON");
  }
}

async function limited(env, binding, req) {
  if (!env[binding]) return;
  const { success } = await env[binding].limit({ key: req.headers.get("CF-Connecting-IP") || "" });
  if (!success) throw new Refused("Too many requests, try again in a minute", 429);
}

const now = () => Math.floor(Date.now() / 1000);

// ---------- validation ----------

const str = (v, re, what) => {
  if (typeof v !== "string" || !re.test(v)) throw new Refused(`Bad ${what}`);
  return v;
};

function pairs(items, valid, max, what) {
  if (!Array.isArray(items) || items.length > max) throw new Refused(`Bad ${what}`);
  const seen = new Set();
  for (const it of items) {
    if (!Array.isArray(it) || it.length !== 2 || !valid(it[0], it[1]) || seen.has(it[0])) throw new Refused(`Bad ${what}`);
    seen.add(it[0]);
  }
  return [...items].sort((a, b) => (a[0] < b[0] ? -1 : 1));
}

const validEnv = (n, v) =>
  typeof n === "string" && typeof v === "string" && ENV_NAME.test(n) && ENV_VALUE.test(v) &&
  catalog.custom.env_prefixes.some((p) => n.startsWith(p)) && !MANAGED.has(n);
const validDll = (d, m) => typeof d === "string" && typeof m === "string" && DLL_NAME.test(d) && DLL_MODES.has(m);

// A profile in the plugin's shape, and nothing else
function profile(b) {
  if (!b || typeof b.settings !== "object" || Array.isArray(b.settings)) throw new Refused("Bad settings");
  const settings = {};
  for (const k of Object.keys(b.settings).sort()) {
    if (!CHOICES.get(k)?.has(b.settings[k])) throw new Refused(`Bad setting ${String(k).slice(0, 40)}`);
    settings[k] = b.settings[k];
  }
  const tool = b.compat_tool ?? null;
  if (tool !== null) str(tool, /^[A-Za-z0-9_.-]{1,64}$/, "compatibility tool");
  return {
    settings,
    env: pairs(b.env ?? [], validEnv, catalog.custom.max_env, "variables"),
    dlls: pairs(b.dlls ?? [], validDll, catalog.custom.max_dlls, "DLL overrides"),
    compat_tool: tool,
  };
}

// the engine a device reported, or null (none, or not one this server knows)
function engineReport(e) {
  if (!e || typeof e !== "object" || !ENGINES.has(e.engine) || !PLATFORMS.has(e.platform ?? "") || !ARCHS.has(e.arch ?? ""))
    return null;
  const ac = Array.isArray(e.anticheat) ? e.anticheat : [];
  if (ac.length > ANTICHEAT.size || !ac.every((a) => ANTICHEAT.has(a))) return null;
  return { engine: e.engine, platform: e.platform ?? "", arch: e.arch ?? "", anticheat: [...new Set(ac)].sort() };
}

function saveEngine(env, appId, reporter, e) {
  if (!e) return null;
  return env.DB.prepare(
    `INSERT INTO engine_reports (app_id, reporter, engine, platform, arch, anticheat, created) VALUES (?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT (app_id, reporter) DO UPDATE SET engine = excluded.engine, platform = excluded.platform,
       arch = excluded.arch, anticheat = excluded.anticheat, created = excluded.created`,
  ).bind(appId, reporter, e.engine, e.platform, e.arch, JSON.stringify(e.anticheat), now()).run();
}

// each game's engine: the one most devices reported
// (with the platform, arch and anti-cheat of its latest report)
const TOP_ENGINE = `top_engine AS (
  SELECT app_id, engine, platform, arch, anticheat, n FROM (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY app_id ORDER BY n DESC, created DESC) AS r FROM (
      SELECT *, COUNT(*) OVER (PARTITION BY app_id, engine) AS n FROM engine_reports))
  WHERE r = 1)`;

async function gameEngine(env, appId) {
  const r = await env.DB.prepare(`WITH ${TOP_ENGINE} SELECT engine, platform, arch, anticheat, n FROM top_engine WHERE app_id = ?`)
    .bind(appId)
    .first();
  return r ? { engine: r.engine, platform: r.platform, arch: r.arch, anticheat: JSON.parse(r.anticheat), reports: r.n } : null;
}

const clean = (s, max) => String(s ?? "").replace(/[\u0000-\u001f\u007f<>]/g, " ").replace(/\s+/g, " ").trim().slice(0, max);

async function banned(env, hash) {
  return !!(await env.DB.prepare("SELECT 1 FROM banned WHERE submitter = ?").bind(hash).first());
}

// ---------- reading ----------

const COUNTS = `
  1 + (SELECT COUNT(*) FROM votes v WHERE v.profile_id = p.id AND v.works = 1) AS works,
  (SELECT COUNT(*) FROM votes v WHERE v.profile_id = p.id AND v.works = 0) AS broken`;

function entry(r, admin = false) {
  const e = {
    id: r.id,
    app_id: r.app_id,
    game: r.game,
    status: r.status,
    rating: r.rating,
    device: r.device,
    variant: r.variant,
    build: r.build,
    compat_tool: r.compat_tool,
    settings: JSON.parse(r.settings),
    env: JSON.parse(r.env),
    dlls: JSON.parse(r.dlls),
    notes: admin || r.status === "approved" ? r.notes : "",
    works: r.works,
    broken: r.broken,
    created: r.created,
  };
  if (admin)
    Object.assign(e, { submitter: r.submitter, by_submitter: r.by_submitter, banned: !!r.banned, reviewed: r.reviewed });
  return e;
}

async function forGame(env, appId) {
  const { results } = await env.DB.prepare(
    `SELECT p.*, ${COUNTS} FROM profiles p WHERE p.app_id = ? AND p.status != 'rejected'`,
  )
    .bind(appId)
    .all();
  return results
    .filter((r) => r.status === "approved" || r.broken < r.works + HIDE_BROKEN)
    .map((r) => entry(r))
    .sort((a, b) => (a.status === b.status ? b.works - b.broken - (a.works - a.broken) : a.status === "approved" ? -1 : 1));
}

async function index(env) {
  const { results } = await env.DB.prepare(
    `SELECT app_id, MAX(game) AS game, SUM(status = 'approved') AS approved, SUM(status = 'pending') AS pending,
            GROUP_CONCAT(DISTINCT variant) AS variants, MAX(created) AS updated
     FROM profiles WHERE status != 'rejected' GROUP BY app_id ORDER BY game COLLATE NOCASE`,
  ).all();
  return results.map((r) => ({ ...r, variants: r.variants ? r.variants.split(",") : [] }));
}

// ---------- writing ----------

async function submit(req, env, url) {
  await limited(env, "SUBMITS", req);
  const b = await body(req);
  const installId = str(b.install_id, /^[0-9a-f]{32}$/, "install id");
  if (!Number.isInteger(b.app_id) || b.app_id <= 0 || b.app_id > 0xffffffff) throw new Refused("Bad app id");
  const p = profile(b);
  const game = clean(b.game, 128);
  if (!game) throw new Refused("Bad game name");
  const variant = str(b.variant, /^[a-z0-9_-]{1,32}$/, "variant");
  const build = str(b.build, /^[A-Za-z0-9._-]{1,20}$/, "build");
  const device = clean(b.device, 64) || variant;
  if (!RATINGS.includes(b.rating)) throw new Refused("Bad rating");
  const notes = clean(b.notes, 500);
  const submitter = await sha256(installId);
  if (await banned(env, submitter)) throw new Refused("Sharing from this device is turned off", 403);
  const hash = (await sha256(JSON.stringify(p))).slice(0, 32);
  await saveEngine(env, b.app_id, submitter, engineReport(b.engine));
  const pageUrl = `${env.PUBLIC_URL ?? url.origin}/g/${b.app_id}`;

  // the same settings for the same game and device already shared: that's a vote for them
  const same = await env.DB.prepare("SELECT id, submitter FROM profiles WHERE app_id = ? AND variant = ? AND hash = ?")
    .bind(b.app_id, variant, hash)
    .first();
  if (same) {
    if (same.submitter !== submitter) await addVote(env, same.id, submitter, true, device, variant, build);
    return json({ id: same.id, url: pageUrl, existing: true }, 200);
  }
  const id = newId();
  await env.DB.prepare(
    `INSERT INTO profiles (id, app_id, game, device, variant, build, hash, compat_tool, settings, env, dlls,
                           rating, notes, submitter, created)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  )
    .bind(id, b.app_id, game, device, variant, build, hash, p.compat_tool, JSON.stringify(p.settings),
      JSON.stringify(p.env), JSON.stringify(p.dlls), b.rating, notes, submitter, now())
    .run();
  return json({ id, url: pageUrl }, 201);
}

function addVote(env, id, voter, works, device, variant, build) {
  return env.DB.prepare(
    `INSERT INTO votes (profile_id, voter, works, device, variant, build, created) VALUES (?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT (profile_id, voter) DO UPDATE SET works = excluded.works, build = excluded.build, created = excluded.created`,
  )
    .bind(id, voter, works ? 1 : 0, device, variant, build, now())
    .run();
}

async function vote(req, env, id) {
  await limited(env, "VOTES", req);
  const b = await body(req);
  const voter = await sha256(str(b.install_id, /^[0-9a-f]{32}$/, "install id"));
  if (typeof b.works !== "boolean") throw new Refused("Bad vote");
  const variant = str(b.variant, /^[a-z0-9_-]{1,32}$/, "variant");
  const build = str(b.build, /^[A-Za-z0-9._-]{1,20}$/, "build");
  if (await banned(env, voter)) throw new Refused("Voting from this device is turned off", 403);
  const p = await env.DB.prepare("SELECT app_id, submitter FROM profiles WHERE id = ? AND status != 'rejected'").bind(id).first();
  if (!p) throw new Refused("No such entry", 404);
  await saveEngine(env, p.app_id, voter, engineReport(b.engine));
  if (p.submitter !== voter) await addVote(env, id, voter, b.works, clean(b.device, 64) || variant, variant, build);
  return json({ ok: true });
}

// ---------- admin ----------

async function authorized(req, env) {
  const want = env.ADMIN_TOKEN;
  const got = (req.headers.get("Authorization") || "").replace(/^Bearer /, "");
  if (!want || !got) return false;
  const [a, b] = await Promise.all([sha256(want), sha256(got)]);
  return crypto.subtle.timingSafeEqual(new TextEncoder().encode(a), new TextEncoder().encode(b));
}

const ADMIN_SELECT = `SELECT p.*, ${COUNTS},
  (SELECT COUNT(*) FROM profiles q WHERE q.submitter = p.submitter) AS by_submitter,
  EXISTS (SELECT 1 FROM banned b WHERE b.submitter = p.submitter) AS banned
  FROM profiles p`;

async function admin(req, env, url) {
  if (!(await authorized(req, env))) return text("Unauthorized", 401);
  const p = url.pathname;
  let m;

  if (p === "/v1/admin/stats" && req.method === "GET") {
    const [byStatus, votes, week, bans, games] = await env.DB.batch([
      env.DB.prepare("SELECT status, COUNT(*) AS n FROM profiles GROUP BY status"),
      env.DB.prepare("SELECT COUNT(*) AS n, SUM(works = 0) AS broken FROM votes"),
      env.DB.prepare("SELECT COUNT(*) AS n FROM profiles WHERE created > ?").bind(now() - 7 * 86400),
      env.DB.prepare("SELECT COUNT(*) AS n FROM banned"),
      env.DB.prepare("SELECT COUNT(DISTINCT app_id) AS n FROM profiles WHERE status != 'rejected'"),
    ]);
    const counts = Object.fromEntries(STATUSES.map((s) => [s, 0]));
    for (const r of byStatus.results) counts[r.status] = r.n;
    return json({
      ...counts,
      votes: votes.results[0].n,
      broken_votes: votes.results[0].broken ?? 0,
      last_week: week.results[0].n,
      bans: bans.results[0].n,
      games: games.results[0].n,
    });
  }

  // per engine: its games, their entries (not rejected) and, for every setting in them, how
  // many entries have it and how their votes went (each entry counts its sharer as a works)
  if (p === "/v1/admin/engines" && req.method === "GET") {
    const [games, entries] = await env.DB.batch([
      env.DB.prepare(`WITH ${TOP_ENGINE} SELECT engine, COUNT(*) AS games, SUM(anticheat != '[]') AS anticheat,
                      SUM(arch = 'x86') AS x86, SUM(platform = 'linux') AS linux FROM top_engine GROUP BY engine`),
      env.DB.prepare(`WITH ${TOP_ENGINE} SELECT t.engine, p.status, p.settings, ${COUNTS}
                      FROM top_engine t JOIN profiles p ON p.app_id = t.app_id WHERE p.status != 'rejected'`),
    ]);
    const out = new Map(games.results.map((g) => [g.engine, {
      ...g, entries: 0, approved: 0, works: 0, broken: 0, settings: {},
    }]));
    for (const r of entries.results) {
      const e = out.get(r.engine);
      e.entries++;
      e.approved += r.status === "approved";
      e.works += r.works;
      e.broken += r.broken;
      for (const [k, v] of Object.entries(JSON.parse(r.settings))) {
        const s = (e.settings[`${k}=${v}`] ??= { entries: 0, works: 0, broken: 0 });
        s.entries++;
        s.works += r.works;
        s.broken += r.broken;
      }
    }
    return json({
      engines: [...out.values()].sort((a, b) => b.games - a.games),
      labels: Object.fromEntries(engines.engines.map((e) => [e.id, e.label])),
    });
  }

  if (p === "/v1/admin/profiles" && req.method === "GET") {
    const status = url.searchParams.get("status") ?? "pending";
    if (status !== "all" && !STATUSES.includes(status)) throw new Refused("Bad status");
    const q = (url.searchParams.get("q") ?? "").trim().slice(0, 100);
    const submitter = (url.searchParams.get("submitter") ?? "").trim();
    const offset = Math.max(0, Number(url.searchParams.get("offset")) || 0);
    const where = [];
    const args = [];
    const add = (sql, arg) => {
      where.push(sql);
      args.push(arg);
    };
    if (status !== "all") add("p.status = ?", status);
    if (/^\d+$/.test(q)) add("p.app_id = ?", Number(q));
    else if (q) add("p.game LIKE ? ESCAPE '\\'", `%${q.replace(/[\\%_]/g, (c) => "\\" + c)}%`);
    if (/^[0-9a-f]{64}$/.test(submitter)) add("p.submitter = ?", submitter);
    const order = status === "pending" ? "p.created ASC" : "p.created DESC";
    const { results } = await env.DB.prepare(
      `${ADMIN_SELECT} ${where.length ? "WHERE " + where.join(" AND ") : ""} ORDER BY ${order} LIMIT ? OFFSET ?`,
    )
      .bind(...args, PAGE + 1, offset)
      .all();
    return json({ profiles: results.slice(0, PAGE).map((r) => entry(r, true)), more: results.length > PAGE, offset });
  }

  if (p === "/v1/admin/bulk" && req.method === "POST") {
    const b = await body(req);
    const ids = Array.isArray(b.ids) ? b.ids.filter((i) => typeof i === "string" && /^[a-z2-7]{12}$/.test(i)).slice(0, 200) : [];
    if (!ids.length) throw new Refused("No entries");
    if (b.delete === true) {
      await env.DB.batch(ids.flatMap((id) => [
        env.DB.prepare("DELETE FROM votes WHERE profile_id = ?").bind(id),
        env.DB.prepare("DELETE FROM profiles WHERE id = ?").bind(id),
      ]));
    } else {
      if (!STATUSES.includes(b.status)) throw new Refused("Bad status");
      await env.DB.batch(ids.map((id) =>
        env.DB.prepare("UPDATE profiles SET status = ?, reviewed = ? WHERE id = ?").bind(b.status, now(), id)));
    }
    return json({ ok: true, count: ids.length });
  }

  if (p === "/v1/admin/bans") {
    if (req.method === "GET") {
      const { results } = await env.DB.prepare(
        `SELECT b.*, (SELECT COUNT(*) FROM profiles q WHERE q.submitter = b.submitter) AS entries
         FROM banned b ORDER BY created DESC`,
      ).all();
      return json({ bans: results });
    }
    if (req.method === "POST") {
      const b = await body(req);
      const hash = str(b.submitter, /^[0-9a-f]{64}$/, "submitter");
      await env.DB.batch([
        env.DB.prepare(
          "INSERT INTO banned (submitter, reason, created) VALUES (?, ?, ?) ON CONFLICT (submitter) DO UPDATE SET reason = excluded.reason",
        ).bind(hash, clean(b.reason, 200), now()),
        env.DB.prepare("UPDATE profiles SET status = 'rejected', reviewed = ? WHERE submitter = ? AND status != 'rejected'").bind(now(), hash),
        env.DB.prepare("DELETE FROM votes WHERE voter = ?").bind(hash),
        env.DB.prepare("DELETE FROM engine_reports WHERE reporter = ?").bind(hash),
      ]);
      return json({ ok: true });
    }
  }
  if ((m = p.match(/^\/v1\/admin\/bans\/([0-9a-f]{64})$/)) && req.method === "DELETE") {
    await env.DB.prepare("DELETE FROM banned WHERE submitter = ?").bind(m[1]).run();
    return json({ ok: true });
  }

  m = p.match(/^\/v1\/admin\/profiles\/([a-z2-7]{12})$/);
  if (!m) return text("Not found", 404);
  const id = m[1];
  if (req.method === "GET") {
    const r = await env.DB.prepare(`${ADMIN_SELECT} WHERE p.id = ?`).bind(id).first();
    if (!r) return text("No such entry", 404);
    const { results: votes } = await env.DB.prepare(
      "SELECT works, device, variant, build, created, voter FROM votes WHERE profile_id = ? ORDER BY created DESC",
    )
      .bind(id)
      .all();
    return json({ profile: entry(r, true), votes });
  }
  if (req.method === "DELETE") {
    await env.DB.batch([
      env.DB.prepare("DELETE FROM votes WHERE profile_id = ?").bind(id),
      env.DB.prepare("DELETE FROM profiles WHERE id = ?").bind(id),
    ]);
    return json({ ok: true });
  }
  if (req.method === "POST") {
    const b = await body(req);
    const sets = [];
    const args = [];
    const set = (sql, arg) => {
      sets.push(sql);
      args.push(arg);
    };
    if (b.status !== undefined) {
      if (!STATUSES.includes(b.status)) throw new Refused("Bad status");
      set("status = ?", b.status);
      set("reviewed = ?", now());
    }
    if (b.notes !== undefined) set("notes = ?", clean(b.notes, 500));
    if (b.rating !== undefined) {
      if (!RATINGS.includes(b.rating)) throw new Refused("Bad rating");
      set("rating = ?", b.rating);
    }
    if (!sets.length) throw new Refused("Nothing to change");
    const r = await env.DB.prepare(`UPDATE profiles SET ${sets.join(", ")} WHERE id = ?`).bind(...args, id).run();
    return r.meta.changes ? json({ ok: true }) : text("No such entry", 404);
  }
  return text("Method not allowed", 405);
}
