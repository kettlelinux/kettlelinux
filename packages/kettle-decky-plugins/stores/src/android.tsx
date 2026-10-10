// The Game Stores page's Android tab, through kettle-android-games (package kettle-lepton): search
// F-Droid and add a game, add an APK file from the device, and remove added games. Google Play is
// left to the desktop's Kettle Welcome: signing in to it goes through Firefox.
import { ButtonItem, ConfirmModal, Field, ProgressBarWithInfo, TextField, showModal } from "@decky/ui";
import { callable, openFilePicker } from "@decky/api";
import type { FileSelectionType } from "@decky/api";
import { ReactNode, useEffect, useState } from "react";
import { size } from "./api";
import { act, small, usePoll } from "./ui";

type Game = { package: string; name: string; appid: number; size: number; in_steam: boolean | null };
type App = { package: string; name: string; summary: string };
// result: kettle-android-games' JSON, once the command is done
type Job = { command: string | null; busy: boolean; done: number; total: number; result: any };

export type AndroidInfo = { available: boolean; files: string };
export const androidInfo = callable<[], AndroidInfo>("android_info");
const list = callable<[], { ok: boolean; games: Game[] }>("android_list");
const start = callable<[command: string, arg: string], void>("android_start");
const job = callable<[], Job>("android_job");

const red = { color: "#ff6b6b" };
const Text = ({ children }: { children: ReactNode }) => <div style={{ lineHeight: "22px", maxWidth: "720px" }}>{children}</div>;
const Heading = ({ children }: { children: ReactNode }) => <h3 style={{ margin: "24px 0 4px", maxWidth: "720px" }}>{children}</h3>;

const DOING: Record<string, string> = {
  add: "Adding the game to Steam…",
  remove: "Removing the game…",
  "fdroid-search": "Searching F-Droid…",
  "fdroid-add": "Downloading from F-Droid and adding to Steam",
};

export function AndroidTab({ files }: { files: string }) {
  const [j] = usePoll(job, 500);
  const [games, setGames] = useState<Game[] | null>(null);
  const [text, setText] = useState("");
  const [found, setFound] = useState<App[]>([]);
  const reload = () => list().then((r) => setGames(r.games ?? [])).catch(() => setGames([]));
  useEffect(() => {
    reload();
  }, []);
  // what a finished command changed
  useEffect(() => {
    if (!j || j.busy || !j.result?.ok) return;
    if (j.command === "fdroid-search") setFound(j.result.apps);
    else reload();
  }, [j?.busy, j?.result]);

  const busy = !!j?.busy;
  const run = (command: string, arg: string) => act(() => start(command, arg), "Couldn't start");
  const pickApk = () =>
    act(async () => {
      const f = await openFilePicker(0 as FileSelectionType /* FILE */, files, true, true, undefined, ["apk", "xapk", "apks"]);
      await start("add", f.realpath || f.path);
    }, "Couldn't add the file");

  return (
    <>
      <Text>
        <h2 style={{ marginTop: 0 }}>Android games</h2>
        <p>
          Android games run in Lepton, an Android 11 container, and show up in your Steam library like any game. Add free
          and open-source games from F-Droid, or an APK file you have on the device. Games from Google Play are added in
          the desktop's Kettle Welcome.
        </p>
      </Text>

      {j && (busy || j.result?.ok === false || (j.result?.ok && j.command !== "fdroid-search")) && (
        <div style={{ maxWidth: "720px" }}>
          {busy ? (
            <ProgressBarWithInfo
              indeterminate={!(j.total > 0)}
              nProgress={j.total > 0 ? (100 * j.done) / j.total : 0}
              sOperationText={DOING[j.command ?? ""] + (j.total > 0 ? `: ${size(j.done)} of ${size(j.total)}` : "")}
            />
          ) : j.result.ok ? (
            <p style={small}>
              {j.command === "remove" ? `${j.result.name} is removed.` : `${j.result.name ?? "The game"} is in your Steam library.`}
              {j.result.google_services && " It uses Google Play services, which aren't available, so it may not start."}
            </p>
          ) : (
            <p style={{ ...small, ...red }}>{j.result.error}</p>
          )}
        </div>
      )}

      <Heading>F-Droid</Heading>
      <div style={{ maxWidth: "720px" }}>
        <TextField label="Search F-Droid" value={text} onChange={(e) => setText(e.target.value)} />
        <ButtonItem layout="below" disabled={busy || !text.trim()} onClick={() => run("fdroid-search", text.trim())}>
          Search
        </ButtonItem>
        {found.map((a) => (
          <div key={a.package}>
            <Field label={a.name} description={<div style={small}>{a.summary}</div>} focusable={false} />
            <ButtonItem layout="below" disabled={busy} onClick={() => run("fdroid-add", a.package)}>
              Add to Steam
            </ButtonItem>
          </div>
        ))}
      </div>

      <Heading>APK file</Heading>
      <div style={{ maxWidth: "720px" }}>
        <ButtonItem
          layout="below"
          disabled={busy}
          description="An .apk, .xapk or .apks file, for example one you downloaded or copied to the device."
          onClick={pickApk}
        >
          Choose a file
        </ButtonItem>
      </div>

      {games && games.length > 0 && (
        <>
          <Heading>Added games</Heading>
          {games.map((g) => (
            <div key={g.package} style={{ maxWidth: "720px" }}>
              <Field
                label={g.name}
                description={
                  <div style={small}>
                    {size(g.size)}
                    {g.in_steam === false && " · no longer in Steam"}
                  </div>
                }
                focusable={false}
              />
              <ButtonItem
                layout="below"
                disabled={busy}
                onClick={() =>
                  showModal(
                    <ConfirmModal
                      strTitle={`Remove ${g.name}?`}
                      strDescription={`This deletes the game, its saves and its shortcut in Steam, and frees ${size(g.size)}.`}
                      strOKButtonText="Remove"
                      onOK={() => run("remove", g.package)}
                    />,
                  )
                }
              >
                Remove
              </ButtonItem>
            </div>
          ))}
        </>
      )}
    </>
  );
}
