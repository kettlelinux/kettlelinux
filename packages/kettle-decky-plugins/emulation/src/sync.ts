// Bringing the Steam library in line with the ROMs (main.py's sync_plan): a shortcut per game,
// running emu-run with the game's system and path, in its system's collection, with the standard
// controls' layout (once: a layout the user picks later stays) and its artwork. One sync runs at a
// time; asking during one runs another after it. What's done is reported back as it goes, and
// each new shortcut is noted in localStorage the moment Steam makes it until the backend has it,
// so a sync cut short (Steam's UI or the plugin reloading) doesn't add a game twice.
import { Art, Plan, artDone, artwork, layoutDone, libraryState, setCollection, syncPlan, synced } from "./api";

declare const appStore: { GetAppOverviewByAppID(appid: number): any | null };
declare const collectionStore: any;

const BATCH = 25;
const PENDING = "kettle-emulation:pending-adds"; // {rom id: appid} added to Steam, not yet in roms.json
const LOADED = Date.now();
const LIBRARY_WAIT = 60_000; // ms after load a library without our shortcuts may still be loading
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export const overview = (appid: number | null) => {
  try {
    return appid ? appStore.GetAppOverviewByAppID(appid) : null;
  } catch {
    return null;
  }
};
export const inLibrary = (appid: number | null) => !!overview(appid);

function pendingAdds(): Record<string, number> {
  try {
    const v = JSON.parse(localStorage.getItem(PENDING) ?? "{}");
    return v && typeof v === "object" ? v : {};
  } catch {
    return {};
  }
}
function savePending(p: Record<string, number>) {
  try {
    if (Object.keys(p).length) localStorage.setItem(PENDING, JSON.stringify(p));
    else localStorage.removeItem(PENDING);
  } catch {
    // no storage: only the batch's own report is left
  }
}

// The device's own pads (not a remote or wireless one): Steam keeps a layout per controller. A
// game counts as laid out once at least one of them took it (none in: tried again next sync).
const ownPads = (): any[] =>
  ((window as any).ControllerStore?.m_controllerList ?? []).filter((c: any) => !c.bRemoteDevice && !c.bWireless && !c.bBluetooth);

function selectLayout(appid: number, layout: string): boolean {
  const store = (window as any).controllerConfiguratorStore;
  if (typeof store?.SetActiveConfigForApp !== "function") return false;
  let n = 0;
  for (const c of ownPads()) {
    try {
      store.SetActiveConfigForApp(appid, c.nControllerIndex, layout, false);
      n++;
    } catch (e) {
      console.error("Emulation: layout for", appid, e);
    }
  }
  return n > 0;
}

export async function applyArt(appid: number, art: Art) {
  for (const [type, a] of Object.entries(art)) await (SteamClient.Apps as any).SetCustomArtworkForApp(appid, a.data, a.ext, Number(type));
}

// --- collections (collectionStore; best effort: a failure is only logged) -----------------------
// Only the collections the plugin made, by the id it keeps: a collection of the user's with the
// same name is never taken over (nor deleted with the system's last game).
function findCollection(id: string | null): any | null {
  try {
    return id ? (collectionStore.GetCollection(id) ?? null) : null;
  } catch {
    return null;
  }
}

async function syncCollection(system: string, name: string, id: string | null, appids: number[], dropped: number[]) {
  let c = findCollection(id);
  if (!appids.length) {
    if (c) {
      collectionStore.DeleteCollection(c.id ?? c.m_strId);
      await setCollection(system, null);
    }
    return;
  }
  if (!c) {
    const nc = collectionStore.NewUnsavedCollection(name, undefined, []);
    await nc.Save();
    c = findCollection(nc.id ?? nc.m_strId);
    if (!c) throw new Error(`collection ${name} wasn't saved`);
  }
  const cid = c.id ?? c.m_strId;
  if (cid !== id) await setCollection(system, cid);
  const dd = c.AsDragDropCollection();
  const has = (a: number) => {
    try {
      return !!c.apps?.has?.(a);
    } catch {
      return false;
    }
  };
  // a new shortcut shows up in the library a moment after it's added
  const want: any[] = [];
  for (const a of appids) {
    if (has(a)) continue;
    let o = overview(a);
    for (let t = 0; !o && t < 8; t++) {
      await sleep(250);
      o = overview(a);
    }
    if (o) want.push(o);
  }
  if (want.length) dd.AddApps(want);
  // RemoveShortcut leaves the appid in its collections
  const stale = dropped.filter(has);
  if (stale.length) dd.RemoveApps(stale.map((a) => overview(a) ?? { appid: a }));
}

// --- the sync ---------------------------------------------------------------------------------
let running: Promise<SyncResult> | null = null;
let again = false;
export type SyncResult = { added: number; removed: number; updated: number };
type Listener = (busy: boolean, r?: SyncResult) => void;
const listeners = new Set<Listener>();
export const onSync = (l: Listener) => {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
};
export const syncing = () => running !== null;

export function sync(): Promise<SyncResult> {
  if (running) {
    again = true;
    return running;
  }
  listeners.forEach((l) => l(true));
  running = (async () => {
    let total: SyncResult = { added: 0, removed: 0, updated: 0 };
    do {
      again = false;
      const r = await syncOnce();
      total = { added: total.added + r.added, removed: total.removed + r.removed, updated: total.updated + r.updated };
    } while (again);
    return total;
  })().finally(() => {
    running = null;
  });
  running.then(
    (r) => listeners.forEach((l) => l(false, r)),
    (e) => {
      console.error("Emulation: sync failed", e);
      listeners.forEach((l) => l(false));
    },
  );
  return running;
}

