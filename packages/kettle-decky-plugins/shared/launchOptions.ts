// Edit a Steam game's launch options without disturbing what the user put there.
// Steam semantics: options without %command% are appended to the game's command line;
// with %command%, text before it is an env/wrapper prefix.
import { findModuleChild } from "@decky/ui";

const CMD = "%command%";

type AppDetails = { strLaunchOptions?: string; strResolutionOverride?: string; bOverrideInternalResolution?: boolean };
declare const appDetailsStore: { GetAppDetails(appid: number): AppDetails | null };

export function getAppDetails(appid: number) {
  try {
    return appDetailsStore.GetAppDetails(appid);
  } catch {
    return null;
  }
}

// The app's details straight from Steam. appDetailsStore's copy (getAppDetails) isn't updated
// by SetAppLaunchOptions and friends (checked on the Portal's client): reading it after a write
// returns what was there before, and an edit built on that puts the old options back.
export function getFreshAppDetails(appid: number): Promise<AppDetails | null> {
  return new Promise((resolve) => {
    let reg: { unregister(): void } | null = null;
    let done = false;
    const finish = (d: AppDetails | null) => {
      if (done) return;
      done = true;
      reg?.unregister();
      resolve(d);
    };
    reg = SteamClient.Apps.RegisterForAppDetails(appid, (d: AppDetails) => finish(d ?? null));
    if (done) reg.unregister(); // the callback ran before reg was assigned
    setTimeout(() => finish(getAppDetails(appid)), 2000);
  });
}

export async function getLaunchOptions(appid: number): Promise<string> {
  return (await getFreshAppDetails(appid))?.strLaunchOptions ?? "";
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

// Set (or with value=null remove) VAR=value in the env prefix: in its place when it's there
// already, else first.
export function withEnv(opts: string, name: string, value: string | null): string {
  const { prefix, rest } = split(opts);
  const at = prefix.findIndex((t) => t.startsWith(`${name}=`));
  const kept = prefix.filter((t) => !t.startsWith(`${name}=`));
  if (value !== null) kept.splice(Math.max(at, 0), 0, `${name}=${value}`);
  return join(kept, rest);
}

// The value of VAR in the env prefix as written (quotes included), or null.
export function envValue(opts: string, name: string): string | null {
  const tok = split(opts).prefix.find((t) => t.startsWith(`${name}=`));
  return tok === undefined ? null : tok.slice(name.length + 1);
}

// One entry of a list-valued variable (see withEnvEntry), or null.
function envEntry(opts: string, name: string, sep: string, key: string): string | null {
  const v = envValue(opts, name);
  if (v === null) return null;
  return v.replace(/^"|"$/g, "").split(sep).find((i) => i.split("=")[0].trim() === key) ?? null;
}

export const hasEnvFlag = (opts: string, name: string, flag: string) => envEntry(opts, name, ",", flag) !== null;

export function dxvkOption(opts: string, key: string): string | null {
  const e = envEntry(opts, "DXVK_CONFIG", ";", key);
  return e === null ? null : e.slice(e.indexOf("=") + 1).trim();
}

export function dllOverride(opts: string, dll: string): string | null {
  const e = envEntry(opts, "WINEDLLOVERRIDES", ";", dll);
  return e === null || !e.includes("=") ? null : e.slice(e.indexOf("=") + 1);
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

// Add a wrapper command (such as `bash -c '...' --`) just before %command%, after the env
// prefix. The edits above keep it as it is, provided its words are single-spaced and none is
// VAR=value or `env`; VAR=value tokens they add go before it, `env -u` after it.
export function withWrapper(opts: string, wrapper: string): string {
  const { prefix, rest } = split(opts);
  return join([...prefix, wrapper], rest);
}

// Remove a wrapper withWrapper added (matched word for word).
export function withoutWrapper(opts: string, wrapper: string): string {
  const { prefix, rest } = split(opts);
  const words = wrapper.split(" ");
  for (let i = 0; i + words.length <= prefix.length; i++) {
    if (words.every((w, j) => prefix[i + j] === w)) {
      prefix.splice(i, words.length);
      return join(prefix, rest);
    }
  }
  return opts;
}

export function hasWrapper(opts: string, wrapper: string): boolean {
  return withoutWrapper(opts, wrapper) !== opts;
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

// Edits run one at a time, so two in flight can't both start from the same options.
let editQueue: Promise<unknown> = Promise.resolve();
export function editLaunchOptions(appid: number, edit: (opts: string) => string): Promise<void> {
  const run = editQueue.then(async () => {
    const before = await getLaunchOptions(appid);
    const after = edit(before);
    if (after !== before) SteamClient.Apps.SetAppLaunchOptions(appid, after);
  });
  editQueue = run.catch(() => {});
  return run;
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
