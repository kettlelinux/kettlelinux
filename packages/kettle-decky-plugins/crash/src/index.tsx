import {
  ButtonItem,
  ConfirmModal,
  DialogButton,
  Field,
  Focusable,
  ModalRoot,
  Navigation,
  PanelSection,
  PanelSectionRow,
  showModal,
  staticClasses,
  useParams,
} from "@decky/ui";
import { addEventListener, callable, definePlugin, removeEventListener, routerHook, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { FaBug } from "react-icons/fa";
import qrcode from "qrcode-generator";

type Summary = {
  id: string;
  kind: "coredump" | "devcoredump" | "game";
  title: string;
  detail: string;
  time_ms: number;
  count: number;
  during: string | null;
  noticed: boolean;
};
type Report = {
  what?: string;
  exe?: string;
  cmdline?: string;
  signal?: string;
  driver?: string;
  device?: string;
  compat_tool?: string | null;
  game?: { app_id: number; name?: string; kettle_features?: string[] } | null;
  game_process?: boolean;
  dump_bytes?: number;
  dump_skipped?: string;
  system: {
    os: { version_id?: string; build_id?: string; variant?: string };
    kernel: string;
    slot: string | null;
    packages: Record<string, string>;
  };
};
type Detail = {
  summary: Summary;
  report: Report;
  backtrace: string;
  output: string;
  journal: string;
  kernel: string;
  shared: Shared | null;
  can_share: boolean;
};
type Shared = { id: string; url: string };

const list = callable<[], { reports: Summary[]; seen: string }>("list");
const get = callable<[rid: string], Detail | null>("get");
const markSeen = callable<[rid: string], void>("mark_seen");
const del = callable<[rid: string], void>("delete");
const share = callable<[rid: string], Shared>("share");
const delAll = callable<[], void>("delete_all");

const ROUTE = "/kettle-crash";
const FEATURES: Record<string, string> = { framegen: "Frame Generation", optiscaler: "Upscaling (OptiScaler)" };

function open(id: string) {
  Navigation.CloseSideMenus();
  Navigation.Navigate(`${ROUTE}/${id}`);
}

function when(ms: number) {
  const d = new Date(ms);
  const today = new Date().toDateString() === d.toDateString();
  return today ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : d.toLocaleString();
}

function line(s: Summary) {
  return [when(s.time_ms), s.detail, s.count > 1 ? `${s.count}×` : "", s.during ? `during ${s.during}` : ""]
    .filter(Boolean)
    .join(" · ");
}

function Content() {
  const [data, setData] = useState<{ reports: Summary[]; seen: string } | null>(null);
  const refresh = () => list().then(setData).catch(() => {});
  useEffect(() => {
    refresh();
    const onCrash = () => refresh();
    addEventListener("crash", onCrash);
    return () => removeEventListener("crash", onCrash);
  }, []);
  // opening the panel counts as having seen what's in it
  useEffect(() => {
    const newest = data?.reports[0]?.id;
    if (newest && newest > data.seen) markSeen(newest).catch(() => {});
  }, [data]);
  if (!data) return null;
  const { reports, seen } = data;
  return (
    <PanelSection title="Recent crashes">
      {reports.length === 0 && (
        <PanelSectionRow>
          <Field label="No crashes recorded" description="Crashes of games and of Game Mode show up here." />
        </PanelSectionRow>
      )}
      {reports.slice(0, 20).map((s) => (
        <PanelSectionRow key={s.id}>
          <ButtonItem layout="below" description={line(s)} onClick={() => open(s.id)}>
            {s.id > seen ? "● " : ""}
            {s.title}
          </ButtonItem>
        </PanelSectionRow>
      ))}
      {reports.length > 0 && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() =>
              showModal(
                <ConfirmModal
                  strTitle="Delete all crash reports?"
                  strDescription="They're only kept on this device."
                  strOKButtonText="Delete"
                  onOK={() => delAll().then(refresh)}
                />,
              )
            }
          >
            Delete all
          </ButtonItem>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

const mono: React.CSSProperties = {
  fontFamily: "monospace",
  fontSize: "11px",
  whiteSpace: "pre-wrap",
  wordBreak: "break-all",
  margin: 0,
  padding: "8px",
  background: "rgba(0,0,0,0.3)",
  borderRadius: "4px",
};

// The shared report's page, as a QR code to open it on a phone (a handheld is no place to file an
// issue), and as a link
function SharedModal({ shared, closeModal }: { shared: Shared; closeModal?: () => void }) {
  const qr = qrcode(0, "M");
  qr.addData(shared.url);
  qr.make();
  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ display: "flex", gap: "24px", alignItems: "center" }}>
        <div
          style={{ background: "white", padding: "8px", borderRadius: "4px", lineHeight: 0 }}
          dangerouslySetInnerHTML={{ __html: qr.createSvgTag({ cellSize: 5, margin: 2, scalable: false }) }}
        />
        <div>
          <h3 style={{ marginTop: 0 }}>Report shared</h3>
          <p>Scan the code to open it on your phone, then use its page to report the crash on GitHub.</p>
          <p style={{ fontFamily: "monospace", wordBreak: "break-all" }}>{shared.url}</p>
          <DialogButton onClick={closeModal}>Done</DialogButton>
        </div>
      </div>
    </ModalRoot>
  );
}

