// Game fixes: launch options a game needs to run on this hardware at all. Welcome applies each
// once (welcome/src/fixes.ts); Game Settings shows the ones for the selected game and can take
// one off or put it back.
import { hasEnv, hasWrapper, withEnv, withWrapper, withoutWrapper } from "./launchOptions";

export type GameFix = {
  id: string;
  appid: number;
  title: string;
  description: string;
  applied: (opts: string) => boolean;
  edit: (opts: string) => string;
  undo: (opts: string) => string;
};

// Start the game's own exe in place of Steam's target, which Steam fills into %command%.
const skipTo = (from: string, to: string) => {
  const esc = from.replace(/\//g, "\\/");
  return `bash -c 'exec "\${@/${esc}/${to}}"' --`;
};

const doomSkip = skipTo("launcher/idTechLauncher.exe", "DOOMEternalx64vk.exe");

export const GAME_FIXES: GameFix[] = [
  {
    // DOOM Eternal's idTechLauncher checks the GPU before starting the game and only accepts
    // NVIDIA, AMD and Intel: on the Adreno it stops at "GPU Validation Failed". The game itself
    // runs; start DOOMEternalx64vk.exe directly (losing only the launcher's mod browser).
    id: "doom-eternal-skip-launcher",
    appid: 782330,
    title: "Skip idTechLauncher",
    description: "Starts the game directly: the launcher's GPU check refuses the Adreno. No mod browser.",
    applied: (opts) => opts.includes("DOOMEternalx64vk.exe"),
    edit: (opts) => withWrapper(opts, doomSkip),
    undo: (opts) => (hasWrapper(opts, doomSkip) ? withoutWrapper(opts, doomSkip) : opts),
  },
  {
    // The Witcher 3 Remastered creates its D3D12 device at feature level 12_0. vkd3d-proton
    // reports only 11_x on Turnip (FL 12_0 needs tiled resources tier 2, and Turnip has no
    // sparseResidencyImage2D), so the game stops at "GPU does not meet minimal requirements.
    // Support for DirectX 12 is required." Forcing 12_0 lets it create the device.
    id: "witcher3-feature-level-12-0",
    appid: 292030,
    title: "DirectX 12 feature level 12_0",
    description: "The game requires 12_0, which Turnip doesn't report; without it, it won't start in DirectX 12.",
    applied: (opts) => hasEnv(opts, "VKD3D_FEATURE_LEVEL"),
    edit: (opts) => withEnv(opts, "VKD3D_FEATURE_LEVEL", "12_0"),
    undo: (opts) => withEnv(opts, "VKD3D_FEATURE_LEVEL", null),
  },
];

export const fixesFor = (appid: number) => GAME_FIXES.filter((f) => f.appid === appid);
