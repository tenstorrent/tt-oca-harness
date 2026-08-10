# SPDX-License-Identifier: Apache-2.0
"""smu_xtrig_ctm_remap_test - product-pin CTM remap.

Proves SMU glue on real TB ports (same class as clock-stop remap):

  1. xtrig_ctm_dst_req[7:0] -> dtp_xtrig_ctm_dst_req[9:2]; SMC[1:0] stay 0
  2. xtrig_ctm_dst_ack stays 0 (wire-OR / no CT peer — by construction)
  3. xtrig_ctm_src_ack[7:0] -> dtp_xtrig_ctm_src_ack[9:2]; ack[1:0] hardwired 0
  4. TB xtrig_ctm_src_req stays idle (0) while only ack is driven (no DTP peer)
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge

from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

DEST_PATS = (0x01, 0x80, 0xA5, 0x5A)
SRC_ACK_PATS = (0x01, 0x80, 0x3C)


def _u8(signal, name: str) -> int:
    val = signal.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val) & 0xFF


def _bits(signal, name: str) -> int:
    val = signal.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val)


@pyuvm.test()
class smu_xtrig_ctm_remap_test(smu_base_test):
    """CTM external remap via product pins only."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        await self.cfg.reset_done.wait()
        dut.xtrig_ctm_dst_req.value = 0
        dut.xtrig_ctm_src_ack.value = 0
        await ClockCycles(dut.clk_smu_i, 8)

        dtp_dst_req = dut.u_dut.dtp_xtrig_ctm_dst_req
        dtp_src_ack = dut.u_dut.dtp_xtrig_ctm_src_ack

        async def _settle() -> None:
            await RisingEdge(dut.clk_smu_i)
            await RisingEdge(dut.clk_smu_i)

        sb.expect_eq(
            "idle dst_ack",
            _u8(dut.xtrig_ctm_dst_ack, "xtrig_ctm_dst_ack"),
            0,
            evidence="XT_CTM_REMAP",
        )
        sb.expect_eq(
            "idle src_ack[1:0] hardwire",
            _bits(dtp_src_ack, "dtp_xtrig_ctm_src_ack") & 0x3,
            0,
        )

        for pat in DEST_PATS:
            dut.xtrig_ctm_dst_req.value = pat
            await _settle()
            dtp = _bits(dtp_dst_req, "dtp_xtrig_ctm_dst_req")
            sb.expect_eq(
                f"dst_req pat={pat:#x} -> DTP[9:2]",
                (dtp >> 2) & 0xFF,
                pat,
                evidence="XT_CTM_REMAP",
            )
            sb.expect_eq(f"dst_req pat={pat:#x} SMC[1:0] idle", dtp & 0x3, 0)
            sb.expect_eq(
                f"dst_req pat={pat:#x} TB ack still 0",
                _u8(dut.xtrig_ctm_dst_ack, "xtrig_ctm_dst_ack"),
                0,
            )
        dut.xtrig_ctm_dst_req.value = 0
        await _settle()

        for pat in SRC_ACK_PATS:
            dut.xtrig_ctm_src_ack.value = pat
            await _settle()
            ack = _bits(dtp_src_ack, "dtp_xtrig_ctm_src_ack")
            sb.expect_eq(
                f"src_ack pat={pat:#x} -> DTP[9:2]",
                (ack >> 2) & 0xFF,
                pat,
                evidence="XT_CTM_REMAP",
            )
            sb.expect_eq(f"src_ack pat={pat:#x} [1:0] hardwire 0", ack & 0x3, 0)
            # Independent idle expect (not a wire-identity vs hierarchical src_req).
            sb.expect_eq(
                f"src_req TB idle while ack-only (pat={pat:#x})",
                _u8(dut.xtrig_ctm_src_req, "xtrig_ctm_src_req"),
                0,
            )
        dut.xtrig_ctm_src_ack.value = 0
        await _settle()

        self.logger.info("smu_xtrig_ctm_remap_test: product-pin CTM remap OK")
