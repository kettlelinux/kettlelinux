// A paired PC's page: its games (each one plays through its own Steam shortcut, added on the
// first play or with X), how it streams (a preset or custom settings, for all of its games), and
// the PC itself (wake it, unpair).
import {
  ConfirmModal,
  DialogButton,
  DropdownItem,
  Field,
  Focusable,
  Navigation,
  SidebarNavigation,
  SliderField,
  ToggleField,
  showModal,
  useParams,
} from "@decky/ui";
import { useEffect, useMemo, useState } from "react";
import { FaCog, FaDesktop, FaGamepad } from "react-icons/fa";
import { App, Host, Preset, Settings, SettingsInfo, apps, boxart, forget, hosts, setSettings, settings, wake } from "./api";
import { status } from "./page";
import { addShortcut, inLibrary, play, removeShortcut } from "./shortcuts";
import { HOST_ROUTE, ROUTE, act, dim, errorText, small, usePoll } from "./ui";

const CSS = `
.kettle-ml-grid { display: grid; grid-template-columns: repeat(auto-fill, 130px); gap: 12px; padding: 8px 0 24px; }
.kettle-ml-card { border-radius: 6px; overflow: hidden; background: #23262e; transition: transform 0.1s; }
.kettle-ml-card.gpfocus { outline: 3px solid #fff; transform: scale(1.04); }
.kettle-ml-card .art { width: 100%; aspect-ratio: 3 / 4; object-fit: cover; display: flex; align-items: center; justify-content: center; background: #1a1c22; font-size: 40px; color: #3d4450; }
.kettle-ml-card .t { padding: 6px 8px 2px; font-size: 13px; line-height: 17px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kettle-ml-card .s { padding: 0 8px 6px; font-size: 11px; color: #8b929a; height: 14px; }
`;

// box art already fetched, by "uuid/app id", so going back to the tab doesn't wait
const arts: Record<string, string> = {};

function GameCard({ uuid, app, onChange }: { uuid: string; app: App; onChange: () => void }) {
  const key = `${uuid}/${app.id}`;
  const [art, setArt] = useState(arts[key] ?? "");
  useEffect(() => {
    if (!(key in arts)) boxart(uuid, app.id).then((a) => setArt((arts[key] = a))).catch(() => {});
  }, [key]);
  const listed = inLibrary(app.shortcut);
  const start = () =>
    act(async () => {
      const sid = await addShortcut(uuid, app.name, app.id, app.shortcut);
      if (!listed) onChange();
      await play(sid);
    }, `Starting ${app.name} failed`);
  const toggleLibrary = () =>
    act(async () => {
      if (listed) await removeShortcut(uuid, app.name, app.shortcut);
      else await addShortcut(uuid, app.name, app.id, app.shortcut);
      onChange();
    }, listed ? "Removing it from the library failed" : "Adding it to the library failed");
  return (
    <Focusable
      className="kettle-ml-card"
      onActivate={start}
      onClick={start}
      onSecondaryButton={toggleLibrary}
      onSecondaryActionDescription={listed ? "Remove from Library" : "Add to Library"}
      onOKActionDescription="Play"
    >
      {art ? <img className="art" src={art} /> : <div className="art"><FaGamepad /></div>}
      <div className="t">{app.name}</div>
      <div className="s">{listed ? "In your library" : ""}</div>
    </Focusable>
  );
}

function GamesTab({ host }: { host: Host }) {
  const [list, reload, error] = usePoll(() => apps(host.uuid), 0);
  const [adding, setAdding] = useState(false);
  if (!host.online) return <OfflineNote host={host} />;
  if (error) return <p>Getting the games failed: {error}</p>;
  if (!list) return <p>Loading the games…</p>;
  const missing = list.filter((a) => !inLibrary(a.shortcut));
  const addAll = () =>
    act(async () => {
      setAdding(true);
      try {
        for (const a of missing) await addShortcut(host.uuid, a.name, a.id, a.shortcut);
      } finally {
        setAdding(false);
        reload();
      }
    }, "Adding to the library failed");
  return (
    <div>
      <style>{CSS}</style>
      <p style={{ ...small, ...dim, margin: "0 0 8px" }}>
        A to play, X to add to or remove from your Steam library. The games are the apps set up in {host.apollo ? "Apollo" : "Sunshine"} on
        the PC.
      </p>
      {missing.length > 0 && (
        <DialogButton style={{ width: "auto", minWidth: 0, marginBottom: "8px" }} disabled={adding} onClick={addAll}>
          {adding ? "Adding…" : `Add all ${missing.length} to the library`}
        </DialogButton>
      )}
      <Focusable className="kettle-ml-grid">
        {list.map((a) => (
          <GameCard key={a.id} uuid={host.uuid} app={a} onChange={reload} />
        ))}
      </Focusable>
    </div>
  );
}

