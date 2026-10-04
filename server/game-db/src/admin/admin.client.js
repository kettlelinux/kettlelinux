// The game database's admin page (served at /admin by src/worker.js). It signs in with the admin
// token, keeps it in sessionStorage (this tab only), and drives the /v1/admin API. Everything the
// players sent is put on the page as text, never as HTML.
const TOKEN_KEY = "kettle-games-admin-token";
const SITE = "https://kettlelinux.org/games.html";
const DEVICES = { odin2portal: "Odin 2 Portal", thor: "AYN Thor", rp5: "Retroid Pocket 5" };

const $ = (id) => document.getElementById(id);
const state = { tab: "pending", q: "", submitter: "", offset: 0, entries: [], selected: new Set(), catalog: null };

function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children.filter((c) => c !== null && c !== undefined && c !== false));
  return node;
}

function getToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return state.token || "";
  }
}

function setToken(t) {
  state.token = t;
  try {
    if (t) sessionStorage.setItem(TOKEN_KEY, t);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {}
}

let toastTimer;
function toast(msg) {
  $("toast").textContent = msg;
  $("toast").classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $("toast").classList.add("hidden"), 3000);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { Authorization: `Bearer ${getToken()}`, "Content-Type": "application/json" },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401) {
    signOut("The token was refused.");
    throw new Error("Unauthorized");
  }
  if (!res.ok) throw new Error((await res.text()).trim() || `HTTP ${res.status}`);
  return res.json();
}

const when = (s) => (s ? new Date(s * 1000).toLocaleString() : "");
const device = (e) => DEVICES[e.variant] ?? e.device ?? e.variant;
const short = (h) => (h ? h.slice(0, 10) : "");

// ---------- describing an entry ----------

function describe(e) {
  const out = [];
  const opts = new Map((state.catalog?.options ?? []).map((o) => [o.id, o]));
  for (const [k, v] of Object.entries(e.settings)) {
    const o = opts.get(k);
    if (!o) out.push({ text: `${k}=${v}`, raw: true });
    else if (o.choices.length === 1) out.push({ text: o.label });
    else out.push({ text: `${o.label}: ${o.choices.find((c) => c.value === v)?.label ?? v}` });
  }
  for (const [n, v] of e.env) out.push({ text: `${n}=${v}`, raw: true });
  const modes = new Map((state.catalog?.dll_modes ?? []).map((m) => [m.value, m.label]));
  for (const [d, m] of e.dlls) out.push({ text: `${d}.dll: ${modes.get(m) ?? m}`, raw: true });
  if (e.compat_tool) out.push({ text: `Proton: ${e.compat_tool}`, raw: true });
  return out;
}

// ---------- entries ----------

async function setStatus(ids, status) {
  if (status === "delete") {
    if (!confirm(`Delete ${ids.length} entr${ids.length > 1 ? "ies" : "y"} for good? Their votes go too.`)) return;
    await api("/v1/admin/bulk", { method: "POST", body: { ids, delete: true } });
  } else if (ids.length === 1) {
    await api(`/v1/admin/profiles/${ids[0]}`, { method: "POST", body: { status } });
  } else {
    await api("/v1/admin/bulk", { method: "POST", body: { ids, status } });
  }
  toast(status === "delete" ? "Deleted" : `Marked ${status}`);
  ids.forEach((id) => state.selected.delete(id));
  await Promise.all([loadStats(), loadList()]);
}

async function ban(e) {
  const reason = prompt(
    `Ban the device that shared this (${short(e.submitter)}, ${e.by_submitter} entr${e.by_submitter > 1 ? "ies" : "y"})?\n` +
      "All its entries are rejected and its votes removed; it can't share or vote again.\n\nReason (kept for you):",
    "spam",
  );
  if (reason === null) return;
  await api("/v1/admin/bans", { method: "POST", body: { submitter: e.submitter, reason } });
  toast("Device banned");
  await Promise.all([loadStats(), loadList()]);
}

