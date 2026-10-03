# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A KM CPU store to KM ROM is dropped and reported as ROM_WRITE_ERR alone.

no_cpu / +skip_fuse_sense / +km_rom_hex=km_rom_bus_err.parhex. Not
``rom_main``: only code on the KM CPU can store to the KM ROM.

Contract. ``hw/ip/key_manager/regs/key_manager.rdl`` (memory-map Access Notes)
says the KM ROM is read-only and is accessed through the PicoRV32 native
memory interface, not AXI-Lite: "A write completes with no error response,
leaves the ROM unchanged and sets KMCSR IRQ_STATUS.ROM_WRITE_ERR". The KM CPU
observes an AXI error response only as the sticky ``IRQ_STATUS.AXI_SLVERR`` /
``AXI_DECERR`` bits (``km_csr.rdl``), so a ROM write leaves both clear.

  CHK-KM-SLVERR-LIVE          control: a store past the KPV register map sets
                              AXI_SLVERR, so the bit and the image's poll work.
  CHK-KM-DECERR-LIVE          control: a load from the Reserved ROM-growth row
                              sets AXI_DECERR, so that bit sets on an erroring
                              access too.
  CHK-KM-ROM-UNCHANGED        the ROM word reads ROM_PROBE_WORD before the
                              store and after it.
  CHK-KM-ROM-WRITE-ERR        the store sets IRQ_STATUS.ROM_WRITE_ERR.
  CHK-KM-ROM-WRITE-NO-AXI-ERR the store leaves IRQ_STATUS.AXI_SLVERR and
                              AXI_DECERR clear.

Each row starts from a write-1-to-clear whose readback must show the watched
bits clear, so a bit that a row reports belongs to that row's access.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_km_bus_err_seq import (
    IRQ_AXI_DECERR,
    IRQ_AXI_ERR,
    IRQ_AXI_SLVERR,
    IRQ_ROM_WRITE_ERR,
    ROM_PROBE_WORD,
    W_DEC_CLEAN,
    W_DEC_IRQ,
    W_ROM_AFTER,
    W_ROM_BEFORE,
    W_ROM_CLEAN,
    W_ROM_IRQ,
    W_SLV_CLEAN,
    W_SLV_IRQ,
    W_VROM_CLEAN,
    SepKmBusErr,
    irq_names,
)


@pyuvm.test()
class sep_km_rom_write_err_test(sep_base_test):
    """KM ROM store: content unchanged, ROM_WRITE_ERR set, no AXI error bit."""

    required_evidence = (
        "CHK-KM-SLVERR-LIVE",
        "CHK-KM-DECERR-LIVE",
        "CHK-KM-ROM-UNCHANGED",
        "CHK-KM-ROM-WRITE-ERR",
        "CHK-KM-ROM-WRITE-NO-AXI-ERR",
    )

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        img = SepKmBusErr(self)
        await img.release()
        await img.wait_pre_marker()
        words = img.dump(W_VROM_CLEAN + 1)

        img.require_clean(words, W_SLV_CLEAN, "the KPV store", "CHK-KM-SLVERR-LIVE")
        slv = words[W_SLV_IRQ]
        assert slv & IRQ_AXI_SLVERR, (
            f"CHK-KM-SLVERR-LIVE FAIL: IRQ_STATUS=0x{slv:08x} ({irq_names(slv)}) after "
            "a store past the KPV register map; AXI_SLVERR did not set, so the "
            "ROM-write row below cannot be graded"
        )
        self.logger.info(
            "CHK-KM-SLVERR-LIVE PASS: store past KM_KPV_SIZE set IRQ_STATUS.AXI_SLVERR "
            "(IRQ_STATUS=0x%08x) and the image ran on",
            slv,
        )

        img.require_clean(words, W_DEC_CLEAN, "the ROM-growth load", "CHK-KM-DECERR-LIVE")
        dec = words[W_DEC_IRQ]
        assert dec & IRQ_AXI_DECERR, (
            f"CHK-KM-DECERR-LIVE FAIL: IRQ_STATUS=0x{dec:08x} ({irq_names(dec)}) after a "
            "load from the Reserved ROM-growth row; AXI_DECERR did not set, so a clear "
            "AXI_DECERR on the ROM-write row below is not evidence"
        )
        self.logger.info(
            "CHK-KM-DECERR-LIVE PASS: load from the Reserved ROM-growth row set "
            "IRQ_STATUS.AXI_DECERR (IRQ_STATUS=0x%08x)",
            dec,
        )

        img.require_clean(words, W_ROM_CLEAN, "the ROM store", "CHK-KM-ROM-WRITE-ERR")
        before, after = words[W_ROM_BEFORE], words[W_ROM_AFTER]
        assert before == ROM_PROBE_WORD, (
            f"CHK-KM-ROM-UNCHANGED FAIL: the ROM probe word read 0x{before:08x} before "
            f"the store, expected the image constant 0x{ROM_PROBE_WORD:08x}"
        )
        assert after == ROM_PROBE_WORD, (
            f"CHK-KM-ROM-UNCHANGED FAIL: the ROM probe word read 0x{after:08x} after "
            f"a store of its complement, expected 0x{ROM_PROBE_WORD:08x}; the ROM "
            "accepted a write"
        )
        self.logger.info(
            "CHK-KM-ROM-UNCHANGED PASS: ROM word read 0x%08x before and after a store of 0x%08x",
            after,
            ROM_PROBE_WORD ^ 0xFFFF_FFFF,
        )

        rom_irq = words[W_ROM_IRQ]
        assert rom_irq & IRQ_ROM_WRITE_ERR, (
            f"CHK-KM-ROM-WRITE-ERR FAIL: IRQ_STATUS=0x{rom_irq:08x} "
            f"({irq_names(rom_irq)}) after a KM ROM store; ROM_WRITE_ERR did not set"
        )
        self.logger.info(
            "CHK-KM-ROM-WRITE-ERR PASS: KM ROM store set IRQ_STATUS.ROM_WRITE_ERR "
            "(IRQ_STATUS=0x%08x)",
            rom_irq,
        )

        assert rom_irq & IRQ_AXI_ERR == 0, (
            f"CHK-KM-ROM-WRITE-NO-AXI-ERR FAIL: IRQ_STATUS=0x{rom_irq:08x} "
            f"({irq_names(rom_irq)}) after a KM ROM store; key_manager.rdl says a ROM "
            "write completes with no error response and is reported only as "
            "ROM_WRITE_ERR, but an AXI error bit set"
        )
        self.logger.info(
            "CHK-KM-ROM-WRITE-NO-AXI-ERR PASS: KM ROM store left IRQ_STATUS.AXI_SLVERR "
            "and AXI_DECERR clear (IRQ_STATUS=0x%08x)",
            rom_irq,
        )
