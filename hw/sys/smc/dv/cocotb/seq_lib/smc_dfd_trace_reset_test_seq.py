# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Take a cool reset while the DST is tracing and check the DFD returns to its reset state.

Every address, field position, width, reset value and software-access type
comes from the generated register map through :mod:`seq_lib.smc_rdl_regmap`
and :mod:`seq_lib.smc_cla_regmap`, and the expected values after the reset
are the RDL reset values. The vendored RTL is not a source for any value this
sequence programs or compares against.

``hw/sys/smc/doc/clk_rst.adoc`` lists the cool reset as a Primary Reset
source. Every other trace leaf leaves the DFD running when it ends and relies
on the next simulation for a clean start; none resets it with the trace live.
This sequence:

* programs the funnel, the sink, the DST and the CLA away from their reset
  values, finds by measurement an ``Action0`` value that starts the
  uncompressed trace, and requires the sink write pointer to be moving;
* drives ``rst_cool_ni`` low and holds it until the primary reset is observed
  asserted, then releases it and waits for the primary reset and the fuse
  sense to complete, each wait bounded;
* reads every programmed register back and requires its plain read-write
  fields to hold their RDL reset values, the sink write pointer to read its
  reset value and to stay there, and the trace to start again from the
  measured action once the path is programmed afresh.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from env.smc_reset_item import SmcResetItem, SmcResetOp

from .smc_cla_regmap import cla_field, cla_register
from .smc_dfd_trace_accumulator_fill_test_seq import (
    cla_mux_normal,
    dfd_register,
    dst_register,
    funnel_register,
    reg_field,
    sink_register,
)
from .smc_dfd_trace_flush_corner_test_seq import smc_dfd_trace_flush_corner_test_seq
from .smc_reset_seq_base import SmcResetSeqBase

# clk_ref_i edges. The assert bound exceeds the cool reset's 32-sample
# de-glitch window; the release bound covers the release and warm re-release.
_COOL_ASSERT_BOUND_REF = 400
_COOL_RELEASE_BOUND_REF = 4000
_SETTLE_CYCLES = 16