async function showVotes(e, box) {
  if (!box.classList.contains("hidden")) {
    box.classList.add("hidden");
    return;
  }
  const { votes } = await api(`/v1/admin/profiles/${e.id}`);
  box.replaceChildren(
    votes.length
      ? el("table", {}, ...votes.map((v) =>
          el("tr", {},
            el("td", { textContent: v.works ? "✔ works" : "✘ doesn't" , style: `color: var(${v.works ? "--ok" : "--bad"})` }),
            el("td", { textContent: DEVICES[v.variant] ?? v.device }),
            el("td", { className: "muted", textContent: `Kettle ${v.build}` }),
            el("td", { className: "muted", textContent: when(v.created) }),
            el("td", { className: "muted", textContent: short(v.voter) }))))
      : el("p", { className: "muted", textContent: "No votes besides the one who shared it." }),
  );
  box.classList.remove("hidden");
}

function card(e) {
  const check = el("input", { type: "checkbox", checked: state.selected.has(e.id) });
  const root = el("div", { className: `card${state.selected.has(e.id) ? " selected" : ""}` });
  check.addEventListener("change", () => {
    if (check.checked) state.selected.add(e.id);
    else state.selected.delete(e.id);
    root.classList.toggle("selected", check.checked);
    updateBulk();
  });

  const rating = el("select", {},
    el("option", { value: "great", textContent: "Great", selected: e.rating === "great" }),
    el("option", { value: "playable", textContent: "Playable", selected: e.rating === "playable" }));
  rating.addEventListener("change", async () => {
    await api(`/v1/admin/profiles/${e.id}`, { method: "POST", body: { rating: rating.value } });
    toast("Rating saved");
  });

  const notes = el("textarea", { value: e.notes, maxLength: 500, placeholder: "No note" });
  const saveNotes = el("button", { textContent: "Save note", disabled: true });
  notes.addEventListener("input", () => (saveNotes.disabled = notes.value === e.notes));
  saveNotes.addEventListener("click", async () => {
    await api(`/v1/admin/profiles/${e.id}`, { method: "POST", body: { notes: notes.value } });
    e.notes = notes.value;
    saveNotes.disabled = true;
    toast("Note saved");
  });

  const votesBox = el("div", { className: "votes hidden" });
  const button = (label, cls, fn) => {
    const b = el("button", { className: cls, textContent: label });
    b.addEventListener("click", () => fn().catch((err) => toast(err.message)));
    return b;
  };
  const filterBySubmitter = el("a", { href: "#", textContent: `${e.by_submitter} from this device` });
  filterBySubmitter.addEventListener("click", (ev) => {
    ev.preventDefault();
    state.submitter = e.submitter;
    state.tab = "all";
    reload();
  });

  root.append(
    el("div", { className: "check" }, check,
      el("img", { src: `https://cdn.cloudflare.steamstatic.com/steam/apps/${e.app_id}/header.jpg`, alt: "", loading: "lazy" })),
    el("div", {},
      el("div", { className: "head" },
        el("h3", {}, el("a", { href: `${SITE}?app=${e.app_id}`, target: "_blank", rel: "noopener", textContent: e.game })),
        el("span", { className: "muted small", textContent: `app ${e.app_id}` }),
        el("span", { className: `badge ${e.status}`, textContent: e.status }),
        e.banned && el("span", { className: "badge rejected", textContent: "banned device" })),
      el("div", { className: "small muted" },
        `${device(e)} · Kettle ${e.build} · shared ${when(e.created)}${e.reviewed ? ` · reviewed ${when(e.reviewed)}` : ""} · `,
        el("span", { style: "color: var(--ok)", textContent: `works for ${e.works}` }),
        e.broken ? el("span", { style: "color: var(--bad)", textContent: `, not for ${e.broken}` }) : "",
        ` · device ${short(e.submitter)} (`, filterBySubmitter, ")"),
      el("ul", { className: "settings" },
        ...(describe(e).length
          ? describe(e).map((d) => el("li", { className: d.raw ? "raw" : "", textContent: d.text }))
          : [el("li", { textContent: "Default settings" })])),
      notes,
      el("div", { className: "actions" },
        saveNotes,
        el("label", { className: "small" }, "Rating ", rating),
        e.status !== "approved" && button("Approve", "ok", () => setStatus([e.id], "approved")),
        e.status !== "rejected" && button("Reject", "bad", () => setStatus([e.id], "rejected")),
        e.status !== "pending" && button("Back to pending", "", () => setStatus([e.id], "pending")),
        button("Votes", "", () => showVotes(e, votesBox)),
        !e.banned && button("Ban device", "bad", () => ban(e)),
        button("Delete", "bad", () => setStatus([e.id], "delete"))),
      votesBox),
  );
  return root;
}

