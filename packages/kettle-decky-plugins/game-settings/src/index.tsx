import {
  ButtonItem,
  ConfirmModal,
  DialogButton,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  ToggleField,
  showModal,
  staticClasses,
} from "@decky/ui";
import { definePlugin, routerHook, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { FaBolt, FaDownload, FaExpandArrowsAlt, FaLayerGroup, FaSlidersH, FaWrench } from "react-icons/fa";
import { ALL_GAMES, GamePicker, InstalledGame, gameName, runningAppId, useSelectedGame } from "../../shared/GamePicker";
import { editLaunchOptions, getLaunchOptions, hasWrapper, withWrapper, withoutWrapper } from "../../shared/launchOptions";
import { fixesFor } from "../../shared/gameFixes";
import {
  CATALOG,
  EMPTY,
  OPTIONS,
  PRESETS,
  Profile,
  applyProfile,
  changedIn,
  isEmpty,
  optionById,
  presetsFor,
  profileOf,
  withPreset,
} from "./catalog";
import {
  Game,
  ROUTE,
  Status,
  commit,
  compatTools,
  currentTool,
  engineSuggestions,
  EngineSuggestions,
  getAuto,
  getEngine,
  getGame,
  installedGames,
  openDatabase,
  recordPlay,
  resetGame,
  setAuto,
  setGame,
  status,
} from "./api";
import { AddDllModal, AddEnvModal, ProfilesModal, ShareModal } from "./modals";
import { Engine, NATIVE_WRAPPER, anticheatText, engineLabel, engineText, runsNatively } from "../../shared/engines";
import { DatabasePage } from "./database";
import { AUTO_EVERY_MS, AUTO_FIRST_MS, autoSync } from "./auto";
import { Tab, Tabs } from "../../shared/Tabs";
import { PerformanceTab } from "./performance";
import { UpscalingTab } from "./upscaling";
import { FrameGenTab, syncFrameGen } from "./framegen";
import { ExtrasTab } from "./extras";

const small: React.CSSProperties = { fontSize: "12px", lineHeight: "16px" };
const mono: React.CSSProperties = { ...small, fontFamily: "monospace", wordBreak: "break-all" };

// sections opened in the panel, kept while it's closed
const opened = new Set<string>();

function restartToast(appid: number, name: string) {
  if (runningAppId() === appid) toaster.toast({ title: "Game Settings", body: `Restart ${name} to apply` });
}

// What the game is built on (gameengine.py, from its files): its engine and the main exe's CPU
function EngineRow({ e }: { e: Engine }) {
  const ac = anticheatText(e);
  return (
    <PanelSectionRow>
      <Field
        label="Engine"
        description={ac ? `Uses ${ac}: its online modes may refuse to run here.` : undefined}
        bottomSeparator="none"
      >
        <div style={small}>{engineText(e)}</div>
      </Field>
    </PanelSectionRow>
  );
}

// Settings suggested for the game's engine: the catalog's presets for it (well-founded ones, such
// as full x87 precision for 32-bit games) and what worked for other games on the same engine in
// the game database. Only ever applied when the player chooses to.
function Suggestions({ appid, e, p, db, apply }: {
  appid: number;
  e: Engine;
  p: Profile;
  db: boolean;
  apply: (label: string, settings: Record<string, string>) => void;
}) {
  const [fromDb, setFromDb] = useState<EngineSuggestions | null>(null);
  useEffect(() => {
    if (db) engineSuggestions(appid).then(setFromDb, () => {});
  }, [appid, db]);
  const applied = (s: Record<string, string>) => Object.entries(s).every(([k, v]) => p.settings[k] === v);
  const describe = (id: string, value: string) => {
    const o = optionById.get(id);
    return o ? `${o.label}: ${o.choices.find((c) => c.value === value)?.label ?? value}` : `${id}=${value}`;
  };
  const rows = presetsFor(e).map((pr) => ({ key: pr.id, label: pr.label, help: pr.help, settings: pr.settings }));
  if (fromDb?.settings.length) {
    const settings = Object.fromEntries(fromDb.settings.map((x) => [x.id, x.value]));
    rows.push({
      key: "database",
      label: `Worked for other ${engineLabel(e)} games`,
      help: fromDb.settings.map((x) => `${describe(x.id, x.value)} (${x.games} games)`).join(" · "),
      settings,
    });
  }
  return (
    <>
      {rows.map((r) => (
        <PanelSectionRow key={r.key}>
          <Field label={`Suggested: ${r.label}`} description={r.help} childrenLayout="below">
            <DialogButton disabled={applied(r.settings)} onClick={() => apply(r.label, r.settings)}>
              {applied(r.settings) ? "Applied" : "Apply"}
            </DialogButton>
          </Field>
        </PanelSectionRow>
      ))}
    </>
  );
}

function minutes(s: number) {
  return `${Math.floor(s / 60)} min`;
}

function GamePanel({ appid, name, s, onChanged }: { appid: number; name: string; s: Status; onChanged: () => void }) {
  // the game database knows games by Steam appid; a non-Steam shortcut's (top bit set) is this device's own
  const db = s.can_share && appid < 2 ** 31;
  const [g, setG] = useState<Game | null>(null);
  const [opts, setOpts] = useState("");
  const [tools, setTools] = useState<{ strToolName: string; strDisplayName: string }[]>([]);
  const [tool, setTool] = useState("");
  const [count, setCount] = useState<number | null>(null);
  const [engine, setEngine] = useState<Engine | null>(null);
  const [open, setOpen] = useState(new Set(opened));

  const reload = async () => {
    const [game, o, t] = await Promise.all([getGame(appid), getLaunchOptions(appid), currentTool(appid)]);
    setG(game);
    setOpts(o);
    setTool(t);
  };
  useEffect(() => {
    reload();
    compatTools(appid).then(setTools);
    getEngine(appid).then(setEngine, () => {});
    if (db) openDatabase.count(appid).then(setCount);
  }, [appid]);
  if (!g) return null;
  const p = profileOf(g);

  const update = async (next: Profile, extra = {}) => {
    try {
      const stored = await commit(appid, g, next, extra);
      setG(stored);
      setOpts(await getLaunchOptions(appid));
      setTool(await currentTool(appid));
      restartToast(appid, name);
      onChanged();
    } catch (e) {
      // commit put the launch options back: show what's there now
      toaster.toast({ title: "Game Settings", body: `Couldn't change ${name}'s settings: ${e}` });
      await reload().catch(() => {});
    }
  };
  const toggle = (id: string) => {
    if (opened.has(id)) opened.delete(id);
    else opened.add(id);
    setOpen(new Set(opened));
  };
  // the launch options don't have the profile any more (edited by hand, or by another plugin)
  const outOfSync = applyProfile(opts, p, g.owned).opts !== opts;
  const fixes = fixesFor(appid);
  const toolNames = new Map(tools.map((t) => [t.strToolName, t.strDisplayName]));

  return (
    <>
      {engine && <EngineRow e={engine} />}
      {engine && runsNatively(engine) && (
        <PanelSectionRow>
          <ToggleField
            label="Run natively on ARM64"
            description={`Runs the game's own code with ARM64 libraries instead of its x86-64 build under FEX (kettle-native). Experimental: turn it off if ${name} doesn't start or misbehaves.`}
            checked={hasWrapper(opts, NATIVE_WRAPPER)}
            onChange={async (on) => {
              await editLaunchOptions(appid, (o) =>
                on ? (hasWrapper(o, NATIVE_WRAPPER) ? o : withWrapper(o, NATIVE_WRAPPER)) : withoutWrapper(o, NATIVE_WRAPPER),
              );
              setOpts(await getLaunchOptions(appid));
              restartToast(appid, name);
            }}
          />
        </PanelSectionRow>
      )}
      {engine && (
        <Suggestions
          appid={appid}
          e={engine}
          p={p}
          db={s.can_share}
          apply={(label, settings) => {
            update({ ...p, settings: { ...p.settings, ...settings } });
            toaster.toast({ title: "Game Settings", body: `Applied: ${label}` });
          }}
        />
      )}
      {tools.length > 0 && (
        <PanelSectionRow>
          <DropdownItem
            label="Proton version"
            description={g.compat_tool ? undefined : `Steam's choice: ${toolNames.get(tool) ?? (tool || "default")}`}
            rgOptions={[
              { data: "", label: "Steam's choice" },
              ...tools.map((t) => ({ data: t.strToolName, label: t.strDisplayName })),
            ]}
            selectedOption={g.compat_tool ?? ""}
            onChange={(o) => update({ ...p, compat_tool: o.data || null })}
          />
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <DropdownItem
          label="Presets"
          description="Starting points; change single options below"
          strDefaultLabel="Apply a preset…"
          rgOptions={PRESETS.map((pr) => ({ data: pr.id, label: pr.label }))}
          selectedOption={null}
          onChange={(o) => {
            const pr = CATALOG.presets.find((x) => x.id === o.data)!;
            update(withPreset(p, pr));
            toaster.toast({ title: pr.label, body: pr.help });
          }}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => showModal(<ProfilesModal profile={p} onLoad={(q) => update({ ...q, compat_tool: p.compat_tool })} />)}>
          Saved profiles…
        </ButtonItem>
      </PanelSectionRow>

      {fixes.map((f) => (
        <PanelSectionRow key={f.id}>
          <ToggleField
            label={`Kettle fix: ${f.title}`}
            description={f.description}
            checked={f.applied(opts)}
            onChange={async (on) => {
              await editLaunchOptions(appid, (o) => (on ? (f.applied(o) ? o : f.edit(o)) : f.undo(o)));
              setOpts(await getLaunchOptions(appid));
              restartToast(appid, name);
            }}
          />
        </PanelSectionRow>
      ))}

      {db && (
        <>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => openDatabase.page(appid)}>
              Known good settings{count ? ` (${count})` : ""}
            </ButtonItem>
          </PanelSectionRow>
          <Feedback appid={appid} name={name} g={g} setG={setG} />
        </>
      )}

      {CATALOG.sections.map((sec) => (
        <div key={sec.id}>
          <PanelSectionRow>
            <ButtonItem layout="below" description={open.has(sec.id) ? sec.help : undefined} onClick={() => toggle(sec.id)}>
              {open.has(sec.id) ? "▾" : "▸"} {sec.title}
              {changedIn(p, sec.id) ? ` · ${changedIn(p, sec.id)} set` : ""}
            </ButtonItem>
          </PanelSectionRow>
          {open.has(sec.id) &&
            OPTIONS.filter((o) => o.section === sec.id).map((o) => (
              <PanelSectionRow key={o.id}>
                <DropdownItem
                  label={o.label}
                  description={o.help}
                  rgOptions={[{ data: "", label: "Default" }, ...o.choices.map((c) => ({ data: c.value, label: c.label }))]}
                  selectedOption={p.settings[o.id] ?? ""}
                  onChange={(c) => {
                    const settings = { ...p.settings };
                    if (c.data === "") delete settings[o.id];
                    else settings[o.id] = c.data;
                    update({ ...p, settings });
                  }}
                />
              </PanelSectionRow>
            ))}
        </div>
      ))}

      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => toggle("custom")}>
          {open.has("custom") ? "▾" : "▸"} Custom
          {p.env.length + p.dlls.length ? ` · ${p.env.length + p.dlls.length} set` : ""}
        </ButtonItem>
      </PanelSectionRow>
      {open.has("custom") && (
        <>
          {p.env.map(([n, v]) => (
            <PanelSectionRow key={`env-${n}`}>
              <ButtonItem layout="below" description="Select to remove" onClick={() => update({ ...p, env: p.env.filter(([m]) => m !== n) })}>
                <span style={mono}>
                  {n}={v}
                </span>
              </ButtonItem>
            </PanelSectionRow>
          ))}
          {p.dlls.map(([d, m]) => (
            <PanelSectionRow key={`dll-${d}`}>
              <ButtonItem layout="below" description="Select to remove" onClick={() => update({ ...p, dlls: p.dlls.filter(([e]) => e !== d) })}>
                <span style={mono}>
                  {d}.dll: {CATALOG.custom.dll_modes.find((x) => x.value === m)?.label}
                </span>
              </ButtonItem>
            </PanelSectionRow>
          ))}
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              disabled={p.env.length >= CATALOG.custom.max_env}
              onClick={() => showModal(<AddEnvModal onAdd={(n, v) => update({ ...p, env: [...p.env.filter(([m]) => m !== n), [n, v]] })} />)}
            >
              Add variable…
            </ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              disabled={p.dlls.length >= CATALOG.custom.max_dlls}
              onClick={() => showModal(<AddDllModal onAdd={(d, m) => update({ ...p, dlls: [...p.dlls.filter(([e]) => e !== d), [d, m]] })} />)}
            >
              Add DLL override…
            </ButtonItem>
          </PanelSectionRow>
        </>
      )}

      <PanelSectionRow>
        <Field label="Launch options" childrenLayout="below" bottomSeparator="none">
          <div style={mono}>{opts || "(none)"}</div>
        </Field>
      </PanelSectionRow>
      {outOfSync && (
        <PanelSectionRow>
          <ButtonItem layout="below" description="They were changed outside Game Settings" onClick={() => update(p)}>
            Re-apply this profile
          </ButtonItem>
        </PanelSectionRow>
      )}
      {!isEmpty(p) && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() =>
              showModal(
                <ConfirmModal
                  strTitle={`Reset ${name}?`}
                  strDescription="Takes out every launch option Game Settings added and puts the Proton version back. Your own launch options stay."
                  strOKButtonText="Reset"
                  onOK={async () => {
                    try {
                      await commit(appid, g, EMPTY);
                      setG(await resetGame(appid));
                      setOpts(await getLaunchOptions(appid));
                      setTool(await currentTool(appid));
                      restartToast(appid, name);
                      onChanged();
                    } catch (e) {
                      toaster.toast({ title: "Game Settings", body: `Couldn't reset ${name}: ${e}` });
                      await reload().catch(() => {});
                    }
                  }}
                />,
              )
            }
          >
            Reset {name}
          </ButtonItem>
        </PanelSectionRow>
      )}
    </>
  );
}

