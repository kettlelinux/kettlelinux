// The backend's calls (main.py) and what they return.
import { callable } from "@decky/api";

export type Host = {
  uuid: string;
  name: string;
  paired: boolean;
  online: boolean;
  address: string;
  busy: boolean; // streaming to a device now
  apollo: boolean; // Apollo, not Sunshine
  can_wake: boolean; // its network card's address is known (Wake-on-LAN)
};
export type App = { id: number; name: string; hdr: boolean; shortcut: number | null };
export type Preset = "latency" | "balanced" | "battery" | "custom";
export type Settings = {
  preset: Preset;
  resolution: string; // "native" or "<w>x<h>"
  fps: number; // 0: the screen's highest rate up to 120
  bitrate: number; // kbps, 0: Moonlight's own
  codec: "auto" | "H.264" | "HEVC";
  audio: "stereo" | "5.1-surround" | "7.1-surround";
  overlay: boolean;
  host_audio: boolean;
  quit_after: boolean;
  swap_buttons: boolean;
};
export type Device = { width: number; height: number; rates: number[]; max_fps: number };
export type SettingsInfo = { settings: Settings; effective: { resolution: string; fps: number; bitrate: number }; device: Device };
export type Pair = { state: "idle" | "waiting" | "done" | "failed"; address: string; pin: string; error: string; uuid: string };
export type ShortcutInfo = { title: string; exe: string; dir: string; launch: string; host: string };

export const hosts = callable<[discover: boolean], Host[]>("hosts");
export const addHost = callable<[address: string], { uuid: string; name: string; address: string }>("add_host");
export const pair = callable<[address: string], string>("pair");
export const pairStatus = callable<[], Pair>("pair_status");
export const pairCancel = callable<[], void>("pair_cancel");
export const apps = callable<[uuid: string], App[]>("apps");
export const boxart = callable<[uuid: string, appId: number], string>("boxart");
export const settings = callable<[uuid: string], SettingsInfo>("settings");
export const setSettings = callable<[uuid: string, changes: Partial<Settings>], SettingsInfo>("set_settings");
export const shortcutInfo = callable<[uuid: string, app: string], ShortcutInfo>("shortcut_info");
export const rememberShortcut = callable<[uuid: string, app: string, appid: number | null], void>("remember_shortcut");
export const streams = callable<[], Record<string, { uuid: string; app: string }>>("streams");
export const wake = callable<[uuid: string], void>("wake");
export const forget = callable<[uuid: string], number[]>("forget");
export const fpsLimit = callable<[], number>("fps_limit");
