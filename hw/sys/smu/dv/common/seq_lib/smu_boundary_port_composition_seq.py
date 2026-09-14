# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_boundary_port_composition_test (SMU_101).

Reads the elaborated SEP=1 `smu` boundary passively: port presence, declared
widths, X-freedom after bring-up, and the inertness of the cross-trigger CTP
channels whose data inputs the wrapper ties to zero.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from seq_lib.smu_compose_helpers import (
    LC_STATE_O_WIDTH,
    LCC_DEMOTE_WIDTH,
    NUM_INT_TO_SMC,
    NUM_SUBSYSTEMS,
    SMN_IN_ID_WIDTH,
    SMN_OUT_ID_WIDTH,
    SS_CONFIG_WIDTH,
    SUBSYS_IN_ID_WIDTH,
    XTRIG_NUM_CTP,
    XTRIG_NUM_INT_CT,
    axi_req_bits,
    axi_resp_bits,
    bit_width,
    hier,
    sample,
)
from seq_lib.smu_tb_pins import smu_scope

CTP_GROUPS = ("req_out", "req_in", "ack_in", "ack_out")
CTP_LEGS = ("dout_o", "dout_en_o", "din_i", "din_en_o")
INERT_WINDOW_CYCLES = 64


class smu_boundary_port_composition_seq:
    """Boundary port widths, presence and tie-off inertness on the SEP=1 wrapper."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger
        self.sb = test.env.scoreboard

    def _width(self, scope, name: str, expected: int, evidence: str) -> None:
        handle = hier(scope, name)
        self.sb.expect_eq(
            f"{name} width",
            bit_width(handle, name),
            expected,
            evidence=evidence,
        )

    def _driven(self, scope, name: str) -> int:
        """Sample an output after bring-up; an X/Z value fails the test."""
        return sample(hier(scope, name), name)

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        smu = smu_scope(dut)
        await self.test.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 8)

        sep = sample(dut.sep_enabled_o, "sep_enabled_o")
        sb.expect_eq("SEP=1 build profile", sep, 1)

        # SMU-LC-STATE.S1 / SMU-LC-DEMOTE.S1
        self._width(smu, "lc_state_o", LC_STATE_O_WIDTH, "CHK-SMU-LC-STATE-S1")
        lc = self._driven(smu, "lc_state_o")
        self._width(smu, "lcc_demote_state_1_o", LCC_DEMOTE_WIDTH, "CHK-SMU-LC-DEMOTE-S1")
        self._width(smu, "lcc_demote_state_2_o", LCC_DEMOTE_WIDTH, "CHK-SMU-LC-DEMOTE-S1")
        d1 = self._driven(smu, "lcc_demote_state_1_o")
        d2 = self._driven(smu, "lcc_demote_state_2_o")
        self.log.info("lifecycle boundary: lc_state_o=0x%02x demote1=%d demote2=%d", lc, d1, d2)

        # SMU-INT-AGG.S1
        self._width(smu, "smc_ext_interrupts_i", NUM_INT_TO_SMC, "CHK-SMU-INT-AGG-S1")
        sb.expect_eq(
            "smc_ext_interrupts_i tie-off reaches the SMU boundary as zero",
            sample(smu.smc_ext_interrupts_i, "smc_ext_interrupts_i"),
            0,
            evidence="CHK-SMU-INT-AGG-S1",
        )

        # SMU-EXT-SMN.S4: struct widths decode to the spec ID widths.
        self._width(smu, "smu_axi_in_req_i", axi_req_bits(SMN_IN_ID_WIDTH), "CHK-SMU-EXT-SMN-S4")
        self._width(smu, "smu_axi_in_resp_o", axi_resp_bits(SMN_IN_ID_WIDTH), "CHK-SMU-EXT-SMN-S4")
        self._width(smu, "smu_axi_out_req_o", axi_req_bits(SMN_OUT_ID_WIDTH), "CHK-SMU-EXT-SMN-S4")
        self._width(
            smu, "smu_axi_out_resp_i", axi_resp_bits(SMN_OUT_ID_WIDTH), "CHK-SMU-EXT-SMN-S4"
        )
        for conv in ("u_iw_conv_sep", "u_iw_conv_smc"):
            inst = hier(smu, f"gen_sep.{conv}")
            sb.expect_eq(
                f"{conv} crossbar-side ID width",
                sample(inst.AxiSlvPortIdWidth, f"{conv}.AxiSlvPortIdWidth"),
                SMN_OUT_ID_WIDTH,
                evidence="CHK-SMU-EXT-SMN-S4",
            )
            sb.expect_eq(
                f"{conv} subsystem-side ID width",
                sample(inst.AxiMstPortIdWidth, f"{conv}.AxiMstPortIdWidth"),
                SUBSYS_IN_ID_WIDTH,
                evidence="CHK-SMU-EXT-SMN-S4",
            )

        # SMU-XTRIG-CTP.S1
        for group in CTP_GROUPS:
            for leg in CTP_LEGS:
                self._width(smu, f"xtrig_ctp_{group}_{leg}", XTRIG_NUM_CTP, "CHK-SMU-XTRIG-CTP-S1")

        # SMU-XTRIG-CTP.S6: tied-zero data inputs, observed at the DTP consumer,
        # leave every CTP output and the CTM boundary static at zero.
        din_names = [f"xtrig_ctp_{g}_din_i" for g in CTP_GROUPS]
        for name in din_names:
            sb.expect_eq(
                f"{name} tie-off at the SMU boundary",
                sample(hier(smu, name), name),
                0,
                evidence="CHK-SMU-XTRIG-CTP-S6",
            )
            sb.expect_eq(
                f"{name} tie-off at the DTP consumer",
                sample(hier(smu, f"u_dtp.{name}"), f"u_dtp.{name}"),
                0,
                evidence="CHK-SMU-XTRIG-CTP-S6",
            )
        watched = {f"xtrig_ctp_{g}_dout_o": hier(smu, f"xtrig_ctp_{g}_dout_o") for g in CTP_GROUPS}
        watched["xtrig_ctm_src_req_o"] = hier(smu, "xtrig_ctm_src_req_o")
        watched["xtrig_ctm_dst_ack_o"] = hier(smu, "xtrig_ctm_dst_ack_o")
        sb.expect_eq(
            "xtrig_ctm_src_req_o width",
            bit_width(watched["xtrig_ctm_src_req_o"], "xtrig_ctm_src_req_o"),
            XTRIG_NUM_INT_CT,
        )
        first = {name: sample(sig, name) for name, sig in watched.items()}
        changes = {name: 0 for name in watched}
        for _ in range(INERT_WINDOW_CYCLES):
            await RisingEdge(dut.clk_smu_i)
            for name, sig in watched.items():
                if sample(sig, name) != first[name]:
                    changes[name] += 1
        self.log.info("CTP inert window: first=%s changes=%s", first, changes)
        sb.expect_eq(
            f"CTP outputs and CTM boundary static over {INERT_WINDOW_CYCLES} clk_smu cycles",
            sum(changes.values()),
            0,
            evidence="CHK-SMU-XTRIG-CTP-S6",
        )
        sb.expect_eq(
            "CTP outputs and CTM boundary idle at zero under tied-zero inputs",
            sum(first.values()),
            0,
            evidence="CHK-SMU-XTRIG-CTP-S6",
        )

        # SMU-SSRESET.S2 / S4
        ss_ctrl = hier(smu, "ss_reset_ctrl_o")
        sb.expect_eq(
            "ss_reset_ctrl_o element count",
            bit_width(ss_ctrl, "ss_reset_ctrl_o"),
            NUM_SUBSYSTEMS,
            evidence="CHK-SMU-SSRESET-S2",
        )
        elem_widths = set()
        for idx in range(NUM_SUBSYSTEMS):
            elem = ss_ctrl[idx]
            elem_widths.add(bit_width(elem, f"ss_reset_ctrl_o[{idx}]"))
            sample(elem, f"ss_reset_ctrl_o[{idx}]")
        sb.expect_eq(
            "ss_reset_ctrl_o elements share one reset_ctrl_t width",
            len(elem_widths),
            1,
            evidence="CHK-SMU-SSRESET-S2",
        )
        self.log.info("ss_reset_ctrl_o: %d elements of %s bits", NUM_SUBSYSTEMS, elem_widths)
        self._width(smu, "ss_config_o", SS_CONFIG_WIDTH, "CHK-SMU-SSRESET-S4")
        cfg_val = self._driven(smu, "ss_config_o")
        self.log.info("ss_config_o=0x%08x", cfg_val)

        # SMU-FUSE-SENSE.S4 / SMU-EFUSE-SHIM-SMC.S3
        self._width(smu, "skip_mem_repair_o", 1, "CHK-SMU-FUSE-SENSE-S4")
        skip = self._driven(smu, "skip_mem_repair_o")
        # port_table.adoc types smc_shadow_regs_o as smc_efuse_pkg::efuse_map_t
        # and states no width, so what is checked is the connection the wrapper
        # can get wrong: the boundary net is as wide as the `smu` port and
        # carries the same value.
        shadow = hier(smu, "smc_shadow_regs_o")
        shadow_bits = bit_width(shadow, "smc_shadow_regs_o")
        sb.expect_eq(
            "smc_shadow_regs boundary net is as wide as the smu smc_shadow_regs_o port",
            bit_width(dut.smc_shadow_regs, "smc_shadow_regs"),
            shadow_bits,
            evidence="CHK-SMU-EFUSE-SHIM-SMC-S3",
        )
        sb.expect_true(
            "smc_shadow_regs_o reaches the wrapper boundary unchanged",
            sample(dut.smc_shadow_regs, "smc_shadow_regs") == sample(shadow, "smc_shadow_regs_o"),
            evidence="CHK-SMU-EFUSE-SHIM-SMC-S3",
        )
        self.log.info("skip_mem_repair_o=%d smc_shadow_regs_o width=%d", skip, shadow_bits)