function OfflineNote({ host }: { host: Host }) {
  return (
    <div>
      <p>{host.name} isn't answering. Turn it on, or check that Sunshine or Apollo is running.</p>
      {host.can_wake && (
        <DialogButton style={{ width: "auto" }} onClick={() => act(() => wake(host.uuid), "Waking it failed")}>
          Wake {host.name}
        </DialogButton>
      )}
    </div>
  );
}

const RESOLUTIONS = ["native", "1280x720", "1920x1080", "2560x1440", "3840x2160"];
const resLabel = (r: string, dev: SettingsInfo["device"]) =>
  r === "native" ? `This screen (${dev.width} × ${dev.height})` : r.replace("x", " × ");
const shortRes = (r: string) => ({ "1280x720": "720p", "1920x1080": "1080p", "2560x1440": "1440p", "3840x2160": "4K" })[r] ?? r;

function SettingsTab({ host }: { host: Host }) {
  const [info, setInfo] = useState<SettingsInfo | null>(null);
  const [error, setError] = useState("");
  // the slider's value while it moves: saved once it has stopped for a moment
  const [bitrate, setBitrate] = useState<number | null>(null);
  useEffect(() => {
    if (bitrate === null) return;
    const t = setTimeout(() => act(async () => setInfo(await setSettings(host.uuid, { bitrate })), "Saving failed"), 400);
    return () => clearTimeout(t);
  }, [bitrate]);
  useEffect(() => {
    settings(host.uuid).then(setInfo).catch((e) => setError(errorText(e)));
  }, [host.uuid]);
  if (error) return <p>{error}</p>;
  if (!info) return null;
  const { settings: s, device: dev } = info;
  const set = (c: Partial<Settings>) => act(async () => setInfo(await setSettings(host.uuid, c)), "Saving failed");
  const native = `${dev.width}x${dev.height}`;
  const presets: { data: Preset; label: string }[] = [
    { data: "latency", label: `Lowest latency: ${shortRes(native)}, ${dev.max_fps} fps` },
    { data: "balanced", label: `Balanced: ${shortRes(native)}, 60 fps` },
    { data: "battery", label: "Battery saver: 720p, 60 fps" },
    { data: "custom", label: "Custom" },
  ];
  const fpsOptions = [...new Set([30, 60, ...dev.rates.filter((r) => r <= 144)])].sort((a, b) => a - b);
  return (
    <div style={{ maxWidth: "720px" }}>
      <p style={{ ...small, ...dim, marginTop: 0 }}>For every game from {host.name}, from the next time one starts.</p>
      <DropdownItem
        label="Stream quality"
        description="Lowest latency matches this screen's fastest refresh rate: smoother and quicker to respond, but it needs a strong Wi-Fi signal and more battery."
        rgOptions={presets}
        selectedOption={s.preset}
        onChange={(o) => set({ preset: o.data })}
      />
      {s.preset === "custom" && (
        <>
          <DropdownItem
            label="Resolution"
            rgOptions={RESOLUTIONS.map((r) => ({ data: r, label: resLabel(r, dev) }))}
            selectedOption={RESOLUTIONS.includes(s.resolution) ? s.resolution : "native"}
            onChange={(o) => set({ resolution: o.data })}
          />
          <DropdownItem
            label="Frame rate"
            rgOptions={fpsOptions.map((f) => ({ data: f, label: `${f} fps` }))}
            selectedOption={s.fps || dev.max_fps}
            onChange={(o) => set({ fps: o.data })}
          />
          <SliderField
            label="Bitrate"
            description={
              (bitrate ?? s.bitrate) ? `${(bitrate ?? s.bitrate) / 1000} Mbps` : "Automatic: Moonlight picks it for the resolution and frame rate"
            }
            value={(bitrate ?? s.bitrate) / 1000}
            min={0}
            max={150}
            step={5}
            notchCount={2}
            notchLabels={[{ notchIndex: 0, label: "Auto" }, { notchIndex: 1, label: "150" }]}
            onChange={(v) => setBitrate(v * 1000)}
          />
        </>
      )}
      <DropdownItem
        label="Video codec"
        description="HEVC needs less bitrate for the same picture. Both are decoded in hardware."
        rgOptions={[
          { data: "auto", label: "Automatic" },
          { data: "HEVC", label: "HEVC (H.265)" },
          { data: "H.264", label: "H.264" },
        ]}
        selectedOption={s.codec}
        onChange={(o) => set({ codec: o.data })}
      />
      <DropdownItem
        label="Audio"
        rgOptions={[
          { data: "stereo", label: "Stereo" },
          { data: "5.1-surround", label: "5.1 surround" },
          { data: "7.1-surround", label: "7.1 surround" },
        ]}
        selectedOption={s.audio}
        onChange={(o) => set({ audio: o.data })}
      />
      <ToggleField
        label="Send the gyro to the PC"
        description="Moonlight uses this device's controller directly, so games on the PC get its motion sensors (it shows up there as a DualShock 4 or DualSense). Steam Input layouts don't apply to the stream."
        checked={s.raw_pad}
        onChange={(v) => set({ raw_pad: v })}
      />
      <ToggleField label="Show the stream's stats" description="Frame rate, latency and decoding time over the game" checked={s.overlay} onChange={(v) => set({ overlay: v })} />
      <ToggleField label="Play sound on the PC too" checked={s.host_audio} onChange={(v) => set({ host_audio: v })} />
      <ToggleField label="Close the game on the PC when the stream ends" checked={s.quit_after} onChange={(v) => set({ quit_after: v })} />
      <ToggleField
        label="Nintendo button layout"
        description="Swaps A with B and X with Y"
        checked={s.swap_buttons}
        onChange={(v) => set({ swap_buttons: v })}
      />
    </div>
  );
}

