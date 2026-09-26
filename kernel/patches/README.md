# Kernel patch stack

Applied in directory order, then file order, with `patch -p1 --fuzz=0` by
`scripts/build-kernel.sh`. Base: kernel.org 7.2.7 (pinned in `../kernel.conf`).

| Dir | Source | Notes |
|---|---|---|
| `10-mainline` | ROCKNIX `projects/ROCKNIX/packages/linux/patches/mainline` | input-polldev, pwm_set_period, adc-keys, RTL8733BU |
| `20-sm8550` | ROCKNIX `projects/ROCKNIX/devices/SM8550/patches/linux` + pocknix-os suspend/UFS/SD additions | Portal: 0057 ICNA35XX panel, 0031/1003/1004/1009 rsinput gamepad, 0033 HTR3212 LEDs, 1000-1005 haptics, 0066 DPU inline rotation |
| `30-version` | ROCKNIX `packages/linux/patches/7.2` via pocknix-os | 0010 carries pocknix's `cstate` uninitialized fix; ROCKNIX 9999 (perf/rust build fix) dropped |
| `40-kettle` | ours | 1060: pcie-qcom `#iommu-cells` SID fix (Manivannan Sadhasivam, via NovaDeck) — 7.2.6+ breaks WCN7850 Wi-Fi without it; 1100: rsinput UART frame reassembly (Armada 0515, rebased) — fixes "Checksum mismatch" and dead pad after resume; 1110: drm/msm debugfs `perf_now` (devfreq GPU load %) — what Valve's mangoapp reads for the overlay's GPU usage; 1120: ICNA3512 backlight floor (slider 0..4096 scaled onto DCS 1330..4096) — lower levels shift colours and go black |

Pinned upstreams:
- pocknix-os `kernel/sm8550` @ `70bd590350f662865dfd8868be15bc731993a6f0` (github.com/shuuri-labs/pocknix-os)
- ROCKNIX distribution @ `5607f6e149934b39196f7a128804d2c04e25ce88`
- NovaDeck os-build @ `b5d61c0`

`../dts/` is ROCKNIX's `devices/SM8550/linux/dts` (Portal: `qcs8550-ayn-odin2portal.dts`,
© Teguh Sobirin). Upstream equivalent is Aaron Kling's "Support AYN QCS8550 Devices"
series (v9, not merged); the Portal panel driver lands upstream in 7.3 as
`panel-chipone-icna35xx` with compatible `ayntec,odin2portal-panel`.

20 patches were refreshed for 7.2.7 context with `scripts/refresh-patches.sh`
(context/offsets only; +/- content verified identical to upstream).

## Dropped
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

## Candidates not yet applied
- Valve `linux-neptune-72` (7.2.4-valve1): `HID: steam` 2026 Steam Controller series
  (`cbb072a1b4d3` and follow-ups), `xbox_gip`, uinput interruptible wait.
- Igalia robust-futex arm64 vDSO (`tonyk/robust_arm` @ `34e9604082b5`) for Proton/FEX.
- Armada suspend refinements (0504 IPCC masked only for s2ram, 0515 rsinput frame reassembly).
