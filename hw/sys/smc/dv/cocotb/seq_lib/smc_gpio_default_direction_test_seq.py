# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The GPIO default direction map at the pads, and the cold-reset forcing of every controller.

`hw/sys/smc/doc/periphs.adoc` (parameter table) gives `INPUT_BY_DEFAULT` per instance from
`smc_padring_pkg::DefaultDirectionMap`: input on 62 of 65 GPIOs, output on the remaining 3;
the package the document delegates to names them as pads 62-64. `hw/ip/gpio/doc/architecture.adoc` states what the
parameter does: with no owner the controller gives output data 0, TX disabled and RX set by
`INPUT_BY_DEFAULT` (Data and Direction Ownership, priority 4), and `rst_cold_ni` separately
forces controller outputs to data 0, TX disabled and RX = `INPUT_BY_DEFAULT` (Reset and Strap
Capture).
The bench exposes `tb_pad2core_en_o`, `tb_core2pad_en_o` and `tb_core2pad_o` of all 65
controllers and `tb_lsio_interface_select`. The map is graded twice: on the pads no LSIO
function owns at reset while the SMC runs, and on all 65 pads while a cold reset is asserted
through the reset agent, after two pads were programmed as outputs with RX off so the forcing
has something to undo. After the release the registers are back at reset and the map holds
again.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from env.smc_reset_item import SmcResetOp

from .smc_addr_map import gpio_intf_u32, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_pad_table import gpio_pad_count, pad_index
from .smc_reset_seq_base import SmcResetSeqBase

