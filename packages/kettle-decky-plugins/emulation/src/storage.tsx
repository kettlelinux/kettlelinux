// The Storage tab, like Steam's storage manager but for games and their data (main.py): each
// storage's space and games, games moved, copied or deleted between them (a job, shown as an
// import's), where new games go, and where the game data (saves, states, the emulators' data that
// can move) lives. Games keep their shortcuts, artwork and emulator choices when they move
// (roms.carry_moves).
import { ConfirmModal, DialogButton, DropdownItem, Field, Focusable, showModal } from "@decky/ui";
import { addEventListener, removeEventListener } from "@decky/api";
import { useEffect, useState } from "react";
import { Job, StorageInfo, StoredGame, storageDelete, storageMoveData, storageOverview, storageSetNewGames, storageTransfer } from "./api";
import { JobProgress } from "./add";
import { act, dim, good, plural, size, small, usePoll, warn } from "./ui";

const page = { marginTop: "40px", height: "calc(100% - 40px)", overflowY: "scroll" as const, padding: "16px 24px 80px" };
const card = { background: "#23262e", borderRadius: "8px", padding: "14px 16px", margin: "0 0 12px" };
const row = { display: "flex", gap: "6px", flexWrap: "wrap" as const };
const btn = { width: "auto", minWidth: 0, padding: "4px 12px" };

const nameOf = (s: StorageInfo) => (s.internal ? "internal storage" : s.label);

// used space: games, game data, everything else; then free
function SpaceBar({ s }: { s: StorageInfo }) {
  if (!s.total) return null;
  const pct = (b: number) => `${Math.max(0, (100 * b) / s.total)}%`;
  const other = Math.max(0, s.total - s.free - s.games_bytes - s.data_bytes);
  return (
    <div>
      <div style={{ display: "flex", height: "8px", background: "#1a1c22", borderRadius: "4px", overflow: "hidden", margin: "6px 0" }}>
        <div style={{ width: pct(s.games_bytes), background: "#1a9fff" }} />
        <div style={{ width: pct(s.data_bytes), background: "#59bf40" }} />
        <div style={{ width: pct(other), background: "#5a6170" }} />
      </div>
      <div style={{ ...small, ...dim }}>
        <span style={{ color: "#1a9fff" }}>■</span> games {size(s.games_bytes)} · <span style={{ color: "#59bf40" }}>■</span> game data{" "}
        {size(s.data_bytes)} · <span style={{ color: "#5a6170" }}>■</span> other {size(other)} · {size(s.free)} free of {size(s.total)}
        {s.fstype ? ` · ${s.fstype}` : ""}
      </div>
    </div>
  );
}

function confirmDelete(games: StoredGame[], where: StorageInfo, done: () => void) {
  showModal(
    <ConfirmModal
      strTitle={`Delete ${plural(games.length, "game")}?`}
      strDescription={`${games
        .slice(0, 5)
        .map((g) => g.title)
        .join(", ")}${games.length > 5 ? "…" : ""} (${size(games.reduce((a, g) => a + g.size, 0))}) will be deleted from ${nameOf(where)}. Their saves stay.`}
      strOKButtonText="Delete"
      onOK={() => act(async () => (await storageDelete(games.map((g) => g.id)), done()), "Deleting failed")}
    />,
  );
}

function Actions({ games, from, others, busy, done }: { games: StoredGame[]; from: StorageInfo; others: StorageInfo[]; busy: boolean; done: () => void }) {
  const bytes = games.reduce((a, g) => a + g.size, 0);
  return (
    <Focusable style={row} flow-children="horizontal">
      {others.map((o) => (
        <DialogButton
          key={`m${o.key}`}
          style={btn}
          disabled={busy}
          onClick={() => act(async () => (await storageTransfer(games.map((g) => g.id), o.key, "move"), done()), "Moving failed")}
        >
          Move to {nameOf(o)}
          {bytes > o.free ? " (no room)" : ""}
        </DialogButton>
      ))}
      {others.map((o) => (
        <DialogButton
          key={`c${o.key}`}
          style={btn}
          disabled={busy}
          onClick={() => act(async () => (await storageTransfer(games.map((g) => g.id), o.key, "copy"), done()), "Copying failed")}
        >
          Copy to {nameOf(o)}
        </DialogButton>
      ))}
      <DialogButton style={btn} disabled={busy} onClick={() => confirmDelete(games, from, done)}>
        Delete
      </DialogButton>
    </Focusable>
  );
}

