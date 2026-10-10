import { ButtonItem, DropdownItem, Field, Focusable, Navigation, PanelSection, PanelSectionRow, SidebarNavigation, SliderField, ToggleField, staticClasses } from "@decky/ui";
import { callable, definePlugin, routerHook, toaster } from "@decky/api";
import { ReactElement, useEffect, useMemo, useState } from "react";
import { FaBatteryHalf, FaBolt, FaCog, FaDesktop, FaLightbulb, FaTabletAlt, FaTools, FaHdd, FaInfoCircle, FaMemory, FaMicrochip, FaTachometerAlt, FaThermometerHalf, FaWifi, FaCube } from "react-icons/fa";
import { runningAppId } from "../../shared/GamePicker";
import { MdScreenRotation } from "react-icons/md";
import { Tab, Tabs } from "../../shared/Tabs";
import { startSteamSync } from "./steamSync";
import { LightsTab } from "./lights";
import { GyroTab } from "./gyro";
import { ScreensTab } from "./screens";
import { SystemTab } from "./system";

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
  // target: the frame rate it holds (Steam's limit, else the refresh rate); fps: the game's now
  auto_tdp: { on: boolean; target: number | null; fps_limit: number; fps: number | null; limiting: boolean };
  steam: Steam;
  battery: { status: string | null; capacity: number | null };
  charge_speed: string;
  charge_custom_ua: number;
  charge_held: boolean;
  sleep_fan: number;
};
type Refresh = { rates: number[]; hz: number };
type DiagSection = { title: string; rows: [string, string][] };

const info = callable<[], Info>("info");
const status = callable<[], Status>("status");
const diagnostics = callable<[], DiagSection[]>("diagnostics");
type Has = { lights: boolean; gyro: boolean; screens: boolean };
const deviceTabs = callable<[], Has>("tabs");
const setActive = callable<[appid: number | null], void>("set_active");
const setChargeLimit = callable<[limit: number], void>("set_charge_limit");
const setChargeSpeed = callable<[name: string], void>("set_charge_speed");
const setChargeCurrent = callable<[ua: number], void>("set_charge_current");
const setSleepFan = callable<[pct: number], void>("set_sleep_fan");
const getRefresh = callable<[], Refresh>("get_refresh");
const setRefresh = callable<[hz: number], Refresh>("set_refresh");
const small = { fontSize: "12px", lineHeight: "16px" };
// Tell kettle-powerd and kettle-motiond which game runs: its settings follow it, the gyro streams
function syncActive(stopped?: number) {
  const a = runningAppId();
  setActive(a !== null && a !== stopped ? a : null).catch(() => {});
}

// The power readout's rows: the Diagnostics window's Now tab, polled every second
function liveRows(s: Status): [string, string][] {
  const st = s.steam;
  const cpu = Object.values(s.cpu_khz).map((v) => (v ? Math.round(v / 1000) : "–")).join(" / ");
  const rows: [string, string | false][] = [
    ["Power draw", s.power_w === null ? "–" : `${s.power_w.toFixed(1)} W${s.tdp_limiting ? " (limiting)" : ""}`],
    ["Battery", s.battery.capacity !== null && `${s.battery.capacity}%, ${(s.battery.status ?? "").toLowerCase()}`],
    ["Temperature", s.temp_c === null ? "–" : `${s.temp_c.toFixed(0)} °C`],
    ["Fan", s.fan_rpm !== null && `${s.fan_rpm} RPM (${s.fan_pct}%)`],
    ["CPU MHz", cpu],
    ["GPU", `${s.gpu_mhz} MHz${s.gpu_load !== null ? `, ${Math.round(s.gpu_load * 100)}% busy` : ""}`],
    ["Auto TDP", s.auto_tdp.on && autoTdpText(s.auto_tdp)],
    ["Steam TDP limit", `${st.tdp} W`],
    ["Steam profile", st.profile],
    ["Steam GPU clock", st.gpu_level === "manual" ? `${st.gpu_clock} MHz` : "auto"],
  ];
  return rows.filter((r): r is [string, string] => r[1] !== false);
}

