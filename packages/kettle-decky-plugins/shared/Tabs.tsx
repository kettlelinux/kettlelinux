// A Quick Access panel's tabs: a row of icon buttons, as narrow as the panel allows (keep the
// labels short: a long one wraps). The D-pad moves along the row; the plugin keeps the open tab
// while the panel is closed.
import { DialogButton, Focusable, PanelSectionRow } from "@decky/ui";
import { ReactElement } from "react";

export type Tab = { id: string; label: string; icon: ReactElement };

export function Tabs({ tabs, tab, onChange }: { tabs: Tab[]; tab: string; onChange: (id: string) => void }) {
  return (
    <PanelSectionRow>
      <Focusable style={{ display: "flex", gap: "4px", marginBottom: "8px" }} flow-children="horizontal">
        {tabs.map((t) => (
          <DialogButton
            key={t.id}
            onClick={() => onChange(t.id)}
            style={{
              flex: 1,
              minWidth: 0,
              padding: "6px 0 4px",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: "2px",
              fontSize: "10px",
              lineHeight: "12px",
              borderBottom: `3px solid ${t.id === tab ? "#1a9fff" : "transparent"}`,
              opacity: t.id === tab ? 1 : 0.7,
            }}
          >
            <span style={{ fontSize: "16px", lineHeight: "16px" }}>{t.icon}</span>
            <span style={{ maxWidth: "100%", overflow: "hidden", textAlign: "center" }}>{t.label}</span>
          </DialogButton>
        ))}
      </Focusable>
    </PanelSectionRow>
  );
}
