# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Lightweight Python-side FCOV counters for OSS SMU (SEP=0 P1/P2/P3).

Verilator cannot compile SV covergroups; VCS can still use this as a
scenario-intent ledger that prints at end-of-test. Hits are recorded when
tests call ``hit()`` or when ``SmuScoreboard`` tags a check with ``fcov=``.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

# covergroup -> coverpoint -> bin
FCOV_BINS: dict[str, dict[str, set[str]]] = {
    "smc_boot_cg": {
        "bringup": {"cold_primary_release"},
    },
    "xbar_route_cg": {
        "sep0_path": {"smc_ext", "ext_smc", "decerr", "id_width", "atop_reject", "remap"},
        "filter": {
            "inbound_program_okay",
            "outside_still_decerr",
            "page_edge",
            "reprogram_shrink",
            "config_clear_deny",
        },
    },
    "reg_access_cg": {
        "path": {"jtag2axi_fabric", "jtag2axi_otp", "hier_ctn", "smn"},
        "outcome": {"success", "decerr_poison", "gated_deny"},
        "race": {"j2a_vs_smn", "otp_vs_fabric", "ctn_vs_j2a"},
    },
    "reset_clock_cg": {
        "ic_reset": {
            "ext",
            "smc_fuse",
            "smc_warm",
            "smc_cool",
            "smc_cold",
            "dual_pack",
        },
        "boot_stall": {"sticky_cold", "trst_clear", "reassert_sticky"},
        "clock_stop": {"jtag", "cla_loop", "jtag_or_cla"},
    },
    "fuse_lifecycle_cg": {
        "lc_state": {"sep0_0xf0"},
        "feat_ctrl": {
            "fabric_allow",
            "fabric_deny",
            "otp_allow",
            "otp_deny",
            "net_golden",
            "mid_op_gate",
        },
    },
    "dtp_debug_cg": {
        "jtag2axi": {
            "rw_matrix",
            "error_path",
            "security_gate",
            "wstrb_neighbor",
            "error_b2b",
            "abort_mid",
        },
        "otp": {"map_complete", "sep0_err_slv", "partial_feat_deny", "instr_scan"},
        "jtag": {"chain_freq"},
        "csr": {"abs_hole", "hier_ctn", "cross_domain"},
    },
    "xtrig_cg": {
        "ctm": {
            "remap_p1",
            "four_phase",
            "smc_glue_1_0",
            "ack_hardwire_0",
            "illegal_phase",
            "smc_bits_clean",
        },
        "cla": {"clk_stop_fb", "concurrent_ctm"},
    },
    "wdt_cg": {
        "timeout": {"wdogip0", "ip0_isolate_clamp"},
        "scratch": {"cold_sticky", "cold_warm_clear", "double_pulse"},
    },
    "glue_p4_cg": {
        "macro": {"pll_route", "pvt_route", "extension_route", "decerr_poison"},
        "octs": {"count_advance"},
        "ic_reset_ss": {"ss_cold0", "ss_warm0"},
        "bsr": {"extest_loopback"},
        "telemetry": {"atb_handshake"},
        "efuse": {"secure_tm_force"},
    },
}

