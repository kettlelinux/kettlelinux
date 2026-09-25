// Edit a Steam game's launch options without disturbing what the user put there.
// Steam semantics: options without %command% are appended to the game's command line;
// with %command%, text before it is an env/wrapper prefix.
import { findModuleChild } from "@decky/ui";

const CMD = "%command%";

declare const appDetailsStore: {
  GetAppDetails(appid: number): { strLaunchOptions?: string; strResolutionOverride?: string; bOverrideInternalResolution?: boolean } | null;
};

export function getAppDetails(appid: number) {
  try {
    return appDetailsStore.GetAppDetails(appid);
  } catch {
    return null;
  }
}

// Current launch options; loads the app's details first if Steam hasn't yet.
export function getLaunchOptions(appid: number): Promise<string> {
  const d = getAppDetails(appid);
  if (d && d.strLaunchOptions !== undefined) return Promise.resolve(d.strLaunchOptions);
  return new Promise((resolve) => {
    const reg = SteamClient.Apps.RegisterForAppDetails(appid, (details: any) => {
      reg.unregister();
      resolve(details?.strLaunchOptions ?? "");
    });
  });
}

function split(opts: string): { prefix: string[]; rest: string } {
  const i = opts.indexOf(CMD);
  if (i < 0) return { prefix: [], rest: opts.trim() ? ` ${opts.trim()}` : "" };
  const prefix = opts.slice(0, i).trim();
  return { prefix: prefix ? prefix.split(/\s+/) : [], rest: opts.slice(i + CMD.length) };
}

function join(prefix: string[], rest: string): string {
  if (prefix.length === 0 && rest.trim() === "") return "";
  return `${prefix.length ? prefix.join(" ") + " " : ""}${CMD}${rest}`;
}

// Set (or with value=null remove) VAR=value in the env prefix.
export function withEnv(opts: string, name: string, value: string | null): string {
  const { prefix, rest } = split(opts);
  const kept = prefix.filter((t) => !t.startsWith(`${name}=`));
  if (value !== null) kept.unshift(`${name}=${value}`);
  return join(kept, rest);
}

// Set (or with entry=null remove) one entry of a list-valued variable, keeping the user's
// other entries: flags in TU_DEBUG=noubwc,sysmem, or `key=value` lines in
// DXVK_CONFIG="dxgi.maxFrameRate=60;d3d9.maxFrameRate=60" (matched on the part before "=").
function withEnvEntry(opts: string, name: string, sep: string, key: string, entry: string | null): string {
  const tok = split(opts).prefix.find((t) => t.startsWith(`${name}=`));
  const quoted = tok !== undefined && /^"|"$/.test(tok.slice(name.length + 1));
  let items = tok ? tok.slice(name.length + 1).replace(/^"|"$/g, "").split(sep).filter(Boolean) : [];
  items = items.filter((i) => i.split("=")[0].trim() !== key);
  if (entry !== null) items.push(entry);
  if (!items.length) return withEnv(opts, name, null);
  const value = items.join(sep);
  return withEnv(opts, name, quoted || /[;\s]/.test(value) ? `"${value}"` : value);
}

// Add (or with on=false remove) one flag in a comma-separated variable (TU_DEBUG).
export function withEnvFlag(opts: string, name: string, flag: string, on: boolean): string {
  return withEnvEntry(opts, name, ",", flag, on ? flag : null);
}

// Set (or with value=null remove) one `key=value` option in DXVK_CONFIG.
export function withDxvkOption(opts: string, key: string, value: string | null): string {
  return withEnvEntry(opts, "DXVK_CONFIG", ";", key, value === null ? null : `${key}=${value}`);
}

// Add (or remove) one entry such as "dxgi=n,b" in WINEDLLOVERRIDES, keeping the others.
export function withDllOverride(opts: string, dll: string, value: string | null): string {
  return withEnvEntry(opts, "WINEDLLOVERRIDES", ";", dll, value === null ? null : `${dll}=${value}`);
}

// Add (or with on=false remove) an `env -u NAME` wrapper, which unsets a variable the session
// sets. Kept last in the prefix, so withEnv's VAR=value tokens still apply to the game.
export function withUnset(opts: string, name: string, on: boolean): string {
  const { prefix, rest } = split(opts);
  const kept: string[] = [];
  for (let i = 0; i < prefix.length; i++) {
    if (prefix[i] === "env" && prefix[i + 1] === "-u" && prefix[i + 2] === name) i += 2;
    else kept.push(prefix[i]);
  }
  if (on) kept.push("env", "-u", name);
  return join(kept, rest);
}

export function hasEnv(opts: string, name: string): boolean {
  return split(opts).prefix.some((t) => t.startsWith(`${name}=`));
}

export function hasUnset(opts: string, name: string): boolean {
  const { prefix } = split(opts);
  return prefix.some((t, i) => t === "env" && prefix[i + 1] === "-u" && prefix[i + 2] === name);
}

export function hasDllOverride(opts: string, dll: string): boolean {
  const tok = split(opts).prefix.find((t) => t.startsWith("WINEDLLOVERRIDES="));
  return !!tok && tok.slice("WINEDLLOVERRIDES=".length).replace(/^"|"$/g, "").split(";").some((e) => e.split("=")[0] === dll);
}

export async function editLaunchOptions(appid: number, edit: (opts: string) => string) {
  const before = await getLaunchOptions(appid);
  const after = edit(before);
  if (after !== before) SteamClient.Apps.SetAppLaunchOptions(appid, after);
}

// The Steam UI's performance-settings store (Quick Access > Performance). Located by shape,
// since webpack names change between client builds; null if this client doesn't have it.
type PerfStore = { SetSplitScalingFilter(v: number): void; SetFSRSharpness(v: number): void; msgSettingsPerApp?: any };
let perfStore: { Get(): PerfStore } | null | undefined;
export function getPerfStore(): PerfStore | null {
  if (perfStore === undefined) {
    perfStore =
      findModuleChild((m: any) => {
        if (typeof m !== "object" || m === null) return undefined;
        for (const k of Object.keys(m)) {
          try {
            const v = m[k];
            if (v && typeof v.Get === "function" && typeof v.Get()?.SetFSRSharpness === "function") return v;
          } catch {}
        }
        return undefined;
      }) ?? null;
  }
  return perfStore ? perfStore.Get() : null;
}
