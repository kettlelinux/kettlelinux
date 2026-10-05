import { ButtonItem, DropdownItem, Field, PanelSection, PanelSectionRow, SliderField, ToggleField, staticClasses } from "@decky/ui";
import { callable, definePlugin } from "@decky/api";
import { useEffect, useState } from "react";
import { FaBolt } from "react-icons/fa";
import { GamePicker, InstalledGame, gameName, runningAppId, useSelectedGame } from "../../shared/GamePicker";
import { startSteamSync } from "./steamSync";

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
};
type Steam = { tdp: number; profile: string; gpu_level: string; gpu_clock: number; fan_control: number; charge_limit: number | null };
type Status = {
  power_w: number | null;
  temp_c: number | null;
  fan_rpm: number | null;
  fan_pct: number | null;
  cpu_khz: Record<string, number | null>;
  cpu_cap_khz: Record<string, number>;
  gpu_mhz: number;
  gpu_cap_mhz: number;
  gpu_load: number | null;
  tdp_limiting: boolean;
  steam: Steam;
  battery: { status: string | null; capacity: number | null };
  charge_speed: string;
  charge_custom_ua: number;
  charge_held: boolean;
};
type FanMode = "auto" | "curve" | "fixed";
type Settings = {
  fan: { mode: FanMode; curve: [number, number][]; fixed: number };
  cpu: { little: number | null; mid: number | null; prime: number | null; mid_cores: number; prime_core: boolean };
};
type Game = { custom: boolean; settings: Settings };

const info = callable<[], Info>("info");
const status = callable<[], Status>("status");
const installedGames = callable<[], InstalledGame[]>("installed_games");
const getGame = callable<[appid: number | null], Game>("get_game");
const setGame = callable<[appid: number | null, settings: Settings | null], Game>("set_game");
const setActive = callable<[appid: number | null], void>("set_active");
const setChargeLimit = callable<[limit: number], void>("set_charge_limit");
const setChargeSpeed = callable<[name: string], void>("set_charge_speed");
const setChargeCurrent = callable<[ua: number], void>("set_charge_current");

const FAN_MODES = [
  { data: "auto", label: "Automatic (built-in curve)" },
  { data: "curve", label: "Custom curve" },
  { data: "fixed", label: "Fixed speed" },
];
const CLUSTER_LABEL: Record<string, string> = { little: "Efficiency cores", mid: "Performance cores", prime: "Prime core" };
const small = { fontSize: "12px", lineHeight: "16px" };
const mhz = (khz: number | null | undefined) => (khz ? `${Math.round(khz / 1000)} MHz` : "off");

// Tell kettle-powerd which game runs, so its settings follow it
function syncActive(stopped?: number) {
  const a = runningAppId();
  setActive(a !== null && a !== stopped ? a : null).catch(() => {});
}

function Readout({ s }: { s: Status }) {
  const st = s.steam;
  const row = (label: string, value: string) => (
    <PanelSectionRow>
      <Field label={label} bottomSeparator="none">{value}</Field>
    </PanelSectionRow>
  );
  const cpu = Object.entries(s.cpu_khz).map(([, v]) => (v ? Math.round(v / 1000) : "–")).join(" / ");
  return (
    <PanelSection title="Now">
      {row("Power draw", s.power_w === null ? "–" : `${s.power_w.toFixed(1)} W${s.tdp_limiting ? " (limiting)" : ""}`)}
      {s.battery.capacity !== null && row("Battery", `${s.battery.capacity}%, ${(s.battery.status ?? "").toLowerCase()}`)}
      {row("Temperature", s.temp_c === null ? "–" : `${s.temp_c.toFixed(0)} °C`)}
      {s.fan_rpm !== null && row("Fan", `${s.fan_rpm} RPM (${s.fan_pct}%)`)}
      {row("CPU MHz", cpu)}
      {row("GPU", `${s.gpu_mhz} MHz${s.gpu_load !== null ? `, ${Math.round(s.gpu_load * 100)}% busy` : ""}`)}
      <PanelSectionRow>
        <div style={small}>
          From Steam's Performance panel: TDP limit {st.tdp}W, {st.profile} profile, GPU clock{" "}
          {st.gpu_level === "manual" ? `${st.gpu_clock} MHz` : "auto"}. Set those per game there.
        </div>
      </PanelSectionRow>
    </PanelSection>
  );
}

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

function GameSettings({ appid, name, inf, fanControl }: { appid: number | null; name: string; inf: Info; fanControl: boolean }) {
  const [g, setG] = useState<Game | null>(null);
  useEffect(() => {
    setG(null);
    getGame(appid).then(setG);
  }, [appid]);
  if (!g) return null;
  const s = g.settings;
  // a game without its own settings shows (and edits) the all-games ones
  const target = appid !== null && g.custom ? appid : null;
  const update = async (patch: { fan?: Partial<Settings["fan"]>; cpu?: Partial<Settings["cpu"]> }) => {
    const next = { fan: { ...s.fan, ...patch.fan }, cpu: { ...s.cpu, ...patch.cpu } };
    setG({ ...g, settings: next });
    setG(await setGame(target, next));
  };
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
          onClick={async () => setG(await setGame(target, target === null ? { fan: { mode: "auto", curve: inf.default_curve, fixed: 50 }, cpu: { little: null, mid: null, prime: null, mid_cores: midCount, prime_core: true } } : null))}
        >
          {target === null ? "Reset all-games settings" : `Reset ${name} to all-games settings`}
        </ButtonItem>
      </PanelSectionRow>
    </>
  );
}

