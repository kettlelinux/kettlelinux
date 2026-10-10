// The Welcome window's tour: a page per part of Kettle in Game Mode, each with screenshots of it
// (assets/, taken on an Odin 2 Portal), what it does, buttons that open it, and a Next button to
// the following page. A page about a plugin this device doesn't have isn't shown.
import { ButtonItem, Focusable, Navigation, QuickAccessTab } from "@decky/ui";
import { callable } from "@decky/api";
import { ReactNode, useEffect, useState } from "react";
import { Heading, Text, small } from "./ui";
import plugins from "../assets/plugins.jpg";
import gsCompat from "../assets/gs-compat.jpg";
import gsPerf from "../assets/gs-perf.jpg";
import gsUpscale from "../assets/gs-upscale.jpg";
import gsFramegen from "../assets/gs-framegen.jpg";
import gsExtras from "../assets/gs-extras.jpg";
import stores from "../assets/stores.jpg";
import dsPower from "../assets/ds-power.jpg";
import dsLights from "../assets/ds-lights.jpg";
import dsGyro from "../assets/ds-gyro.jpg";
import diag from "../assets/diag.jpg";

// plugins: Kettle's Decky plugins on this device ("game-settings", "stores", ...)
export type Features = { plugins: string[]; android: boolean };

export const ROUTE = "/kettle-welcome";
export const go = (page: string) => Navigation.Navigate(`${ROUTE}/${page}`);
// a page of Steam's Settings, the way Steam's own menus open one (not in @decky/ui's typings)
const steamSettings = (page: string) => (SteamClient.URL as any).ExecuteSteamURL(`steam://open/settings/${page}`);
// the library's Desktop entry (desktop.ts adds it): Desktop Mode's Plasma nested in Game Mode
const desktopAppid = callable<[], number | null>("desktop_appid");

// Quick Access on one of Decky's plugins (Decky's own state: no API for it, so only if it's there)
function openPanel(name: string) {
  Navigation.OpenQuickAccessMenu(QuickAccessTab.Decky);
  try {
    (window as any).DeckyPluginLoader?.deckyState?.setActivePlugin(name);
  } catch {
    // the Decky tab opens on its list instead
  }
}

const page = { maxWidth: "760px", paddingBottom: "24px" };
const shot = { borderRadius: "8px", boxShadow: "0 4px 18px rgba(0, 0, 0, 0.5)", display: "block" };

// A screenshot of a Quick Access panel beside what it's for. Focusable, so the D-pad scrolls the
// page down to it.
function Feature({ img, title, children }: { img: string; title: string; children: ReactNode }) {
  return (
    <Focusable onActivate={() => {}} style={{ display: "flex", gap: "20px", alignItems: "flex-start", margin: "16px 0" }}>
      <img src={img} style={{ ...shot, width: "230px", flexShrink: 0 }} />
      <div style={{ lineHeight: "22px" }}>
        <h3 style={{ margin: "4px 0 6px" }}>{title}</h3>
        {children}
      </div>
    </Focusable>
  );
}

// A screenshot of a whole window, as wide as the page
function Wide({ img, caption }: { img: string; caption: string }) {
  return (
    <Focusable onActivate={() => {}} style={{ margin: "16px 0" }}>
      <img src={img} style={{ ...shot, width: "100%" }} />
      <div style={{ ...small, marginTop: "6px", opacity: 0.8 }}>{caption}</div>
    </Focusable>
  );
}

function Buttons({ children }: { children: ReactNode }) {
  return <Focusable style={{ marginTop: "8px" }}>{children}</Focusable>;
}

const Button = ({ label, description, onClick }: { label: string; description?: string; onClick: () => void }) => (
  <ButtonItem layout="below" description={description} onClick={onClick}>
    {label}
  </ButtonItem>
);

// the tour's pages, in order: route, sidebar title, and whether this device has what it shows
export type Stop = { id: string; title: string; has: (f: Features) => boolean };
export const STOPS: Stop[] = [
  { id: "welcome", title: "Welcome", has: () => true },
  { id: "games", title: "Your games", has: (f) => f.plugins.includes("game-settings") },
  { id: "upscaling", title: "Upscaling", has: (f) => f.plugins.includes("game-settings") },
  { id: "framegen", title: "Frame Gen", has: (f) => f.plugins.includes("game-settings") },
  { id: "stores", title: "Game Stores", has: (f) => f.plugins.includes("stores") },
  { id: "device", title: "Your device", has: (f) => f.plugins.includes("device-settings") },
  { id: "desktop", title: "Desktop mode", has: () => true },
];

function Next({ from, f }: { from: string; f: Features }) {
  const stops = STOPS.filter((s) => s.has(f));
  const next = stops[stops.findIndex((s) => s.id === from) + 1];
  if (!next) return null;
  return <Button label={`Next: ${next.title}`} onClick={() => go(next.id)} />;
}

