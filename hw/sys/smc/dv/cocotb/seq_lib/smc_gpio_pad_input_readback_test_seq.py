# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A pad input transition is captured in DATA_CTRL.pad2core; TX enable drives core2pad_en_o.

``port_table.adoc`` describes ``pad2core_i`` as "GPIO input data from pad ring
to core" and ``core2pad_en_o`` as the "core-to-pad path enable". For several
wraps the pad is driven from the bench (``tb_gpio_ext_drive_*``, the same
external-pin path the GPIO interrupt tests use), the wrap is programmed as a
register-controlled input, and the ``DATA_CTRL.pad2core`` bit must follow the
pad both ways within a bounded number of reads. Each wrap is then programmed
as a register-controlled output and its bit of ``tb_core2pad_en_o`` (a mirror
of the ``core2pad_en_o`` port) must rise and fall with the enable; exactly one
bit of the vector may move, which is what attributes the change to that wrap.

``pad2core_en_o`` has no vector probe in ``tb_top`` and
``lsio_interface_select_o`` is unconnected, so the RX direction enable and the
interface-select output are not claimed.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import gpio_intf_u32, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_pad_table import pad_function, pad_index
from .smc_probe_positive_control import _pad_vec

# Field positions from the generated gpio_intf.h.
_IF_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERFACE_ENABLE_bm")
_RX_TX_BP = gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bp")
_CORE2PAD = gpio_intf_u32("GPIO_INTF__DATA_CTRL__CORE2PAD_bm")
_PAD2CORE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__PAD2CORE_bm")
# enable_rx_tx: bit 1 = RX (input enable), bit 0 = TX (output enable).
DATA_CTRL_REG_INPUT = _IF_ENABLE | (2 << _RX_TX_BP)
DATA_CTRL_REG_OUTPUT_HIGH = _IF_ENABLE | (1 << _RX_TX_BP) | _CORE2PAD
DATA_CTRL_RESET = 0

# Wraps chosen from the integrator pad table (`doc/integrator/meta/
# ocah_gpio_table.csv`): three SPI data lanes and the SPI chip select, whose
# function the bench leaves disabled, the thermal-emergency input and a pad the
# table reserves. Whether a wrap is free is measured, not assumed: each must
# read its enable bit clear before it is programmed and follow the bench drive
# on `pad2core`, so a wrap some function or bench block owns fails here.
_RESERVED_WRAP = 60
assert pad_function(_RESERVED_WRAP) == "Reserved", (
    f"the integrator pad table no longer reserves pad {_RESERVED_WRAP}"
)
WRAPS = (
    pad_index("SPI.DATA[0]"),
    pad_index("SPI.DATA[1]"),
    pad_index("SPI.DATA[2]"),
    pad_index("SPI.CS"),
    pad_index("Thermal Emergency N"),
    _RESERVED_WRAP,
)
# DATA_CTRL reads polled until pad2core follows the pad; the path is the pad
# shim, a two-flop synchronizer and the register read.
CAPTURE_BOUND_READS = 8
# Bound for core2pad_en_o to follow the register, in clk_smc_i cycles.
OE_BOUND_SMC_CYCLES = 64

# Per wrap: the input-mode write, at least one DATA_CTRL poll per pad level
# (three levels), the output-mode write and the restore; the exact count
# depends on how many polls each level needed.
EXPECTED_MIN_ACCESSES = len(WRAPS) * 6


