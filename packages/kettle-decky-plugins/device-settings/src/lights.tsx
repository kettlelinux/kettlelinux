// The Lights tab: the RGB rings around the sticks and the power light, through kettle-ledd
// (lights.py in the backend)
import { DialogButton, DropdownItem, Focusable, PanelSection, PanelSectionRow, SliderField, ToggleField } from "@decky/ui";
import { callable } from "@decky/api";
import { useEffect, useState } from "react";

type Mode = "off" | "solid" | "battery" | "breathe" | "rainbow";
type PowerMode = "off" | "solid" | "battery" | "charging";
type Color = { hue: number; sat: number };
type Power = { mode: PowerMode; brightness: number; color: Color; sleep: boolean };
type State = {
  mode: Mode;
  brightness: number;
  sync: boolean;
  left: Color;
  right: Color;
  speed: number;
  power: Power;
  available: boolean;
  power_available: boolean;
  error: string | null;
};
type Settings = Omit<State, "available" | "power_available" | "error" | "power">;
type Changes = Partial<Settings> & { power?: Partial<Power> };

const get = callable<[], State>("lights_get");
const set = callable<[changes: Changes], State>("lights_set");

const MODES: { data: Mode; label: string }[] = [
  { data: "off", label: "Off" },
  { data: "solid", label: "Solid color" },
  { data: "battery", label: "Battery level" },
  { data: "breathe", label: "Breathe" },
  { data: "rainbow", label: "Rainbow" },
];

const POWER_MODES: { data: PowerMode; label: string }[] = [
  { data: "battery", label: "Battery level" },
  { data: "charging", label: "Charging only" },
  { data: "solid", label: "Color" },
  { data: "off", label: "Off" },
];

const PRESETS: Color[] = [
  { hue: 0, sat: 100 },
  { hue: 25, sat: 100 },
  { hue: 55, sat: 100 },
  { hue: 120, sat: 100 },
  { hue: 185, sat: 100 },
  { hue: 225, sat: 100 },
  { hue: 275, sat: 100 },
  { hue: 320, sat: 100 },
  { hue: 0, sat: 0 },
];

// the LEDs' full-value HSV color as CSS
const css = (c: Color) => `hsl(${c.hue}, 100%, ${100 - c.sat / 2}%)`;

const small = { fontSize: "12px", color: "#b8bcbf", lineHeight: "1.4" };
const strip = (background: string) => ({ height: "6px", borderRadius: "3px", background, margin: "0 16px" });
const HUES = `linear-gradient(to right, ${[0, 60, 120, 180, 240, 300, 360].map((h) => `hsl(${h}, 100%, 50%)`).join(", ")})`;

function ColorPicker({ title, color, onChange }: { title: string; color: Color; onChange: (c: Color) => void }) {
  return (
    <>
      <PanelSectionRow>
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <div style={{ width: "22px", height: "22px", borderRadius: "50%", background: css(color),
            boxShadow: "0 0 8px " + css(color) }} />
          <div>{title}</div>
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <Focusable flow-children="horizontal" style={{ display: "flex", justifyContent: "space-between", padding: "4px 0" }}>
          {PRESETS.map((p) => {
            const chosen = p.hue === color.hue && p.sat === color.sat;
            return (
              <DialogButton
                key={`${p.hue}-${p.sat}`}
                style={{ minWidth: 0, width: "24px", height: "24px", padding: 0, borderRadius: "50%",
                  background: css(p), border: chosen ? "2px solid white" : "2px solid transparent" }}
                onClick={() => onChange(p)}
              />
            );
          })}
        </Focusable>
      </PanelSectionRow>
      <PanelSectionRow>
        <SliderField label="Hue" value={color.hue} min={0} max={359} step={5} showValue valueSuffix="°"
          onChange={(hue) => onChange({ ...color, hue })} />
        <div style={strip(HUES)} />
      </PanelSectionRow>
      <PanelSectionRow>
        <SliderField label="Saturation" value={color.sat} min={0} max={100} step={5} showValue valueSuffix="%"
          onChange={(sat) => onChange({ ...color, sat })} />
        <div style={strip(`linear-gradient(to right, white, ${css({ hue: color.hue, sat: 100 })})`)} />
      </PanelSectionRow>
    </>
  );
}

