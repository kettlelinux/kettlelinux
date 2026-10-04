// "Use verified settings automatically": gives games the player hasn't changed the best verified
// game database entry for this device type (main.py's auto_pending picks them). Runs a little
// after Game Mode starts, when the switch is turned on, and every 10 minutes for games installed
// since (each game is looked up again at most daily). Skips the running game, and entries that
// need a Proton version that isn't installed.
import { toaster } from "@decky/api";
import { runningAppId } from "../../shared/GamePicker";
import { autoPending, commit, compatTools, getGame } from "./api";

export const AUTO_FIRST_MS = 30_000;
export const AUTO_EVERY_MS = 600_000;

let running = false;

export async function autoSync(force = false): Promise<number> {
  if (running) return 0;
  running = true;
  const applied: string[] = [];
  try {
    for (const { appid, name, entry } of await autoPending(force)) {
      if (runningAppId() === appid) continue;
      if (entry.compat_tool && !(await compatTools(appid)).some((t) => t.strToolName === entry.compat_tool)) continue;
      const g = await getGame(appid);
      if (!g.auto_eligible) continue; // changed by the player in the meantime
      const p = { settings: entry.settings, env: entry.env, dlls: entry.dlls, compat_tool: entry.compat_tool };
      await commit(appid, g, p, { source: { id: entry.id, status: entry.status, auto: true }, verdict: null });
      applied.push(name);
    }
  } catch (e) {
    console.warn("Game Settings: verified settings automatically:", e);
  } finally {
    running = false;
  }
  if (applied.length)
    toaster.toast({ title: "Verified settings applied", body: applied.join(", ") + ". Game Settings can take them off." });
  return applied.length;
}
