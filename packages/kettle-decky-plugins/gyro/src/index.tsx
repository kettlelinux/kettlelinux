import { DropdownItem, Field, PanelSection, PanelSectionRow, staticClasses } from "@decky/ui";
import { callable, definePlugin } from "@decky/api";
import { useEffect, useState } from "react";
import { MdScreenRotation } from "react-icons/md";
import { runningAppId } from "../../shared/GamePicker";

type Mode = "games" | "always" | "off";
type State = {
  service: boolean;
  available: boolean;
  mode?: Mode;
  game?: boolean;
  streaming?: boolean;
  rate?: number;
  gyro?: number;
};

const get = callable<[], State>("get");
const setMode = callable<[mode: Mode], State>("set_mode");
const setGame = callable<[running: boolean], void>("set_game");

const MODES: { data: Mode; label: string }[] = [
  { data: "games", label: "While a game runs" },
  { data: "always", label: "Always" },
  { data: "off", label: "Off" },
];

const small = { fontSize: "12px", color: "#b8bcbf", lineHeight: "1.4" };

// Tell kettle-motiond whether a game runs: the sensors stream only then (in the default mode)
function syncGame(stopped?: number) {
  const a = runningAppId();
  setGame(a !== null && a !== stopped).catch(() => {});
}

// How fast the device is turning, as a bar: full at 180 degree/s
function Meter({ dps }: { dps: number }) {
  const pct = Math.min(100, (dps / 180) * 100);
  return (
    <div style={{ height: "8px", borderRadius: "4px", background: "#23262e", overflow: "hidden" }}>
      <div style={{ width: `${pct}%`, height: "100%", background: "#1a9fff", transition: "width 0.1s" }} />
    </div>
  );
}

function Content() {
  const [s, setS] = useState<State | null>(null);
  useEffect(() => {
    let live = true;
    const poll = () => get().then((r) => live && setS(r)).catch(() => {});
    poll();
    const t = setInterval(poll, 150);
    return () => {
      live = false;
      clearInterval(t);
    };
  }, []);
  if (!s) return null;
  if (!s.service || !s.available)
    return (
      <PanelSection title="Gyro">
        <PanelSectionRow>
          <div style={small}>
            {s.service
              ? "Waiting for the motion sensors to start…"
              : "This device has no motion sensors Kettle can read (kettle-motiond isn't running)."}
          </div>
        </PanelSectionRow>
      </PanelSection>
    );

  const status = s.streaming
    ? `On, ${Math.round(s.rate ?? 0)} Hz`
    : s.mode === "off"
      ? "Off"
      : "Idle until a game starts";

  return (
    <PanelSection title="Gyro">
      <PanelSectionRow>
        <DropdownItem label="Motion sensors" rgOptions={MODES} selectedOption={s.mode}
          onChange={(o) => {
            setS({ ...s, mode: o.data });
            setMode(o.data).then(setS).catch(() => {});
          }} />
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={small}>
          {s.mode === "games" && "The gyro and accelerometer run only while a game is open, to save power."}
          {s.mode === "always" && "The gyro and accelerometer run all the time, in the Steam UI too (about 0.05 W)."}
          {s.mode === "off" && "The controller has no motion: gyro controls in Steam Input do nothing."}
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <Field label="Status" bottomSeparator="none">{status}</Field>
      </PanelSectionRow>
      {s.streaming && (
        <PanelSectionRow>
          <div style={{ padding: "0 0 8px" }}>
            <div style={{ ...small, marginBottom: "6px" }}>Move the device to test it</div>
            <Meter dps={s.gyro ?? 0} />
          </div>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <div style={small}>
          Gyro aiming is set per game in Steam Input: the game's controller settings, then Gyro Behavior
          (for example "As Mouse" or "As Joystick").
        </div>
      </PanelSectionRow>
    </PanelSection>
  );
}

export default definePlugin(() => {
  syncGame();
  const lifetime = SteamClient.GameSessions.RegisterForAppLifetimeNotifications((n: { unAppID: number; bRunning: boolean }) => {
    if (n.bRunning) setGame(true).catch(() => {});
    else setTimeout(() => syncGame(n.unAppID), 1000);
  });
  return {
    name: "Gyro",
    titleView: <div className={staticClasses.Title}>Gyro</div>,
    content: <Content />,
    icon: <MdScreenRotation />,
    onDismount: () => lifetime.unregister(),
  };
});