class smc_dfd_trace_reset_test_seq(SmcResetSeqBase, smc_dfd_trace_flush_corner_test_seq):
    """Cool-reset the SMC with the DST tracing and check the DFD registers and trace."""

    ASSERT_BOUND_REF_CYCLES = _COOL_ASSERT_BOUND_REF
    RELEASE_BOUND_REF_CYCLES = _COOL_RELEASE_BOUND_REF

    def __init__(self, name: str = "smc_dfd_trace_reset_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.checked_registers: list[str] = []

    async def _dispatch_reset_item(self, item: SmcResetItem) -> None:
        await self.dispatch_reset(item)

    async def _await_level(self, signal: str, want: int, bound: int, label: str) -> None:
        sig = getattr(cocotb.top, signal)
        last: int | None = None
        for _ in range(bound):
            value = sig.value
            last = int(value) if value.is_resolvable else None
            if last == want:
                return
            await RisingEdge(cocotb.top.clk_ref_i)
        raise AssertionError(
            f"{label}: {signal} never reached {want} within {bound} clk_ref_i edges "
            f"(last={'X/Z' if last is None else last})"
        )

    @staticmethod
    def _programmed() -> tuple:
        """Each register this sequence moves off reset, with the fields it moves."""
        return (
            (dst_register("Trdstcontrol"), ("Trdstactive", "Trdstenable", "Trdstformat")),
            (dst_register("Trdstimpl"), ("Trdstvendorstreamlength",)),
            (sink_register("Trdstramcontrol"), ("Trdstramactive", "Trdstramenable")),
            (funnel_register("Trfunnelcontrol"), ("Trfunnelactive", "Trfunnelenable")),
            (cla_register("CDbgClaCtrlStatus"), ("EnableCla", "EnableEap")),
            (cla_register("CDbgNode0Eap0"), ("Action0",)),
            (cla_register("CDbgMuxSelLo"), ("Dbmmode",)),
            (dfd_register("dfx_ctrl/DEBUG_BUS_MUX"), ("Dbmmode",)),
            (dfd_register("dfx_ctrl/DEBUG_CTRL"), ("force_clk_en",)),
        )

    @staticmethod
    def _off_reset(reg, names, word: int) -> list[str]:
        """The named fields of ``word`` that differ from their RDL reset values."""
        moved = []
        for name in names:
            field = reg_field(reg, name)
            if (word & field.mask) >> field.offset != field.reset:
                moved.append(name)
        return moved

    async def _find_start(self) -> None:
        span = 1 << cla_field(cla_register("CDbgNode0Eap0"), "Action0").width
        for value in range(span):
            await self._dst(0, f"start{value}_off")
            await self._action(value, f"start{value}")
            await self._dst(1, f"start{value}_on")
            await self._settle()
            if await self._moving(f"start{value}"):
                self.start_action = value
                self.value_checks += 1
                return
        raise AssertionError(
            f"no value of the {span}-value Action0 field started the uncompressed trace: the "
            f"write pointer never moved"
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        await self._bring_up()
        await self._arm_cla()
        await cla_mux_normal(self, "clamux")
        await self._find_start()
        await self._write_check(
            dst_register("Trdstimpl"),
            {"Trdstvendorframelength": 1, "Trdstvendorstreamlength": 0},
            "impl",
        )
        still = []
        for reg, names in self._programmed():
            word = await self._read(reg, "before")
            moved = self._off_reset(reg, names, word)
            if moved != list(names):
                still.append(f"{self._short(reg)}.{sorted(set(names) - set(moved))}")
        assert not still, (
            f"fields {still} read their RDL reset values before the reset, so they would pass "
            f"the reset check without being reset"
        )
        assert await self._moving("before"), (
            f"the write pointer is not moving with start action {self.start_action} held, so "
            f"the reset would not land on a live trace"
        )
        cocotb.log.info(
            "CHK-DFD-RESET-LIVE: every programmed field of the %d DFD registers read away from "
            "its RDL reset value and the sink write pointer was moving under start action %d",
            len(self._programmed()),
            self.start_action,
        )

        await self._send(SmcResetOp.COOL_RST_LO, item_name="cool_rst_lo")
        await self._await_level("rst_primary_smc_clk_no", 0, _COOL_ASSERT_BOUND_REF, "ASSERT")
        await self._send(SmcResetOp.COOL_RST_HI, item_name="cool_rst_hi")
        await self._await_level("rst_primary_smc_clk_no", 1, _COOL_RELEASE_BOUND_REF, "RELEASE")
        await self._await_level("tb_rst_warm_smc_clk_n", 1, _COOL_RELEASE_BOUND_REF, "RELEASE_WARM")
        await self.wait_fuse_sense_done()
        cocotb.log.info(
            "CHK-DFD-RESET-TAKEN: rst_cool_ni low brought rst_primary_smc_clk_no to 0 within "
            "%d clk_ref_i edges, and after release it and the warm reset returned to 1 within "
            "%d",
            _COOL_ASSERT_BOUND_REF,
            _COOL_RELEASE_BOUND_REF,
        )

        for reg, names in self._programmed():
            word = await self._read(reg, "after")
            moved = self._off_reset(reg, names, word)
            assert not moved, (
                f"{reg.path} @ 0x{reg.addr:08x} reads 0x{word:x} after the cool reset: fields "
                f"{moved} are not at their RDL reset values"
            )
            self.checked_registers.append(self._short(reg))
            self.value_checks += 1
        wp = sink_register("Trdstramwplow")
        pointer = reg_field(wp, "Trdstramwplow")
        reset_pointer = (wp.reset_word & pointer.mask) >> pointer.offset
        first = await self._read(wp, "after_wp0")
        await self._settle(2 * _SETTLE_CYCLES)
        second = await self._read(wp, "after_wp1")
        assert (first & pointer.mask) >> pointer.offset == reset_pointer and second == first, (
            f"the sink write pointer reads 0x{first:x} then 0x{second:x} after the cool reset; "
            f"its RDL reset is 0x{reset_pointer << pointer.offset:x} and nothing is armed"
        )
        self.value_checks += 1
        cocotb.log.info(
            "CHK-DFD-RESET-CLEARED: after the cool reset every programmed field of %s read its "
            "RDL reset value, and the sink write pointer read its reset value and stayed there",
            ", ".join(self.checked_registers),
        )

        await self._bring_up()
        await self._arm_cla()
        await cla_mux_normal(self, "clamux_after")
        await self._action(self.start_action, "after_start")
        await self._settle()
        assert await self._moving("after"), (
            f"start action {self.start_action} does not move the write pointer once the trace "
            f"path is programmed again after the cool reset"
        )
        self.value_checks += 1
        cocotb.log.info(
            "CHK-DFD-RESET-RESTART: programmed again after the cool reset, the trace path "
            "started from action %d and the write pointer moved",
            self.start_action,
        )
        for reg, _ in self._programmed():
            await self._write(reg, reg.reset_word, "restore")
