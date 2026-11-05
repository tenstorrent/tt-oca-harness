# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""One failed zero fill stops the boot, at every place the ROM clears memory with one.

The ROM clears memory with the secure DMA's zero fill (CONTROL.OPCODE 4). A correct ROM
never sees a fill fail, so each case here makes exactly one fill fail: while a zero fill
whose destination lies in the region ``dma_fill_fault_sel_i`` names is running, the
testbench forces an error onto the DMA host path's write responses (``tb/tb_top.sv``),
and the fill ends in BUS_ERROR. Every other transfer of the boot runs unfaulted.

``+zero_fill_fault=<case>`` picks the clear site; the testlist runs each case with the
firmware build that has that site:

* ``pad``: default build, the ICCM pad before the BL1 copy.
* ``iccm_clear``: ``boot_rom_clear``, the full ICCM clear at ``[S16]``.
* ``retry``: default build with the primary slot erased, the SEP SRAM clear before the
  backup is staged.
* ``scrub``: ``boot_rom_clear``, the SEP SRAM scrub at ``[S15]``.

Each case boots as ``sep_rom_ot_dma_boot_test`` does, with the scoreboard told to expect a
refused boot. It requires that the fault fired (``dma_fill_fault_count_o``), that the ROM
printed the failure marker of that clear site, in order, and nothing that would show the
boot carrying on past it, and that the statuses the site reports reached
``cold_scratch[1]``.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env import sep_manifest_mutate as mm
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

# dma_fill_fault_sel_i encodings (tb/sep_tb_signal_list.svh).
FAULT_ICCM = 1
FAULT_SRAM_BASE = 2

_BASE_FORBIDDEN = sep_rom_ot_dma_boot_test.forbidden_markers


@dataclass(frozen=True)
class _Case:
    fault_sel: int
    # Console markers that must appear, in this order.
    in_order: tuple[str, ...]
    # Console markers that must appear anywhere, on top of in_order.
    also_required: tuple[str, ...]
    forbidden: tuple[str, ...]
    # (kind, SEP_MSG_* name) statuses the ROM must report, kind "ERROR" or "WARN".
    statuses: tuple[tuple[str, str], ...]
    erase_primary: bool = False


_CASES = {
    "pad": _Case(
        fault_sel=FAULT_ICCM,
        in_order=("BL1_DST=ICCM", "ICCM_PAD_FAIL"),
        also_required=sep_rom_ot_dma_boot_test.required_markers,
        forbidden=("ICCM_PAD=", "BL1_COPIED", "BL1_JUMP="),
        statuses=(("WARN", "SEP_MSG_DMA_ERROR"), ("ERROR", "SEP_MSG_BL1_BAD_ADDR")),
    ),
    "iccm_clear": _Case(
        fault_sel=FAULT_ICCM,
        in_order=("SRAM_CLR_OK", "ICCM_CLR_FAIL"),
        also_required=(),
        forbidden=("ICCM_CLR_FULL", "MANIFEST_SRC="),
        statuses=(("WARN", "SEP_MSG_DMA_ERROR"),),
    ),
    "retry": _Case(
        fault_sel=FAULT_SRAM_BASE,
        in_order=(
            f"MANIFEST_ERR=0x{mm.boot_err('OCA_FAIL_MAGIC'):08x}",
            "SRAM_RETRY_CLR_FAIL",
            f"MANIFEST_BOOT_FAIL=0x{mm.rom_boot_err('OCA_BOOT_ERR_DMA'):08x}",
        ),
        also_required=("BOOT_SPI", "MANIFEST_SRC=0x00001000"),
        forbidden=("MANIFEST_BACKUP", "MANIFEST_ALL_FAILED", "MANIFEST_OK"),
        statuses=(("WARN", "SEP_MSG_DMA_ERROR"), ("ERROR", "SEP_MSG_MANIFEST_LOAD_FAILED")),
        erase_primary=True,
    ),
    "scrub": _Case(
        fault_sel=FAULT_SRAM_BASE,
        in_order=("SRAM_SCRUB_LEN=", "SRAM_CLR_FAIL"),
        also_required=(),
        forbidden=("SRAM_CLR_OK", "MANIFEST_SRC="),
        statuses=(("WARN", "SEP_MSG_DMA_ERROR"),),
    ),
}


@pyuvm.test()
class sep_rom_zero_fill_fault_test(sep_rom_ot_dma_boot_test):
    """Boot over SPI with one zero fill faulted; the ROM must refuse the boot."""

    _case: _Case | None = None
    _seen_statuses: list[int] = []

    def _select_case(self) -> _Case:
        name = cocotb.plusargs.get("zero_fill_fault")
        assert name in _CASES, f"+zero_fill_fault={name!r}; expected one of {sorted(_CASES)}"
        self.logger.info("CHK-CASE: zero fill fault case %s", name)
        return _CASES[name]

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        if self._case.erase_primary:
            mm.erase_slot(buf, "primary")
            assert mm.slot_is_erased(buf, "primary"), "primary slot is not fully erased"
        return buf

    async def _record_statuses(self) -> None:
        dut = cocotb.top
        last = None
        while True:
            await RisingEdge(dut.clk_i)
            status = (self.rd(dut.scratch_cold_probe_o) >> 32) & 0xFFFF_FFFF
            if status != last:
                last = status
                self._seen_statuses.append(status)

    def start_watchers(self, console: list[str]) -> None:
        self._seen_statuses = []
        cocotb.start_soon(self._record_statuses())

    async def run_scenario(self) -> None:
        self._case = self._select_case()
        self.required_markers = self._case.also_required + self._case.in_order
        self.forbidden_markers = _BASE_FORBIDDEN + self._case.forbidden
        await super().run_scenario()

    async def run_boot(self) -> None:
        # Set here, not in build_phase: the scoreboard's own build_phase runs later
        # and sets it back to True.
        self.sb.expect_fw_pass = False
        # Armed after bring-up, which returns every tb input to its idle default.
        cocotb.top.dma_fill_fault_sel_i.value = self._case.fault_sel
        try:
            await super().run_boot()
        finally:
            cocotb.top.dma_fill_fault_sel_i.value = 0

    def check_transport(self, console: list[str], flash) -> None:
        case = self._case
        fault_clocks = self.rd(cocotb.top.dma_fill_fault_count_o)
        assert fault_clocks > 0, (
            f"the zero-fill fault (dma_fill_fault_sel_i={case.fault_sel}) never fired: no "
            f"zero fill ran with its destination in the selected region. Console: {console}"
        )
        self.logger.info("CHK-FAULT-FIRED PASS: fault condition held for %d clocks", fault_clocks)

        at = 0
        for marker in case.in_order:
            hits = [i for i, line in enumerate(console) if i >= at and marker in line]
            assert hits, (
                f"{marker} missing, or not after the markers before it in {case.in_order}. "
                f"Console: {console}"
            )
            at = hits[0] + 1
        self.logger.info("CHK-MARKER-ORDER PASS: %s", ", ".join(case.in_order))

        for kind, name in case.statuses:
            want = mm.rom_status_word(kind, name)
            assert want in self._seen_statuses, (
                f"the ROM never reported {kind} {name} (0x{want:08x}); cold_scratch[1] went "
                f"through " + ", ".join(f"0x{s:08x}" for s in self._seen_statuses)
            )
            self.logger.info("CHK-STATUS PASS: %s %s (0x%08x)", kind, name, want)
