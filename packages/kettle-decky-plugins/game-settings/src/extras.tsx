// The Extras tab: downloads Kettle offers but can't ship in the image, for every game: the
// community Protons (GE-Proton, Proton-CachyOS) and the optional components (AMD FSR 3.1), through
// extras.py in the backend. They were Welcome's Gaming Extras up to 1.12.0-40.
import { ButtonItem, ConfirmModal, Field, PanelSection, PanelSectionRow, ProgressBarWithInfo, showModal } from "@decky/ui";
import { callable, toaster } from "@decky/api";
import { useEffect, useState } from "react";

const small = { fontSize: "12px", lineHeight: "16px" };
const red = { color: "#ff6b6b" };
const size = (n: number) => (n >= 1e9 ? `${(n / 1e9).toFixed(2)} GB` : `${Math.max(1, Math.round(n / 1e6))} MB`);

async function act(f: () => Promise<unknown>, fail: string) {
  try {
    await f();
  } catch (e) {
    toaster.toast({ title: "Game Settings", body: `${fail}: ${e}` });
  }
}

// get(), now and every ms while the tab is shown: downloads carry on in the background
function usePoll<T>(get: () => Promise<T>, ms: number): T | null {
  const [v, setV] = useState<T | null>(null);
  useEffect(() => {
    let live = true;
    const tick = () => get().then((r) => live && setV(r)).catch(() => {});
    tick();
    const t = setInterval(tick, ms);
    return () => {
      live = false;
      clearInterval(t);
    };
  }, []);
  return v;
}

type Component = {
  id: string;
  name: string;
  description: string;
  license: string;
  homepage: string;
  version: string;
  host: string;
  installed: string | null;
  busy: boolean;
  progress: number | null;
  error: string | null;
};
type Status = { components: Component[] };
// welcome-proton (package kettle-welcome): status is idle | running TOOL download BYTES TOTAL |
// running TOOL unpack | done TOOL NAME | error TOOL MESSAGE
type ProtonStatus = { available: boolean; status: string; installed: { tool: string; name: string }[] };

const status = callable<[], Status>("extras_status");
const install = callable<[id: string], void>("extras_install");
const uninstall = callable<[id: string], void>("extras_uninstall");
const protonStatus = callable<[], ProtonStatus>("proton_status");
const protonLatest = callable<[], Record<string, string>>("proton_latest");
const protonInstall = callable<[tool: string], void>("proton_install");
const protonRemove = callable<[name: string], void>("proton_remove");

function ComponentRow({ c }: { c: Component }) {
  const upgrade = c.installed !== null && c.installed !== c.version;
  const state = c.installed === null ? "" : upgrade ? ` (${c.installed} installed)` : " ✓";
  return (
    <>
      <Field
        label={`${c.name} ${c.version}${state}`}
        description={
          <div style={small}>
            {c.description}
            <br />
            {c.license} · downloaded from {c.host}
            {c.error && <div style={red}>{c.error}</div>}
          </div>
        }
        focusable={false}
      />
      {c.busy ? (
        <ProgressBarWithInfo nProgress={(c.progress ?? 0) * 100} indeterminate={!c.progress} sOperationText="Downloading" />
      ) : (
        <>
          {(c.installed === null || upgrade) && (
            <ButtonItem layout="below" onClick={() => act(() => install(c.id), "Install failed")}>
              {upgrade ? "Update" : "Download and install"}
            </ButtonItem>
          )}
          {c.installed !== null && (
            <ButtonItem layout="below" onClick={() => act(() => uninstall(c.id), "Remove failed")}>
              Remove
            </ButtonItem>
          )}
        </>
      )}
    </>
  );
}

