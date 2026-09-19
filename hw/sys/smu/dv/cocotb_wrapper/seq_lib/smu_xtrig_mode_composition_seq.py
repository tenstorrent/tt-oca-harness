# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_xtrig_mode_composition_test (SMU_104).

The per-internal-CT mode vector the SMU presents to the DTP is
Cfg.XTRIG_INT_CT_MODE in the SMU-exposed lanes concatenated with
SMC-reserved pulse-sync bits, declared as DTP_XTRIG_INT_CT_MODE in
hw/sys/smu/rtl/smu.sv. Reading that parameter back and comparing it against the
elaborated Cfg field, or against the +xtrig_int_ct_mode the same build was
elaborated with, is a drift check on the elaboration: both sides come from the
build, so no RTL defect can separate them. Those compares therefore carry no
evidence token.

The evidence is the live leg. Each external CTM lane is requested in turn and
the ack pins are sampled: port_table.adoc states the ack ports are "Unused in
pulse-sync mode (mode bit = 0)", so a lane whose mode bit is set must
acknowledge and hold, a pulse-sync lane must never assert, and the number of
lanes at which an ack was *observed* must come to the mode vector's population
count. A DTP that ignored the mode vector fails all three.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from seq_lib.smu_compose_helpers import (
    DTP_NUM_INT_CT,
    XTRIG_NUM_INT_CT,
    XTRIG_SMC_INT_CT_LANES,
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
            "mode bits in the SMC reservation presented to DTP are zero (pulse-sync)",
            dtp_mode & ((1 << XTRIG_SMC_INT_CT_LANES) - 1),
            0,
            evidence="CHK-SMU-XTRIG-MODE-S1",
        )
        cfg_fields = decode_cfg(sample(hier(smu, "Cfg"), "smu.Cfg"))
        sb.expect_eq(
            "elaborated Cfg.XTRIG_INT_CT_MODE drift against +xtrig_int_ct_mode",
            cfg_fields["XTRIG_INT_CT_MODE"],
            mode_contract,
        )
        sb.expect_eq(
            "mode bits above the SMC reservation presented to DTP are Cfg.XTRIG_INT_CT_MODE unmodified",
            dtp_mode >> XTRIG_SMC_INT_CT_LANES,
            cfg_fields["XTRIG_INT_CT_MODE"] & ((1 << XTRIG_NUM_INT_CT) - 1),
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
        # Counted from what was sampled on xtrig_ctm_dst_ack, not from the mode
        # vector the bench elaborated the DUT with: the aggregate below then
        # fails on a DTP that acknowledged the wrong set of lanes.
        observed_ack_lanes = 0
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
            if any(v for v in trace):
                observed_ack_lanes += 1
            dut.xtrig_ctm_dst_req.value = 0
            cleared = None
            for _ in range(ACK_CLEAR_BOUND):
                await RisingEdge(dut.clk_smu_i)
                cleared = sample(dut.xtrig_ctm_dst_ack, "xtrig_ctm_dst_ack")
                if cleared == 0:
                    break
            sb.expect_eq(f"lane {lane} dst_ack returns to idle", cleared, 0)
        sb.expect_eq(
            "lanes observed acknowledging equals the mode vector population count",
            observed_ack_lanes,
            bin(mode_contract).count("1"),
            evidence="CHK-SMU-XTRIG-MODE-S2",
        )
        # Bench-side: the elaborated mode vector has to contain both kinds of
        # lane or the two legs above have nothing to separate.
        sb.expect_true(
            "the elaborated mode vector has a handshake lane and a pulse-sync lane",
            0 < bin(mode_contract).count("1") < XTRIG_NUM_INT_CT,
        )
        self.log.info(
            "CTM lanes: %d observed acknowledging of %d requested, mode vector 0x%02x",
            observed_ack_lanes,
            XTRIG_NUM_INT_CT,
            mode_contract,
        )