export function LightsTab() {
  const [s, setS] = useState<State | null>(null);
  useEffect(() => {
    get().then(setS).catch(() => {});
  }, []);
  if (!s) return null;
  if (!s.available && !s.power_available)
    return (
      <PanelSection title="Lights">
        <PanelSectionRow>
          <div style={small}>{s.error ?? "This device has no lights Kettle knows how to set."}</div>
        </PanelSectionRow>
      </PanelSection>
    );

  const update = (changes: Partial<Settings>) => {
    // the backend's answer only brings its error: an older answer would undo a slider still moving
    setS((cur) => cur && { ...cur, ...changes });
    set(changes).then((r) => setS((cur) => cur && { ...cur, error: r.error })).catch(() => {});
  };
  const updatePower = (changes: Partial<Power>) => {
    setS((cur) => cur && { ...cur, power: { ...cur.power, ...changes } });
    set({ power: changes }).then((r) => setS((cur) => cur && { ...cur, error: r.error })).catch(() => {});
  };
  const p = s.power;
  const colored = s.mode === "solid" || s.mode === "breathe";
  const animated = s.mode === "breathe" || s.mode === "rainbow";

  return (
    <>
      {s.available && (
        <>
          <PanelSection title="Stick lights">
            <PanelSectionRow>
              <DropdownItem label="Mode" rgOptions={MODES} selectedOption={s.mode}
                onChange={(o) => update({ mode: o.data })} />
            </PanelSectionRow>
            {s.mode === "battery" && (
              <PanelSectionRow>
                <div style={small}>
                  Red when the battery is empty, yellow at half, green when full. Pulses while charging and
                  blinks red below 10%.
                </div>
              </PanelSectionRow>
            )}
            {s.mode !== "off" && (
              <PanelSectionRow>
                <SliderField label="Brightness" value={s.brightness} min={5} max={100} step={5} showValue valueSuffix="%"
                  onChange={(brightness) => update({ brightness })} />
              </PanelSectionRow>
            )}
            {animated && (
              <PanelSectionRow>
                <SliderField label="Speed" value={s.speed} min={0} max={100} step={10} showValue valueSuffix="%"
                  onChange={(speed) => update({ speed })} />
              </PanelSectionRow>
            )}
            {colored && (
              <PanelSectionRow>
                <ToggleField label="Same color on both sticks" checked={s.sync}
                  onChange={(sync) => update({ sync })} />
              </PanelSectionRow>
            )}
            {s.error && (
              <PanelSectionRow>
                <div style={{ ...small, color: "#ff7b6b" }}>{s.error}</div>
              </PanelSectionRow>
            )}
          </PanelSection>
          {colored && (
            <PanelSection title={s.sync ? "Color" : "Left stick"}>
              <ColorPicker title={s.sync ? "Both sticks" : "Left stick"} color={s.left}
                onChange={(left) => update({ left })} />
            </PanelSection>
          )}
          {colored && !s.sync && (
            <PanelSection title="Right stick">
              <ColorPicker title="Right stick" color={s.right} onChange={(right) => update({ right })} />
            </PanelSection>
          )}
        </>
      )}
      {s.power_available && (
        <PanelSection title="Power light">
          <PanelSectionRow>
            <DropdownItem label="Mode" rgOptions={POWER_MODES} selectedOption={p.mode}
              onChange={(o) => updatePower({ mode: o.data })} />
          </PanelSectionRow>
          <PanelSectionRow>
            <div style={small}>
              {p.mode === "battery" &&
                "On while the device is, in the battery's color: red when empty, yellow at half, green when full. Pulses while charging."}
              {p.mode === "charging" && "Orange while charging, green when full. Dark on battery."}
              {p.mode === "solid" && "On while the device is, in the color below."}
              {p.mode === "off" && "The light by the power button stays dark."}
            </div>
          </PanelSectionRow>
          {p.mode !== "off" && (
            <>
              <PanelSectionRow>
                <SliderField label="Brightness" value={p.brightness} min={5} max={100} step={5} showValue
                  valueSuffix="%" onChange={(brightness) => updatePower({ brightness })} />
              </PanelSectionRow>
              <PanelSectionRow>
                <ToggleField label="Dim light while asleep" checked={p.sleep}
                  description="Very dim, in its color going to sleep (orange while charging, green when full). It changes when the device wakes."
                  onChange={(sleep) => updatePower({ sleep })} />
              </PanelSectionRow>
            </>
          )}
          {p.mode === "solid" && (
            <ColorPicker title="Power light" color={p.color} onChange={(color) => updatePower({ color })} />
          )}
        </PanelSection>
      )}
    </>
  );
}
