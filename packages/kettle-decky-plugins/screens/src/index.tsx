import { PanelSection, PanelSectionRow, SliderField, ToggleField, staticClasses } from "@decky/ui";
import { callable, definePlugin } from "@decky/api";
import { useEffect, useState } from "react";
import { FaDesktop } from "react-icons/fa";

type State = { enabled: boolean; brightness: number };

const get = callable<[], State>("get");
const setEnabled = callable<[enabled: boolean], State>("set_enabled");
const setBrightness = callable<[percent: number], void>("set_brightness");

function Content() {
  const [s, setS] = useState<State | null>(null);
  useEffect(() => {
    get().then(setS).catch(() => {});
  }, []);
  if (!s) return null;
  return (
    <PanelSection title="Bottom screen">
      <PanelSectionRow>
        <ToggleField
          label="Bottom screen"
          description="The touch screen below. Off, it stays dark and ignores touches."
          checked={s.enabled}
          onChange={(enabled) => {
            setS({ ...s, enabled });
            setEnabled(enabled).then(setS).catch(() => {});
          }}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <SliderField
          label="Brightness"
          description="Steam's own brightness slider sets the top screen's."
          value={s.brightness}
          min={2}
          max={100}
          step={1}
          showValue
          valueSuffix="%"
          disabled={!s.enabled}
          onChange={(brightness) => {
            setS({ ...s, brightness });
            setBrightness(brightness).catch(() => {});
          }}
        />
      </PanelSectionRow>
    </PanelSection>
  );
}

export default definePlugin(() => ({
  name: "Screens",
  titleView: <div className={staticClasses.Title}>Screens</div>,
  content: <Content />,
  icon: <FaDesktop />,
}));
