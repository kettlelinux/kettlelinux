import { ButtonItem, PanelSection, PanelSectionRow, SliderField, ToggleField, staticClasses } from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { FaLayerGroup } from "react-icons/fa";
import { editLaunchOptions, getLaunchOptions, hasUnset, withEnv, withUnset } from "../../shared/launchOptions";
import { GamePicker, InstalledGame, gameName, runningAppId, useSelectedGame } from "../../shared/GamePicker";

type Status = { layer: boolean; dll: string | null; lossless_installed: boolean; allow_fp16: boolean; enabled_games: number[] };
type Game = {
  enabled: boolean;
  multiplier: number;
  flow_scale: number;
  performance_mode: boolean;
  fifo: boolean;
  preserve_images: boolean;
  bypass_wsi: boolean;
};

const status = callable<[], Status>("status");
const installedGames = callable<[], InstalledGame[]>("installed_games");
const getGame = callable<[appid: number], Game>("get_game");
const setGame = callable<[appid: number, settings: Partial<Game>], Game>("set_game");
const resetGame = callable<[appid: number], Game>("reset_game");
const setFp16 = callable<[allow: boolean], void>("set_fp16");

// The session disables the lsfg-vk layer everywhere (environment.d); games that are on unset it
const OFF = "DISABLE_LSFGVK";
// lsfg-vk paces with FIFO; gamescope's WSI layer then shows a black screen or stutters
const WSI = "ENABLE_GAMESCOPE_WSI";
// Settings the layer only reads at game start (the others it reloads live)
const ON_RESTART: (keyof Game)[] = ["enabled", "fifo", "preserve_images", "bypass_wsi"];

// Launch options follow the stored settings: on -> `env -u DISABLE_LSFGVK` (+ WSI bypass)
const applyLaunchOptions = (appid: number, g: Game) =>
  editLaunchOptions(appid, (o) => withUnset(withEnv(o, WSI, g.enabled && g.bypass_wsi ? "0" : null), OFF, g.enabled));

function DllNotice({ s }: { s: Status }) {
  if (!s.layer) return <PanelSectionRow><div>lsfg-vk isn't installed on this system.</div></PanelSectionRow>;
  if (s.dll) return null;
  return (
    <PanelSectionRow>
      <div style={{ fontSize: "12px", lineHeight: "16px" }}>
        {s.lossless_installed
          ? "Lossless Scaling is installed, but not on the lsfg-vk branch. In Steam: Lossless Scaling › Properties › Betas › lsfg-vk."
          : "Frame generation needs Lossless Scaling (Steam). Install it with Proton, then switch it to the lsfg-vk beta branch in Properties › Betas."}
      </div>
    </PanelSectionRow>
  );
}

function GameSettings({ appid, name, onChanged }: { appid: number; name: string; onChanged: () => void }) {
  const [g, setG] = useState<Game | null>(null);

  useEffect(() => {
    setG(null);
    getGame(appid).then(async (g) => {
      setG(g);
      // launch options edited by hand (or from an older plugin version): make them match
      const o = await getLaunchOptions(appid);
      if (hasUnset(o, OFF) !== g.enabled) applyLaunchOptions(appid, g);
    });
  }, [appid]);
  if (!g) return null;

  const update = async (patch: Partial<Game>) => {
    setG({ ...g, ...patch });
    const next = await setGame(appid, patch);
    setG(next);
    if ("enabled" in patch || "bypass_wsi" in patch) await applyLaunchOptions(appid, next);
    if (runningAppId() === appid && ON_RESTART.some((k) => k in patch))
      toaster.toast({ title: "Frame Generation", body: `Restart ${name} to apply` });
    if ("enabled" in patch) onChanged();
  };

  return (
    <>
      <PanelSectionRow>
        <ToggleField label="Frame generation" checked={g.enabled} onChange={(enabled) => update({ enabled })} />
      </PanelSectionRow>
      <PanelSectionRow>
        <SliderField
          label="Multiplier"
          description="Frames shown per rendered frame. Cap the game at 1/N of the refresh rate."
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
          label="Performance mode"
          description="Lighter frame generation model; recommended on this GPU"
          checked={g.performance_mode}
          onChange={(performance_mode) => update({ performance_mode })}
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
            await applyLaunchOptions(appid, next);
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
      <PanelSection title="Lossless Scaling">
        <DllNotice s={s} />
        <GamePicker games={games} appid={appid} onChange={pick} />
        {appid !== null && <GameSettings key={appid} appid={appid} name={name} onChanged={refresh} />}
      </PanelSection>
      <PanelSection title="All games">
        <PanelSectionRow>
          <ToggleField
            label="FP16"
            description="Half-precision shaders (faster on Adreno). Applies on game start."
            checked={s.allow_fp16}
            onChange={async (v) => {
              await setFp16(v);
              refresh();
            }}
          />
        </PanelSectionRow>
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

export default definePlugin(() => ({
  name: "Frame Generation",
  titleView: <div className={staticClasses.Title}>Frame Generation</div>,
  content: <Content />,
  icon: <FaLayerGroup />,
}));
