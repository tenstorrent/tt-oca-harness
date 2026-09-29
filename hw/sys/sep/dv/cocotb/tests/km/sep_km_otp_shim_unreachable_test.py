# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The KM CPU cannot reach the eFuse shim CSR port past the OTP MMR aperture.

no_cpu / +skip_fuse_sense / +km_rom_hex=km_rom_bus_err.parhex. RANDCFG: the
value the host programs into the shim register. Not ``rom_main``: only code on
the KM CPU can present a KM-side OTP address.

Contract. ``hw/ip/key_manager/regs/key_manager.rdl`` (OTP / eFuse Pass-Through)
says only the MAP, CTRL and MMR sub-regions are decoded and "efuse_shim_ctrl
is intentionally excluded (not in the AXIL path)". Its memory-map summary
says an unmapped offset inside a window answers SLVERR and an address outside
every window answers DECERR. The KM CPU observes either response only as the
sticky ``IRQ_STATUS.AXI_SLVERR`` / ``AXI_DECERR`` bits (``km_csr.rdl``).

The KM image loads from, then stores OTP_WR_VALUE to, the first word after the
0x100-byte OTP_EFUSE_MMR aperture. The host reads and writes the shim register
``EFUSE_BANK_INIT_TIME`` on its real path, the SEP-side
``SEP_EXTERNAL_EFUSE_SHIM_CTRL`` window, before and after.

  CHK-KM-SHIM-HOST-PATH   control: the host read of EFUSE_BANK_INIT_TIME is
                          OKAY at its RDL reset, and a seeded value written
                          there reads back.
  CHK-KM-DECERR-LIVE      control: a KM load from the Reserved ROM-growth row
                          sets AXI_DECERR, so the bit and the image's poll work.
  CHK-KM-OTP-SHIM-EXCLUDED
                          the KM load and the KM store each set AXI_SLVERR or
                          AXI_DECERR; the load does not return the shim
                          register value; the shim register still holds the
                          host value after the KM store.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import RegBlock
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_km_bus_err_seq import (
    IRQ_AXI_DECERR,
    IRQ_AXI_ERR,
    OTP_WR_VALUE,
    W_DEC_CLEAN,
    W_DEC_IRQ,
    W_OTP_RD_CLEAN,
    W_OTP_RD_DATA,
    W_OTP_RD_IRQ,
    W_OTP_WR_CLEAN,
    W_OTP_WR_IRQ,
    W_VROM_CLEAN,
    SepKmBusErr,
    irq_names,
)

_SHIM = RegBlock("SEP_EXTERNAL_EFUSE_SHIM_CTRL")
_SHIM_REG = "EFUSE_BANK_INIT_TIME"
_SHIM_ADDR = _SHIM.addr(_SHIM_REG)
_SHIM_RESET = _SHIM.reset(_SHIM_REG)
_SHIM_MASK = _SHIM.mask_all(_SHIM_REG)


