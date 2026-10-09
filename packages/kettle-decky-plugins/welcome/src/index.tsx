import { ButtonItem, DropdownItem, Navigation, PanelSection, PanelSectionRow, SidebarNavigation, ToggleField, staticClasses } from "@decky/ui";
import { callable, definePlugin, routerHook, toaster } from "@decky/api";
import { ReactNode, useEffect, useMemo, useState } from "react";
import { FaAndroid, FaDesktop, FaDownload, FaGamepad, FaHandSparkles, FaMugHot, FaNetworkWired, FaUndo } from "react-icons/fa";
import { applyGameFixes } from "./fixes";
import { addDesktop } from "./desktop";
import { AndroidPage } from "./android";
import { ExtrasPage, Setup, status } from "./extras";
import { ResetPage } from "./reset";
import { Heading, Text, act, red, small, usePoll } from "./ui";

type BootMode = "game" | "desktop";
// plugins: Kettle's Decky plugins on this device ("framegen", "screens", ...); files: where to
// look for an APK file
type Features = { plugins: string[]; extras: boolean; android: boolean; files: string };
type Ssh = { active: boolean; enabled: boolean; user: string; addresses: string[] };

const firstRun = callable<[], boolean>("first_run");
const signedIn = callable<[], boolean>("signed_in");
const claimDefault = callable<[name: string], boolean>("claim_default");
const bootMode = callable<[], BootMode | null>("boot_mode");
const setBootMode = callable<[mode: BootMode], void>("set_boot_mode");
const features = callable<[], Features>("features");
const sshStatus = callable<[], Ssh>("ssh_status");
const setSsh = callable<[on: boolean], void>("set_ssh");

const ROUTE = "/kettle-welcome";

const openWelcome = () => {
  Navigation.CloseSideMenus();
  Navigation.Navigate(`${ROUTE}/welcome`);
};
const go = (page: string) => Navigation.Navigate(`${ROUTE}/${page}`);
// a page of Steam's Settings, the way Steam's own menus open one (not in @decky/ui's typings)
const steamSettings = (page: string) => (SteamClient.URL as any).ExecuteSteamURL(`steam://open/settings/${page}`);

// One of a page's links: a button with what it's for below it
const Link = ({ label, description, onClick }: { label: string; description: string; onClick: () => void }) => (
  <div style={{ maxWidth: "720px" }}>
    <ButtonItem layout="below" description={description} onClick={onClick}>
      {label}
    </ButtonItem>
  </div>
);

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

function WelcomePage({ f }: { f: Features }) {
  return (
    <>
      <Text>
        <h2 style={{ marginTop: 0 }}>Welcome to Kettle Linux</h2>
        <p>
          Kettle is a SteamOS-style system for Snapdragon handhelds: Valve's arm64 Steam client with Game Mode, a Plasma
          desktop, and Windows games through Proton ARM64.
        </p>
        <p>
          Game Mode is where you play. Kettle's own tools are in the Quick Access menu (the <b>…</b> button), under the
          plug icon. This page stays there too, under Welcome.
        </p>
      </Text>
      <Heading>Get started</Heading>
      <Link label="Connect to Wi-Fi" description="Pick a network in Steam's Internet settings." onClick={() => steamSettings("internet")} />
      <Link label="Kettle in Game Mode" description="Frame generation, upscaling, per-game settings and more, per game." onClick={() => go("game-mode")} />
      {f.extras && (
        <Link label="Get emulators and streaming apps" description="Install them from Flathub and add them to your Steam library." onClick={() => go("extras")} />
      )}
      {f.android && (
        <Link label="Add Android games" description="From F-Droid or an APK file, played in Game Mode like any game." onClick={() => go("android")} />
      )}
      <Link
        label="Change your password"
        description={`The account starts with the password "kettle". Change it in the desktop: it also protects remote logins (SSH) and administrator tasks.`}
        onClick={() => go("desktop")}
      />
      <Heading>Start up in</Heading>
      <BootModeSetting />
    </>
  );
}

