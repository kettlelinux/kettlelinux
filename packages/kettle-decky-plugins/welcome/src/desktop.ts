// The desktop in Game Mode: Desktop Mode's Plasma nested in gamescope as a Steam app
// (usr/lib/kettle/nested-desktop), added to the library once per device as "Desktop", with its
// artwork (kettle-desktop-art) and the desktop's controls as its controller layout
// (usr/share/kettle/nested-desktop/controller.vdf: what desktop-controller does in Desktop Mode).
// Each is done once, so a user who removes the entry or picks another layout keeps that.
import { callable } from "@decky/api";

const EXE = "/usr/lib/kettle/nested-desktop";
const LAYOUT = "local:///usr/share/kettle/nested-desktop/controller.vdf";
const NAME = "Desktop";

const claimDefault = callable<[name: string], boolean>("claim_default");
// SetCustomArtworkForApp's asset type -> the PNG, base64; and the icon's path
const desktopArt = callable<[], { art: Record<string, string>; icon: string }>("desktop_art");
const rememberDesktop = callable<[appid: number], void>("remember_desktop");
const desktopAppid = callable<[], number | null>("desktop_appid");

declare const appStore: { GetAppOverviewByAppID(appid: number): object | null };

const inLibrary = (appid: number | null) => {
  try {
    return !!appid && !!appStore.GetAppOverviewByAppID(appid);
  } catch {
    return false;
  }
};

async function addShortcut() {
  const id = await SteamClient.Apps.AddShortcut(NAME, EXE, "", "");
  if (!id) throw new Error("Steam didn't create the shortcut");
  SteamClient.Apps.SetShortcutName(id, NAME);
  SteamClient.Apps.SetShortcutExe(id, `"${EXE}"`);
  await rememberDesktop(id);
  const { art, icon } = await desktopArt();
  if (icon) SteamClient.Apps.SetShortcutIcon(id, icon);
  for (const [type, png] of Object.entries(art)) {
    await (SteamClient.Apps as any).SetCustomArtworkForApp(id, png, "png", Number(type));
  }
}

// The layout goes to the device's own pad (not a remote or wireless one): Steam keeps a
// selection per controller.
const ownPads = (): any[] =>
  ((window as any).ControllerStore?.m_controllerList ?? []).filter(
    (c: any) => !c.bRemoteDevice && !c.bWireless && !c.bBluetooth,
  );

function selectLayout(appid: number, pads: any[]) {
  const store = (window as any).controllerConfiguratorStore;
  for (const c of pads) store.SetActiveConfigForApp(appid, c.nControllerIndex, LAYOUT, false);
}

export async function addDesktop() {
  // not again when the entry is still there (Reset settings forgets the claim, not the library)
  if ((await claimDefault("desktop-shortcut")) && !inLibrary(await desktopAppid())) await addShortcut();
  const appid = await desktopAppid();
  if (!appid) return;
  // a new entry and the pad can both come up a moment later: try for a while
  for (let tries = 0; tries < 60; tries++) {
    const pads = ownPads();
    if (inLibrary(appid) && pads.length && typeof (window as any).controllerConfiguratorStore?.SetActiveConfigForApp === "function") {
      if (await claimDefault("desktop-controls")) selectLayout(appid, pads);
      return;
    }
    await new Promise((r) => setTimeout(r, 5000));
  }
}