function SystemGroup({
  name,
  games,
  others,
  busy,
  picked,
  toggle,
  done,
}: {
  name: string;
  games: StoredGame[];
  others: StorageInfo[];
  busy: boolean;
  picked: Set<string>;
  toggle: (ids: string[], on: boolean) => void;
  done: () => void;
}) {
  const [open, setOpen] = useState(false);
  const bytes = games.reduce((a, g) => a + g.size, 0);
  const all = games.every((g) => picked.has(g.id));
  return (
    <div style={{ margin: "4px 0" }}>
      <Field
        label={`${open ? "▾" : "▸"} ${name}`}
        description={`${plural(games.length, "game")} · ${size(bytes)}`}
        onActivate={() => setOpen(!open)}
        onClick={() => setOpen(!open)}
        highlightOnFocus
        focusable
        childrenContainerWidth="max"
      >
        <Focusable style={row} flow-children="horizontal">
          <DialogButton style={btn} onClick={() => toggle(games.map((g) => g.id), !all)}>
            {all ? "Unselect all" : "Select all"}
          </DialogButton>
          {others.map((o) => (
            <DialogButton
              key={o.key}
              style={btn}
              disabled={busy}
              onClick={() => act(async () => (await storageTransfer(games.map((g) => g.id), o.key, "move"), done()), "Moving failed")}
            >
              Move all to {nameOf(o)}
            </DialogButton>
          ))}
        </Focusable>
      </Field>
      {open &&
        games.map((g) => (
          <Field
            key={g.id}
            label={`${picked.has(g.id) ? "☑" : "☐"} ${g.title}`}
            description={size(g.size)}
            onActivate={() => toggle([g.id], !picked.has(g.id))}
            onClick={() => toggle([g.id], !picked.has(g.id))}
            highlightOnFocus
            focusable
            indentLevel={1}
          />
        ))}
    </div>
  );
}

function StorageSection({ s, all, busy, done }: { s: StorageInfo; all: StorageInfo[]; busy: boolean; done: () => void }) {
  const [picked, setPicked] = useState<Set<string>>(new Set());
  useEffect(() => setPicked((p) => new Set([...p].filter((id) => s.games.some((g) => g.id === id)))), [s.games]);
  const toggle = (ids: string[], on: boolean) =>
    setPicked((p) => {
      const n = new Set(p);
      ids.forEach((id) => (on ? n.add(id) : n.delete(id)));
      return n;
    });
  const others = all.filter((o) => o.key !== s.key);
  const bySystem = new Map<string, StoredGame[]>();
  s.games.forEach((g) => bySystem.set(g.system_name, [...(bySystem.get(g.system_name) ?? []), g]));
  const sel = s.games.filter((g) => picked.has(g.id));
  return (
    <div style={card}>
      <h3 style={{ margin: "0 0 2px", fontSize: "16px" }}>
        {s.internal ? "Internal storage" : s.label}
        {s.new_games && <span style={{ ...small, ...good }}> · new games go here</span>}
        {s.data && <span style={{ ...small, ...good }}> · game data</span>}
      </h3>
      <SpaceBar s={s} />
      {!s.set_up && !s.internal && <p style={{ ...small, ...dim }}>Not set up for games yet: moving games or the game data here sets it up.</p>}
      {s.set_up && s.games.length === 0 && <p style={{ ...small, ...dim }}>No games on it.</p>}
      {sel.length > 0 && (
        <div style={{ margin: "8px 0" }}>
          <div style={{ ...small, marginBottom: "4px" }}>
            {plural(sel.length, "game")} selected · {size(sel.reduce((a, g) => a + g.size, 0))}
          </div>
          <Actions games={sel} from={s} others={others} busy={busy} done={() => (setPicked(new Set()), done())} />
        </div>
      )}
      {[...bySystem.entries()].map(([name, games]) => (
        <SystemGroup key={name} name={name} games={games} others={others} busy={busy} picked={picked} toggle={toggle} done={done} />
      ))}
    </div>
  );
}