function updateBulk() {
  const n = state.selected.size;
  $("bulk").classList.toggle("hidden", n === 0);
  $("bulk-count").textContent = `${n} selected`;
  $("select-all").checked = n > 0 && state.entries.every((e) => state.selected.has(e.id));
}

async function loadList(append = false) {
  if (state.tab === "bans") return loadBans();
  if (state.tab === "engines") return loadEngines();
  if (!append) state.offset = 0;
  const qs = new URLSearchParams({ status: state.tab, q: state.q, offset: String(state.offset) });
  if (state.submitter) qs.set("submitter", state.submitter);
  const { profiles, more } = await api(`/v1/admin/profiles?${qs}`);
  state.entries = append ? state.entries.concat(profiles) : profiles;
  state.offset += profiles.length;
  const list = $("list");
  if (!append) list.replaceChildren();
  if (!state.entries.length) list.replaceChildren(el("p", { className: "muted", textContent: "Nothing here." }));
  else list.append(...profiles.map(card));
  $("more").classList.toggle("hidden", !more);
  updateBulk();
}

async function loadBans() {
  const { bans } = await api("/v1/admin/bans");
  $("more").classList.add("hidden");
  $("list").replaceChildren(
    bans.length
      ? el("div", {}, ...bans.map((b) => {
          const unban = el("button", { textContent: "Unban" });
          unban.addEventListener("click", async () => {
            await api(`/v1/admin/bans/${b.submitter}`, { method: "DELETE" });
            toast("Unbanned (their entries stay rejected)");
            loadStats();
            loadBans();
          });
          return el("div", { className: "card", style: "grid-template-columns: 1fr auto" },
            el("div", {},
              el("b", { textContent: `Device ${short(b.submitter)}` }),
              el("div", { className: "small muted", textContent: `Banned ${when(b.created)} · ${b.entries} entries` }),
              b.reason ? el("div", { className: "small", textContent: `Reason: ${b.reason}` }) : null),
            el("div", {}, unban));
        }))
      : el("p", { className: "muted", textContent: "No banned devices." }),
  );
}

// what devices found the games with entries built on, and per engine how each setting fared:
// the starting point for FEX defaults per engine
async function loadEngines() {
  const { engines, labels } = await api("/v1/admin/engines");
  const opts = new Map(state.catalog.options.map((o) => [o.id, o]));
  const setting = (kv) => {
    const [id, v] = kv.split("=");
    const o = opts.get(id);
    return o ? `${o.label}: ${o.choices.find((c) => c.value === v)?.label ?? v}` : kv;
  };
  $("more").classList.add("hidden");
  $("list").replaceChildren(
    engines.length
      ? el("div", {}, ...engines.map((e) => {
          const rows = Object.entries(e.settings).sort((a, b) => b[1].entries - a[1].entries);
          return el("div", { className: "card", style: "grid-template-columns: 1fr" },
            el("div", {},
              el("div", { className: "head" }, el("h3", { textContent: labels[e.engine] ?? e.engine })),
              el("div", { className: "small muted", textContent:
                `${e.games} games (${e.x86} 32-bit, ${e.linux} native Linux, ${e.anticheat} with anti-cheat) · ` +
                `${e.entries} entries, ` +
                `${e.approved} verified · works ${e.works}, broken ${e.broken}` }),
              rows.length
                ? el("div", { className: "votes" }, el("table", {},
                    el("tr", {}, ...["Setting", "Games", "Entries", "Works", "Broken"].map((h) => el("td", {}, el("b", { textContent: h })))),
                    ...rows.map(([kv, n]) => el("tr", {},
                      el("td", { textContent: setting(kv) }),
                      el("td", { textContent: String(n.games) }),
                      el("td", { textContent: String(n.entries) }),
                      el("td", { textContent: String(n.works) }),
                      el("td", { textContent: String(n.broken) })))))
                : el("div", { className: "small muted", textContent: "No settings in its entries yet." })));
        }))
      : el("p", { className: "muted", textContent: "No engine reports yet: they come with shares and votes from Game Settings." }),
  );
}

