# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The CLA debug interrupt holds through the W2C and releases once EnableEap is cleared.

`dfd_cla.rdl` `CDbgEapStatus` states that a W2C write does not release a debug
interrupt while `EnableEap` is set: the EAP holds the interrupt and the write
clears only the status bit; to release it, software clears `EnableEap`, then
writes the W2C bit. `EnableEap` states that clearing it is required before that
release write and that setting it again re-arms the EAPs. `dfd.adoc` and
`interrupts.adoc` give the same level, held until `EnableEap` is cleared and
the W2C bit is then written (#3389, ruled intended).

Node 0 pair 0 fires the debug-interrupt action and is quieted. The sequence
then walks the documented service sequence and samples the status bit and
`tb_cla_interrupt` after each step:

* `CHK-CLA-IRQ-W2C-HOLD`: after a W2C write with `EnableEap` set, the
  status reads 0 and the line still reads 1, and a second W2C write with
  `EnableEap` still set leaves the same.
* `CHK-CLA-IRQ-EAP-RELEASE`: clearing `EnableEap` alone leaves the status 0
  and the line 1; the W2C write that follows drops both to 0; setting
  `EnableEap` again with the pair still quiet leaves both at 0; driving the
  activating relation after that re-arm fires the pair again, status and
  line 1.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_dfd_cla_action_seq_utils import (
    ACTION_DEBUG_INTERRUPT,
    SAMPLE_CYCLES,
    SmcDfdClaActionSeq,
)

CHK_HOLD = "CHK-CLA-IRQ-W2C-HOLD"
CHK_RELEASE = "CHK-CLA-IRQ-EAP-RELEASE"


class smc_dfd_cla_irq_w2c_release_test_seq(SmcDfdClaActionSeq):
    """Fire the debug-interrupt action, then walk and grade the documented release sequence."""

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
        action, activating, quiet = await self._discover(
            "tb_cla_interrupt", "irq", ACTION_DEBUG_INTERRUPT
        )
        fired = await self._sample("fired")
        assert fired == (1, 1), (
            f"debug-interrupt action {action} with LogicalOp {activating}: status={fired[0]} "
            f"irq={fired[1]} after the fire, want both 1"
        )
        await self._quiet(action, quiet, "quiet")
        quieted = await self._sample("quiet")
        assert quieted == (1, 1), (
            f"pair quiet on LogicalOp {quiet} before any W2C: status={quieted[0]} "
            f"irq={quieted[1]}, want both 1"
        )

        await self._w2c("hold")
        held = await self._sample("after_w2c_eap_on")
        await self._w2c("hold_again")
        held_again = await self._sample("after_second_w2c_eap_on")
        if held != (0, 1) or held_again != (0, 1):
            raise AssertionError(
                f"{CHK_HOLD} FAIL: with EnableEap=1 and the pair quiet (op {quiet}) "
                f"status={held[0]} irq={held[1]} after one W2C and status={held_again[0]} "
                f"irq={held_again[1]} after a second; want status 0 and the line held at 1 "
                f"for both ({'; '.join(self.samples)})"
            )
        cocotb.log.info(
            "%s: two W2C writes with EnableEap=1 cleared CDbgEapStatus.Node0Eap0 and "
            "tb_cla_interrupt stayed 1 (action %d, quiet op %d)",
            CHK_HOLD,
            action,
            quiet,
        )

        await self._write_ctrl(1, 0, 1, "eap_off")
        eap_off = await self._sample("after_eap_off")
        await self._w2c("release")
        released = await self._sample("after_eap_off_w2c")
        await self._write_ctrl(1, 1, 1, "rearm")
        rearmed = await self._sample("after_rearm")
        await self._arm(action, activating, "refire")
        refired = await self._sample("after_rearm_fire")
        if (eap_off, released, rearmed, refired) != ((0, 1), (0, 0), (0, 0), (1, 1)):
            raise AssertionError(
                f"{CHK_RELEASE} FAIL: (status, irq) after EnableEap=0 {eap_off} want (0, 1), "
                f"after the W2C {released} want (0, 0), after EnableEap=1 with the pair quiet "
                f"{rearmed} want (0, 0), after the activating relation op {activating} "
                f"{refired} want (1, 1) ({'; '.join(self.samples)})"
            )
        cocotb.log.info(
            "%s: EnableEap=0 alone held tb_cla_interrupt, the W2C then dropped it with the "
            "status, EnableEap=1 with the pair quiet left both at 0, and the activating "
            "relation fired the pair again (%s)",
            CHK_RELEASE,
            "; ".join(self.samples),
        )
