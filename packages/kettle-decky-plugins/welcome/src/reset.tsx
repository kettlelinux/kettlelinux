// Reset: every setting back to its default, or everything erased (kettle-reset, on the next
// start), each behind a confirmation. Erasing while /home holds the Kettle Installer's backup of
// the internal storage is left to the desktop's Reset Kettle, which says what that loses.
import { ButtonItem, ConfirmModal, showModal } from "@decky/ui";
import { callable } from "@decky/api";
import { useEffect, useState } from "react";
import { Heading, Text, act, red, small } from "./ui";

type What = "settings" | "everything";
type Status = { pending: "none" | What; ufs_backup: boolean };

const resetStatus = callable<[], Status>("reset_status");
const reset = callable<[what: What], void>("reset");

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

export function ResetPage() {
  const [s, setS] = useState<Status | null>(null);
  useEffect(() => {
    resetStatus().then(setS).catch(() => {});
  }, []);
  return (
    <>
      <Text>
        <h2 style={{ marginTop: 0 }}>Reset</h2>
        <p>Put this device back to how Kettle Linux started, without reinstalling it.</p>
        {s && s.pending !== "none" && (
          <p style={red}>
            {s.pending === "settings" ? "Settings are" : "Everything is"} set to be reset on the next start. To take that back,
            use Reset Kettle in the desktop.
          </p>
        )}
      </Text>
      <Heading>Reset settings</Heading>
      <Text>
        <p style={small}>Every setting back to its default. Games, saves and files stay.</p>
      </Text>
      <div style={{ maxWidth: "720px" }}>
        <ButtonItem layout="below" onClick={() => confirm("settings")}>
          Reset Settings...
        </ButtonItem>
      </div>
      <Heading>Erase everything</Heading>
      <Text>
        <p style={small}>A factory reset: games, saves, files and settings are deleted. The same as Steam's Settings &gt; System &gt; Factory Reset.</p>
        {s?.ufs_backup && (
          <p style={{ ...small, ...red }}>
            This device's SD card holds the backup of the internal storage (Android) that the Kettle Installer made, and erasing
            would delete it. Copy it to another computer first, then erase from Reset Kettle in the desktop.
          </p>
        )}
      </Text>
      <div style={{ maxWidth: "720px" }}>
        <ButtonItem layout="below" disabled={!s || s.ufs_backup} onClick={() => confirm("everything")}>
          Erase Everything...
        </ButtonItem>
      </div>
    </>
  );
}
