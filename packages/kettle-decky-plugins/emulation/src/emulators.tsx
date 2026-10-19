// The Emulators tab: the emulators from Flathub (RetroArch and the standalone ones, installed for
// this user: install, update, remove) and RetroArch's cores from libretro's buildbot; "Install
// what my games need" for every system the library has games of. Kettle builds none of them.
// Get started (start.tsx) and the emulator choices (page.tsx) use installNeeded / offerInstall.
import { ConfirmModal, DialogButton, Field, Focusable, showModal } from "@decky/ui";
import { addEventListener, removeEventListener } from "@decky/api";
import { useEffect, useState } from "react";
import {
  Emulator,
  Emulators,
  Flatpak,
  NeededCore,
  Setup,
  coreDownload,
  coreRemove,
  emulators,
  flatpakSize,
  installNeeded as installNeededCall,
  setupCancel,
  setupStart,
} from "./api";
import { act, dim, good, plural, size, small, warn } from "./ui";

const page = { padding: "0 0 40px" };

// The setup job's progress, as the backend emits it ("setup" events)
export function useSetup(initial: Setup | null): Setup | null {
  const [job, setJob] = useState<Setup | null>(initial);
  useEffect(() => setJob(initial), [initial]);
  useEffect(() => {
    const l = addEventListener<[Setup]>("setup", (j) => setJob(j));
    return () => removeEventListener("setup", l);
  }, []);
  return job;
}

export function SetupRow({ job }: { job: Setup | null }) {
  if (!job || job.state === "idle") return null;
  if (job.state === "running") {
    const what = job.step?.startsWith("core:") ? `Downloading the ${job.step.slice(5)} core` : job.kind === "remove" ? "Removing" : job.kind === "update" ? "Updating" : "Installing";
    return (
      <Field label={`${what}…`} description={`${Math.round(job.percent ?? 0)}%${job.eta ? ` · ${job.eta} left` : ""}`}>
        <DialogButton style={{ width: "auto" }} onClick={() => act(setupCancel, "Cancelling failed")}>
          Cancel
        </DialogButton>
      </Field>
    );
  }
  if (job.state === "failed") return <p style={{ ...small, ...warn }}>That didn't work: {job.error}</p>;
  if (job.state === "done") return <p style={{ ...small, ...good }}>Done.</p>;
  return null;
}

// A yes to the terms of the cores whose licenses aren't free, then the install of everything the
// library's games need.
export function installNeeded(cores: NeededCore[], onStarted?: () => void) {
  const start = (accepted: string[]) => act(async () => (await installNeededCall(accepted), onStarted?.()), "Installing failed");
  const nonFree = cores.filter((c) => !c.free);
  if (!nonFree.length) {
    start([]);
    return;
  }
  showModal(
    <ConfirmModal
      strTitle="Some of these cores aren't free software"
      strDescription={
        <div>
          {nonFree.map((c) => (
            <p key={c.core}>
              <b>{c.name}</b>: {c.terms}
            </p>
          ))}
          <p>Accept their licenses and download them too, or install the rest without them.</p>
        </div>
      }
      strOKButtonText="Accept and download"
      strCancelButtonText="Without them"
      onOK={() => start(nonFree.map((c) => c.core))}
      onCancel={() => start([])}
    />,
  );
}

