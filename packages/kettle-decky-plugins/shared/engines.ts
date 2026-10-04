// How the engine gameengine.py found reads: "Unity (Mono) · 64-bit x86" (a native Linux build:
// "Unity (Mono) · native Linux build · 64-bit x86"), and its anti-cheat.
import ENGINES from "./engines.json";

export type Engine = { engine: string; platform: string; arch: string; exe: string | null; anticheat: string[] };

const label = (list: { id: string; label: string }[], id: string) => list.find((x) => x.id === id)?.label ?? id;

export const engineLabel = (e: Engine) => label(ENGINES.engines, e.engine);

export const engineText = (e: Engine) =>
  [
    label(ENGINES.engines, e.engine),
    e.platform === "linux" && label(ENGINES.platforms, e.platform),
    e.arch && label(ENGINES.archs, e.arch),
  ].filter(Boolean).join(" · ");

export const anticheatText = (e: Engine) => e.anticheat.map((a) => label(ENGINES.anticheat, a)).join(" and ");
