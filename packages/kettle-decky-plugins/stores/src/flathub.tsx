// Flathub in Game Stores: the apps Flathub builds for ARM64, by category or searched (the tab), and
// an app's page: installing it for the user (the same Flatpak installation as the Welcome plugin's
// Gaming Extras), playing, updating and uninstalling it. Installs go through the backend's job
// queue like the stores' games, and index.tsx adds a finished one to Steam (shortcuts.ts).
import { ButtonItem, ConfirmModal, Dropdown, Field, Focusable, Navigation, TextField, showModal } from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import { FlathubApp, FlathubCategory, FlathubDetails, cancel, flathubApp, flathubBrowse, install, size, status, uninstall } from "./api";
import { addShortcut, inLibrary, play, removeShortcut } from "./shortcuts";
import { JobProgress, act, dim, openGame, small, usePoll } from "./ui";

// Flathub's categories (the backend's FLATHUB_CATEGORIES): games, by genre, then the other apps
const CATEGORIES: { data: FlathubCategory; label: string }[] = [
  { data: "games", label: "Games" },
  { data: "emulators", label: "Emulators" },
  ...[
    ["ActionGame", "Action"],
    ["AdventureGame", "Adventure"],
    ["ArcadeGame", "Arcade"],
    ["BoardGame", "Board"],
    ["CardGame", "Card"],
    ["KidsGame", "Kids"],
    ["LogicGame", "Puzzle"],
    ["RolePlaying", "Role-playing"],
    ["Shooter", "Shooter"],
    ["Simulation", "Simulation"],
    ["SportsGame", "Sports"],
    ["StrategyGame", "Strategy"],
  ].map(([data, label]) => ({ data, label: `Games › ${label}` })),
  { data: "audiovideo", label: "Audio & Video" },
  { data: "graphics", label: "Graphics & Photos" },
  { data: "network", label: "Internet" },
  { data: "office", label: "Productivity" },
  { data: "development", label: "Development" },
  { data: "education", label: "Education" },
  { data: "science", label: "Science" },
  { data: "system", label: "System" },
  { data: "utility", label: "Utilities" },
  { data: "all", label: "All of Flathub" },
  { data: "installed", label: "Installed" },
];

const CSS = `
.kettle-flathub-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; padding: 4px 0 12px; }
.kettle-flathub-card { display: flex; gap: 10px; align-items: center; padding: 10px; border-radius: 6px; background: #23262e; transition: transform 0.1s; }
.kettle-flathub-card.gpfocus { outline: 3px solid #fff; transform: scale(1.03); }
.kettle-flathub-card img, .kettle-flathub-card .noicon { width: 56px; height: 56px; flex: none; object-fit: contain; }
.kettle-flathub-card .t { font-size: 14px; line-height: 18px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kettle-flathub-card .s { font-size: 11px; line-height: 14px; color: #8b929a; height: 28px; overflow: hidden; }
`;

function Card({ a }: { a: FlathubApp }) {
  return (
    <Focusable className="kettle-flathub-card" onActivate={() => openGame("flathub", a.id)} onClick={() => openGame("flathub", a.id)}>
      {a.icon ? <img src={a.icon} loading="lazy" /> : <div className="noicon" />}
      <div style={{ minWidth: 0 }}>
        <div className="t">{a.title}</div>
        <div className="s">{a.summary}</div>
      </div>
    </Focusable>
  );
}

// what the tab last showed, so going back to it doesn't wait
let shown: { category: FlathubCategory; query: string; apps: FlathubApp[]; page: number; pages: number; total: number } | null = null;

