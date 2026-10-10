// The backend's calls (main.py) and what they return.
import { callable } from "@decky/api";

// the stores with an account; Flathub (flathub.tsx) has none, but shares the downloads and shortcuts
export type Store = "epic" | "gog" | "amazon";
export type Source = Store | "flathub";
export const STORES: Store[] = ["epic", "gog", "amazon"];
export const NAMES: Record<Source, string> = { epic: "Epic Games", gog: "GOG", amazon: "Amazon Games", flathub: "Flathub" };

// kind: an install or an update; base: where it installs (the running job only); appid: in the
// finished job's event, the Steam shortcut the game has already (a reinstall), if any
export type Job = {
  store: Source;
  id: string;
  title: string;
  kind: "install" | "update";
  percent?: number;
  eta?: string;
  speed?: number;
  appid?: number | null;
};
export type Login = { store: Store | null; state: "idle" | "waiting" | "done" | "failed"; error: string };
export type Status = { users: Record<Store, string | null>; job: Job | null; queue: Job[]; login: Login; cloud_saves: boolean };

// note: why it can't be installed here ("" if it can); busy: queued or running ("install"|"update")
export type Game = {
  id: string;
  title: string;
  card: string;
  note: string;
  installed: boolean;
  update: boolean;
  appid: number | null;
  busy: "install" | "update" | null;
  dlc?: string[]; // Epic: the DLC the player owns (GOG's come with GameInfo)
};
export type GameInfo = {
  download: number;
  disk: number;
  update?: boolean;
  dlc?: string[]; // GOG: the DLC the player owns
  installed: { path: string; version: string } | null;
};
// the game's page's About section ("" or [] where the store doesn't say)
export type Details = { summary: string; developer: string; publisher: string; released: string; genres: string[]; modes: string[] };
export type Location = { path: string; label: string; free: number };
// native: started as it is (Flathub's flatpak), not with Proton; icon: a PNG for the shortcut
export type ShortcutInfo = { title: string; exe: string; dir: string; launch: string; native?: boolean; icon?: string };

// Flathub: a browse or search result, and an app's page
// "installed", or one of the backend's FLATHUB_CATEGORIES (flathub.tsx's CATEGORIES names them)
export type FlathubCategory = string;
export type FlathubApp = { id: string; title: string; summary: string; icon: string; developer: string; verified: boolean };
export type FlathubDetails = FlathubApp & {
  description: string;
  license: string;
  free: boolean;
  homepage: string;
  version: string;
  screenshots: string[];
  arm64: boolean;
  download: number;
  disk: number;
  installed: { title: string; version: string; origin: string; installation: string } | null;
  update: boolean;
  appid: number | null; // its Steam shortcut, if any
  busy: "install" | "update" | null;
};

export const status = callable<[], Status>("status");
export const loginStart = callable<[store: Store], string>("login_start");
export const loginCancel = callable<[], void>("login_cancel_wait");
export const logout = callable<[store: Store], void>("logout");
export const library = callable<[store: Store, refresh: boolean], { games: Game[]; fetched: number }>("library");
export const gameInfo = callable<[store: Store, id: string], GameInfo>("game_info");
export const details = callable<[store: Store, id: string], Details>("details");
export const locations = callable<[], { locations: Location[]; current: string }>("locations");
export const setLocation = callable<[path: string], void>("set_location");
export const setCloudSaves = callable<[on: boolean], void>("set_cloud_saves");
export const flathubBrowse = callable<[category: FlathubCategory, query: string, page: number], { apps: FlathubApp[]; pages: number; total: number }>("flathub_browse");
export const flathubApp = callable<[id: string], FlathubDetails>("flathub_app");
export const install = callable<[store: Source, id: string, title: string, kind: "install" | "update"], void>("install");
export const cancel = callable<[store: Source, id: string], void>("cancel");
export const uninstall = callable<[store: Source, id: string], number | null>("uninstall");
export const shortcutInfo = callable<[store: Source, id: string], ShortcutInfo>("shortcut_info");
export const artwork = callable<[store: Source, id: string], Record<string, { data: string; ext: string }>>("artwork");
export const rememberShortcut = callable<[store: Source, id: string, appid: number], void>("remember_shortcut");
export const pending = callable<[], { store: Source; id: string; appid: number | null }[]>("pending");

export const size = (n: number) =>
  n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n > 0 ? `${Math.max(1, Math.round(n / 1e6))} MB` : "?";
