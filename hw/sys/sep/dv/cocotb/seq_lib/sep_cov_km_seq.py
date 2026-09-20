# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared helpers for the ``sep_cov_km_*`` code-coverage stimulus tests.

Stimulus only. Nothing here asserts a design contract. The waits are flow
control: they stop a run whose KM image never loaded from reporting a pass
off an empty console, which is the one failure mode these tests must keep.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from env.sep_axi_agent import SepAxiOp
from sep_reg_meta import sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_km_mailbox_seq import KM_MBOX_WRITE_DATA, KM_MBOX_WRITE_SEPARATOR
from seq_lib.sep_km_mem_smoke_seq import sep_km_release_seq

KM_MBOX_BASE = sym("KM_MAILBOX_SEP_REG_MAP_BASE_ADDR")

# Every km_rom_cov_*.S image reports completion as this byte in KM SRAM word0,
# which the tb exposes on ``km_sram_word0_o``. The low bits name the image.
KM_COV_MAGIC = 0xC0

DONE_KPV_WALK = 0x01
DONE_CSR = 0x02
DONE_TBVUART = 0x04
DONE_LOCKOUT_SRAM_EXEC = 0x08
DONE_LOCKOUT_ROM_FETCH = 0x0C
DONE_FAULT = 0x10
DONE_SOFT_RST_FIRST_BOOT = 0x20
DONE_SOFT_RST_SECOND_BOOT = 0x60
DONE_DRBG_TIMEOUT = 0x40
DONE_DRBG_PREFETCH = 0x80
DONE_MBOX_KM = 0x100


async def km_cov_release(test) -> None:
    """Release the KM out of software reset so its ROM image boots."""
    await test.start_seq(sep_km_release_seq("km_cov_release"))


async def km_cov_post_cfg(test, cfg_word: int) -> None:
    """Post one config word on the SEP-side KM mailbox.

    The images that take a config word block on it, so this call is also the
    ordering point between host-side register programming and the image.
    """
    wr_sep = SepAxiAccessSeq(
        "km_cov_sep",
        op=SepAxiOp.WRITE,
        addr=KM_MBOX_BASE + KM_MBOX_WRITE_SEPARATOR,
        wdata=1,
        size=2,
    )
    await test.start_seq(wr_sep)
    wr_data = SepAxiAccessSeq(
        "km_cov_cfg",
        op=SepAxiOp.WRITE,
        addr=KM_MBOX_BASE + KM_MBOX_WRITE_DATA,
        wdata=cfg_word,
        size=2,
    )
    await test.start_seq(wr_data)


def cfg_fold(cfg_word: int) -> int:
    """The eight-bit fold of the config word that an image echoes at [23:16]."""
    folded = cfg_word ^ (cfg_word >> 8) ^ (cfg_word >> 16) ^ (cfg_word >> 24)
    return folded & 0xFF


async def wait_km_cov_done(test, *, max_cycles: int = 200_000, settle_cycles: int = 0) -> int:
    """Wait for a km_rom_cov_* image to report completion, and return word0.

    A KM image that never boots -- a missing or unreadable ``+km_rom_hex``
    image, for instance -- leaves word0 without the magic and raises here.
    The returned value is logged by the caller, not graded.
    """
    dut = cocotb.top
    word = 0
    for _ in range(max_cycles):
        await RisingEdge(dut.clk_i)
        word = test.rd(dut.km_sram_word0_o)
        if (word >> 24) == KM_COV_MAGIC:
            break
    else:
        raise AssertionError(
            f"KM stimulus image never reported completion: km_sram_word0_o=0x{word:08x} "
            f"after {max_cycles} cycles (check +km_rom_hex resolved to a real image)"
        )
    if settle_cycles:
        await ClockCycles(dut.clk_i, settle_cycles)
        word = test.rd(dut.km_sram_word0_o)
    return word
