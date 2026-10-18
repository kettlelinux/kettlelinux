// Pairing with a PC: the PIN shown large, to type in on the PC (Sunshine's or Apollo's web page),
// while moonlight-qt pairs in the background (main.py's pair); and adding a PC by its address.
import { DialogButton, Focusable, ModalRoot, TextField, showModal } from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { Pair, addHost, pair, pairCancel, pairStatus } from "./api";
import { dim, errorText, openHost, small } from "./ui";

const PIN_STYLE = {
  fontSize: "72px",
  lineHeight: "84px",
  fontWeight: 700,
  letterSpacing: "24px",
  textAlign: "center" as const,
  padding: "12px 0 4px 24px",
  fontVariantNumeric: "tabular-nums",
};

function PairModal({ name, address, closeModal }: { name: string; address: string; closeModal?: () => void }) {
  const [p, setP] = useState<Pair | null>(null);
  const [n, setN] = useState(0); // a new attempt

  useEffect(() => {
    let live = true;
    let t: ReturnType<typeof setInterval> | undefined;
    setP(null);
    // this attempt's status only: the PIN pair() gave it ("" when it ended at once: paired
    // already, or the PC didn't answer)
    const follow = (pin: string) => {
      const tick = () =>
        pairStatus()
          .then((s) => {
            if (!live || s.address !== address || s.pin !== pin || s.state === "starting") return;
            setP(s);
            if (s.state === "done" || s.state === "failed") clearInterval(t);
            if (s.state === "done") {
              toaster.toast({ title: "Moonlight", body: `Paired with ${name}.` });
              closeModal?.();
              openHost(s.uuid);
            }
          })
          .catch(() => {});
      tick();
      t = setInterval(tick, 1000);
    };
    pair(address)
      .then((pin) => live && follow(pin))
      .catch((e) => live && setP({ state: "failed", address, pin: "", error: errorText(e), uuid: "" }));
    return () => {
      live = false;
      clearInterval(t);
    };
  }, [n]);

  const cancel = () => {
    pairCancel().catch(() => {});
    closeModal?.();
  };

  return (
    <ModalRoot closeModal={cancel}>
      <h3 style={{ marginTop: 0 }}>Pair with {name}</h3>
      {p?.state === "failed" ? (
        <p>{p.error}</p>
      ) : (
        <>
          <p style={{ marginBottom: 0 }}>On the PC, open Sunshine's or Apollo's web page, go to <b>PIN</b>, and type:</p>
          <div style={PIN_STYLE}>{p?.pin || "····"}</div>
          <p style={{ ...small, ...dim, textAlign: "center" }}>
            {p?.pin ? "Waiting for the PC…" : "Starting…"} On the PC itself the page is https://localhost:47990
          </p>
        </>
      )}
      <Focusable style={{ display: "flex", gap: "8px", marginTop: "16px" }} flow-children="horizontal">
        {p?.state === "failed" && <DialogButton onClick={() => setN(n + 1)}>Try again</DialogButton>}
        <DialogButton onClick={cancel}>Cancel</DialogButton>
      </Focusable>
    </ModalRoot>
  );
}

export const startPairing = (name: string, address: string) => showModal(<PairModal name={name} address={address} />);

function AddModal({ closeModal }: { closeModal?: () => void }) {
  const [address, setAddress] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const add = async () => {
    setBusy(true);
    setError("");
    try {
      const h = await addHost(address);
      closeModal?.();
      startPairing(h.name, h.address);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <ModalRoot closeModal={closeModal}>
      <h3 style={{ marginTop: 0 }}>Add a PC</h3>
      <p style={small}>
        PCs on this network show up by themselves. Add one here by its IP address or name, as Sunshine or Apollo shows it (for
        example 192.168.1.20).
      </p>
      <TextField label="IP address or name" value={address} onChange={(e) => setAddress(e.target.value.trim())} />
      {error && <p style={{ ...small, color: "#ff6b6b" }}>{error}</p>}
      <Focusable style={{ display: "flex", gap: "8px", marginTop: "16px" }} flow-children="horizontal">
        <DialogButton disabled={!address || busy} onClick={add}>
          {busy ? "Looking for it…" : "Add and pair"}
        </DialogButton>
        <DialogButton onClick={closeModal}>Cancel</DialogButton>
      </Focusable>
    </ModalRoot>
  );
}

export const addPc = () => showModal(<AddModal />);
