# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The CLA global clock-halt request deasserts once the action drops or the halt is disabled.

`smc_dfd_wrap.sv` describes `tdr_dbg_ctrl_clocks_stopped_by_cla_o` as high
while a CLA halt-clock action is requesting a clock stop, `dfd.adoc` as
asserted while the CLA has stopped clocks, and `dfd_cla.rdl` says the clock
halt action is not applied to global clocks while `DisableGlobalClockHalt` is
set. Held to that, `halt_clock_global_or_o` follows the action: it is 0 once
the pair that fired the clock-halt action is quiet, its status is cleared,
`EnableEap` is 0 and `DisableGlobalClockHalt` is 1.

`cla_action_gen.sv` registers the global clock halt as a set-only flop whose
enable gates the set alone, reset only by the CLA gated reset, which is the
SMC primary reset. The W2C, `EnableEap`, `EnableCla` and `DisableGlobalClockHalt`
do not reach it, so the request stays asserted until the primary reset.

The bench ties `tdr_dbg_ctrl_clock_stop_en_i` low, so the request is observed
on the wrapper's `halt_clock_global_or_o` with `DEBUG_CTRL.xtrig_clk_halt_mask`
bit 0 set; the mask is cleared again at the end, so no later leaf on the same
model sees the term.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_dfd_cla_action_seq_utils import SAMPLE_CYCLES, SmcDfdClaActionSeq
from .smc_dfd_trace_accumulator_fill_test_seq import dfd_register

CHK = "CHK-CLA-CLOCK-HALT-RELEASE"
# dfx_ctrl_status.rdl DEBUG_CTRL.xtrig_clk_halt_mask: bit 0 passes the halt request.
_HALT_MASK_LOWEST = 0x1


class smc_dfd_cla_clock_halt_release_test_seq(SmcDfdClaActionSeq):
    """Fire the clock-halt action, walk the release steps, grade the request after each."""

    def __init__(self, name: str = "smc_dfd_cla_clock_halt_release_test_seq") -> None:
        super().__init__(name)

    async def _sample(self, phase: str) -> tuple[int, int]:
        await ClockCycles(cocotb.top.clk_smc_i, SAMPLE_CYCLES)
        status = await self._status_bit(f"stop_{phase}")
        stopped = self._pin("tb_cla_halt_clock_global")
        line = (
            f"OBS-CLA-CLOCK-HALT phase={phase} status={status} stopped={stopped} "
            f"clock_stop_o={self._pin('tb_cla_clock_stop')}"
        )
        cocotb.log.info(line)
        self.samples.append(line)
        return status, stopped

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        debug_ctrl = dfd_register("dfx_ctrl/DEBUG_CTRL")
        await self._write(
            debug_ctrl, {"force_clk_en": 1, "xtrig_clk_halt_mask": _HALT_MASK_LOWEST}, "halt_mask"
        )
        await self._write(self._eap(), {}, "reset")
        await self._write_ctrl(1, 1, 0, "arm")
        armed = await self._sample("armed")
        assert armed == (0, 0), f"status={armed[0]} stopped={armed[1]} before the fire, want 0 0"
        action, activating, quiet = await self._discover("tb_cla_halt_clock_global", "stop")
        fired = await self._sample("fired")
        assert fired == (1, 1), (
            f"clock-halt action {action} with LogicalOp {activating}: status={fired[0]} "
            f"stopped={fired[1]} after the fire, want both 1"
        )
        await self._quiet(action, quiet, "quiet")
        await self._sample("action_dropped")
        await self._w2c("once")
        status, _ = await self._sample("after_w2c")
        assert status == 0, (
            f"CDbgEapStatus.Node0Eap0 still 1 after the W2C with the pair quiet (op {quiet})"
        )
        await self._write_ctrl(1, 0, 0, "eap_off")
        await self._sample("after_eap_disable")
        await self._write_ctrl(1, 0, 1, "global_halt_disabled")
        _, stopped = await self._sample("after_global_halt_disable")
        await self._write(debug_ctrl, {"force_clk_en": 1}, "halt_unmask")
        _, masked = await self._sample("mask_cleared")
        assert masked == 0, "halt_clock_global_or_o still 1 with xtrig_clk_halt_mask cleared"
        if stopped != 0:
            raise AssertionError(
                f"{CHK} FAIL: halt_clock_global_or_o still 1 after the clock-halt action "
                f"dropped, CDbgEapStatus.Node0Eap0 was cleared by W2C, EnableEap was cleared and "
                f"DisableGlobalClockHalt was set ({'; '.join(self.samples)})"
            )
        cocotb.log.info(
            "%s PASS: halt_clock_global_or_o dropped once the clock-halt action dropped and "
            "DisableGlobalClockHalt was set (%s)",
            CHK,
            "; ".join(self.samples),
        )
