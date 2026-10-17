// The Buttons tab: what the rear buttons do, on the devices whose controller lets them copy another
// button (the KONKR Pocket FIT Elite's MCU; buttons.py in the backend)
import { DropdownItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { callable } from "@decky/api";
import { useEffect, useState } from "react";

type Side = "left" | "right";
type State = { available: boolean; error?: string | null; left?: string; right?: string };

const get = callable<[], State>("buttons_get");
const set = callable<[side: Side, target: string], State>("buttons_set");

const TARGETS: { data: string; label: string }[] = [
  { data: "none", label: "Nothing" },
  { data: "a", label: "A" },
  { data: "b", label: "B" },
  { data: "x", label: "X" },
  { data: "y", label: "Y" },
  { data: "up", label: "D-pad up" },
  { data: "down", label: "D-pad down" },
  { data: "left", label: "D-pad left" },
  { data: "right", label: "D-pad right" },
  { data: "lb", label: "LB" },
  { data: "rb", label: "RB" },
  { data: "lt", label: "LT" },
  { data: "rt", label: "RT" },
  { data: "l3", label: "Left stick click" },
  { data: "r3", label: "Right stick click" },
  { data: "view", label: "View" },
  { data: "menu", label: "Menu" },
];

const small = { fontSize: "12px", color: "#b8bcbf", lineHeight: "1.4" };

export function ButtonsTab() {
  const [s, setS] = useState<State | null>(null);
  useEffect(() => {
    get().then(setS).catch(() => {});
  }, []);
  if (!s) return null;
  if (!s.available)
    return (
      <PanelSection title="Rear buttons">
        <PanelSectionRow>
          <div style={small}>This device's rear buttons can't be set.</div>
        </PanelSectionRow>
      </PanelSection>
    );

  const pick = (side: Side, target: string) => {
    setS({ ...s, [side]: target });
    set(side, target).then(setS).catch(() => {});
  };

  return (
    <PanelSection title="Rear buttons">
      <PanelSectionRow>
        <DropdownItem label="Left rear button" rgOptions={TARGETS} selectedOption={s.left}
          onChange={(o) => pick("left", o.data)} />
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem label="Right rear button" rgOptions={TARGETS} selectedOption={s.right}
          onChange={(o) => pick("right", o.data)} />
      </PanelSectionRow>
      {s.error && (
        <PanelSectionRow>
          <div style={{ ...small, color: "#ff7b6b" }}>{s.error}</div>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <div style={small}>
          A rear button presses the button you pick, so games and Steam Input see that button, not a
          button of its own. The controller keeps the setting, in every game and in Desktop Mode.
        </div>
      </PanelSectionRow>
    </PanelSection>
  );
}
