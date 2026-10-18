// What the Moonlight pages share: routes, text styles, error toasts and polling the backend.
import { useEffect, useState } from "react";
import { Navigation } from "@decky/ui";
import { toaster } from "@decky/api";

export const ROUTE = "/kettle-moonlight";
export const HOST_ROUTE = "/kettle-moonlight-host"; // apart from ROUTE: the sidebar's route isn't exact

export const small = { fontSize: "12px", lineHeight: "16px" };
export const dim = { color: "#8b929a" };

// moonlight-qt's own controller combos (streaming/input/gamepad.cpp)
export const QUIT_COMBO = "Start + Select + L1 + R1";
export const STATS_COMBO = "Select + L1 + R1 + X";

export const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

export async function act(f: () => Promise<unknown>, fail: string) {
  try {
    await f();
  } catch (e) {
    toaster.toast({ title: "Moonlight", body: `${fail}: ${errorText(e)}` });
  }
}

// get(), now and every ms while shown; the second value reloads now
export function usePoll<T>(get: () => Promise<T>, ms: number): [T | null, () => void, string] {
  const [v, setV] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    const tick = () =>
      get()
        .then((r) => {
          if (!live) return;
          setV(r);
          setError("");
        })
        .catch((e) => live && setError(errorText(e)));
    tick();
    const t = ms > 0 ? setInterval(tick, ms) : undefined;
    return () => {
      live = false;
      if (t) clearInterval(t);
    };
  }, [n]);
  return [v, () => setN(n + 1), error];
}

export function openMoonlight() {
  Navigation.CloseSideMenus();
  Navigation.Navigate(ROUTE);
}

export function openHost(uuid: string, tab: "games" | "settings" | "pc" = "games") {
  Navigation.CloseSideMenus();
  Navigation.Navigate(`${HOST_ROUTE}/${uuid}/${tab}`);
}
