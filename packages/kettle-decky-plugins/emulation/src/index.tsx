// Emulation: retro games in Game Mode (main.py). The Quick Access panel: while a game runs, the
// standard controls as buttons (the very keys the Select hotkeys send, through emu-run's keys
// bridge), the cheat sheet and this game's emulator; otherwise the library's size, a card or stick
// with games on it to import, and the way into the Emulation page (page.tsx) or, the first time,
// Get started (start.tsx). The library is synced on load and whenever the ROMs change (a card,
// the inbox, an import, an upload).
import { ButtonItem, DialogButton, DropdownItem, Focusable, Navigation, PanelSection, PanelSectionRow, staticClasses } from "@decky/ui";
import { addEventListener, definePlugin, removeEventListener, routerHook, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { FaGamepad } from "react-icons/fa";
import { HotkeyAction, Job, Media, Running, hotkey, importStart, importStatus, media, overview, running, setGameChoice } from "./api";
import { Page } from "./page";
import { StartPage } from "./start";
import { onSync, sync, syncing } from "./sync";
import { ControlsTable, ROUTE, START_ROUTE, act, dim, openEmulation, openStart, plural, small, usePoll } from "./ui";

const BUTTONS: [HotkeyAction, string][] = [
  ["save_state", "Save state"],
  ["load_state", "Load state"],
  ["menu", "Menu"],
  ["fast_forward", "Fast-forward"],
  ["slot_down", "Slot −"],
  ["slot_up", "Slot +"],
  ["rewind", "Rewind"],
  ["screenshot", "Screenshot"],
];

// The keys go to the window that has the focus: Quick Access closes first, and the key is sent
// once the game has the focus back
const FOCUS_BACK = 450; // ms

function press(a: HotkeyAction) {
  act(async () => {
    Navigation.CloseSideMenus();
    await new Promise((r) => setTimeout(r, FOCUS_BACK));
    if (!(await hotkey(a))) throw new Error("the game isn't listening (it started before Emulation was set up?)");
  }, "That didn't reach the game");
}

function RunningPanel({ r, face }: { r: Running; face: "xbox" | "nintendo" }) {
  const choices = [{ data: "", label: "The system's emulator" }, ...r.emulators.filter((e) => e.installed).map((e) => ({ data: e.id, label: e.name }))];
  return (
    <>
      <PanelSection title={r.title}>
        <PanelSectionRow>
          <div style={{ ...small, ...dim, marginBottom: "6px" }}>{r.emulator_name}</div>
        </PanelSectionRow>
        {r.bridge ? (
          <PanelSectionRow>
            <Focusable style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px" }}>
              {/* melonDS has no screenshot key (F8 is RetroArch's, PPSSPP's and Dolphin's) */}
              {BUTTONS.filter(([a]) => (a !== "rewind" || r.rewind) && (a !== "screenshot" || r.emulator !== "melonds")).map(([a, label]) => (
                <DialogButton key={a} style={{ minWidth: 0, padding: "8px 4px" }} onClick={() => press(a)}>
                  {label}
                </DialogButton>
              ))}
              {/* only the melonDS binary has a swap key (F9); RetroArch's DS core doesn't */}
              {r.emulator === "melonds" && (
                <DialogButton style={{ minWidth: 0, padding: "8px 4px" }} onClick={() => press("swap_screens")}>
                  Swap screens
                </DialogButton>
              )}
              <DialogButton style={{ minWidth: 0, padding: "8px 4px" }} onClick={() => press("quit")}>
                Quit
              </DialogButton>
            </Focusable>
          </PanelSectionRow>
        ) : (
          <PanelSectionRow>
            <div style={small}>The buttons need the game to be started again. The Select hotkeys work.</div>
          </PanelSectionRow>
        )}
        {r.id && choices.length > 2 && (
          <PanelSectionRow>
            <DropdownItem
              label="Emulator for this game"
              description="From the next start"
              rgOptions={choices}
              selectedOption={r.game_choice}
              onChange={(o) => act(() => setGameChoice(r.id!, o.data || null), "Saving failed")}
            />
          </PanelSectionRow>
        )}
      </PanelSection>
      <PanelSection title="Controls">
        <PanelSectionRow>
          <ControlsTable face={face} compact />
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

function ImportOffer({ m, onStarted }: { m: Media; onStarted: () => void }) {
  if (m.set_up) return null;
  return (
    <PanelSectionRow>
      <ButtonItem
        layout="below"
        description={[m.games_total && plural(m.games_total, "game"), m.bios && plural(m.bios, "BIOS file", "BIOS files")].filter(Boolean).join(", ")}
        onClick={() => act(async () => (await importStart(m.path, "copy", "internal"), onStarted()), "Importing failed")}
      >
        Import from {m.label}
      </ButtonItem>
    </PanelSectionRow>
  );
}

function JobRow({ job }: { job: Job }) {
  if (job.state !== "running") return null;
  const pct = job.bytes ? Math.round((100 * (job.bytes_done ?? 0)) / job.bytes) : 0;
  return (
    <PanelSectionRow>
      <div style={small}>
        {job.kind === "inbox" ? "Sorting the inbox" : "Importing"}: {job.done ?? 0} of {job.files ?? 0} files{job.bytes ? ` (${pct}%)` : ""}
        <div style={{ ...dim, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{job.current}</div>
      </div>
    </PanelSectionRow>
  );
}

function Content() {
  const [r] = usePoll(running, 3000);
  const [ov, reloadOv] = usePoll(overview, 0);
  const [cards, reloadCards] = usePoll(media, 0);
  const [job, reloadJob] = usePoll(importStatus, 2000);
  const [busy, setBusy] = useState(syncing());
  useEffect(() => {
    const off = onSync((b) => {
      setBusy(b);
      if (!b) reloadOv();
    });
    const onMedia = () => reloadCards();
    addEventListener("media", onMedia);
    return () => {
      off();
      removeEventListener("media", onMedia);
    };
  }, []);
  if (r && ov) return <RunningPanel r={r} face={ov.face} />;
  const first = ov && !ov.settings.first_run_done;
  return (
    <>
      <PanelSection>
        <PanelSectionRow>
          <div style={small}>
            {ov ? (ov.total ? `${plural(ov.total, "game")} in your library` : "No games yet") : "…"}
            {busy && <span style={dim}> · updating the library…</span>}
          </div>
        </PanelSectionRow>
        {job && <JobRow job={job} />}
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => (first ? openStart() : openEmulation())}>
            {first ? "Get started" : "Open Emulation"}
          </ButtonItem>
        </PanelSectionRow>
        {!first && (
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => openEmulation("add")}>
              Add games
            </ButtonItem>
          </PanelSectionRow>
        )}
      </PanelSection>
      {cards && cards.some((m) => !m.set_up && (m.games_total || m.bios)) && (
        <PanelSection title="On a card or stick">
          {cards.map((m) => (m.games_total || m.bios ? <ImportOffer key={m.path} m={m} onStarted={reloadJob} /> : null))}
        </PanelSection>
      )}
      {ov && (
        <PanelSection title="Controls">
          <PanelSectionRow>
            <ControlsTable face={ov.face} compact />
          </PanelSectionRow>
        </PanelSection>
      )}
    </>
  );
}

// a burst of changes (an import's files) makes one sync
let timer: ReturnType<typeof setTimeout> | undefined;
function soon(ms = 1500) {
  clearTimeout(timer);
  timer = setTimeout(() => sync().catch(() => {}), ms);
}

export default definePlugin(() => {
  const onChanged = () => soon();
  const onMedia = (m: Media) => {
    if (m.set_up) return; // its own Emulation tree: played in place, the sync picks it up
    toaster.toast({
      title: `${m.label}: ${[m.games_total && plural(m.games_total, "game"), m.bios && plural(m.bios, "BIOS file", "BIOS files")].filter(Boolean).join(", ")}`,
      body: "Open Quick Access > Emulation to import them",
    });
  };
  const onError = (e: { message: string }) => toaster.toast({ title: "Can't start the game", body: e.message });
  const onSyncDone = onSync((busy, r) => {
    if (!busy && r && (r.added || r.removed))
      toaster.toast({ title: "Emulation", body: [r.added && `${plural(r.added, "game")} added`, r.removed && `${r.removed} removed`].filter(Boolean).join(", ") });
  });
  addEventListener("roms_changed", onChanged);
  addEventListener("media", onMedia);
  addEventListener("launch_error", onError);
  routerHook.addRoute(START_ROUTE, StartPage, { exact: true });
  routerHook.addRoute(`${ROUTE}/:tab`, Page);
  // Steam's stores are filled a little after the plugin loads
  soon(8000);
  return {
    name: "Emulation",
    titleView: <div className={staticClasses.Title}>Emulation</div>,
    content: <Content />,
    icon: <FaGamepad />,
    onDismount: () => {
      clearTimeout(timer);
      onSyncDone();
      removeEventListener("roms_changed", onChanged);
      removeEventListener("media", onMedia);
      removeEventListener("launch_error", onError);
      routerHook.removeRoute(START_ROUTE);
      routerHook.removeRoute(`${ROUTE}/:tab`);
    },
  };
});
