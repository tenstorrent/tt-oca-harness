<!-- markdownlint-disable MD033 -- HTML is required for the centered banner and badges -->
<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="doc/ui-supplemental/img/oca_white.svg">
    <img alt="Open Chiplet Atlas" src="doc/ui-supplemental/img/oca_black.svg" width="360">
  </picture>
</p>

<h1 align="center">Open Chiplet Atlas Harness (OCAH)</h1>

<p align="center">
  Tenstorrent reference design (harness) for the Open Chiplet Atlas (OCA)
  architecture — RTL, register descriptions, generated collateral, and
  documentation.
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-blue.svg"></a>
  <a href="https://tenstorrent.github.io/tt-oca-harness/"><img alt="Documentation" src="https://img.shields.io/badge/docs-online-brightgreen.svg"></a>
  <a href="https://github.com/tenstorrent/tt-oca-harness/releases"><img alt="Release" src="https://img.shields.io/github/v/release/tenstorrent/tt-oca-harness?display_name=tag"></a>
</p>
<!-- markdownlint-enable MD033 -->

## Ecosystem repositories

This repository is the entry point to the OCA Harness ecosystem — a family of
Tenstorrent-owned repositories, each covering a distinct part of building and
using OCAH:

| Package | Repository | Role in the ecosystem |
| --- | --- | --- |
| tt-oca-harness | [tenstorrent/tt-oca-harness](https://github.com/tenstorrent/tt-oca-harness) | This repository: OCAH's RTL, documentation, and register/IP-XACT tooling |
| tt-oca-harness-aou | [tenstorrent/tt-oca-harness-aou](https://github.com/tenstorrent/tt-oca-harness-aou) | AXI-over-UCIe Bridge (AoU) RTL, a component of OCAH's RTL collateral |
| tt-oca-harness-model | [tenstorrent/tt-oca-harness-model](https://github.com/tenstorrent/tt-oca-harness-model) | Virtual platform of the harness for rapid prototyping |
| tt-oca-manifest | [tenstorrent/tt-oca-manifest](https://github.com/tenstorrent/tt-oca-manifest) | OCA boot manifest format and producer/consumer tooling for the secure boot images OCAH's SEP subsystem loads |

## Documentation

Full documentation is published at
**[tenstorrent.github.io/tt-oca-harness](https://tenstorrent.github.io/tt-oca-harness/)**:

- **[Getting Started Guide](https://tenstorrent.github.io/tt-oca-harness/ocah-starting/latest/index.html)** — setup, workflows, and contribution.
- **[Technical Reference Manual](https://tenstorrent.github.io/tt-oca-harness/ocah-docs/latest/index.html)** — architecture and register reference.
- **[Integrator Guide](https://tenstorrent.github.io/tt-oca-harness/ocah-integrator-guide/latest/index.html)** — integrating OCAH into a chiplet design.
- Per-subsystem datasheets (PDF): [SMC](https://tenstorrent.github.io/tt-oca-harness/downloads/ocah-smc-datasheet.pdf), [SEP](https://tenstorrent.github.io/tt-oca-harness/downloads/ocah-sep-datasheet.pdf), [SMU](https://tenstorrent.github.io/tt-oca-harness/downloads/ocah-smu-datasheet.pdf), [DTP](https://tenstorrent.github.io/tt-oca-harness/downloads/ocah-dtp-datasheet.pdf), and [AoU](https://tenstorrent.github.io/tt-oca-harness/downloads/ocah-aou-datasheet.pdf).
- Integrator-facing register and timing collateral is indexed under [`integration/`](integration/).

## What's inside this repository

| Path | Contents |
| --- | --- |
| [`hw/sys/`](hw/sys/) | Subsystems: `smc`, `sep`, `smu`, `dtp` |
| [`hw/ip/`](hw/ip/) | Reusable IP blocks (`jtag/`, `uart/`, `cross_trigger/`, ...) |
| [`hw/common/`](hw/common/) | Shared primitives, TL-UL / AXI infrastructure, and the register flow |
| [`doc/`](doc/) | Technical Reference Manual, Integrator, Getting Started, datasheets |
| [`tools/`](tools/), [`scripts/`](scripts/) | Register, documentation, DV and container tooling |
| [`flows/`](flows/) | Lint, format and synthesis flow makefiles |
| [`vendor/`](vendor/) | Vendored third-party packages, with local patches and overlays |

## Contributing

Contributions are welcome under the Apache License 2.0. Read
[`CONTRIBUTING.md`](CONTRIBUTING.md) for setup, the pull-request process, SPDX
header form, and local lint/format commands. This project follows the
[`CODE_OF_CONDUCT.adoc`](CODE_OF_CONDUCT.adoc).

## Releases

Release notes are recorded in [`CHANGELOG.md`](CHANGELOG.md).

## License

- [`LICENSE`](LICENSE) (Apache License 2.0): overall license for this project,
  except where specified.
- [`LICENSE-DOCS`](LICENSE-DOCS) (CC-BY-4.0): license for all documentation and
  images only.
- [`LICENSE_understanding.txt`](LICENSE_understanding.txt): Tenstorrent's
  clarification of how the Apache License 2.0 applies to this repository.
- Third-party notices: [`NOTICE`](NOTICE).

By contributing you agree that your contributions are licensed as described
in [`CONTRIBUTING.md`](CONTRIBUTING.md).
