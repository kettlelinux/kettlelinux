// The Game Stores page: a tab per store with its games (search, installed only), the downloads
// with where games go, and the store accounts.
import {
  ButtonItem,
  DialogButton,
  DropdownItem,
  Field,
  Focusable,
  ProgressBarWithInfo,
  SidebarNavigation,
  TextField,
} from "@decky/ui";
import { ReactNode, useEffect, useMemo, useState } from "react";
import { FaBoxOpen, FaCompactDisc, FaDownload, FaStore, FaUserCircle } from "react-icons/fa";
import { Game, Job, NAMES, STORES, Store, cancel, library, locations, logout, setLocation, size, status } from "./api";
import { ROUTE, act, dim, openGame, signIn, small, usePoll } from "./ui";

const CSS = `
.kettle-stores-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; padding: 4px 0 24px; }
.kettle-stores-card { border-radius: 6px; overflow: hidden; background: #23262e; transition: transform 0.1s; }
.kettle-stores-card.gpfocus { outline: 3px solid #fff; transform: scale(1.04); }
.kettle-stores-card img { width: 100%; aspect-ratio: 16 / 9; object-fit: cover; display: block; background: #1a1c22; }
.kettle-stores-card .t { padding: 6px 8px; font-size: 13px; line-height: 17px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kettle-stores-card .s { padding: 0 8px 6px; font-size: 11px; color: #8b929a; height: 14px; }
`;

const badge = (g: Game) =>
  g.busy ? (g.busy === "update" ? "Updating…" : "Downloading…") : g.installed ? (g.update ? "Update available" : "Installed") : g.note;

function Card({ store, g }: { store: Store; g: Game }) {
  return (
    <Focusable className="kettle-stores-card" onActivate={() => openGame(store, g.id)} onClick={() => openGame(store, g.id)}>
      {g.card ? <img src={g.card} loading="lazy" /> : <div style={{ aspectRatio: "16 / 9", background: "#1a1c22" }} />}
      <div className="t">{g.title}</div>
      <div className="s">{badge(g)}</div>
    </Focusable>
  );
}

// the last library each store showed, so going back to a tab doesn't wait
const shown: Partial<Record<Store, Game[]>> = {};

function StoreTab({ store }: { store: Store }) {
  const [s] = usePoll(status, 3000);
  const user = s?.users[store];
  const [games, setGames] = useState<Game[] | null>(shown[store] ?? null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [onlyInstalled, setOnlyInstalled] = useState(false);
  const [loading, setLoading] = useState(false);
  const load = (refresh: boolean) => {
    setLoading(true);
    setError("");
    library(store, refresh)
      .then((r) => setGames((shown[store] = r.games)))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    if (user) load(false);
  }, [user]);
  const list = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (games ?? []).filter((g) => (!onlyInstalled || g.installed) && (!q || g.title.toLowerCase().includes(q)));
  }, [games, query, onlyInstalled]);

  if (!s) return null;
  if (!user)
    return (
      <div style={{ maxWidth: "640px" }}>
        <p>Sign in to {NAMES[store]} to see your games here and install them.</p>
        <p style={{ ...small, ...dim }}>
          The sign-in page opens in Steam's browser. Your sign-in is shared with Heroic on the desktop.
        </p>
        <ButtonItem layout="below" onClick={() => act(() => signIn(store), "Signing in failed")}>
          Sign in to {NAMES[store]}
        </ButtonItem>
      </div>
    );
  return (
    <div>
      <style>{CSS}</style>
      <Focusable style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "8px" }} flow-children="horizontal">
        <div style={{ flex: 1 }}>
          <TextField label="Search" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <DialogButton style={{ width: "auto", minWidth: "150px" }} onClick={() => setOnlyInstalled(!onlyInstalled)}>
          {onlyInstalled ? "Installed" : "All games"}
        </DialogButton>
        <DialogButton style={{ width: "auto", minWidth: "110px" }} disabled={loading} onClick={() => load(true)}>
          {loading ? "Loading…" : "Refresh"}
        </DialogButton>
      </Focusable>
      <div style={{ ...small, ...dim, marginBottom: "6px" }}>
        {error
          ? `Couldn't load your games: ${error}`
          : games
            ? `${list.length} of ${games.length} games · signed in as ${user}`
            : "Loading your games…"}
      </div>
      <Focusable className="kettle-stores-grid">
        {list.map((g) => (
          <Card key={g.id} store={store} g={g} />
        ))}
      </Focusable>
    </div>
  );
}

