<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# OpenTitan chip config

Vendored OpenTitan IP and the TT TL-UL stack import `top_pkg` and
`top_racl_pkg`. Upstream, those packages come from a generated chip top. OCAH
has no such top, so the two files here supply the names and types those
sources compile against.

`bender vendor init` does not refresh this directory.
The SystemVerilog package names stay `top_pkg`
and `top_racl_pkg` because vendor RTL writes those identifiers.

| File | What it supplies |
|------|------------------|
| `top_pkg.sv` | TL-UL widths (address, data, user, source, sink) |
| `top_racl_pkg.sv` | Register-access-control types on OT IP ports |
