# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Releases before 1.0.0 are early-stage: public interfaces (register maps, RTL
ports) may change between minor versions. A patch stays compatible with the
minor release it updates.

## [Unreleased]

### Added

- SEP secure DMA zero-fill opcode, `CONTROL.OPCODE` 4 (#3081).
- SMC cluster MMIO covers I3C instance 5 at `0xC003F000`, which took an access
  fault (#3362).

### Changed

- SMU top level: the SMC RAS outputs `smc_cluster_ded_o`,
  `smc_wdt_first_timeout_o` and `smc_wdt_second_timeout_o` are grouped into
  `smc_ras_o` (`smc_pkg::smc_ras_t`), which adds the AXI hang timeouts, the
  eFuse lifecycle integrity error and the UART and I2C integrity errors. A new
  `sep_ras_o` (`sep_pkg::sep_ras_t`) exports the SEP lockstep, watchdog, ICCM
  and DCCM ECC, Key Manager, DMA, crypto, bus and entropy faults, and is 0 when
  `CFG.SEP` is 0. `lc_sigint_err_o` is the OR of both structs' `lc_sigint_err`
  (#3339). `smc_ras_o.cluster_ded` is not held (#3500).
- SMU memory interfaces answer every read on the next clock and carry the macro
  clock in the request: the SEP SRAM and boot ROM (now `sep_boot_rom_req_t` and
  `sep_boot_rom_rsp_t`), Key Manager ROM and SRAM, I3C DAT, DCT and RLT
  memories and trace sink RAMs gain a `clk` field and drop `gnt`, `rvalid`,
  `rerror` and `q_valid` where they had them. The SEP SRAM request is
  `{clk, req, we, addr, wdata, wmask}` (#3360). Each memory clock, including
  the trace, I3C and Adams Bridge ones on packed-array ports, is constrained as
  a generated clock (#3360, #3579).
- SEP outbound traffic sets its security state and source ID per path: the AP
  output remap forces NS to 1, and the SMU aperture and addresses at or above
  4 GiB take NS from the inverse of address bit 55. `output_remap` gains
  `PROT_NS_OVERRIDE_EN`, `PROT_NS_OVERRIDE_VAL` and `PROT_NS_FROM_ADDR_EN`, off
  by default (#3225).
- Register blocks answer SLVERR only past their end, and OKAY in gaps and
  between instances of arrayed blocks (#3514, #3518).
- SEP watchdog reset clears the bite, and a cold reset must follow every
  watchdog timeout (#3341). The SMC second-stage watchdog flag is qualified by
  the first-stage timeout (#3502).
- SMC fabric demuxes look up the full AXI ID, so IDs sharing their low bits no
  longer stall each other across ports (#3308).
- `test_en_i` drives the SEP clock-gater and AXI cell test inputs and the
  scan-reset bypass of the CDC primitives, which were tied to 0 (#3221).
- SEP `LC_STATE` resets to `0x0F`, the INVALID hold before fuse sensing (#3450).
- Configuration checks run at elaboration through `OCAH_ASSERT_STATIC` (#3034).
- Integrator Guide: `smu_axi_in` carries no AXI atomics (#3591), and the SMU
  forwards illegal AXI burst encodings unchecked (#3593).
- AVSBus controller cites PMBus 1.3 Part III (#3394).
- AoU RTL moves to upstream 080724c. `AOU_TOP` gains `O_LP_LINKERROR` and
  `INT_FDI_LINK_DOWN` and loses `I_SW_DEACTIVATE_START` and `I_SW_RETRAIN_REQ`;
  nothing in this tree instantiates it (#3274, #3412).

### RTL bugs

RTL bugs fixed on `main` since v0.5.3, each with the pull request that fixed it.

- SEP Boot ROM set FIPS lock with the entropy FIFO enabled, so later software
  could read the DRBG seed (#3402).
- Key Manager wipe left keys already delivered to the crypto engines valid
  (#3260).
- Any write with a byte strobe set cleared SMC FLR isolation (#3359).
- TRNG divider and downsample counters loaded their CSR values asynchronously;
  they count up to them (#3413).
- Scratchpad and BEU accesses hung while an SMC core was held in reset (#3319).
- Zeroer changed WLAST while WVALID was high (#3626).
- `rr_arb_tree` left its round-robin register undriven with `FairArb=0`
  (#3398).
- SEP secure DMA set `STATUS.ABORTED` while granted writes could still land
  (#3163).
- Narrow AXI-Lite writes at byte lanes 1-3 reached TL-UL unaligned and were
  dropped with SLVERR (#3164).
- Mailbox `WIRQT` and `RIRQT` were declared 8 bits wide, so their generated
  collateral dropped the upper bytes (#3076).
- SMC DMA clock gate waited for its busy hysteresis instead of opening as soon
  as the DMA had work (#3516). iDMA read-write coupler channel fix (#3025).
- I2C bus timeout mid-byte corrupted the next transaction (#3166).
- SEP entropy-path counter and FSM faults reached no alert, and simulations with
  assertions failed at time 0 (#3326).
- SEP Boot ROM accepted the SMC invalid manifest offset (#3511) and misaligned
  boot storage addresses (#3261), and could skip the halt on a failed memory
  check (#3401).
- SMC firmware let the SEP reset hart 0 with stores still in its D-cache
  (#3503).

## [0.5.3] - 2026-10-09 (Beta)

### Added

- Native arm64 container image, published with the amd64 one under the same
  tag, so arm64 hosts such as Apple silicon no longer emulate x86_64 (#3012).
- `scripts/docker-run.sh` commands to list, refresh, prune and remove local
  images, and `OCAH_IMAGE_FALLBACK=main`, which runs the image CI last verified
  on `main` while a checkout's image is unpublished (#3027).

### Changed

- Documentation links point at `docs.tenstorrent.com/tt-oca-harness` (#3011).
- SMU inbound AXI port registered, which adds a cycle of latency, and SMU and
  SMC I/O delay constraints refreshed (#3007). I/O delay budgets come from a
  shared `io_delay_budgets.tcl` (#3024).
- Starting guide: memory requirement raised for synthesis, with a warning for
  synthesis on macOS (#3026).
- SEP Boot ROM: obsolete SPI pad-select hook removed (#2998).
- `peakrdl-rawheader` floats from 0.2.9, and the include-guard rewrite is
  dropped. Generated headers are unchanged (#3003).
- SMC regblock-wide scoreboard grades write responses (#2972).
- DV dashboard: each run gets its own trend point (#3006).
- Container images for amd64 build on the standard GitHub runner (#3017).

### Fixed

- Container: `HOME` set, so Verilator builds through `ccache` work under Podman.
  SMC DV runs failed with `ccache: error: not an absolute path: ""` (#3016).
- Container: Python packages that load native libraries work in the image
  without bundled uv dependencies, which now includes GNU coreutils (#3010).
- Container: `make format-nix` warns to run on the host instead of failing
  (#3023).
- `scripts/docker-run.sh` finds a loaded image with Docker 29 and later
  (#3015).
- Missing `make` aliases restored, and documented `CHECK=1` settings honoured
  (#3013).
- Documentation: the `vale` acronym check no longer times out, and PDF builds
  set a UTF-8 locale (#3021).
- DV: personal access tokens are redacted in environment snapshots (#3018), and
  host paths and host names are kept out of dashboard data (#3019).
- DV: `sep_km_handover_test` waits for the key-manager handover before the warm
  reset (#2997), and `smu_jtag_reset_override_test` waives the crypto EDN
  request-hold checks (#2917).

### RTL bugs

RTL bugs fixed on `main` since v0.5.2. Each entry is the issue and the pull
request that closed it.

- SEP secure DMA drove AxPROT 0, so AXI filters that pass the SEP CPU rejected
  its transfers. It now drives privileged secure data (#2995, #3005).

## [0.5.2] - 2026-10-08 (Beta)

### Changed

- SMC and SEP production ROMs take register definitions and SMC window offsets
  from the generated headers instead of hardcoded copies (#2992, #2994, #2549).
- The two longest SEP key-manager tests log less and run in under half the
  time (#2996).
- Weekly issue summaries close the earlier ones again (#2987).

### Fixed

- Container: `perl` on `PATH`, which cocotb's Verilator runner needs. DV runs in
  the container failed with `No such file or directory: 'perl'` (#3000).
- Starting guide: Podman machine on macOS sized to the memory requirement. The
  2 GB default fails firmware builds with `Killed signal terminated program lto1`
  (#2993).
- Starting guide: `run_dv.py` examples use the `smc` DUT and describe only wave
  options that exist (#2999).

### RTL bugs

RTL bugs fixed on `main` since v0.5.1. Each entry is the issue and the pull
request that closed it.

None.

## [0.5.1] - 2026-10-07 (Beta)

### Added

- Hang-detector status register, so software can identify which detector hung
  (#2944, #2367).
- Vivado elaboration flow for the emulation view, enabled for the SMU (#2954).
- `make update-integration-filelists` as the single entry point for
  `integration/filelists/` (#2931).
- SystemRDL `desc` text in the generated C headers (#2924).
- AXI VIP slave that serves several outstanding requests (#2964).
- DV scenarios for wide register-block strobes (#2923, #2940), the I3C5 CSR
  window from the SMC CPU (#2961), and an LC signature fault (#2959).
- SEP phase 3 verification plan and its phase 2 coverage groups (#2970).
- DTP DV bench prepared for publication, with its AXI responder patches in the
  shared VIP (#2980, #2968).
- Virtual-platform jobs as pull-request gates (#2981).
- Podman on macOS in `scripts/docker-run.sh` (#2979).
- Repository links in the documentation site header (#2952).
- Weekly issue summaries, charts, and a dedicated discussion category
  (#2930, #2947, #2948).

### Changed

- SMC external window split into mandatory and supplementary regions (#2922).
  The virtual platform follows the new strap and PVT offsets (#2976).
- SEP virtual-platform suite reduced to the critical smoke tests (#2919).
- Generic prim cells stay on the emulation filelists (#2951).
- `peakrdl-rawheader` 0.2.8 replaces the local svpkg template. Generated raw
  C header macro names are unchanged (#2939, #2901).
- SEP regression drops data-only reseeds and shortens the key-manager share
  walk (#2936).
- Starting guide leads with the prebuilt container (#2982).
- Release policy stated as semantic versioning (#2932).
- SEP threat model, SEP SPI, and SMC CPU sections clarified (#2918). The SMU
  AXI4 crossbar outline is dashed where the SEP is (#2945, #2933).
- DV comment hygiene across SMC, SMU, SEP, and DTP
  (#2955, #2957, #2958, #2962, #2965, #2966, #2967, #2974).

### Fixed

- GPIO interrupt lines sized from the total wrap count, so every wrap reaches
  the peripheral interrupt output (#2950).
- Each Bender source is listed once. `make lint-bender-sources` fails when one
  manifest lists a path twice under targets that can match together
  (#2975, #2911).
- SMU elaboration. The cross-trigger mode localparam keeps the full function
  result, and the DTP port takes the slice (#2954).
- Output-delay constraints no longer sit on top of de-skew constraints (#2973).
- Parameter assignments that synthesis reads only when they occupy one line
  (#2941).
- Remaining CDC and RDC violations (#2984).
- SMC lint findings from the weekly checks (#2978).
- `.envrc` dev-shell override syntax (#2937).
- DV runner keeps the checkout and run provenance (#2934, #2900).
- DTP VCS unreachability list matches the current RTL (#2971, #2953).
- DTP coverage-tier and unreachability claims (#2943).

### RTL bugs

RTL bugs fixed on `main` since v0.5.0. Each entry is the issue and the pull
request that closed it.

None.

## [0.5.0] - 2026-10-05 (Beta)

First public release of the Open Chiplet Atlas (OCA) Harness.

### Added

- RTL for the OCAH subsystems — `smc`, `sep`, `smu`, `dtp` — with the reusable IP
  blocks and shared primitives they build on (`hw/common/`, `hw/ip/`).
- SystemRDL register descriptions and their generated collateral (SystemVerilog,
  C headers, IP-XACT, HTML/AsciiDoc), plus the register-generation flow.
- Documentation set — Technical Reference Manual, Integrator Guide, Getting
  Started, and per-subsystem datasheets — published to the project site.
- Integrator-facing register, IP-XACT and timing indexes under `integration/`.
- Lint, format and DV tooling, and a Nix-based reproducible environment with a
  container for the RISC-V firmware toolchain.

[Unreleased]: https://github.com/tenstorrent/tt-oca-harness/compare/v0.5.3...HEAD
[0.5.3]: https://github.com/tenstorrent/tt-oca-harness/releases/tag/v0.5.3
[0.5.2]: https://github.com/tenstorrent/tt-oca-harness/releases/tag/v0.5.2
[0.5.1]: https://github.com/tenstorrent/tt-oca-harness/releases/tag/v0.5.1
[0.5.0]: https://github.com/tenstorrent/tt-oca-harness/releases/tag/v0.5.0
