# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Releases before 1.0.0 are early-stage: public interfaces (register maps, RTL
ports) may change between minor versions.

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

[0.5.0]: https://github.com/tenstorrent/tt-oca-harness/releases/tag/v0.5.0
