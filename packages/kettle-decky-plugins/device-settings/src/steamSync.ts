// Steam's power controls follow changes made outside Steam (the Performance app on the Thor's
// bottom screen). Steam keeps them as client settings (steamos_tdp_limit, ...) and sends them to
// kettle-powerd through steamos-manager, but never reads them back: a value set in kettle-powerd
// directly left Steam's sliders where they were, and Steam set its own again later.
//
// So, a second after kettle-powerd last said one changed (its PropertiesChanged, passed on by the
// backend as "steam_values"), and every 30 s in case one was missed: a value of Steam's that
// changes in kettle-powerd to something Steam's setting doesn't have was set from outside Steam,
// and goes into Steam's setting (through the setter Steam's own settings pages use), which moves
// the slider and sends it back to kettle-powerd. A change made in Steam reaches kettle-powerd already matching Steam's setting,
// and is left alone. Not at once: setting one of Steam's values makes Steam send kettle-powerd
// the values on the way (the limit turned on at its old value, then the new one), and one of those
// read as set outside Steam went back into Steam's setting.
import { addEventListener, removeEventListener } from "@decky/api";
import { findModuleExport } from "@decky/ui";

export type SteamValues = { tdp: number; profile: string; gpu_level: string; gpu_clock: number; charge_limit: number | null };
type ClientSettings = Record<string, unknown>;

const KEYS = ["tdp", "profile", "gpu_level", "gpu_clock", "charge_limit"] as const;

// Steam's client settings setter (key, value) and the store holding their values
let setSetting: ((key: string, value: unknown) => unknown) | null = null;
let store: { clientSettings: ClientSettings } | null = null;

function findSteam(): boolean {
  if (setSetting && store) return true;
  try {
    setSetting ??= findModuleExport((e: any) => typeof e === "function" && e.toString().includes("Settings.SetSetting("));
    store ??= findModuleExport((e: any) => e && typeof e === "object" && "clientSettings" in e);
  } catch (e) {
    console.warn("Power: Steam's settings not found", e);
  }
  return !!(setSetting && store);
}

// Steam's settings as kettle-powerd has them; tdpMax is "no limit"
function steamValues(cs: ClientSettings, tdpMax: number): SteamValues {
  return {
    tdp: cs.steamos_tdp_limit_enabled ? Number(cs.steamos_tdp_limit) : tdpMax,
    profile: String(cs.steamos_platform_performance_profile ?? ""),
    gpu_level: cs.steamos_manual_gpu_clock_enabled ? "manual" : "auto",
    gpu_clock: Number(cs.steamos_manual_gpu_clock_hz), // MHz, whatever the name says
    charge_limit: cs.steamos_charge_limit_enabled ? Number(cs.steamos_charge_limit) : -1,
  };
}

function setInSteam(key: (typeof KEYS)[number], value: number | string) {
  const set = setSetting!;
  switch (key) {
    case "tdp":
      set("steamos_tdp_limit_enabled", true);
      set("steamos_tdp_limit", value);
      break;
    case "profile":
      set("steamos_platform_performance_profile", value);
      break;
    case "gpu_level":
      set("steamos_manual_gpu_clock_enabled", value === "manual");
      break;
    case "gpu_clock":
      set("steamos_manual_gpu_clock_hz", value);
      break;
    case "charge_limit":
      if (Number(value) < 0) set("steamos_charge_limit_enabled", false);
      else {
        set("steamos_charge_limit_enabled", true);
        set("steamos_charge_limit", value);
      }
      break;
  }
}

// read: kettle-powerd's Steam values and its TDP range's top
export function startSteamSync(read: () => Promise<{ steam: SteamValues; tdpMax: number }>): () => void {
  let last: SteamValues | null = null;
  let busy = false;
  let again = false; // a change told of while looking: look once more after
  const tick = async () => {
    if (busy) {
      again = true;
      return;
    }
    if (!findSteam()) return;
    busy = true;
    try {
      const { steam, tdpMax } = await read();
      const inSteam = steamValues(store!.clientSettings, tdpMax);
      if (last) {
        for (const key of KEYS) {
          const v = steam[key];
          if (v === null || v === undefined || v === last[key] || v === inSteam[key]) continue;
          console.log(`Power: ${key} set outside Steam (${last[key]} -> ${v}), setting it in Steam`);
          setInSteam(key, v);
        }
      }
      last = steam;
    } catch (e) {
      // kettle-powerd away: start over when it's back
      last = null;
    } finally {
      busy = false;
    }
    if (again) {
      again = false;
      tick();
    }
  };
  let settle: ReturnType<typeof setTimeout> | undefined;
  const changed = () => {
    clearTimeout(settle);
    settle = setTimeout(tick, 1000);
  };
  const timer = setInterval(tick, 30000);
  addEventListener("steam_values", changed);
  tick();
  return () => {
    clearInterval(timer);
    clearTimeout(settle);
    removeEventListener("steam_values", changed);
  };
}
