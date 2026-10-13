// The System tab: what the device starts up in, the SSH server, resetting the device, and the
// bootloader: installing, updating or removing the ROCKNIX ABL (system.py in the backend). The first three were the
// Welcome window's up to 1.12.0-38.
import { ButtonItem, ConfirmModal, DropdownItem, Field, PanelSection, PanelSectionRow, ProgressBarWithInfo, ToggleField, showModal } from "@decky/ui";
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
// kettle-abl-update's view: each abl slot's ROCKNIX release ("test-signed": one it can't
// identify, "other": stock), the image's release, whether a stock bootloader is saved to put
// back, what can be done (check) and what was just done or would be (result)
type AblMode = "update" | "install" | "restore";
type Abl = {
  available: boolean;
  installed: boolean;
  busy?: AblMode | null;
  slots?: Record<string, string>;
  image?: string | null;
  backup?: boolean;
  check?: string | null;
  result?: string | null;
};
const ablStatus = callable<[], Abl>("abl_status");
const ablUpdate = callable<[mode: AblMode], Abl>("abl_update");

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
              ? "Lets another computer on your network log in, for copying files or a terminal. Change the password first, in the desktop. Turning it on asks you to hold Volume Up + Volume Down."
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
      {what === "everything" && <p>Then hold Volume Up and Volume Down together for a second to confirm.</p>}
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

// what a kettle-abl-update result means for the player
function ablText(a: Abl): string {
  switch (a.result) {
    case "up-to-date":
      return `Up to date: ROCKNIX ABL ${a.image}.`;
    case "would-update":
      return `ROCKNIX ABL ${a.image} is in this Kettle update. Updating takes a few seconds; keep the device on.`;
    case "updated":
      return `Updated to ROCKNIX ABL ${a.image}. It's used from the next start.`;
    case "installed":
      return `ROCKNIX ABL ${a.image} is installed, and the stock bootloader is saved. On the next start, hold Volume Down for its menu and set Device model, Boot source and Boot mode: Linux.`;
    case "restored":
      return "The stock bootloader is back. From the next start the device starts as it did before the ROCKNIX ABL.";
    case "newer":
      return `Newer than this image's (${a.image}): left as it is.`;
    case "unknown":
      return "A bootloader Kettle can't identify (a test-signed ABL, 1.1.9?, or no ABL at all). If you're sure it's safe to replace, do it from a desktop terminal: sudo kettle-abl-update --install --force.";
    case "not-installed":
      return "The device's own bootloader, which starts Kettle through U-Boot (fastboot mode's Loader). The ROCKNIX ABL is only needed where there's no Loader choice.";
    case "stock":
      return "One slot has the stock bootloader again (an Android update can do that). Reinstall the ROCKNIX ABL to put it back in that slot; the stock one there is saved first.";
    case "is-stock":
      return "Both slots already have the stock bootloader.";
    case "no-backup":
      return "No saved stock bootloader to put back. With one saved elsewhere (such as ROCKNIX's backup), use a desktop terminal: sudo kettle-abl-update --restore-stock --stock-image FILE.";
    case "low-battery":
      return "Connect the charger (or charge above 30%) first: losing power while it writes can stop the device from starting.";
    case "not-confirmed":
      return "Nothing was changed: hold Volume Up and Volume Down together for a second, within 30 seconds of starting it.";
    default:
      return "";
  }
}

const slotText = (v: string) => (v === "other" ? "stock" : v === "test-signed" ? "unidentified" : v);
const BUSY_TEXT: Record<AblMode, string> = {
  update: "Updating the bootloader… keep the device on",
  install: "Installing the ROCKNIX ABL… keep the device on",
  restore: "Putting the stock bootloader back… keep the device on",
};

