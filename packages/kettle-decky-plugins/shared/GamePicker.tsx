// Game selector for per-game settings: the running game first, then installed games by
// last played. The choice survives the Quick Access panel closing (module state).
import { DropdownItem, PanelSectionRow, Router } from "@decky/ui";
import { useEffect, useState } from "react";

export type InstalledGame = { appid: number; name: string };
// GamePicker's "All games" entry (allGames), for settings every game without its own uses
export const ALL_GAMES = -1;

let lastPicked: number | null = null;

function lastPlayed(appid: number): number {
  try {
    return (window as any).appStore?.GetAppOverviewByAppID(appid)?.rt_last_time_played ?? 0;
  } catch {
    return 0;
  }
}

export function runningAppId(): number | null {
  const a = Router.MainRunningApp;
  return a ? Number(a.appid) : null;
}

// Selected appid: the running game when the panel opens, else the last pick, else the most
// recently played installed game.
export function useSelectedGame(games: InstalledGame[] | null): [number | null, (a: number) => void] {
  const [appid, setAppid] = useState<number | null>(runningAppId() ?? lastPicked);
  useEffect(() => {
    if (appid === null && games?.length) setAppid([...games].sort((a, b) => lastPlayed(b.appid) - lastPlayed(a.appid))[0].appid);
  }, [games]);
  return [appid, (a) => { lastPicked = a; setAppid(a); }];
}

export function GamePicker({ games, appid, onChange, allGames }: {
  games: InstalledGame[];
  appid: number | null;
  onChange: (a: number) => void;
  allGames?: boolean;
}) {
  const running = runningAppId();
  const opts = [...games].sort((a, b) => {
    if (a.appid === running) return -1;
    if (b.appid === running) return 1;
    return lastPlayed(b.appid) - lastPlayed(a.appid);
  });
  // a running non-Steam shortcut or a game outside the libraries still gets an entry
  if (running !== null && !opts.some((g) => g.appid === running))
    opts.unshift({ appid: running, name: Router.MainRunningApp?.display_name ?? `App ${running}` });
  return (
    <PanelSectionRow>
      <DropdownItem
        label="Game"
        rgOptions={[
          ...(allGames ? [{ data: ALL_GAMES, label: "All games" }] : []),
          ...opts.map((g) => ({ data: g.appid, label: g.appid === running ? `▶ ${g.name}` : g.name })),
        ]}
        selectedOption={appid}
        onChange={(o) => onChange(o.data)}
      />
    </PanelSectionRow>
  );
}

export function gameName(games: InstalledGame[] | null, appid: number): string {
  return games?.find((g) => g.appid === appid)?.name ?? Router.MainRunningApp?.display_name ?? `App ${appid}`;
}