// Kettle's plugins, as far as this device has them
const TOOLS: { plugin: string; name: string; text: ReactNode }[] = [
  {
    plugin: "framegen",
    name: "Frame Generation",
    text: (
      <>
        shows extra frames between the ones the game renders (2×, 3× or an automatic multiplier), with Kettle's
        own engine: nothing to buy or install. The base frame rate is capped automatically: leave Steam's frame limit
        off for these games.
      </>
    ),
  },
  {
    plugin: "upscaling",
    name: "Upscaling",
    text: (
      <>
        renders the game at a lower resolution and scales it up: FSR 1 through gamescope for any game, or Snapdragon GSR
        2, Arm ASR or FSR 2.2 in place of a game's own DLSS, FSR 2+ or XeSS.
      </>
    ),
  },
  {
    plugin: "game-settings",
    name: "Game Settings",
    text: (
      <>
        sets how a Windows game runs: the Proton version and FEX, DXVK, vkd3d and Turnip options, with known good
        settings other players have shared from Kettle's game database.
      </>
    ),
  },
  {
    plugin: "power",
    name: "Power",
    text: (
      <>
        shows power use and temperatures live, and sets the fan and CPU limits per game, and the battery charge limit.
      </>
    ),
  },
  {
    plugin: "crash",
    name: "Crash Reports",
    text: <>lists what crashed (a game, Game Mode or the GPU) with the details, kept on the device and never sent.</>,
  },
  { plugin: "screens", name: "Screens", text: <>turns the bottom screen on or off and sets its own brightness.</> },
];

function GameModePage({ f }: { f: Features }) {
  return (
    <Text>
      <h2 style={{ marginTop: 0 }}>Kettle in Game Mode</h2>
      <p>
        Open the Quick Access menu (the <b>…</b> button) and the plug icon. The per-game panels open on the running game,
        and can set up any installed game before you launch it. Everything is off until you turn it on for a game, and
        settings are kept when you turn it off again.
      </p>
      {TOOLS.filter((t) => f.plugins.includes(t.plugin)).map((t) => (
        <p key={t.plugin}>
          <b>{t.name}</b> {t.text}
        </p>
      ))}
    </Text>
  );
}

function RemotePage() {
  const [s, refresh] = usePoll(sshStatus, 3000);
  const [busy, setBusy] = useState(false);
  const toggle = (on: boolean) => {
    setBusy(true);
    act(() => setSsh(on), on ? "Couldn't turn on the SSH server" : "Couldn't turn off the SSH server").finally(() => {
      setBusy(false);
      refresh();
    });
  };
  return (
    <>
      <Text>
        <h2 style={{ marginTop: 0 }}>Remote access</h2>
        <p>
          An SSH server lets you log in to this device from another computer on your network, for copying files or using
          a terminal. Turn it on only when you need it, and change the password first (in the desktop): anyone on the
          network who knows it can log in.
        </p>
      </Text>
      {s && (
        <div style={{ maxWidth: "720px" }}>
          <ToggleField
            label="SSH server"
            checked={s.active}
            disabled={busy}
            onChange={toggle}
            description={
              <div style={small}>
                {!s.active
                  ? "Off. Nothing on the network can log in to this device."
                  : s.addresses.length > 0
                    ? `On. From another computer: ${s.addresses.map((a) => `ssh ${s.user}@${a}`).join(" or ")}`
                    : "On. Connect to a network to log in from another computer."}
                <br />
                {s.enabled
                  ? s.active
                    ? "It's set to start with the device. To change that, use Kettle Welcome in the desktop."
                    : <span style={red}>It starts again with the device. To keep it off, use Kettle Welcome in the desktop.</span>
                  : s.active
                    ? "Turned on here, it stays on until the device restarts. To have it on at every start, use Kettle Welcome in the desktop."
                    : null}
              </div>
            }
          />
        </div>
      )}
    </>
  );
}

const CONTROLS =
  "Left stick: pointer · Right stick: scroll · A / R2: click · B / L2: right click · R1 (held): precise pointer · R3: middle click · X / Home: on-screen keyboard · Y: Enter · D-pad: arrow keys · L1: Escape · Start: application menu · Select: Overview";

