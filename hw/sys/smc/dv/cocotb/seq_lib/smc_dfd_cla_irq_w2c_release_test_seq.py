# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The CLA debug interrupt holds through the W2C and releases once EnableEap is cleared.

`dfd_cla.rdl` `CDbgEapStatus` states that a W2C write does not release a debug
interrupt while `EnableEap` is set: the EAP holds the interrupt and the write
clears only the status bit; to release it, software clears `EnableEap`, then
writes the W2C bit. `EnableEap` states that clearing it is required before that
release write and that setting it again re-arms the EAPs. `dfd.adoc` and
`interrupts.adoc` give the same level, held until `EnableEap` is cleared and
the W2C bit is then written (#3389, ruled intended). `CDbgEapStatus` also
states that a status bit sets in every cycle in which its EAP relation holds
while its node is current and `EnableEap` is set, that the set takes priority
over a W2C write in the same cycle, which then leaves the bit at 1, and that
software writes the W2C bit once the relation is false, the node is no longer
current or `EnableEap` is clear.

Node 0 pair 0 fires the debug-interrupt action, takes a W2C write with the
relation still selected, and is quieted. The sequence then walks the
documented service sequence and samples the status bit and `tb_cla_interrupt`
after each step:

* `CHK-CLA-EAP-SET-OVER-W2C`: a W2C write with the activating relation still
  selected and `EnableEap` set leaves the status reading 1 and the line 1.
  `LogicalOp` and `EnableEap` are read back after the write and logged as
  `CTRL-CLA-W2C-RELATION-ON`, so the write is shown to land with the relation
  selected. The same W2C write with the pair quiet reads the status 0 under
  `CHK-CLA-IRQ-W2C-HOLD`, so the relation is the only difference between the
  two. The status is sampled through register reads, so which of the set and
  the clear wins inside one clock cycle is not separated from a status that is
  cleared and set again in the next cycle.
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

from .smc_cla_regmap import cla_field
from .smc_dfd_cla_action_seq_utils import (
    ACTION_DEBUG_INTERRUPT,
    SAMPLE_CYCLES,
    SmcDfdClaActionSeq,
)

CHK_SET_OVER = "CHK-CLA-EAP-SET-OVER-W2C"
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
        await self._w2c("relation_on")
        op_field = cla_field(self._eap(), "LogicalOp")
        eap_field = cla_field(self._ctrl(), "EnableEap")
        op_now = (
            await self._read(self._eap(), "relation_on_rb") & op_field.mask
        ) >> op_field.offset
        eap_now = 1 if await self._read(self._ctrl(), "relation_on_rb") & eap_field.mask else 0
        assert (op_now, eap_now) == (activating, 1), (
            f"after the W2C write LogicalOp reads {op_now} and EnableEap {eap_now}; the "
            f"relation-on leg needs the activating op {activating} and EnableEap 1"
        )
        cocotb.log.info(
            "CTRL-CLA-W2C-RELATION-ON: the W2C write of CDbgEapStatus.Node0Eap0W2C was issued "
            "with LogicalOp=%d (activating) and EnableEap=%d read back after it",
            op_now,
            eap_now,
        )
        kept = await self._sample("after_w2c_relation_on")
        if kept != (1, 1):
            raise AssertionError(
                f"{CHK_SET_OVER} FAIL: with EnableEap=1 and the activating relation still "
                f"selected (op {activating}) status={kept[0]} irq={kept[1]} after one W2C; "
                f"want the status left at 1 and the line at 1 ({'; '.join(self.samples)})"
            )
        cocotb.log.info(
            "%s: a W2C write with EnableEap=1 and the activating relation still selected "
            "left CDbgEapStatus.Node0Eap0 at 1 and tb_cla_interrupt at 1 (action %d, "
            "activating op %d)",
            CHK_SET_OVER,
            action,
            activating,
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
