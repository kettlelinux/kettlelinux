import { ButtonItem, DropdownItem, Field, Navigation, PanelSection, PanelSectionRow, ProgressBarWithInfo, SidebarNavigation, staticClasses } from "@decky/ui";
import { callable, definePlugin, routerHook, toaster } from "@decky/api";
import { FC, ReactNode, useEffect, useState } from "react";
import { FaDesktop, FaDownload, FaGamepad, FaHandSparkles, FaMugHot } from "react-icons/fa";
import { applyGameFixes } from "./fixes";

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
type BootMode = "game" | "desktop";

const status = callable<[], Status>("status");
const firstRun = callable<[], boolean>("first_run");
const claimDefault = callable<[name: string], boolean>("claim_default");
const install = callable<[id: string], void>("install");
const bootMode = callable<[], BootMode | null>("boot_mode");
const setBootMode = callable<[mode: BootMode], void>("set_boot_mode");
const uninstall = callable<[id: string], void>("uninstall");

const ROUTE = "/kettle-welcome";
const small = { fontSize: "12px", lineHeight: "16px" };

const openWelcome = () => {
  Navigation.CloseSideMenus();
  Navigation.Navigate(`${ROUTE}/welcome`);
};

// Backend status, polled while shown: downloads and Steam installs finish in the background
function useStatus(): Status | null {
  const [s, setS] = useState<Status | null>(null);
  useEffect(() => {
    let live = true;
    const tick = () => status().then((v) => live && setS(v)).catch(() => {});
    tick();
    const t = setInterval(tick, 2000);
    return () => {
      live = false;
      clearInterval(t);
    };
  }, []);
  return s;
}

function ComponentRow({ c }: { c: Component }) {
  const run = async (f: () => Promise<void>, fail: string) => {
    try {
      await f();
    } catch (e) {
      toaster.toast({ title: "Welcome", body: `${fail}: ${e}` });
    }
  };
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
            {c.error && <div style={{ color: "#ff6b6b" }}>{c.error}</div>}
          </div>
        }
        focusable={false}
      />
      {c.busy ? (
        <ProgressBarWithInfo nProgress={(c.progress ?? 0) * 100} indeterminate={!c.progress} sOperationText="Downloading" />
      ) : (
        <>
          {(c.installed === null || upgrade) && (
            <ButtonItem layout="below" onClick={() => run(() => install(c.id), "Install failed")}>
              {upgrade ? "Update" : "Download and install"}
            </ButtonItem>
          )}
          {c.installed !== null && (
            <ButtonItem layout="below" onClick={() => run(() => uninstall(c.id), "Remove failed")}>
              Remove
            </ButtonItem>
          )}
        </>
      )}
    </>
  );
}

// The checklist, both on the welcome page and in the Quick Access panel (Row: PanelSectionRow)
type Row = FC<{ children: ReactNode }>;
const Plain: Row = ({ children }) => <>{children}</>;

function Setup({ s, Row }: { s: Status; Row: Row }) {
  return (
    <>
      {s.components.map((c) => (
        <Row key={c.id}>
          <ComponentRow c={c} />
        </Row>
      ))}
    </>
  );
}

// steamos-manager's default login mode; switching from the power menu only lasts until a reboot
const BOOT_MODES = [
  { data: "game" as BootMode, label: "Game Mode (Steam)" },
  { data: "desktop" as BootMode, label: "Desktop" },
];

function BootModeSetting() {
  const [mode, setMode] = useState<BootMode | null>(null);
  useEffect(() => {
    bootMode().then(setMode).catch(() => {});
  }, []);
  const choose = async (m: BootMode) => {
    const was = mode;
    setMode(m);
    try {
      await setBootMode(m);
    } catch (e) {
      setMode(was);
      toaster.toast({ title: "Welcome", body: `Couldn't change the start-up mode: ${e}` });
    }
  };
  return (
    <div style={{ maxWidth: "720px" }}>
      <DropdownItem
        label="Start up in"
        description="What Kettle opens when it turns on. Switching from the power menu lasts until the next restart."
        rgOptions={BOOT_MODES}
        selectedOption={mode}
        disabled={mode === null}
        onChange={(o) => choose(o.data)}
      />
    </div>
  );
}

const Text = ({ children }: { children: ReactNode }) => <div style={{ lineHeight: "22px", maxWidth: "720px" }}>{children}</div>;

function SetupPage() {
  const s = useStatus();
  if (!s) return null;
  return (
    <>
      <Text>
        <p>
          Optional extras Kettle can't include itself. Anything downloaded here comes from its own project's servers
          and is checked against a pinned checksum before it is installed.
        </p>
      </Text>
      <Setup s={s} Row={Plain} />
    </>
  );
}

