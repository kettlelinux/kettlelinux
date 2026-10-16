// The Performance tab: kettle-powerd's per-game fan, CPU and Auto TDP settings (with "All games"
// picked, the settings every game without its own uses), and a game's own refresh rate, held
// while it runs (the all-games rate is Device Settings'), and in Unreal Engine 5 games Lumen (off
// unless turned back on, for all games or one) and the Nanite fix for DirectX 12 (on unless turned
// off for a game): lumen.py. Steam's TDP limit, profile and GPU clock stay in Quick Access >
// Performance.
import { ButtonItem, DropdownItem, PanelSectionRow, SliderField, ToggleField } from "@decky/ui";
import { callable } from "@decky/api";
import { useEffect, useState } from "react";
import { runningAppId } from "../../shared/GamePicker";

type Cluster = { name: string; cpus: number[]; freqs: number[] };
type Info = {
  clusters: Cluster[];
  gpu_mhz: number[];
  default_curve: [number, number][];
  full_speed_temp: number;
  fan: boolean;
  profiles: string[];
  tdp: [number, number];
  charge_limit: boolean;
  charge_limit_min: number;
  charge_speeds: { name: string; ua: number }[];
  charge_custom: { min: number; max: number; step: number } | null;
  sleep_fan: boolean;
};
type FanMode = "auto" | "curve" | "fixed";
type Settings = {
  fan: { mode: FanMode; curve: [number, number][]; fixed: number };
  cpu: { little: number | null; mid: number | null; prime: number | null; mid_cores: number; prime_core: boolean };
  auto_tdp: boolean;
};
type Patch = { fan?: Partial<Settings["fan"]>; cpu?: Partial<Settings["cpu"]>; auto_tdp?: boolean };
type Game = { custom: boolean; settings: Settings };
// what the tab needs from kettle-powerd's status
type Status = { steam: { fan_control: number }; auto_tdp: { fps_limit: number } };
// the rates there are, the all-games one (0 Auto) and the games' own, by appid
// framegen: games with Frame Gen on, which holds their rate instead
type Refresh = { rates: number[]; hz: number; games: Record<string, number>; framegen: Record<string, number> };

// Lumen: the all-games default, and with a game, its state and the Nanite fix's (lumen.py's get)
type Lumen = {
  default_off: boolean; ue5?: boolean; choice?: "default" | "off" | "on"; off?: boolean; applied?: boolean; pending?: boolean;
  nanite?: boolean; nanite_applied?: boolean; nanite_pending?: boolean;
};

const info = callable<[], Info>("perf_info");
const status = callable<[], Status>("perf_status");
const getGame = callable<[appid: number | null], Game>("perf_get_game");
// kettle-powerd merges what it gets into the game's settings (fan and cpu key by key); null resets
const setGame = callable<[appid: number | null, settings: Patch | Settings | null], Game>("perf_set_game");
const getRefresh = callable<[], Refresh>("get_refresh");
const setGameRefresh = callable<[appid: number, hz: number | null, running: boolean], Refresh>("set_game_refresh");
const getLumen = callable<[appid: number | null], Lumen>("lumen_get");
const setLumen = callable<[appid: number | null, value: boolean | string], Lumen>("lumen_set");
const setNanite = callable<[appid: number, on: boolean], Lumen>("lumen_set_nanite");
// after a game exits (index.tsx): a first launch made its prefix, or it rewrote its Engine.ini
export const syncLumen = callable<[], void>("lumen_sync");

const FAN_MODES = [
  { data: "auto", label: "Automatic (built-in curve)" },
  { data: "curve", label: "Custom curve" },
  { data: "fixed", label: "Fixed speed" },
];
const CLUSTER_LABEL: Record<string, string> = { little: "Efficiency cores", mid: "Performance cores", prime: "Prime core" };
const mhz = (khz: number | null | undefined) => (khz ? `${Math.round(khz / 1000)} MHz` : "off");
const small = { fontSize: "12px", lineHeight: "16px" };

// Curve points stay in order: raising a point raises the ones after it, lowering lowers the ones before
function setPoint(curve: [number, number][], i: number, pct: number): [number, number][] {
  return curve.map(([t, p], j): [number, number] => [t, j === i ? pct : j > i ? Math.max(p, pct) : Math.min(p, pct)]);
}

// Cluster cap slider: steps are the cluster's frequencies, the last one meaning no cap
function CapSlider({ c, value, onChange }: { c: Cluster; value: number | null; onChange: (v: number | null) => void }) {
  const top = c.freqs.length - 1;
  const idx = value === null ? top : Math.max(0, c.freqs.filter((f) => f <= value).length - 1);
  return (
    <PanelSectionRow>
      <SliderField
        label={`${CLUSTER_LABEL[c.name] ?? c.name} max`}
        description={idx === top ? "No limit" : mhz(c.freqs[idx])}
        value={idx}
        min={0}
        max={top}
        step={1}
        onChange={(i) => onChange(i === top ? null : c.freqs[i])}
      />
    </PanelSectionRow>
  );
}

