// The Games page: known good settings from the Kettle game database (server/game-db), which the
// Game Settings plugin shares to. games.html lists the games; games.html?app=<id> shows one.
// Everything players sent is put on the page as text, never as HTML.
const API = ["localhost", "127.0.0.1"].includes(location.hostname) ? "http://127.0.0.1:8787" : "https://games.kettlelinux.org";
const DEVICES = { odin2portal: "AYN Odin 2 Portal", thor: "AYN Thor", rp5: "Retroid Pocket 5" };
const STEAM_IMG = (id) => `https://cdn.cloudflare.steamstatic.com/steam/apps/${id}/header.jpg`;

function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children.filter((c) => c !== null && c !== undefined && c !== false));
  return node;
}

async function get(path) {
  const res = await fetch(API + path);
  if (!res.ok) throw new Error(`game database ${res.status}`);
  return res.json();
}

function ago(seconds) {
  const s = Date.now() / 1000 - seconds;
  for (const [unit, secs] of [["year", 31536000], ["month", 2592000], ["day", 86400], ["hour", 3600], ["minute", 60]]) {
    if (s >= secs) {
      const n = Math.floor(s / secs);
      return `${n} ${unit}${n > 1 ? "s" : ""} ago`;
    }
  }
  return "just now";
}

function gameImage(id, lazy = true) {
  const img = el("img", { src: STEAM_IMG(id), alt: "", loading: lazy ? "lazy" : "eager", width: 460, height: 215 });
  img.addEventListener("error", () => img.classList.add("missing"));
  return img;
}

// ---------- the list ----------

let games = [];

function renderList() {
  const q = document.getElementById("q").value.trim().toLowerCase();
  const device = document.getElementById("device").value;
  const verified = document.getElementById("verified").checked;
  const shown = games.filter((g) =>
    (!q || g.game.toLowerCase().includes(q) || String(g.app_id) === q) &&
    (!device || g.variants.includes(device)) &&
    (!verified || g.approved > 0));
  const box = document.getElementById("games");
  document.getElementById("count").textContent = games.length
    ? `${shown.length} of ${games.length} game${games.length > 1 ? "s" : ""}`
    : "";
  if (!games.length) {
    box.replaceChildren(el("div", { className: "card" },
      el("p", {}, "Nothing shared yet. Be the first: get a game running with Game Settings, then share its settings.")));
    return;
  }
  if (!shown.length) {
    box.replaceChildren(el("div", { className: "card" }, el("p", { className: "muted", textContent: "No games match." })));
    return;
  }
  box.replaceChildren(...shown.map((g) =>
    el("a", { className: "game-card", href: `games.html?app=${g.app_id}` },
      gameImage(g.app_id),
      el("div", { className: "game-card-body" },
        el("h3", { textContent: g.game }),
        el("div", { className: "badges" },
          g.approved ? el("span", { className: "badge verified", textContent: `${g.approved} verified` }) : null,
          g.pending ? el("span", { className: "badge", textContent: `${g.pending} community` }) : null),
        el("p", { className: "muted small", textContent:
          `${g.variants.map((v) => DEVICES[v] ?? v).join(", ")} · updated ${ago(g.updated)}` })))));
}

async function showList() {
  try {
    games = (await get("/v1/games")).games;
  } catch {
    document.getElementById("games").replaceChildren(el("div", { className: "card" },
      el("p", { textContent: "Couldn't reach the game database. Try again later." })));
    return;
  }
  for (const id of ["q", "device", "verified"]) document.getElementById(id).addEventListener("input", renderList);
  renderList();
}

// ---------- one game ----------

// The entry as launch options, for typing into Steam's Properties by hand
function launchOptions(e, catalog) {
  const opts = new Map(catalog.options.map((o) => [o.id, o]));
  const words = [];
  const flags = new Map();
  const dxvk = [];
  for (const [k, v] of Object.entries(e.settings)) {
    const t = opts.get(k)?.target;
    if (!t) continue;
    if (t.env) words.push(`${t.env}=${v}`);
    else if (t.flags) flags.set(t.flags, [...(flags.get(t.flags) ?? []), t.flag]);
    else if (t.dxvk) dxvk.push(`${t.dxvk}=${v}`);
  }
  for (const [name, list] of flags) words.push(`${name}=${list.join(",")}`);
  if (dxvk.length) words.push(`DXVK_CONFIG="${dxvk.join(";")}"`);
  for (const [n, v] of e.env) words.push(/;/.test(v) ? `${n}="${v}"` : `${n}=${v}`);
  if (e.dlls.length) words.push(`WINEDLLOVERRIDES="${e.dlls.map(([d, m]) => `${d}=${m}`).join(";")}"`);
  return words.length ? `${words.join(" ")} %command%` : "";
}

