// Game fixes (shared/gameFixes.ts): launch options a game needs to run on this hardware at all.
// Each is applied once, on the first plugin load that finds the game in the library (installed
// or not, since launch options belong to the app), and recorded by the backend so a user who
// removes it (by hand or in Game Settings) keeps it off.
import { callable } from "@decky/api";
import { editLaunchOptions } from "../../shared/launchOptions";
import { GAME_FIXES } from "../../shared/gameFixes";

declare const appStore: { GetAppOverviewByAppID(appid: number): object | null };

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
  for (const f of GAME_FIXES) {
    if (done.has(f.id) || !inLibrary(f.appid)) continue;
    await editLaunchOptions(f.appid, (opts) => (f.applied(opts) ? opts : f.edit(opts)));
    await markFixApplied(f.id);
  }
}