function PowerSettings({ appid, name, inf, fanControl, fpsLimit }: { appid: number | null; name: string; inf: Info; fanControl: boolean; fpsLimit: number }) {
  const [g, setG] = useState<Game | null>(null);
  useEffect(() => {
    setG(null);
    getGame(appid).then(setG);
  }, [appid]);
  if (!g) return null;
  const s = g.settings;
  // a game without its own settings shows (and edits) the all-games ones
  const target = appid !== null && g.custom ? appid : null;
  // only the change goes out, so it can't undo one made meanwhile elsewhere (the Performance app)
  const update = async (patch: Patch) => {
    const next = { fan: { ...s.fan, ...patch.fan }, cpu: { ...s.cpu, ...patch.cpu }, auto_tdp: patch.auto_tdp ?? s.auto_tdp };
    setG({ ...g, settings: next });
    setG(own(await setGame(target, patch)));
  };
  // kettle-powerd's answer for the all-games settings says custom; for a game following them, it isn't
  const own = (r: Game): Game => (target === null ? { ...r, custom: false } : r);
  const clusters = Object.fromEntries(inf.clusters.map((c) => [c.name, c]));
  const midCount = clusters.mid?.cpus.length ?? 0;

  return (
    <>
      {appid !== null && (
        <PanelSectionRow>
          <ToggleField
            label="Settings for this game only"
            description={g.custom ? `${name} has its own settings` : "Off: the all-games settings apply"}
            checked={g.custom}
            onChange={async (on) => setG(await setGame(appid, on ? s : null))}
          />
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <div style={small}>Editing: {target === null ? "all games" : `${name} only`}</div>
      </PanelSectionRow>

      <PanelSectionRow>
        <ToggleField
          label="Auto TDP"
          description={fpsLimit
            ? `Holds Steam's frame rate limit (${fpsLimit} fps) on the lowest CPU and GPU clocks that keep it`
            : "Set a frame rate limit in Steam's Performance panel: Auto TDP holds it on the lowest clocks that keep it"}
          checked={s.auto_tdp}
          onChange={(auto_tdp) => update({ auto_tdp })}
        />
      </PanelSectionRow>

      {inf.fan && (
        <>
          <PanelSectionRow>
            <DropdownItem
              label="Fan"
              description={fanControl ? undefined : "Fan control is off in Steam's settings: the built-in curve runs"}
              rgOptions={FAN_MODES}
              selectedOption={s.fan.mode}
              onChange={(o) => update({ fan: { mode: o.data } })}
            />
          </PanelSectionRow>
          {s.fan.mode === "fixed" && (
            <PanelSectionRow>
              <SliderField label="Fan speed" value={s.fan.fixed} min={0} max={100} step={5} showValue valueSuffix="%"
                onChange={(fixed) => update({ fan: { fixed } })} />
            </PanelSectionRow>
          )}
          {s.fan.mode === "curve" &&
            s.fan.curve.map(([t, p], i) => (
              <PanelSectionRow key={t}>
                <SliderField label={`At ${t} °C`} value={p} min={0} max={100} step={5} showValue valueSuffix="%"
                  onChange={(v) => update({ fan: { curve: setPoint(s.fan.curve, i, v) } })} />
              </PanelSectionRow>
            ))}
          {s.fan.mode !== "auto" && (
            <PanelSectionRow>
              <div style={small}>Full speed from {inf.full_speed_temp} °C whatever the setting.</div>
            </PanelSectionRow>
          )}
        </>
      )}

      {clusters.prime && (
        <PanelSectionRow>
          <ToggleField
            label="Prime core"
            description="Off parks the fastest core: less heat in games that don't need it"
            checked={s.cpu.prime_core}
            onChange={(prime_core) => update({ cpu: { prime_core } })}
          />
        </PanelSectionRow>
      )}
      {midCount > 1 && (
        <PanelSectionRow>
          <SliderField label="Performance cores" value={s.cpu.mid_cores} min={1} max={midCount} step={1} showValue
            notchCount={midCount} notchTicksVisible onChange={(mid_cores) => update({ cpu: { mid_cores } })} />
        </PanelSectionRow>
      )}
      {inf.clusters.map((c) => (
        <CapSlider key={c.name} c={c} value={s.cpu[c.name as "little" | "mid" | "prime"]}
          onChange={(v) => update({ cpu: { [c.name]: v } })} />
      ))}
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={async () => setG(own(await setGame(target, target === null ? { fan: { mode: "auto", curve: inf.default_curve, fixed: 50 }, cpu: { little: null, mid: null, prime: null, mid_cores: midCount, prime_core: true }, auto_tdp: true } : null)))}
        >
          {target === null ? "Reset all-games settings" : `Reset ${name} to all-games settings`}
        </ButtonItem>
      </PanelSectionRow>
    </>
  );
}

// A game's own refresh rate, held while it runs; the others follow Device Settings' all-games one
function GameRefresh({ appid, name, r, onChange }: { appid: number; name: string; r: Refresh; onChange: (r: Refresh) => void }) {
  const hz = r.games[String(appid)] ?? null;
  const all = r.hz === 0 ? "Auto" : `${r.hz} Hz`;
  const fg = r.framegen[String(appid)];
  if (fg)
    return (
      <PanelSectionRow>
        <DropdownItem
          label="Refresh rate"
          description={`Frame Gen holds ${fg} Hz while ${name} runs (its Base FPS)`}
          rgOptions={[{ data: fg, label: `${fg} Hz` }]}
          selectedOption={fg}
          disabled
        />
      </PanelSectionRow>
    );
  return (
    <PanelSectionRow>
      <DropdownItem
        label="Refresh rate"
        description={hz === null ? "Follows the all-games rate (Device Settings › Power)" : `Used while ${name} runs`}
        rgOptions={[
          { data: -1, label: `All games' (${all})` },
          { data: 0, label: "Auto" },
          ...r.rates.map((v) => ({ data: v, label: `${v} Hz` })),
        ]}
        selectedOption={hz ?? -1}
        onChange={async (o) => {
          const v = o.data === -1 ? null : o.data;
          const games = { ...r.games };
          if (v === null) delete games[String(appid)];
          else games[String(appid)] = v;
          onChange({ ...r, games });
          onChange(await setGameRefresh(appid, v, runningAppId() === appid));
        }}
      />
    </PanelSectionRow>
  );
}

// Lumen, UE5's global illumination and reflections: off in UE5 games unless turned back on; and
// with a game, its Nanite fix (Nanite's meshes drawn in software: its hardware path is broken in
// DirectX 12 here)
function LumenSetting({ appid, name }: { appid: number | null; name: string }) {
  const [l, setL] = useState<Lumen | null>(null);
  useEffect(() => {
    setL(null);
    getLumen(appid).then(setL).catch(() => {});
  }, [appid]);
  if (!l) return null;
  if (appid === null)
    return (
      <PanelSectionRow>
        <ToggleField
          label="Lumen off in Unreal Engine 5 games"
          description="UE5's global illumination and reflections: the heaviest part of most UE5 games here. Some games look darker without it; turn it back on per game. Takes effect at each game's next launch."
          checked={l.default_off}
          onChange={async (on) => {
            setL({ ...l, default_off: on });
            setL(await setLumen(null, on));
          }}
        />
      </PanelSectionRow>
    );
  if (!l.ue5) return null;
  const all = l.default_off ? "Off" : "On";
  const state = l.pending
    ? `Off from ${name}'s next launch (it hasn't run here yet)`
    : l.off
      ? `Off: set in ${name}'s Engine.ini from its next launch. A game that ignores it keeps Lumen.`
      : "On: the game's own setting";
  const nanite = l.nanite_pending
    ? `On from ${name}'s next launch (it hasn't run here yet). `
    : l.nanite
      ? `On: set in ${name}'s Engine.ini from its next launch. `
      : "";
  return (
    <>
      <PanelSectionRow>
        <DropdownItem
          label="Lumen (Unreal Engine 5)"
          description={state}
          rgOptions={[
            { data: "default", label: `All games' (${all})` },
            { data: "off", label: "Off" },
            { data: "on", label: "On" },
          ]}
          selectedOption={l.choice ?? "default"}
          onChange={async (o) => {
            setL({ ...l, choice: o.data });
            setL(await setLumen(appid, o.data));
          }}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label="Nanite fix (Unreal Engine 5)"
          description={`${nanite}Draws Nanite meshes in software: in DirectX 12 the faster path makes distant objects vanish as you get close.`}
          checked={l.nanite ?? true}
          onChange={async (on) => {
            setL({ ...l, nanite: on });
            setL(await setNanite(appid, on));
          }}
        />
      </PanelSectionRow>
    </>
  );
}

export function PerformanceTab({ appid, name }: { appid: number | null; name: string }) {
  const [inf, setInf] = useState<Info | null>(null);
  const [s, setS] = useState<Status | null>(null);
  const [r, setR] = useState<Refresh | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    info().then(setInf).catch(() => setError(true));
    status().then(setS).catch(() => setError(true));
    getRefresh().then(setR);
  }, []);
  if (error)
    return (
      <PanelSectionRow>
        <div style={small}>The power service (kettle-powerd) isn't running.</div>
      </PanelSectionRow>
    );
  if (!inf || !s) return null;
  return (
    <>
      <PowerSettings key={appid ?? "all"} appid={appid} name={name} inf={inf}
        fanControl={s.steam.fan_control === 1} fpsLimit={s.auto_tdp.fps_limit} />
      {appid !== null && r && r.rates.length >= 2 && <GameRefresh appid={appid} name={name} r={r} onChange={setR} />}
      <LumenSetting key={`lumen-${appid ?? "all"}`} appid={appid} name={name} />
    </>
  );
}
