# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The CLA global clock-halt request is held until primary reset; the mask gates it.

`dfd.adoc` says a halt-clock action sets a request that is held until the SMC
primary reset: `CDbgEapStatus`, `EnableEap` and `DisableGlobalClockHalt` do
not release it, and the mask gates the output without clearing it. `dfd_cla.rdl` says setting `DisableGlobalClockHalt` does
not release a request already set. Held to that, `halt_clock_global_or_o` stays
1 once the pair that fired the clock-halt action is quiet, its status is
cleared by the W2C, `EnableEap` is 0 and `DisableGlobalClockHalt` is 1; it
reads 0 while `DEBUG_CTRL.xtrig_clk_halt_mask` bit 0 is cleared and 1 again
once the bit is set back, since nothing cleared the request.

The bench holds `tdr_dbg_ctrl_clock_stop_en_i` low in this leaf, so the
request is observed on the wrapper's `halt_clock_global_or_o`; the mask is
cleared again at the end.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_dfd_cla_action_seq_utils import SAMPLE_CYCLES, SmcDfdClaActionSeq
from .smc_dfd_trace_accumulator_fill_test_seq import dfd_register

CHK = "CHK-CLA-CLOCK-HALT-HELD"
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
        clock_stop = self._pin("tb_cla_clock_stop")
        assert clock_stop == 0, f"tb_cla_clock_stop={clock_stop} at {phase} with the enable at 0"
        return status, stopped

    def _held(self, phase: str, stopped: int, step: str) -> None:
        if stopped != 1:
            raise AssertionError(
                f"{CHK} FAIL: halt_clock_global_or_o={stopped} at {phase} after {step}, want 1: "
                f"the request must be held until primary reset ({'; '.join(self.samples)})"
            )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        assert self._pin("tb_cla_clock_stop_en") == 0, "tb_cla_clock_stop_en not idle 0"
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
        _, stopped = await self._sample("action_dropped")
        self._held("action_dropped", stopped, f"the pair went quiet on LogicalOp {quiet}")
        await self._w2c("once")
        status, stopped = await self._sample("after_w2c")
        assert status == 0, (
            f"CDbgEapStatus.Node0Eap0 still 1 after the W2C with the pair quiet (op {quiet})"
        )
        self._held("after_w2c", stopped, "the CDbgEapStatus W2C cleared the status")
        await self._write_ctrl(1, 0, 0, "eap_off")
        _, stopped = await self._sample("after_eap_disable")
        self._held("after_eap_disable", stopped, "EnableEap was cleared")
        await self._write_ctrl(1, 0, 1, "global_halt_disabled")
        _, stopped = await self._sample("after_global_halt_disable")
        self._held("after_global_halt_disable", stopped, "DisableGlobalClockHalt was set")
        await self._write(debug_ctrl, {"force_clk_en": 1}, "halt_unmask")
        _, masked = await self._sample("mask_cleared")
        if masked != 0:
            raise AssertionError(
                f"{CHK} FAIL: halt_clock_global_or_o={masked} with xtrig_clk_halt_mask bit 0 "
                f"cleared, want 0 ({'; '.join(self.samples)})"
            )
        await self._write(
            debug_ctrl, {"force_clk_en": 1, "xtrig_clk_halt_mask": _HALT_MASK_LOWEST}, "remask"
        )
        _, stopped = await self._sample("mask_restored")
        self._held("mask_restored", stopped, "xtrig_clk_halt_mask bit 0 was set back")
        await self._write(debug_ctrl, {"force_clk_en": 1}, "halt_unmask_end")
        cocotb.log.info(
            "%s: halt_clock_global_or_o stayed 1 after the action dropped, the W2C, EnableEap "
            "cleared and DisableGlobalClockHalt set, read 0 with the mask cleared and 1 again "
            "with it restored (%s)",
            CHK,
            "; ".join(self.samples),
        )
