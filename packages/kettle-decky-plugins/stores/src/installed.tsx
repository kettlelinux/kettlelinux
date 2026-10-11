// The Game Stores page's Installed tab: everything installed through Game Stores in one list (the
// stores' games, Flathub's apps and, where kettle-lepton is installed, Android games), each with
// its size on disk, and Update (a store game or app with one waiting: the download queue's job)
// and Uninstall (its Steam shortcut goes too). Android games have no updates here.
import { ConfirmModal, DialogButton, Field, Focusable, showModal } from "@decky/ui";
import { callable } from "@decky/api";
import { useEffect, useState } from "react";
import { NAMES, Source, cancel, install, size, status, uninstall } from "./api";
import { removeShortcut } from "./shortcuts";
import { JobProgress, act, dim, small, usePoll } from "./ui";

type Item = {
  store: Source;
  id: string;
  title: string;
  version: string;
  update: boolean;
  appid: number | null;
  busy: "install" | "update" | null;
  removable: boolean;
};
type AndroidGame = { package: string; name: string; appid: number; size: number };

const installedAll = callable<[], Item[]>("installed_all");
const installedSize = callable<[store: Source, id: string], number>("installed_size");
const androidList = callable<[], { ok: boolean; games: AndroidGame[] }>("android_list");
const androidStart = callable<[command: string, arg: string], void>("android_start");
const androidJob = callable<[], { busy: boolean; result: any }>("android_job");

// sizes take a while (du over a game's folder): asked once per item, kept while Game Mode runs
const sizes = new Map<string, number>();

function Size({ store, id }: { store: Source; id: string }) {
  const key = `${store}:${id}`;
  const [n, setN] = useState(sizes.get(key));
  useEffect(() => {
    if (n === undefined)
      installedSize(store, id)
        .then((v) => {
          sizes.set(key, v);
          setN(v);
        })
        .catch(() => setN(0));
  }, [key]);
  return <>{n === undefined ? "…" : n > 0 ? size(n) : "?"}</>;
}

async function removeAndroid(pkg: string) {
  await androidStart("remove", pkg);
  for (let i = 0; i < 240; i++) {
    await new Promise((r) => setTimeout(r, 500));
    const j = await androidJob();
    if (!j.busy) {
      if (j.result && !j.result.ok) throw new Error(j.result.error || "kettle-android-games failed");
      return;
    }
  }
}

function confirm(title: string, what: string, onOK: () => void) {
  showModal(
    <ConfirmModal
      strTitle={`Uninstall ${title}?`}
      strDescription={what}
      strOKButtonText="Uninstall"
      onOK={onOK}
    />,
  );
}

const button = { width: "auto", minWidth: "110px", marginLeft: "8px" };

export function InstalledTab() {
  const [items, setItems] = useState<Item[] | null>(null);
  const [android, setAndroid] = useState<AndroidGame[]>([]);
  const [working, setWorking] = useState<string | null>(null); // an uninstall running
  const [s] = usePoll(status, 1000);
  const [n, setN] = useState(0);
  const reload = () => setN(n + 1);

  useEffect(() => {
    installedAll().then(setItems).catch(() => setItems([]));
    androidList()
      .then((r) => setAndroid(r.games ?? []))
      .catch(() => setAndroid([]));
  }, [n]);

  // a job ending (an update done) shows the new state
  const jobKey = s?.job ? `${s.job.store}:${s.job.id}` : "";
  const [lastJob, setLastJob] = useState("");
  useEffect(() => {
    if (lastJob && lastJob !== jobKey) reload();
    setLastJob(jobKey);
  }, [jobKey]);

  if (!items) return <div style={dim}>Loading…</div>;
  const updates = items.filter((i) => i.update && !i.busy);
  const queued = (i: Item) => s?.queue.some((j) => j.store === i.store && j.id === i.id);
  const running = (i: Item) => (s?.job && s.job.store === i.store && s.job.id === i.id ? s.job : null);

  const doUninstall = (i: Item) =>
    confirm(
      i.title,
      i.store === "flathub"
        ? "The app and the runtimes nothing else uses are removed, and it leaves your Steam library. Its settings and saves in ~/.var/app stay."
        : "The game's files are deleted and it leaves your Steam library. Saves the store syncs stay in the store's cloud.",
      () => {
        const key = `${i.store}:${i.id}`;
        setWorking(key);
        act(async () => {
          const appid = await uninstall(i.store, i.id);
          removeShortcut(appid ?? i.appid);
          sizes.delete(key);
        }, `Uninstalling ${i.title} failed`).finally(() => {
          setWorking(null);
          reload();
        });
      },
    );

  return (
    <div style={{ maxWidth: "760px" }}>
      <p style={{ ...small, ...dim, marginTop: 0 }}>
        Everything installed through Game Stores: games from your stores, Flathub apps and Android games.
      </p>
      {updates.length > 1 && (
        <DialogButton
          style={{ marginBottom: "12px" }}
          onClick={() => act(async () => {
            for (const i of updates) await install(i.store, i.id, i.title, "update");
          }, "Queuing the updates failed")}
        >
          Update all ({updates.length})
        </DialogButton>
      )}
      {items.length === 0 && android.length === 0 && <p style={dim}>Nothing is installed yet.</p>}
      {items.map((i) => {
        const key = `${i.store}:${i.id}`;
        const job = running(i);
        const wait = queued(i);
        return (
          <Field
            key={key}
            label={i.title}
            description={
              <div style={small}>
                {NAMES[i.store]}
                {i.version && ` · ${i.version}`} · <Size store={i.store} id={i.id} />
                {i.update && !job && !wait && " · Update available"}
                {wait && " · Waiting to download"}
                {!i.removable && " · Installed for all users: remove it in Discover on the desktop"}
                {job && <JobProgress job={job} />}
              </div>
            }
            bottomSeparator="thick"
          >
            <Focusable style={{ display: "flex" }}>
              {(job || wait) && (
                <DialogButton style={button} onClick={() => act(() => cancel(i.store, i.id), "Cancelling failed")}>
                  {job ? "Stop" : "Remove from queue"}
                </DialogButton>
              )}
              {i.update && !job && !wait && (
                <DialogButton
                  style={button}
                  onClick={() => act(() => install(i.store, i.id, i.title, "update"), `Updating ${i.title} failed`)}
                >
                  Update
                </DialogButton>
              )}
              {i.removable && !job && !wait && (
                <DialogButton style={button} disabled={working !== null} onClick={() => doUninstall(i)}>
                  {working === key ? "Uninstalling…" : "Uninstall"}
                </DialogButton>
              )}
            </Focusable>
          </Field>
        );
      })}
      {android.map((g) => {
        const key = `android:${g.package}`;
        return (
          <Field
            key={key}
            label={g.name}
            description={<div style={small}>Android{g.size > 0 && ` · ${size(g.size)}`}</div>}
            bottomSeparator="thick"
          >
            <DialogButton
              style={button}
              disabled={working !== null}
              onClick={() =>
                confirm(g.name, "This deletes the game, its saves and its shortcut in Steam.", () => {
                  setWorking(key);
                  act(() => removeAndroid(g.package), `Uninstalling ${g.name} failed`).finally(() => {
                    setWorking(null);
                    reload();
                  });
                })
              }
            >
              {working === key ? "Uninstalling…" : "Uninstall"}
            </DialogButton>
          </Field>
        );
      })}
    </div>
  );
}
