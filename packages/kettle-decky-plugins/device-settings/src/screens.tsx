// The Screens tab: the Thor's bottom screen (screens.py in the backend): on or off, its own
// brightness, 30 or 60 Hz
import { PanelSection, PanelSectionRow, SliderField, ToggleField } from "@decky/ui";
import { callable } from "@decky/api";
import { useEffect, useState } from "react";

type State = { enabled: boolean; brightness: number; refresh_hz: number };

const get = callable<[], State>("screens_get");
const setEnabled = callable<[enabled: boolean], State>("screens_set_enabled");
const setBrightness = callable<[percent: number], void>("screens_set_brightness");
const setRefresh = callable<[hz: number], State>("screens_set_refresh");

export function ScreensTab() {
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
      <PanelSectionRow>
        <ToggleField
          label="30 Hz"
          description="Refreshes at 30 Hz instead of 60, for about 0.1 W less. Scrolling and moving readings on it are less smooth."
          checked={s.refresh_hz === 30}
          disabled={!s.enabled}
          onChange={(on) => {
            const refresh_hz = on ? 30 : 60;
            setS({ ...s, refresh_hz });
            setRefresh(refresh_hz).then(setS).catch(() => {});
          }}
        />
      </PanelSectionRow>
    </PanelSection>
  );
}
