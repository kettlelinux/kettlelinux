import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow, SliderField, ToggleField, staticClasses } from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { FaLayerGroup } from "react-icons/fa";
import { editLaunchOptions, withDxvkOption, withEnv, withEnvFlag, withUnset } from "../../shared/launchOptions";
import { GamePicker, InstalledGame, gameName, runningAppId, useSelectedGame } from "../../shared/GamePicker";

type Status = { layer: boolean; enabled_games: number[] };
type Game = {
  enabled: boolean;
  multiplier: number;
  flow_scale: number;
  fifo: boolean;
  preserve_images: boolean;
  bypass_wsi: boolean;
  fps_cap: string;
  // from the backend: automatic cap and what it's based on
  auto_cap: number;
  refresh: number;
  measure: Measure | null;
  live: Measure | null;
};
type Measure = { base: number; median: number; at_cap: number; cap: number | null; samples: number };

const status = callable<[], Status>("status");
const installedGames = callable<[], InstalledGame[]>("installed_games");
const getGame = callable<[appid: number], Game>("get_game");
const setGame = callable<[appid: number, settings: Partial<Game>], Game>("set_game");
const resetGame = callable<[appid: number], Game>("reset_game");

// The layer loads only with KETTLE_FG=1
const KETTLE = "KETTLE_FG";
// Generated frames are paced with FIFO; through gamescope's WSI layer that can show a black
// screen or stutter
const WSI = "ENABLE_GAMESCOPE_WSI";
// Launch options older versions wrote for the lsfg-vk engine (removed); cleared from games
// that still have them: `env -u DISABLE_LSFGVK`, TU_DEBUG=noubwc, KETTLE_LSFG_NOUBWC=1
const LSFG_OFF = "DISABLE_LSFGVK";
const TU = "TU_DEBUG";
const LSFG_NOUBWC = "KETTLE_LSFG_NOUBWC";
// The base frame rate has to be capped inside the game's renderer, before frame generation: Steam's
// limiter (gamescope) paces every presented frame, generated ones included, so it halves the
// real frame rate. DXVK (DX9-11) and vkd3d-proton (DX12) limit at present time instead.
const FPS_CAPS = [
  { data: "auto", label: "Auto (measured)" },
  { data: "off", label: "Off" },
  { data: "30", label: "30 fps" },
  { data: "40", label: "40 fps" },
  { data: "60", label: "60 fps" },
];
const baseCap = (g: Game): string | null =>
  g.fps_cap === "off" ? null : g.fps_cap === "auto" ? String(g.auto_cap) : g.fps_cap;

function capDescription(g: Game): string {
  const cap = baseCap(g);
  const m = g.live ?? g.measure;
  const seen = m ? `${g.live ? "running at" : "last ran at"} ~${Math.round(m.base)} fps` : "not measured yet";
  const shown = cap ? ` → ${Number(cap) * g.multiplier} fps shown` : "";
  if (g.fps_cap === "auto")
    return `${cap} fps${shown} (${seen}). Adjusts after each session; applies at launch.`;
  return `${cap ? `${cap} fps` : "No cap"}${shown} (${seen}). Leave Steam's frame limit off.`;
}
// Settings the layer only reads at game start (the others it reloads live)
const ON_RESTART: (keyof Game)[] = ["enabled", "fifo", "preserve_images", "bypass_wsi", "fps_cap"];
// Settings that live in the launch options
const IN_LAUNCH_OPTIONS: (keyof Game)[] = ["enabled", "bypass_wsi", "fps_cap", "multiplier"];

// Launch options follow the stored settings: on -> KETTLE_FG=1 (+ WSI bypass and the base
// frame cap)
const applyLaunchOptions = (appid: number, g: Game, s: Status) => {
  const on = g.enabled && s.layer;
  const cap = on ? baseCap(g) : null;
  return editLaunchOptions(appid, (o) => {
    o = withEnv(o, WSI, on && g.bypass_wsi ? "0" : null);
    o = withDxvkOption(withDxvkOption(o, "dxgi.maxFrameRate", cap), "d3d9.maxFrameRate", cap);
    o = withEnv(o, "VKD3D_FRAME_RATE", cap);
    o = withEnv(o, KETTLE, on ? "1" : null);
    o = withEnvFlag(o, TU, "noubwc", false);
    o = withEnv(o, LSFG_NOUBWC, null);
    return withUnset(o, LSFG_OFF, false);
  });
};

// Bring every game that's on in line with the stored settings (also clears what older
// versions wrote for lsfg-vk)
async function syncAll() {
  const s = await status();
  for (const appid of s.enabled_games) await applyLaunchOptions(appid, await getGame(appid), s);
}

