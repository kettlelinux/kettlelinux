// The Moonlight page: the PCs, paired ones first, each a big card to open (a paired PC) or pair
// with (one on the network that isn't yet); adding a PC by address; the controller combos.
import { DialogButton, Focusable } from "@decky/ui";
import { FaDesktop, FaPlus, FaSyncAlt } from "react-icons/fa";
import { Host, hosts } from "./api";
import { addPc, startPairing } from "./pair";
import { QUIT_COMBO, STATS_COMBO, dim, openHost, small, usePoll } from "./ui";

const CSS = `
.kettle-ml-hosts { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; padding: 8px 0 16px; }
.kettle-ml-host { display: flex; gap: 14px; align-items: center; padding: 16px; border-radius: 8px; background: #23262e; transition: transform 0.1s; }
.kettle-ml-host.gpfocus { outline: 3px solid #fff; transform: scale(1.03); }
.kettle-ml-host .icon { font-size: 34px; flex: none; }
.kettle-ml-host .n { font-size: 17px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kettle-ml-host .s { font-size: 12px; color: #8b929a; margin-top: 2px; }
.kettle-ml-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
`;

export function status(h: Host): [string, string] {
  if (!h.online) return ["Offline", "#6b7079"];
  if (!h.paired) return ["Select to pair", "#e0b341"];
  if (h.busy) return ["Streaming to another device", "#e0b341"];
  return ["Ready", "#59bf40"];
}

function HostCard({ h }: { h: Host }) {
  const [text, color] = status(h);
  const go = () => (h.paired ? openHost(h.uuid) : startPairing(h.name, h.address));
  return (
    <Focusable className="kettle-ml-host" onActivate={go} onClick={go}>
      <FaDesktop className="icon" style={{ color: h.online ? "#fff" : "#6b7079" }} />
      <div style={{ minWidth: 0 }}>
        <div className="n">{h.name || h.address}</div>
        <div className="s">
          <span className="kettle-ml-dot" style={{ background: color }} />
          {text}
          {h.online && ` · ${h.apollo ? "Apollo" : "Sunshine"}`}
        </div>
      </div>
    </Focusable>
  );
}

export function Page() {
  const [list, reload, error] = usePoll(() => hosts(true), 10000);
  return (
    <div style={{ marginTop: "40px", height: "calc(100% - 40px)", overflowY: "scroll", padding: "16px 24px 80px" }}>
      <style>{CSS}</style>
      <h2 style={{ margin: "0 0 4px" }}>Moonlight</h2>
      <p style={{ ...small, ...dim, margin: 0 }}>
        Play games streamed from your PC. It needs Sunshine or Apollo running on the PC, on the same network.
      </p>
      <Focusable style={{ display: "flex", gap: "8px", margin: "12px 0 4px" }} flow-children="horizontal">
        <DialogButton style={{ width: "auto", minWidth: 0 }} onClick={reload}>
          <FaSyncAlt style={{ marginRight: "8px" }} />
          Search again
        </DialogButton>
        <DialogButton style={{ width: "auto", minWidth: 0 }} onClick={addPc}>
          <FaPlus style={{ marginRight: "8px" }} />
          Add a PC by address
        </DialogButton>
      </Focusable>
      {list === null && !error && <p>Looking for PCs…</p>}
      {error && <p>Looking for PCs failed: {error}</p>}
      {list && list.length === 0 && (
        <p>
          No PC found. Start Sunshine or Apollo on your PC, check it's on the same network, and search again, or add it by
          address.
        </p>
      )}
      {list && list.length > 0 && (
        <Focusable className="kettle-ml-hosts">
          {list.map((h) => (
            <HostCard key={h.uuid} h={h} />
          ))}
        </Focusable>
      )}
      <h3 style={{ margin: "16px 0 4px" }}>While streaming</h3>
      <div style={{ ...small, ...dim }}>
        <div>End the stream: {QUIT_COMBO}, or End stream in Quick Access</div>
        <div>Show or hide the stream's stats: {STATS_COMBO}</div>
        <div>The touchscreen works as the PC's trackpad.</div>
      </div>
    </div>
  );
}
