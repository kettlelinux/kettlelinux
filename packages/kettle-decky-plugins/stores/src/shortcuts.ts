// A store game in the Steam library: a shortcut to its .exe, started with Proton through
// kettle-store-run (its launch options, from the backend), with the store's artwork. Added
// while Steam runs, so no restart is needed. A Flathub app's shortcut runs `flatpak run <id>`
// natively, with the app's icon.
import { Source, artwork, rememberShortcut, shortcutInfo } from "./api";

// The Proton a new shortcut gets: the community builds with ARM64 releases first (installed per
// user from Gaming Extras), then Valve's ARM64 Protons
const PROTONS = [/^proton-cachyos/i, /^GE-Proton.*aarch64/i, /^proton_\d+-arm64$/, /^proton-experimental-arm64$/];

declare const appStore: { GetAppOverviewByAppID(appid: number): { m_gameid?: string; display_name?: string } | null };

export const overview = (appid: number | null) => {
  try {
    return appid ? appStore.GetAppOverviewByAppID(appid) : null;
  } catch {
    return null;
  }
};

export const inLibrary = (appid: number | null) => !!overview(appid);

async function proton(appid: number): Promise<string | null> {
  const tools = ((await SteamClient.Apps.GetAvailableCompatTools(appid)) ?? []).map((t: any) => t.strToolName as string);
  for (const re of PROTONS) {
    // newest first: the names hold the version (numbers compared as numbers: 11-7 after 9-27)
    const found = tools.filter((t) => re.test(t)).sort((a, b) => b.localeCompare(a, undefined, { numeric: true }))[0];
    if (found) return found;
  }
  return null;
}

// Adds the installed game to Steam (or brings an existing shortcut up to date); returns its appid
export async function addShortcut(store: Source, id: string, appid: number | null = null): Promise<number> {
  const info = await shortcutInfo(store, id);
  const isNew = !inLibrary(appid);
  const sid = isNew ? await SteamClient.Apps.AddShortcut(info.title, info.exe, info.dir, "") : appid!;
  if (!sid) throw new Error("Steam didn't add the shortcut");
  SteamClient.Apps.SetShortcutName(sid, info.title);
  SteamClient.Apps.SetShortcutExe(sid, `"${info.exe}"`);
  if (info.dir) SteamClient.Apps.SetShortcutStartDir(sid, `"${info.dir}"`);
  // the flatpak arguments as the shortcut's own, as the Welcome plugin's Gaming Extras sets them
  if (info.native) SteamClient.Apps.SetShortcutLaunchOptions(sid, info.launch);
  else SteamClient.Apps.SetAppLaunchOptions(sid, info.launch);
  if (info.icon) SteamClient.Apps.SetShortcutIcon(sid, info.icon);
  const tool = info.native ? null : await proton(sid);
  if (tool) SteamClient.Apps.SpecifyCompatTool(sid, tool);
  await rememberShortcut(store, id, sid);
  if (isNew) {
    // artwork last: a missing picture shouldn't cost the shortcut
    try {
      const art = await artwork(store, id);
      for (const [type, a] of Object.entries(art))
        await (SteamClient.Apps as any).SetCustomArtworkForApp(sid, a.data, a.ext, Number(type));
    } catch (e) {
      console.error("Game Stores: artwork failed", e);
    }
  }
  return sid;
}

export function removeShortcut(appid: number | null) {
  if (appid && inLibrary(appid)) SteamClient.Apps.RemoveShortcut(appid);
}

// Starts the game through its shortcut (a new one shows up in the library a moment after it's added)
export async function play(appid: number) {
  let gameid: string | undefined;
  for (let tries = 0; tries < 20 && !(gameid = overview(appid)?.m_gameid); tries++) await new Promise((r) => setTimeout(r, 250));
  if (!gameid) throw new Error("the game isn't in the Steam library yet");
  SteamClient.Apps.RunGame(gameid, "", -1, 100);
}
