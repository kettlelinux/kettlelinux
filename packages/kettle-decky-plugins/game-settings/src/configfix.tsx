// Game config fixes (configfix.py): a value set in a game's own config file in its prefix, for a
// game that needs one to run here and has no launch option for it. Shown with the game fixes
// (shared/gameFixes.ts) in the Compatibility tab, on unless turned off for the game.
import { PanelSectionRow, ToggleField } from "@decky/ui";
import { callable } from "@decky/api";
import { useEffect, useState } from "react";

// on: the player hasn't turned it off; applied: our key is in the file; game_value: the file's
// own value for the key (set by the game or in its options), kept; pending: no prefix yet
type ConfigFix = {
  id: string;
  title: string;
  description: string;
  on: boolean;
  applied: boolean;
  game_value: string | null;
  pending: boolean;
};

const getFixes = callable<[appid: number], ConfigFix[]>("configfix_get");
const setFix = callable<[appid: number, id: string, on: boolean], ConfigFix[]>("configfix_set");
// after a game exits (index.tsx): a first launch made its prefix and config file
export const syncConfigFixes = callable<[], void>("configfix_sync");

export function ConfigFixes({ appid, name }: { appid: number; name: string }) {
  const [fixes, setFixes] = useState<ConfigFix[]>([]);
  useEffect(() => {
    setFixes([]);
    getFixes(appid).then(setFixes).catch(() => {});
  }, [appid]);
  return (
    <>
      {fixes.map((f) => {
        const state = !f.on
          ? ""
          : f.pending
            ? ` Set after ${name}'s first launch here, which runs without it.`
            : !f.applied && f.game_value !== null
              ? ` The game's config already sets it (${f.game_value}): left as it is.`
              : "";
        return (
          <PanelSectionRow key={f.id}>
            <ToggleField
              label={`Kettle fix: ${f.title}`}
              description={f.description + state}
              checked={f.on}
              onChange={async (on) => {
                setFixes(fixes.map((x) => (x.id === f.id ? { ...x, on } : x)));
                setFixes(await setFix(appid, f.id, on));
              }}
            />
          </PanelSectionRow>
        );
      })}
    </>
  );
}