PAD_COUNT = gpio_pad_count()
PAD_MASK = (1 << PAD_COUNT) - 1
#: Pads the package makes outputs by default (`DefaultDirectionMap` 62-64).
OUTPUT_BY_DEFAULT = (62, 63, 64)
DEFAULT_INPUT_MAP = PAD_MASK & ~sum(1 << p for p in OUTPUT_BY_DEFAULT)
DEFAULT_INPUT_COUNT = PAD_COUNT - len(OUTPUT_BY_DEFAULT)
#: Two pads no LSIO function owns at reset, programmed as outputs before the cold reset.
PROGRAMMED_PADS = (pad_index("SPI.DATA[1]"), pad_index("SPI.DATA[2]"))
#: Register-owned output driving 1 with RX off.
OUTPUT_DRIVING_ONE = (
    gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERFACE_ENABLE_bm")
    | (1 << gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bp"))
    | gpio_intf_u32("GPIO_INTF__DATA_CTRL__CORE2PAD_bm")
)
#: Rises the pad vectors may take to follow a DATA_CTRL write or the cold-reset assertion.
PAD_BOUND = 64
FUSE_BOUND_CYCLES = 200_000


def _data_ctrl(pad: int) -> int:
    return smc_indexed_addr("SMC_TOP_GPIO_INTF_WRAP_GPIO_INTF_DATA_CTRL_BASE_ADDR", pad)


def _popcount(value: int) -> int:
    return bin(value & PAD_MASK).count("1")


def _pads(value: int) -> list[int]:
    return [p for p in range(PAD_COUNT) if value >> p & 1]


class smc_gpio_default_direction_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """Grade the 62/3 direction map on the pads, in operation and under cold reset."""

    def __init__(self, name: str = "smc_gpio_default_direction_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()
        self.waits: list[str] = []

    async def _dispatch_reset_item(self, item) -> None:
        await self.dispatch_reset(item)

    def _chk(self, token: str, text: str) -> None:
        cocotb.log.info("%s: %s", token, text)
        self.chk_seen.add(token)

    @staticmethod
    def _vectors() -> dict[str, int]:
        out = {}
        for name in (
            "tb_pad2core_en_o",
            "tb_core2pad_en_o",
            "tb_core2pad_o",
            "tb_lsio_interface_select",
        ):
            value = getattr(cocotb.top, name).value
            assert value.is_resolvable, f"{name} unresolvable: {value}"
            out[name] = int(value) & PAD_MASK
        return out

    async def _await_vectors(self, label: str, holds) -> dict[str, int]:
        """Sample the pad vectors every rise until `holds(vectors)`; expiry fails."""
        clk = cocotb.top.clk_smc_i
        last = None
        for rises in range(1, PAD_BOUND + 1):
            await RisingEdge(clk)
            await ReadOnly()
            last = self._vectors()
            if holds(last):
                self.waits.append(f"{label}: after {rises} rises")
                await RisingEdge(clk)
                return last
        raise AssertionError(f"{label}: pad vectors never matched within {PAD_BOUND} rises: {last}")

    def _grade_free_pads(self, label: str, v: dict[str, int]) -> tuple[int, int]:
        """On the pads no LSIO function owns: RX per the map, TX off, data 0."""
        free = PAD_MASK & ~v["tb_lsio_interface_select"]
        rx_off = free & ~v["tb_pad2core_en_o"] & DEFAULT_INPUT_MAP
        rx_on = free & v["tb_pad2core_en_o"] & ~DEFAULT_INPUT_MAP
        tx_on = free & v["tb_core2pad_en_o"]
        data = free & v["tb_core2pad_o"]
        assert not (rx_off | rx_on | tx_on | data), (
            f"{label}: on the pads no LSIO function owns (select=0x{free:x}): input pads with RX off "
            f"{_pads(rx_off)}, output-by-default pads with RX on {_pads(rx_on)}, TX on {_pads(tx_on)}, "
            f"data 1 {_pads(data)}; map {_pads(~DEFAULT_INPUT_MAP & PAD_MASK)} output by default"
        )
        return free, _popcount(free & v["tb_pad2core_en_o"])

    async def body(self) -> None:
        entry = self._vectors()
        free_entry, inputs_entry = self._grade_free_pads("ENTRY", entry)

        for pad in PROGRAMMED_PADS:
            await self.csr_write(f"PAD{pad}_OUT", _data_ctrl(pad), OUTPUT_DRIVING_ONE)
        programmed = await self._await_vectors(
            "PROGRAMMED",
            lambda v: all(
                v["tb_core2pad_en_o"] >> p & 1
                and v["tb_core2pad_o"] >> p & 1
                and not v["tb_pad2core_en_o"] >> p & 1
                for p in PROGRAMMED_PADS
            ),
        )

        await self._send(SmcResetOp.COLD_RST_LO)
        await self._wait_state(
            "COLD_ASSERT",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        in_reset = await self._await_vectors(
            "COLD_FORCED",
            lambda v: v["tb_core2pad_en_o"] == 0 and v["tb_pad2core_en_o"] == DEFAULT_INPUT_MAP,
        )
        assert in_reset["tb_core2pad_o"] == 0, (
            f"cold reset asserted: core2pad data 0x{in_reset['tb_core2pad_o']:x}, expected 0 on all pads"
        )
        await self._send(SmcResetOp.COLD_RST_HI)
        await self._wait_released("COLD_RELEASE")
        await self.wait_fuse_sense_done(FUSE_BOUND_CYCLES)
        self.waits.append(f"fuse sense after the release: bound {FUSE_BOUND_CYCLES} clk_smc_i")
        after = self._vectors()
        free_after, inputs_after = self._grade_free_pads("AFTER_RELEASE", after)
        for pad in PROGRAMMED_PADS:
            await self.csr_read(f"PAD{pad}_RESET_RB", _data_ctrl(pad), expected=0)
        for term in self._timeout_paths:
            self.waits.append(term)

        self._chk(
            "CHK-GPIO-DEFAULT-DIRECTION-MAP",
            f"cold reset asserted (programmed pads {list(PROGRAMMED_PADS)} were TX on, data 1, RX "
            f"off: core2pad_en=0x{programmed['tb_core2pad_en_o']:x} pad2core_en="
            f"0x{programmed['tb_pad2core_en_o']:x}): pad2core_en=0x{in_reset['tb_pad2core_en_o']:x} "
            f"== DefaultDirectionMap "
            f"(popcount {_popcount(in_reset['tb_pad2core_en_o'])} == {DEFAULT_INPUT_COUNT}, off "
            f"on {_pads(~in_reset['tb_pad2core_en_o'] & PAD_MASK)}), core2pad_en=0 and core2pad=0 "
            f"on all {PAD_COUNT}; in operation at entry and after the release the "
            f"{_popcount(free_entry)}/{_popcount(free_after)} pads no LSIO function owns had RX on "
            f"{inputs_entry}/{inputs_after} (all of them), TX off and data 0, LSIO-owned pads "
            f"{_pads(entry['tb_lsio_interface_select'])}; DATA_CTRL of the programmed pads reads 0 "
            f"after the release; bounded waits: {'; '.join(self.waits)}",
        )
