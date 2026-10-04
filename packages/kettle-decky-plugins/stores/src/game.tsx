// A store game's page: its size, and installing, playing, updating and uninstalling it.
import { ButtonItem, ConfirmModal, Field, Focusable, Navigation, showModal, useParams } from "@decky/ui";
import { useEffect, useState } from "react";
import { Details, Game, GameInfo, NAMES, Store, cancel, details, gameInfo, install, library, size, status, uninstall } from "./api";
import { JobProgress } from "./library";
import { addShortcut, inLibrary, play, removeShortcut } from "./shortcuts";
import { act, dim, small, usePoll } from "./ui";

const date = (d: string) => {
  const t = Date.parse(d);
  return isNaN(t) ? d : new Date(t).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric", timeZone: "UTC" });
};

// The game's summary and facts, under the buttons (focusable, so the controller scrolls to them)
function About({ d, dlc }: { d: Details; dlc: string[] }) {
  const rows: [string, string][] = [
    ["Developer", d.developer],
    ["Publisher", d.publisher],
    ["Released", d.released ? date(d.released) : ""],
    ["Genres", d.genres.join(", ")],
    ["Modes", d.modes.join(", ")],
    ["DLC you own", dlc.join(", ")], // installed with the game
  ];
  if (!d.summary && !rows.some(([, v]) => v)) return null;
  return (
    <Focusable style={{ marginTop: "20px" }}>
      <h3 style={{ margin: "0 0 8px" }}>About</h3>
      {d.summary && (
        <Focusable onActivate={() => {}} style={{ whiteSpace: "pre-line", lineHeight: "22px", marginBottom: "8px" }}>
          {d.summary}
        </Focusable>
      )}
      {rows
        .filter(([, v]) => v)
        .map(([k, v]) => (
          <Field key={k} label={k} focusable bottomSeparator="thick">
            {v}
          </Field>
        ))}
    </Focusable>
  );
}

export function GamePage() {
  const { store, id: raw } = useParams<{ store: Store; id: string }>();
  const id = decodeURIComponent(raw);
  const [game, setGame] = useState<Game | null | undefined>(undefined);
  const [info, setInfo] = useState<GameInfo | null>(null);
  const [about, setAbout] = useState<Details | null>(null);
  const [s] = usePoll(status, 1000);
  const [n, setN] = useState(0);
  const reload = () => setN(n + 1);

  useEffect(() => {
    library(store, false)
      .then((r) => setGame(r.games.find((g) => g.id === id) ?? null))
      .catch(() => setGame(null));
  }, [store, id, n]);
  useEffect(() => {
    gameInfo(store, id).then(setInfo).catch(() => setInfo(null));
  }, [store, id, game?.installed]);
  useEffect(() => {
    details(store, id).then(setAbout).catch(() => setAbout(null));
  }, [store, id]);

  // the download ending (it leaves the job and the queue) shows the game as installed
  const running = s?.job && s.job.store === store && s.job.id === id ? s.job : null;
  const queued = !!s?.queue.some((j) => j.store === store && j.id === id);
  const busy = !!running || queued;
  const [wasBusy, setWasBusy] = useState(false);
  useEffect(() => {
    if (wasBusy && !busy) setTimeout(reload, 1500); // after index.tsx has added the shortcut
    setWasBusy(busy);
  }, [busy]);

  if (game === undefined) return <div style={{ marginTop: "40px", padding: "16px 24px" }}>Loading…</div>;
  if (game === null) return <div style={{ marginTop: "40px", padding: "16px 24px" }}>This game isn't in your {NAMES[store]} library.</div>;

  const update = game.update || !!info?.update;
  const shortcut = game.appid && inLibrary(game.appid) ? game.appid : null;
  const confirmUninstall = () =>
    showModal(
      <ConfirmModal
        strTitle={`Uninstall ${game.title}?`}
        strDescription="The game's files are deleted and it leaves your Steam library. Saves the game keeps in its Proton prefix stay."
        strOKButtonText="Uninstall"
        onOK={() =>
          act(async () => {
            const appid = await uninstall(store, id);
            removeShortcut(appid ?? game.appid);
            reload();
          }, "Uninstalling failed")
        }
      />,
    );

  return (
    <div style={{ marginTop: "40px", height: "calc(100% - 40px)", overflowY: "scroll" }}>
      {game.card && (
        <div style={{ height: "200px", background: `center / cover url("${game.card}")`, position: "relative" }}>
          <div style={{ position: "absolute", inset: 0, background: "linear-gradient(transparent 40%, #0e141b)" }} />
        </div>
      )}
      <div style={{ padding: "8px 24px 80px", maxWidth: "760px" }}>
        <h2 style={{ margin: "0 0 4px" }}>{game.title}</h2>
        <div style={{ ...small, ...dim, marginBottom: "12px" }}>
          {NAMES[store]}
          {game.installed
            ? ` · Installed${info?.installed?.path ? ` in ${info.installed.path.replace(/^\/home\/[^/]+\//, "~/")}` : ""}`
            : info
              ? ` · ${size(info.download)} download${info.disk ? `, ${size(info.disk)} installed` : ""}`
              : " · Getting the size…"}
        </div>
        {game.note && !game.installed && <p style={dim}>{game.note}: it can't be installed here.</p>}
        {/* autoFocus: the page opens on its buttons, not on About (which loads after them) */}
        <Focusable autoFocus>
          {running && <JobProgress job={running} />}
          {busy && (
            <ButtonItem layout="below" onClick={() => act(() => cancel(store, id), "Cancelling failed")}>
              {running ? "Stop the download" : "Remove from the queue"}
            </ButtonItem>
          )}
          {!busy && !game.installed && !game.note && (
            <ButtonItem layout="below" onClick={() => act(() => install(store, id, game.title, "install").then(reload), "Installing failed")}>
              Install
            </ButtonItem>
          )}
          {!busy && game.installed && shortcut && (
            <ButtonItem layout="below" onClick={() => act(() => play(shortcut), "Starting the game failed")}>
              Play
            </ButtonItem>
          )}
          {!busy && game.installed && !shortcut && (
            <ButtonItem
              layout="below"
              onClick={() => act(() => addShortcut(store, id, game.appid).then(reload), "Adding the game to Steam failed")}
            >
              Add to Steam
            </ButtonItem>
          )}
          {!busy && game.installed && update && (
            <ButtonItem layout="below" onClick={() => act(() => install(store, id, game.title, "update").then(reload), "Updating failed")}>
              Update
            </ButtonItem>
          )}
          {!busy && game.installed && (
            <ButtonItem layout="below" onClick={confirmUninstall}>
              Uninstall
            </ButtonItem>
          )}
          <ButtonItem layout="below" onClick={() => Navigation.NavigateBack()}>
            Back
          </ButtonItem>
        </Focusable>
        {game.installed && shortcut && (
          <p style={{ ...small, ...dim }}>
            In your Steam library as {game.title}, started with Proton. Game Settings (Quick Access) works for it as for
            any other game.
          </p>
        )}
        {about && <About d={about} dlc={game.dlc?.length ? game.dlc : (info?.dlc ?? [])} />}
      </div>
    </div>
  );
}