function DesktopPage() {
  return (
    <>
      <Text>
        <h2 style={{ marginTop: 0 }}>Desktop mode</h2>
        <p>
          A Plasma desktop, for everything Game Mode doesn't do. Kettle Welcome opens there with its own guide. Switch from
          the power menu or below; the desktop's <b>Return to Gaming Mode</b> icon brings you back.
        </p>
      </Text>
      <Heading>Done in the desktop</Heading>
      <Text>
        <ul style={{ margin: 0, paddingLeft: "20px" }}>
          <li>Changing your password, in Kettle Welcome &gt; Setup.</li>
          <li>Installing Kettle to the internal storage, next to Android, with the Kettle Installer.</li>
          <li>Games from Epic, GOG and Amazon (Heroic Games Launcher) and other Windows games (Lutris).</li>
          <li>Android games from Google Play, and apps that need a mouse.</li>
        </ul>
      </Text>
      <div style={{ maxWidth: "720px" }}>
        <ButtonItem layout="below" onClick={() => SteamClient.System.SwitchToDesktop()}>
          Switch to Desktop
        </ButtonItem>
      </div>
      <Heading>Controls</Heading>
      <Text>
        <p>
          The controller drives the mouse and keyboard there; hold <b>Select + Start</b> to hand it to a game started from
          the desktop, and again to take it back.
        </p>
        <p style={small}>{CONTROLS}</p>
      </Text>
    </>
  );
}

let loaded: Features | null = null; // features(), asked once
const NONE: Features = { plugins: [], extras: false, android: false, files: "/" };

// SidebarNavigation reports each tab as a route under ROUTE (as Decky's own settings do), which is
// why that route isn't exact. The pages are built once per set of features, so the sidebar isn't
// rebuilt on every render.
function Page() {
  const [f, setF] = useState<Features | null>(loaded);
  useEffect(() => {
    if (!loaded) features().then((v) => setF((loaded = v))).catch(() => setF(NONE));
  }, []);
  const pages = useMemo(() => {
    const ft = f ?? NONE;
    return [
      { title: "Welcome", route: `${ROUTE}/welcome`, icon: <FaMugHot />, content: <WelcomePage f={ft} /> },
      { title: "Kettle in Game Mode", route: `${ROUTE}/game-mode`, icon: <FaGamepad />, content: <GameModePage f={ft} /> },
      { title: "Gaming Extras", route: `${ROUTE}/extras`, icon: <FaDownload />, content: <ExtrasPage flatpak={ft.extras} /> },
      ...(ft.android
        ? [{ title: "Android games", route: `${ROUTE}/android`, icon: <FaAndroid />, content: <AndroidPage files={ft.files} /> }]
        : []),
      { title: "Remote access", route: `${ROUTE}/remote`, icon: <FaNetworkWired />, content: <RemotePage /> },
      { title: "Desktop mode", route: `${ROUTE}/desktop`, icon: <FaDesktop />, content: <DesktopPage /> },
      { title: "Reset", route: `${ROUTE}/reset`, icon: <FaUndo />, content: <ResetPage /> },
    ];
  }, [f]);
  if (!f) return null;
  return (
    <div style={{ marginTop: "40px", height: "calc(100% - 40px)" }}>
      <SidebarNavigation title="Welcome" showTitle pages={pages} />
    </div>
  );
}

function Content() {
  const [s] = usePoll(status, 2000);
  return (
    <>
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={openWelcome}>
            Open Welcome
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => {
              Navigation.CloseSideMenus();
              go("extras");
            }}
          >
            Gaming Extras
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      {s && (
        <PanelSection title="Downloads">
          <Setup s={s} Row={PanelSectionRow} />
        </PanelSection>
      )}
    </>
  );
}

// Runs fn once, when someone is signed in to Steam (at once if already). Plugins load before
// Steam's first-time setup and sign-in: opening the welcome page then took Steam off its setup
// pages (language, network, time zone), and it went straight on to sign-in after. Steam's UI
// has no reliable signed-in state (App.m_CurrentUser is set before sign-in, and the login state
// numbers RegisterForLoginStateChange reports don't match @decky/ui's ELoginState on this
// client), so the backend answers from Steam's list of accounts that have signed in.
function whenSignedIn(fn: () => void): () => void {
  let done = false;
  let asking = false;
  const check = () => {
    if (done || asking) return;
    asking = true;
    signedIn()
      .then((yes) => {
        if (!yes || done) return;
        done = true;
        stop();
        fn();
      })
      .catch(() => {})
      .finally(() => (asking = false));
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
    addDesktop().catch((e) => console.error("Welcome: adding the Desktop to Steam failed", e));
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
