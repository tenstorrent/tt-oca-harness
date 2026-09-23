# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_xtrig_ctm_remap_test - product-pin CTM remap.

Proves SMU glue on real TB ports (same class as clock-stop remap):

  1. xtrig_ctm_dst_req[7:0] -> dtp_xtrig_ctm_dst_req[9:2]; SMC[1:0] stay 0
  2. xtrig_ctm_dst_ack[7] follows dst_req[7] within a settle window and holds:
     lane 7 is the one lane the TB configures for req/ack handshaking
     (XTRIG_INT_CT_MODE = 8'h80). The integrator guide says a mode-0 lane's
     ack is "unused" and pins no level for it, so lanes 0-6 are recorded, not
     compared
  3. xtrig_ctm_src_ack[7:0] -> dtp_xtrig_ctm_src_ack[9:2]; ack[1:0] hardwired 0
  4. TB xtrig_ctm_src_req stays idle (0) while only ack is driven (no DTP peer)
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from seq_lib.smu_tb_pins import smu_scope
from smu_base_test import smu_base_test

DEST_PATS = (0x01, 0x80, 0xA5, 0x5A)
SRC_ACK_PATS = (0x01, 0x80, 0x3C)

# Lane 7 is the only lane the TB configures for req/ack handshaking (both TB
# tops set XTRIG_INT_CT_MODE = 8'h80). The integrator guide (SMU cross-trigger
# port table) says that when a mode bit is 0 the lane is pulse-synchronised and
# its ack is unused; it pins no level for an unused ack, so only lane 7's ack
# is compared and lanes 0-6 are logged as observed.
#
# The ack is a synchronised handshake, not a combinational remap, so the
# property is settle-and-hold: within ACK_SETTLE cycles ack[7] must reach
# req[7] and must stay there for the rest of the window. ACK_SETTLE is a wait
# bound, not an expectation.
ACK_SETTLE = 4
ACK_WINDOW = 12
HANDSHAKE_LANE = 0x80


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

    use_shared_env = True

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        await self.cfg.reset_done.wait()
        dut.xtrig_ctm_dst_req.value = 0
        dut.xtrig_ctm_src_ack.value = 0
        await ClockCycles(dut.clk_smu_i, 8)

        dtp_dst_req = smu_scope(dut).dtp_xtrig_ctm_dst_req
        dtp_src_ack = smu_scope(dut).dtp_xtrig_ctm_src_ack

        async def _settle() -> None:
            await RisingEdge(dut.clk_smu_i)
            await RisingEdge(dut.clk_smu_i)

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

            want_ack7 = pat & HANDSHAKE_LANE
            trace = []
            for _ in range(ACK_WINDOW):
                trace.append(_u8(dut.xtrig_ctm_dst_ack, "xtrig_ctm_dst_ack"))
                await RisingEdge(dut.clk_smu_i)
            held = [v & HANDSHAKE_LANE for v in trace[ACK_SETTLE:]]
            # Report the first offender rather than a bare mismatch, so a
            # regression says which cycle broke the hold.
            bad = next((v for v in held if v != want_ack7), want_ack7)
            sb.expect_eq(
                f"dst_req pat={pat:#x} ack[7] settles to {want_ack7 >> 7} within "
                f"{ACK_SETTLE} cycles and holds",
                bad,
                want_ack7,
                evidence="XT_CTM_REMAP",
            )
            self.logger.info(
                "dst_req pat=%#x: ack trace %s (lanes 0-6 observed only: the guide leaves a "
                "pulse-synchronised lane's ack unused and pins no level for it)",
                pat,
                [f"{v:#04x}" for v in trace],
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
            sb.expect_eq(
                f"src_ack pat={pat:#x} TB src_req idle",
                _u8(dut.xtrig_ctm_src_req, "xtrig_ctm_src_req"),
                0,
            )
        dut.xtrig_ctm_src_ack.value = 0
        await _settle()

        self.logger.info("smu_xtrig_ctm_remap_test: product-pin CTM remap OK")