const DIAG_REFRESH = 5000; // ms: the device tabs (temperatures, Wi-Fi) change slower than the readout
const ROUTE = "/kettle-device-settings/diagnostics";
const DIAG_ICONS: Record<string, ReactElement> = {
  Device: <FaInfoCircle />, Software: <FaCube />, CPU: <FaMicrochip />, Memory: <FaMemory />, Storage: <FaHdd />,
  Battery: <FaBatteryHalf />, Display: <FaDesktop />, Network: <FaWifi />, Temperatures: <FaThermometerHalf />,
};

// The sidebar's title (the tab list column's first child) shrinks to make room for a long tab
// list, and it's overflow: hidden, which clips the descender of "Diagnostics"
const TITLE_FIX = ".kettle-diagnostics .PageListColumn > :first-child { flex-shrink: 0; }";

function openDiagnostics() {
  Navigation.CloseSideMenus();
  Navigation.Navigate(`${ROUTE}/now`);
}

// A tab's rows; each one focusable, so the D-pad scrolls a long tab
function Rows({ rows }: { rows: [string, string][] | null }) {
  if (!rows) return <div>Loading…</div>;
  return (
    <Focusable style={{ maxWidth: "720px" }}>
      {rows.map(([k, v]) => (
        <Field key={k} label={k} focusable bottomSeparator="standard">
          <span style={{ wordBreak: "break-word" }}>{v}</span>
        </Field>
      ))}
    </Focusable>
  );
}

// Only the shown tab is mounted, so each polls for itself while it's shown
function usePolled<T>(get: () => Promise<T>, ms: number): T | null {
  const [v, setV] = useState<T | null>(null);
  useEffect(() => {
    let live = true;
    const tick = () => get().then((r) => live && setV(r)).catch(() => {});
    tick();
    const t = setInterval(tick, ms);
    return () => {
      live = false;
      clearInterval(t);
    };
  }, []);
  return v;
}

function NowTab() {
  const s = usePolled(status, 1000);
  return <Rows rows={s && liveRows(s)} />;
}

function DiagTab({ title }: { title: string }) {
  const d = usePolled(diagnostics, DIAG_REFRESH);
  return <Rows rows={d && (d.find((sec) => sec.title === title)?.rows ?? [])} />;
}

// The Diagnostics window: the live readout, then everything about the device, a tab each
// (SidebarNavigation reports each tab as a route under ROUTE, as the Welcome window does)
function DiagnosticsPage() {
  const [titles, setTitles] = useState<string[] | null>(null);
  useEffect(() => {
    diagnostics().then((d) => setTitles(d.map((sec) => sec.title))).catch(() => setTitles([]));
  }, []);
  const pages = useMemo(
    () => [
      { title: "Now", route: `${ROUTE}/now`, icon: <FaTachometerAlt />, content: <NowTab /> },
      ...(titles ?? []).map((t) => ({
        title: t,
        route: `${ROUTE}/${t.toLowerCase()}`,
        icon: DIAG_ICONS[t] ?? <FaInfoCircle />,
        content: <DiagTab title={t} />,
      })),
    ],
    [titles],
  );
  if (!titles) return null;
  return (
    <div className="kettle-diagnostics" style={{ marginTop: "40px", height: "calc(100% - 40px)" }}>
      <style>{TITLE_FIX}</style>
      <SidebarNavigation title="Diagnostics" showTitle pages={pages} />
    </div>
  );
}

function autoTdpText(a: Status["auto_tdp"]) {
  if (a.target === null || a.fps === null) return "Waiting for the game";
  return `${Math.round(a.fps)} of ${a.target} fps${a.limiting ? ", clocks lowered" : ""}`;
}

