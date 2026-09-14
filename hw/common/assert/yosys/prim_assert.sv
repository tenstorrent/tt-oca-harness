// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Local shim for the vendored OpenTitan prim_assert.sv.
//
// This file shadows vendor/lowRISC/opentitan/upstream/hw/ip/prim/rtl/prim_assert.sv
// because this directory precedes that one in the flist +incdir search order.
// Do NOT edit the vendored tree; keep this override in the harness instead.
//
// It lives in its own include dir, which only the yosys flow puts on its flist
// (flows/synth/yosys/yosys.mk prepends it). Do not move it back beside the other
// hw/common/assert headers: those are on every flist, and the customer IP
// packager flattens all include dirs into one directory, where this file and
// the vendored file it delegates to collide on the basename `prim_assert.sv`.
//
// Why the shim exists:
//   yosys-slang auto-defines `YOSYS`. The vendored prim_assert.sv treats `YOSYS`
//   as "formal verification" and unconditionally enables assertions (it defines
//   OCAH_OT_INC_ASSERT and pulls in prim_assert_yosys_macros.svh). Two problems
//   for the yosys+yosys-slang *synthesis* flow (SYNTHESIS defined):
//     1. The yosys formal `OCAH_OT_ASSERT` wraps `assert (__prop)` in an
//        `always_ff`, which cannot carry the concurrent/temporal properties
//        (e.g. `|=>`) that prim_count.sv passes in.
//     2. Even ignoring the macro bodies, OCAH_OT_INC_ASSERT being set makes
//        blocks like prim_count.sv's assertion section elaborate helper signals
//        (e.g. `fpv_force`) that only exist under formal.
//   During synthesis we want assertions dropped entirely, exactly as the
//   non-YOSYS synthesis path already does.
//
//   Fix: when both YOSYS and SYNTHESIS are defined, temporarily `undef YOSYS` so
//   the vendored header takes its standard branch. With SYNTHESIS defined there,
//   OCAH_OT_INC_ASSERT stays unset and the standard macros expand to nothing.
//   YOSYS is restored afterwards for any downstream code that keys off it. The
//   Yosys *formal* flow (YOSYS without SYNTHESIS) is left untouched.
//
// The vendored file is included by a path relative to this file's directory so
// it resolves to the real upstream copy rather than recursing back into this
// shim (which owns the `prim_assert.sv` include name).

`ifdef YOSYS
`ifdef SYNTHESIS
`undef YOSYS
`include "../../../../vendor/lowRISC/opentitan/upstream/hw/ip/prim/rtl/prim_assert.sv"
`define YOSYS
`else
`include "../../../../vendor/lowRISC/opentitan/upstream/hw/ip/prim/rtl/prim_assert.sv"
`endif
`else
`include "../../../../vendor/lowRISC/opentitan/upstream/hw/ip/prim/rtl/prim_assert.sv"
`endif
