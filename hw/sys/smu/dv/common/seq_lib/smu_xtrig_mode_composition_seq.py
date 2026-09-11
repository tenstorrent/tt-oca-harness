# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_xtrig_mode_composition_test (SMU_104).

The per-internal-CT mode vector the SMU presents to the DTP is
{Cfg.XTRIG_INT_CT_MODE, 2'b00}: read on the DTP instance parameter, tied back
to the elaborated Cfg field and to the +xtrig_int_ct_mode contract, and then
exercised lane by lane on the external CTM pins, where a lane whose mode bit is
set acknowledges a destination request and a pulse-sync lane never does.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from seq_lib.smu_compose_helpers import (
    DTP_NUM_INT_CT,
    XTRIG_NUM_INT_CT,
    bit_width,
    decode_cfg,
    hier,
    parse_plusarg_int,
    sample,
)
from seq_lib.smu_tb_pins import smu_scope

ACK_SETTLE = 4
ACK_HOLD = 8
ACK_CLEAR_BOUND = 16


class smu_xtrig_mode_composition_seq:
    """Mode vector concatenation into DTP, decoded and exercised."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger
        self.sb = test.env.scoreboard

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        smu = smu_scope(dut)
        mode_contract = parse_plusarg_int("xtrig_int_ct_mode")
        await self.test.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 8)

        smu_vec = hier(smu, "DTP_XTRIG_INT_CT_MODE")
        dtp_vec = hier(smu, "u_dtp.XTRIG_INT_CT_MODE")
        sb.expect_eq(
            "mode vector width at the DTP",
            bit_width(dtp_vec, "u_dtp.XTRIG_INT_CT_MODE"),
            DTP_NUM_INT_CT,
        )
        dtp_mode = sample(dtp_vec, "u_dtp.XTRIG_INT_CT_MODE")
        sb.expect_eq(
            "DTP receives the vector the SMU concatenates",
            dtp_mode,
            sample(smu_vec, "DTP_XTRIG_INT_CT_MODE"),
        )
        sb.expect_eq(
            "mode bits [1:0] presented to DTP are zero (SMC pulse-sync)",
            dtp_mode & 0x3,
            0,
            evidence="CHK-SMU-XTRIG-MODE-S1",
        )
        cfg_fields = decode_cfg(sample(hier(smu, "Cfg"), "smu.Cfg"))
        sb.expect_eq(
            "elaborated Cfg.XTRIG_INT_CT_MODE matches the +xtrig_int_ct_mode contract",
            cfg_fields["XTRIG_INT_CT_MODE"],
            mode_contract,
        )
        sb.expect_eq(
            "mode bits [9:2] presented to DTP are Cfg.XTRIG_INT_CT_MODE unmodified",
            dtp_mode >> 2,
            cfg_fields["XTRIG_INT_CT_MODE"],
            evidence="CHK-SMU-XTRIG-MODE-S2",
        )
        self.log.info("DTP mode vector 0x%03x = {0x%02x, 2'b00}", dtp_mode, mode_contract)

        # Live: a destination request on an external lane is acknowledged only
        # when that lane's mode bit is set.
        dut.xtrig_ctm_dst_req.value = 0
        dut.xtrig_ctm_src_ack.value = 0
        await ClockCycles(dut.clk_smu_i, ACK_SETTLE)
        sb.expect_eq(
            "dst_ack idle before stimulus",
            sample(dut.xtrig_ctm_dst_ack, "xtrig_ctm_dst_ack"),
            0,
        )
        acked_lanes = 0
        for lane in range(XTRIG_NUM_INT_CT):
            want_ack = (1 << lane) if (mode_contract >> lane) & 1 else 0
            dut.xtrig_ctm_dst_req.value = 1 << lane
            await ClockCycles(dut.clk_smu_i, ACK_SETTLE)
            trace = []
            for _ in range(ACK_HOLD):
                await RisingEdge(dut.clk_smu_i)
                trace.append(sample(dut.xtrig_ctm_dst_ack, "xtrig_ctm_dst_ack"))
            bad = next((v for v in trace if v != want_ack), want_ack)
            token = "CHK-SMU-XTRIG-MODE-S2" if want_ack else "CHK-SMU-XTRIG-MODE-S1"
            sb.expect_eq(
                f"lane {lane} (mode bit {(mode_contract >> lane) & 1}) dst_ack holds {want_ack:#04x}",
                bad,
                want_ack,
                evidence=token,
            )
            if want_ack:
                acked_lanes += 1
            dut.xtrig_ctm_dst_req.value = 0
            cleared = None
            for _ in range(ACK_CLEAR_BOUND):
                await RisingEdge(dut.clk_smu_i)
                cleared = sample(dut.xtrig_ctm_dst_ack, "xtrig_ctm_dst_ack")
                if cleared == 0:
                    break
            sb.expect_eq(f"lane {lane} dst_ack returns to idle", cleared, 0)
        sb.expect_eq(
            "handshake-mode lanes exercised",
            acked_lanes,
            bin(mode_contract).count("1"),
            evidence="CHK-SMU-XTRIG-MODE-S2",
        )
        sb.expect_true(
            "the contract exercises both a handshake lane and a pulse-sync lane",
            0 < acked_lanes < XTRIG_NUM_INT_CT,
        )