function settingsBySection(e, catalog) {
  const groups = catalog.sections.map((s) => ({ title: s.title, items: [] }));
  const opts = new Map(catalog.options.map((o) => [o.id, o]));
  for (const [k, v] of Object.entries(e.settings)) {
    const o = opts.get(k);
    if (!o) continue;
    const g = groups[catalog.sections.findIndex((s) => s.id === o.section)];
    g?.items.push(o.choices.length === 1 ? o.label : `${o.label}: ${o.choices.find((c) => c.value === v)?.label ?? v}`);
  }
  const custom = [
    ...e.env.map(([n, v]) => `${n}=${v}`),
    ...e.dlls.map(([d, m]) => `${d}.dll: ${catalog.dll_modes.find((x) => x.value === m)?.label ?? m}`),
  ];
  if (custom.length) groups.push({ title: "Custom", items: custom });
  return groups.filter((g) => g.items.length);
}

function entryCard(e, catalog) {
  const groups = settingsBySection(e, catalog);
  const lo = launchOptions(e, catalog);
  const copy = el("button", { className: "btn small-btn", type: "button", textContent: "Copy" });
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(lo);
      copy.textContent = "Copied";
    } catch {
      copy.textContent = "Select and copy";
    }
    setTimeout(() => (copy.textContent = "Copy"), 2000);
  });
  return el("div", { className: "card entry" },
    el("div", { className: "badges" },
      el("span", { className: e.status === "approved" ? "badge verified" : "badge", textContent: e.status === "approved" ? "Verified" : "Community" }),
      el("span", { className: `badge ${e.rating}`, textContent: e.rating === "great" ? "Runs great" : "Playable" })),
    el("p", { className: "muted small", textContent:
      `${DEVICES[e.variant] ?? (e.status === "approved" ? e.device : e.variant)} · Kettle ${e.build} · shared ${ago(e.created)}` }),
    el("p", { className: "small" },
      el("span", { className: "works", textContent: `Works for ${e.works}` }),
      e.broken ? el("span", { className: "broken", textContent: ` · didn't for ${e.broken}` }) : null),
    groups.length
      ? el("div", { className: "settings-groups" }, ...groups.map((g) =>
          el("div", {}, el("h4", { textContent: g.title }), el("ul", {}, ...g.items.map((t) => el("li", { textContent: t }))))))
      : el("p", { textContent: "Runs with the default settings." }),
    e.compat_tool ? el("p", { className: "small" }, "Proton version: ", el("code", { textContent: e.compat_tool })) : null,
    e.notes ? el("blockquote", { textContent: e.notes }) : null,
    lo ? el("div", { className: "launch" },
      el("p", { className: "muted small", textContent: "Without the plugin: Steam > game Properties > Launch options" }),
      el("div", { className: "launch-line" }, el("code", { textContent: lo }), copy)) : null);
}

async function showGame(appId) {
  document.getElementById("games-list").classList.add("hidden");
  document.getElementById("game").classList.remove("hidden");
  const body = document.getElementById("game-body");
  body.replaceChildren(el("p", { className: "muted", textContent: "Loading…" }));
  let data, catalog;
  try {
    [data, catalog] = await Promise.all([get(`/v1/games/${appId}`), get("/v1/catalog")]);
  } catch {
    body.replaceChildren(el("div", { className: "card" }, el("p", { textContent: "Couldn't reach the game database. Try again later." })));
    return;
  }
  const entries = data.profiles;
  // the server names the game from a verified entry when there is one
  const name = data.game ?? entries[0]?.game ?? `Steam app ${appId}`;
  document.title = `${name} · Kettle Linux game settings`;
  const verified = entries.filter((e) => e.status === "approved");
  const community = entries.filter((e) => e.status !== "approved");
  const parts = [
    el("div", { className: "game-head" },
      gameImage(appId, false),
      el("div", {},
        el("h1", { textContent: name }),
        el("p", { className: "muted small" }, `Steam app ${appId} · `,
          el("a", { href: `https://store.steampowered.com/app/${appId}/`, textContent: "Store page" })),
        el("p", { className: "small", textContent:
          "To use one: in Game Mode, Quick Access > Game Settings, pick the game, then Known good settings > Apply." }))),
    entries.length ? null : el("div", { className: "card" },
      el("p", { textContent: "Nothing shared for this game yet. Once you get it running with Game Settings, share your settings." })),
    verified.length ? el("h2", { textContent: "Verified" }) : null,
    ...verified.map((e) => entryCard(e, catalog)),
    community.length ? el("h2", { textContent: "Community" }) : null,
    community.length ? el("p", { className: "muted small", textContent: "Shared by players and not reviewed yet." }) : null,
    ...community.map((e) => entryCard(e, catalog)),
  ];
  body.replaceChildren(...parts.filter(Boolean));
}

const app = new URLSearchParams(location.search).get("app");
if (app && /^\d{1,10}$/.test(app)) showGame(app);
else showList();
