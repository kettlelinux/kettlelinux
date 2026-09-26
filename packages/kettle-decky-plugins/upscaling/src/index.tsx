import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow, SliderField, ToggleField, staticClasses } from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { FaExpandArrowsAlt } from "react-icons/fa";
import { editLaunchOptions, getAppDetails, getFreshAppDetails, getPerfStore, withDllOverride } from "../../shared/launchOptions";
import { GamePicker, InstalledGame, gameName, runningAppId, useSelectedGame } from "../../shared/GamePicker";

const small = { fontSize: "12px", lineHeight: "16px" };


// gamescope FSR 1: the game renders at a lower resolution, gamescope upscales it with
// Steam's "Sharp" scaling filter. FSR 1 modes for the 1920x1080 panel (Steam accepts
// "Default", "Native" or "WxH").
const RESOLUTIONS = [
  { data: "Default", label: "Default (Steam setting)" },
  { data: "Native", label: "Native 1920×1080" },
  { data: "1600x900", label: "Ultra quality 1600×900" },
  { data: "1280x720", label: "Quality 1280×720" },
  { data: "1152x648", label: "Balanced 1152×648" },
  { data: "960x540", label: "Performance 960×540" },
];
// Steam's split scaling filter enum (Quick Access › Performance › Scaling filter)
const FILTERS = [
  { data: 1, label: "Linear" },
  { data: 2, label: "Nearest" },
  { data: 3, label: "FSR (Sharp)" },
];

