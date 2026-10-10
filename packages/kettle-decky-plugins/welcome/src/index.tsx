import { ButtonItem, Navigation, PanelSection, PanelSectionRow, SidebarNavigation, staticClasses } from "@decky/ui";
import { callable, definePlugin, routerHook } from "@decky/api";
import { ReactElement, useEffect, useMemo, useState } from "react";
import { FaCog, FaDesktop, FaExpandArrowsAlt, FaGamepad, FaHandSparkles, FaLayerGroup, FaMugHot, FaStore, FaTabletAlt } from "react-icons/fa";
import { applyGameFixes } from "./fixes";
import { addDesktop } from "./desktop";
import { DesktopPage, DevicePage, Features, FrameGenPage, GamesPage, ROUTE, STOPS, ScreenPage, StoresPage, UpscalingPage, WelcomePage } from "./tour";

const firstRun = callable<[], boolean>("first_run");
const signedIn = callable<[], boolean>("signed_in");
const claimDefault = callable<[name: string], boolean>("claim_default");
const features = callable<[], Features>("features");

const openWelcome = () => {
  Navigation.CloseSideMenus();
  Navigation.Navigate(`${ROUTE}/welcome`);
};

const ICONS: Record<string, ReactElement> = {
  welcome: <FaMugHot />,
  games: <FaGamepad />,
  upscaling: <FaExpandArrowsAlt />,
  framegen: <FaLayerGroup />,
  stores: <FaStore />,
  device: <FaCog />,
  screen: <FaTabletAlt />,
  desktop: <FaDesktop />,
};
const PAGES: Record<string, (p: { f: Features }) => ReactElement> = {
  welcome: WelcomePage,
  games: GamesPage,
  upscaling: UpscalingPage,
  framegen: FrameGenPage,
  stores: StoresPage,
  device: DevicePage,
  screen: ScreenPage,
  desktop: DesktopPage,
};

let loaded: Features | null = null; // features(), asked once
const NONE: Features = { plugins: [], android: false, bottom_screen: false };

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
    return STOPS.filter((s) => s.has(ft)).map((s) => {
      const P = PAGES[s.id];
      return { title: s.title, route: `${ROUTE}/${s.id}`, icon: ICONS[s.id], content: <P f={ft} /> };
    });
  }, [f]);
  if (!f) return null;
  return (
    <div style={{ marginTop: "40px", height: "calc(100% - 40px)" }}>
      <SidebarNavigation title="Welcome" showTitle pages={pages} />
    </div>
  );
}

function Content() {
  return (
    <PanelSection>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={openWelcome}>
          Open Welcome
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
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