async function loadStats() {
  const s = await api("/v1/admin/stats");
  const stat = (label, n) => el("div", { className: "stat" }, el("b", { textContent: String(n) }), el("span", { className: "muted small", textContent: label }));
  $("stats").replaceChildren(
    stat("pending", s.pending),
    stat("approved", s.approved),
    stat("rejected", s.rejected),
    stat("games", s.games),
    stat("votes", s.votes),
    stat("shared this week", s.last_week),
    stat("banned devices", s.bans),
  );
  $("tabs").querySelector('[data-tab="pending"]').textContent = `Pending (${s.pending})`;
}

function reload() {
  state.selected.clear();
  for (const b of $("tabs").querySelectorAll("button")) b.classList.toggle("active", b.dataset.tab === state.tab);
  const f = $("submitter-filter");
  f.classList.toggle("hidden", !state.submitter);
  f.replaceChildren(`Device ${short(state.submitter)} `, Object.assign(el("a", { href: "#", textContent: "✕" }), {
    onclick: (ev) => {
      ev.preventDefault();
      state.submitter = "";
      reload();
    },
  }));
  $("toolbar").classList.toggle("hidden", state.tab === "bans" || state.tab === "engines");
  loadList().catch((e) => toast(e.message));
}

// ---------- sign in ----------

function signOut(message = "") {
  setToken("");
  $("app").classList.add("hidden");
  $("logout").classList.add("hidden");
  $("login").classList.remove("hidden");
  $("login-error").textContent = message;
}

async function start() {
  try {
    await loadStats();
  } catch {
    return;
  }
  $("login").classList.add("hidden");
  $("app").classList.remove("hidden");
  $("logout").classList.remove("hidden");
  if (!state.catalog) state.catalog = await (await fetch("/v1/catalog")).json();
  reload();
}

$("signin").addEventListener("click", () => {
  setToken($("token").value.trim());
  $("token").value = "";
  start();
});
$("token").addEventListener("keydown", (e) => e.key === "Enter" && $("signin").click());
$("logout").addEventListener("click", () => signOut());
$("refresh").addEventListener("click", () => {
  loadStats();
  reload();
});
$("more").addEventListener("click", () => loadList(true).catch((e) => toast(e.message)));
$("tabs").addEventListener("click", (e) => {
  const tab = e.target.closest("button")?.dataset.tab;
  if (!tab) return;
  state.tab = tab;
  reload();
});
let searchTimer;
$("search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.q = $("search").value.trim();
    reload();
  }, 300);
});
$("select-all").addEventListener("change", () => {
  for (const e of state.entries) {
    if ($("select-all").checked) state.selected.add(e.id);
    else state.selected.delete(e.id);
  }
  for (const c of $("list").querySelectorAll(".card")) {
    const box = c.querySelector('input[type="checkbox"]');
    if (box) box.checked = $("select-all").checked;
    c.classList.toggle("selected", $("select-all").checked);
  }
  updateBulk();
});
$("bulk").addEventListener("click", (e) => {
  const action = e.target.closest("button")?.dataset.bulk;
  if (action) setStatus([...state.selected], action).catch((err) => toast(err.message));
});

if (getToken()) start();