function confirmShare(id: string, onShared: (s: Shared) => void) {
  showModal(
    <ConfirmModal
      strTitle="Share this crash report?"
      strDescription={
        "It's uploaded to Kettle's crash report server, where anyone with its link can read it: what crashed, " +
        "the game, the versions and the logs. Your user name, Steam account, network names and addresses are " +
        "taken out first, and core dumps stay on this device."
      }
      strOKButtonText="Share"
      onOK={() =>
        share(id)
          .then((s) => {
            onShared(s);
            showModal(<SharedModal shared={s} />);
          })
          .catch((e) => toaster.toast({ title: "Crash Reports", body: String(e?.message ?? e) }))
      }
    />,
  );
}

// A block the D-pad can stop on, so the page scrolls to it
function Block({ title, text }: { title: string; text: string }) {
  if (!text.trim()) return null;
  return (
    <Focusable onActivate={() => {}} style={{ marginBottom: "16px" }}>
      <div className={staticClasses.PanelSectionTitle}>{title}</div>
      <pre style={mono}>{text}</pre>
    </Focusable>
  );
}

function Page() {
  const { id } = useParams<{ id: string }>();
  const [d, setD] = useState<Detail | null | undefined>(undefined);
  useEffect(() => {
    get(id).then(setD).catch(() => setD(null));
  }, [id]);
  const r = d?.report;
  const sys = r?.system;
  const pkgs = sys?.packages ?? {};
  const mesa = Object.entries(pkgs).find(([k]) => k.includes("mesa"));
  const rows: [string, string | undefined][] = r
    ? [
        ["When", new Date(d!.summary.time_ms).toLocaleString() + (d!.summary.count > 1 ? ` (${d!.summary.count} times)` : "")],
        ["Program", r.exe?.replace(/^\/home\/kettle\//, "~/")],
        ["Signal", r.signal],
        ["Error", r.what],
        ["Device", r.device ? `${r.device} (${r.driver})` : undefined],
        ["Dump", r.dump_skipped ?? (r.dump_bytes ? `${Math.round(r.dump_bytes / 1024)} KiB saved` : undefined)],
        [r.game_process ? "Game" : "Game running", r.game ? (r.game.name ?? `App ${r.game.app_id}`) : undefined],
        ["Compatibility tool", r.compat_tool ?? undefined],
        ["Kettle features", r.game ? (r.game.kettle_features ?? []).map((f) => FEATURES[f] ?? f).join(", ") || "None" : undefined],
        ["Kettle", sys ? `${sys.os.version_id ?? ""} build ${sys.os.build_id ?? "?"}, slot ${sys.slot ?? "?"}` : undefined],
        ["Kernel", sys?.kernel],
        ["Mesa", mesa?.[1]],
        ["FEX", pkgs["fex-emu-wine"]],
        ["gamescope", pkgs["gamescope"]],
      ]
    : [];
  return (
    <div style={{ marginTop: "40px", height: "calc(100% - 40px)", overflowY: "scroll", padding: "16px 24px" }}>
      {d === undefined && <div>Loading…</div>}
      {d === null && <div>This report is gone.</div>}
      {d && (
        <>
          <h2 style={{ margin: "0 0 12px" }}>{d.summary.title}</h2>
          <Focusable style={{ marginBottom: "16px" }}>
            {rows
              .filter(([, v]) => v)
              .map(([k, v]) => (
                <Field key={k} label={k} focusable bottomSeparator="thick">
                  <span style={{ wordBreak: "break-all" }}>{v}</span>
                </Field>
              ))}
          </Focusable>
          <Block title="Stack trace" text={d.backtrace} />
          <Block title="Game output" text={d.output} />
          <Block title="Kernel log" text={d.kernel} />
          <Block title="System log" text={d.journal} />
          <Focusable style={{ marginBottom: "24px" }}>
            {d.shared ? (
              <ButtonItem layout="below" onClick={() => showModal(<SharedModal shared={d.shared!} />)}>
                Show shared link
              </ButtonItem>
            ) : (
              d.can_share && (
                <ButtonItem layout="below" onClick={() => confirmShare(id, (shared) => setD({ ...d, shared }))}>
                  Share…
                </ButtonItem>
              )
            )}
            <ButtonItem layout="below" onClick={() => del(id).then(() => Navigation.NavigateBack())}>
              Delete this report
            </ButtonItem>
          </Focusable>
        </>
      )}
    </div>
  );
}

export default definePlugin(() => {
  routerHook.addRoute(`${ROUTE}/:id`, Page);
  const onCrash = (s: Summary) => {
    if (!s.noticed) return;
    toaster.toast({
      title: s.kind === "devcoredump" ? s.title : `${s.title} crashed`,
      body: "A crash report was saved. Select to view it.",
      icon: <FaBug />,
      onClick: () => open(s.id),
    });
  };
  addEventListener("crash", onCrash);
  return {
    name: "Crash Reports",
    titleView: <div className={staticClasses.Title}>Crash Reports</div>,
    content: <Content />,
    icon: <FaBug />,
    onDismount: () => {
      removeEventListener("crash", onCrash);
      routerHook.removeRoute(`${ROUTE}/:id`);
    },
  };
});
