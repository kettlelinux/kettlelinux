# Variable refresh rate (shelved, 2026-10-12)

Experiments toward VRR on the SM8550 devices, kept here so the kernel doesn't build them:
`scripts/build-kernel.sh` applies only `kernel/patches/*/`. Nothing here is in an image.

To try them again, copy the wanted patches back into `kernel/patches/40-kettle/` (they were written
against linux 7.2.7 after 1420) and `git apply kernel/parked/vrr/userspace/vrr.diff` for the
device tree, gamescope-session and Device Settings parts (plus `userspace/vrr.py` into
`device-settings/py_modules/`, and in its `main.py`: `import vrr` and two callables,
`get_vrr` → `vrr.get`, `set_vrr(on)` → `vrr.set_enabled`, both through `asyncio.to_thread`).
**Don't take the Portal's `kettle,msync` hunk:** it causes rainbow lines (below).

## Where it started

portareOS (github.com/portare-ch/portareos, Retroid Pocket Nova, also SM8550) gets real VRR from
the DPU's INTF AVR registers, in DSI **video mode** only. Its patches 1097, 1098, 1107 and 1108
(GPL-2) are our 1430-1433. The panel exposes `monitor_range` and `vrr_capable`, so gamescope works
unchanged (`adaptive_sync`).

## Results by panel

| Panel | Mode | Result |
|---|---|---|
| Thor bottom, CH13726A | video | **AVR works.** Clean only from 52 to 60 Hz: the panel drops rows once the front porch is past about 3.2 ms (about 250 extra lines). The AYN 120 Hz timing (1436 `thor_timing=2`) gives 100-120 Hz, and the panel RAM path doesn't help |
| Thor top, ICNA3520 | cmd + DSC | Video mode needs the DSI_MODE bits in 48h (1435). The picture shows, but under DSC noise with a 12-row period (the slice height). None of these fixed it: slices per packet (1437), the PPS in the vendor registers (1438), compression mode 07h (1440), one DSC encoder (1441). Uncompressed video mode (1439) gives pure noise. AYN ships command mode only |
| Portal, ICNA3512 | cmd + DSC | No VRR. See below |

### Portal ICNA3512: what the sync commands do

All of this was measured with 45h RDTESCAN, an 18-bit line counter that wraps at 262144 (about
0.95 s at 120 Hz). Read it as 3 bytes, one byte at a time per register: multi-byte reads of
1-byte registers return junk.

- **69h MSYNC** only stops TE output; the panel keeps scanning at a fixed 120 Hz. With the DPU tear
  window opened (1443/1445), frames are written blind into the scan, which gives rainbow lines (worst
  as the QAM opens). It is **not** VRR.
- **6Bh Qsync** is a real frame hold: the counter climbs and wraps forever. Nothing we sent ended
  it: 30 fps frames, 32h, an empty 2Ch, or 6Dh timeouts (big-endian, several values).
- **32h RTE, "Request TE ... a new command for MSYNC"** (datasheet) gave no TE under MSYNC: 20
  requests showed only the background rd_ptr rate.
- **65h WRMANDLY** (little-endian: MANUAL_DELAY = "manual AFP", VALID_TE_OFFSET) is stored (66h
  reads it back) but unused. 68h, the internal valid-offset counter, stays 0, and the scan never
  passes vtotal 2348. **67h** (undocumented) reads 0 and keeps no write.
- **91h** VR and **63h** LTPO (modes 1-16) change nothing; **97h-9Eh** are an on-screen FPS circle.
- The vendor registers (9Fh groups) **can't be read back**: generic and DCS reads return zeros even
  for B3/B5/CE, which the driver writes. A 9Bh PARA_SEL / group-read session blacked the screen
  (panel still reporting 9c) until a reboot.

What we take from this: the DDIC implements MediaTek MSync 2.0 (request-TE) and Qualcomm Qsync,
but their timing setup (AFP, valid-TE window, as in the MediaTek NT37801 tables below) lives in
undocumented vendor registers that AYN's init never writes. Only Chipone or AYN can say which.

## Protocol references

- **MediaTek MSync 2.0 request-TE:** OnePlusOSS/android_kernel_5.10_oneplus_mt6895
  `drivers/gpu/drm/panel/panel-nt37801-msync2-rte.c` and `mediatek_v2/mtk_drm_crtc.c`
  (`mtk_crtc_msync2_send_cmds_bef_cfg`); NothingOSS/android_kernel_5.15_nothing_mt6886
  `panel-l12a-42-02-0a-dsc-cmd.c`.
  - Per frame, the AP sends RTE (3F 00 on Novatek), the DDIC answers with TE inside its valid-TE
    window, and the AP writes 2Ch.
  - The Novatek panel tables set: max AFP `6F 26; C0 0A 00`, valid TE start/end `40 12 BC` /
    `40 1C B0`, MSync on `40 07`, RTE enable `2F 12`.
- **Qualcomm cmd-mode Qsync:** LineageOS/android_kernel_ayn_qcs8550-modules `sde_encoder_phys_cmd.c`
  `_get_tearcheck_threshold`.
  - No per-frame panel command. The tear-check threshold is the lines up to `qsync_min_fps`
    (rounded down to 4, minus 2), with height 0xFFF0.
  - `rd_ptr` is overridden to vdisplay + thresh + 1 on every wr_ptr irq.
  - The panel is expected to hold after one TE until a frame starts inside the window, or until its
    timeout.
  - Panel examples: vtdr6130 (`bb 01` plus a `ce` table) and LG sw43404 (`5a 01`).
  - AYN's own icna3512/icna3520 dtsi have no qsync properties.
