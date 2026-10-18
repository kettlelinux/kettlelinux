// The backend's calls (main.py) and what they return.
import { callable } from "@decky/api";

export type Emulator = { id: string; name: string; installed: boolean; download: boolean; flatpak: boolean; license: string };
export type BiosState = "ok" | "missing-required" | "missing-optional" | "none";
export type System = {
  id: string;
  name: string;
  folder: string;
  count: number;
  emulators: Emulator[];
  emulator: string; // the one its games start with ("" when none is installed)
  bios: BiosState;
  bios_from_core: boolean; // what it misses is only its core's folders (system_dirs), from Extra cores
  note: string;
  extensions: string[];
};
export type Storage = { path: string; emulation: string; label: string; internal: boolean; set_up: boolean };
export type Settings = { first_run_done: boolean; auto_inbox: boolean; sgdb_key: string };
export type Overview = { systems: System[]; total: number; face: "xbox" | "nintendo"; settings: Settings; storages: Storage[] };

export type Entry = {
  id: string;
  title: string;
  system: string;
  exe: string;
  dir: string;
  launch: string;
  collection: string;
  appid: number | null;
  was?: number | null; // a game brought back: the shortcut it had, used again if Steam has it
};
export type Plan = {
  add: Entry[];
  update: Entry[];
  remove: { id: string; appid: number; system: string }[];
  check: { id: string; appid: number; system: string }[];
  layout: string;
};
export type LibraryState = {
  collections: Record<string, { name: string; id: string | null; appids: number[] }>;
  layout: number[];
  art: { id: string; appid: number }[];
};
export type Art = Record<string, { data: string; ext: string }>;
export type Game = { id: string; title: string; path: string; appid: number | null; emulator: string };

export type Running = {
  system: string;
  rom: string;
  emulator: string;
  emulator_name: string;
  pid: number;
  bridge: boolean;
  appid: string | null;
  id: string | null;
  title: string;
  emulators: Emulator[];
  rewind: boolean; // its emulator rewinds (systems.json)
  game_choice: string;
};
export type HotkeyAction =
  | "save_state"
  | "load_state"
  | "menu"
  | "fast_forward"
  | "slot_down"
  | "slot_up"
  | "rewind"
  | "screenshot"
  | "swap_screens"
  | "quit";

export type BiosEntry = {
  file: string;
  required: boolean;
  one_of: boolean;
  note: string;
  found: string | null; // installed where the emulators look
  elsewhere: string | null; // a right file somewhere else, for bios_install to copy into place
  bad: string | null;
  folder?: boolean; // a folder its core needs (system_dirs), downloaded with it in Extra cores
};
export type BiosSystem = { id: string; name: string; state: BiosState; entries: BiosEntry[] };

export type Media = { path: string; label: string; set_up: boolean; games_total: number; games: Record<string, number>; bios: number; bytes: number };
export type Job = {
  state: "idle" | "running" | "done" | "failed" | "cancelled";
  kind?: "import" | "inbox";
  path?: string;
  files?: number;
  done?: number;
  bytes?: number;
  bytes_done?: number;
  current?: string;
  error?: string;
  unsorted?: number;
  stats?: { games: Record<string, number>; bios: unknown[]; unsorted: number; identical: number; errors: number } | null;
};
// id: what assign takes (the path's bytes in hex); path and name are for showing (a name that isn't UTF-8 has U+FFFD in it)
export type Unsorted = { id: string; path: string; name: string; size: number; systems: string[]; storage: string };
export type Upload = { state: "off" | "on" | "locked"; pin?: string; urls?: string[]; port?: number; uploaded?: number; last?: string };
export type Share = { enabled: boolean; active: boolean; share: string; path: string; user: string; hostname: string; urls: string[] };

// id: what saveDelete and backup take; thumb: the picture's id for saveThumb ("" without one); path is for showing
export type SaveFile = { id: string; path: string; kind: "save" | "state"; slot: string; size: number; mtime: number; thumb: string };
export type SaveGame = { id: string; title: string; system: string; files: SaveFile[] };
export type Backup = { id: string; path: string; size: number; mtime: number };
export type Core = {
  core: string;
  emulator: string;
  name: string;
  license: string;
  terms: string;
  installed: boolean;
  size: number;
  systems: string[];
  system_dirs: string[]; // folders it needs in Emulation/bios, downloaded with it
  missing: string[]; // those of them that aren't there (it isn't installed until they are)
};

export const overview = callable<[], Overview>("overview");
export const syncPlan = callable<[], Plan>("sync_plan");
// returns the games now counted as deleted in Steam
export const synced = callable<[added: Record<string, number>, updated: string[], removed: string[], missing: string[], seen: string[]], string[]>(
  "synced",
);
export const libraryState = callable<[], LibraryState>("library_state");
export const setCollection = callable<[system: string, id: string | null], void>("set_collection");
export const layoutDone = callable<[appids: number[]], void>("layout_done");
export const artwork = callable<[id: string, chosen: string | null], Art>("artwork");
export const artDone = callable<[id: string, ok: boolean], void>("art_done");
export const artChoices = callable<[id: string], string[]>("art_choices");
export const games = callable<[system: string], Game[]>("games");
export const restoreDeleted = callable<[system: string], number>("restore_deleted");
export const setChoice = callable<[system: string, emulator: string | null], void>("set_choice");
export const setGameChoice = callable<[id: string, emulator: string | null], void>("set_game_choice");
export const running = callable<[], Running | null>("running");
export const hotkey = callable<[action: HotkeyAction], boolean>("hotkey");
export const bios = callable<[], { systems: BiosSystem[]; folder: string }>("bios");
// copies the BIOS files found elsewhere into place (one system's, or all); the names installed
export const biosInstall = callable<[system: string | null], string[]>("bios_install");
export const media = callable<[], Media[]>("media");
export const setUpCard = callable<[path: string], void>("set_up_card");
export const importStart = callable<[path: string, mode: "copy" | "move", dest: string], void>("import_start");
export const inboxNow = callable<[], void>("inbox_now");
export const importStatus = callable<[], Job>("import_status");
export const importCancel = callable<[], void>("import_cancel");
export const unsorted = callable<[], Unsorted[]>("unsorted");
export const assign = callable<[id: string, system: string], void>("assign");
export const uploadStart = callable<[], Upload>("upload_start");
export const uploadStatus = callable<[], Upload>("upload_status");
export const uploadStop = callable<[], void>("upload_stop");
export const shareStatus = callable<[], Share>("share_status");
export const shareEnable = callable<[password: string], Share>("share_enable");
export const shareDisable = callable<[], Share>("share_disable");
export const saves = callable<[], SaveGame[]>("saves");
export const saveThumb = callable<[id: string], string>("save_thumb");
export const saveDelete = callable<[ids: string[]], number>("save_delete");
export const backup = callable<[ids: string[], dest: string], string>("backup");
export const backups = callable<[], Backup[]>("backups");
export const restore = callable<[id: string], { restored: number; skipped: number }>("restore");
export const cores = callable<[], Core[]>("cores");
export const coreDownload = callable<[core: string], Core[]>("core_download");
export const coreRemove = callable<[core: string], Core[]>("core_remove");
export const setSettings = callable<[changes: Partial<Settings>], Settings>("set_settings");
