<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
-->

# Integration collateral

Each subsystem or IP under `hw/{sys,ip}` keeps the canonical integration
collateral beside its implementation. The `rdl/`, `ipxact/`, and
`constraint/` directories centralize symlinks to those distributed files so
integrators can find them in one place.
RDL and IP-XACT files are grouped into flat, self-contained subsystem folders.

The symlink targets remain the canonical files. See the
[Integrator Guide](../doc/integrator/) for detailed integration guidance.

Regenerate the indexes after adding or moving collateral:

```bash
python3 scripts/collect_integration.py
```