export function WelcomePage({ f }: { f: Features }) {
  return (
    <div style={page}>
      <Text>
        <h1 style={{ margin: "0 0 8px", fontSize: "32px" }}>Welcome to Kettle Linux</h1>
        <p>
          Kettle is a SteamOS-style system for Snapdragon handhelds: Valve's arm64 Steam client with Game Mode, a Plasma
          desktop, and Windows games through Proton ARM64. This tour shows what Kettle adds to Game Mode, a page at a
          time; it's here whenever you want it, in Quick Access under Welcome.
        </p>
      </Text>
      <Feature img={plugins} title="Everything is in Quick Access">
        <p>
          Press the <b>…</b> button for Quick Access, then the <b>plug icon</b>. Kettle's own tools are listed there: Game
          Settings, Game Stores, Device Settings, Crash Reports and this Welcome.
        </p>
        <p style={small}>Crash Reports keeps what crashed (a game, Game Mode or the GPU) on the device; nothing is sent.</p>
      </Feature>
      <Heading>Get started</Heading>
      <Buttons>
        <Button label="Connect to Wi-Fi" description="Pick a network in Steam's Internet settings." onClick={() => steamSettings("internet")} />
        <Button
          label="Change your password"
          description={`The account starts with the password "kettle". Change it in the desktop: it also protects remote logins (SSH) and administrator tasks.`}
          onClick={() => go("desktop")}
        />
        <Next from="welcome" f={f} />
      </Buttons>
    </div>
  );
}

export function GamesPage({ f }: { f: Features }) {
  return (
    <div style={page}>
      <Text>
        <p>
          <b>Game Settings</b> sets up each game, a tab each. It opens on the game that's running, and can set up any
          installed game before you start it. Pick <b>All games</b> at the top for the settings every game without its
          own uses.
        </p>
      </Text>
      <Feature img={gsCompat} title="Compat: how a Windows game runs">
        <p>
          The Proton version and FEX, DXVK, vkd3d and Turnip options, with presets for the engine the game is built on.
          <b> Known good settings</b> other players shared in Kettle's game database are a button away, and you can share
          yours once a game plays well.
        </p>
      </Feature>
      <Feature img={gsPerf} title="Perf: fan, CPU and Auto TDP">
        <p>
          A fan curve or a fixed speed, CPU core and clock limits, and the screen's refresh rate, for one game or all.
          <b> Auto TDP</b> holds Steam's frame rate limit on the lowest clocks that keep it, for longer battery life.
        </p>
        <p style={small}>The TDP limit, performance profile and GPU clock stay in Steam's own Performance panel.</p>
      </Feature>
      <Feature img={gsExtras} title="Extras: more Protons, AMD FSR 3.1">
        <p>
          GE-Proton and Proton-CachyOS, the community Protons with their own game fixes, and AMD's FSR 3.1 for the
          Upscaling tab: each downloaded from its own project and checked before it's installed.
        </p>
      </Feature>
      <Buttons>
        <Button label="Open Game Settings" onClick={() => openPanel("Game Settings")} />
        <Next from="games" f={f} />
      </Buttons>
    </div>
  );
}

export function UpscalingPage({ f }: { f: Features }) {
  return (
    <div style={page}>
      <Text>
        <p>
          Game Settings' Upscale tab, for games that need more speed: the game renders at a lower resolution and is scaled
          up to the screen. Off until you turn it on for a game.
        </p>
      </Text>
      <Feature img={gsUpscale} title="Render lower, show sharper">
        <p>
          <b>FSR 1</b> through gamescope works with any game: it renders at a lower resolution and gamescope scales it up.
          For games with DLSS, FSR 2+ or XeSS, <b>OptiScaler</b> runs Snapdragon GSR 2, Arm ASR or FSR 2.2 in their place,
          or AMD's FSR 3.1 from the Extras tab.
        </p>
      </Feature>
      <Buttons>
        <Button label="Open Game Settings" onClick={() => openPanel("Game Settings")} />
        <Next from="upscaling" f={f} />
      </Buttons>
    </div>
  );
}

export function FrameGenPage({ f }: { f: Features }) {
  return (
    <div style={page}>
      <Text>
        <p>
          Game Settings' Frame Gen tab: smoother motion from the frames the game already renders. Off until you turn it on
          for a game, and its settings are kept when you turn it off.
        </p>
      </Text>
      <Feature img={gsFramegen} title="More frames on screen">
        <p>
          Kettle's own frame generation shows extra frames between the ones the game renders: 2×, 3×, or the fewest that
          fill the display. Its base frame rate is capped automatically, so leave Steam's frame limit off for these
          games.
        </p>
      </Feature>
      <Buttons>
        <Button label="Open Game Settings" onClick={() => openPanel("Game Settings")} />
        <Next from="framegen" f={f} />
      </Buttons>
    </div>
  );
}