const CUSTOM = "Custom";
const SLEEP_FAN_ON = 30; // the speed when it's switched on, percent
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
  const [fan, setFan] = useState(s.sleep_fan);
  useEffect(() => setFan(s.sleep_fan), [s.sleep_fan]);
  const sleepFan = (v: number) => {
    setFan(v);
    setSleepFan(v);
  };
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
      {inf.sleep_fan && (
        <PanelSectionRow>
          <ToggleField
            label="Fan while charging asleep"
            description="Keeps the fan running while the device sleeps on its charger, to carry the charging heat away"
            checked={fan > 0}
            onChange={(on) => sleepFan(on ? SLEEP_FAN_ON : 0)}
          />
        </PanelSectionRow>
      )}
      {inf.sleep_fan && fan > 0 && (
        <PanelSectionRow>
          <SliderField label="Fan speed asleep" value={fan} min={10} max={100} step={5} showValue valueSuffix="%"
            onChange={sleepFan} />
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

// The panel's refresh rate: Auto (0, Steam's frame limit picks it) or one held whatever the game
// or Steam asks for
function Screen({ r, onChange }: { r: Refresh; onChange: (r: Refresh) => void }) {
  const pick = async (hz: number) => {
    onChange({ ...r, hz });
    try {
      onChange(await setRefresh(hz));
    } catch (e) {
      onChange(r);
      toaster.toast({ title: "Device Settings", body: `The refresh rate wasn't set: ${e}` });
    }
  };
  return (
    <PanelSection title="Screen">
      <PanelSectionRow>
        <DropdownItem
          label="Refresh rate"
          description={(r.hz === 0
            ? "Steam's frame limit picks it: each limit runs at a rate it divides evenly"
            : "Holds in games and the Steam UI alike. Lower rates use less power") +
            ". A game can have its own, in Game Settings › Perf"}
          rgOptions={[{ data: 0, label: "Auto" }, ...r.rates.map((hz) => ({ data: hz, label: `${hz} Hz` }))]}
          selectedOption={r.hz}
          onChange={(o) => pick(o.data)}
        />
      </PanelSectionRow>
    </PanelSection>
  );
}

// The Power tab: the battery and the screen
function PowerTab() {
  const [inf, setInf] = useState<Info | null>(null);
  const [s, setS] = useState<Status | null>(null);
  const [error, setError] = useState(false);
  const [refresh, setRefreshState] = useState<Refresh | null>(null);
  useEffect(() => {
    getRefresh().then(setRefreshState).catch(() => {});
    info().then(setInf).catch(() => setError(true));
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
  if (!inf || !s) return null;
  return (
    <>
      {(inf.charge_limit || inf.charge_speeds.length > 0 || inf.sleep_fan) && <Battery s={s} inf={inf} />}
      {refresh && refresh.rates.length >= 2 && <Screen r={refresh} onChange={setRefreshState} />}
    </>
  );
}

const ALL_TABS: Tab[] = [
  { id: "power", label: "Power", icon: <FaBolt /> },
  { id: "lights", label: "Lights", icon: <FaLightbulb /> },
  { id: "gyro", label: "Gyro", icon: <MdScreenRotation /> },
  { id: "screens", label: "Screens", icon: <FaTabletAlt /> },
  { id: "system", label: "System", icon: <FaTools /> },
];
let lastTab = ALL_TABS[0].id; // kept while the panel is closed
let has: Has | null = null; // asked once

function Content() {
  const [have, setHave] = useState(has);
  const [tab, setTab] = useState(lastTab);
  useEffect(() => {
    if (!has) deviceTabs().then((h) => setHave((has = h))).catch(() => setHave({ lights: false, gyro: false, screens: false }));
  }, []);
  if (!have) return null;
  const tabs = ALL_TABS.filter((t) => t.id === "power" || t.id === "system" || have[t.id as keyof Has]);
  const shown = tabs.some((t) => t.id === tab) ? tab : "power";
  return (
    <>
      <PanelSection>
        <Tabs tabs={tabs} tab={shown} onChange={(t) => setTab((lastTab = t))} />
      </PanelSection>
      {shown === "power" && <PowerTab />}
      {shown === "lights" && <LightsTab />}
      {shown === "gyro" && <GyroTab />}
      {shown === "screens" && <ScreensTab />}
      {shown === "system" && <SystemTab />}
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={openDiagnostics}>
            Diagnostics
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

export default definePlugin(() => {
  routerHook.addRoute(ROUTE, DiagnosticsPage);
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
    name: "Device Settings",
    titleView: <div className={staticClasses.Title}>Device Settings</div>,
    content: <Content />,
    icon: <FaCog />,
    onDismount: () => {
      lifetime.unregister();
      stopSync();
      routerHook.removeRoute(ROUTE);
    },
  };
});
