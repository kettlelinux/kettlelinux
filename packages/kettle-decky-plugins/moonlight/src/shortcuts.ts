// A host's app in the Steam library: a shortcut running kettle-moonlight (main.py's
// shortcut_info), with the app's box art from the host as its library capsule. Added while Steam
// runs, so no restart is needed.
import { boxart, rememberShortcut, shortcutInfo } from "./api";

declare const appStore: { GetAppOverviewByAppID(appid: number): { m_gameid?: string; display_name?: string } | null; allApps?: unknown[] };

export const overview = (appid: number | null) => {
  try {
    return appid ? appStore.GetAppOverviewByAppID(appid) : null;
  } catch {
    return null;
  }
};

export const inLibrary = (appid: number | null) => !!overview(appid);

// Steam's custom artwork types: the portrait capsule (grid) is what a host's box art is
const GRID = 0;

// Steam Input keeps a shortcut's controller layout by its name: an app named like another entry
// (Sunshine's "Desktop" and Kettle's nested desktop, whose layout drives the mouse) gets the PC's
// name too, and a layout of its own
function title(appName: string, host: string, self: number | null): string {
  const taken = ((appStore as any).allApps ?? []).some(
    (a: any) => a.appid !== self && String(a.display_name ?? "").toLowerCase() === appName.toLowerCase(),
  );
  return taken ? `${appName} (${host})` : appName;
}

export async function addShortcut(uuid: string, appName: string, appId: number, existing: number | null): Promise<number> {
  const info = await shortcutInfo(uuid, appName);
  const isNew = !inLibrary(existing);
  const name = title(info.title, info.host, isNew ? null : existing);
  const sid = isNew ? await SteamClient.Apps.AddShortcut(name, info.exe, info.dir, "") : existing!;
  if (!sid) throw new Error("Steam didn't add the shortcut");
  SteamClient.Apps.SetShortcutName(sid, name);
  SteamClient.Apps.SetShortcutExe(sid, `"${info.exe}"`);
  SteamClient.Apps.SetShortcutStartDir(sid, `"${info.dir}"`);
  SteamClient.Apps.SetShortcutLaunchOptions(sid, info.launch);
  await rememberShortcut(uuid, appName, sid);
  if (isNew) {
    // artwork last: a missing picture shouldn't cost the shortcut
    try {
      const art = await boxart(uuid, appId);
      if (art) await (SteamClient.Apps as any).SetCustomArtworkForApp(sid, art.split(",")[1], "png", GRID);
    } catch (e) {
      console.error("Moonlight: artwork failed", e);
    }
  }
  return sid;
}

export async function removeShortcut(uuid: string, appName: string, appid: number | null) {
  if (appid && inLibrary(appid)) SteamClient.Apps.RemoveShortcut(appid);
  await rememberShortcut(uuid, appName, null);
}

// Starts the stream through its shortcut (a new one shows up in the library a moment after it's added)
export async function play(appid: number) {
  let gameid: string | undefined;
  for (let tries = 0; tries < 20 && !(gameid = overview(appid)?.m_gameid); tries++) await new Promise((r) => setTimeout(r, 250));
  if (!gameid) throw new Error("the stream isn't in the Steam library yet");
  SteamClient.Apps.RunGame(gameid, "", -1, 100);
}
