// The Game Stores page's Battle.net tab, through kettle-welcome's welcome-battlenet (the desktop's
// Kettle Welcome uses it too): Blizzard's installer added to Steam as "Battle.net" with
// Proton-CachyOS and started; once it has installed the launcher, the same entry starts that.
import { ButtonItem, Field, ProgressBarWithInfo } from "@decky/ui";
import { callable } from "@decky/api";
import { useState } from "react";
import { act, small, usePoll } from "./ui";

// proton: the newest Proton-CachyOS build (null: none); in_steam: the entry is in the library
// (null: Steam couldn't be asked); ready: it starts the installed launcher
type BnetStatus = { available: boolean; proton: string | null; steam: boolean; appid: number | null; in_steam: boolean | null; ready: boolean };

const battlenetStatus = callable<[], BnetStatus>("battlenet_status");
const battlenetInstall = callable<[], void>("battlenet_install");

export function BattleNetTab() {
  // status also switches the entry to the launcher once the installer has finished
  // a failed check shows its error rather than an empty tab
  const [r, refresh] = usePoll(() => battlenetStatus().catch((e) => ({ error: String(e?.message ?? e) })), 5000);
  const [busy, setBusy] = useState(false);
  if (!r) return null;
  if ("error" in r) return <div style={small}>Couldn't check Battle.net: {r.error}</div>;
  const s = r;
  if (!s.available) return <div style={small}>Battle.net needs kettle-welcome, which isn't installed.</div>;
  const done = !!s.in_steam && s.ready;
  return (
    <div style={{ maxWidth: "720px" }}>
      <Field
        label={`Battle.net${done ? " ✓" : ""}`}
        description={
          <div style={small}>
            Blizzard's launcher, for Blizzard and Activision games you own there, added to your library and run with
            Proton-CachyOS. Its installer comes from battle.net. The launcher is slow to start on this device, and games
            with anti-cheat may refuse to run.
            {!s.proton && <div>Install Proton-CachyOS first (Game Settings &gt; Extras), then restart Steam.</div>}
            {s.in_steam && !s.ready && (
              <div>The installer is in your library as Battle.net. Once it finishes, the same entry starts Battle.net.</div>
            )}
            {done && <div>In your library. Sign in there, then install your games from Battle.net.</div>}
          </div>
        }
        focusable={false}
      />
      {busy ? (
        <ProgressBarWithInfo indeterminate nProgress={0} sOperationText="Downloading the installer" />
      ) : (
        !done && (
          <ButtonItem
            layout="below"
            disabled={!s.proton}
            onClick={() => {
              setBusy(true);
              act(battlenetInstall, "Installing Battle.net failed").finally(() => {
                setBusy(false);
                refresh();
              });
            }}
          >
            {s.in_steam ? "Run the installer again" : "Install and add to Steam"}
          </ButtonItem>
        )
      )}
    </div>
  );
}
