// Getting games in, the four ways (main.py): the inbox, a card or stick, the upload page for a phone
// or PC (a QR code and a PIN) and the network share. Games are sorted into their system's folder by
// what's in the file; BIOS files are recognised wherever they are. Get started (start.tsx) shows
// the same sections.
import { ConfirmModal, DialogButton, DropdownItem, Field, Focusable, ModalRoot, TextField, ToggleField, showModal } from "@decky/ui";
import { addEventListener, removeEventListener } from "@decky/api";
import qrcode from "qrcode-generator";
import { useEffect, useState } from "react";
import {
  Job,
  Overview,
  Share,
  Upload,
  assign,
  importCancel,
  importStart,
  importStatus,
  inboxNow,
  media,
  setSettings,
  setUpCard,
  shareDisable,
  shareEnable,
  shareStatus,
  unsorted,
  uploadStart,
  uploadStatus,
  uploadStop,
} from "./api";
import { act, dim, errorText, good, plural, size, small, usePoll, warn } from "./ui";

const card = { background: "#23262e", borderRadius: "8px", padding: "14px 16px", margin: "0 0 12px" };
const h = { margin: "0 0 6px", fontSize: "16px" };
const mono = { fontFamily: "monospace", fontSize: "13px", wordBreak: "break-all" as const };

export function JobProgress() {
  const [job, setJob] = useState<Job | null>(null);
  useEffect(() => {
    importStatus().then(setJob).catch(() => {});
    const on = (j: Job) => setJob(j);
    addEventListener("import", on);
    return () => removeEventListener("import", on);
  }, []);
  if (!job || job.state === "idle") return null;
  const pct = job.bytes ? Math.round((100 * (job.bytes_done ?? 0)) / job.bytes) : 0;
  const s = job.stats;
  return (
    <div style={{ ...card, border: "1px solid #3d4450" }}>
      {job.state === "running" ? (
        <>
          <div>
            {job.kind === "inbox" ? "Sorting the inbox" : "Importing"}: {job.done ?? 0} of {plural(job.files ?? 0, "file")}
            {job.bytes ? ` · ${size(job.bytes_done ?? 0)} of ${size(job.bytes)} (${pct}%)` : ""}
          </div>
          <div style={{ height: "6px", background: "#1a1c22", borderRadius: "3px", margin: "8px 0" }}>
            <div style={{ width: `${pct}%`, height: "100%", background: "#1a9fff", borderRadius: "3px" }} />
          </div>
          <div style={{ ...small, ...dim }}>{job.current}</div>
          <DialogButton style={{ width: "auto", marginTop: "8px" }} onClick={() => act(importCancel, "Cancelling failed")}>
            Cancel
          </DialogButton>
        </>
      ) : (
        <div>
          {job.state === "done" ? "Done" : job.state === "cancelled" ? "Cancelled" : "It failed"}
          {s && (
            <span style={dim}>
              {" · "}
              {plural(Object.values(s.games).reduce((a, b) => a + b, 0), "game")} sorted, {plural(s.bios.length, "BIOS file", "BIOS files")}
              {s.identical ? `, ${s.identical} already there` : ""}
              {s.unsorted ? `, ${s.unsorted} not recognised (below)` : ""}
            </span>
          )}
          {job.error && <div style={{ ...small, ...warn }}>{job.error}</div>}
        </div>
      )}
    </div>
  );
}

export function InboxSection({ ov }: { ov: Overview }) {
  const internal = ov.storages.find((s) => s.internal);
  return (
    <div style={card}>
      <h3 style={h}>1. Copy them into the inbox</h3>
      <p style={{ ...small, margin: "0 0 8px" }}>
        Put ROMs and BIOS files (zipped or not, any folder layout) into the <b>inbox</b>. They're sorted into the right system's folder on
        their own within a minute: you don't need to know which folder a game goes in.
      </p>
      <div style={mono}>{internal ? `${internal.emulation}/inbox` : "~/Emulation/inbox"}</div>
      <div style={{ ...small, ...dim, marginTop: "6px" }}>
        On a card: <span style={mono}>Emulation/inbox</span> on the card. Desktop Mode's file manager has both. Games already sorted go
        straight into <span style={mono}>Emulation/roms/&lt;system&gt;</span>.
      </div>
      <Focusable style={{ display: "flex", gap: "8px", marginTop: "10px" }} flow-children="horizontal">
        <DialogButton style={{ width: "auto" }} onClick={() => act(inboxNow, "Sorting failed")}>
          Sort the inbox now
        </DialogButton>
      </Focusable>
      <ToggleField
        label="Sort the inbox on its own"
        checked={ov.settings.auto_inbox}
        onChange={(v) => act(() => setSettings({ auto_inbox: v }), "Saving failed")}
      />
      <Unsorted systems={ov.systems.map((s) => ({ id: s.id, name: s.name }))} />
    </div>
  );
}

