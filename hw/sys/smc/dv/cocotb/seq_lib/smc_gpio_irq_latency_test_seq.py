# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO interrupt latency from the pad edge, and detection with register readback unselected.

`hw/ip/gpio/doc/architecture.adoc` (Interrupts) states that the input passes through a
three-stage synchronizer before interrupt detection and that the selected condition is
registered on `clk_i` and gated by `DATA_CTRL.interrupt_enable` at `interrupt_o`: a pad edge
reaches `interrupt_o` `SYNC_STAGES + 1` rises of `clk_smc_i` later, in every interrupt type.
The same section states that detection uses the synchronized input independently of whether
register readback is selected, and Input Readback states that `DATA_CTRL.pad2core` returns the
synchronized input only when `interface_enable` or `use_reg_rx` selects register readback.
`interface.adoc` (Interrupt Specifications) gives the latency as 2-3 clock cycles; the leaf
grades the architecture figure and reports the measured one against both.

Eight pads are drawn from the pads no bench function drives and no LSIO function owns at
reset (SPI lanes 1-7, SPI.CS, SPI.CLK, SPI.DQS, Thermal Emergency N and the reserved pads).
Each pad is driven through `tb_gpio_ext_drive_*` right after a `clk_smc_i` rise and
`tb_gpio_interrupt` is sampled on every following rise, so the latency is the number of rises
between the pad edge and the interrupt.
"""

from __future__ import annotations

import os
import random

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge

from .smc_addr_map import gpio_intf_u32, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_gpio_irq_active_test_seq import DATA_CTRL_SW_MASK
from .smc_gpio_vip_utils import drive_gpio_pad
from .smc_pad_table import gpio_pad_count, pad_function, pad_index

_RX_ENABLE = 2 << gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bp")
_IF_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERFACE_ENABLE_bm")
_IRQ_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERRUPT_ENABLE_bm")
_TYPE_BP = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERRUPT_TYPE_bp")
_PAD2CORE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__PAD2CORE_bm")
#: `interrupt_type` encodings of `gpio_intf.rdl`.
TYPE_ACTIVE_HIGH = 0 << _TYPE_BP
TYPE_RISING = 2 << _TYPE_BP
TYPE_FALLING = 3 << _TYPE_BP

#: Readback selected: RX enabled through the register path, the interrupt enabled.
CFG_READBACK = _RX_ENABLE | _IF_ENABLE | _IRQ_ENABLE
#: Readback unselected: neither `interface_enable` nor `use_reg_rx`; the pad is an input by
#: default and only the interrupt is enabled.
CFG_NO_READBACK = _IRQ_ENABLE

SYNC_STAGES = 3
#: Rises from the pad edge to `interrupt_o`: the synchronizer plus the condition register.
EXPECTED_LATENCY = SYNC_STAGES + 1
#: An edge type gives a one-rise pulse; a level type holds while the pad does.
EDGE_PULSE = 1
LATENCY_BOUND = 16
DRAWN_PADS = 8


def _pad_pool() -> list[int]:
    pads = [pad_index(f"SPI.DATA[{lane}]") for lane in range(1, 8)]
    pads += [pad_index("SPI.CS"), pad_index("SPI.CLK"), pad_index("SPI.DQS")]
    pads.append(pad_index("Thermal Emergency N"))
    pads += [i for i in range(gpio_pad_count()) if pad_function(i) == "Reserved"]
    return sorted(set(pads))


def _data_ctrl(pad: int) -> int:
    return smc_indexed_addr("SMC_TOP_GPIO_INTF_WRAP_GPIO_INTF_DATA_CTRL_BASE_ADDR", pad)


class smc_gpio_irq_latency_test_seq(SmcCsrSeq):
    """Measure the pad-edge-to-interrupt latency on drawn pads and the readback-free detection."""

    def __init__(self, name: str = "smc_gpio_irq_latency_test_seq") -> None:
        super().__init__(name)
        self.seed = int(os.environ.get("RANDOM_SEED", "1"), 0)
        self.pads = random.Random(self.seed).sample(_pad_pool(), DRAWN_PADS)
        self.chk_seen: set[str] = set()
        self.latencies: list[tuple[int, str, int, int]] = []

    def _chk(self, token: str, text: str) -> None:
        cocotb.log.info("%s: %s", token, text)
        self.chk_seen.add(token)

    @staticmethod
    def _irq_vector() -> int:
        value = cocotb.top.tb_gpio_interrupt.value
        assert value.is_resolvable, f"tb_gpio_interrupt unresolvable: {value}"
        return int(value)

    async def _edge_to_irq(
        self, pad: int, level: int, label: str, edge: bool = True
    ) -> tuple[int, int]:
        """Drive `pad` to `level` right after a rise; return (rises to the interrupt, rises held).

        Every sample before the interrupt must show the whole vector at 0 and the sample that
        shows it must be exactly this pad's bit; the bound expiring is a failure. The rises
        held are counted for an edge type only; a level type holds while the pad does.
        """
        dut = cocotb.top
        clk = dut.clk_smc_i
        await RisingEdge(clk)
        drive_gpio_pad(dut, pad, level)
        latency = None
        for rises in range(1, LATENCY_BOUND + 1):
            await RisingEdge(clk)
            await ReadOnly()
            vector = self._irq_vector()
            if vector:
                assert vector == 1 << pad, (
                    f"{label}: tb_gpio_interrupt=0x{vector:x} {rises} rises after the pad {pad} "
                    f"edge, expected only bit {pad}"
                )
                latency = rises
                break
        assert latency is not None, (
            f"{label}: pad {pad} driven to {level}, tb_gpio_interrupt stayed 0 for {LATENCY_BOUND} "
            f"rises"
        )
        pulse = 1
        while edge:
            await RisingEdge(clk)
            await ReadOnly()
            if not self._irq_vector() >> pad & 1:
                break
            pulse += 1
            assert pulse <= LATENCY_BOUND, f"{label}: pad {pad} interrupt held for {pulse} rises"
        await RisingEdge(clk)
        return latency, pulse

    async def _wait_level_irq_clear(self, pad: int, label: str) -> None:
        """Drop the pad and wait for a level interrupt to clear, bounded."""
        dut = cocotb.top
        clk = dut.clk_smc_i
        await RisingEdge(clk)
        drive_gpio_pad(dut, pad, 0)
        for _ in range(LATENCY_BOUND):
            await RisingEdge(clk)
            await ReadOnly()
            if not self._irq_vector():
                await RisingEdge(clk)
                return
        raise AssertionError(f"{label}: pad {pad} level interrupt did not clear in {LATENCY_BOUND}")

    async def _program(self, pad: int, cfg: int, label: str) -> int:
        """Write DATA_CTRL and read it back; returns the readback word."""
        await self.csr_write(f"{label}_W", _data_ctrl(pad), cfg)
        got = await self.csr_read(f"{label}_RB", _data_ctrl(pad))
        assert got & DATA_CTRL_SW_MASK == cfg, (
            f"{label}: pad {pad} DATA_CTRL stored 0x{got & DATA_CTRL_SW_MASK:08x}, wrote 0x{cfg:08x}"
        )
        return got

    async def _latency_legs(self, pad: int) -> None:
        dut = cocotb.top
        drive_gpio_pad(dut, pad, 0)
        got = await self._program(pad, CFG_READBACK | TYPE_RISING, f"P{pad}_RISING")
        assert not got & _PAD2CORE, f"pad {pad} pad2core reads 1 with the pad driven 0"
        assert self._irq_vector() == 0, (
            f"tb_gpio_interrupt=0x{self._irq_vector():x} before the edge"
        )
        latency, pulse = await self._edge_to_irq(pad, 1, f"P{pad}_RISING")
        self.latencies.append((pad, "rising", latency, pulse))
        got = await self.csr_read(f"P{pad}_HIGH_RB", _data_ctrl(pad))
        assert got & _PAD2CORE, (
            f"pad {pad} pad2core reads 0 with the pad driven 1 and readback selected"
        )

        await self._program(pad, CFG_READBACK | TYPE_FALLING, f"P{pad}_FALLING")
        latency, pulse = await self._edge_to_irq(pad, 0, f"P{pad}_FALLING")
        self.latencies.append((pad, "falling", latency, pulse))

        await self._program(pad, CFG_READBACK | TYPE_ACTIVE_HIGH, f"P{pad}_LEVEL")
        latency, pulse = await self._edge_to_irq(pad, 1, f"P{pad}_LEVEL", edge=False)
        self.latencies.append((pad, "level", latency, pulse))
        await self._wait_level_irq_clear(pad, f"P{pad}_LEVEL_CLEAR")
        await self._program(pad, 0, f"P{pad}_OFF")
        drive_gpio_pad(dut, pad, None)

    async def _without_readback(self, pad: int) -> None:
        dut = cocotb.top
        input_enable = int(dut.tb_pad2core_en_o.value) >> pad & 1
        assert input_enable, f"pad {pad} pad2core_en is 0 with every DATA_CTRL field clear"
        drive_gpio_pad(dut, pad, 0)
        got = await self._program(pad, CFG_NO_READBACK | TYPE_RISING, f"P{pad}_NORB")
        assert not got & _PAD2CORE, f"pad {pad} pad2core reads 1 with the pad driven 0"
        latency, pulse = await self._edge_to_irq(pad, 1, f"P{pad}_NORB")
        high_rb = await self.csr_read(f"P{pad}_NORB_HIGH_RB", _data_ctrl(pad))
        await self._program(pad, 0, f"P{pad}_NORB_OFF")
        drive_gpio_pad(dut, pad, None)
        assert latency == EXPECTED_LATENCY and pulse == EDGE_PULSE, (
            f"pad {pad} with readback unselected: interrupt {latency} rises after the edge, held "
            f"{pulse}; expected {EXPECTED_LATENCY} and {EDGE_PULSE}"
        )
        assert not high_rb & _PAD2CORE, (
            f"pad {pad} pad2core reads 1 (0x{high_rb:08x}) with neither interface_enable nor "
            f"use_reg_rx set; readback unselected returns zero"
        )
        self._chk(
            "CHK-GPIO-IRQ-WITHOUT-READBACK",
            f"pad {pad}: DATA_CTRL=0x{CFG_NO_READBACK | TYPE_RISING:08x} (interrupt_enable + "
            f"rising edge, no interface_enable, no use_reg_rx), pad2core_en={input_enable}; a "
            f"0 -> 1 pad edge raised tb_gpio_interrupt[{pad}] {latency} rises later for {pulse} "
            f"rise while DATA_CTRL.pad2core read {high_rb >> 31 & 1} with the pad high; with "
            f"readback selected the same pad read pad2core 1",
        )

    async def body(self) -> None:
        for pad in self.pads:
            await self._latency_legs(pad)
        await self._without_readback(self.pads[0])
        off = [
            (pad, kind, latency, pulse)
            for pad, kind, latency, pulse in self.latencies
            if latency != EXPECTED_LATENCY or (kind != "level" and pulse != EDGE_PULSE)
        ]
        assert not off, (
            f"(pad, type, rises to interrupt, rises held) off the stated figure "
            f"{EXPECTED_LATENCY} / {EDGE_PULSE}: {off}"
        )
        measured = sorted({latency for _, _, latency, _ in self.latencies})
        self._chk(
            "CHK-GPIO-IRQ-LATENCY",
            f"seed {self.seed} pads {self.pads}: {len(self.latencies)} pad edges (rising, falling "
            f"and active-high level on each pad) raised the pad's own tb_gpio_interrupt bit "
            f"{measured} rises of clk_smc_i after the edge == {SYNC_STAGES}-stage synchronizer + 1 "
            f"register ({EXPECTED_LATENCY}); edge pulses held {EDGE_PULSE} rise; interface.adoc "
            f"gives 2-3 cycles",
        )
