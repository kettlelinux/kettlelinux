// The Frame Gen tab: per-game settings for Kettle's frame generation layer (framegen.py in the
// backend), which loads with KETTLE_FG=1 in the game's launch options
import { ButtonItem, DropdownItem, PanelSectionRow, SliderField, ToggleField } from "@decky/ui";
import { callable, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { editLaunchOptions, hasEnv, withDxvkOption, withEnv, withEnvFlag, withUnset } from "../../shared/launchOptions";
import { InstalledGame, gameName, runningAppId } from "../../shared/GamePicker";

type Status = { layer: boolean; enabled_games: number[] };
type Game = {
  enabled: boolean;
  multiplier: number | "auto";
  flow_scale: number;
  fifo: boolean;
  preserve_images: boolean;
  low_latency: boolean;
  bypass_wsi: boolean;
  fps_cap: string;
  // from the backend: automatic cap and what it's based on
  auto_cap: number | null; // null with multiplier auto: the layer paces the game itself
  refresh: number;
  measure: Measure | null;
  live: Measure | null;
};
type Measure = { base: number; median: number; at_cap: number; cap: number | null; samples: number };

const status = callable<[], Status>("fg_status");
const getGame = callable<[appid: number], Game>("fg_get_game");
const setGame = callable<[appid: number, settings: Partial<Game>], Game>("fg_set_game");
const resetGame = callable<[appid: number], Game>("fg_reset_game");

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
const MULTIPLIERS = [
  { data: "auto", label: "Auto" },
  { data: 2, label: "2×" },
  { data: 3, label: "3×" },
];
const baseCap = (g: Game): string | null =>
  g.fps_cap === "off" ? null : g.fps_cap === "auto" ? (g.auto_cap ? String(g.auto_cap) : null) : g.fps_cap;

function capDescription(g: Game): string {
  const cap = baseCap(g);
  if (g.multiplier === "auto") {
    if (g.fps_cap === "auto") return `No cap: the layer holds the game at what fills the ${g.refresh} Hz display.`;
    return `${cap ? `${cap} fps` : "No cap"}. Leave Steam's frame limit off.`;
  }
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
    // off, and no KETTLE_FG=1 left behind: a frame cap or WSI setting there is the player's own
    if (!on && !hasEnv(o, KETTLE)) return o;
    o = withEnv(o, WSI, on && g.bypass_wsi ? "0" : null);
    o = withDxvkOption(withDxvkOption(o, "dxgi.maxFrameRate", cap), "d3d9.maxFrameRate", cap);
    o = withEnv(o, "VKD3D_FRAME_RATE", cap);
    o = withEnv(o, KETTLE, on ? "1" : null);
    // only lsfg-vk's own noubwc: Game Settings can set TU_DEBUG=noubwc too
    if (hasEnv(o, LSFG_NOUBWC)) o = withEnvFlag(o, TU, "noubwc", false);
    o = withEnv(o, LSFG_NOUBWC, null);
    return withUnset(o, LSFG_OFF, false);
  });
};

// Bring every game that's on in line with the stored settings (also clears what older
// versions wrote for lsfg-vk)
export async function syncFrameGen() {
  const s = await status();
  for (const appid of s.enabled_games) await applyLaunchOptions(appid, await getGame(appid), s);
}

function FrameGenSettings({ appid, name, s, onChanged }: { appid: number; name: string; s: Status; onChanged: () => void }) {
  const [g, setG] = useState<Game | null>(null);

  useEffect(() => {
    setG(null);
    getGame(appid)
      .then((g) => {
        setG(g);
        // launch options edited by hand (or from an older plugin version, or Frame Gen turned off
        // while they couldn't be edited): make them match; a no-op when they already do
        return applyLaunchOptions(appid, g, s);
      })
      .catch((e) => toaster.toast({ title: "Game Settings", body: `Couldn't load Frame Gen for ${name}: ${e}` }));
  }, [appid]);
  if (!g) return null;
  const ok = s.layer;

  const update = async (patch: Partial<Game>) => {
    const before = g;
    setG({ ...g, ...patch });
    let next: Game;
    try {
      next = await setGame(appid, patch);
    } catch (e) {
      setG(before); // not stored: show what is
      toaster.toast({ title: "Game Settings", body: `Couldn't change Frame Gen for ${name}: ${e}` });
      return;
    }
    setG(next);
    if (IN_LAUNCH_OPTIONS.some((k) => k in patch)) await applyLaunchOptions(appid, next, s);
    if (runningAppId() === appid && (ON_RESTART.some((k) => k in patch) || ("multiplier" in patch && next.fps_cap === "auto")))
      toaster.toast({ title: "Game Settings", body: `Restart ${name} to apply` });
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
        <DropdownItem
          label="Multiplier"
          description={
            g.multiplier === "auto"
              ? "The fewest frames per rendered frame that fill every refresh, up to 3×"
              : "Frames shown per rendered frame. 3× needs a high base frame rate, or motion warps."
          }
          rgOptions={MULTIPLIERS}
          selectedOption={g.multiplier}
          onChange={(o) => update({ multiplier: o.data })}
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
          label="Low latency"
          description="Hold the game until its previous frame is on screen. Less input lag, may lower the frame rate."
          checked={g.low_latency}
          onChange={(low_latency) => update({ low_latency })}
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

// A game's settings; with "All games" picked, the games it's on for
export function FrameGenTab({ appid, name, games }: { appid: number | null; name: string; games: InstalledGame[] }) {
  const [s, setS] = useState<Status | null>(null);
  const refresh = () => status().then(setS);
  useEffect(() => {
    refresh();
  }, []);
  if (!s) return null;
  if (appid !== null) return <FrameGenSettings key={appid} appid={appid} name={name} s={s} onChanged={refresh} />;
  return (
    <PanelSectionRow>
      <div style={{ fontSize: "12px", lineHeight: "16px" }}>
        Frame generation is set per game: pick one above.
        {s.enabled_games.length > 0 && ` On for: ${s.enabled_games.map((a) => gameName(games, a)).join(", ")}.`}
      </div>
    </PanelSectionRow>
  );
}
