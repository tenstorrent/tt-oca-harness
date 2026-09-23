# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Hang-detector OR reaches the PLIC on peripheral_interrupts[30].

Covers the smc_base -> smc_peripherals[30] -> cpu_interrupts route through which
FW services an armed detector. The observation point is the PLIC source pin on
``u_smc_cpu_wrapper.interrupts_i`` (raw bit NUM_EXT_INTERRUPTS+30 = 286 in the
4-core config, PLIC source ID 287). PLIC register-level claim/complete needs CPU
firmware and is not claimed here.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import (
    HANG_DET_DATA_ACCEL_CTRL,
    HANG_DET_ENABLE,
    HANG_DET_FIRE,
    HANG_DET_IRQ_TEST,
    HANG_DET_SEP_AXI_CTRL,
    HANG_DET_SYS_AXI_CTRL,
)
from .smc_csr_seq_utils import SmcCsrSeq

# irq_o is combinational after the CTRL flop, and the route to the PLIC pin is
# combinational too, so the AXI write completion already implies the update.
# This bound is only the fail-closed ceiling.
_IRQ_BOUND = 64

# Every stage of the route, innermost first. All three must move together.
_ROUTE = ("tb_axi_hang_irq", "tb_axi_hang_irq_periph30", "tb_axi_hang_irq_plic_src")

# Independent detectors: (label, CTRL addr, TB per-source pin).
_DETECTORS = (
    ("SYS", HANG_DET_SYS_AXI_CTRL, "tb_axi_hang_irq_sys"),
    ("SEP", HANG_DET_SEP_AXI_CTRL, "tb_axi_hang_irq_sep"),
    ("DATA", HANG_DET_DATA_ACCEL_CTRL, "tb_axi_hang_irq_data"),
)


class smc_hang_detector_plic_route_test_seq(SmcCsrSeq):
    """Each detector's irq_test drives the PLIC source pin, and clears it."""

    def __init__(self, name: str = "smc_hang_detector_plic_route_test_seq") -> None:
        super().__init__(name)
        self.idle_ok = False
        self.gated_ok = False
        self.route_ok = False
        self.shared_slot_ok = False

    async def _await_pins(self, dut, expect: dict[str, int], label: str) -> None:
        """Handshake each lifted pin to ``expect``; expiry fails with last state.

        expect==1: return as soon as every wanted pin reads 1.
        expect==0: fail immediately if a pin rises; succeed after the bound of
        still-low samples.
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
                    return
            elif cycle + 1 == _IRQ_BOUND:
                return
        raise AssertionError(
            f"{label}: pin handshake expired after {_IRQ_BOUND} smc clocks "
            f"last={ {n: str(v) for n, v in last.items()} }"
        )

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()

        # Quiet at rest, so a pass below is the route working and not a
        # stuck-high peripheral bit.
        await self._await_pins(dut, {n: 0 for n in _ROUTE}, "IDLE")
        self.idle_ok = True
        cocotb.log.info("CHK-HANG-PLIC-IDLE: periph[30] and PLIC source pin low at rest")

        # irq_test without enable+irq_en must not reach the PLIC either.
        await self.csr_write(
            "HANG_SYS_EN_TEST", HANG_DET_SYS_AXI_CTRL, HANG_DET_ENABLE | HANG_DET_IRQ_TEST
        )
        await self._await_pins(dut, {n: 0 for n in _ROUTE}, "GATED_NO_IRQ_EN")
        await self.csr_write("HANG_SYS_CLEAR_POISON", HANG_DET_SYS_AXI_CTRL, 0)
        await self._await_pins(dut, {n: 0 for n in _ROUTE}, "GATED_CLR")
        self.gated_ok = True
        cocotb.log.info("CHK-HANG-PLIC-GATED: irq_en gates the PLIC route, not just irq_o")

        # Each detector alone must light the whole route, then release it.
        for label, addr, pin in _DETECTORS:
            await self.csr_write(f"HANG_{label}_FIRE", addr, HANG_DET_FIRE)
            expect_fire = {p: 0 for _l, _a, p in _DETECTORS}
            expect_fire[pin] = 1
            expect_fire.update({n: 1 for n in _ROUTE})
            await self._await_pins(dut, expect_fire, f"{label}_PLIC_FIRE")
            cocotb.log.info("CHK-HANG-PLIC-%s-FIRE: source=1 periph[30]=1 PLIC source pin=1", label)

            await self.csr_write(f"HANG_{label}_CLR", addr, 0)
            await self._await_pins(dut, {pin: 0, **{n: 0 for n in _ROUTE}}, f"{label}_PLIC_CLR")
            cocotb.log.info("CHK-HANG-PLIC-%s-CLR: route back to 0", label)
        self.route_ok = True

        # The slot is shared by all three detectors: it must stay asserted while
        # any one is still firing, so FW cannot lose a fault by clearing a peer.
        for label, addr, _pin in _DETECTORS:
            await self.csr_write(f"HANG_{label}_SHARED_FIRE", addr, HANG_DET_FIRE)
        await self._await_pins(dut, {n: 1 for n in _ROUTE}, "SHARED_ALL")

        await self.csr_write("HANG_SYS_SHARED_DROP", HANG_DET_SYS_AXI_CTRL, 0)
        await self.csr_write("HANG_SEP_SHARED_DROP", HANG_DET_SEP_AXI_CTRL, 0)
        await self._await_pins(
            dut,
            {
                "tb_axi_hang_irq_sys": 0,
                "tb_axi_hang_irq_sep": 0,
                "tb_axi_hang_irq_data": 1,
                **{n: 1 for n in _ROUTE},
            },
            "SHARED_HOLD",
        )
        cocotb.log.info("CHK-HANG-PLIC-SHARED-HOLD: DATA holds the PLIC slot after SYS+SEP clear")

        await self.csr_write("HANG_DATA_SHARED_DROP", HANG_DET_DATA_ACCEL_CTRL, 0)
        await self._await_pins(
            dut, {"tb_axi_hang_irq_data": 0, **{n: 0 for n in _ROUTE}}, "SHARED_CLR"
        )
        self.shared_slot_ok = True
        cocotb.log.info("CHK-HANG-PLIC-SHARED-CLR: slot releases after the last detector clears")

        cocotb.log.info(
            "CHK-HANG-PLIC-ROUTE: idle=%s gated=%s route=%s shared=%s",
            self.idle_ok,
            self.gated_ok,
            self.route_ok,
            self.shared_slot_ok,
        )
