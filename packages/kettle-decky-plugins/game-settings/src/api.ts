// The backend's calls, and committing a profile: launch options, then Proton version, then
// stored.
import { Navigation } from "@decky/ui";
import { callable } from "@decky/api";
import { Engine } from "../../shared/engines";
import { InstalledGame } from "../../shared/GamePicker";
import { editLaunchOptions, getFreshAppDetails } from "../../shared/launchOptions";
import { Owned, Profile, applyProfile } from "./catalog";

export const ROUTE = "/kettle-game-settings";

export type Status = { can_share: boolean; device: { model: string; variant: string; build: string }; configured: number[] };
export type Game = Profile & {
  appid: number;
  owned: Owned;
  compat_before: string | null;
  voted: string[];
  hash: string;
  played_s: number;
  played_enough: boolean;
  played_min_s: number;
  works: boolean;
  broken: boolean;
  from_database: { id: string; status: string; hash: string; auto?: boolean } | null;
  auto_eligible: boolean;
  is_shared: boolean;
  can_submit: boolean;
  can_vote: boolean;
};
type Patch = Partial<Profile> & {
  owned?: Owned;
  compat_before?: string | null;
  source?: { id: string; status: string; auto?: boolean } | null;
  verdict?: boolean | null;
};
export type DbProfile = Profile & {
  id: string;
  status: "approved" | "pending";
  rating: "great" | "playable";
  notes: string;
  device: string;
  variant: string;
  build: string;
  works: number;
  broken: number;
};
export type Community = { profiles: DbProfile[]; page: string | null; error: string | null; enabled: boolean };
export type Saved = Profile & { name: string };

export const status = callable<[], Status>("status");
export const installedGames = callable<[], InstalledGame[]>("installed_games");
export const getGame = callable<[appid: number], Game>("get_game");
export const getEngine = callable<[appid: number], Engine | null>("engine");
export type EngineSuggestions = { games: number; settings: { id: string; value: string; games: number }[] };
export const engineSuggestions = callable<[appid: number], EngineSuggestions>("engine_suggestions");
export const setGame = callable<[appid: number, patch: Patch], Game>("set_game");
export const resetGame = callable<[appid: number], Game>("reset_game");
export const recordPlay = callable<[appid: number, seconds: number, tool: string], void>("record_play");
export const listProfiles = callable<[], Saved[]>("list_profiles");
export const saveProfile = callable<[name: string, profile: Profile], Saved[]>("save_profile");
export const deleteProfile = callable<[name: string], Saved[]>("delete_profile");
export const community = callable<[appid: number], Community>("community");
export const submit = callable<[appid: number, game: string, rating: string, notes: string], { id: string; url: string }>("submit");
const vote = callable<[appid: number, works: boolean], Game>("vote");
export const getAuto = callable<[], boolean>("get_auto");
export const setAuto = callable<[on: boolean], boolean>("set_auto");
export const autoPending = callable<[force: boolean], { appid: number; name: string; entry: DbProfile }[]>("auto_pending");

export async function currentTool(appid: number): Promise<string> {
  const d = (await getFreshAppDetails(appid)) as { strCompatToolName?: string } | null;
  return d?.strCompatToolName ?? "";
}

// ARM64 builds first: the others are x86 Protons, which run entirely under emulation here
export async function compatTools(appid: number): Promise<{ strToolName: string; strDisplayName: string }[]> {
  try {
    const tools = (await SteamClient.Apps.GetAvailableCompatTools(appid)) ?? [];
    const arm = (t: { strToolName: string }) => (/arm64/i.test(t.strToolName) ? 0 : 1);
    return [...tools].sort((a, b) => arm(a) - arm(b));
  } catch {
    return [];
  }
}

// Write the profile into the game's launch options (taking out what the old one added) and
// set its Proton version, then store it. The Proton version Steam had before the first change
// is kept, so choosing "Steam's choice" again (or a reset) puts it back. If storing it fails,
// the launch options and Proton version go back as they were: else the stored game wouldn't
// say which entries the plugin wrote, and it couldn't take them out again.
export async function commit(appid: number, g: Game, next: Profile, extra: Patch = {}): Promise<Game> {
  let owned = g.owned;
  const lo = { before: "", after: "" };
  await editLaunchOptions(appid, (o) => {
    const r = applyProfile(o, next, g.owned);
    owned = r.owned;
    lo.before = o;
    lo.after = r.opts;
    return r.opts;
  });
  const patch: Patch = { ...next, owned, ...extra };
  let toolBefore: string | null = null; // the tool to put back on failure (null: unchanged)
  if (next.compat_tool !== g.compat_tool) {
    const before = g.compat_tool === null ? await currentTool(appid) : (g.compat_before ?? "");
    toolBefore = g.compat_tool ?? before;
    SteamClient.Apps.SpecifyCompatTool(appid, next.compat_tool ?? before);
    patch.compat_before = next.compat_tool === null ? null : before;
  }
  try {
    return await setGame(appid, patch);
  } catch (e) {
    // only if nothing else changed them meanwhile
    if (lo.after !== lo.before) await editLaunchOptions(appid, (o) => (o === lo.after ? lo.before : o)).catch(() => {});
    if (toolBefore !== null) SteamClient.Apps.SpecifyCompatTool(appid, toolBefore);
    throw e;
  }
}

export const openDatabase = {
  count: (appid: number) =>
    community(appid)
      .then((c) => c.profiles.length)
      .catch(() => 0),
  page: (appid: number) => {
    Navigation.CloseSideMenus();
    Navigation.Navigate(`${ROUTE}/${appid}`);
  },
  vote,
};