# Auto-hit map: test class name -> list of (cg, cp, bin)
TEST_FCOV_HITS: dict[str, list[tuple[str, str, str]]] = {
    "smu_smc_smoke_test": [
        ("smc_boot_cg", "bringup", "cold_primary_release"),
    ],
    "smu_smc_reset_ctrl_test": [
        ("smc_boot_cg", "bringup", "cold_primary_release"),
    ],
    "smu_sys_in_filter_program_jtag_test": [
        ("xbar_route_cg", "filter", "inbound_program_okay"),
        ("xbar_route_cg", "filter", "outside_still_decerr"),
        ("reg_access_cg", "path", "jtag2axi_fabric"),
    ],
    "smu_sys_in_filter_window_edge_test": [
        ("xbar_route_cg", "filter", "inbound_program_okay"),
        ("xbar_route_cg", "filter", "outside_still_decerr"),
        ("xbar_route_cg", "filter", "page_edge"),
    ],
    "smu_sys_in_filter_reprogram_shrink_test": [
        ("xbar_route_cg", "filter", "inbound_program_okay"),
        ("xbar_route_cg", "filter", "reprogram_shrink"),
        ("xbar_route_cg", "filter", "config_clear_deny"),
    ],
    "smu_dtp_jtag2axi_wstrb_partial_sticky_test": [
        ("reg_access_cg", "path", "jtag2axi_fabric"),
        ("reg_access_cg", "outcome", "success"),
        ("dtp_debug_cg", "jtag2axi", "wstrb_neighbor"),
    ],
    "smu_dtp_jtag2axi_back_to_back_error_ok_test": [
        ("reg_access_cg", "outcome", "decerr_poison"),
        ("reg_access_cg", "outcome", "success"),
        ("dtp_debug_cg", "jtag2axi", "error_b2b"),
    ],
    "smu_feat_ctrl_partial_bit_corner_test": [
        ("dtp_debug_cg", "otp", "partial_feat_deny"),
        ("dtp_debug_cg", "otp", "map_complete"),
        ("reg_access_cg", "path", "jtag2axi_otp"),
    ],
    "smu_ic_reset_dual_domain_illegal_test": [
        ("reset_clock_cg", "ic_reset", "smc_fuse"),
        ("reset_clock_cg", "ic_reset", "smc_warm"),
        ("reset_clock_cg", "ic_reset", "smc_cool"),
        ("reset_clock_cg", "ic_reset", "smc_cold"),
        ("reset_clock_cg", "ic_reset", "dual_pack"),
    ],
    "smu_boot_stall_vs_ic_reset_priority_test": [
        ("reset_clock_cg", "boot_stall", "sticky_cold"),
        ("reset_clock_cg", "boot_stall", "trst_clear"),
        ("reset_clock_cg", "ic_reset", "smc_warm"),
        ("reset_clock_cg", "ic_reset", "smc_cold"),
    ],
    "smu_dtp_jtag2axi_smc_rw_matrix_test": [
        ("reg_access_cg", "path", "jtag2axi_fabric"),
        ("reg_access_cg", "outcome", "success"),
        ("dtp_debug_cg", "jtag2axi", "rw_matrix"),
    ],
    "smu_dtp_jtag2axi_smc_error_path_test": [
        ("reg_access_cg", "outcome", "decerr_poison"),
        ("dtp_debug_cg", "jtag2axi", "error_path"),
    ],
    "smu_dtp_jtag_smc_cpu_register_test": [
        ("reg_access_cg", "path", "jtag2axi_fabric"),
        ("reg_access_cg", "outcome", "success"),
    ],
    "smu_dtp_otp_smc_complete_rw_test": [
        ("reg_access_cg", "path", "jtag2axi_otp"),
        ("dtp_debug_cg", "otp", "map_complete"),
    ],
    "smu_dtp_ptap_otp_instr_scan_test": [
        ("reg_access_cg", "path", "jtag2axi_otp"),
        ("dtp_debug_cg", "otp", "instr_scan"),
    ],
    "smu_jtag_chain_enhanced_test": [
        ("dtp_debug_cg", "jtag", "chain_freq"),
    ],
    "smu_smc_mailbox_sanity_test": [
        ("reg_access_cg", "path", "jtag2axi_fabric"),
        ("reg_access_cg", "outcome", "success"),
    ],
    "smu_dtp_otp_sep0_err_slv_test": [
        ("dtp_debug_cg", "otp", "sep0_err_slv"),
    ],
    "smu_boot_stall_jtag_cold_reset_matrix_test": [
        ("reset_clock_cg", "boot_stall", "sticky_cold"),
        ("reset_clock_cg", "boot_stall", "trst_clear"),
        ("reset_clock_cg", "boot_stall", "reassert_sticky"),
    ],
    "smu_ic_reset_smc_multi_domain_test": [
        ("reset_clock_cg", "ic_reset", "smc_fuse"),
        ("reset_clock_cg", "ic_reset", "smc_warm"),
        ("reset_clock_cg", "ic_reset", "smc_cool"),
        ("reset_clock_cg", "ic_reset", "smc_cold"),
    ],
    "smu_dtp_clock_stop_smc_cla_loop_test": [
        ("reset_clock_cg", "clock_stop", "cla_loop"),
        ("xtrig_cg", "cla", "clk_stop_fb"),
    ],
    "smu_xtrig_ctm_remap_test": [
        ("xtrig_cg", "ctm", "remap_p1"),
        ("xtrig_cg", "ctm", "smc_bits_clean"),
    ],
    "smu_xtrig_ctm_four_phase_test": [
        ("xtrig_cg", "ctm", "four_phase"),
    ],
    "smu_xtrig_ctm_illegal_phase_test": [
        ("xtrig_cg", "ctm", "illegal_phase"),
    ],
    "smu_cla_and_xtrig_concurrent_test": [
        ("reset_clock_cg", "clock_stop", "cla_loop"),
        ("xtrig_cg", "ctm", "four_phase"),
        ("xtrig_cg", "cla", "concurrent_ctm"),
    ],
    "smu_clock_stop_jtag_vs_cla_fb_race_test": [
        ("reset_clock_cg", "clock_stop", "jtag_or_cla"),
        ("reset_clock_cg", "clock_stop", "cla_loop"),
    ],
    "smc_wdt_scratch_double_pulse_test": [
        ("wdt_cg", "scratch", "cold_sticky"),
        ("wdt_cg", "scratch", "cold_warm_clear"),
        ("wdt_cg", "scratch", "double_pulse"),
    ],
    "smu_dtp_jtag2axi_abort_mid_op_test": [
        ("dtp_debug_cg", "jtag2axi", "abort_mid"),
        ("reg_access_cg", "outcome", "success"),
    ],
    "smu_feat_ctrl_flip_mid_jtag2axi_test": [
        ("fuse_lifecycle_cg", "feat_ctrl", "mid_op_gate"),
        ("reg_access_cg", "outcome", "success"),
    ],
    "smu_jtag2axi_vs_smn_same_csr_race_test": [
        ("reg_access_cg", "path", "jtag2axi_fabric"),
        ("xbar_route_cg", "filter", "inbound_program_okay"),
        ("reg_access_cg", "race", "j2a_vs_smn"),
    ],
    "smu_otp_vs_fabric_map_race_test": [
        ("reg_access_cg", "path", "jtag2axi_otp"),
        ("reg_access_cg", "path", "jtag2axi_fabric"),
        ("reg_access_cg", "race", "otp_vs_fabric"),
    ],
    "smu_hier_ctn_vs_jtag2axi_concurrent_test": [
        ("dtp_debug_cg", "csr", "hier_ctn"),
        ("reg_access_cg", "path", "jtag2axi_fabric"),
        ("reg_access_cg", "race", "ctn_vs_j2a"),
    ],
    "smu_dtp_xtrigger_smc_cla_test": [
        ("xtrig_cg", "ctm", "smc_glue_1_0"),
        ("xtrig_cg", "ctm", "ack_hardwire_0"),
    ],
    "smu_dtp_csr_access_test": [
        ("dtp_debug_cg", "csr", "abs_hole"),
        ("dtp_debug_cg", "csr", "hier_ctn"),
        ("reg_access_cg", "path", "hier_ctn"),
    ],
    "smu_fabric_smc_dtp_cross_domain_test": [
        ("dtp_debug_cg", "csr", "cross_domain"),
        ("reg_access_cg", "path", "jtag2axi_fabric"),
    ],
    "smu_dtp_feat_ctrl_gate_matrix_test": [
        ("fuse_lifecycle_cg", "feat_ctrl", "net_golden"),
        ("fuse_lifecycle_cg", "feat_ctrl", "fabric_allow"),
        ("fuse_lifecycle_cg", "feat_ctrl", "fabric_deny"),
        ("fuse_lifecycle_cg", "feat_ctrl", "otp_allow"),
        ("fuse_lifecycle_cg", "feat_ctrl", "otp_deny"),
        ("dtp_debug_cg", "jtag2axi", "security_gate"),
    ],
    "smu_lifecycle_debug_policy_test": [
        ("fuse_lifecycle_cg", "lc_state", "sep0_0xf0"),
        ("fuse_lifecycle_cg", "feat_ctrl", "fabric_allow"),
        ("fuse_lifecycle_cg", "feat_ctrl", "fabric_deny"),
    ],
    "smu_smc_dtp_jtag2axi_security_test": [
        ("dtp_debug_cg", "jtag2axi", "security_gate"),
        ("reg_access_cg", "outcome", "gated_deny"),
    ],
    "smu_smc_wdt_timeout_irq_test": [
        ("wdt_cg", "timeout", "wdogip0"),
    ],
    "smc_reset_unit_wdt_scratch_test": [
        ("wdt_cg", "scratch", "cold_sticky"),
        ("wdt_cg", "scratch", "cold_warm_clear"),
    ],
    "smc_efuse_secure_tm_force_test": [
        ("glue_p4_cg", "efuse", "secure_tm_force"),
    ],
    "smc_wdt_ip0_isolate_clamp_test": [
        ("wdt_cg", "timeout", "wdogip0"),
        ("wdt_cg", "timeout", "ip0_isolate_clamp"),
    ],
    "smu_macro_axil_pll_pvt_route_test": [
        ("glue_p4_cg", "macro", "pll_route"),
        ("glue_p4_cg", "macro", "pvt_route"),
        ("glue_p4_cg", "macro", "extension_route"),
        ("glue_p4_cg", "macro", "decerr_poison"),
        ("xbar_route_cg", "sep0_path", "decerr"),
    ],
    "smu_octs_timer_count_csr_test": [
        ("glue_p4_cg", "octs", "count_advance"),
    ],
    "smu_ic_reset_ss_domain_matrix_test": [
        ("glue_p4_cg", "ic_reset_ss", "ss_cold0"),
        ("glue_p4_cg", "ic_reset_ss", "ss_warm0"),
    ],
    "smu_dtp_bsr_extest_loopback_test": [
        ("glue_p4_cg", "bsr", "extest_loopback"),
    ],
    "smu_telemetry_atb_handshake_test": [
        ("glue_p4_cg", "telemetry", "atb_handshake"),
    ],
}


class SmuFcov:
    """Per-test FCOV hit ledger (SEP=0 intent bins)."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str, str], int] = defaultdict(int)

    def hit(self, covergroup: str, coverpoint: str, bin_name: str) -> None:
        key = (covergroup, coverpoint, bin_name)
        # Keys are not validated against FCOV_BINS; any (cg, cp, bin) triple is counted.
        self._hits[key] += 1

    def hit_many(self, items: Iterable[tuple[str, str, str]]) -> None:
        for cg, cp, bn in items:
            self.hit(cg, cp, bn)

    def hit_for_test(self, test_name: str) -> int:
        items = TEST_FCOV_HITS.get(test_name, [])
        self.hit_many(items)
        return len(items)

    def summary_lines(self) -> list[str]:
        if not self._hits:
            return ["FCOV: no hits recorded"]
        lines = ["FCOV hits:"]
        for (cg, cp, bn), n in sorted(self._hits.items()):
            lines.append(f"  {cg}.{cp}.{bn} = {n}")
        return lines

    def hit_count(self) -> int:
        return sum(self._hits.values())
