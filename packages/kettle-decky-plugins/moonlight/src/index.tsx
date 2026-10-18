// Moonlight: games streamed from a PC running Sunshine or Apollo (main.py). The Quick Access
// panel shows the stream that's running (end it, the controller combos, a warning when Steam's
// frame limit is below the stream's frame rate, which drops every other frame) and the paired
// PCs; the Moonlight page (page.tsx) finds and pairs PCs, and each PC's page (host.tsx) has its
// games and how it streams.
import { ButtonItem, Navigation, PanelSection, PanelSectionRow, Router, staticClasses } from "@decky/ui";
import { definePlugin, routerHook } from "@decky/api";
import { useEffect, useState } from "react";
import { FaDesktop } from "react-icons/fa";
import { MdCastConnected } from "react-icons/md";
import { fpsLimit, hosts, settings, streams } from "./api";
import { HostPage } from "./host";
import { Page, status } from "./page";
import { overview } from "./shortcuts";
import { HOST_ROUTE, QUIT_COMBO, ROUTE, STATS_COMBO, dim, openHost, openMoonlight, small, usePoll } from "./ui";

type Running = { appid: number; uuid: string; app: string; fps: number; limit: number };

function useRunningStream(): Running | null {
  const [r, setR] = useState<Running | null>(null);
  useEffect(() => {
    let live = true;
    const appid = Number(Router.MainRunningApp?.appid ?? 0);
    if (!appid) return;
    (async () => {
      const s = (await streams())[String(appid)];
      if (!s || !live) return;
      const [info, limit] = await Promise.all([settings(s.uuid), fpsLimit()]);
      if (live) setR({ appid, ...s, fps: info.effective.fps, limit });
    })().catch(() => {});
    return () => {
      live = false;
    };
  }, []);
  return r;
}

function endStream(appid: number) {
  const gameid = overview(appid)?.m_gameid;
  if (gameid) SteamClient.Apps.TerminateApp(gameid, false);
  Navigation.CloseSideMenus();
}

function Content() {
  const running = useRunningStream();
  const [list] = usePoll(() => hosts(false), 0);
  const paired = (list ?? []).filter((h) => h.paired);
  return (
    <>
      {running && (
        <PanelSection title={`Streaming ${running.app}`}>
          {running.limit > 0 && running.limit < running.fps && (
            <PanelSectionRow>
              <div style={{ ...small, color: "#e0b341" }}>
                Steam's frame limit ({running.limit} fps) is below the stream's {running.fps} fps, so frames are dropped. Set
                Framerate Limit to Off in Performance.
              </div>
            </PanelSectionRow>
          )}
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => endStream(running.appid)}>
              End stream
            </ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => openHost(running.uuid, "settings")}>
              Stream settings
            </ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            <div style={{ ...small, ...dim }}>
              <div>End: {QUIT_COMBO}</div>
              <div>Stats: {STATS_COMBO}</div>
            </div>
          </PanelSectionRow>
        </PanelSection>
      )}
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={openMoonlight}>
            {paired.length ? "Open Moonlight" : "Find a PC to stream from"}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      {paired.length > 0 && (
        <PanelSection title="Your PCs">
          {paired.map((h) => (
            <PanelSectionRow key={h.uuid}>
              <ButtonItem layout="below" icon={<FaDesktop />} description={status(h)[0]} onClick={() => openHost(h.uuid)}>
                {h.name}
              </ButtonItem>
            </PanelSectionRow>
          ))}
        </PanelSection>
      )}
    </>
  );
}

export default definePlugin(() => {
  routerHook.addRoute(ROUTE, Page, { exact: true });
  routerHook.addRoute(`${HOST_ROUTE}/:uuid`, HostPage);
  return {
    name: "Moonlight",
    titleView: <div className={staticClasses.Title}>Moonlight</div>,
    content: <Content />,
    icon: <MdCastConnected />,
    onDismount: () => {
      routerHook.removeRoute(ROUTE);
      routerHook.removeRoute(`${HOST_ROUTE}/:uuid`);
    },
  };
});
