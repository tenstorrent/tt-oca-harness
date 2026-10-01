# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Host side of the KM CPU bus-error image (``tests/km_fw/km_rom_bus_err.S``).

The image makes each KM CPU access, copies raw words to KM SRAM, and grades
nothing. The word layout below is the one the image writes. The IRQ_STATUS
field masks come from the generated ``km_csr.h``.

Three leaves boot the same image and each grades its own rows:
``sep_km_rom_write_err_test``, ``sep_km_otp_shim_unreachable_test`` and
``sep_km_vrom_decerr_test``. The virtual ROM load is the last access, so a
leaf that grades an earlier row does not depend on it.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from sep_reg_meta import CHeaderRegBlock, ip_c_header

from seq_lib.sep_km_mem_smoke_seq import sep_km_release_seq

KM_CSR = CHeaderRegBlock("KM_CSR", ip_c_header("key_manager").with_name("km_csr.h"))
_IRQ = KM_CSR.fields("IRQ_STATUS_REG")
IRQ_AXI_SLVERR = _IRQ["AXI_SLVERR"]["bm"]
IRQ_AXI_DECERR = _IRQ["AXI_DECERR"]["bm"]
IRQ_ROM_WRITE_ERR = _IRQ["ROM_WRITE_ERR"]["bm"]
IRQ_AXI_ERR = IRQ_AXI_SLVERR | IRQ_AXI_DECERR
IRQ_WATCHED = IRQ_AXI_ERR | IRQ_ROM_WRITE_ERR

WORD_BITS = 32
WORD_MASK = (1 << WORD_BITS) - 1

# KM SRAM word indices, from the KM SRAM base. km_rom_bus_err.S holds the same
# list as byte offsets.
W_MARKER = 0
W_SLV_CLEAN = 1
W_SLV_IRQ = 2
W_DEC_CLEAN = 3
W_DEC_IRQ = 4
W_ROM_BEFORE = 5
W_ROM_CLEAN = 6
W_ROM_IRQ = 7
W_ROM_AFTER = 8
W_OTP_RD_CLEAN = 9
W_OTP_RD_DATA = 10
W_OTP_RD_IRQ = 11
W_OTP_WR_CLEAN = 12
W_OTP_WR_IRQ = 13
W_OTP_OK_CLEAN = 14
W_OTP_OK_IRQ = 15
W_VROM_CLEAN = 16
W_VROM_DATA = 17
W_VROM_IRQ = 18
DUMP_WORDS = W_VROM_IRQ + 1

# Stimulus constants the image carries. They are what the image stores, not
# expected DUT results.
PRE_MARKER = 0xB0E1_A000
POST_MARKER = 0xB0E1_A0FF
ROM_PROBE_WORD = 0x5EC0_D0D5
OTP_WR_VALUE = 0x0000_0A5C

_MAX_PRE_CYCLES = 20_000


def irq_names(value: int) -> str:
    """The watched IRQ_STATUS bits set in ``value``, for a failure message."""
    names = [
        name
        for name, bit in (
            ("AXI_SLVERR", IRQ_AXI_SLVERR),
            ("AXI_DECERR", IRQ_AXI_DECERR),
            ("ROM_WRITE_ERR", IRQ_ROM_WRITE_ERR),
        )
        if value & bit
    ]
    return "|".join(names) or "none"


class SepKmBusErr:
    """Release the KM CPU into the image and read back its dump."""

    def __init__(self, test) -> None:
        self.test = test
        self.pre_cycle = 0

    async def release(self) -> None:
        await self.test.start_seq(sep_km_release_seq("km_bus_err_release"))

    async def wait_pre_marker(self) -> None:
        """Wait for PRE_MARKER in KM SRAM word 0: every dump word is written.

        The word is unknown before the image's first store to it; the poll
        tolerates that.
        """
        dut = cocotb.top
        word = 0
        for cycle in range(1, _MAX_PRE_CYCLES + 1):
            await RisingEdge(dut.clk_i)
            word = self.test.rd(dut.km_sram_word0_o, allow_unknown=True)
            if word in (PRE_MARKER, POST_MARKER):
                self.pre_cycle = cycle
                return
        raise AssertionError(
            f"CHK-KM-BUS-ERR-LIVE FAIL: KM SRAM word0=0x{word:08x} after "
            f"{_MAX_PRE_CYCLES} cycles, expected 0x{PRE_MARKER:08x}; the image did "
            f"not reach its last dump (KM ROM fetches="
            f"{self.test.rd(dut.km_rom_req_count_o)})"
        )

    def dump(self, count: int) -> list[int]:
        """KM SRAM words ``0..count-1``, each required fully known."""
        probe = cocotb.top.km_sram_probe_o
        words = len(probe) // WORD_BITS
        assert count <= words, (
            f"test bug: km_sram_probe_o holds {words} words, the leaf reads {count}"
        )
        value = self.test.rd_known(probe, (1 << (WORD_BITS * count)) - 1)
        return [(value >> (WORD_BITS * i)) & WORD_MASK for i in range(count)]

    def require_clean(self, words: list[int], idx: int, what: str, chk: str) -> None:
        """The image cleared the watched IRQ bits before ``what``; they read 0."""
        value = words[idx]
        assert value & IRQ_WATCHED == 0, (
            f"{chk} FAIL: IRQ_STATUS=0x{value:08x} ({irq_names(value)}) after the "
            f"write-1-to-clear before {what}; the sticky bits did not start clear, "
            "so the check after it would not be about this access"
        )