function Unsorted({ systems }: { systems: { id: string; name: string }[] }) {
  const [list, reload] = usePoll(unsorted, 15000);
  if (!list || !list.length) return null;
  const names = Object.fromEntries(systems.map((s) => [s.id, s.name]));
  return (
    <div style={{ marginTop: "10px" }}>
      <div style={{ ...small, ...warn }}>Not recognised: pick the system of each</div>
      {list.map((u) => {
        const likely = u.systems.length ? u.systems : systems.map((s) => s.id);
        return (
          <DropdownItem
            key={u.id}
            label={u.name}
            description={u.storage ? `${size(u.size)} · on ${u.storage}` : size(u.size)}
            rgOptions={[{ data: "", label: "Which system?" }, ...likely.map((s) => ({ data: s, label: names[s] ?? s }))]}
            selectedOption=""
            onChange={(o) => o.data && act(async () => (await assign(u.id, o.data), reload()), "Sorting it failed")}
          />
        );
      })}
    </div>
  );
}

export function CardsSection() {
  const [list, reload] = usePoll(media, 0);
  useEffect(() => {
    const on = () => reload();
    addEventListener("media", on);
    return () => removeEventListener("media", on);
  }, []);
  return (
    <div style={card}>
      <h3 style={h}>2. Use a card or USB stick</h3>
      <p style={{ ...small, margin: "0 0 8px" }}>
        Put in a card or stick with games on it. Emulation offers to copy them in (sorted), or a card can keep its games and play them from
        there: set it up and copy games into its <span style={mono}>Emulation/inbox</span>.
      </p>
      {list && list.length === 0 && <div style={{ ...small, ...dim }}>No card or stick is in.</div>}
      {list?.map((m) => (
        <Field
          key={m.path}
          label={m.label}
          description={
            m.set_up
              ? "Set up: its games are in your library and play from the card"
              : m.games_total || m.bios
                ? [m.games_total && plural(m.games_total, "game"), m.bios && plural(m.bios, "BIOS file", "BIOS files"), size(m.bytes)]
                    .filter(Boolean)
                    .join(" · ")
                : "No games found on it"
          }
        >
          <Focusable style={{ display: "flex", gap: "6px" }} flow-children="horizontal">
            {!m.set_up && (m.games_total > 0 || m.bios > 0) && (
              <DialogButton style={{ width: "auto", minWidth: 0 }} onClick={() => act(() => importStart(m.path, "copy", "internal"), "Importing failed")}>
                Copy in
              </DialogButton>
            )}
            {!m.set_up && (
              <DialogButton style={{ width: "auto", minWidth: 0 }} onClick={() => act(async () => (await setUpCard(m.path), reload()), "Setting it up failed")}>
                Play from the card
              </DialogButton>
            )}
          </Focusable>
        </Field>
      ))}
    </div>
  );
}

export function Qr({ text }: { text: string }) {
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  return (
    <div
      style={{ background: "white", padding: "8px", borderRadius: "4px", lineHeight: 0, flex: "none" }}
      dangerouslySetInnerHTML={{ __html: qr.createSvgTag({ cellSize: 5, margin: 2, scalable: false }) }}
    />
  );
}