// An emulator that isn't installed yet: what installing it means (its Flatpak, and RetroArch's
// core), then the install
export function offerInstall(e: Emulator, onStarted?: () => void) {
  const apps = e.flatpak ? [e.flatpak] : [];
  const coreList = e.kind === "libretro" ? [e.core] : [];
  const go = () => act(async () => (await setupStart("install", apps, coreList, e.free ? [] : coreList), onStarted?.()), "Installing failed");
  showModal(
    <ConfirmModal
      strTitle={`Install ${e.name}?`}
      strDescription={
        <div>
          <p>
            {e.kind === "libretro"
              ? `It's a RetroArch core: RetroArch comes from Flathub if it isn't installed, the core from libretro's build server.`
              : `It comes from Flathub (${e.flatpak}).`}
          </p>
          {!e.free && <p>Its license ({e.license}) isn't free: by installing it you accept it.</p>}
          {e.experimental && <p style={warn}>Experimental: it may run slowly, or not at all, on this device.</p>}
          {e.needs.map((n) => (
            <p key={n.text} style={dim}>
              {n.text}
            </p>
          ))}
        </div>
      }
      strOKButtonText={e.free ? "Install" : "Accept and install"}
      onOK={go}
    />,
  );
}

function FlatpakRow({ f, busy, reload }: { f: Flatpak; busy: boolean; reload: () => void }) {
  const [bytes, setBytes] = useState(0);
  useEffect(() => {
    if (!f.installed) flatpakSize(f.id).then((s) => setBytes(s.download)).catch(() => {});
  }, [f.id, f.installed]);
  const run = (kind: "install" | "update" | "remove") => act(async () => (await setupStart(kind, [f.id], [], []), reload()), "That failed");
  const desc = [
    f.installed ? `${f.version || "installed"}${f.update ? " · update out" : ""}` : bytes ? `${size(bytes)} download` : "",
    f.systems.join(", "),
    f.license,
  ].filter(Boolean);
  return (
    <Field
      label={
        <span>
          {f.name}
          {f.experimental && <span style={{ ...small, ...warn }}> · experimental</span>}
        </span>
      }
      description={
        <span>
          {desc.join(" · ")}
          {f.needs.map((n) => (
            <div key={n.text} style={n.met === false && f.installed ? warn : dim}>
              {n.met === true ? "✓ " : n.met === false && f.installed ? "✗ " : ""}
              {n.text}
            </div>
          ))}
        </span>
      }
      childrenContainerWidth="max"
    >
      <Focusable style={{ display: "flex", gap: "6px" }} flow-children="horizontal">
        {!f.installed && (
          <DialogButton style={{ width: "auto", minWidth: 0 }} disabled={busy} onClick={() => run("install")}>
            Install
          </DialogButton>
        )}
        {f.update && (
          <DialogButton style={{ width: "auto", minWidth: 0 }} disabled={busy} onClick={() => run("update")}>
            Update
          </DialogButton>
        )}
        {f.removable && (
          <DialogButton
            style={{ width: "auto", minWidth: 0 }}
            disabled={busy}
            onClick={() =>
              showModal(
                <ConfirmModal
                  strTitle={`Remove ${f.name}?`}
                  strDescription="The app goes; its settings and data in its Flatpak folder stay, for if you install it again. Your games, saves in Emulation and BIOS files stay too."
                  strOKButtonText="Remove"
                  onOK={() => run("remove")}
                />,
              )
            }
          >
            Remove
          </DialogButton>
        )}
      </Focusable>
    </Field>
  );
}

export function EmulatorsTab({ reload: reloadAll }: { reload: () => void }) {
  const [info, setInfo] = useState<Emulators | null>(null);
  const [busyCore, setBusyCore] = useState("");
  const load = (updates = false) => emulators(updates).then(setInfo).catch(() => {});
  useEffect(() => {
    load(true);
  }, []);
  const job = useSetup(info?.job ?? null);
  useEffect(() => {
    if (job && job.state !== "running") (load(), reloadAll());
  }, [job?.state]);
  if (!info) return <p>Loading…</p>;
  const busy = job?.state === "running";
  const need = info.needed;
  const needCount = need.flatpaks.length + need.cores.length;
  const coreRow = (c: Emulators["cores"][number]) => (
    <Field
      key={c.core}
      label={c.name}
      description={`${c.systems.join(", ")}${c.free ? "" : ` · ${c.license}: ${c.terms}`}${c.missing.length ? ` · its ${c.missing.join(" and ")} folders are missing from Emulation/bios: download it again` : ""}`}
      childrenContainerWidth="max"
    >
      {c.installed ? (
        <DialogButton style={{ width: "auto" }} onClick={() => act(async () => (setInfo({ ...info, cores: await coreRemove(c.core) }), reloadAll()), "Removing failed")}>
          Remove
        </DialogButton>
      ) : (
        <DialogButton
          style={{ width: "auto" }}
          disabled={!!busyCore}
          onClick={() => {
            const get = () =>
              act(async () => {
                setBusyCore(c.core);
                try {
                  setInfo({ ...info, cores: await coreDownload(c.core, !c.free) });
                  reloadAll();
                } finally {
                  setBusyCore("");
                }
              }, "Downloading failed");
            if (c.free) {
              get();
              return;
            }
            showModal(
              <ConfirmModal
                strTitle={`Download ${c.name}?`}
                strDescription={`${c.terms} License: ${c.license}. By downloading it you accept that license.`}
                strOKButtonText="Accept and download"
                onOK={get}
              />,
            );
          }}
        >
          {busyCore === c.core ? "Downloading…" : "Download"}
        </DialogButton>
      )}
    </Field>
  );
  return (
    <div style={page}>
      <p style={{ ...small, marginTop: 0 }}>
        The emulators come from Flathub, from their own projects, and RetroArch's cores from libretro's build server; they update on their
        own schedule, apart from Kettle's. Kettle sets each one up with the same controls before it starts.
      </p>
      <SetupRow job={job} />
      {info.list_failed && <p style={{ ...small, ...warn }}>Flatpak couldn't say what's installed; this page shows it as soon as it can.</p>}
      <Field
        label="Install what my games need"
        description={
          needCount
            ? `${[need.flatpaks.length && plural(need.flatpaks.length, "app"), need.cores.length && plural(need.cores.length, "core")].filter(Boolean).join(" and ")} for ${plural(need.systems.length, "system")} you have games of`
            : "Every system you have games of has its emulator."
        }
      >
        <DialogButton style={{ width: "auto" }} disabled={busy || !needCount} onClick={() => installNeeded(need.cores, () => load())}>
          Install
        </DialogButton>
      </Field>
      <h3 style={{ margin: "16px 0 4px" }}>Emulators</h3>
      {info.flatpaks.map((f) => (
        <FlatpakRow key={f.id} f={f} busy={busy} reload={() => load()} />
      ))}
      <h3 style={{ margin: "16px 0 4px" }}>RetroArch's cores</h3>
      <p style={{ ...small, ...dim, margin: "0 0 4px" }}>They run in RetroArch; install it above first. A core whose license isn't free asks before it downloads.</p>
      {info.cores.map(coreRow)}
    </div>
  );
}
