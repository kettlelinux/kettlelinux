// The backend's calls (main.py) and what they return.
import { callable } from "@decky/api";

export type Store = "epic" | "gog" | "amazon";
export const STORES: Store[] = ["epic", "gog", "amazon"];
export const NAMES: Record<Store, string> = { epic: "Epic Games", gog: "GOG", amazon: "Amazon Games" };

// kind: an install or an update; base: where it installs (the running job only)
export type Job = { store: Store; id: string; title: string; kind: "install" | "update"; percent?: number; eta?: string; speed?: number };
export type Login = { store: Store | null; state: "idle" | "waiting" | "done" | "failed"; error: string };
export type Status = { users: Record<Store, string | null>; job: Job | null; queue: Job[]; login: Login };

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
};
export type GameInfo = { download: number; disk: number; update?: boolean; installed: { path: string; version: string } | null };
// the game's page's About section ("" or [] where the store doesn't say)
export type Details = { summary: string; developer: string; publisher: string; released: string; genres: string[]; modes: string[] };
export type Location = { path: string; label: string; free: number };
export type ShortcutInfo = { title: string; exe: string; dir: string; launch: string };

export const status = callable<[], Status>("status");
export const loginStart = callable<[store: Store], string>("login_start");
export const loginCancel = callable<[], void>("login_cancel_wait");
export const logout = callable<[store: Store], void>("logout");
export const library = callable<[store: Store, refresh: boolean], { games: Game[]; fetched: number }>("library");
export const gameInfo = callable<[store: Store, id: string], GameInfo>("game_info");
export const details = callable<[store: Store, id: string], Details>("details");
export const locations = callable<[], { locations: Location[]; current: string }>("locations");
export const setLocation = callable<[path: string], void>("set_location");
export const install = callable<[store: Store, id: string, title: string, kind: "install" | "update"], void>("install");
export const cancel = callable<[store: Store, id: string], void>("cancel");
export const uninstall = callable<[store: Store, id: string], number | null>("uninstall");
export const shortcutInfo = callable<[store: Store, id: string], ShortcutInfo>("shortcut_info");
export const artwork = callable<[store: Store, id: string], Record<string, { data: string; ext: string }>>("artwork");
export const rememberShortcut = callable<[store: Store, id: string, appid: number], void>("remember_shortcut");
export const pending = callable<[], { store: Store; id: string }[]>("pending");

export const size = (n: number) =>
  n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n > 0 ? `${Math.max(1, Math.round(n / 1e6))} MB` : "?";
