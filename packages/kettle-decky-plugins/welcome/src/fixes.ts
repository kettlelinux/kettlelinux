// Game fixes: launch options a game needs to run on this hardware at all. Each is applied once,
// on the first plugin load that finds the game in the library (installed or not, since launch
// options belong to the app), and recorded by the backend so a user who removes it keeps it off.
import { callable } from "@decky/api";
import { editLaunchOptions, hasEnv, withEnv, withWrapper } from "../../shared/launchOptions";

type Fix = { id: string; appid: number; applied: (opts: string) => boolean; edit: (opts: string) => string };

declare const appStore: { GetAppOverviewByAppID(appid: number): object | null };

// Start the game's own exe in place of Steam's target, which Steam fills into %command%.
const skipTo = (from: string, to: string) => {
  const esc = from.replace(/\//g, "\\/");
  return `bash -c 'exec "\${@/${esc}/${to}}"' --`;
};

const FIXES: Fix[] = [
  {
    // DOOM Eternal's idTechLauncher checks the GPU before starting the game and only accepts
    // NVIDIA, AMD and Intel: on the Adreno it stops at "GPU Validation Failed". The game itself
    // runs; start DOOMEternalx64vk.exe directly (losing only the launcher's mod browser).
    id: "doom-eternal-skip-launcher",
    appid: 782330,
    applied: (opts) => opts.includes("DOOMEternalx64vk.exe"),
    edit: (opts) => withWrapper(opts, skipTo("launcher/idTechLauncher.exe", "DOOMEternalx64vk.exe")),
  },
  {
    // The Witcher 3 Remastered creates its D3D12 device at feature level 12_0. vkd3d-proton
    // reports only 11_x on Turnip (FL 12_0 needs tiled resources tier 2, and Turnip has no
    // sparseResidencyImage2D), so the game stops at "GPU does not meet minimal requirements.
    // Support for DirectX 12 is required." Forcing 12_0 lets it create the device.
    id: "witcher3-feature-level-12-0",
    appid: 292030,
    applied: (opts) => hasEnv(opts, "VKD3D_FEATURE_LEVEL"),
    edit: (opts) => withEnv(opts, "VKD3D_FEATURE_LEVEL", "12_0"),
  },
];

const appliedFixes = callable<[], string[]>("applied_fixes");
const markFixApplied = callable<[id: string], void>("mark_fix_applied");

function inLibrary(appid: number): boolean {
  try {
    return !!appStore.GetAppOverviewByAppID(appid);
  } catch {
    return false;
  }
}

export async function applyGameFixes() {
  const done = new Set(await appliedFixes());
  for (const f of FIXES) {
    if (done.has(f.id) || !inLibrary(f.appid)) continue;
    await editLaunchOptions(f.appid, (opts) => (f.applied(opts) ? opts : f.edit(opts)));
    await markFixApplied(f.id);
  }
}
