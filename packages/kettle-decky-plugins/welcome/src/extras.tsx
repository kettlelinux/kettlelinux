// Gaming Extras in Game Mode: what the desktop's Kettle Welcome offers on its Gaming Extras page
// that works with a controller (Flathub apps, through the same welcome-flatpak), each added to
// Steam as a shortcut so it can be started here; Battle.net (battlenet.tsx); the community Protons
// (welcome-proton); and the optional components Kettle can't ship itself (components.json).
import { ButtonItem, ConfirmModal, Field, ProgressBarWithInfo, showModal } from "@decky/ui";
import { callable } from "@decky/api";
import { useEffect, useState } from "react";
import { BattleNet } from "./battlenet";
import { Heading, Plain, Row, Text, act, red, size, small, usePoll } from "./ui";

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
export type Status = { components: Component[] };
// welcome-proton (package kettle-welcome): status is idle | running TOOL download BYTES TOTAL |
// running TOOL unpack | done TOOL NAME | error TOOL MESSAGE
type ProtonStatus = { available: boolean; status: string; installed: { tool: string; name: string }[] };
// welcome-flatpak: status is idle | running I N ID | done N | error ID MESSAGE; shortcuts: app
// ID -> appid of the Steam shortcut added for it
type ExtrasStatus = { status: string; installed: string[]; shortcuts: Record<string, number> };

export const status = callable<[], Status>("status");
const install = callable<[id: string], void>("install");
const uninstall = callable<[id: string], void>("uninstall");
const protonStatus = callable<[], ProtonStatus>("proton_status");
const protonLatest = callable<[], Record<string, string>>("proton_latest");
const protonInstall = callable<[tool: string], void>("proton_install");
const protonRemove = callable<[name: string], void>("proton_remove");
const extrasStatus = callable<[], ExtrasStatus>("extras_status");
const extrasInstall = callable<[app: string], void>("extras_install");
const flatpakIcon = callable<[app: string], string>("flatpak_icon");
const rememberShortcut = callable<[app: string, appid: number], void>("remember_shortcut");

// The desktop's Gaming Extras (kettle-welcome ExtrasPage.qml) that work with a controller. Its
// mouse-driven tools (Flatseal, Warehouse, ProtonUp-Qt, SGDBoop, ...) stay on the desktop.
const APPS: { title: string; apps: { id: string; name: string; description: string }[] }[] = [
  {
    title: "Emulators",
    apps: [
      { id: "org.libretro.RetroArch", name: "RetroArch", description: "One app for many classic consoles, through downloadable emulator cores." },
      { id: "org.DolphinEmu.dolphin-emu", name: "Dolphin", description: "Nintendo GameCube and Wii." },
      { id: "org.ppsspp.PPSSPP", name: "PPSSPP", description: "Sony PlayStation Portable." },
      { id: "org.azahar_emu.Azahar", name: "Azahar", description: "Nintendo 3DS." },
      { id: "net.kuribo64.melonDS", name: "melonDS", description: "Nintendo DS." },
      { id: "io.github.ryubing.Ryujinx", name: "Ryujinx", description: "Nintendo Switch." },
      { id: "net.rpcs3.RPCS3", name: "RPCS3", description: "Sony PlayStation 3. Demanding: many games run slowly on a handheld." },
      { id: "app.xemu.xemu", name: "xemu", description: "The original Microsoft Xbox." },
      { id: "org.flycast.Flycast", name: "Flycast", description: "Sega Dreamcast, Naomi and Atomiswave." },
      { id: "com.github.Rosalie241.RMG", name: "Rosalie's Mupen GUI", description: "Nintendo 64." },
      { id: "io.mgba.mGBA", name: "mGBA", description: "Game Boy Advance, Game Boy and Game Boy Color." },
      { id: "org.scummvm.ScummVM", name: "ScummVM", description: "Classic point-and-click adventures, using the original game data." },
    ],
  },
  {
    title: "Game streaming",
    apps: [
      { id: "com.moonlight_stream.Moonlight", name: "Moonlight", description: "Streams games from your gaming PC (Sunshine or NVIDIA GameStream) to this device." },
      { id: "io.github.streetpea.Chiaki4deck", name: "Chiaki4deck", description: "PlayStation 4 and 5 Remote Play." },
    ],
  },
];
const appName = (id: string) => APPS.flatMap((g) => g.apps).find((a) => a.id === id)?.name ?? id;

const inSteam = (appid: number | undefined) => {
  try {
    return !!appid && !!(window as any).appStore?.GetAppOverviewByAppID(appid);
  } catch {
    return false;
  }
};