export function JobProgress({ job }: { job: Job }) {
  const pct = job.percent ?? 0;
  const detail = [job.speed ? `${job.speed.toFixed(1)} MiB/s` : "", job.eta ? `${job.eta} left` : ""].filter(Boolean).join(" · ");
  return (
    <ProgressBarWithInfo
      nProgress={pct}
      sOperationText={`${job.kind === "update" ? "Updating" : "Installing"} ${job.title}`}
      description={detail || "Starting…"}
      indeterminate={pct === 0}
    />
  );
}

function DownloadsTab() {
  const [s] = usePoll(status, 1000);
  const [loc, refreshLoc] = usePoll(locations, 10000);
  if (!s) return null;
  return (
    <div style={{ maxWidth: "720px" }}>
      {s.job ? (
        <Focusable style={{ marginBottom: "12px" }}>
          <JobProgress job={s.job} />
          <ButtonItem layout="below" onClick={() => act(() => cancel(s.job!.store, s.job!.id), "Cancelling failed")}>
            Stop (it carries on from here if you install again)
          </ButtonItem>
        </Focusable>
      ) : (
        <p style={dim}>Nothing is downloading.</p>
      )}
      {s.queue.length > 0 && <h3 style={{ margin: "16px 0 4px" }}>Waiting</h3>}
      {s.queue.map((j) => (
        <Field key={`${j.store}:${j.id}`} label={j.title} description={`${NAMES[j.store]} · ${j.kind}`}>
          <DialogButton style={{ width: "auto" }} onClick={() => act(() => cancel(j.store, j.id), "Cancelling failed")}>
            Remove
          </DialogButton>
        </Field>
      ))}
      {loc && (
        <>
          <h3 style={{ margin: "24px 0 4px" }}>Where games go</h3>
          <DropdownItem
            label="New installs"
            description="Games already installed stay where they are."
            rgOptions={loc.locations.map((l) => ({ data: l.path, label: `${l.label} (${size(l.free)} free)` }))}
            selectedOption={loc.current}
            onChange={(o) => act(() => setLocation(o.data).then(refreshLoc), "Changing the location failed")}
          />
        </>
      )}
    </div>
  );
}

function AccountsTab() {
  const [s, refresh] = usePoll(status, 2000);
  if (!s) return null;
  return (
    <div style={{ maxWidth: "720px" }}>
      <p style={{ ...small, ...dim }}>
        Sign-ins open the store's page in Steam's browser. They're shared with Heroic on the desktop: signing in or out
        here does the same there.
      </p>
      {STORES.map((st) => (
        <Field key={st} label={NAMES[st]} description={s.users[st] ? `Signed in as ${s.users[st]}` : "Not signed in"}>
          {s.users[st] ? (
            <DialogButton style={{ width: "auto" }} onClick={() => act(() => logout(st).then(refresh), "Signing out failed")}>
              Sign out
            </DialogButton>
          ) : (
            <DialogButton style={{ width: "auto" }} onClick={() => act(() => signIn(st), "Signing in failed")}>
              Sign in
            </DialogButton>
          )}
        </Field>
      ))}
    </div>
  );
}

const ICONS: Record<Store, ReactNode> = { epic: <FaStore />, gog: <FaCompactDisc />, amazon: <FaBoxOpen /> };

export function Page() {
  const pages = useMemo(
    () => [
      ...STORES.map((st) => ({ title: NAMES[st], route: `${ROUTE}/${st}`, icon: ICONS[st], content: <StoreTab store={st} /> })),
      { title: "Downloads", route: `${ROUTE}/downloads`, icon: <FaDownload />, content: <DownloadsTab /> },
      { title: "Accounts", route: `${ROUTE}/accounts`, icon: <FaUserCircle />, content: <AccountsTab /> },
    ],
    [],
  );
  return (
    <div style={{ marginTop: "40px", height: "calc(100% - 40px)" }}>
      <SidebarNavigation title="Game Stores" showTitle pages={pages} />
    </div>
  );
}
