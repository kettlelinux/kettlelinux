# Kernel patch stack: cix flavour (CIX P1 / Sky1, Radxa Orion O6N)

Applied in directory order, then file order, with `patch -p1 --fuzz=0` by
`KERNEL_FLAVOUR=cix scripts/build-kernel.sh` (or `KETTLE_DEVICE=radxa-o6n`). Base: Linux 7.3-rc7,
the same source as the qcom kernel (`../kernel.conf`). The board boots UEFI with ACPI only, so
there are no device trees here.

| Dir | Source | Notes |
|---|---|---|
| `20-cix` | CIX's BSP series, github.com/cixtech/cix-linux-main @ `6d69935080f85fb9ae2fb5335f50434215a3b0aa`, as ported to 7.2.7 in 06n-arch (`pkgs/linux-o6n/patches/7.2`, its `PORTING.md`) | ACPI/SCMI glue (mailbox, SCMI, clocks, resets, pmdomains, syscon, regulators, pinctrl), Panthor on Sky1 (00111-00116, 0063), the linlon-dp display driver and DP/HDMI (00100/00101, 0043, 0047, 0053, 0057, 1001-1009), HDA and SOF/DSP audio, Cadence USB (cdnsp) and the RTS5453 Type-C controller, Sky1 PCIe, SMMUv3 suspend, thermal IPA, `cix_dst`. 1001-1009 and 2003/2004 are 06n-arch's fixes for building CIX's drivers on mainline 7.x. Each patch keeps CIX's header; 06n-arch's notes say `[o6n: ported to 7.2: ...]`, ours `[kettle: ported to 7.3: ...]` |
| `40-kettle` | ours (from 06n-arch, by the same author, and new) | 3001: Panthor on Sky1 maps GPU memory cached and only imported dma-bufs uncached (the GPU isn't coherent there; uncached everything made it ~7x slower: Skyrim SE ~7 -> ~50 fps); 3002: Panthor doesn't wait on a syncobj BO's reservation while holding `sched->lock` (GPU stalls under memory pressure); 3003: the GPU Energy Model from SCMI, so the power_allocator thermal governor can budget the GPU zone; 3004: `cix-sky1-fan`, the fan's quiet/balanced/performance mode (the DSDT's SPFM/SPFA/SPFP methods) as a platform profile; 3005: `cix_dst`'s `boot_record()` copies at most its event buffer (it copied `strlen(str)` bytes into a fixed buffer, and checked the slot count outside its lock); 3006: `soc_button_array` builds on ARM64 again (7.3 made it X86-only): the O6N's power button is an ACPI0011 Generic Buttons device, and without it the button neither works nor wakes the board from s2idle; 3007: the VPU's driver (amvx, CIX's Linlon/Mali-V codec, bound by ACPI `CIXH3010`), CIX's out-of-tree `cix_opensource__vpu_driver` @ `51d1ec01` with the two fixes CIX's Debian package applies (NV12M rather than AFBC by default, 16-byte chroma stride) and 06n-arch's `strscpy()`, built in the tree (`drivers/media/platform/cix`) instead of by DKMS |

## Linux 7.3 rebase (2026-10-17)

The 7.2 series applied in order to a git tree of the 7.3-rc7 tarball, one commit per patch,
exported with each original header: of its 90 patches 80 applied as they are (3 with fuzz), 7
are ported and 3 dropped; 3005-3007 are new.

Dropped, upstream in 7.3: 00050 (Sky1 audss CRU bindings), 00051 (the audss clock driver),
00060 (the audss reset driver). Upstream's versions are CIX's reworked after review (devm probe,
`clk_parent_data`, the noc reset released only after the clocks are on).

Ported (each says how in its header):
- 0001 mailbox ACPI: 7.3's probe reports errors with `dev_err_probe`.
- 00053 and 00062, the audss clock's and reset's ACPI support: rebased onto the upstream drivers.
  The clock's ACPI D0 transition (the PPRS power resource) still comes before the first CRU
  register access.
- 0013 HDA ipbloq (and 0071 on top of it): CIX's Sky1 alc269 fixups appended after the ones 7.3
  added.
- 0031 (Sky1 PCIe) and 00100 (linlon-dp): compile fixes for 7.3's renames
  (`PCIE_LINK_WAIT_MAX_RETRIES`, `drm_of_get_panel_orientation()`).
- 1006 `fwnode_drm_find_panel()`: 7.3's panel lookups return a counted reference, so this is a
  wrapper of the fwnode lookup, and the trilin eDP caller drops its reference on unbind (and the
  fwnode reference it leaked). The O6N has no eDP panel, so that path doesn't run there.

Applied with fuzz only (context lines changed upstream; +/- lines checked by hand): 00052,
00114 (`panthor_vm_create`'s `pgsize_bitmap`), 0032.

Not run on hardware yet; 06n-arch's PORTING.md risk list (USB, SCMI, SMMU, DRM panel lifetime)
still applies.