// Did the settings work: the user's verdict, and from it sharing to the game database (own
// settings) or a confirmation (settings from the database)
function Feedback({ appid, name, g, setG }: { appid: number; name: string; g: Game; setG: (g: Game) => void }) {
  const need = g.played_min_s;
  const played = g.played_s > 0 ? `Played ${minutes(g.played_s)} with these settings.` : "Not played with these settings yet.";
  if (g.from_database) {
    const voted = g.voted.includes(g.from_database.id);
    return (
      <PanelSectionRow>
        <Field
          label={`From the game database (${g.from_database.status === "approved" ? "verified" : "community"}${
            g.from_database.auto ? ", applied automatically" : ""
          })`}
          description={
            voted
              ? "Thanks, your answer was sent."
              : `${played}${g.played_enough ? "" : ` You can confirm it works after ${minutes(need)}.`}`
          }
          childrenLayout="below"
        >
          {!voted && (
            <div style={{ display: "flex", gap: "8px" }}>
              <DialogButton disabled={!g.can_vote || !g.played_enough} onClick={() => vote(appid, true, setG)}>
                Works here
              </DialogButton>
              <DialogButton disabled={!g.can_vote} onClick={() => vote(appid, false, setG)}>
                Doesn't work
              </DialogButton>
            </div>
          )}
        </Field>
      </PanelSectionRow>
    );
  }
  if (g.played_s === 0 && isEmpty(profileOf(g))) return null;
  return (
    <>
      <PanelSectionRow>
        <DropdownItem
          label="Do these settings work?"
          description={played}
          rgOptions={[
            { data: "", label: "Not sure yet" },
            { data: "works", label: "Yes, it plays" },
            { data: "broken", label: "No" },
          ]}
          selectedOption={g.works ? "works" : g.broken ? "broken" : ""}
          onChange={async (o) => setG(await setGame(appid, { verdict: o.data === "" ? null : o.data === "works" }))}
        />
      </PanelSectionRow>
      {g.works && !g.is_shared && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={!g.can_submit}
            description={
              g.can_submit
                ? "Share them as known good, so other players can try them"
                : `You can share them after ${minutes(need)} of play with these settings`
            }
            onClick={() => showModal(<ShareModal appid={appid} name={name} g={g} onShared={() => getGame(appid).then(setG)} />)}
          >
            Share to the game database…
          </ButtonItem>
        </PanelSectionRow>
      )}
      {g.is_shared && (
        <PanelSectionRow>
          <Field label="Shared to the game database" description="It shows as community settings until it's verified." />
        </PanelSectionRow>
      )}
    </>
  );
}

