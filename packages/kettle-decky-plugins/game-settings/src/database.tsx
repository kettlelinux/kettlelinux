// The game's page in the game database: known good settings other players shared, verified
// ones first. Applying one replaces the game's settings here.
import { ButtonItem, ConfirmModal, Field, Focusable, Navigation, showModal, useParams } from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { Community, DbProfile, commit, community, compatTools, getGame } from "./api";
import { Profile, describe } from "./catalog";
import { LinkModal } from "./modals";

const small: React.CSSProperties = { fontSize: "12px", lineHeight: "16px" };
const VARIANTS: Record<string, string> = { odin2portal: "Odin 2 Portal", thor: "AYN Thor", rp5: "Retroid Pocket 5" };

function appName(appid: number): string {
  try {
    return (window as any).appStore?.GetAppOverviewByAppID(appid)?.display_name ?? `App ${appid}`;
  } catch {
    return `App ${appid}`;
  }
}

async function apply(appid: number, entry: DbProfile, tools: Map<string, string>) {
  let p: Profile = { settings: entry.settings, env: entry.env, dlls: entry.dlls, compat_tool: entry.compat_tool };
  if (p.compat_tool && !tools.has(p.compat_tool)) {
    toaster.toast({ title: "Game Settings", body: `${p.compat_tool} isn't installed: keeping the current Proton version` });
    p = { ...p, compat_tool: null };
  }
  const g = await getGame(appid);
  await commit(appid, g, p, { source: { id: entry.id, status: entry.status }, verdict: null });
  toaster.toast({ title: "Game Settings", body: `Applied. Play ${appName(appid)}, then say in Game Settings whether it worked.` });
  Navigation.NavigateBack();
}

export function DatabasePage() {
  const { appid: param } = useParams<{ appid: string }>();
  const appid = Number(param);
  const [c, setC] = useState<Community | null>(null);
  const [tools, setTools] = useState(new Map<string, string>());
  useEffect(() => {
    community(appid).then(setC);
    compatTools(appid).then((t) => setTools(new Map(t.map((x) => [x.strToolName, x.strDisplayName]))));
  }, [appid]);
  const name = appName(appid);

  return (
    <div style={{ marginTop: "40px", height: "calc(100% - 40px)", overflowY: "scroll", padding: "16px 24px" }}>
      <h2 style={{ margin: "0 0 4px" }}>{name}</h2>
      <div style={{ ...small, marginBottom: "16px" }}>
        Known good settings from the Kettle game database. Verified ones were checked by the Kettle team; community ones
        were shared by players and confirmed by the counts shown.
      </div>
      {!c && <div>Loading…</div>}
      {c?.error && <div>Couldn't reach the game database: {c.error}</div>}
      {c && !c.error && c.profiles.length === 0 && (
        <div>
          Nothing for this game yet. Once you find settings that work, mark them as working in Game Settings and share them.
        </div>
      )}
      <Focusable style={{ marginBottom: "24px" }}>
        {c?.profiles.map((e) => {
          const lines = describe(e, tools);
          const device = VARIANTS[e.variant] ?? e.device;
          return (
            <Field
              key={e.id}
              label={`${e.status === "approved" ? "✔ Verified" : "Community"} · ${e.rating === "great" ? "Great" : "Playable"}`}
              description={
                <>
                  <div>
                    {device}, Kettle {e.build} · works for {e.works}
                    {e.broken ? `, not for ${e.broken}` : ""}
                  </div>
                  <div style={{ fontFamily: "monospace" }}>{lines.join(", ") || "Default settings (runs as is)"}</div>
                  {e.notes && <div style={{ fontStyle: "italic" }}>“{e.notes}”</div>}
                </>
              }
              childrenLayout="below"
              bottomSeparator="thick"
            >
              <ButtonItem
                layout="below"
                onClick={() =>
                  showModal(
                    <ConfirmModal
                      strTitle="Use these settings?"
                      strDescription={`They replace the settings Game Settings has for ${name}. Your own launch options stay.`}
                      strOKButtonText="Apply"
                      onOK={() => apply(appid, e, tools)}
                    />,
                  )
                }
              >
                Apply
              </ButtonItem>
            </Field>
          );
        })}
        {c?.page && (
          <ButtonItem
            layout="below"
            onClick={() => showModal(<LinkModal title="On the web" text="This game's page in the game database." url={c.page!} />)}
          >
            Open on your phone
          </ButtonItem>
        )}
      </Focusable>
    </div>
  );
}
