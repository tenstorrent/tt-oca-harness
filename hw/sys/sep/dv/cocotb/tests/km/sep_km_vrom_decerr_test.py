# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A KM CPU load from the testbench virtual ROM window completes with DECERR.

no_cpu / +skip_fuse_sense / +km_rom_hex=km_rom_bus_err.parhex. Not
``rom_main``: only code on the KM CPU can present a KM-side address.

Contract. The memory-map summary in ``hw/ip/key_manager/regs/key_manager.rdl``
lists every KM CPU window and ends with "Every other address | Reserved/Unmapped
| DECERR". The virtual ROM base 0x1000_0000
(``hw/ip/key_manager/doc/architecture.adoc``) is in no listed window, so a
load from it must complete and answer DECERR. The KM CPU observes DECERR only
as the sticky ``IRQ_STATUS.AXI_DECERR`` bit (``km_csr.rdl``).

The image stores PRE_MARKER to KM SRAM word 0 just before the load and
POST_MARKER just after the load, the data store and a bounded IRQ_STATUS poll.

  CHK-KM-DECERR-LIVE      control: a KM load from the Reserved ROM-growth row
                          sets AXI_DECERR, so the bit and the image's poll work.
  CHK-KM-VROM-PRE         the image reached the load (PRE_MARKER), with the
                          watched IRQ bits clear just before it.
  CHK-KM-VROM-DECERR      POST_MARKER appears within _POST_BOUND cycles of
                          PRE_MARKER, and the load set IRQ_STATUS.AXI_DECERR.

The bound is a completion requirement, not a pass on expiry: the claim is that
the load completes, and CHK-KM-VROM-PRE with CHK-KM-DECERR-LIVE shows the image
alive and an erroring load completing on the same bus. The host logs the cycles
the image took from release to PRE_MARKER for scale.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from sep_base_test import sep_base_test
from seq_lib.sep_km_bus_err_seq import (
    IRQ_AXI_DECERR,
    POST_MARKER,
    PRE_MARKER,
    W_DEC_CLEAN,
    W_DEC_IRQ,
    W_VROM_CLEAN,
    W_VROM_DATA,
    W_VROM_IRQ,
    SepKmBusErr,
    irq_names,
)

# The image reaches PRE_MARKER through five error-path accesses and their
# polls; this bound is many times the time one such access takes. The host logs
# the measured release-to-PRE time next to it.
_POST_BOUND = 5_000


@pyuvm.test()
class sep_km_vrom_decerr_test(sep_base_test):
    """KM load from the virtual ROM window: completes, IRQ_STATUS.AXI_DECERR set."""

    required_evidence = (
        "CHK-KM-DECERR-LIVE",
        "CHK-KM-VROM-PRE",
        "CHK-KM-VROM-DECERR",
    )

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        img = SepKmBusErr(self)
        await img.release()
        await img.wait_pre_marker()
        words = img.dump(W_VROM_CLEAN + 1)

        img.require_clean(words, W_DEC_CLEAN, "the ROM-growth load", "CHK-KM-DECERR-LIVE")
        dec = words[W_DEC_IRQ]
        assert dec & IRQ_AXI_DECERR, (
            f"CHK-KM-DECERR-LIVE FAIL: IRQ_STATUS=0x{dec:08x} ({irq_names(dec)}) after a "
            "load from the Reserved ROM-growth row; AXI_DECERR did not set, so the "
            "virtual ROM row cannot be graded"
        )
        self.logger.info(
            "CHK-KM-DECERR-LIVE PASS: load from the Reserved ROM-growth row set "
            "IRQ_STATUS.AXI_DECERR (IRQ_STATUS=0x%08x)",
            dec,
        )

        img.require_clean(words, W_VROM_CLEAN, "the virtual ROM load", "CHK-KM-VROM-PRE")
        self.logger.info(
            "CHK-KM-VROM-PRE PASS: the image stored PRE_MARKER 0x%08x %d cycles after "
            "release, with IRQ_STATUS clear just before the virtual ROM load",
            PRE_MARKER,
            img.pre_cycle,
        )

        dut = cocotb.top
        word0 = 0
        waited = 0
        for waited in range(1, _POST_BOUND + 1):
            word0 = self.rd(dut.km_sram_word0_o)
            if word0 == POST_MARKER:
                break
            await RisingEdge(dut.clk_i)
        assert word0 == POST_MARKER, (
            f"CHK-KM-VROM-DECERR FAIL: KM SRAM word0=0x{word0:08x} {_POST_BOUND} cycles "
            f"after PRE_MARKER; the KM load from the virtual ROM base 0x1000_0000 did not "
            "complete. key_manager.rdl maps every address outside its listed windows "
            f"to DECERR (image reached PRE_MARKER {img.pre_cycle} cycles after release)"
        )
        vrom = img.dump(W_VROM_IRQ + 1)
        irq = vrom[W_VROM_IRQ]
        assert irq & IRQ_AXI_DECERR, (
            f"CHK-KM-VROM-DECERR FAIL: the virtual ROM load completed with "
            f"IRQ_STATUS=0x{irq:08x} ({irq_names(irq)}) and data 0x{vrom[W_VROM_DATA]:08x}; "
            "key_manager.rdl maps it to DECERR, and AXI_DECERR did not set"
        )
        self.logger.info(
            "CHK-KM-VROM-DECERR PASS: the virtual ROM load completed %d cycles after "
            "PRE_MARKER and set IRQ_STATUS.AXI_DECERR (IRQ_STATUS=0x%08x)",
            waited,
            irq,
        )
