import { DialogButton, DropdownItem, Field, Focusable, ModalRoot, TextField, showModal } from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";
import qrcode from "qrcode-generator";
import { CATALOG, Profile, describe, dllError, envError } from "./catalog";
import { Game, Saved, deleteProfile, listProfiles, saveProfile, submit } from "./api";

const small: React.CSSProperties = { fontSize: "12px", lineHeight: "16px" };
const error: React.CSSProperties = { ...small, color: "#e2794f", minHeight: "16px" };
const row: React.CSSProperties = { display: "flex", gap: "8px", marginTop: "12px" };

export function ProfilesModal({ profile, onLoad, closeModal }: { profile: Profile; onLoad: (p: Profile) => void; closeModal?: () => void }) {
  const [saved, setSaved] = useState<Saved[] | null>(null);
  const [name, setName] = useState("");
  useEffect(() => {
    listProfiles().then(setSaved);
  }, []);
  return (
    <ModalRoot closeModal={closeModal}>
      <h3 style={{ marginTop: 0 }}>Saved profiles</h3>
      <p style={small}>Save this game's settings under a name, to load them on other games. The Proton version isn't saved.</p>
      <TextField label="Name" value={name} onChange={(e) => setName(e.target.value)} />
      <div style={row}>
        <DialogButton disabled={!name.trim()} onClick={() => saveProfile(name, profile).then(setSaved).then(() => setName(""))}>
          Save current settings
        </DialogButton>
      </div>
      <Focusable style={{ marginTop: "16px", maxHeight: "50vh", overflowY: "auto" }}>
        {saved?.length === 0 && <div style={small}>No saved profiles yet.</div>}
        {saved?.map((p) => (
          <Field key={p.name} label={p.name} description={describe(p).join(", ") || "Everything default"} childrenLayout="below">
            <div style={{ display: "flex", gap: "8px" }}>
              <DialogButton
                onClick={() => {
                  onLoad(p);
                  closeModal?.();
                }}
              >
                Load
              </DialogButton>
              <DialogButton onClick={() => deleteProfile(p.name).then(setSaved)}>Delete</DialogButton>
            </div>
          </Field>
        ))}
      </Focusable>
    </ModalRoot>
  );
}

export function AddEnvModal({ onAdd, closeModal }: { onAdd: (name: string, value: string) => void; closeModal?: () => void }) {
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const err = name ? envError(name, value) : null;
  return (
    <ModalRoot closeModal={closeModal}>
      <h3 style={{ marginTop: 0 }}>Add a variable</h3>
      <p style={small}>An environment variable for the game: {CATALOG.custom.env_prefixes.join(", ")}…</p>
      <TextField label="Name" value={name} onChange={(e) => setName(e.target.value.toUpperCase().trim())} />
      <TextField label="Value" value={value} onChange={(e) => setValue(e.target.value.trim())} />
      <div style={error}>{err}</div>
      <div style={row}>
        <DialogButton
          disabled={!name || !!err}
          onClick={() => {
            onAdd(name, value);
            closeModal?.();
          }}
        >
          Add
        </DialogButton>
        <DialogButton onClick={closeModal}>Cancel</DialogButton>
      </div>
    </ModalRoot>
  );
}

export function AddDllModal({ onAdd, closeModal }: { onAdd: (dll: string, mode: string) => void; closeModal?: () => void }) {
  const [dll, setDll] = useState("");
  const [mode, setMode] = useState("n,b");
  const name = dll.toLowerCase().trim().replace(/\.dll$/, "");
  const err = name ? dllError(name) : null;
  return (
    <ModalRoot closeModal={closeModal}>
      <h3 style={{ marginTop: 0 }}>Add a DLL override</h3>
      <p style={small}>Which copy of a DLL Wine loads: the game's own (native) or Wine's (builtin). For mods such as dinput8 or dxgi.</p>
      <TextField label="DLL" value={dll} onChange={(e) => setDll(e.target.value)} />
      <DropdownItem
        label="Load"
        rgOptions={CATALOG.custom.dll_modes.map((m) => ({ data: m.value, label: m.label }))}
        selectedOption={mode}
        onChange={(o) => setMode(o.data)}
      />
      <div style={error}>{err}</div>
      <div style={row}>
        <DialogButton
          disabled={!name || !!err}
          onClick={() => {
            onAdd(name, mode);
            closeModal?.();
          }}
        >
          Add
        </DialogButton>
        <DialogButton onClick={closeModal}>Cancel</DialogButton>
      </div>
    </ModalRoot>
  );
}

// A link as a QR code, to open on a phone
export function LinkModal({ title, text, url, closeModal }: { title: string; text: string; url: string; closeModal?: () => void }) {
  const qr = qrcode(0, "M");
  qr.addData(url);
  qr.make();
  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ display: "flex", gap: "24px", alignItems: "center" }}>
        <div
          style={{ background: "white", padding: "8px", borderRadius: "4px", lineHeight: 0 }}
          dangerouslySetInnerHTML={{ __html: qr.createSvgTag({ cellSize: 5, margin: 2, scalable: false }) }}
        />
        <div>
          <h3 style={{ marginTop: 0 }}>{title}</h3>
          <p>{text}</p>
          <p style={{ fontFamily: "monospace", wordBreak: "break-all" }}>{url}</p>
          <DialogButton onClick={closeModal}>Done</DialogButton>
        </div>
      </div>
    </ModalRoot>
  );
}

export function ShareModal({ appid, name, g, onShared, closeModal }: { appid: number; name: string; g: Game; onShared: () => void; closeModal?: () => void }) {
  const [rating, setRating] = useState("great");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const what = describe(g);
  return (
    <ModalRoot closeModal={closeModal}>
      <h3 style={{ marginTop: 0 }}>Share {name}'s settings</h3>
      <p style={small}>
        They go to the Kettle game database as known good settings, where anyone can see them. Sent: the game, these settings
        and the Proton version, your device model and Kettle build, a random id for this device (so it's counted once), and
        your note. Nothing else.
      </p>
      <div style={{ ...small, fontFamily: "monospace", marginBottom: "8px" }}>{what.join(", ") || "Everything default (works as is)"}</div>
      <DropdownItem
        label="How well does it play?"
        rgOptions={[
          { data: "great", label: "Great: no problems" },
          { data: "playable", label: "Playable: minor problems" },
        ]}
        selectedOption={rating}
        onChange={(o) => setRating(o.data)}
      />
      <TextField label="Note (optional)" value={notes} onChange={(e) => setNotes(e.target.value.slice(0, 500))} />
      <div style={row}>
        <DialogButton
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const out = await submit(appid, name, rating, notes);
              onShared();
              closeModal?.();
              showModal(
                <LinkModal
                  title="Settings shared"
                  text="Thanks! They show as community settings until they're verified. Scan to see the game's page."
                  url={out.url}
                />,
              );
            } catch (e: any) {
              setBusy(false);
              toaster.toast({ title: "Game Settings", body: String(e?.message ?? e) });
            }
          }}
        >
          Share
        </DialogButton>
        <DialogButton onClick={closeModal}>Cancel</DialogButton>
      </div>
    </ModalRoot>
  );
}
