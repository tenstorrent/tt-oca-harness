# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Host side of the KM DRBG-sampler image (``tests/km_fw/km_rom_drbg_sampler.S``).

The image makes each sampler access, copies raw words to KM SRAM, and grades
nothing. The word layout, the markers and ``TIMEOUT_CYCLES`` below are the ones
the image carries. The sampler and KMCSR field masks and resets come from the
generated ``km_drbg_sampler.h`` and ``km_csr.h``.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from sep_reg_meta import CHeaderRegBlock, ip_c_header

KM_CSR = CHeaderRegBlock("KM_CSR", ip_c_header("key_manager").with_name("km_csr.h"))
KM_SMP = CHeaderRegBlock(
    "KM_DRBG_SAMPLER", ip_c_header("key_manager").with_name("km_drbg_sampler.h")
)

_IRQ = KM_CSR.fields("IRQ_STATUS_REG")
IRQ_AXI_SLVERR = _IRQ["AXI_SLVERR"]["bm"]
IRQ_AXI_DECERR = _IRQ["AXI_DECERR"]["bm"]
IRQ_DRBG_ERR = _IRQ["DRBG_ERR"]["bm"]
IRQ_WATCHED = IRQ_AXI_SLVERR | IRQ_AXI_DECERR | IRQ_DRBG_ERR
COLD_BOOT_DONE = KM_CSR.fields("BOOT_STATUS_REG")["COLD_BOOT_DONE"]["bm"]

CFG_RESET = KM_SMP.reset("CFG_REG")
STATUS_RESET = KM_SMP.reset("STATUS_REG")

WORD_BITS = 32
WORD_MASK = (1 << WORD_BITS) - 1

# KM SRAM word indices, from the KM SRAM base. km_rom_drbg_sampler.S holds the
# same list as byte offsets.
W_MARKER = 0
W_T_BOOT = 1
W_T_STATUS_PRE = 2
W_T_CFG = 3
W_T_CLEAN = 4
W_T_DATA = 5
W_T_IRQ = 6
W_T_STATUS = 7
W_R_CFG = 8
W_R_STATUS = 9
W_R_DATA = 10
W_W_BOOT = 11
W_W_CFG = 12
W_W_STATUS = 13
W_W_IRQ = 14
W_P_CFG = 15
W_P_STATUS_PRE = 16
W_P_CLEAN = 17
W_P_DATA = 18
W_P_IRQ = 19
W_P_STATUS = 20
DUMP_WORDS = W_P_STATUS + 1

# Stimulus constants the image carries. They are what the image stores or
# programs, not expected DUT results.
MK_BLOCK = 0xD5A7_0001
MK_R_DONE = 0xD5A7_0002
MK_WARM = 0xD5A7_0003
MK_DONE = 0xD5A7_0004
TIMEOUT_CYCLES = 40


def field(reg: str, name: str, value: int) -> int:
    """Field ``name`` of sampler register ``reg`` extracted from ``value``."""
    meta = KM_SMP.fields(reg)[name]
    return (value & meta["bm"]) >> meta["bp"]


def cfg_value(**fields: int) -> int:
    """A CFG value: named fields as given, the rest at their RDL reset."""
    return KM_SMP.value("CFG_REG", **fields)


def irq_names(value: int) -> str:
    """The watched IRQ_STATUS bits set in ``value``, for a log or failure message."""
    names = [
        name
        for name, bit in (
            ("AXI_SLVERR", IRQ_AXI_SLVERR),
            ("AXI_DECERR", IRQ_AXI_DECERR),
            ("DRBG_ERR", IRQ_DRBG_ERR),
        )
        if value & bit
    ]
    return "|".join(names) or "none"


def status_str(value: int) -> str:
    """STATUS decoded into its fields, for a log or failure message."""
    return " ".join(
        f"{name}={field('STATUS_REG', name, value)}"
        for name in (
            "DRBG_READY",
            "PREFETCHED",
            "TIMEOUT_ERR",
            "STREAM_ERR",
            "COUNT_BAD",
            "COUNT_GOOD",
        )
    )


class SepKmTreadyMonitor:
    """Record every run of cycles with the KM entropy TREADY high.

    ``km_entropy_tready_o`` is the TREADY the DRBG sampler drives on the
    EDN->KM AXI-Stream. Each run is ``[start_cycle, length, handshakes]``; the
    last run is still open while TREADY is high. The monitor starts after
    reset, so every sample must be known: ``xz`` counts the cycles with an X/Z
    TREADY, or an X/Z TVALID while TREADY is not low. Such a cycle opens no run
    and adds no handshake, so each checker fails on ``take_xz()``, the X/Z
    cycles since the previous checker took them.
    """

    def __init__(self, test) -> None:
        self.test = test
        self.cycle = 0
        self.runs: list[list[int]] = []
        self.high = False
        self.xz = 0
        self._xz_taken = 0
        self._task = None

    def take_xz(self) -> int:
        """X/Z cycles since the previous call: the window of the calling checker."""
        n = self.xz - self._xz_taken
        self._xz_taken = self.xz
        return n

    @staticmethod
    def _bit(sig) -> int | None:
        """Bit 0 of ``sig``, or None when it is not 0 or 1."""
        value = sig.value
        if isinstance(value, int):
            return int(value) & 1
        bits = getattr(value, "binstr", None)
        if bits is None:
            bits = str(value)
        c = bits.strip()[-1:]
        return {"0": 0, "1": 1}.get(c)

    def start(self) -> None:
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.kill()
            self._task = None

    async def _run(self) -> None:
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            self.cycle += 1
            ready = self._bit(dut.km_entropy_tready_o)
            valid = self._bit(dut.km_entropy_tvalid_o) if ready != 0 else 0
            if ready is None or valid is None:
                self.xz += 1
                ready = valid = 0
            if ready and not self.high:
                self.runs.append([self.cycle, 0, 0])
            if ready:
                self.runs[-1][1] += 1
                self.runs[-1][2] += valid
            self.high = bool(ready)
