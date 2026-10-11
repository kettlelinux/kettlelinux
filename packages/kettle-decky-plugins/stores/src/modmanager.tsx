// The Game Stores page's Mod Manager tab, and the Quick Access panel's button: Amethyst Mod
// Manager (a desktop app) in Game Mode, as the desktop nested in Game Mode (nested-desktop) with
// the app started in it. Its library entry is added the first time it's opened, with its artwork
// and the desktop's controller layout (selected once, so a layout the user picks stays).
import { ButtonItem, Field } from "@decky/ui";
import { callable } from "@decky/api";
import { useEffect, useState } from "react";
import { inLibrary, play, selectLayout } from "./shortcuts";
import { act, small } from "./ui";

export type ModManagerInfo = { available: boolean; appid: number | null; exe: string; launch: string };

export const modManagerInfo = callable<[], ModManagerInfo>("mod_manager_info");
const modManagerArt = callable<[], { art: Record<string, string>; icon: string }>("mod_manager_art");
const rememberModManager = callable<[appid: number], void>("remember_mod_manager");

const NAME = "Amethyst Mod Manager";
const LAYOUT = "local:///usr/share/kettle/nested-desktop/controller.vdf";

async function addEntry(info: ModManagerInfo): Promise<number> {
  const id = await SteamClient.Apps.AddShortcut(NAME, info.exe, "", "");
  if (!id) throw new Error("Steam didn't add the shortcut");
  SteamClient.Apps.SetShortcutName(id, NAME);
  SteamClient.Apps.SetShortcutExe(id, `"${info.exe}"`);
  SteamClient.Apps.SetShortcutLaunchOptions(id, info.launch);
  await rememberModManager(id);
  try {
    const { art, icon } = await modManagerArt();
    if (icon) SteamClient.Apps.SetShortcutIcon(id, icon);
    for (const [type, png] of Object.entries(art))
      await (SteamClient.Apps as any).SetCustomArtworkForApp(id, png, "png", Number(type));
  } catch (e) {
    console.error("Game Stores: Mod Manager artwork failed", e);
  }
  selectLayout(id, LAYOUT);
  return id;
}

// Opens the Mod Manager: its entry (added first if it isn't in the library)
export async function openModManager() {
  const info = await modManagerInfo();
  if (!info.available) throw new Error("Amethyst Mod Manager isn't installed");
  const appid = inLibrary(info.appid) ? info.appid! : await addEntry(info);
  await play(appid);
}

export function ModManagerTab() {
  const [info, setInfo] = useState<ModManagerInfo | null>(null);
  useEffect(() => {
    modManagerInfo().then(setInfo).catch(() => setInfo({ available: false, appid: null, exe: "", launch: "" }));
  }, []);
  if (!info) return null;
  if (!info.available) return <div style={small}>Amethyst Mod Manager isn't installed.</div>;
  return (
    <div style={{ maxWidth: "720px" }}>
      <Field
        label="Amethyst Mod Manager"
        description={
          <div style={small}>
            Installs and sorts mods for your games: Nexus Mods and its Collections, Wabbajack lists, LOOT for Bethesda
            games, and about a hundred others. It finds the games in your Steam library and in Game Stores. It opens in
            the desktop, inside Game Mode: the Steam button comes back here, and Exit Game closes it.
            {inLibrary(info.appid) && <div>It's in your library as {NAME}.</div>}
          </div>
        }
        focusable={false}
      />
      <ButtonItem layout="below" onClick={() => act(openModManager, "Opening the Mod Manager failed")}>
        Open the Mod Manager
      </ButtonItem>
    </div>
  );
}