function GameSettings({ appid, name, s, onChanged }: { appid: number; name: string; s: Status; onChanged: () => void }) {
  const [g, setG] = useState<Game | null>(null);

  useEffect(() => {
    setG(null);
    getGame(appid).then((g) => {
      setG(g);
      // launch options edited by hand (or from an older plugin version): make them match;
      // a no-op when they already do
      if (g.enabled) applyLaunchOptions(appid, g, s);
    });
  }, [appid]);
  if (!g) return null;
  const ok = s.layer;

  const update = async (patch: Partial<Game>) => {
    setG({ ...g, ...patch });
    const next = await setGame(appid, patch);
    setG(next);
    if (IN_LAUNCH_OPTIONS.some((k) => k in patch)) await applyLaunchOptions(appid, next, s);
    if (runningAppId() === appid && (ON_RESTART.some((k) => k in patch) || ("multiplier" in patch && next.fps_cap === "auto")))
      toaster.toast({ title: "Frame Generation", body: `Restart ${name} to apply` });
    if ("enabled" in patch) onChanged();
  };

  return (
    <>
      <PanelSectionRow>
        <ToggleField
          label="Frame generation"
          description={ok ? undefined : "The Kettle frame generation layer isn't installed"}
          checked={g.enabled && ok}
          disabled={!ok}
          onChange={(enabled) => update({ enabled })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <SliderField
          label="Multiplier"
          description="Frames shown per rendered frame. Above 2× needs a high base frame rate, or motion warps."
          value={g.multiplier}
          min={2}
          max={4}
          step={1}
          notchCount={3}
          notchLabels={[2, 3, 4].map((v, i) => ({ notchIndex: i, label: `${v}×`, value: v }))}
          notchTicksVisible
          onChange={(multiplier) => update({ multiplier })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem
          label="Base FPS cap"
          description={capDescription(g)}
          rgOptions={FPS_CAPS}
          selectedOption={g.fps_cap}
          onChange={(o) => update({ fps_cap: o.data })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <SliderField
          label="Flow scale"
          description="Motion estimation resolution: lower is faster, higher tracks motion better"
          value={Math.round(g.flow_scale * 100)}
          min={25}
          max={100}
          step={5}
          showValue
          valueSuffix="%"
          onChange={(v) => update({ flow_scale: v / 100 })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label="V-Sync pacing"
          description="Present generated frames with FIFO. Turn off only if the game stutters."
          checked={g.fifo}
          onChange={(fifo) => update({ fifo })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label="Keep swapchain image count"
          description="Don't add swapchain images for generated frames (less latency, may stutter)"
          checked={g.preserve_images}
          onChange={(preserve_images) => update({ preserve_images })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label="Bypass gamescope WSI"
          description="ENABLE_GAMESCOPE_WSI=0; fixes a black screen with frame generation"
          checked={g.bypass_wsi}
          onChange={(bypass_wsi) => update({ bypass_wsi })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={async () => {
            const next = await resetGame(appid);
            setG(next);
            await applyLaunchOptions(appid, next, s);
          }}
        >
          Reset {name} to defaults
        </ButtonItem>
      </PanelSectionRow>
    </>
  );
}

function Content() {
  const [s, setS] = useState<Status | null>(null);
  const [games, setGames] = useState<InstalledGame[] | null>(null);
  const [appid, pick] = useSelectedGame(games);
  const refresh = () => status().then(setS);
  useEffect(() => {
    refresh();
    installedGames().then(setGames);
  }, []);
  if (!s || !games) return null;

  const name = appid !== null ? gameName(games, appid) : "";
  return (
    <>
      <PanelSection title="Game">
        <GamePicker games={games} appid={appid} onChange={pick} />
        {appid !== null && <GameSettings key={appid} appid={appid} name={name} s={s} onChanged={refresh} />}
      </PanelSection>
      <PanelSection title="All games">
        {s.enabled_games.length > 0 && (
          <PanelSectionRow>
            <div style={{ fontSize: "12px", lineHeight: "16px" }}>
              On for: {s.enabled_games.map((a) => gameName(games, a)).join(", ")}
            </div>
          </PanelSectionRow>
        )}
      </PanelSection>
    </>
  );
}

export default definePlugin(() => {
  syncAll().catch(() => {});
  // after a game exits the backend stores its measurement (it samples every 2 s), which can
  // change the automatic cap: rewrite launch options for the next launch
  const lifetime = SteamClient.GameSessions.RegisterForAppLifetimeNotifications((n: { bRunning: boolean }) => {
    if (!n.bRunning) setTimeout(() => syncAll().catch(() => {}), 5000);
  });
  return {
    name: "Frame Generation",
    titleView: <div className={staticClasses.Title}>Frame Generation</div>,
    content: <Content />,
    icon: <FaLayerGroup />,
    onDismount: () => lifetime.unregister(),
  };
});
