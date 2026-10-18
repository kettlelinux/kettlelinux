// Get started: the first visit's walk through, a step a screen: where games go, the ways to add
// them (add.tsx), the BIOS files some systems need, the controls, and adding what's there to the
// library. Finishing it opens the Library; Quick Access opens Emulation from then on.
import { DialogButton, Focusable, Navigation } from "@decky/ui";
import { useState } from "react";
import { bios, overview, setSettings, setUpCard } from "./api";
import { CardsSection, InboxSection, JobProgress, ShareSection, UploadSection } from "./add";
import { sync } from "./sync";
import { ControlsTable, ROUTE, act, dim, good, plural, small, usePoll, warn } from "./ui";

const STEPS = ["Welcome", "Add games", "BIOS files", "Controls", "Your library"];
const mono = { fontFamily: "monospace", fontSize: "13px" };

export function StartPage() {
  const [step, setStep] = useState(0);
  const [ov, reload] = usePoll(overview, 0);
  const [b] = usePoll(bios, 0, [step]);
  const [result, setResult] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!ov) return <div style={{ marginTop: "40px", padding: "16px 24px" }}>Loading…</div>;
  const finish = () =>
    act(async () => {
      await setSettings({ first_run_done: true });
      Navigation.Navigate(`${ROUTE}/library`);
    }, "That failed");
  const addNow = () =>
    act(async () => {
      setBusy(true);
      try {
        const r = await sync();
        reload();
        setResult(r.added ? `${plural(r.added, "game")} added to your library.` : "Your library is up to date.");
      } finally {
        setBusy(false);
      }
    }, "Adding to the library failed");
  const missing = (b?.systems ?? []).filter((s) => s.state === "missing-required");
  const counted = ov.systems.filter((s) => s.count);
  const noteOf = (id: string) => ov.systems.find((o) => o.id === id)?.note ?? "";
  return (
    <div style={{ marginTop: "40px", height: "calc(100% - 40px)", overflowY: "scroll", padding: "16px 24px 80px", maxWidth: "860px" }}>
      <div style={{ ...small, ...dim }}>
        Step {step + 1} of {STEPS.length}: {STEPS[step]}
      </div>
      {step === 0 && (
        <>
          <h2 style={{ margin: "4px 0 8px" }}>Play your retro games</h2>
          <p>
            Emulation plays games of consoles from the NES to the GameCube and Wii, right from your Steam library: each game gets its own entry,
            with artwork, in a collection per system. Everything it needs comes with Kettle; you bring the games (and, for a few systems, a
            BIOS file from the console).
          </p>
          <p style={small}>Games go in a folder per system, on this device or on a card:</p>
          {ov.storages.map((s) => (
            <div key={s.path} style={{ ...small, margin: "4px 0" }}>
              <b>{s.label}</b>: <span style={mono}>{s.emulation}/roms</span>
              {!s.internal && !s.set_up && (
                <DialogButton
                  style={{ width: "auto", display: "inline-block", marginLeft: "8px", padding: "2px 10px", minWidth: 0 }}
                  onClick={() => act(async () => (await setUpCard(s.path), reload()), "Setting it up failed")}
                >
                  Use this card for games
                </DialogButton>
              )}
              {!s.internal && s.set_up && <span style={good}> · ready</span>}
            </div>
          ))}
          <p style={{ ...small, ...dim }}>You don't need to sort anything yourself: the next step shows how to drop games in and have them sorted.</p>
        </>
      )}
      {step === 1 && (
        <>
          <h2 style={{ margin: "4px 0 8px" }}>Add games, any way you like</h2>
          <JobProgress />
          <InboxSection ov={ov} />
          <CardsSection />
          <UploadSection />
          <ShareSection />
        </>
      )}
      {step === 2 && (
        <>
          <h2 style={{ margin: "4px 0 8px" }}>BIOS files</h2>
          <p style={small}>
            Most systems need nothing. Some need a BIOS file from the console, which Kettle can't include. Add yours the same way as games:
            they're recognised by their content, whatever they're called. A few need folders that come with their core instead, from Extra
            cores.
          </p>
          {b &&
            b.systems
              .filter((s) => s.state !== "none")
              .map((s) => (
                <div key={s.id} style={{ ...small, margin: "3px 0" }}>
                  <b>{s.name}</b>:{" "}
                  {s.state === "ok" ? (
                    <span style={good}>ready</span>
                  ) : s.state === "missing-required" && s.entries.filter((e) => e.required && !e.found).every((e) => e.folder) ? (
                    <span style={warn}>
                      needs its {s.entries.filter((e) => e.folder && !e.found).map((e) => e.file).join(", ")} folders: they come with the core
                      from Extra cores, no BIOS from the console
                      {noteOf(s.id) && <span style={dim}> ({noteOf(s.id)})</span>}
                    </span>
                  ) : s.state === "missing-required" ? (
                    <span style={warn}>
                      needs{" "}
                      {s.entries.some((e) => e.one_of)
                        ? `one of ${s.entries.filter((e) => e.one_of).map((e) => e.file).join(", ")}`
                        : s.entries.filter((e) => e.required && !e.found).map((e) => e.file).join(", ")}
                    </span>
                  ) : (
                    <span style={dim}>plays without one (optional files: {s.entries.filter((e) => !e.found).map((e) => e.file).join(", ")})</span>
                  )}
                </div>
              ))}
          {missing.length === 0 && <p style={{ ...small, ...good }}>Nothing you need is missing.</p>}
        </>
      )}
      {step === 3 && (
        <>
          <h2 style={{ margin: "4px 0 8px" }}>The same controls everywhere</h2>
          <p style={small}>
            Buttons sit where the original controller had them, in every system. Hold <b>Select</b> for the hotkeys:
          </p>
          <ControlsTable face={ov.face} />
          <p style={{ ...small, ...dim }}>Quick Access has the same actions as buttons while a game runs.</p>
        </>
      )}
      {step === 4 && (
        <>
          <h2 style={{ margin: "4px 0 8px" }}>Your library</h2>
          <p style={small}>
            {counted.length
              ? `Found: ${counted.map((s) => `${s.name} ${s.count}`).join(", ")}.`
              : "Games you add from now on show up in your Steam library by themselves."}
          </p>
          <DialogButton style={{ width: "auto" }} disabled={busy} onClick={addNow}>
            {busy ? "Adding…" : "Add my games to the library now"}
          </DialogButton>
          {result && <p style={{ ...small, ...good }}>{result}</p>}
        </>
      )}
      <Focusable style={{ display: "flex", gap: "8px", marginTop: "20px" }} flow-children="horizontal">
        {step > 0 && (
          <DialogButton style={{ width: "auto" }} onClick={() => setStep(step - 1)}>
            Back
          </DialogButton>
        )}
        {step < STEPS.length - 1 ? (
          <DialogButton style={{ width: "auto" }} onClick={() => setStep(step + 1)}>
            Next
          </DialogButton>
        ) : (
          <DialogButton style={{ width: "auto" }} onClick={finish}>
            Done
          </DialogButton>
        )}
      </Focusable>
    </div>
  );
}