export function StoresPage({ f }: { f: Features }) {
  const open = (tab: string) => Navigation.Navigate(`/kettle-stores/${tab}`);
  return (
    <div style={page}>
      <Text>
        <p>
          Your games from other stores, in your Steam library. Sign in to <b>Epic Games</b>, <b>GOG</b> and{" "}
          <b>Amazon Games</b>, then install and update their games here; each is added to Steam with Proton, and the
          desktop's Heroic shares the same sign-ins and installs. <b>Battle.net</b> is added the same way.
        </p>
      </Text>
      <Wide img={stores} caption="The Game Stores window, open from Quick Access > Game Stores." />
      <Text>
        <p>
          <b>Flathub</b> has hundreds of apps built for ARM64, emulators and game streaming apps among them (RetroArch,
          Dolphin, PPSSPP, Moonlight, ...), added to Steam as they install.
          {f.android && (
            <>
              {" "}
              <b>Android</b> games come from F-Droid or an APK file, and run like any other game.
            </>
          )}
        </p>
      </Text>
      <Buttons>
        <Button label="Open Game Stores" onClick={() => open("epic")} />
        <Button label="Browse Flathub" onClick={() => open("flathub")} />
        {f.android && <Button label="Add Android games" onClick={() => open("android")} />}
        <Next from="stores" f={f} />
      </Buttons>
    </div>
  );
}

export function DevicePage({ f }: { f: Features }) {
  return (
    <div style={page}>
      <Text>
        <p>
          <b>Device Settings</b> is the device's own settings, a tab each. A tab for something your device doesn't have
          (motion sensors, a second screen) isn't shown.
        </p>
      </Text>
      <Feature img={dsPower} title="Power: battery and screen">
        <p>
          A <b>charge limit</b> that keeps the battery from sitting at 100%, the charge speed, and the screen's
          refresh rate: Auto lets Steam's frame limit pick one it divides evenly.
        </p>
      </Feature>
      <Feature img={dsLights} title="Lights">
        <p>
          The lights around the sticks and by the power button: a color, the battery level, breathe or rainbow, and their
          brightness. They stay dark while the device sleeps.
        </p>
      </Feature>
      <Feature img={dsGyro} title="Gyro, and System">
        <p>
          The motion sensors for Steam Input's gyro controls, on while a game runs to save power. <b>System</b> holds
          what Kettle starts up in, the SSH server for logging in from another computer, resetting the device, and, where the ROCKNIX ABL starts Kettle, its updates.
        </p>
      </Feature>
      <Wide img={diag} caption="Diagnostics, at the bottom of Device Settings: power use, temperatures and everything about the device." />
      <Buttons>
        <Button label="Open Device Settings" onClick={() => openPanel("Device Settings")} />
        <Button label="Open Diagnostics" onClick={() => Navigation.Navigate("/kettle-device-settings/diagnostics/now")} />
        <Next from="device" f={f} />
      </Buttons>
    </div>
  );
}

const CONTROLS =
  "Left stick: pointer · Right stick: scroll · A / R2: click · B / L2: right click · R1 (held): precise pointer · R3: middle click · X / Home: on-screen keyboard · Y: Enter · D-pad: arrow keys · L1: Escape · Start: application menu · Select: Overview";

export function DesktopPage() {
  const [nested, setNested] = useState<number | null>(null);
  useEffect(() => {
    desktopAppid().then(setNested).catch(() => {});
  }, []);
  return (
    <div style={page}>
      <Text>
        <p>
          A Plasma desktop, for everything Game Mode doesn't do. Kettle Welcome opens there with its own guide. There are
          two ways in.
        </p>
      </Text>
      <Heading>The desktop in Game Mode</Heading>
      <Text>
        <p>
          <b>Desktop</b> in your Steam library starts the same desktop inside Game Mode: its settings, apps and files,
          with nothing to switch. Steam keeps running behind it, so the Steam button and Quick Access still work, and{" "}
          <b>Exit Game</b> (or the desktop's <b>Return to Gaming Mode</b>) closes it. Best for a quick look at a file or
          an app.
        </p>
      </Text>
      {nested !== null && (
        <Buttons>
          <Button label="Start the Desktop" onClick={() => SteamClient.Apps.RunGame(String(nested), "", -1, 100)} />
        </Buttons>
      )}
      <Heading>Desktop Mode</Heading>
      <Text>
        <p>
          Switching to Desktop Mode closes Game Mode and gives the desktop the whole device, as on a Steam Deck. Switch from
          the power menu or below; the desktop's <b>Return to Gaming Mode</b> icon brings you back.
        </p>
      </Text>
      <Buttons>
        <Button label="Switch to Desktop Mode" onClick={() => SteamClient.System.SwitchToDesktop()} />
      </Buttons>
      <Heading>Done in the desktop</Heading>
      <Text>
        <ul style={{ margin: 0, paddingLeft: "20px" }}>
          <li>Changing your password, in Kettle Welcome &gt; Setup.</li>
          <li>Installing Kettle to the internal storage, next to Android, with the Kettle Installer.</li>
          <li>Games from other launchers (Heroic Games Launcher, Lutris).</li>
          <li>Android games from Google Play, and apps that need a mouse.</li>
        </ul>
      </Text>
      <Heading>Controls</Heading>
      <Text>
        <p>
          The controller drives the mouse and keyboard in both, with the same controls. In Desktop Mode, hold{" "}
          <b>Select + Start</b> to hand it to a game started from the desktop, and again to take it back.
        </p>
        <p style={small}>{CONTROLS}</p>
      </Text>
    </div>
  );
}
