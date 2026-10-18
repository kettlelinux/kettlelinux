// The Emulation page, a tab each: Library (the systems, their games and emulators), Add games
// (add.tsx), BIOS, Controls, Saves, Extra cores and Settings.
import {
  ConfirmModal,
  DialogButton,
  DropdownItem,
  Field,
  Focusable,
  ModalRoot,
  SidebarNavigation,
  TextField,
  showModal,
} from "@decky/ui";
import { useEffect, useMemo, useState } from "react";
import { FaBook, FaCog, FaDownload, FaGamepad, FaMicrochip, FaPlus, FaSave } from "react-icons/fa";
import {
  BiosEntry,
  Game,
  Overview,
  SaveGame,
  System,
  artChoices,
  artDone,
  artwork,
  backup,
  backups,
  bios,
  biosInstall,
  coreDownload,
  coreRemove,
  cores,
  games,
  overview,
  restore,
  restoreDeleted,
  saveDelete,
  saveThumb,
  saves,
  setChoice,
  setGameChoice,
  setSettings,
} from "./api";
import { AddTab } from "./add";
import { applyArt, inLibrary, onSync, play, sync } from "./sync";
import { toaster } from "@decky/api";
import { ControlsTable, ROUTE, act, dim, good, openStart, plural, size, small, usePoll, warn } from "./ui";

const page = { padding: "0 0 40px" };

function emulatorOptions(s: System) {
  return s.emulators.map((e) => ({
    data: e.id,
    label: e.installed ? e.name : e.download ? `${e.name} (download it in Extra cores)` : e.flatpak ? `${e.name} (install it from Game Stores > Flathub)` : `${e.name} (not installed)`,
  }));
}

function ArtModal({ g, names, closeModal }: { g: Game; names: string[]; closeModal?: () => void }) {
  const pick = (n: string) =>
    act(async () => {
      if (!g.appid || !inLibrary(g.appid)) throw new Error("the game isn't in the Steam library yet");
      const art = await artwork(g.id, n);
      if (!Object.keys(art).length) throw new Error(`no pictures came for "${n}"`);
      await applyArt(g.appid, art);
      await artDone(g.id, true);
      closeModal?.();
      toaster.toast({ title: "Emulation", body: `Artwork set for ${g.title}` });
    }, "Setting the artwork failed");
  return (
    <ModalRoot closeModal={closeModal}>
      <h3 style={{ marginTop: 0 }}>Artwork for {g.title}</h3>
      <Focusable style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
        {names.map((n) => (
          <DialogButton key={n} onClick={() => pick(n)}>
            {n}
          </DialogButton>
        ))}
      </Focusable>
    </ModalRoot>
  );
}

function GamesModal({ s, closeModal }: { s: System; closeModal?: () => void }) {
  const [list, reload] = usePoll(() => games(s.id), 0);
  const installed = s.emulators.filter((e) => e.installed);
  const fixArt = (g: Game) =>
    act(async () => {
      const names = await artChoices(g.id);
      if (!names.length) throw new Error("libretro-thumbnails has nothing close to its name");
      showModal(<ArtModal g={g} names={names} />);
    }, "Finding artwork failed");
  return (
    <ModalRoot closeModal={closeModal}>
      <h3 style={{ marginTop: 0 }}>{s.name}</h3>
      {!list && <p>Loading…</p>}
      {list && list.length === 0 && <p>No games. Add some in Add games.</p>}
      <div style={{ maxHeight: "60vh", overflowY: "auto" }}>
        {list?.map((g) => (
          <Field key={g.id} label={g.title} description={g.path} childrenContainerWidth="max">
            <Focusable style={{ display: "flex", gap: "6px", alignItems: "center" }} flow-children="horizontal">
              {g.appid && inLibrary(g.appid) && (
                <DialogButton style={{ width: "auto", minWidth: 0 }} onClick={() => act(() => play(g.appid!), "Starting it failed")}>
                  Play
                </DialogButton>
              )}
              <DialogButton style={{ width: "auto", minWidth: 0 }} onClick={() => fixArt(g)}>
                Artwork
              </DialogButton>
              {installed.length > 1 && (
                <DropdownItem
                  rgOptions={[{ data: "", label: "System's emulator" }, ...installed.map((e) => ({ data: e.id, label: e.name }))]}
                  selectedOption={g.emulator}
                  onChange={(o) => act(async () => (await setGameChoice(g.id, o.data || null), reload()), "Saving failed")}
                />
              )}
            </Focusable>
          </Field>
        ))}
      </div>
    </ModalRoot>
  );
}

