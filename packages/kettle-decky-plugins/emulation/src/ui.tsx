// What the Emulation pages share: routes, text styles, error toasts, polling the backend, and the
// standard controls (kettle-emulation's mkvdf.py: the same in every emulator).
import { useEffect, useState } from "react";
import { Navigation } from "@decky/ui";
import { toaster } from "@decky/api";

export const ROUTE = "/kettle-emulation";
export const START_ROUTE = "/kettle-emulation-start"; // apart from ROUTE: the sidebar's route isn't exact

export const small = { fontSize: "12px", lineHeight: "16px" };
export const dim = { color: "#8b929a" };
export const warn = { color: "#e0b341" };
export const good = { color: "#59bf40" };

export const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

export async function act(f: () => Promise<unknown>, fail: string) {
  try {
    await f();
  } catch (e) {
    toaster.toast({ title: "Emulation", body: `${fail}: ${errorText(e)}` });
  }
}

// get(), now and every ms while shown; the second value reloads now
export function usePoll<T>(get: () => Promise<T>, ms: number, deps: unknown[] = []): [T | null, () => void, string] {
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
  }, [n, ...deps]);
  return [v, () => setN((x) => x + 1), error];
}

export type Tab = "library" | "add" | "bios" | "controls" | "saves" | "cores" | "settings";

export function openEmulation(tab: Tab = "library") {
  Navigation.CloseSideMenus();
  Navigation.Navigate(`${ROUTE}/${tab}`);
}

export function openStart() {
  Navigation.CloseSideMenus();
  Navigation.Navigate(START_ROUTE);
}

export const size = (b: number) =>
  b >= 1 << 30 ? `${(b / (1 << 30)).toFixed(1)} GB` : b >= 1 << 20 ? `${(b / (1 << 20)).toFixed(0)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`;

export const plural = (n: number, one: string, many = one + "s") => `${n} ${n === 1 ? one : many}`;

// --- the standard controls ----------------------------------------------------------------------
// The buttons go by their labels: on a Nintendo-labelled pad (Thor, Retroid) A is the right one.
export const CONTROLS: [string, string][] = [
  ["Select + A", "Save state"],
  ["Select + B", "Load state"],
  ["Select + X", "Emulator menu"],
  ["Select + Y", "Fast-forward on or off"],
  ["Select + L1 / R1", "State slot down / up"],
  ["Select + L2 (hold)", "Rewind (8/16-bit systems)"],
  ["Select + R2", "Screenshot (not in melonDS)"],
  ["Select + D-pad left/right", "Swap screens (DS, melonDS)"],
  ["Select + Start", "Quit to Steam (if an emulator hangs: Steam menu > Exit game)"],
];

const keyCap = {
  display: "inline-block",
  padding: "1px 7px",
  borderRadius: "4px",
  background: "#3d4450",
  fontWeight: 600,
  marginRight: "2px",
  whiteSpace: "nowrap" as const,
};

export function ControlsTable({ face, compact = false }: { face: "xbox" | "nintendo"; compact?: boolean }) {
  return (
    <div style={compact ? small : undefined}>
      <table style={{ borderCollapse: "collapse", width: "100%" }}>
        <tbody>
          {CONTROLS.map(([combo, what]) => (
            <tr key={combo}>
              <td style={{ padding: compact ? "2px 6px 2px 0" : "5px 12px 5px 0", whiteSpace: "nowrap" }}>
                {combo.split(" + ").map((k, i) => (
                  <span key={i}>
                    {i > 0 && " + "}
                    <span style={keyCap}>{k}</span>
                  </span>
                ))}
              </td>
              <td style={{ padding: compact ? "2px 0" : "5px 0" }}>{what}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ ...small, ...dim, marginTop: compact ? "4px" : "8px" }}>
        Tap Select on its own and the game gets Select.
        {face === "nintendo" && " A, B, X and Y are the buttons printed so: on this device A is the right one."}
      </div>
    </div>
  );
}
