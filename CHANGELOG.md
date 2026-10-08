# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Releases before 1.0.0 are early-stage: public interfaces (register maps, RTL
ports) may change between minor versions. A patch stays compatible with the
minor release it updates.

## [0.5.2] - Unreleased

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

[0.5.2]: https://github.com/tenstorrent/tt-oca-harness/compare/v0.5.1...HEAD
[0.5.1]: https://github.com/tenstorrent/tt-oca-harness/releases/tag/v0.5.1
[0.5.0]: https://github.com/tenstorrent/tt-oca-harness/releases/tag/v0.5.0