// A Steam shortcut that runs the Flatpak app, with its icon
async function addToSteam(app: { id: string; name: string }) {
  const launch = `run ${app.id}`;
  const id = await SteamClient.Apps.AddShortcut(app.name, "/usr/bin/flatpak", "", launch);
  if (!id) throw new Error("Steam didn't create the shortcut");
  SteamClient.Apps.SetShortcutName(id, app.name);
  SteamClient.Apps.SetShortcutExe(id, '"/usr/bin/flatpak"');
  SteamClient.Apps.SetShortcutLaunchOptions(id, launch);
  const icon = await flatpakIcon(app.id);
  if (icon) SteamClient.Apps.SetShortcutIcon(id, icon);
  await rememberShortcut(app.id, id);
}

// apps asked for here, added to Steam when their install finishes while the page is open (one
// that finishes later gets an Add to Steam button)
const wanted = new Set<string>();

function FlatpakApps() {
  const [s, refresh] = usePoll(extrasStatus, 1500);
  useEffect(() => {
    if (!s) return;
    if (s.status.startsWith("error")) wanted.clear();
    for (const id of [...wanted].filter((id) => s.installed.includes(id))) {
      wanted.delete(id);
      if (!inSteam(s.shortcuts[id])) act(() => addToSteam({ id, name: appName(id) }).then(refresh), `Adding ${appName(id)} to Steam failed`);
    }
  }, [s]);
  if (!s) return null;
  const w = s.status.split(" ");
  const busy = w[0] === "running";
  return (
    <>
      <Text>
        <p style={small}>
          {busy
            ? +w[1] === 0
              ? "Getting ready…"
              : `Installing ${appName(w[3])}…`
            : w[0] === "error"
              ? null
              : "From Flathub, for your user only. Remove them in the desktop's Discover."}
          {w[0] === "error" && (
            <span style={red}>
              {w[1] === "-" || w[1] === "flathub" ? "" : `${appName(w[1])} could not be installed: `}
              {w.slice(2).join(" ")}
            </span>
          )}
        </p>
      </Text>
      {APPS.map((g) => (
        <div key={g.title}>
          <Heading>{g.title}</Heading>
          {g.apps.map((a) => {
            const installed = s.installed.includes(a.id);
            const added = installed && inSteam(s.shortcuts[a.id]);
            const mine = busy && w[3] === a.id;
            return (
              <div key={a.id} style={{ maxWidth: "720px" }}>
                <Field
                  label={`${a.name}${added ? " ✓" : installed ? " (installed)" : ""}`}
                  description={<div style={small}>{a.description}</div>}
                  focusable={false}
                />
                {mine ? (
                  <ProgressBarWithInfo indeterminate nProgress={0} sOperationText="Installing" />
                ) : !installed ? (
                  <ButtonItem layout="below" disabled={busy} onClick={() => act(() => extrasInstall(a.id).then(() => wanted.add(a.id)).then(refresh), "Install failed")}>
                    Install and add to Steam
                  </ButtonItem>
                ) : (
                  !added && (
                    <ButtonItem layout="below" onClick={() => act(() => addToSteam(a).then(refresh), "Adding to Steam failed")}>
                      Add to Steam
                    </ButtonItem>
                  )
                )}
              </div>
            );
          })}
        </div>
      ))}
    </>
  );
}

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

function ProtonSetup({ Row }: { Row: Row }) {
  const [s] = usePoll(protonStatus, 1000);
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
          <Row key={p.id}>
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
          </Row>
        );
      })}
    </>
  );
}

// The downloads, both on the Gaming Extras page and in the Quick Access panel (Row: PanelSectionRow)
export function Setup({ s, Row }: { s: Status; Row: Row }) {
  return (
    <>
      {s.components.map((c) => (
        <Row key={c.id}>
          <ComponentRow c={c} />
        </Row>
      ))}
      <ProtonSetup Row={Row} />
    </>
  );
}

export function ExtrasPage({ flatpak }: { flatpak: boolean }) {
  const [s] = usePoll(status, 2000);
  return (
    <>
      <Text>
        <h2 style={{ marginTop: 0 }}>Gaming Extras</h2>
        <p>
          Emulators and game streaming apps, added to your Steam library so they start from here like a game. More apps,
          and tools that need a mouse, are in the desktop's Gaming Extras.
        </p>
      </Text>
      {flatpak && <FlatpakApps />}
      <Heading>Game stores</Heading>
      <BattleNet />
      <Heading>Proton versions and graphics</Heading>
      <Text>
        <p style={small}>
          Optional extras Kettle can't include itself, each downloaded from its own project and checked against a
          checksum before it is installed. The other Protons are only used for a game you choose them for, in its
          Properties &gt; Compatibility or in Game Settings.
        </p>
      </Text>
      {s && <Setup s={s} Row={Plain} />}
    </>
  );
}
