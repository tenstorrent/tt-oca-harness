# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Clearing the hang detector's enable while it has fired, and irq_test with it clear.

`HANG_DET_CTRL.enable` reads: "When 0, the counter reloads from the threshold
and irq_o is forced low", and `irq_test` is "Gated by enable and irq_en". The hang detector leaves
so far clear `enable` only while the detector is quiet, and drive `irq_test`
only with `enable` set, so two cases the RDL settles have never run:

* **Disabled while fired.** The SEP detector times out on a read held at
  its R channel. With the read still held, `enable` is cleared and `irq_en`
  kept, and the SEP interrupt has to drop while the bus is still hung.
* **irq_test with enable clear.** `irq_en` and `irq_test` set with `enable`
  clear must leave the interrupt low, and setting `enable` as well must raise
  it, which shows the same write can.

The held read occupies the system AXI agent, so the control writes made during
the stall go through the JTAG AXI master.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._hang_status import check_hang_status
from ._one_shot import _OneShot
from .smc_addr_map import (
    HANG_DET_ARMED,
    HANG_DET_DATA_ACCEL_CTRL,
    HANG_DET_ENABLE,
    HANG_DET_IRQ_EN,
    HANG_DET_IRQ_TEST,
    HANG_DET_SEP_AXI_CTRL,
    HANG_DET_SEP_AXI_TIMEOUT,
    HANG_DET_SYS_AXI_CTRL,
)
from .smc_hang_detector_timeout_test_seq import smc_hang_detector_timeout_test_seq

_THR = 0x10
_IRQ_BOUND = _THR + 64
#: Cycles the interrupt is watched for staying low; well beyond the threshold,
#: so a detector still counting would have fired inside it.
_QUIET_CYCLES = 4 * _THR


class smc_hang_detector_disable_test_seq(smc_hang_detector_timeout_test_seq):
    """Disable a fired SEP detector mid-stall, and drive irq_test with enable clear."""

    def __init__(self, name: str = "smc_hang_detector_disable_test_seq") -> None:
        super().__init__(name)
        self.disabled_drop = False
        self.test_gated = False

    async def _jtag_write(self, label: str, addr: int, data: int) -> None:
        item = SmcSysAxiItem(label)
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = data
        await _OneShot(item, f"{label}_os").start(self.env.jtag_axi_agent.sequencer)
        assert item.resp_code == 0, f"{label}: JTAG write to 0x{addr:08x} answered {item.resp_code}"

    async def _jtag_read(self, label: str, addr: int) -> int:
        item = SmcSysAxiItem(label)
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        await _OneShot(item, f"{label}_os").start(self.env.jtag_axi_agent.sequencer)
        assert item.resp_code == 0, f"{label}: JTAG read of 0x{addr:08x} answered {item.resp_code}"
        return item.rdata & 0xFFFF_FFFF

    async def _hold_low(self, dut, label: str) -> None:
        for cycle in range(_QUIET_CYCLES):
            await RisingEdge(dut.clk_smc_i)
            level = self._bit(dut.tb_axi_hang_irq_sep, "tb_axi_hang_irq_sep")
            assert level == 0, f"{label}: SEP hang interrupt high at cycle {cycle}"

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        dut.tb_sep_axi_r_hold.value = 0
        await self.csr_write("HANG_SYS_OFF", HANG_DET_SYS_AXI_CTRL, 0)
        await self.csr_write("HANG_DATA_OFF", HANG_DET_DATA_ACCEL_CTRL, 0)
        await self.csr_write("HANG_SEP_THR", HANG_DET_SEP_AXI_TIMEOUT, _THR)
        await self.csr_read("HANG_SEP_THR_RB", HANG_DET_SEP_AXI_TIMEOUT, expected=_THR)
        await self.csr_write("HANG_SEP_ARM", HANG_DET_SEP_AXI_CTRL, HANG_DET_ARMED)
        await self.csr_read("HANG_SEP_ARM_RB", HANG_DET_SEP_AXI_CTRL, expected=HANG_DET_ARMED)

        async def _disable_while_fired() -> None:
            await self._await_irq(dut, "tb_axi_hang_irq_sep", 1, _IRQ_BOUND, "DISABLE_FIRE")
            await self._jtag_write("HANG_SEP_DISABLE", HANG_DET_SEP_AXI_CTRL, HANG_DET_IRQ_EN)
            ctrl = await self._jtag_read("HANG_SEP_DISABLE_RB", HANG_DET_SEP_AXI_CTRL)
            assert ctrl == HANG_DET_IRQ_EN, (
                f"HANG_DET_CTRL reads 0x{ctrl:x} after writing irq_en alone"
            )
            level = self._bit(dut.tb_axi_hang_irq_sep, "tb_axi_hang_irq_sep")
            assert level == 0, (
                "the SEP hang interrupt stayed high with enable cleared and the read still "
                "held; the RDL forces irq_o low when enable is 0"
            )
            await check_hang_status(self._jtag_read, "DISABLED_MID_STALL", set())
            await self._hold_low(dut, "DISABLED_MID_STALL")
            self.disabled_drop = True

        await self._hold_read_until(dut, "DISABLE_STALL_RD", _disable_while_fired)
        cocotb.log.info(
            "CHK-HANG-DISABLE-FIRED: the SEP detector fired on a held read, and clearing "
            "enable with irq_en kept dropped its interrupt and held it low for %d cycles "
            "while the read stayed held",
            _QUIET_CYCLES,
        )
        cocotb.log.info(
            "CHK-HANG-DISABLE-STATUS: HANG_DET_SEP_AXI_CTRL.irq read 0 with enable cleared "
            "and the read still held"
        )

        await self.csr_write(
            "HANG_SEP_TEST_NO_EN", HANG_DET_SEP_AXI_CTRL, HANG_DET_IRQ_EN | HANG_DET_IRQ_TEST
        )
        await self.csr_read(
            "HANG_SEP_TEST_NO_EN_RB",
            HANG_DET_SEP_AXI_CTRL,
            expected=HANG_DET_IRQ_EN | HANG_DET_IRQ_TEST,
        )
        await self._hold_low(dut, "IRQ_TEST_NO_ENABLE")
        full = HANG_DET_ENABLE | HANG_DET_IRQ_EN | HANG_DET_IRQ_TEST
        await self.csr_write("HANG_SEP_TEST_EN", HANG_DET_SEP_AXI_CTRL, full)
        await self._await_irq(dut, "tb_axi_hang_irq_sep", 1, _IRQ_BOUND, "IRQ_TEST_ENABLED")
        await self.csr_write("HANG_SEP_OFF", HANG_DET_SEP_AXI_CTRL, 0)
        await self._await_irq(dut, "tb_axi_hang_irq_sep", 0, _IRQ_BOUND, "IRQ_TEST_OFF")
        self.test_gated = True
        cocotb.log.info(
            "CHK-HANG-TEST-GATED: irq_test with irq_en and enable clear left the SEP hang "
            "interrupt low for %d cycles; setting enable as well raised it, and clearing the "
            "control dropped it",
            _QUIET_CYCLES,
        )