function PcTab({ host, reload }: { host: Host; reload: () => void }) {
  const [text] = status(host);
  const unpair = () =>
    showModal(
      <ConfirmModal
        strTitle={`Unpair ${host.name}?`}
        strDescription="Its games leave your Steam library. To stream from it again, pair with it again. You can also remove this device from the PC's list in Sunshine or Apollo."
        strOKButtonText="Unpair"
        onOK={() =>
          act(async () => {
            const gone = await forget(host.uuid);
            for (const appid of gone) if (inLibrary(appid)) SteamClient.Apps.RemoveShortcut(appid);
            Navigation.Navigate(ROUTE);
          }, "Unpairing failed")
        }
      />,
    );
  return (
    <div style={{ maxWidth: "720px" }}>
      <Field label="Status">{text}</Field>
      <Field label="Address">{host.address || "?"}</Field>
      <Field label="Host app">{host.online ? (host.apollo ? "Apollo" : "Sunshine") : "?"}</Field>
      {host.can_wake && (
        <Field label="Wake the PC" description="Turns it on over the network, if its Wake-on-LAN is set up">
          <DialogButton style={{ width: "auto" }} onClick={() => act(() => wake(host.uuid).then(() => setTimeout(reload, 15000)), "Waking it failed")}>
            Wake
          </DialogButton>
        </Field>
      )}
      <Field label="Unpair" description="Forget this PC on this device">
        <DialogButton style={{ width: "auto" }} onClick={unpair}>
          Unpair
        </DialogButton>
      </Field>
    </div>
  );
}

export function HostPage() {
  const { uuid } = useParams<{ uuid: string }>();
  const [list, reload] = usePoll(() => hosts(false), 15000);
  const host = list?.find((h) => h.uuid === uuid);
  const pages = useMemo(
    () =>
      host
        ? [
            // keyed by whether it's online: the games load again once an offline PC answers
            {
              title: "Games",
              route: `${HOST_ROUTE}/${uuid}/games`,
              icon: <FaGamepad />,
              content: <GamesTab key={`${host.uuid}-${host.online}`} host={host} />,
            },
            { title: "Stream settings", route: `${HOST_ROUTE}/${uuid}/settings`, icon: <FaCog />, content: <SettingsTab host={host} /> },
            { title: "PC", route: `${HOST_ROUTE}/${uuid}/pc`, icon: <FaDesktop />, content: <PcTab host={host} reload={reload} /> },
          ]
        : [],
    [host?.uuid, host?.online, host?.busy, host?.address],
  );
  if (!list) return <div style={{ marginTop: "40px", padding: "16px 24px" }}>Loading…</div>;
  if (!host) return <div style={{ marginTop: "40px", padding: "16px 24px" }}>This PC isn't paired.</div>;
  return (
    <div style={{ marginTop: "40px", height: "calc(100% - 40px)" }}>
      {/* keyed by PC: going from one PC's page to another's starts afresh */}
      <SidebarNavigation key={uuid} title={host.name} showTitle pages={pages} />
    </div>
  );
}
