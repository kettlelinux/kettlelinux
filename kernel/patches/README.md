# Kernel patch stack

Applied in directory order, then file order, with `patch -p1 --fuzz=0` by
`scripts/build-kernel.sh`. Base: kernel.org 7.2.9 (pinned in `../kernel.conf`).

| Dir | Source | Notes |
|---|---|---|
| `10-mainline` | ROCKNIX `projects/ROCKNIX/packages/linux/patches/mainline` | input-polldev, pwm_set_period, adc-keys, RTL8733BU |
| `20-sm8550` | ROCKNIX `projects/ROCKNIX/devices/SM8550/patches/linux` + pocknix-os suspend/UFS/SD additions | Portal: 0057 ICNA35XX panel, 0031/1003/1004/1009 rsinput gamepad, 0033 HTR3212 LEDs, 1000-1005 haptics, 0066 DPU inline rotation |
| `21-sm8250` | ROCKNIX `projects/ROCKNIX/devices/SM8250/patches/linux` | Retroid Pocket 5: 0004/0005 PM8150B charger+fg nodes and uart16, 0008/0013 Retroid gamepad MCU + rumble, 0009 PM8150B SPMI haptics, 0011 PM8150B charger/fuel-gauge drivers, 0012/0100 q6asm/sm8250 audio, 0102 PM8150 RTC offset, 0105 VTDR6130 RP5 mode (its vendor-page hunk dropped: `20-sm8550/1022` has it) and our 0106 exposing only its 60Hz mode (as 1021 does for the RP6; pocknix-os carries the same), 0300 wcd938x jack IRQ guard. 0014 is only the ath11k half of ROCKNIX's MAC fix (btqca/socinfo are in `20-sm8550/0501`). 0058 is ours: the 120 ms sleep-out delay ROCKNIX's SM8250 CH13726A driver has. 0110-0112 are ROCKNIX's 9998 split up: 0110 the A650's DDR bandwidth votes (`gfx-mem` path and stock per-OPP peak votes; mainline's GPU never votes DDR), 0111 its overclock ladder up to 750 MHz only (manual GPU clock only: kettle-powerd's `auto_max_mhz`), 0112 its ACD levels. 0114 is ours: the CPUs' DDR votes tagged active-only (as sm8550 does), so DDR can self-refresh in s2idle. 0115 is ours: the PM8150B charger's fast-charge current as `constant_charge_current` (capped by the battery's `constant-charge-current-max-microamp`, 5.35 A on the RP5) and its charging enable as `charge_behaviour` (auto / inhibit-charge); kettle-powerd holds the charge limit with inhibit-charge (the battery sits at 0 mA, the charger powers the system; a fast-charge current of 0 still drains ~200 mA) and sets the charge speed with the current. **Shared with SM8550** (re-test the Portal/Thor): 0001 DSI wide_bus bpp, 0016 DSI link clocks left on while the display runs, 0058, 0300 |
| `30-version` | ROCKNIX `packages/linux/patches/7.2` via pocknix-os | 0010 carries pocknix's `cstate` uninitialized fix; ROCKNIX 9999 (perf/rust build fix) dropped |
| `40-kettle` | ours | 1060: pcie-qcom `#iommu-cells` SID fix (Manivannan Sadhasivam, via NovaDeck) — 7.2.6+ breaks WCN7850 Wi-Fi without it; 1100: rsinput UART frame reassembly (Armada 0515, rebased) — fixes "Checksum mismatch" and dead pad after resume; 1110: drm/msm debugfs `perf_now` (devfreq GPU load %) — what Valve's mangoapp reads for the overlay's GPU usage; 1120: ICNA3512 backlight floor (slider 0..4096 scaled onto DCS 1130..4096) — lower levels shift colours and go black; 1130: CH13726A backlight named after the panel's dts `label` — the Thor's bottom panel is `bottom-panel`, which sorts after the top panel's `ae96000.dsi.0`, so Steam's brightness slider (first backlight) drives the top screen; 1150: qcom-geni serial forces the runtime suspend of open, non-console ports in suspend_late (the PM core's own runtime PM reference otherwise keeps their SE clocks, OPP and QUP/NoC votes on through s2idle, blocking CX collapse); 1160: ufs-qcom enables its lane clocks (all of the host's clocks) only once; a runtime resume enabled them twice and leaked a reference each time, so the UFS clocks never turned off and kept XO on in s2idle (upstream bug); 1140: pcie-qcom clears Hot-Plug Capable on SM8250 (as mainline did before NCCS) — the RP5's root port otherwise never reaches D3 in suspend (no pciehp), so PCIe keeps CX and interconnect votes and s2idle never reaches CX collapse; 1170: qcom_battmgr registers its power supplies without a wakeup source — the charger firmware's notifications (many a minute while charging) otherwise each count as a wakeup event and end s2idle within minutes, which is what `20-sm8550/0502` worked around; 1180: drm/msm a6xx drops the kernel's boot-time GPU bus vote once the GMU votes bandwidth (a740+) — a6xx_gmu_set_initial_bw() votes the 680 MHz OPP's 16.5 GB/s at every GMU resume and nothing removed it while the GPU stayed powered, so DDR sat at 4224 MHz with the screen on (upstream bug); 1190: qcom_battmgr exposes the charger firmware's fast-charge current (BATT_CHG_CTRL_LIM) as `constant_charge_current` (and `_max`) on SM8550 (Portal default 8 A, Thor 4.68 A) — the Portal's firmware never answers the charge limit request (`charge_control_end_threshold` does nothing), so kettle-powerd holds the charge limit by setting 0 at the limit (the charger then powers the system, the battery sits idle) and sets the Power plugin's charge speed with it |

Pinned upstreams:
- pocknix-os `kernel/sm8550` @ `70bd590350f662865dfd8868be15bc731993a6f0` (github.com/shuuri-labs/pocknix-os)
- ROCKNIX distribution @ `5607f6e149934b39196f7a128804d2c04e25ce88`
- NovaDeck os-build @ `b5d61c0`

`../dts/` is ROCKNIX's `devices/SM8550/linux/dts` plus, for the RP5, `devices/SM8250/linux/dts` (`sm8250-retroidpocket-{common.dtsi,rp5.dts,rp5-visionox.dts}`, `sm8250-pwm-fan-cooling.dtsi`) (Portal: `qcs8550-ayn-odin2portal.dts`,
© Teguh Sobirin). Upstream equivalent is Aaron Kling's "Support AYN QCS8550 Devices"
series (v9, not merged); the Portal panel driver lands upstream in 7.3 as
`panel-chipone-icna35xx` with compatible `ayntec,odin2portal-panel`.