// Fixed, so the sidebar isn't rebuilt on every render. SidebarNavigation reports each tab as a
// route under ROUTE (as Decky's own settings do), which is why that route isn't exact.
const PAGES = [
  {
    title: "Welcome",
    route: `${ROUTE}/welcome`,
    icon: <FaMugHot />,
    content: (
      <>
        <Text>
          <h2>Welcome to Kettle Linux</h2>
          <p>
            Kettle is a SteamOS-style system for the AYN Odin 2 Portal: Valve's arm64 Steam client with Game Mode, a
            Plasma desktop, and Windows games through Proton ARM64.
          </p>
          <p>
            Kettle's own tools live in the Quick Access menu (the <b>…</b> button), under the plug icon: Frame
            Generation, Upscaling, and this Welcome page. Everything is off until you turn it on for a game.
          </p>
          <p>The last page, Setup, lists optional extras. You can come back here from Quick Access at any time.</p>
        </Text>
        <BootModeSetting />
      </>
    ),
  },
  {
    title: "Game Mode",
    route: `${ROUTE}/game-mode`,
    icon: <FaGamepad />,
    content: (
      <Text>
        <h2>Per-game enhancements</h2>
        <p>
          Both panels open on the running game, and can set up any installed game before you launch it. Settings are
          kept when you turn a game off.
        </p>
        <p>
          <b>Frame Generation</b> shows extra frames between the ones the game renders (2–4×), with Kettle's own
          engine: nothing to buy or install. The base frame rate is capped automatically: leave Steam's frame limit
          off for these games.
        </p>
        <p>
          <b>Upscaling</b> renders the game at a lower resolution and scales it up: FSR 1 through gamescope for any
          game, or Snapdragon GSR 2 for games that offer DLSS, FSR 2+ or XeSS.
        </p>
      </Text>
    ),
  },
  {
    title: "Desktop mode",
    route: `${ROUTE}/desktop`,
    icon: <FaDesktop />,
    content: (
      <Text>
        <h2>Desktop mode</h2>
        <p>
          Switch from the power menu. The gamepad drives the mouse and keyboard there; hold <b>Select + Start</b> to
          hand it to a game started from the desktop, and again to take it back.
        </p>
        <p>
          Left stick: pointer · Right stick: scroll · A / R2: click · B / L2: right click · R1 (held): precise pointer
          · R3: middle click · X / Home: on-screen keyboard · Y: Enter · D-pad: arrow keys · L1: Escape · Start:
          application menu · Select: Overview
        </p>
      </Text>
    ),
  },
  {
    title: "Setup",
    route: `${ROUTE}/setup`,
    icon: <FaDownload />,
    content: <SetupPage />,
  },
];

const Page = () => (
  <div style={{ marginTop: "40px", height: "calc(100% - 40px)" }}>
    <SidebarNavigation title="Welcome" showTitle pages={PAGES} />
  </div>
);

function Content() {
  const s = useStatus();
  return (
    <>
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={openWelcome}>
            Open Welcome
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      {s && (
        <PanelSection title="Setup">
          <Setup s={s} Row={PanelSectionRow} />
        </PanelSection>
      )}
    </>
  );
}

// Steam's UI sets App.m_CurrentUser once someone is signed in. (The login state numbers that
// RegisterForLoginStateChange reports don't match @decky/ui's ELoginState on this client: it
// reports 5, "WaitingForServerResponse" there, while signed in.)
const signedIn = () => !!(window as any).App?.m_CurrentUser;

// Runs fn once, when someone is signed in to Steam (at once if already). Plugins load before
// Steam's first-time setup and sign-in: opening the welcome page then took Steam off its setup
// pages (language, network, time zone), and it went straight on to sign-in after.
function whenSignedIn(fn: () => void): () => void {
  let done = false;
  const check = () => {
    if (done || !signedIn()) return;
    done = true;
    stop();
    fn();
  };
  // login state changes say when to look; the timer covers a change that sets the user later
  const reg = SteamClient.User.RegisterForLoginStateChange(() => setTimeout(check, 0));
  const timer = setInterval(check, 2000);
  const stop = () => {
    clearInterval(timer);
    reg?.unregister();
  };
  setTimeout(check, 0);
  return stop;
}

// Kettle's defaults for Steam settings that have no system-wide configuration: Steam keeps them
// in its UI's own storage, so they are set here, through the same call as its Settings page,
// once per device (claim_default), and a later change in Settings sticks.
function applySteamDefaults() {
  // Settings > System > Show battery percentage (Steam's default: off)
  const settings = (window as any).settingsStore;
  if (typeof settings?.SetBatteryPreferences === "function") {
    claimDefault("battery-percentage")
      .then((first) => first && settings.SetBatteryPreferences({ bShowBatteryPercentage: true }))
      .catch((e) => console.error("Welcome: battery percentage default failed", e));
  }
}

export default definePlugin(() => {
  routerHook.addRoute(ROUTE, Page);
  // after sign-in, and a moment for Game Mode's home screen to come up
  const stopWaiting = whenSignedIn(() => {
    applySteamDefaults();
    firstRun()
      .then((first) => first && setTimeout(openWelcome, 3000))
      .catch(() => {});
  });
  applyGameFixes().catch((e) => console.error("Welcome: game fixes failed", e));
  return {
    name: "Welcome",
    titleView: <div className={staticClasses.Title}>Welcome</div>,
    content: <Content />,
    icon: <FaHandSparkles />,
    onDismount: () => {
      stopWaiting();
      routerHook.removeRoute(ROUTE);
    },
  };
});