function LibraryTab({ ov, reload }: { ov: Overview; reload: () => void }) {
  const [busy, setBusy] = useState(false);
  useEffect(() => onSync((b) => (setBusy(b), b || reload())), []);
  const withGames = ov.systems.filter((s) => s.count > 0);
  const without = ov.systems.filter((s) => s.count === 0);
  const row = (s: System) => (
    <Field
      key={s.id}
      label={`${s.name}${s.count ? ` · ${plural(s.count, "game")}` : ""}`}
      description={
        <span>
          <span style={dim}>Emulation/roms/{s.folder}</span>
          {s.bios === "missing-required" && !s.bios_from_core && <span style={warn}> · needs a BIOS file (BIOS tab)</span>}
          {s.bios_from_core ? (
            <span style={warn}> · {s.note || "needs folders that come with its core, from Extra cores"}</span>
          ) : (
            !s.emulator && <span style={warn}> · {s.note || "no emulator installed"}</span>
          )}
        </span>
      }
      childrenContainerWidth="max"
    >
      <Focusable style={{ display: "flex", gap: "6px", alignItems: "center" }} flow-children="horizontal">
        {s.emulators.length > 1 && (
          <DropdownItem
            rgOptions={emulatorOptions(s)}
            selectedOption={s.emulator || s.emulators[0].id}
            onChange={(o) => act(async () => (await setChoice(s.id, o.data), reload()), "Saving failed")}
          />
        )}
        {s.count > 0 && (
          <DialogButton style={{ width: "auto", minWidth: 0 }} onClick={() => showModal(<GamesModal s={s} />)}>
            Games
          </DialogButton>
        )}
      </Focusable>
    </Field>
  );
  return (
    <div style={page}>
      <Focusable style={{ display: "flex", gap: "8px", marginBottom: "8px" }} flow-children="horizontal">
        <DialogButton style={{ width: "auto" }} disabled={busy} onClick={() => sync().catch(() => {})}>
          {busy ? "Updating the library…" : "Look for new games now"}
        </DialogButton>
        <DialogButton style={{ width: "auto" }} onClick={openStart}>
          Get started again
        </DialogButton>
      </Focusable>
      <p style={{ ...small, ...dim, margin: "0 0 8px" }}>
        {plural(ov.total, "game")} in your library, a collection per system. New games show up on their own; a game whose shortcut you delete
        in Steam stays out.
      </p>
      {withGames.map(row)}
      {withGames.length > 0 && (
        <Field label="Deleted from Steam" description="Bring back the games of every system whose shortcuts were deleted in Steam">
          <DialogButton
            style={{ width: "auto" }}
            onClick={() =>
              act(async () => {
                for (const s of ov.systems) await restoreDeleted(s.id);
                await sync();
              }, "That failed")
            }
          >
            Bring back
          </DialogButton>
        </Field>
      )}
      <h3 style={{ margin: "16px 0 4px" }}>Other systems</h3>
      {without.map(row)}
    </div>
  );
}

// a right file in a BIOS folder under another name or in a subfolder: the emulators don't see it yet
function Found({ e, onInstall }: { e: BiosEntry; onInstall: () => void }) {
  return (
    <span>
      <span style={warn}> · found, needs installing</span>
      <span style={dim}> ({e.elsewhere})</span>{" "}
      <DialogButton style={{ display: "inline-block", width: "auto", minWidth: 0, padding: "2px 10px" }} onClick={onInstall}>
        Install
      </DialogButton>
    </span>
  );
}