export function FlathubTab() {
  const [category, setCategory] = useState<FlathubCategory>(shown?.category ?? "games");
  const [query, setQuery] = useState(shown?.query ?? "");
  const [res, setRes] = useState(shown);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const asked = useRef(0); // the newest request: an older one answering late is dropped

  const load = (page: number) => {
    const n = ++asked.current;
    setLoading(true);
    setError("");
    flathubBrowse(category, query, page)
      .then((r) => {
        if (n !== asked.current) return;
        const apps = page > 1 && res ? [...res.apps, ...r.apps] : r.apps;
        setRes((shown = { category, query, apps, page, pages: r.pages, total: r.total }));
      })
      .catch((e) => n === asked.current && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => n === asked.current && setLoading(false));
  };
  // typing waits a moment before searching
  useEffect(() => {
    if (res && res.category === category && res.query === query) return;
    const t = setTimeout(() => load(1), query ? 400 : 0);
    return () => clearTimeout(t);
  }, [category, query]);

  return (
    <div>
      <style>{CSS}</style>
      <Focusable style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "8px" }} flow-children="horizontal">
        <div style={{ flex: 1 }}>
          <TextField label="Search" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <div style={{ minWidth: "200px" }}>
          <Dropdown rgOptions={CATEGORIES} selectedOption={category} onChange={(o) => setCategory(o.data)} />
        </div>
      </Focusable>
      <div style={{ ...small, ...dim, marginBottom: "6px" }}>
        {error
          ? `Couldn't reach Flathub: ${error}`
          : res
            ? category === "installed"
              ? `${res.total} Flatpak apps installed on this device`
              : `${res.total} apps with an ARM64 build${query ? ` matching "${query}"` : ""}, most installed first`
            : "Loading Flathub…"}
      </div>
      <Focusable className="kettle-flathub-grid">
        {res?.apps.map((a) => (
          <Card key={a.id} a={a} />
        ))}
      </Focusable>
      {res && res.page < res.pages && (
        <ButtonItem layout="below" disabled={loading} onClick={() => load(res.page + 1)}>
          {loading ? "Loading…" : "Show more"}
        </ButtonItem>
      )}
      <p style={{ ...small, ...dim, maxWidth: "720px" }}>
        Only the apps Flathub builds for ARM64 are listed. They're installed for your user, next to the ones from Gaming
        Extras, and added to your Steam library.
      </p>
    </div>
  );
}