// Community Protons with ARM64 releases, installed by welcome-proton into compatibilitytools.d
const PROTONS = [
  {
    id: "ge",
    name: "GE-Proton",
    description: "GloriousEggroll's Proton: Valve's Proton with extra fixes for individual games, a newer Wine, and codecs for games' video scenes.",
    host: "github.com/GloriousEggroll",
  },
  {
    id: "cachyos",
    name: "Proton-CachyOS",
    description: "The CachyOS team's Proton: Valve's Proton with a newer Wine, performance patches and extra game fixes.",
    host: "github.com/CachyOS",
  },
];

function ProtonSetup() {
  const s = usePoll(protonStatus, 1000);
  const [latest, setLatest] = useState<Record<string, string>>({});
  useEffect(() => {
    protonLatest().then(setLatest).catch(() => {});
  }, []);
  if (!s?.available) return null;
  const w = s.status.split(" ");
  const busy = w[0] === "running";
  return (
    <>
      {PROTONS.map((p) => {
        const builds = s.installed.filter((b) => b.tool === p.id).map((b) => b.name);
        const newest = latest[p.id] && latest[p.id] !== "-" ? latest[p.id] : null;
        const upToDate = newest !== null && builds.includes(newest);
        const mine = w[1] === p.id;
        return (
          <PanelSectionRow key={p.id}>
            <Field
              label={`${p.name}${newest ? ` (${newest})` : ""}${upToDate ? " ✓" : ""}`}
              description={
                <div style={small}>
                  {p.description} About 2 GB.
                  <br />
                  Latest ARM64 release, downloaded from {p.host} and checked against its published checksum
                  {mine && w[0] === "error" && <div style={red}>{w.slice(2).join(" ")}</div>}
                  {mine && w[0] === "done" && <div>{w[2]} is installed. Restart Steam to choose it for a game.</div>}
                </div>
              }
              focusable={false}
            />
            {busy && mine ? (
              <ProgressBarWithInfo
                nProgress={+w[4] > 0 ? (100 * +w[3]) / +w[4] : 0}
                indeterminate={w[2] !== "download" || !(+w[4] > 0)}
                sOperationText={w[2] === "unpack" ? "Unpacking" : +w[4] > 0 ? `Downloading: ${size(+w[3])} of ${size(+w[4])}` : "Downloading"}
              />
            ) : (
              !upToDate && (
                <ButtonItem layout="below" disabled={busy} onClick={() => act(() => protonInstall(p.id), "Install failed")}>
                  {builds.length > 0 ? "Update" : "Download and install"}
                </ButtonItem>
              )
            )}
            {mine && w[0] === "done" && (
              <ButtonItem layout="below" onClick={() => SteamClient.User.StartRestart(false)}>
                Restart Steam
              </ButtonItem>
            )}
            {builds.map((b) => (
              <ButtonItem
                key={b}
                layout="below"
                disabled={busy}
                onClick={() =>
                  showModal(
                    <ConfirmModal
                      strTitle={`Remove ${b}?`}
                      strDescription="Games set to use it need another Proton chosen in their Properties > Compatibility."
                      strOKButtonText="Remove"
                      onOK={() => act(() => protonRemove(b), "Remove failed")}
                    />,
                  )
                }
              >
                Remove {b}
              </ButtonItem>
            ))}
          </PanelSectionRow>
        );
      })}
    </>
  );
}

export function ExtrasTab() {
  const s = usePoll(status, 2000);
  return (
    <>
      <PanelSection title="Proton versions">
        <PanelSectionRow>
          <div style={small}>
            Used only for a game you choose them for, in its Proton version on the Compatibility tab (or its Properties &gt;
            Compatibility).
          </div>
        </PanelSectionRow>
        <ProtonSetup />
      </PanelSection>
      {s && s.components.length > 0 && (
        <PanelSection title="Graphics">
          {s.components.map((c) => (
            <PanelSectionRow key={c.id}>
              <ComponentRow c={c} />
            </PanelSectionRow>
          ))}
        </PanelSection>
      )}
      <PanelSection>
        <PanelSectionRow>
          <div style={small}>
            Each is downloaded from its own project and checked against a checksum before it is installed.
          </div>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}