export function StorageTab() {
  const [ov, reload, error] = usePoll(storageOverview, 0);
  const [busy, setBusy] = useState(false);
  // a move or copy changes what's where: shown again when it's done
  useEffect(() => {
    const on = (j: Job) => {
      setBusy(j.state === "running");
      if (j.state !== "running" && (j.kind === "transfer" || j.kind === "data")) reload();
    };
    addEventListener("import", on);
    return () => removeEventListener("import", on);
  }, []);
  if (error) return <div style={page}>The storages couldn't be read: {error}</div>;
  if (!ov) return <div style={page}>Looking at the storages…</div>;
  const usable = ov.storages.filter((s) => s.internal || s.set_up);
  const dataOn = ov.storages.find((s) => s.data);
  const newOn = ov.storages.find((s) => s.new_games);
  return (
    <div style={page}>
      <JobProgress />
      <div style={card}>
        <Field label="New games go to" description="Where the upload page and copying from a card or stick put them. Each storage's own inbox still sorts into that storage." childrenContainerWidth="min">
          <DropdownItem
            rgOptions={usable.map((s) => ({ data: s.key, label: s.internal ? "Internal storage" : s.label }))}
            selectedOption={newOn?.key ?? "internal"}
            onChange={(o) => act(async () => (await storageSetNewGames(o.data), reload()), "Changing it failed")}
          />
        </Field>
        {ov.new_games !== "internal" && newOn?.internal && (
          <div style={{ ...small, ...warn }}>{ov.new_games_label || "The card you picked"} isn't in: new games go to internal storage until it is.</div>
        )}
        <Field
          label="Game data"
          description={
            ov.data_missing
              ? `On ${ov.data_missing}, which isn't in: games that keep their data there won't start until it is.`
              : `On ${dataOn ? nameOf(dataOn) : "internal storage"}. What moves with it: ${ov.moves.join("; ")}.`
          }
          childrenContainerWidth="min"
        >
          <DropdownItem
            disabled={busy || !!ov.data_missing}
            rgOptions={ov.storages.map((s) => ({ data: s.key, label: s.internal ? "Internal storage" : s.label }))}
            selectedOption={dataOn?.key ?? ov.data}
            onChange={(o) => {
              const to = ov.storages.find((s) => s.key === o.data);
              if (!to || to.data) return;
              showModal(
                <ConfirmModal
                  strTitle={`Move the game data to ${nameOf(to)}?`}
                  strDescription={`${size(dataOn?.data_bytes ?? 0)} of saves, states and emulator data move there, and the emulators use it from there.${
                    to.internal ? "" : " Games that keep their data there won't start while the card is out."
                  } Nothing is removed from where it is now until all of it is copied.`}
                  strOKButtonText="Move it"
                  onCancel={reload}
                  onOK={() => act(async () => await storageMoveData(to.key), "Moving the game data failed")}
                />,
              );
            }}
          />
        </Field>
        {ov.stays.length > 0 && (
          <div style={{ ...small, ...dim }}>
            Stays on internal storage (those emulators can't keep it elsewhere): {ov.stays.join(", ")}. BIOS files, keys and firmware always stay
            internal.
          </div>
        )}
      </div>
      {ov.storages.map((s) => (
        <StorageSection key={s.key} s={s} all={ov.storages} busy={busy} done={reload} />
      ))}
    </div>
  );
}
