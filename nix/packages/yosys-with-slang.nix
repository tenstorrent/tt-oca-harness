# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
{
  yosys,
  yosys-slang,
  ...
}:
# Include yosys-slang plugin for SystemVerilog support
yosys.withPlugins [yosys-slang]
