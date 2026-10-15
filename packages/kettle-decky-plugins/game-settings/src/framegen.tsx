// The Frame Gen tab: per-game settings for Kettle's frame generation layer (framegen.py in the
// backend), which loads with KETTLE_FG=1 in the game's launch options. Always 2x: the game's base
// frame rate is half the refresh rate held while it runs, which changes live.
import { ButtonItem, DropdownItem, PanelSectionRow, SliderField, ToggleField } from "@decky/ui";
import { callable, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { editLaunchOptions, hasEnv, withDxvkOption, withEnv, withEnvFlag, withUnset } from "../../shared/launchOptions";
import { InstalledGame, gameName, runningAppId } from "../../shared/GamePicker";

type Status = { layer: boolean; enabled_games: number[] };
type Game = {
  enabled: boolean;
  flow_scale: number;
  preserve_images: boolean;
  bypass_wsi: boolean;
  refresh: number; // Hz held while the game runs
  rates: number[]; // from the backend: the rates the panel has for it
};

const status = callable<[], Status>("fg_status");
const getGame = callable<[appid: number], Game>("fg_get_game");
const setGame = callable<[appid: number, settings: Partial<Game>, running: boolean], Game>("fg_set_game");
const resetGame = callable<[appid: number, running: boolean], Game>("fg_reset_game");

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
// Settings the layer only reads at game start (the others apply live)
const ON_RESTART: (keyof Game)[] = ["preserve_images", "bypass_wsi"];
// Settings that live in the launch options
const IN_LAUNCH_OPTIONS: (keyof Game)[] = ["enabled", "bypass_wsi"];

// Launch options follow the stored settings: on -> KETTLE_FG=1 (+ WSI bypass). Older versions
// capped the base frame rate in DXVK (DX9-11) and vkd3d-proton (DX12); the held refresh rate does
// that now, for Vulkan games too, so those caps are cleared from games Frame Gen is or was on for.
const applyLaunchOptions = (appid: number, g: Game, s: Status) => {
  const on = g.enabled && s.layer;
  return editLaunchOptions(appid, (o) => {
    // off, and no KETTLE_FG=1 left behind: a frame cap or WSI setting there is the player's own
    if (!on && !hasEnv(o, KETTLE)) return o;
    o = withEnv(o, WSI, on && g.bypass_wsi ? "0" : null);
    o = withDxvkOption(withDxvkOption(o, "dxgi.maxFrameRate", null), "d3d9.maxFrameRate", null);
    o = withEnv(o, "VKD3D_FRAME_RATE", null);
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
    const running = runningAppId() === appid;
    let next: Game;
    try {
      next = await setGame(appid, patch, running);
    } catch (e) {
      setG(before); // not stored: show what is
      toaster.toast({ title: "Game Settings", body: `Couldn't change Frame Gen for ${name}: ${e}` });
      return;
    }
    setG(next);
    if (IN_LAUNCH_OPTIONS.some((k) => k in patch)) await applyLaunchOptions(appid, next, s);
    if (running && ON_RESTART.some((k) => k in patch))
      toaster.toast({ title: "Game Settings", body: `Restart ${name} to apply` });
    // the layer loads at launch: off and back on again applies live, but not for the first time
    else if (running && patch.enabled)
      toaster.toast({ title: "Game Settings", body: `If ${name} started without Frame Gen, restart it to apply` });
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
          label="Base FPS"
          description={`The screen runs at ${g.refresh} Hz while ${name} runs, ${g.refresh} fps shown. Leave Steam's frame limit off.`}
          rgOptions={g.rates.map((hz) => ({ data: hz, label: `${Math.floor(hz / 2)} fps` }))}
          selectedOption={g.refresh}
          onChange={(o) => update({ refresh: o.data })}
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
            const next = await resetGame(appid, runningAppId() === appid);
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
