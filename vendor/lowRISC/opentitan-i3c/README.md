<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
-->

# OpenTitan I3C (temporary import)

RTL copied from lowRISC/opentitan `hw/ip/i3c/rtl` at
9494dc05ded5535c16219fc688d02fcbfde567ab, for a PD evaluation of replacing the
CHIPS Alliance I3C core in the SMC. Not a Bender vendor package.

Edits applied:

- Assertion macros renamed to `OCAH_OT_*`.
- TL-UL parameter names and the `tlul_pkg::GET` opcode in ALL_CAPS, matching `hw/common/tlul`.
- `i3c_prim_subreg`: a renamed copy of upstream `prim_subreg` (the harness's copy has no
  `reinit_i`), used only by `i3c_reg_top.sv`.
- `ceil_udiv` in `i3c_consts_pkg`, in place of `prim_util_pkg::ceil_udiv`.
- RAM configuration types renamed to the harness's `prim_ram_1p_pkg`.
- Buffer, DAT and DCT memories exported as ports.
