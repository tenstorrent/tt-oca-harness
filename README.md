# tt-oca-harness

## Overview

Open Chiplet Atlas Harness (OCAH) — the open hardware tree for the OCA design:
RTL, register descriptions, generated collateral, and documentation.

## Getting Started

For detailed documentation, please refer to the GitHub pages site generated as a
deployment of this repository: [tenstorrent.github.io/tt-oca-harness/](https://tenstorrent.github.io/tt-oca-harness/)

The Getting Started Guide, in particular, can be found [here](https://tenstorrent.github.io/tt-oca-harness/ocah-starting/latest/index.html).

Integrator-facing register and timing collateral is indexed under
[`integration/`](integration/).

## Ecosystem repositories

The OCA Harness ecosystem itself spans a small family of Tenstorrent-owned repositories, each covering a distinct part of building and using OCAH:

| Package | Upstream | Repository | Role in the ecosystem |
| --- | --- | --- | --- |
| tt-oca-harness | Tenstorrent | [tenstorrent/tt-oca-harness](https://github.com/tenstorrent/tt-oca-harness) | This repository: OCAH’s RTL, documentation, and register/IP-XACT tooling |
| tt-oca-harness-aou | Tenstorrent | [tenstorrent/tt-oca-harness-aou](https://github.com/tenstorrent/tt-oca-harness-aou) | AXI-over-UCIe Bridge (AoU) RTL, a component of OCAH’s RTL collateral |
| tt-oca-harness-model | Tenstorrent | [tenstorrent/tt-oca-harness-model](https://github.com/tenstorrent/tt-oca-harness-model) | Virtual platform of the harness for rapid prototyping |
| tt-oca-manifest | Tenstorrent | [tenstorrent/tt-oca-manifest](https://github.com/tenstorrent/tt-oca-manifest) | OCA boot manifest format specification and producer/consumer tooling for the secure boot images OCAH’s SEP subsystem loads |


## Contributing

Contributions are welcome under the Apache License 2.0. Read
[`CONTRIBUTING.md`](CONTRIBUTING.md) for setup, the pull-request process,
SPDX header form, and local lint/format commands. This project follows the
[`CODE_OF_CONDUCT.adoc`](CODE_OF_CONDUCT.adoc).

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
