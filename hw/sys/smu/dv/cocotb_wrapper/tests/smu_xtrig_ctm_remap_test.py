# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_xtrig_ctm_remap_test - product-pin CTM remap.

Proves SMU glue on real TB ports (same class as clock-stop remap):

  1. xtrig_ctm_dst_req[7:0] -> dtp_xtrig_ctm_dst_req[9:2]; SMC[1:0] stay 0
  2. xtrig_ctm_dst_ack is held at 0 across a window on pulse-sync lanes and
     acknowledges lane 7 within that window, whose nonzero mode bit exercises
     the configured-mode packing
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

# Lane 7 is the only lane the TB configures point-to-point (both TB tops set
# XTRIG_INT_CT_MODE = 8'h80); the wire-OR lanes tie ctm_dst_ack_o to 0 in the
# RTL, so only lane 7 has an ack that moves at all.
#
# That ack is not combinational the way the req remap is: it crosses
# cross_trigger_port's prim_flop_2sync and then the handshake FSM's own
# ct_ack_out_q, three cycles in both directions -- rising when lane 7's req
# asserts and falling when it deasserts -- so a single sample at a two-cycle
# settle reads the pre-transition value.
#
# So the property is a settle-and-hold: within ACK_SETTLE cycles the ack must
# reach (pat & 0x80), and it must stay there for the rest of the window.
ACK_SETTLE = 4
ACK_WINDOW = 12


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

            want_ack = pat & 0x80
            trace = []
            for _ in range(ACK_WINDOW):
                trace.append(_u8(dut.xtrig_ctm_dst_ack, "xtrig_ctm_dst_ack"))
                await RisingEdge(dut.clk_smu_i)
            held = trace[ACK_SETTLE:]
            # Report the first offender rather than a bare mismatch, so a
            # regression says which cycle broke the hold.
            bad = next((v for v in held if v != want_ack), want_ack)
            sb.expect_eq(
                f"dst_req pat={pat:#x} ack settles to {want_ack:#04x} within "
                f"{ACK_SETTLE} cycles and holds",
                bad,
                want_ack,
                evidence="XT_CTM_REMAP",
            )
            self.logger.info(
                "dst_req pat=%#x: ack trace %s",
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
