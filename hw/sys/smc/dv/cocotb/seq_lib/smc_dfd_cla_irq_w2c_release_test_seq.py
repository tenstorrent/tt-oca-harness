# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The CLA debug interrupt is released by the EapStatus W2C write.

`dfd_cla.rdl` says software writes the matching `CDbgEapStatus` W2C bit to
reset a status bit, and names the ISR as the writer; `dfd.adoc` describes the
line as an ordinary maskable PLIC source (321). Held to that, once the pair
that fired the debug-interrupt action is quiet, a single W2C write of its
status bit clears the status and drops `cla_interrupt`.

`cla_node_eap.sv` feeds the debug-interrupt flop back through the action-bus
idle value without consulting the status, and `core_logic_analyzer.sv` gives
the set priority over the W2C-edge clear, so the W2C clears the status while
the line stays asserted; it releases only after `EnableEap` is cleared and a
second W2C is written.

The sequence samples the status bit and the line after each step, walks the
release steps that recover the bench, then grades the sample taken after the
single W2C.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_dfd_cla_action_seq_utils import SAMPLE_CYCLES, SmcDfdClaActionSeq

CHK = "CHK-CLA-IRQ-W2C-RELEASE"


class smc_dfd_cla_irq_w2c_release_test_seq(SmcDfdClaActionSeq):
    """Fire the debug-interrupt action, quiet the pair, write the W2C once, grade the line."""

    def __init__(self, name: str = "smc_dfd_cla_irq_w2c_release_test_seq") -> None:
        super().__init__(name)

    async def _sample(self, phase: str) -> tuple[int, int]:
        await ClockCycles(cocotb.top.clk_smc_i, SAMPLE_CYCLES)
        status = await self._status_bit(f"irq_{phase}")
        irq = self._pin("tb_cla_interrupt")
        line = f"OBS-CLA-IRQ phase={phase} status={status} irq={irq}"
        cocotb.log.info(line)
        self.samples.append(line)
        return status, irq

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        await self._write(self._eap(), {}, "reset")
        await self._write_ctrl(1, 1, 1, "arm")
        action, activating, quiet = await self._discover("tb_cla_interrupt", "irq")
        fired = await self._sample("fired")
        assert fired == (1, 1), (
            f"debug-interrupt action {action} with LogicalOp {activating}: status={fired[0]} "
            f"irq={fired[1]} after the fire, want both 1"
        )
        await self._quiet(action, quiet, "quiet")
        await self._sample("quiet")
        await self._w2c("once")
        status, irq = await self._sample("after_w2c")
        assert status == 0, (
            f"CDbgEapStatus.Node0Eap0 still 1 after the W2C with the pair quiet (op {quiet})"
        )
        await self._write_ctrl(1, 0, 1, "eap_off")
        await self._sample("after_eap_disable")
        await self._w2c("again")
        _, irq_final = await self._sample("after_eap_disable_w2c")
        assert irq_final == 0, (
            f"cla_interrupt still 1 after EnableEap=0 and a second W2C: {self.samples[-1]}"
        )
        if irq != 0:
            raise AssertionError(
                f"{CHK} FAIL: cla_interrupt still 1 after the single W2C write cleared "
                f"CDbgEapStatus.Node0Eap0 with the pair quiet; released only after EnableEap=0 "
                f"and a second W2C ({'; '.join(self.samples)})"
            )
        cocotb.log.info(
            "%s PASS: the single W2C write cleared CDbgEapStatus.Node0Eap0 and dropped "
            "cla_interrupt (%s)",
            CHK,
            "; ".join(self.samples),
        )