function GamescopeFsr({ appid }: { appid: number }) {
  const [res, setRes] = useState(getAppDetails(appid)?.strResolutionOverride || "Default");
  useEffect(() => {
    getFreshAppDetails(appid).then((d) => d && setRes(d.strResolutionOverride || "Default"));
  }, [appid]);
  // Steam's filter and sharpness are per game, but only settable for the running one
  const running = runningAppId() === appid;
  const perf = running ? getPerfStore() : null;
  const [filter, setFilter] = useState<number>(perf?.msgSettingsPerApp?.split_scaling_filter || 1);
  const [sharp, setSharp] = useState<number>(perf?.msgSettingsPerApp?.fsr_sharpness ?? 2);

  return (
    <PanelSection title="FSR 1 (gamescope)">
      <PanelSectionRow>
        <DropdownItem
          label="Render resolution"
          description="The game renders at this size; gamescope upscales it. Applies on next launch."
          rgOptions={RESOLUTIONS}
          selectedOption={res}
          onChange={async (o) => {
            setRes(o.data);
            SteamClient.Apps.SetAppResolutionOverride(appid, o.data);
            // on the built-in screen Steam only honours the override with this flag set; it's a
            // toggle, so it has to be read fresh (the cached copy isn't updated by the toggle)
            if (o.data !== "Default" && o.data !== "Native" && !(await getFreshAppDetails(appid))?.bOverrideInternalResolution)
              SteamClient.Apps.ToggleOverrideResolutionForInternalDisplay(appid);
          }}
        />
      </PanelSectionRow>
      {perf ? (
        <>
          <PanelSectionRow>
            <DropdownItem
              label="Scaling filter"
              rgOptions={FILTERS}
              selectedOption={filter}
              onChange={(o) => {
                perf.SetSplitScalingFilter(o.data);
                setFilter(o.data);
              }}
            />
          </PanelSectionRow>
          {filter === 3 && (
            <PanelSectionRow>
              <SliderField
                label="FSR sharpness"
                description="0 is sharpest"
                value={sharp}
                min={0}
                max={8}
                step={1}
                showValue
                onChange={(v) => {
                  perf.SetFSRSharpness(v);
                  setSharp(v);
                }}
              />
            </PanelSectionRow>
          )}
        </>
      ) : (
        <PanelSectionRow>
          <div style={small}>
            {running
              ? 'Set the filter to "Sharp" in Quick Access › Performance.'
              : "Scaling filter and sharpness: start the game (Steam keeps them per game)."}
          </div>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

// ---------- OptiScaler (SGSR 2, Arm ASR, FSR 2.2): replaces the game's DLSS / FSR 2+ / XeSS ----------

type Settings = { upscaler: string; asr_quality: string; framegen: string; hudfix: boolean; sharpen: boolean; sharpness: number; ratio: string; spoof: boolean; menu_key: string };
type Status = { available: boolean; version: string | null; proxies: string[]; amd: boolean };
type Game = {
  found: boolean;
  on?: boolean;
  outdated?: boolean;
  dir?: string;
  candidates?: string[];
  proxy?: string;
  settings?: Settings;
};
const status = callable<[], Status>("status");
const installedGames = callable<[], InstalledGame[]>("installed_games");
const getGame = callable<[appid: number], Game>("get_game");
const enable = callable<[appid: number, exe_dir: string, proxy: string], Game>("enable");
const disable = callable<[appid: number], Game>("disable");
const configure = callable<[appid: number, settings: Partial<Settings>], Game>("configure");
const reset = callable<[appid: number], Game>("reset");

const UPSCALERS = [
  { data: "sgsr2", label: "SGSR 2 (Snapdragon)" },
  { data: "asr", label: "Arm ASR" },
  { data: "fsr22", label: "FSR 2.2" },
];
// with AMD's DLLs (Welcome panel › AMD FSR 3.1)
const AMD_UPSCALERS = [{ data: "fsr31", label: "FSR 3.1 (AMD)" }];
const FRAMEGEN = [
  { data: "off", label: "Off" },
  { data: "upscaler", label: "FSR FG from the upscaler" },
  { data: "game", label: "Game's own FSR 3 FG" },
];
const ASR_QUALITY = [
  { data: "balanced", label: "Balanced" },
  { data: "quality", label: "Quality (slower)" },
];
const RATIOS = [
  { data: "game", label: "Game's quality setting" },
  { data: "1.3", label: "1.3× (ultra quality)" },
  { data: "1.5", label: "1.5× (quality)" },
  { data: "1.7", label: "1.7× (balanced)" },
  { data: "2.0", label: "2.0× (performance)" },
  { data: "3.0", label: "3.0× (ultra performance)" },
];
const MENU_KEYS = [
  { data: "0x2D", label: "Insert" },
  { data: "0x24", label: "Home" },
  { data: "0x7B", label: "F12" },
  { data: "0x71", label: "F2" },
];

const dllName = (proxy: string) => proxy.replace(/\.dll$/, "");
const short = (d: string) => d.split("/steamapps/common/")[1] ?? d;

function Sgsr({ appid, name, s }: { appid: number; name: string; s: Status }) {
  const [g, setG] = useState<Game | null>(null);
  const [dir, setDir] = useState("");
  const [proxy, setProxy] = useState("dxgi.dll");
  const [busy, setBusy] = useState(false);

  const show = (g: Game) => {
    setG(g);
    setDir(g.dir ?? g.candidates?.[0] ?? "");
    setProxy(g.proxy ?? "dxgi.dll");
  };
  useEffect(() => {
    setG(null);
    getGame(appid).then(show);
  }, [appid]);

  if (!s.available)
    return <PanelSection title="OptiScaler"><PanelSectionRow><div>OptiScaler isn't installed on this system.</div></PanelSectionRow></PanelSection>;
  if (!g) return null;
  if (!g.found)
    return <PanelSection title="OptiScaler"><PanelSectionRow><div>{name} isn't installed.</div></PanelSectionRow></PanelSection>;

  const run = async (f: () => Promise<Game>, msg?: string) => {
    setBusy(true);
    try {
      show(await f());
      if (msg) toaster.toast({ title: "OptiScaler", body: msg });
    } catch (e) {
      toaster.toast({ title: "OptiScaler", body: String(e) });
    } finally {
      setBusy(false);
    }
  };
  const restartNote = () => (runningAppId() === appid ? ` Restart ${name} to apply.` : "");
  const st = g.settings!;
  // FSR 3.1 and frame generation need AMD's DLLs; a game already using them keeps its choice
  const amd = s.amd || st.upscaler === "fsr31" || st.framegen !== "off";
  const set = (patch: Partial<Settings>) => run(() => configure(appid, patch), g.on ? restartNote().trim() || undefined : undefined);

  // On: OptiScaler is copied into the game folder and loaded through a DLL override in the
  // game's launch options. Off: both are removed, so nothing of it is left in the game.
  const toggle = (on: boolean) =>
    run(async () => {
      if (on) {
        const r = await enable(appid, dir, proxy);
        await editLaunchOptions(appid, (o) => withDllOverride(o, dllName(proxy), "n,b"));
        return r;
      }
      const was = g.proxy ?? "dxgi.dll";
      const r = await disable(appid);
      await editLaunchOptions(appid, (o) => withDllOverride(o, dllName(was), null));
      return r;
    }, (on ? "On." : "Off.") + restartNote());

  return (
    <PanelSection title="Temporal upscaling (OptiScaler)">
      <PanelSectionRow>
        <div style={small}>
          For DX11/DX12 games with DLSS, FSR 2+ or XeSS: pick that upscaler in the game's settings and
          the one chosen here runs in its place. Keep the render resolution above at
          Default. Vulkan games are untested.
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label="OptiScaler"
          description={g.on ? short(g.dir ?? "") : undefined}
          checked={!!g.on}
          disabled={busy || (!g.on && !dir)}
          onChange={toggle}
        />
      </PanelSectionRow>
      {!g.on && (
        <>
          <PanelSectionRow>
            <DropdownItem
              label="Game folder"
              description="Where the game's exe is"
              rgOptions={(g.candidates ?? []).map((d) => ({ data: d, label: short(d) }))}
              selectedOption={dir}
              onChange={(o) => setDir(o.data)}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <DropdownItem
              label="Load as"
              description="Try another name if the game crashes or OptiScaler doesn't appear"
              rgOptions={s.proxies.map((p) => ({ data: p, label: p }))}
              selectedOption={proxy}
              onChange={(o) => setProxy(o.data)}
            />
          </PanelSectionRow>
        </>
      )}

      <PanelSectionRow>
        <DropdownItem label="Upscaler" description="Vulkan games always use SGSR 2"
          rgOptions={amd ? [...UPSCALERS, ...AMD_UPSCALERS] : UPSCALERS} selectedOption={st.upscaler} disabled={busy}
          onChange={(o) => set({ upscaler: o.data })} />
      </PanelSectionRow>
      {st.upscaler === "asr" && (
        <PanelSectionRow>
          <DropdownItem label="ASR preset" rgOptions={ASR_QUALITY} selectedOption={st.asr_quality} disabled={busy}
            onChange={(o) => set({ asr_quality: o.data })} />
        </PanelSectionRow>
      )}
      {amd ? (
        <>
          <PanelSectionRow>
            <DropdownItem label="Frame generation" description="DX12 games; heavy on this GPU (choppy in Deep Rock Galactic), the Frame Generation plugin is usually better. Don't combine the two."
              rgOptions={FRAMEGEN} selectedOption={st.framegen} disabled={busy} onChange={(o) => set({ framegen: o.data })} />
          </PanelSectionRow>
          {st.framegen === "upscaler" && (
            <PanelSectionRow>
              <ToggleField label="HUD fix" description="Keeps the HUD from ghosting in generated frames; may crash some games"
                checked={st.hudfix} disabled={busy} onChange={(hudfix) => set({ hudfix })} />
            </PanelSectionRow>
          )}
        </>
      ) : (
        <PanelSectionRow>
          <div style={small}>FSR 3.1 and frame generation: install AMD FSR 3.1 in the Welcome panel.</div>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <DropdownItem label="Render scale" description="Force a ratio instead of the game's DLSS/FSR quality mode"
          rgOptions={RATIOS} selectedOption={st.ratio} disabled={busy} onChange={(o) => set({ ratio: o.data })} />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField label="Sharpening (RCAS)" description="RCAS after the upscaler"
          checked={st.sharpen} disabled={busy} onChange={(sharpen) => set({ sharpen })} />
      </PanelSectionRow>
      {st.sharpen && (
        <PanelSectionRow>
          <SliderField label="Sharpness" value={Math.round(st.sharpness * 100)} min={0} max={130} step={5} showValue
            valueSuffix="%" disabled={busy} onChange={(v) => set({ sharpness: v / 100 })} />
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ToggleField label="Report GPU as NVIDIA" description="Makes games offer DLSS, which OptiScaler then replaces"
          checked={st.spoof} disabled={busy} onChange={(spoof) => set({ spoof })} />
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem label="Overlay key" description="Opens OptiScaler's in-game menu; map it to a button in Steam Input"
          rgOptions={MENU_KEYS} selectedOption={st.menu_key} disabled={busy} onChange={(o) => set({ menu_key: o.data })} />
      </PanelSectionRow>

      {g.on && g.outdated && (
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy}
            onClick={() => run(() => enable(appid, g.dir!, g.proxy ?? "dxgi.dll"), `Updated.${restartNote()}`)}>
            Update to OptiScaler {s.version}
          </ButtonItem>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} onClick={() => run(() => reset(appid), "Settings reset.")}>
          Reset settings
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}

function Content() {
  const [s, setS] = useState<Status | null>(null);
  const [games, setGames] = useState<InstalledGame[] | null>(null);
  const [appid, pick] = useSelectedGame(games);
  useEffect(() => {
    status().then(setS);
    installedGames().then(setGames);
  }, []);
  if (!s || !games) return null;

  return (
    <>
      <PanelSection>
        <GamePicker games={games} appid={appid} onChange={pick} />
      </PanelSection>
      {appid !== null && (
        <>
          <GamescopeFsr key={`fsr-${appid}`} appid={appid} />
          <Sgsr key={`sgsr-${appid}`} appid={appid} name={gameName(games, appid)} s={s} />
        </>
      )}
    </>
  );
}

export default definePlugin(() => ({
  name: "Upscaling",
  titleView: <div className={staticClasses.Title}>Upscaling</div>,
  content: <Content />,
  icon: <FaExpandArrowsAlt />,
}));