@pyuvm.test()
class sep_km_otp_shim_unreachable_test(sep_base_test):
    """KM access past the OTP MMR aperture is refused and does not reach the shim."""

    required_evidence = (
        "CHK-KM-SHIM-HOST-PATH",
        "CHK-KM-DECERR-LIVE",
        "CHK-KM-OTP-SHIM-EXCLUDED",
    )

    async def _shim(self, op: SepAxiOp, wdata: int = 0) -> SepAxiAccessSeq:
        seq = SepAxiAccessSeq(
            f"shim_{op.value}", op=op, addr=_SHIM_ADDR, wdata=wdata, length=4, size=2
        )
        await self.start_seq(seq)
        assert not seq.timed_out and seq.resp_ok, (
            f"CHK-KM-SHIM-HOST-PATH FAIL: host {op.value} of {_SHIM_REG} "
            f"0x{_SHIM_ADDR:08x} resp={seq.resp_code} timed_out={seq.timed_out}, "
            "expected OKAY"
        )
        return seq

    def _host_value(self, rng: SepSeededRng) -> int:
        """A seeded shim value distinct from its reset and from the KM store."""
        while True:
            value = rng.randrange(0x100, 0x1_0000) & _SHIM_MASK
            if value not in (_SHIM_RESET, OTP_WR_VALUE & _SHIM_MASK):
                return value

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        host_value = self._host_value(SepSeededRng(seed))
        self.logger.info("km otp shim: seed=%d host_value=0x%08x", seed, host_value)
        await self.bring_up_no_cpu()

        at_reset = (await self._shim(SepAxiOp.READ)).rdata & _SHIM_MASK
        assert at_reset == _SHIM_RESET, (
            f"CHK-KM-SHIM-HOST-PATH FAIL: {_SHIM_REG} read 0x{at_reset:08x} before any "
            f"write, expected the RDL reset 0x{_SHIM_RESET:08x}"
        )
        await self._shim(SepAxiOp.WRITE, host_value)
        programmed = (await self._shim(SepAxiOp.READ)).rdata & _SHIM_MASK
        assert programmed == host_value, (
            f"CHK-KM-SHIM-HOST-PATH FAIL: {_SHIM_REG} read 0x{programmed:08x} after a "
            f"host write of 0x{host_value:08x}; the host path cannot program it, so "
            "the no-alias rows below would hold for the wrong reason"
        )
        self.logger.info(
            "CHK-KM-SHIM-HOST-PATH PASS: %s at 0x%08x read OKAY 0x%08x (RDL reset) and "
            "0x%08x after the host wrote it",
            _SHIM_REG,
            _SHIM_ADDR,
            at_reset,
            programmed,
        )

        img = SepKmBusErr(self)
        await img.release()
        await img.wait_pre_marker()
        words = img.dump(W_VROM_CLEAN + 1)

        img.require_clean(words, W_DEC_CLEAN, "the ROM-growth load", "CHK-KM-DECERR-LIVE")
        dec = words[W_DEC_IRQ]
        assert dec & IRQ_AXI_DECERR, (
            f"CHK-KM-DECERR-LIVE FAIL: IRQ_STATUS=0x{dec:08x} ({irq_names(dec)}) after a "
            "load from the Reserved ROM-growth row; AXI_DECERR did not set, so the "
            "refusal rows below cannot be graded"
        )
        self.logger.info(
            "CHK-KM-DECERR-LIVE PASS: load from the Reserved ROM-growth row set "
            "IRQ_STATUS.AXI_DECERR (IRQ_STATUS=0x%08x)",
            dec,
        )

        img.require_clean(words, W_OTP_RD_CLEAN, "the OTP load", "CHK-KM-OTP-SHIM-EXCLUDED")
        img.require_clean(words, W_OTP_WR_CLEAN, "the OTP store", "CHK-KM-OTP-SHIM-EXCLUDED")
        after = (await self._shim(SepAxiOp.READ)).rdata & _SHIM_MASK

        rd_irq, rd_data, wr_irq = words[W_OTP_RD_IRQ], words[W_OTP_RD_DATA], words[W_OTP_WR_IRQ]
        faults = []
        if not rd_irq & IRQ_AXI_ERR:
            faults.append(
                f"the KM load completed with no error (IRQ_STATUS=0x{rd_irq:08x}, "
                f"{irq_names(rd_irq)})"
            )
        if rd_data & _SHIM_MASK == host_value:
            faults.append(
                f"the KM load returned 0x{rd_data:08x}, the value the host wrote to {_SHIM_REG}"
            )
        if not wr_irq & IRQ_AXI_ERR:
            faults.append(
                f"the KM store completed with no error (IRQ_STATUS=0x{wr_irq:08x}, "
                f"{irq_names(wr_irq)})"
            )
        if after != host_value:
            faults.append(
                f"{_SHIM_REG} read 0x{after:08x} after the KM store of "
                f"0x{OTP_WR_VALUE:08x}, expected the host value 0x{host_value:08x}"
            )
        self.logger.info(
            "km otp shim: KM load data=0x%08x IRQ_STATUS=0x%08x; KM store "
            "IRQ_STATUS=0x%08x; %s after=0x%08x",
            rd_data,
            rd_irq,
            wr_irq,
            _SHIM_REG,
            after,
        )
        assert not faults, (
            "CHK-KM-OTP-SHIM-EXCLUDED FAIL: key_manager.rdl excludes efuse_shim_ctrl "
            "from the KM AXI-Lite path and makes an unmapped KM address answer "
            "SLVERR or DECERR, but a KM access past the OTP MMR aperture reached the "
            "shim: " + "; ".join(faults)
        )
        self.logger.info(
            "CHK-KM-OTP-SHIM-EXCLUDED PASS: the KM load and store past the MMR aperture "
            "were refused (%s, %s), the load did not return %s, and the register kept "
            "the host value 0x%08x",
            irq_names(rd_irq),
            irq_names(wr_irq),
            _SHIM_REG,
            after,
        )
