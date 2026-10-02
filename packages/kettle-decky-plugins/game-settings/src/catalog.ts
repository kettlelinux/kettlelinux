// The options Game Settings offers (shared/game-options.json, which the game database server
// validates against too) and how a profile turns into launch options.
import raw from "../../shared/game-options.json";
import {
  dllOverride,
  dxvkOption,
  envValue,
  hasEnvFlag,
  withDllOverride,
  withDxvkOption,
  withEnv,
  withEnvFlag,
} from "../../shared/launchOptions";

export type Choice = { value: string; label: string };
export type Target = { env?: string; flags?: string; flag?: string; dxvk?: string };
export type Option = { id: string; section: string; label: string; help: string; target: Target; choices: Choice[] };
export type Section = { id: string; title: string; help: string };
export type Preset = { id: string; label: string; help: string; section?: string; settings: Record<string, string> };
type Catalog = {
  sections: Section[];
  options: Option[];
  presets: Preset[];
  custom: {
    env_name: string;
    env_prefixes: string[];
    env_reserved: string[];
    env_value: string;
    dll_name: string;
    dll_modes: Choice[];
    max_env: number;
    max_dlls: number;
  };
};

export const CATALOG = raw as unknown as Catalog;
export const OPTIONS = CATALOG.options;
export const optionById = new Map(OPTIONS.map((o) => [o.id, o]));

export type Profile = {
  settings: Record<string, string>;
  env: [string, string][];
  dlls: [string, string][];
  compat_tool: string | null;
};
// Launch option entries the plugin wrote, each with what was there before it (null: nothing),
// which is put back when the profile no longer has it
export type Owned = { options: Record<string, string | null>; env: Record<string, string | null>; dlls: Record<string, string | null> };

export const EMPTY: Profile = { settings: {}, env: [], dlls: [], compat_tool: null };
export const NOTHING_OWNED: Owned = { options: {}, env: {}, dlls: {} };

// variables the catalog's options (and the other Kettle plugins) manage: not for custom entries
const MANAGED = new Set([
  ...CATALOG.custom.env_reserved,
  ...OPTIONS.map((o) => o.target.env ?? o.target.flags ?? "DXVK_CONFIG"),
]);

export function envError(name: string, value: string): string | null {
  const c = CATALOG.custom;
  if (!new RegExp(c.env_name).test(name)) return "Names are capital letters, digits and _";
  if (!c.env_prefixes.some((p) => name.startsWith(p))) return `Only ${c.env_prefixes.join(", ")} variables`;
  if (MANAGED.has(name)) return `${name} is set from the options above`;
  if (!new RegExp(c.env_value).test(value)) return "Values can't have spaces, quotes, / or $";
  return null;
}

export function dllError(name: string): string | null {
  return new RegExp(CATALOG.custom.dll_name).test(name) ? null : "A DLL name without .dll, such as dinput8";
}

function setTarget(opts: string, t: Target, value: string | null): string {
  if (t.env) return withEnv(opts, t.env, value);
  if (t.flags && t.flag) return withEnvFlag(opts, t.flags, t.flag, value !== null);
  if (t.dxvk) return withDxvkOption(opts, t.dxvk, value);
  return opts;
}

function targetValue(opts: string, t: Target): string | null {
  if (t.env) return envValue(opts, t.env);
  if (t.flags && t.flag) return hasEnvFlag(opts, t.flags, t.flag) ? "1" : null;
  if (t.dxvk) return dxvkOption(opts, t.dxvk);
  return null;
}

// ';' would end the command in Steam's shell
const quote = (v: string) => (/;/.test(v) ? `"${v}"` : v);

const has = (rec: object, k: string) => Object.prototype.hasOwnProperty.call(rec, k);

// The launch options with the profile in them, and what the plugin owns in them now. An entry
// the plugin wrote before (owned) that the profile no longer has gets back what was there before
// it, so a variable the player had set themselves survives; everything else is left as it is.
export function applyProfile(opts: string, p: Profile, owned: Owned): { opts: string; owned: Owned } {
  const now: Owned = { options: {}, env: {}, dlls: {} };
  for (const o of OPTIONS) {
    const v = p.settings[o.id];
    if (v !== undefined) {
      now.options[o.id] = has(owned.options, o.id) ? owned.options[o.id] : targetValue(opts, o.target);
      opts = setTarget(opts, o.target, v);
    } else if (has(owned.options, o.id)) opts = setTarget(opts, o.target, owned.options[o.id]);
  }
  for (const n of Object.keys(owned.env)) if (!p.env.some(([m]) => m === n)) opts = withEnv(opts, n, owned.env[n]);
  for (const [n, v] of p.env) {
    now.env[n] = has(owned.env, n) ? owned.env[n] : envValue(opts, n);
    opts = withEnv(opts, n, quote(v));
  }
  for (const d of Object.keys(owned.dlls)) if (!p.dlls.some(([e]) => e === d)) opts = withDllOverride(opts, d, owned.dlls[d]);
  for (const [d, m] of p.dlls) {
    now.dlls[d] = has(owned.dlls, d) ? owned.dlls[d] : dllOverride(opts, d);
    opts = withDllOverride(opts, d, m);
  }
  return { opts, owned: now };
}

export function changedIn(p: Profile, section: string): number {
  return OPTIONS.filter((o) => o.section === section && p.settings[o.id] !== undefined).length;
}

export function isEmpty(p: Profile): boolean {
  return Object.keys(p.settings).length === 0 && p.env.length === 0 && p.dlls.length === 0 && !p.compat_tool;
}

// A preset on top of a profile: it replaces its own section's settings (FEX presets) or just
// the settings it names
export function withPreset(p: Profile, preset: Preset): Profile {
  const settings = { ...p.settings };
  if (preset.section)
    for (const o of OPTIONS) if (o.section === preset.section) delete settings[o.id];
  return { ...p, settings: { ...settings, ...preset.settings } };
}

// What a profile changes, in words, for lists and the database page
export function describe(p: Profile, tools?: Map<string, string>): string[] {
  const out = OPTIONS.filter((o) => p.settings[o.id] !== undefined).map((o) => {
    const c = o.choices.find((c) => c.value === p.settings[o.id]);
    return o.choices.length === 1 ? o.label : `${o.label}: ${c?.label ?? p.settings[o.id]}`;
  });
  for (const [n, v] of p.env) out.push(`${n}=${v}`);
  for (const [d, m] of p.dlls) out.push(`${d}.dll ${m || "disabled"}`);
  if (p.compat_tool) out.push(`Proton: ${tools?.get(p.compat_tool) ?? p.compat_tool}`);
  return out;
}

export const profileOf = (g: Profile): Profile => ({
  settings: g.settings,
  env: g.env,
  dlls: g.dlls,
  compat_tool: g.compat_tool,
});