class smc_gpio_pad_input_readback_test_seq(SmcCsrSeq):
    """Pad -> DATA_CTRL.pad2core both ways, TX enable -> core2pad_en_o, on several wraps."""

    def __init__(self, name: str = "smc_gpio_pad_input_readback_test_seq") -> None:
        super().__init__(name)
        self.polls: dict[tuple[int, int], int] = {}
        self.oe_cycles: dict[int, tuple[int, int]] = {}
        self.wraps_done: list[int] = []

    @staticmethod
    def _data_ctrl(wrap: int) -> int:
        return smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", wrap)

    @staticmethod
    def _drive(dut, wrap: int, level: int | None) -> None:
        en = int(dut.tb_gpio_ext_drive_en.value)
        val = int(dut.tb_gpio_ext_drive_value.value)
        mask = 1 << wrap
        if level is None:
            en &= ~mask
        else:
            en |= mask
            val = (val | mask) if level else (val & ~mask)
        dut.tb_gpio_ext_drive_en.value = en
        dut.tb_gpio_ext_drive_value.value = val

    async def _await_pad2core(self, wrap: int, want: int) -> int:
        addr = self._data_ctrl(wrap)
        last = None
        for poll in range(1, CAPTURE_BOUND_READS + 1):
            word = await self.csr_read(f"GPIO{wrap}_DATA_CTRL_PAD{want}", addr)
            last = 1 if word & _PAD2CORE else 0
            if last == want:
                self.polls[(wrap, want)] = poll
                return word
            await ClockCycles(cocotb.top.clk_smc_i, 4)
        raise AssertionError(
            f"GPIO wrap {wrap}: DATA_CTRL.pad2core stayed {last} over {CAPTURE_BOUND_READS} reads "
            f"while the pad was driven {want}"
        )

    async def _await_oe(self, dut, wrap: int, want: int, base_en: int, mask: int) -> int:
        for cycle in range(OE_BOUND_SMC_CYCLES):
            en = _pad_vec(dut, "tb_core2pad_en_o")
            moved = en ^ base_en
            assert moved & ~(1 << wrap) == 0, (
                f"GPIO wrap {wrap}: programming its output enable moved other core2pad_en_o bits "
                f"(delta 0x{moved & mask:x})"
            )
            if ((en >> wrap) & 1) == want:
                return cycle
            await ClockCycles(dut.clk_smc_i, 1)
        raise AssertionError(
            f"GPIO wrap {wrap}: tb_core2pad_en_o[{wrap}] did not reach {want} within "
            f"{OE_BOUND_SMC_CYCLES} clk_smc_i cycles of the DATA_CTRL write"
        )

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        width = len(dut.tb_core2pad_en_o.value)
        mask = (1 << width) - 1

        for wrap in WRAPS:
            addr = self._data_ctrl(wrap)
            base_en = _pad_vec(dut, "tb_core2pad_en_o")
            assert ((base_en >> wrap) & 1) == 0, (
                f"GPIO wrap {wrap}: core2pad_en_o already set before programming; not a "
                f"register-controlled input wrap in this bench"
            )
            await self.csr_write(f"GPIO{wrap}_DATA_CTRL_INPUT", addr, DATA_CTRL_REG_INPUT)
            self._drive(dut, wrap, 0)
            await self._await_pad2core(wrap, 0)
            self._drive(dut, wrap, 1)
            await self._await_pad2core(wrap, 1)
            self._drive(dut, wrap, 0)
            await self._await_pad2core(wrap, 0)
            self._drive(dut, wrap, None)

            await self.csr_write(f"GPIO{wrap}_DATA_CTRL_OUTPUT", addr, DATA_CTRL_REG_OUTPUT_HIGH)
            rise = await self._await_oe(dut, wrap, 1, base_en, mask)
            await self.csr_write(f"GPIO{wrap}_DATA_CTRL_RESTORE", addr, DATA_CTRL_RESET)
            fall = await self._await_oe(dut, wrap, 0, base_en, mask)
            self.oe_cycles[wrap] = (rise, fall)
            self.wraps_done.append(wrap)
            cocotb.log.info(
                "CHK-GPIO-PAD-INPUT-WRAP%d: pad 0->1->0 followed in DATA_CTRL.pad2core after "
                "%d/%d/%d read(s); TX enable raised core2pad_en_o[%d] after %d cycle(s) and the "
                "restore cleared it after %d",
                wrap,
                self.polls[(wrap, 0)],
                self.polls[(wrap, 1)],
                self.polls[(wrap, 0)],
                wrap,
                rise,
                fall,
            )

        assert self.wraps_done == list(WRAPS)
        assert self.accesses >= EXPECTED_MIN_ACCESSES, (
            f"issued {self.accesses} accesses, expected at least {EXPECTED_MIN_ACCESSES}"
        )
        sb = self.env.scoreboard
        assert sb.sys_axi_checks_seen >= self.accesses, (
            f"scoreboard checked {sb.sys_axi_checks_seen} SEP_IN items for {self.accesses} accesses"
        )
        cocotb.log.info(
            "CHK-GPIO-PAD-INPUT-READBACK: %d wraps %s each captured pad low and high in "
            "DATA_CTRL.pad2core and toggled their own core2pad_en_o bit under TX enable; "
            "%d SEP_IN accesses; pad2core_en_o and lsio_interface_select_o are not probed in tb_top "
            "and are not claimed",
            len(self.wraps_done),
            self.wraps_done,
            self.accesses,
        )
