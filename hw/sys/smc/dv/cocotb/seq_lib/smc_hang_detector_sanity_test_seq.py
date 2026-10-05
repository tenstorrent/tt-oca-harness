# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Hang-detector CTRL.irq_test on each lifted IRQ. Real bus-stall timeout is not claimed."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import (
    HANG_DET_DATA_ACCEL_CTRL,
    HANG_DET_ENABLE,
    HANG_DET_FIRE,
    HANG_DET_IRQ_EN,
    HANG_DET_IRQ_TEST,
    HANG_DET_SEP_AXI_CTRL,
    HANG_DET_SYS_AXI_CTRL,
)
from .smc_csr_seq_utils import SmcCsrSeq

# irq_o is combinational after the CTRL flop (axi_hang_detector.sv). AXI write
# completion already implies the CSR update beat; this bound is only the
# fail-closed ceiling until that flop is visible on the TB lift.
_IRQ_BOUND = 64

# Independent detectors: (label, CTRL addr, TB per-source pin).
_DETECTORS = (
    ("SYS", HANG_DET_SYS_AXI_CTRL, "tb_axi_hang_irq_sys"),
    ("SEP", HANG_DET_SEP_AXI_CTRL, "tb_axi_hang_irq_sep"),
    ("DATA", HANG_DET_DATA_ACCEL_CTRL, "tb_axi_hang_irq_data"),
)


class smc_hang_detector_sanity_test_seq(SmcCsrSeq):
    """irq_test fire/clear per detector + OR, with enable/irq_en poison."""

    def __init__(self, name: str = "smc_hang_detector_sanity_test_seq") -> None:
        super().__init__(name)
        # Counted by _await_irqs on each handshake that actually completed.
        self.irq_legs_handshaked = 0

    async def _await_irqs(self, dut, expect: dict[str, int], label: str) -> None:
        """Handshake each lifted irq to ``expect``; expiry fails with last state.

        expect==1: return as soon as the pin is 1.
        expect==0: fail immediately if the pin rises; succeed after the bound
        of still-low samples (ungated irq_test would already have gone high).
        """
        clk = dut.clk_smc_i
        want_high = [n for n, v in expect.items() if v == 1]
        want_low = [n for n, v in expect.items() if v == 0]
        last: dict[str, object] = {}
        for cycle in range(_IRQ_BOUND):
            await RisingEdge(clk)
            last = {n: getattr(dut, n).value for n in expect}
            for name in want_low:
                if not last[name].is_resolvable:
                    raise AssertionError(f"{label}: {name} unresolvable")
                if int(last[name]) != 0:
                    raise AssertionError(
                        f"{label}: {name} rose (last={last[name]}) while gated/cleared"
                    )
            if want_high:
                if all(last[n].is_resolvable and int(last[n]) == 1 for n in want_high):
                    self.irq_legs_handshaked += 1
                    return
            elif cycle + 1 == _IRQ_BOUND:
                self.irq_legs_handshaked += 1
                return
        raise AssertionError(
            f"{label}: irq handshake expired after {_IRQ_BOUND} smc clocks "
            f"last={ {n: str(v) for n, v in last.items()} }"
        )

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        await self._await_irqs(dut, {"tb_axi_hang_irq": 0}, "IDLE")

        # Poison: irq_test alone must not fire (enable and irq_en gate irq_o).
        await self.csr_write("HANG_SYS_TEST_ONLY", HANG_DET_SYS_AXI_CTRL, HANG_DET_IRQ_TEST)
        await self._await_irqs(
            dut,
            {"tb_axi_hang_irq": 0, "tb_axi_hang_irq_sys": 0},
            "POISON_TEST_ONLY",
        )
        await self.csr_write(
            "HANG_SYS_EN_TEST", HANG_DET_SYS_AXI_CTRL, HANG_DET_ENABLE | HANG_DET_IRQ_TEST
        )
        await self._await_irqs(dut, {"tb_axi_hang_irq": 0}, "POISON_NO_IRQ_EN")
        # irq_en and irq_test without enable: enable gates irq_o as well.
        await self.csr_write(
            "HANG_SYS_IRQEN_TEST", HANG_DET_SYS_AXI_CTRL, HANG_DET_IRQ_EN | HANG_DET_IRQ_TEST
        )
        await self._await_irqs(
            dut,
            {"tb_axi_hang_irq": 0, "tb_axi_hang_irq_sys": 0},
            "POISON_NO_ENABLE",
        )
        await self.csr_write("HANG_SYS_CLEAR_POISON", HANG_DET_SYS_AXI_CTRL, 0)
        await self._await_irqs(dut, {"tb_axi_hang_irq": 0}, "POISON_CLR")
        cocotb.log.info(
            "CHK-HANG-POISON: irq_test gated by enable+irq_en (test alone, enable+test and "
            "irq_en+test each left irq_o low)"
        )

        # Per-detector: fire one, others off, then clear.
        for label, addr, pin in _DETECTORS:
            await self.csr_write(f"HANG_{label}_FIRE", addr, HANG_DET_FIRE)
            expect_fire = {p: 0 for _l, _a, p in _DETECTORS}
            expect_fire[pin] = 1
            expect_fire["tb_axi_hang_irq"] = 1
            await self._await_irqs(dut, expect_fire, f"{label}_FIRE")
            cocotb.log.info("CHK-HANG-%s-FIRE: source=1 OR=1 others=0", label)
            await self.csr_write(f"HANG_{label}_CLR", addr, 0)
            await self._await_irqs(dut, {pin: 0, "tb_axi_hang_irq": 0}, f"{label}_CLR")
            cocotb.log.info("CHK-HANG-%s-CLR: source=0 OR=0", label)

        # OR: all three fire, then drop SYS+SEP, DATA keeps OR, then last clear.
        for label, addr, _pin in _DETECTORS:
            await self.csr_write(f"HANG_{label}_OR_FIRE", addr, HANG_DET_FIRE)
        await self._await_irqs(
            dut,
            {
                "tb_axi_hang_irq": 1,
                "tb_axi_hang_irq_sys": 1,
                "tb_axi_hang_irq_sep": 1,
                "tb_axi_hang_irq_data": 1,
            },
            "OR_ALL",
        )
        cocotb.log.info("CHK-HANG-OR-ALL: OR=1 sys=1 sep=1 data=1")

        await self.csr_write("HANG_SYS_OR_DROP", HANG_DET_SYS_AXI_CTRL, 0)
        await self.csr_write("HANG_SEP_OR_DROP", HANG_DET_SEP_AXI_CTRL, 0)
        await self._await_irqs(
            dut,
            {
                "tb_axi_hang_irq_sys": 0,
                "tb_axi_hang_irq_sep": 0,
                "tb_axi_hang_irq_data": 1,
                "tb_axi_hang_irq": 1,
            },
            "OR_HOLD",
        )
        cocotb.log.info("CHK-HANG-OR-HOLD: DATA keeps OR=1 after SYS+SEP clear")

        await self.csr_write("HANG_DATA_OR_DROP", HANG_DET_DATA_ACCEL_CTRL, 0)
        await self._await_irqs(dut, {"tb_axi_hang_irq": 0, "tb_axi_hang_irq_data": 0}, "OR_CLR")
        cocotb.log.info("CHK-HANG-OR-CLR: OR=0 after last detector clear")
        cocotb.log.info(
            "CHK-HANG-BASIC: %d irq handshakes completed across the poison, per-source and OR legs",
            self.irq_legs_handshaked,
        )