function BiosTab() {
  const [info, reload] = usePoll(bios, 0);
  if (!info) return null;
  const elsewhere = info.systems.reduce((n, s) => n + s.entries.filter((e) => !e.found && e.elsewhere).length, 0);
  const install = (system?: string) =>
    act(async () => {
      const done = await biosInstall(system ?? null);
      reload();
      toaster.toast({ title: "Emulation", body: done.length ? `Installed ${done.join(", ")}` : "Nothing was installed" });
    }, "Installing the BIOS files failed");
  return (
    <div style={page}>
      <p style={{ ...small, marginTop: 0 }}>
        Some systems need a BIOS file from the console itself. Kettle can't include them: copy yours into the inbox, under any name, and
        they're recognised by their content and put in place. One copied straight into{" "}
        <span style={{ fontFamily: "monospace" }}>{info.folder}</span> (or a card's Emulation/bios) under another name or in a subfolder
        is found too, and installed with the button below.
      </p>
      <Focusable style={{ display: "flex", gap: "8px", marginBottom: "8px" }}>
        <DialogButton style={{ width: "auto" }} onClick={reload}>
          Check again
        </DialogButton>
        {elsewhere > 0 && (
          <DialogButton style={{ width: "auto" }} onClick={() => install()}>
            Install {plural(elsewhere, "file")} found
          </DialogButton>
        )}
      </Focusable>
      {info.systems.map((s) => {
        const one = s.entries.filter((e) => e.one_of);
        const rest = s.entries.filter((e) => !e.one_of);
        const color = s.state === "ok" ? good : s.state === "missing-required" ? warn : dim;
        const label = { ok: "Ready", "missing-required": "Missing what it needs", "missing-optional": "Works; optional files missing", none: "" }[s.state];
        return (
          <Field key={s.id} label={s.name} description={<span style={color}>{label}</span>} childrenContainerWidth="max" bottomSeparator="standard">
            <div style={small}>
              {one.length > 0 && (
                <div style={{ marginBottom: "4px" }}>
                  <div style={one.some((e) => e.found) ? good : warn}>One of these (a region each):</div>
                  {one.map((e) => (
                    <div key={e.file}>
                      {e.found ? "✓" : "·"} {e.file} <span style={dim}>{e.note}</span>
                      {!e.found && e.elsewhere && <Found e={e} onInstall={() => install(s.id)} />}
                    </div>
                  ))}
                </div>
              )}
              {rest.map((e) => (
                <div key={e.file}>
                  <span style={e.found ? good : e.required ? warn : dim}>{e.found ? "✓" : e.required ? "✗" : "·"}</span> {e.file}
                  <span style={dim}>
                    {" "}
                    {e.required ? "needed" : "optional"}
                    {e.note ? ` · ${e.note}` : ""}
                  </span>
                  {!e.found && e.elsewhere && <Found e={e} onInstall={() => install(s.id)} />}
                  {e.bad && !e.elsewhere && <span style={warn}> · the file there isn't a good dump</span>}
                </div>
              ))}
            </div>
          </Field>
        );
      })}
    </div>
  );
}

function ControlsTab({ ov }: { ov: Overview }) {
  return (
    <div style={{ ...page, maxWidth: "720px" }}>
      <p style={{ ...small, marginTop: 0 }}>
        Every system plays with the same controls. Buttons sit where the original controller had them (the bottom face button is the
        bottom one everywhere), and holding <b>Select</b> turns the buttons into hotkeys, in every emulator:
      </p>
      <ControlsTable face={ov.face} />
      <p style={{ ...small, ...dim }}>
        The same actions are buttons in Quick Access while a game runs. The layout is Steam's "Kettle Emulation" controller layout, set for
        each game once on the device's own controls and on wired (USB) controllers: change a game's layout in Steam and it keeps yours. A
        Bluetooth or other wireless controller, or a Remote Play one, doesn't get it: it keeps its own layout, without the Select hotkeys.
      </p>
    </div>
  );
}

function SaveRow({ g, onChange }: { g: SaveGame; onChange: () => void }) {
  const [thumb, setThumb] = useState("");
  useEffect(() => {
    const t = g.files.find((f) => f.thumb);
    if (t) saveThumb(t.thumb).then(setThumb).catch(() => {});
  }, [g.id]);
  const st = g.files.filter((f) => f.kind === "state").length;
  const sv = g.files.filter((f) => f.kind === "save").length;
  const del = () =>
    showModal(
      <ConfirmModal
        strTitle={`Delete ${g.title}'s saves?`}
        strDescription={`${plural(sv, "save")} and ${plural(st, "state")} are deleted. Back them up first to keep a copy.`}
        strOKButtonText="Delete"
        onOK={() => act(async () => (await saveDelete(g.files.map((f) => f.id)), onChange()), "Deleting failed")}
      />,
    );
  return (
    <Field
      label={g.title}
      icon={thumb ? <img src={thumb} style={{ height: "40px", borderRadius: "3px" }} /> : undefined}
      description={`${plural(sv, "save")}, ${plural(st, "state")} · ${new Date(Math.max(...g.files.map((f) => f.mtime)) * 1000).toLocaleString()}`}
    >
      <Focusable style={{ display: "flex", gap: "6px" }} flow-children="horizontal">
        <DialogButton style={{ width: "auto", minWidth: 0 }} onClick={() => act(async () => toastDone(await backup(g.files.map((f) => f.id), "internal")), "Backing up failed")}>
          Back up
        </DialogButton>
        <DialogButton style={{ width: "auto", minWidth: 0 }} onClick={del}>
          Delete
        </DialogButton>
      </Focusable>
    </Field>
  );
}

const toastDone = (path: string) =>
  showModal(
    <ConfirmModal strTitle="Backed up" strDescription={path} strOKButtonText="OK" bAlertDialog />,
  );

function SavesTab({ ov }: { ov: Overview }) {
  const [list, reload] = usePoll(saves, 0);
  const [bks, reloadBks] = usePoll(backups, 0);
  const cards = ov.storages.filter((s) => !s.internal);
  return (
    <div style={page}>
      <Focusable style={{ display: "flex", gap: "8px", marginBottom: "8px" }} flow-children="horizontal">
        <DialogButton style={{ width: "auto" }} onClick={() => act(async () => (toastDone(await backup([], "internal")), reloadBks()), "Backing up failed")}>
          Back up everything
        </DialogButton>
        {cards.map((c) => (
          <DialogButton key={c.path} style={{ width: "auto" }} onClick={() => act(async () => (toastDone(await backup([], c.path)), reloadBks()), "Backing up failed")}>
            Back up to {c.label}
          </DialogButton>
        ))}
      </Focusable>
      {list && list.length === 0 && <p>No saves yet.</p>}
      {list?.map((g) => <SaveRow key={g.id} g={g} onChange={reload} />)}
      {bks && bks.length > 0 && (
        <>
          <h3 style={{ margin: "16px 0 4px" }}>Backups</h3>
          {bks.map((b) => (
            <Field key={b.id} label={b.path.split("/").pop()} description={`${size(b.size)} · ${b.path}`}>
              <DialogButton
                style={{ width: "auto" }}
                onClick={() =>
                  showModal(
                    <ConfirmModal
                      strTitle="Restore this backup?"
                      strDescription="Its saves and states replace the ones you have now for the same games."
                      strOKButtonText="Restore"
                      onOK={() =>
                        act(async () => {
                          const r = await restore(b.id);
                          reload();
                          showModal(<ConfirmModal strTitle="Restored" strDescription={`${plural(r.restored, "file")} restored${r.skipped ? `, ${r.skipped} skipped` : ""}.`} bAlertDialog />);
                        }, "Restoring failed")
                      }
                    />,
                  )
                }
              >
                Restore
              </DialogButton>
            </Field>
          ))}
        </>
      )}
    </div>
  );
}

function CoresTab({ reload }: { reload: () => void }) {
  const [list, setList] = useState<Awaited<ReturnType<typeof cores>> | null>(null);
  const [busy, setBusy] = useState("");
  useEffect(() => {
    cores().then(setList).catch(() => {});
  }, []);
  return (
    <div style={page}>
      <p style={{ ...small, marginTop: 0 }}>
        These emulators are free to use at home, but their licenses don't allow them to be sold or included in Kettle. Download one and the
        systems it plays (arcade, 32X; better Genesis and SNES) work like the rest. They come from libretro's own build server.
      </p>
      {list?.map((c) => (
        <Field
          key={c.core}
          label={c.name}
          description={`${c.systems.join(", ")} · ${c.terms}${c.missing.length ? ` Its ${c.missing.join(" and ")} folders are missing from Emulation/bios: download it again.` : ""}`}
          childrenContainerWidth="max"
        >
          {c.installed ? (
            <DialogButton style={{ width: "auto" }} onClick={() => act(async () => (setList(await coreRemove(c.core)), reload()), "Removing failed")}>
              Remove
            </DialogButton>
          ) : (
            <DialogButton
              style={{ width: "auto" }}
              disabled={!!busy}
              onClick={() =>
                showModal(
                  <ConfirmModal
                    strTitle={`Download ${c.name}?`}
                    strDescription={`${c.terms} License: ${c.license}. By downloading it you accept that license.`}
                    strOKButtonText="Accept and download"
                    onOK={() =>
                      act(async () => {
                        setBusy(c.core);
                        try {
                          setList(await coreDownload(c.core));
                          reload(); // the emulator lists of Library and Settings
                        } finally {
                          setBusy("");
                        }
                      }, "Downloading failed")
                    }
                  />,
                )
              }
            >
              {busy === c.core ? "Downloading…" : "Download"}
            </DialogButton>
          )}
        </Field>
      ))}
    </div>
  );
}

function SettingsTab({ ov, reload }: { ov: Overview; reload: () => void }) {
  const [key, setKey] = useState(ov.settings.sgdb_key);
  return (
    <div style={{ ...page, maxWidth: "720px" }}>
      <Field
        label="SteamGridDB API key"
        description="Optional: artwork from SteamGridDB for games libretro-thumbnails doesn't have. Get a key at steamgriddb.com/profile/preferences/api."
        childrenContainerWidth="max"
      >
        <TextField value={key} onChange={(e) => setKey(e.target.value)} />
      </Field>
      <DialogButton style={{ width: "auto" }} onClick={() => act(async () => (await setSettings({ sgdb_key: key.trim() }), reload()), "Saving failed")}>
        Save the key
      </DialogButton>
      <h3 style={{ margin: "16px 0 4px" }}>Emulator per system</h3>
      {ov.systems
        .filter((s) => s.emulators.length > 1)
        .map((s) => (
          <DropdownItem
            key={s.id}
            label={s.name}
            rgOptions={emulatorOptions(s)}
            selectedOption={s.emulator || s.emulators[0].id}
            onChange={(o) => act(async () => (await setChoice(s.id, o.data), reload()), "Saving failed")}
          />
        ))}
    </div>
  );
}

export function Page() {
  const [ov, reload, error] = usePoll(overview, 0);
  const pages = useMemo(
    () =>
      ov
        ? [
            { title: "Library", route: `${ROUTE}/library`, icon: <FaGamepad />, content: <LibraryTab ov={ov} reload={reload} /> },
            { title: "Add games", route: `${ROUTE}/add`, icon: <FaPlus />, content: <AddTab ov={ov} /> },
            { title: "BIOS", route: `${ROUTE}/bios`, icon: <FaMicrochip />, content: <BiosTab /> },
            { title: "Controls", route: `${ROUTE}/controls`, icon: <FaBook />, content: <ControlsTab ov={ov} /> },
            { title: "Saves", route: `${ROUTE}/saves`, icon: <FaSave />, content: <SavesTab ov={ov} /> },
            { title: "Extra cores", route: `${ROUTE}/cores`, icon: <FaDownload />, content: <CoresTab reload={reload} /> },
            { title: "Settings", route: `${ROUTE}/settings`, icon: <FaCog />, content: <SettingsTab ov={ov} reload={reload} /> },
          ]
        : [],
    [ov],
  );
  if (error) return <div style={{ marginTop: "40px", padding: "16px 24px" }}>Emulation isn't working: {error}</div>;
  if (!ov) return <div style={{ marginTop: "40px", padding: "16px 24px" }}>Loading…</div>;
  return (
    <div style={{ marginTop: "40px", height: "calc(100% - 40px)" }}>
      <SidebarNavigation title="Emulation" showTitle pages={pages} />
    </div>
  );
}