export function UploadSection() {
  const [u, setU] = useState<Upload | null>(null);
  useEffect(() => {
    uploadStatus().then(setU).catch(() => {});
    const on = (x: Upload) => setU(x);
    addEventListener("upload", on);
    return () => removeEventListener("upload", on);
  }, []);
  const on = u?.state === "on" || u?.state === "locked";
  const url = u?.urls?.[0] ?? "";
  return (
    <div style={card}>
      <h3 style={h}>3. Send them from your phone or PC</h3>
      {!on ? (
        <>
          <p style={{ ...small, margin: "0 0 8px" }}>
            Opens a page on your Wi-Fi to drop files on from a phone's or PC's browser. Only someone with the PIN shown here can use it, and it
            closes after 10 minutes without use.
          </p>
          <DialogButton style={{ width: "auto" }} onClick={() => act(async () => setU(await uploadStart()), "Starting the upload page failed")}>
            Start the upload page
          </DialogButton>
        </>
      ) : (
        <div style={{ display: "flex", gap: "20px", alignItems: "center" }}>
          {url && <Qr text={url} />}
          <div style={{ minWidth: 0 }}>
            <div style={small}>Scan the code, or open this address on a device on the same Wi-Fi:</div>
            {u?.urls?.map((x) => (
              <div key={x} style={{ ...mono, fontSize: "15px", margin: "2px 0" }}>
                {x}
              </div>
            ))}
            <div style={{ margin: "8px 0 2px" }}>
              PIN: <span style={{ fontSize: "28px", fontWeight: 700, letterSpacing: "6px", fontVariantNumeric: "tabular-nums" }}>{u?.pin}</span>
            </div>
            {u?.state === "locked" && <div style={{ ...small, ...warn }}>Too many wrong PINs: stop it and start it again for a new PIN.</div>}
            {!!u?.uploaded && (
              <div style={{ ...small, ...good }}>
                {plural(u.uploaded, "file")} received{u.last ? `, last ${u.last}` : ""}
              </div>
            )}
            <DialogButton style={{ width: "auto", marginTop: "8px" }} onClick={() => act(uploadStop, "Stopping failed")}>
              Stop
            </DialogButton>
          </div>
        </div>
      )}
    </div>
  );
}

function PasswordModal({ onSet, closeModal }: { onSet: (p: string) => void; closeModal?: () => void }) {
  const [p, setP] = useState("");
  return (
    <ModalRoot closeModal={closeModal}>
      <h3 style={{ marginTop: 0 }}>A password for the share</h3>
      <p style={small}>At least 8 characters. Your PC asks for it the first time it opens the share.</p>
      <TextField label="Password" bIsPassword value={p} onChange={(e) => setP(e.target.value)} />
      <DialogButton
        disabled={p.length < 8}
        style={{ marginTop: "12px" }}
        onClick={() => {
          onSet(p);
          closeModal?.();
        }}
      >
        Turn the share on
      </DialogButton>
    </ModalRoot>
  );
}

export function ShareSection() {
  const [s, setS] = useState<Share | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    shareStatus().then(setS).catch((e) => setErr(errorText(e)));
  }, []);
  const enable = (pw: string) => act(async () => setS(await shareEnable(pw)), "Turning the share on failed");
  const disable = () =>
    showModal(
      <ConfirmModal
        strTitle="Turn the network share off?"
        strDescription="Computers on your network can't open the Kettle share any more. Your games stay where they are."
        strOKButtonText="Turn off"
        onOK={() => act(async () => setS(await shareDisable()), "Turning the share off failed")}
      />,
    );
  return (
    <div style={card}>
      <h3 style={h}>4. Open it as a network folder</h3>
      <p style={{ ...small, margin: "0 0 8px" }}>
        Shares the Emulation folder with the computers on your network (Windows, macOS, Linux), so you can copy whole collections in with
        your PC's file manager: copy into <b>inbox</b> to have them sorted. Off until you turn it on.
      </p>
      {err && <div style={{ ...small, ...warn }}>{err}</div>}
      {s &&
        (s.enabled ? (
          <>
            <div style={{ ...small, ...(s.active ? good : warn) }}>{s.active ? "On" : "On, but the file server isn't running"}</div>
            <div style={{ ...small, marginTop: "4px" }}>
              User <b>{s.user}</b>, with the password you set. Open:
            </div>
            {s.urls.map((x) => (
              <div key={x} style={mono}>
                {x}
              </div>
            ))}
            <DialogButton style={{ width: "auto", marginTop: "8px" }} onClick={disable}>
              Turn off
            </DialogButton>
          </>
        ) : (
          <DialogButton style={{ width: "auto" }} onClick={() => showModal(<PasswordModal onSet={enable} />)}>
            Turn on…
          </DialogButton>
        ))}
    </div>
  );
}

export function AddTab({ ov }: { ov: Overview }) {
  return (
    <div style={{ maxWidth: "820px" }}>
      <p style={{ ...small, ...dim, marginTop: 0 }}>
        Any of these four ways works; games then show up in your Steam library by themselves, in a collection per system. BIOS files are
        recognised wherever you put them. Kettle never comes with games or BIOS files: use your own.
      </p>
      <JobProgress />
      <InboxSection ov={ov} />
      <CardsSection />
      <UploadSection />
      <ShareSection />
    </div>
  );
}