// The app's description, screenshots and facts, under the buttons (focusable, so the controller scrolls to them)
function About({ a }: { a: FlathubDetails }) {
  const rows: [string, string][] = [
    ["Developer", a.developer + (a.verified ? " (verified by Flathub)" : "")],
    ["Version", a.installed?.version || a.version],
    ["License", a.free ? a.license : `Proprietary${a.license && !a.license.startsWith("LicenseRef") ? ` (${a.license})` : ""}`],
    ["Website", a.homepage],
    ["App ID", a.id],
  ];
  return (
    <Focusable style={{ marginTop: "20px" }}>
      <h3 style={{ margin: "0 0 8px" }}>About</h3>
      {a.description && (
        <Focusable onActivate={() => {}} style={{ whiteSpace: "pre-line", lineHeight: "22px", marginBottom: "8px" }}>
          {a.description}
        </Focusable>
      )}
      {a.screenshots.map((src) => (
        <Focusable key={src} onActivate={() => {}} style={{ margin: "8px 0" }}>
          <img src={src} loading="lazy" style={{ width: "100%", borderRadius: "6px", display: "block" }} />
        </Focusable>
      ))}
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

export function FlathubPage({ id }: { id: string }) {
  const [a, setA] = useState<FlathubDetails | null | undefined>(undefined);
  const [error, setError] = useState("");
  const [s] = usePoll(status, 1000);
  const [n, setN] = useState(0);
  const reload = () => setN(n + 1);

  useEffect(() => {
    flathubApp(id)
      .then(setA)
      .catch((e) => {
        setError(e instanceof Error ? e.message : String(e));
        setA(null);
      });
  }, [id, n]);

  // the install ending (it leaves the job and the queue) shows the app as installed
  const running = s?.job && s.job.store === "flathub" && s.job.id === id ? s.job : null;
  const queued = !!s?.queue.some((j) => j.store === "flathub" && j.id === id);
  const busy = !!running || queued;
  const [wasBusy, setWasBusy] = useState(false);
  useEffect(() => {
    if (wasBusy && !busy) setTimeout(reload, 1500); // after index.tsx has added the shortcut
    setWasBusy(busy);
  }, [busy]);

  if (a === undefined) return <div style={{ marginTop: "40px", padding: "16px 24px" }}>Loading…</div>;
  if (a === null) return <div style={{ marginTop: "40px", padding: "16px 24px" }}>Couldn't load this app: {error}</div>;

  const installed = !!a.installed;
  const shortcut = a.appid && inLibrary(a.appid) ? a.appid : null;
  const confirmUninstall = () =>
    showModal(
      <ConfirmModal
        strTitle={`Uninstall ${a.title}?`}
        strDescription="The app and the runtimes nothing else uses are removed, and it leaves your Steam library. Its settings and saves in ~/.var/app stay."
        strOKButtonText="Uninstall"
        onOK={() =>
          act(async () => {
            const appid = await uninstall("flathub", id);
            removeShortcut(appid ?? a.appid);
            reload();
          }, "Uninstalling failed")
        }
      />,
    );

  return (
    <div style={{ marginTop: "40px", height: "calc(100% - 40px)", overflowY: "scroll" }}>
      {a.screenshots[0] && (
        <div style={{ height: "200px", background: `center / cover url("${a.screenshots[0]}")`, position: "relative" }}>
          <div style={{ position: "absolute", inset: 0, background: "linear-gradient(transparent 40%, #0e141b)" }} />
        </div>
      )}
      <div style={{ padding: "8px 24px 80px", maxWidth: "760px" }}>
        <div style={{ display: "flex", gap: "12px", alignItems: "center", marginBottom: "12px" }}>
          {a.icon && <img src={a.icon} style={{ width: "64px", height: "64px", objectFit: "contain" }} />}
          <div>
            <h2 style={{ margin: "0 0 4px" }}>{a.title}</h2>
            <div style={{ ...small, ...dim }}>
              {a.summary}
              <br />
              Flathub
              {installed
                ? ` · Installed${a.installed!.installation !== "user" ? " for all users" : ""}`
                : a.download
                  ? ` · about ${size(a.download)} download, ${size(a.disk)} installed, and the runtime it needs if it isn't here yet`
                  : ""}
            </div>
          </div>
        </div>
        {!a.arm64 && !installed && <p style={dim}>Flathub has no ARM64 build of this app: it can't be installed here.</p>}
        {/* autoFocus: the page opens on its buttons, not on About (which loads after them) */}
        <Focusable autoFocus>
          {running && <JobProgress job={running} />}
          {busy && (
            <ButtonItem layout="below" onClick={() => act(() => cancel("flathub", id), "Cancelling failed")}>
              {running ? "Stop the download" : "Remove from the queue"}
            </ButtonItem>
          )}
          {!busy && !installed && a.arm64 && (
            <ButtonItem layout="below" onClick={() => act(() => install("flathub", id, a.title, "install").then(reload), "Installing failed")}>
              Install
            </ButtonItem>
          )}
          {!busy && installed && shortcut && (
            <ButtonItem layout="below" onClick={() => act(() => play(shortcut), "Starting the app failed")}>
              Play
            </ButtonItem>
          )}
          {!busy && installed && !shortcut && (
            <ButtonItem layout="below" onClick={() => act(() => addShortcut("flathub", id).then(reload), "Adding the app to Steam failed")}>
              Add to Steam
            </ButtonItem>
          )}
          {!busy && installed && a.update && (
            <ButtonItem layout="below" onClick={() => act(() => install("flathub", id, a.title, "update").then(reload), "Updating failed")}>
              Update
            </ButtonItem>
          )}
          {!busy && installed && (
            <ButtonItem layout="below" onClick={confirmUninstall}>
              Uninstall
            </ButtonItem>
          )}
          <ButtonItem layout="below" onClick={() => Navigation.NavigateBack()}>
            Back
          </ButtonItem>
        </Focusable>
        {installed && shortcut && (
          <p style={{ ...small, ...dim }}>In your Steam library as {a.installed!.title}, started with flatpak run.</p>
        )}
        <About a={a} />
      </div>
    </div>
  );
}