// Where Kettle has a ROCKNIX ABL build for the device and can see its abl partitions. Most devices
// start Kettle through U-Boot and keep their stock bootloader: installing over it is offered, but
// isn't needed there.
function Bootloader() {
  const [a, setA] = useState<Abl | null>(null);
  const [busy, setBusy] = useState<AblMode | null>(null);
  useEffect(() => {
    ablStatus().then(setA).catch(() => {});
  }, []);
  // a write started before the tab was reopened: follow it until it's done
  useEffect(() => {
    if (!a?.busy || busy) return;
    const t = setInterval(() => ablStatus().then(setA).catch(() => {}), 3000);
    return () => clearInterval(t);
  }, [a?.busy, busy]);
  if (!a?.available) return null;

  const run = (mode: AblMode, fail: string) => async () => {
    setBusy(mode);
    try {
      const r = await ablUpdate(mode);
      setA(r);
      toaster.toast({ title: "Device Settings", body: ablText(r) });
    } catch (e) {
      toaster.toast({ title: "Device Settings", body: `${fail}: ${e}` });
      ablStatus().then(setA).catch(() => {});
    } finally {
      setBusy(null);
    }
  };
  const keys = <p>Then hold Volume Up and Volume Down together for a second to confirm.</p>;
  const power = (
    <p>Keep the device on and the charger connected until it's done: losing power while it writes can stop the device from starting.</p>
  );
  const update = () =>
    showModal(
      <ConfirmModal
        strTitle={`Update the bootloader to ROCKNIX ABL ${a.image}?`}
        strOKButtonText="Update"
        strCancelButtonText="Not now"
        bDestructiveWarning
        onOK={run("update", "The bootloader wasn't updated")}
      >
        <p>
          Both bootloader slots get ROCKNIX's {a.image} release, one at a time, each checked after it's written (a slot
          that doesn't check out gets its old contents back).
        </p>
        {power}
        {keys}
      </ConfirmModal>,
    );
  const install = () =>
    showModal(
      <ConfirmModal
        strTitle={`Install ROCKNIX ABL ${a.image} as the bootloader?`}
        strOKButtonText="Install"
        strCancelButtonText="Not now"
        bDestructiveWarning
        onOK={run("install", "The ROCKNIX ABL wasn't installed")}
      >
        {a.check === "stock" ? (
          <p>
            The slot that has the stock bootloader again gets ROCKNIX's {a.image} release. The stock one there is saved on
            this device first, so it can be put back.
          </p>
        ) : (
          <p>
            This replaces the device's own bootloader. The stock one is saved on this device first (and on the SD card),
            so <i>Put the stock bootloader back</i> can undo it. With the ROCKNIX ABL, fastboot mode's Loader choice is
            gone: hold Volume Down while powering on for its menu, Volume Up for Android.
          </p>
        )}
        <p>
          {a.check === "stock" ? "If it starts nothing afterwards, hold Volume Down while powering on and set" : "On the next start, set"}{" "}
          its <b>Device model</b>, <b>Boot source</b> (SD, or Internal for an internal install) and{" "}
          <b>Boot mode: Linux</b>: it starts nothing until the device model is set.
        </p>
        {power}
        {keys}
      </ConfirmModal>,
    );
  const restore = () =>
    showModal(
      <ConfirmModal
        strTitle="Put the stock bootloader back?"
        strOKButtonText="Put it back"
        strCancelButtonText="Not now"
        bDestructiveWarning
        onOK={run("restore", "The stock bootloader wasn't put back")}
      >
        <p>
          Each slot gets the stock bootloader saved when the ROCKNIX ABL was installed, checked after it's written. Then
          the device starts as it did before.
        </p>
        <p>
          To keep starting Kettle, set fastboot mode's default boot to <b>Loader</b>. If your device has no Loader
          choice, it then starts only Android, until the ROCKNIX ABL is installed again from Android.
        </p>
        {power}
        {keys}
      </ConfirmModal>,
    );

  const writing = busy || a.busy;
  // low-battery and not-confirmed: the check still says what can be done, so the button stays
  const buttons: [string, () => void][] = [];
  if (a.check === "would-update") buttons.push([`Update to ROCKNIX ABL ${a.image}…`, update]);
  if (a.check === "not-installed") buttons.push([`Install ROCKNIX ABL ${a.image}…`, install]);
  if (a.check === "stock") buttons.push([`Reinstall ROCKNIX ABL ${a.image}…`, install]);
  if (a.installed && a.backup) buttons.push(["Put the stock bootloader back…", restore]);
  return (
    <PanelSection title="Bootloader">
      <PanelSectionRow>
        <Field label={a.installed ? "ROCKNIX ABL" : "Stock bootloader"} bottomSeparator="none">
          {Object.entries(a.slots ?? {}).map(([s, v]) => `${s.toUpperCase()}: ${slotText(v)}`).join(" · ")}
        </Field>
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={small}>{ablText(a)}</div>
      </PanelSectionRow>
      {writing ? (
        <PanelSectionRow>
          <ProgressBarWithInfo indeterminate nProgress={0} sOperationText={BUSY_TEXT[writing]} />
        </PanelSectionRow>
      ) : (
        buttons.map(([label, onClick]) => (
          <PanelSectionRow key={label}>
            <ButtonItem layout="below" onClick={onClick}>
              {label}
            </ButtonItem>
          </PanelSectionRow>
        ))
      )}
    </PanelSection>
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
      <Bootloader />
      <PanelSection title="Reset">
        <Reset />
      </PanelSection>
    </>
  );
}