- Chipone's ICNA3512 datasheet: github.com/csvke/panel-chipone-icna3512 (reference/). AYN's panel
  nodes: github.com/LineageOS/android_kernel_ayn_qcs8550-devicetrees `qcom/display`.

## Files

- `patches/`
  - 1430-1433: portareOS AVR, LFC, flip and fence fixes.
  - 1434: CH13726A `kettle,vrr-min-hz`.
  - 1435-1441: ICNA35xx video-mode experiments (module params `video_mode`, `dsc_cfg`;
    `msm.dpu_dsc_single`).
  - 1436: CH13726A `thor_timing`, `ram`.
  - 1437: DSC slices per packet.
  - 1442: debugfs `icna35xx_regs` (`w`/`d`/`r`/`g`; at `/sys/kernel/debug/dri/0/DSI-N/panel/`).
  - 1443: `msm.dpu_te_sync_thresh`/`_height`.
  - 1444: `kettle,msync`.
  - 1445: open tear window plus kickoff gap for a vrr_capable cmd panel.
  - 1446 (written 10-12, not yet built or tested): runtime-writable `msm.dpu_dsc_initial_lines`.
    Mainline computes 2 for our 540-wide slices; Qualcomm's DSC 1.2 formula gives 3 (two merged
    encoders) or 4 (one encoder, 1441). This is the next Thor top-panel video-mode test: try 3-6,
    then restart the display.
- `userspace/`: the device tree, gamescope-session (`vrr.conf`) and Device Settings toggle diff, and
  `vrr.py` (GAMESCOPE_VRR_CAPABLE, `gamescopectl adaptive_sync`).
- `tools/`
  - `vrr-probe.c`: adapted from portareOS's probe, GPL-2. Cross-compile with clang against an
    image rootfs (`-nostartfiles` plus crt1/crti/crtn).
  - `run-*.sh`, `vm-*.sh`, `bootopt.sh` (test kernel options through `/etc/kettle/boot.conf`).
  - `regs.sh`, `p*.sh`: the Portal register and scanline tests.

## RP5 (research 2026-10-12, untested)

- **CH13726A units** (`ch13726a,rp5`, `panel-ddic-ch13726a.c`) run in **video mode** at 60 Hz
  (vtotal 1948). Downstream Kona has the INTF AVR registers at 0x270-0x27C, and the mainline sm8250
  INTF block (0x2c0) covers them. So 1430 should work once its DPU >= 9 gate is lowered to 6, and
  1434 needs porting to this driver. Going by the Thor's ~250-line limit, the expected range is only
  about 52-60 Hz.
- **Visionox VTDR6130 COG units** (`vtdr6130,rp5`, `panel-visionox-vtdr6130-cog.c`) run in command
  mode with DSC (540x12 slices), 60 Hz only in Kettle (0106).
  - Rates: `6C 00` = 120 Hz, `6C 01` = 60 Hz (AYN's cog dtsi).
  - Qualcomm's HDK dtsi for this panel family has Qsync (min 95 Hz at 144):
    - on: `F0 AA 13; CE 09 11 09 11 08 C1 07 FA 05 A4 00 3C 00 3C 00 3C 00 0C 00 0C 04 00 00;
      F0 AA 10; BB 00 4C 00 01 FF 01 32 01 6E 01 6E; BB 01`
    - off: `F0 AA 10; BB 00`, then the normal CE table.
    - The COG's CE table differs, so don't write the HDK CE values. Try BB alone first.
  - On the host side, Qsync is only the tear-check window: threshold = lines to the minimum rate
    (about 1950 at 60 Hz with a 40 Hz minimum). SM8250's TE is in the INTF, so 1443/1445 apply.
  - Tell the variants apart with `/proc/device-tree/model` ("Retroid Pocket 5 Visionox").

## Chipone search (2026-10-12)

- No public source configures MSync, Qsync or TE extension on any Chipone DDIC. Every MediaTek MSync
  panel driver found is Novatek, Samsung or similar, and the Chipone FAE notes
  (github.com/Mirac1e-Yao/obisdian-backup) say nothing about it. The application notes are not
  public.
- **A shipping Chipone DSC video-mode reference:** Motorola ICNA3508
  (MotorolaMobilityLLC/kernel-display-devicetree, `android-14-release-u3uo34.49-15-2`,
  `display/dsi-panel-mot-tm-icna3508-ft3683g-667-1080x2400-video.dtsi`), Qualcomm DPU, 540x12
  slices, 2 slices per packet, non-burst sync events, porches H 32/32/32, VBP 20, VFP 36, pulse 4.
  - On: `9C A5 A5; FD 5A 5A; 48 23; 51 FF 0F; 53 E0; 11 (120 ms); 9F 01; B4 10 00 00 03;
    51 0D BA; 53 E0; 35; 29`.
  - Rates: `90 00` + `48 03`/`48 13`/`48 23` (60/90/120, video bypass GRAM).
  - The group-1 `B4 10 00 00 03` is the one write we never sent in the Thor-top video-mode tests.
- Cheap, untested ideas:
  - 32h RTE **before** 29h (the datasheet's restriction says RTE has no effect once the display is
    on).
  - 6Dh TE_EXT_TIME_OUT with MSYNC on (not Qsync).
