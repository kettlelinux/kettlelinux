// What the Welcome pages share: text styles, error toasts, and polling the backend.
import { FC, ReactNode, useEffect, useState } from "react";
import { toaster } from "@decky/api";

export const small = { fontSize: "12px", lineHeight: "16px" };
export const red = { color: "#ff6b6b" };

export const Text = ({ children }: { children: ReactNode }) => <div style={{ lineHeight: "22px", maxWidth: "720px" }}>{children}</div>;

// A page's section heading, like the desktop Welcome's
export const Heading = ({ children }: { children: ReactNode }) => (
  <h3 style={{ margin: "24px 0 4px", maxWidth: "720px" }}>{children}</h3>
);

// Rows of a list: plain on the welcome page, PanelSectionRow in the Quick Access panel
export type Row = FC<{ children: ReactNode }>;
export const Plain: Row = ({ children }) => <>{children}</>;

export async function act(f: () => Promise<unknown>, fail: string) {
  try {
    await f();
  } catch (e) {
    toaster.toast({ title: "Welcome", body: `${fail}: ${e}` });
  }
}

// get(), now and every ms while shown: installs carry on in the background
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

export const size = (n: number) => (n >= 1e9 ? `${(n / 1e9).toFixed(2)} GB` : `${Math.max(1, Math.round(n / 1e6))} MB`);
