// Game Stores: Epic Games, GOG and Amazon Games in Game Mode, Flathub's ARM64 apps and Android
// games (main.py).
// The Quick Access panel shows the accounts and the running download and opens the Game Stores
// page (library.tsx); each game has its own page (game.tsx). The listeners here run while Game
// Mode does: leaving Steam's browser after a sign-in, and adding a finished install to Steam
// (shortcuts.ts).
import { ButtonItem, Navigation, PanelSection, PanelSectionRow, staticClasses } from "@decky/ui";
import { addEventListener, definePlugin, removeEventListener, routerHook, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { FaStore } from "react-icons/fa";
import { Job, NAMES, STORES, Source, Store, pending, status } from "./api";
import { GamePage } from "./game";
import { Page } from "./library";
import { addShortcut } from "./shortcuts";
import { androidInfo } from "./android";
import { GAME_ROUTE, JobProgress, ROUTE, act, openGame, openStores, signIn, usePoll } from "./ui";

function Content() {
  const [s] = usePoll(status, 2000);
  const [android, setAndroid] = useState(false);
  useEffect(() => {
    androidInfo().then((a) => setAndroid(a.available)).catch(() => {});
  }, []);
  return (
    <>
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => openStores(STORES.find((st) => s?.users[st]) ?? "accounts")}>
            Open Game Stores
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => openStores("flathub")}>
            Browse Flathub
          </ButtonItem>
        </PanelSectionRow>
        {android && (
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => openStores("android")}>
              Android games
            </ButtonItem>
          </PanelSectionRow>
        )}
        {s?.job && (
          <PanelSectionRow>
            <div onClick={() => openStores("downloads")}>
              <JobProgress job={s.job} />
            </div>
          </PanelSectionRow>
        )}
        {s && s.queue.length > 0 && (
          <PanelSectionRow>
            <div style={{ fontSize: "12px" }}>{s.queue.length} more waiting</div>
          </PanelSectionRow>
        )}
      </PanelSection>
      {s && (
        <PanelSection title="Accounts">
          {STORES.map((st) => (
            <PanelSectionRow key={st}>
              <ButtonItem
                layout="below"
                description={s.users[st] ? `Signed in as ${s.users[st]}` : undefined}
                onClick={() => (s.users[st] ? openStores(st) : act(() => signIn(st), "Signing in failed"))}
              >
                {s.users[st] ? NAMES[st] : `Sign in to ${NAMES[st]}`}
              </ButtonItem>
            </PanelSectionRow>
          ))}
        </PanelSection>
      )}
    </>
  );
}

// Adds a finished install to Steam, and says so
async function added(store: Source, id: string, title: string) {
  await addShortcut(store, id);
  toaster.toast({
    title: `${title} is installed`,
    body: "It's in your Steam library. Select to open its page.",
    icon: <FaStore />,
    onClick: () => openGame(store, id),
  });
}

export default definePlugin(() => {
  routerHook.addRoute(ROUTE, Page);
  routerHook.addRoute(`${GAME_ROUTE}/:store/:id`, GamePage, { exact: true });

  const onLogin = (store: Store, ok: boolean, error: string) => {
    if (ok) {
      Navigation.NavigateBack(); // out of Steam's browser
      toaster.toast({ title: "Game Stores", body: `Signed in to ${NAMES[store]}.` });
    } else toaster.toast({ title: "Game Stores", body: `Signing in to ${NAMES[store]} failed: ${error}` });
  };
  const onJob = (job: Job, ok: boolean, error: string) => {
    if (!ok) toaster.toast({ title: "Game Stores", body: `${job.kind === "update" ? "Updating" : "Installing"} ${job.title} failed: ${error}` });
    else if (job.kind === "update") toaster.toast({ title: "Game Stores", body: `${job.title} is up to date.` });
    else act(() => added(job.store, job.id, job.title), `Adding ${job.title} to Steam failed`);
  };
  addEventListener("login", onLogin);
  addEventListener("job", onJob);
  // installs that finished while Game Mode wasn't running
  pending()
    .then((list) => list.forEach((p) => act(() => addShortcut(p.store, p.id), "Adding a game to Steam failed")))
    .catch(() => {});

  return {
    name: "Game Stores",
    titleView: <div className={staticClasses.Title}>Game Stores</div>,
    content: <Content />,
    icon: <FaStore />,
    onDismount: () => {
      removeEventListener("login", onLogin);
      removeEventListener("job", onJob);
      routerHook.removeRoute(ROUTE);
      routerHook.removeRoute(`${GAME_ROUTE}/:store/:id`);
    },
  };
});