async function syncOnce(): Promise<SyncResult> {
  const plan: Plan = await syncPlan();
  const dropped: Record<string, number[]> = {};
  const drop = (system: string, appid: number) => (dropped[system] ??= []).push(appid);

  // shortcuts of ours the user deleted in Steam: never again. Only when the library looks loaded
  // (others of ours are there); the backend counts one only when two syncs minutes apart miss it.
  const ready = plan.check.some((c) => inLibrary(c.appid));

  // shortcuts an earlier sync added but didn't get to report: reported now instead of added again
  // (one Steam doesn't show yet, while its library may still be loading, is left for later)
  const pending = pendingAdds();
  const left: Record<string, number> = {};
  const held: Record<string, number> = {};
  for (const [id, sid] of Object.entries(pending)) {
    if (!plan.add.some((a) => a.id === id)) continue;
    if (inLibrary(sid)) left[id] = sid;
    else if (!ready && Date.now() - LOADED < LIBRARY_WAIT) held[id] = sid;
  }
  if (Object.keys(pending).length) {
    if (Object.keys(left).length) await synced(left, [], [], [], []);
    savePending(held);
  }
  plan.add = plan.add.filter((a) => !(a.id in left) && !(a.id in held));
  const missing = ready ? plan.check.filter((c) => !inLibrary(c.appid)) : [];
  const seen = ready ? plan.check.filter((c) => inLibrary(c.appid)) : [];

  const removed: string[] = [];
  for (const r of plan.remove) {
    if (inLibrary(r.appid)) SteamClient.Apps.RemoveShortcut(r.appid);
    drop(r.system, r.appid);
    removed.push(r.id);
  }

  const updated: string[] = [];
  for (const u of plan.update) {
    if (!u.appid || !inLibrary(u.appid)) continue;
    SteamClient.Apps.SetShortcutName(u.appid, u.title);
    SteamClient.Apps.SetShortcutStartDir(u.appid, `"${u.dir}"`);
    SteamClient.Apps.SetShortcutLaunchOptions(u.appid, u.launch);
    updated.push(u.id);
  }
  const goneIds = await synced(
    {},
    updated,
    removed,
    missing.map((m) => m.id),
    seen.map((m) => m.id),
  );
  const gone = plan.check.filter((c) => goneIds.includes(c.id));
  gone.forEach((g) => drop(g.system, g.appid));

  let added = Object.keys(left).length;
  for (let i = 0; i < plan.add.length; i += BATCH) {
    const batch: Record<string, number> = {};
    for (const a of plan.add.slice(i, i + BATCH)) {
      try {
        // a game brought back whose old shortcut Steam has after all: that one, not a second
        const old = a.was && inLibrary(a.was) ? a.was : null;
        const sid = old ?? (await SteamClient.Apps.AddShortcut(a.title, a.exe, a.dir, a.launch));
        if (!sid) continue;
        batch[a.id] = sid;
        savePending({ ...pendingAdds(), [a.id]: sid });
        SteamClient.Apps.SetShortcutName(sid, a.title);
        SteamClient.Apps.SetShortcutExe(sid, `"${a.exe}"`);
        SteamClient.Apps.SetShortcutStartDir(sid, `"${a.dir}"`);
        SteamClient.Apps.SetShortcutLaunchOptions(sid, a.launch);
      } catch (e) {
        console.error("Emulation: adding", a.title, e);
      }
    }
    await synced(batch, [], [], [], []);
    const p = pendingAdds();
    for (const id of Object.keys(batch)) delete p[id];
    savePending(p);
    added += Object.keys(batch).length;
    await sleep(100);
  }

  const st = await libraryState();
  for (const [system, c] of Object.entries(st.collections)) {
    try {
      await syncCollection(system, c.name, c.id, c.appids, dropped[system] ?? []);
    } catch (e) {
      console.error("Emulation: collection", c.name, e);
    }
  }

  const laid: number[] = [];
  for (const appid of st.layout) {
    if (inLibrary(appid) && selectLayout(appid, plan.layout)) laid.push(appid);
  }
  if (laid.length) await layoutDone(laid);

  // artwork on its own: the downloads are the slow part, and the games are playable meanwhile
  artQueue(st.art);
  return { added, removed: removed.length + gone.length, updated: updated.length };
}

let artBusy = false;
const artPending = new Map<string, number>();

async function artQueue(items: { id: string; appid: number }[]) {
  for (const a of items) artPending.set(a.id, a.appid);
  if (artBusy) return;
  artBusy = true;
  try {
    while (artPending.size) {
      const [id, appid] = artPending.entries().next().value as [string, number];
      artPending.delete(id);
      if (!inLibrary(appid)) continue;
      let art: Art;
      try {
        art = await artwork(id, null);
      } catch (e) {
        console.error("Emulation: artwork", id, e);
        continue;
      }
      if (!Object.keys(art).length) continue; // none (a try used) or offline (none used)
      try {
        await applyArt(appid, art);
        await artDone(id, true);
      } catch (e) {
        console.error("Emulation: setting the artwork", id, e);
        await artDone(id, false).catch(() => {});
      }
    }
  } finally {
    artBusy = false;
  }
}

// Starts a game through its shortcut
export async function play(appid: number) {
  let gameid: string | undefined;
  for (let tries = 0; tries < 20 && !(gameid = overview(appid)?.m_gameid); tries++) await sleep(250);
  if (!gameid) throw new Error("the game isn't in the Steam library yet");
  SteamClient.Apps.RunGame(gameid, "", -1, 100);
}
