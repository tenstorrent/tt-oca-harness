<!-- SPDX-License-Identifier: Apache-2.0 -->
# SEP OSS ROM/SRAM/OTP Shim Plan

> Historical shim-plan note: this document records the responder architecture and
> validation intent. The current user-facing layout and run guidance live in
> `README.md`; current test-selection/readiness lives in `SEP_OSS_VPLAN_PHASE1.md`
> (smoke + TOP-20) and `SEP_OSS_VPLAN_PHASE2.md` (basic-feature breadth).

## Goal

Provide open-source DV infrastructure for SEP ROM, SRAM, and OTP/eFuse behavior
without moving behavioral models into the DUT. The shims live under
`hw/sys/sep/dv/` and connect only at the bare `sep` external ports, so a
future OSS RTL-side model can replace them by updating `tb/tb_top.sv`,
`sep_sim_cfg.toml`, and the related tests.

## Boundary

The bare `sep` module exposes the replacement points:

- `sep_sram_req` / `sep_sram_rsp`
- `sep_boot_rom_req` / `sep_boot_rom_rsp`
- `efuse_bank_ctrl_req_o` / `efuse_bank_ctrl_resp_i`
- `efuse_shim_command_req_o` / `efuse_shim_command_resp_i`

`tb/tb_top.sv` is the single integration boundary. The DUT stays unchanged; the
testbench wires these external ports to DV-side responders.

## Architecture

The shim layout is:

- `shims/mem/tb_tcm_responder.sv`: existing ICCM/DCCM responder for CPU firmware
  boot from TCM.
- `shims/mem/tb_sep_sram_responder.sv`: 64-bit SRAM responder with byte-strobe
  writes and optional `+sep_sram_hex=<path>` initialization.
- `shims/mem/tb_boot_rom_responder.sv`: read-only 64-bit boot-ROM responder with
  optional `+sep_boot_rom_hex=<path>` initialization.
- `shims/analog/tb_sep_efuse_responder.sv`: deterministic OTP/eFuse responder
  for fuse sense without `+skip_fuse_sense`. It defaults to the generated
  `out/sep_efuse.hex` image and supports `+sep_efuse_hex=<path>` for overrides.
  OTP program failure injection is opt-in through
  `+sep_efuse_prog_fail_count=<n>` for deterministic first-N failures, or
  `+sep_efuse_prog_fail_percent=<0..100>` plus
  `+sep_efuse_prog_fail_seed=<seed>` for pseudo-random failures.

All shims are listed as extra build sources in `sep_sim_cfg.toml` and mirrored in
`sep_sim.core`.

## Adjacent Models

This plan covers the ROM/SRAM/OTP replacement points above. Adjacent OSS DV-side
models now cover the next memory and device boundaries:

- **KM ROM/SRAM + KM smoke firmware**: `tb_km_mem_responder.sv` implements the
  external KM ROM/SRAM ports and loads `.rom.parhex` images with `+km_rom_hex`.
- **OTBN IMEM/DMEM + program loading**: `tb_otbn_mem_responder.sv` implements
  the external encoded IMEM/DMEM ports and supports CPU-LSU frontdoor loads.
- **SPI device/flash model**: `tb_top.sv` exposes the OpenTitan SPI host pins to
  cocotb, where tests attach the Apache-2.0 `OcahSpiFlash` Python BFM.

## Memory Responders

The ROM and SRAM responders implement the `sep_sram_req_t` / `sep_sram_rsp_t`
protocol after `memory_interface` translates AXI addresses into local byte
offsets.

ROM behavior:

- 64-bit memory indexed by `addr >> 3`.
- `gnt=1` always.
- `rvalid` one cycle after request.
- Reads return the initialized word.
- Writes complete but ignore data, matching read-only ROM behavior.

SRAM behavior:

- 64-bit read/write memory indexed by `addr >> 3`.
- `gnt=1` always.
- One-cycle read/write completion.
- Byte strobes update individual bytes on writes.
- Default contents are zero unless a hex image is supplied.

## Memory Tests

Focused memory tests provide positive evidence that traffic reaches the shims:

- `sep_sram_smoke_test`: uses the existing CPU-LSU AXI splice to write/read the
  SRAM aperture, including a full 64-bit write and a 32-bit byte-strobed update.
- `sep_boot_rom_smoke_test`: boots the CPU from a small tracked ROM hex image and
  checks that the retired-instruction trace reaches the expected ROM loop PC.

These tests are registered under the `memory` testlist group.

## OTP/eFuse Responder

The OTP responder is intentionally scoped to the OSS test surface. It supports
the read/sense path used by eFuse image tests and the token-gated W1S programming
path used by the LCC stitch test:

- Stores `sep_efuse_pkg::NumFuseWords` 32-bit words.
- Initializes from `out/sep_efuse.hex` by default, or from
  `+sep_efuse_hex=<path>` when a test needs an explicit responder path.
- On `FUSE_COMMAND_READ`, streams one valid response per requested word.
- Returns `status=0` for reads.
- On supported program commands, overlays W1S-programmed bits onto the OTP image
  so reset/resense observes the newly programmed lifecycle state.
- Returns unsupported status for commands outside the modeled OSS test surface.
- Provides an always-OK AXI-Lite bank-control responder to prevent unused bank
  traffic from hanging the simulation.

The `efuse_image` run mode omits `+skip_fuse_sense`, so fuse sense runs through
the RTL controller and the behavioral OTP responder.

## OTP/eFuse Tests

The eFuse tests prove the bypass has been removed for real-sense modes:

- Holds the CPU off.
- Releases reset with no `+skip_fuse_sense` plusarg.
- Waits for `sep_fuse_sense_done_o` surfaced through `tb_top.sv`.
- `sep_efuse_sense_test` backdoor-compares the sensed shadow contents against the
  selected image.
- `sep_efuse_image_test` reads the shadow over AXI and then resenses a fresh image.
- `sep_efuse_lcc_lc_state_stitch_test` programs lifecycle state through
  `EFUSE_PROGRAM_CTRL`, cold-resenses, and checks the LCC decode against a golden.

Together these give positive evidence for sense completion, shadow load, resense,
frontdoor readout, and the W1S program/resense path.

## Replacement Switch

When OSS RTL-side ROM/SRAM/OTP models are available:

- Remove the corresponding shim source from `sep_sim_cfg.toml`.
- Rewire the matching external DUT port in `tb/tb_top.sv` to the new RTL model,
  or delete the connection if the behavior is internalized by the DUT.
- Keep the cocotb tests as regression coverage for the replacement model.
- Do not add broad compatibility layers. The stable contract is the bare `sep`
  external port behavior and the tests that prove it.

## Validation

Required checks after shim changes:

- `hw/sys/sep/dv/sim/run.sh --testlist`
- `hw/sys/sep/dv/sim/run.sh <test> --stage flist`
- `python3 tools/dv/check_no_vendor_paths.py --filelist hw/sys/sep/dv/build/sep_dut_compile.f`
- `python3 tools/dv/check_no_vendor_paths.py --filelist hw/sys/sep/dv/build/sep_bender.f`
- `sep_sram_smoke_test`
- `sep_boot_rom_smoke_test`
- `sep_efuse_sense_test`
- `sep_km_mem_smoke_test`
- `sep_otbn_mem_smoke_test`
- `sep_spi_flash_jedec_smoke_test`
- Existing regressions: `sep_axi_smoke_test`, `sep_address_map_test`,
  `sep_hello_world_test`
