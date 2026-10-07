// What the Game Stores pages share: text styles, error toasts, polling the backend, signing in,
// opening a game's page and a download's progress.
import { useEffect, useState } from "react";
import { Navigation, ProgressBarWithInfo } from "@decky/ui";
import { toaster } from "@decky/api";
import { Job, NAMES, Source, Store, loginStart } from "./api";

export const ROUTE = "/kettle-stores";
export const GAME_ROUTE = "/kettle-stores-game"; // apart from ROUTE: the sidebar's route isn't exact

export const small = { fontSize: "12px", lineHeight: "16px" };
export const dim = { color: "#8b929a" };

export async function act(f: () => Promise<unknown>, fail: string) {
  try {
    await f();
  } catch (e) {
    toaster.toast({ title: "Game Stores", body: `${fail}: ${e instanceof Error ? e.message : e}` });
  }
}

// get(), now and every ms while shown: downloads carry on in the background
export function usePoll<T>(get: () => Promise<T>, ms: number): [T | null, () => void] {
  const [v, setV] = useState<T | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    const tick = () => get().then((r) => live && setV(r)).catch(() => {});
    tick();
    const t = setInterval(tick, ms);
    return () => {
      live = false;
      clearInterval(t);
    };
  }, [n]);
  return [v, () => setN(n + 1)];
}

// Opens the store's login page in Steam's browser; the backend notices the sign-in there, and
// index.tsx's "login" listener leaves the browser
export async function signIn(store: Store) {
  const url = await loginStart(store);
  Navigation.CloseSideMenus();
  (SteamClient.URL as any).ExecuteSteamURL(`steam://openurl/${url}`); // (missing from @decky/ui's types)
  toaster.toast({ title: `Sign in to ${NAMES[store]}`, body: "Steam's browser returns here once you're signed in." });
}

// (Flathub's apps too: the game route shows their page, flathub.tsx)
export function openGame(store: Source, id: string) {
  Navigation.CloseSideMenus();
  Navigation.Navigate(`${GAME_ROUTE}/${store}/${encodeURIComponent(id)}`);
}

export function openStores(tab: string = "downloads") {
  Navigation.CloseSideMenus();
  Navigation.Navigate(`${ROUTE}/${tab}`);
}

export function JobProgress({ job }: { job: Job }) {
  const pct = job.percent ?? 0;
  const detail = [job.speed ? `${job.speed.toFixed(1)} MiB/s` : "", job.eta ? `${job.eta} left` : ""].filter(Boolean).join(" · ");
  return (
    <ProgressBarWithInfo
      nProgress={pct}
      sOperationText={`${job.kind === "update" ? "Updating" : "Installing"} ${job.title}`}
      description={detail || "Starting…"}
      indeterminate={pct === 0}
    />
  );
}
