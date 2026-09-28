<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# PDK management

`pdks.mk` uses `ciel` to install version-pinned PDKs below `PDK_ROOT`, which
defaults to `local/pdks`. Synthesis installs the selected PDK on demand.

The available management targets are:

```bash
make synth-pdk TECH=ihp-sg13g2 [PDK_ROOT=<path>]
make synth-pdks [PDK_ROOT=<path>]
make synth-pdks-clean [PDK_ROOT=<path>]
```

The installer has pinned entries for `ihp-sg13g2`, `sky130`, and
`gf180mcuD`. Only `ihp-sg13g2` has a matching `tech/<pdk>/tech.tcl`
configuration and can currently be used for synthesis.

To add another synthesis PDK:

1. Add its name, `ciel` version hash, and aggregate-install prerequisite to
   `pdks.mk`.
2. Add `tech/<pdk>/tech.tcl` with its liberty files, tie cells, ABC constraint,
   and any cells excluded from mapping.