20 patches were refreshed for 7.2.7 context with `scripts/refresh-patches.sh`
(context/offsets only; +/- content verified identical to upstream).

## Dropped
- `20-sm8550/0502-wakeup-qcom-ipcc-remove-IRQF-NO-SUSPEND` (masks the IPCC mailbox IRQ across
  suspend so the charger firmware's notifications can't wake the AP). Nothing answers the
  ADSP while it's masked: about five minutes into s2idle the charger stops drawing power
  (seen on the Thor with a 20 W PD charger), and a device left asleep on its charger ran the
  battery flat. `40-kettle/1170` keeps the AP asleep instead.
- ROCKNIX `20-sm8550/0004-drm-msm-a6xx-Enable-IFPC-on-Adreno-740` (enables IFPC on A740
  with the A750 IFPC reglist). Under test as the cause of GMU `GX_BW_PERF_VOTE` HFI and
  `OOB GPU_SET` timeouts that end in a CP fault at iova 0 and a hangcheck recovery that
  deadlocks in `a6xx_gmu_stop` (frozen display, minutes after boot).
  Dropping it did not stop the hangs (seen again on the IFPC-free build).
- `20-sm8550/1051-arm64-dts-qcom-sm8550-add-lowest-gpu-opp` (Thorch; 124.8 MHz A740 OPP from
  the AYN Thor Android DT, no `qcom,opp-acd-level`). Under test as the cause of the same GMU
  `OOB GPU_SET` / `GX_BW_PERF_VOTE` timeouts: the GPU idles at this level ~75% of the time, so
  nearly every wake from slumber starts from it. It shares LOW_SVS_D2 and the bus vote with
  220 MHz, so dropping it costs no measurable power.

## Not taken from ROCKNIX SM8250
- 0010 htr3212, 0015 edt-ft5x06, 0017 hdmi hw_params, 0047 aw88166, 0104 RP6 panel, 0504, 0505,
  9997 boot fan speed: already in `20-sm8550` (ours are the same or newer).
- 0057 ICNA35XX, 0060/0063/0064 Mangmi, 0061 aw200xx, 0062 wsa881x shared GPIO, 0065 cst66xx
  iovcc, 0066/0067 PM8150L LCDB: for SM8250 devices other than the RP5.
- 9998's 800-925 MHz A650 steps: 800 MHz gained almost nothing over 750 at 82 C, near the 85 C passive trip, with the fan at full speed (the rest is taken as 0110-0112).
- 9999 log-spam silencing: comments out real errors (and changes `net/core/sock.c` behaviour).

## Candidates not yet applied
- Valve `linux-neptune-72` (7.2.4-valve1): `HID: steam` 2026 Steam Controller series
  (`cbb072a1b4d3` and follow-ups), `xbox_gip`, uinput interruptible wait.
- Igalia robust-futex arm64 vDSO (`tonyk/robust_arm` @ `34e9604082b5`) for Proton/FEX.
- Armada suspend refinements (0504 IPCC masked only for s2ram, 0515 rsinput frame reassembly).