async function vote(appid: number, works: boolean, setG: (g: Game) => void) {
  try {
    setG(await openDatabase.vote(appid, works));
  } catch (e: any) {
    toaster.toast({ title: "Game Settings", body: String(e?.message ?? e) });
  }
}

const TABS: Tab[] = [
  { id: "compat", label: "Compat", icon: <FaWrench /> },
  { id: "perf", label: "Perf", icon: <FaBolt /> },
  { id: "upscaling", label: "Upscale", icon: <FaExpandArrowsAlt /> },
  { id: "framegen", label: "Frame Gen", icon: <FaLayerGroup /> },
  { id: "extras", label: "Extras", icon: <FaDownload /> },
];
let lastTab = TABS[0].id; // kept while the panel is closed

// The Compatibility tab with "All games" picked: the database's verified settings for every game
function AllGames({ s, games, onSynced }: { s: Status; games: InstalledGame[]; onSynced: () => void }) {
  const [auto, setAutoState] = useState(false);
  useEffect(() => {
    getAuto().then(setAutoState);
  }, []);
  return (
    <>
      {s.can_share && (
        <PanelSectionRow>
          <ToggleField
            label="Use verified settings automatically"
            description="Games you haven't changed get the settings the Kettle team verified for this device. Your own changes always win, and Reset takes them off for good."
            checked={auto}
            onChange={async (on) => {
              setAutoState(await setAuto(on));
              if (on && (await autoSync(true))) onSynced();
            }}
          />
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <div style={small}>
          {s.configured.length > 0
            ? `Changed for: ${s.configured.map((a) => gameName(games, a)).join(", ")}`
            : "Compatibility settings are per game: pick one above."}
        </div>
      </PanelSectionRow>
    </>
  );
}

function Content() {
  const [s, setS] = useState<Status | null>(null);
  const [games, setGames] = useState<InstalledGame[] | null>(null);
  const [appid, pick] = useSelectedGame(games);
  const [tab, setTab] = useState(lastTab);
  const [panelKey, setPanelKey] = useState(0);
  const refresh = () => status().then(setS);
  useEffect(() => {
    refresh();
    installedGames().then(setGames);
  }, []);
  if (!s || !games) return null;
  // null: "All games"
  const game = appid !== null && appid !== ALL_GAMES ? appid : null;
  const name = game !== null ? gameName(games, game) : "";
  const pickTab = (t: string) => setTab((lastTab = t));
  return (
    <>
      <PanelSection>
        <GamePicker games={games} appid={appid} onChange={pick} allGames />
        <Tabs tabs={TABS} tab={tab} onChange={pickTab} />
      </PanelSection>
      {tab === "upscaling" ? (
        <UpscalingTab appid={game} name={name} />
      ) : tab === "extras" ? (
        <ExtrasTab />
      ) : (
        <PanelSection>
          {tab === "compat" &&
            (game !== null ? (
              <GamePanel key={`${game}-${panelKey}`} appid={game} name={name} s={s} onChanged={refresh} />
            ) : (
              <AllGames s={s} games={games} onSynced={() => {
                refresh();
                setPanelKey((k) => k + 1);
              }} />
            ))}
          {tab === "perf" && <PerformanceTab appid={game} name={name} />}
          {tab === "framegen" && <FrameGenTab appid={game} name={name} games={games} />}
        </PanelSection>
      )}
    </>
  );
}

export default definePlugin(() => {
  routerHook.addRoute(`${ROUTE}/:appid`, DatabasePage);
  syncFrameGen().catch(() => {});
  // play time per profile: settings can be shared, or confirmed, only after real play
  const started = new Map<number, { at: number; tool: string }>();
  const lifetime = SteamClient.GameSessions.RegisterForAppLifetimeNotifications(
    (n: { unAppID: number; bRunning: boolean }) => {
      if (n.bRunning) {
        const at = Date.now();
        started.set(n.unAppID, { at, tool: "" });
        currentTool(n.unAppID).then((tool) => {
          const s = started.get(n.unAppID);
          if (s && s.at === at) s.tool = tool;
        });
      } else {
        const s = started.get(n.unAppID);
        started.delete(n.unAppID);
        if (s) recordPlay(n.unAppID, (Date.now() - s.at) / 1000, s.tool).catch(() => {});
        // the backend stores the Frame Gen measurement after a game exits (it samples every
        // 2 s), which can change the automatic cap: rewrite launch options for the next launch
        setTimeout(() => syncFrameGen().catch(() => {}), 5000);
      }
    },
  );
  const first = setTimeout(() => autoSync(), AUTO_FIRST_MS);
  const every = setInterval(() => autoSync(), AUTO_EVERY_MS);
  return {
    name: "Game Settings",
    titleView: <div className={staticClasses.Title}>Game Settings</div>,
    content: <Content />,
    icon: <FaSlidersH />,
    onDismount: () => {
      clearTimeout(first);
      clearInterval(every);
      lifetime.unregister();
      routerHook.removeRoute(`${ROUTE}/:appid`);
    },
  };
});