const CUSTOM = "Custom";
const amps = (ua: number) => `${(ua / 1e6).toFixed(1)} A`;

function Battery({ s, inf }: { s: Status; inf: Info }) {
  const limit = s.steam.charge_limit ?? -1;
  const custom = inf.charge_custom;
  const speed = inf.charge_speeds.find((sp) => sp.name === s.charge_speed);
  const fastest = Math.max(...inf.charge_speeds.map((sp) => sp.ua));
  // the slider's own value while it moves: the 1 s status poll would pull it back
  const [ua, setUa] = useState(s.charge_custom_ua);
  useEffect(() => setUa(s.charge_custom_ua), [s.charge_custom_ua]);
  const [pct, setPct] = useState(limit < 0 ? 100 : limit);
  useEffect(() => setPct(limit < 0 ? 100 : limit), [limit]);
  const options = inf.charge_speeds.map((sp) => ({ data: sp.name, label: sp.name }));
  if (custom) options.push({ data: CUSTOM, label: "Custom" });
  const hint = s.charge_speed === CUSTOM ? "Set the most current that goes into the battery"
    : !speed ? "" : speed.ua >= fastest ? "As fast as the charger allows"
    : `At most ${amps(speed.ua)} into the battery: slower, and easier on it`;
  return (
    <PanelSection title="Battery">
      {inf.charge_limit && (
        <PanelSectionRow>
          <SliderField
            label="Charge limit"
            description={pct >= 100 ? "Charges to full" : s.charge_held
              ? "Holding here: the charger powers the device, the battery rests"
              : "Stops charging here, resumes 5% below"}
            value={pct}
            min={inf.charge_limit_min}
            max={100}
            step={5}
            showValue
            valueSuffix="%"
            onChange={(v) => {
              setPct(v);
              setChargeLimit(v >= 100 ? -1 : v);
            }}
          />
        </PanelSectionRow>
      )}
      {options.length > 0 && (
        <PanelSectionRow>
          <DropdownItem
            label="Charge speed"
            description={hint}
            rgOptions={options}
            selectedOption={s.charge_speed}
            onChange={(o) => setChargeSpeed(o.data)}
          />
        </PanelSectionRow>
      )}
      {custom && s.charge_speed === CUSTOM && (
        <PanelSectionRow>
          <SliderField
            label="Charge current"
            description={`Up to ${amps(custom.max)}, the charger's own speed. A weaker charger gives less.`}
            value={ua / 1e6}
            min={custom.min / 1e6}
            max={custom.max / 1e6}
            step={custom.step / 1e6}
            showValue
            valueSuffix=" A"
            onChange={(v) => {
              const n = Math.round(v * 1e6);
              setUa(n);
              setChargeCurrent(n);
            }}
          />
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

function Content() {
  const [inf, setInf] = useState<Info | null>(null);
  const [s, setS] = useState<Status | null>(null);
  const [error, setError] = useState(false);
  const [games, setGames] = useState<InstalledGame[] | null>(null);
  const [appid, pick] = useSelectedGame(games);
  useEffect(() => {
    info().then(setInf).catch(() => setError(true));
    installedGames().then(setGames);
    const poll = () => status().then(setS).catch(() => setError(true));
    poll();
    const timer = setInterval(poll, 1000);
    return () => clearInterval(timer);
  }, []);
  if (error)
    return (
      <PanelSection>
        <PanelSectionRow>
          <div style={small}>The power service (kettle-powerd) isn't running.</div>
        </PanelSectionRow>
      </PanelSection>
    );
  if (!inf || !s || !games) return null;

  return (
    <>
      {(inf.charge_limit || inf.charge_speeds.length > 0) && <Battery s={s} inf={inf} />}
      <Readout s={s} />
      <PanelSection title="Fan and CPU">
        <GamePicker games={games} appid={appid} onChange={pick} />
        <GameSettings key={appid ?? "all"} appid={appid} name={appid !== null ? gameName(games, appid) : ""} inf={inf}
          fanControl={s.steam.fan_control === 1} />
      </PanelSection>
    </>
  );
}

export default definePlugin(() => {
  syncActive();
  // Steam's sliders follow what the Performance app sets (steamSync.ts)
  let tdpMax: number | null = null;
  const stopSync = startSteamSync(async () => {
    tdpMax ??= (await info()).tdp[1];
    return { steam: (await status()).steam, tdpMax };
  });
  const lifetime = SteamClient.GameSessions.RegisterForAppLifetimeNotifications((n: { unAppID: number; bRunning: boolean }) => {
    if (n.bRunning) setActive(n.unAppID).catch(() => {});
    else setTimeout(() => syncActive(n.unAppID), 1000);
  });
  return {
    name: "Power",
    titleView: <div className={staticClasses.Title}>Power</div>,
    content: <Content />,
    icon: <FaBolt />,
    onDismount: () => {
      lifetime.unregister();
      stopSync();
    },
  };
});
