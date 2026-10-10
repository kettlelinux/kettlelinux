// The System tab: what the device starts up in, the SSH server, and resetting the device
// (system.py in the backend). These were the Welcome window's up to 1.12.0-38.
import { ButtonItem, ConfirmModal, DropdownItem, PanelSection, PanelSectionRow, ToggleField, showModal } from "@decky/ui";
import { callable, toaster } from "@decky/api";
import { useEffect, useState } from "react";

type BootMode = "game" | "desktop";
type Ssh = { active: boolean; enabled: boolean; user: string; addresses: string[] };
type What = "settings" | "everything";
type ResetStatus = { pending: "none" | What; ufs_backup: boolean };

const bootMode = callable<[], BootMode | null>("boot_mode");
const setBootMode = callable<[mode: BootMode], void>("set_boot_mode");
const sshStatus = callable<[], Ssh>("ssh_status");
const setSsh = callable<[on: boolean], void>("set_ssh");
const resetStatus = callable<[], ResetStatus>("reset_status");
const reset = callable<[what: What], void>("reset");

const small = { fontSize: "12px", lineHeight: "16px" };
const red = { color: "#ff6b6b" };

async function act(f: () => Promise<unknown>, fail: string) {
  try {
    await f();
  } catch (e) {
    toaster.toast({ title: "Device Settings", body: `${fail}: ${e}` });
  }
}

// steamos-manager's default login mode; switching from the power menu only lasts until a reboot
const BOOT_MODES = [
  { data: "game" as BootMode, label: "Game Mode" },
  { data: "desktop" as BootMode, label: "Desktop" },
];

function StartUp() {
  const [mode, setMode] = useState<BootMode | null>(null);
  useEffect(() => {
    bootMode().then(setMode).catch(() => {});
  }, []);
  const choose = async (m: BootMode) => {
    const was = mode;
    setMode(m);
    try {
      await setBootMode(m);
    } catch (e) {
      setMode(was);
      toaster.toast({ title: "Device Settings", body: `Couldn't change the start-up mode: ${e}` });
    }
  };
  return (
    <PanelSectionRow>
      <DropdownItem
        label="Start up in"
        description="What Kettle opens when it turns on. Switching from the power menu lasts until the next restart."
        rgOptions={BOOT_MODES}
        selectedOption={mode}
        disabled={mode === null}
        onChange={(o) => choose(o.data)}
      />
    </PanelSectionRow>
  );
}

function RemoteAccess() {
  const [s, setS] = useState<Ssh | null>(null);
  const [busy, setBusy] = useState(false);
  const refresh = () => sshStatus().then(setS).catch(() => {});
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, []);
  if (!s) return null;
  const toggle = (on: boolean) => {
    setBusy(true);
    act(() => setSsh(on), on ? "Couldn't turn on the SSH server" : "Couldn't turn off the SSH server").finally(() => {
      setBusy(false);
      refresh();
    });
  };
  return (
    <>
      <PanelSectionRow>
        <ToggleField
          label="SSH server"
          checked={s.active}
          disabled={busy}
          onChange={toggle}
          description={
            !s.active
              ? "Lets another computer on your network log in, for copying files or a terminal. Change the password first, in the desktop."
              : s.addresses.length > 0
                ? `On. From another computer: ${s.addresses.map((a) => `ssh ${s.user}@${a}`).join(" or ")}`
                : "On. Connect to a network to log in from another computer."
          }
        />
      </PanelSectionRow>
      {(s.enabled || s.active) && (
        <PanelSectionRow>
          <div style={small}>
            {s.enabled
              ? s.active
                ? "It's set to start with the device. To change that, use Kettle Welcome in the desktop."
                : <span style={red}>It starts again with the device. To keep it off, use Kettle Welcome in the desktop.</span>
              : "Turned on here, it stays on until the device restarts. To have it on at every start, use Kettle Welcome in the desktop."}
          </div>
        </PanelSectionRow>
      )}
    </>
  );
}

const SETTINGS = (
  <>
    <p>Back to their defaults, as on a new install:</p>
    <ul style={{ margin: 0, paddingLeft: "20px" }}>
      <li>The system's: Wi-Fi networks, Bluetooth pairings, the start-up mode, the SSH server, and the password (back to "kettle").</li>
      <li>The desktop's: its layout, wallpaper, screen and keyboard settings.</li>
      <li>Steam's: its settings, launch options and controller layouts. Steam signs out.</li>
      <li>Kettle's: power profiles, lights, gyro, and every Decky plugin's settings.</li>
    </ul>
    <p>
      Games, saves, your files, apps and the non-Steam games in your library stay. What's reset is kept in
      /home/.kettle/settings-backup until the next reset.
    </p>
  </>
);

const EVERYTHING = (
  <p>
    All games, saves, screenshots, downloaded apps, your files and every setting on this install are deleted, and it starts
    like a new install. Kettle Linux itself stays, at the version it has now, and Android isn't touched.
  </p>
);

function confirm(what: What) {
  const title = what === "settings" ? "Reset all settings?" : "Erase everything?";
  showModal(
    <ConfirmModal
      strTitle={title}
      strOKButtonText={what === "settings" ? "Reset settings" : "Erase everything"}
      strCancelButtonText="Back"
      bDestructiveWarning={what === "everything"}
      onOK={() => act(() => reset(what), "Couldn't reset")}
    >
      {what === "settings" ? SETTINGS : EVERYTHING}
      <p>The device restarts now and {what === "settings" ? "resets" : "erases"} while it starts.{what === "everything" && " This can't be undone."}</p>
    </ConfirmModal>,
  );
}

function Reset() {
  const [s, setS] = useState<ResetStatus | null>(null);
  useEffect(() => {
    resetStatus().then(setS).catch(() => {});
  }, []);
  return (
    <>
      {s && s.pending !== "none" && (
        <PanelSectionRow>
          <div style={{ ...small, ...red }}>
            {s.pending === "settings" ? "Settings are" : "Everything is"} set to be reset on the next start. To take that
            back, use Reset Kettle in the desktop.
          </div>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem layout="below" description="Every setting back to its default. Games, saves and files stay." onClick={() => confirm("settings")}>
          Reset Settings...
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={!s || s.ufs_backup}
          description={
            s?.ufs_backup ? (
              <span style={red}>
                The SD card holds the Kettle Installer's backup of the internal storage (Android), which erasing would delete.
                Copy it to another computer first, then erase from Reset Kettle in the desktop.
              </span>
            ) : (
              "A factory reset: games, saves, files and settings are deleted. The same as Steam's Settings > System > Factory Reset."
            )
          }
          onClick={() => confirm("everything")}
        >
          Erase Everything...
        </ButtonItem>
      </PanelSectionRow>
    </>
  );
}

export function SystemTab() {
  return (
    <>
      <PanelSection title="Start-up">
        <StartUp />
      </PanelSection>
      <PanelSection title="Remote access">
        <RemoteAccess />
      </PanelSection>
      <PanelSection title="Reset">
        <Reset />
      </PanelSection>
    </>
  );
}
