# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Canonical evidence map for OSS SMU tests.

Each test lists (CHK_ID, TOKEN, EXPECT) triples. Scoreboard logs
``EVIDENCE: <TOKEN>``.
``CHK-NONVAC`` is emitted by SmuScoreboard.check_phase when checks > 0.

What a TOKEN carries: a passing ``expect_*`` compare logged it, bound either
by an explicit ``evidence=`` argument or by the TOKEN/CHK id appearing in the
check name. EXPECT is free-text contract wording for readers and reviewers;
no code compares it against an observed value.

Keys name the pyuvm type name of the test body. Testcases that build an
``SmuScoreboard`` and carry no rows here must be listed in
``UNMAPPED_TESTS``; ``prove_mapped_features`` raises otherwise. The
``--dut smu_wrapper`` bodies build no ``SmuScoreboard`` and never reach it.

Names without an enrolled test body are catalogued in
``docs/SMU_DEFERRED_DISPOSITION.adoc``; their rows stay here and nothing logs
their tokens.
"""

from __future__ import annotations

# testcase -> recorded reason for running with no (CHK_ID, TOKEN, EXPECT) rows
UNMAPPED_TESTS: dict[str, str] = {
    "smu_ext_axi_global_addr_smoke_test": (
        "present but not enrolled: the OSS s_axi is a LOCAL aperture, so "
        "GLOBAL_BASE + offset DECERRs. Rows are withheld until enrollment; "
        "disposition in docs/SMU_DEFERRED_DISPOSITION.adoc"
    ),
}

# testcase -> ordered checkbox contracts (FEATURE_LIST / VPLAN aligned)
TEST_EVIDENCE: dict[str, list[tuple[str, str, str]]] = {
    # --- P0 density / phase1 ---
    "smu_smc_smoke_test": [
        (
            "CHK-SMC-FAB-DUAL-NET-S2",
            "CHK-SMC-FAB-DUAL-NET-S2",
            "AXI4-Lite LP to local_peripheral + config_register",
        ),
        (
            "CHK-SMC-FAB-DUAL-NET-S3",
            "CHK-SMC-FAB-DUAL-NET-S3",
            "AXI4 + AXI4-Lite both 64-bit data",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK-TIMEOUT-PATHS", "bounded waits with last-state"),
        ("CHK-NONVAC", "CHK-NONVAC", "ordered fence S1<S2<S3<S4<PASS"),
    ],
    "smu_dtp_jtag_smoke_test": [
        (
            "CHK-DTP-JTAG-PTAP-S1",
            "CHK-DTP-JTAG-PTAP-S1",
            "IDCODE instruction returns configured IDCODE fields",
        ),
        (
            "CHK-DTP-JTAG-PTAP-S2",
            "CHK-DTP-JTAG-PTAP-S2",
            "BYPASS single-bit TDI/TDO latency",
        ),
        (
            "CHK-DTP-JTAG-PTAP-S3",
            "CHK-DTP-JTAG-PTAP-S3",
            "TRST and POR return TAP to Test-Logic-Reset",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK-TIMEOUT-PATHS", "bounded JTAG waits with last TAP state"),
        ("CHK-NONVAC", "CHK-NONVAC", "ordered fence S1<S2<S3<S4<S5<PASS"),
    ],
    "smu_no_sep_configuration_test": [
        ("CHK-SEP0-LC", "CHK-SEP0-LC", "lc_state_o==0xf0 stable >=16 cycles"),
        ("CHK-TIMEOUT-PATHS", "CHK-TIMEOUT-PATHS", "bounded waits with last-state"),
        ("CHK-NONVAC", "CHK-NONVAC", "ordered fence S2<PASS"),
    ],
    "smu_ext_boot_seq_gate_test": [
        ("CHK-BOOT-SEQ-GATE", "CHK-BOOT-SEQ-GATE", "gate holds then releases fuse_reset"),
        ("CHK-PRIMARY-NOT-GATED", "CHK-PRIMARY-NOT-GATED", "primary still releases while gated"),
        ("CHK-TIMEOUT-PATHS", "CHK-TIMEOUT-PATHS", "bounded sample waits with last state"),
        ("CHK-NONVAC", "CHK-NONVAC", "ordered fence S2<S3<S4<PASS"),
    ],
    "smu_dft_dtp_boot_stall_test": [
        ("CHK-STALL-STICKY", "STALL_COLD_STICKY", "stall survives cold"),
        ("CHK-STALL-REASSERT", "STALL_REASSERT_STICKY", "re-assert does not re-gate"),
    ],
    "smu_dft_gpio_boot_stall_test": [
        ("CHK-STALL-STICKY", "STALL_COLD_STICKY", "GPIO stall sticky across cold"),
        ("CHK-STALL-REASSERT", "STALL_REASSERT_STICKY", "re-assert does not re-gate"),
    ],
    "smu_dtp_dtm_local_axi_test": [
        ("CHK-J2A-RW-MATRIX", "J2A_RW_MATRIX_OK", "local AXI / DTM path completes"),
    ],
    "smu_cross_trigger_matrix_test": [
        ("CHK-XT-DEST-4PH", "XT_DEST_4PHASE", "CTM path observable"),
    ],
    "smu_clock_stop_coordination_test": [
        (
            "CHK-DTP-BOOT-STALL-S1",
            "CHK-DTP-BOOT-STALL-S1",
            "Override enabled with stall asserted holds SMC boot",
        ),
        (
            "CHK-DTP-BOOT-STALL-S2",
            "CHK-DTP-BOOT-STALL-S2",
            "Clearing stall/override allows SMC boot progression",
        ),
        (
            "CHK-DTP-IC-RESET-S1",
            "CHK-DTP-IC-RESET-S1",
            "SMC IC_RESET override forces selected SMC reset slice",
        ),
        (
            "CHK-DTP-IC-RESET-S3",
            "CHK-DTP-IC-RESET-S3",
            "TRST/POR or clearing override removes override effect",
        ),
        (
            "CHK-DTP-CLKSTOP-AGG-S1",
            "CHK-DTP-CLKSTOP-AGG-S1",
            "Only jtag_clock_stop asserts stop_clks_o",
        ),
        (
            "CHK-DTP-CLKSTOP-AGG-S2",
            "CHK-DTP-CLKSTOP-AGG-S2",
            "Only CLA clk_stop_req asserts stop_clks_o and CLA-only status",
        ),
        (
            "CHK-DTP-CLKSTOP-AGG-S3",
            "CHK-DTP-CLKSTOP-AGG-S3",
            "Port [0] reserved for SMC participates in SMC CLA handshake",
        ),
        (
            "CHK-NONVAC",
            "CHK-NONVAC",
            "ordered simulation-time fence S1<S2<S3<S4<S5<S6<S7<S8<S9<PASS",
        ),
    ],
    "smu_sep_smoke_test": [
        (
            "CHK-SMC-RST-PRIMARY-EXPORT-S1",
            "CHK-SMC-RST-PRIMARY-EXPORT-S1",
            "Functional cold reset asserts both exported primary reset outputs",
        ),
        (
            "CHK-SMC-RST-PRIMARY-EXPORT-S2",
            "CHK-SMC-RST-PRIMARY-EXPORT-S2",
            "JTAG/TDR state is not cleared by rst_primary alone",
        ),
        (
            "CHK-DTP-XTRIG-CTM-S2",
            "CHK-DTP-XTRIG-CTM-S2",
            "Pulse-sync mode leaves ack ports unused as specified",
        ),
        (
            "CHK-DTP-XTRIG-CTM-S3",
            "CHK-DTP-XTRIG-CTM-S3",
            "Bits [1:0] remain reserved for SMC",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK-TIMEOUT-PATHS", "bounded waits with last-state"),
        ("CHK-NONVAC", "CHK-NONVAC", "ordered fence S1<S2<S3<S4<S5<S6<PASS"),
    ],
    "smu_xtrig_ctm_remap_test": [
        ("CHK-XT-CTM-REMAP", "XT_CTM_REMAP", "product-pin CTM remap"),
    ],
    "smu_dtp_otp_debug_access_test": [
        ("CHK-OTP-MAP-RW", "OTP_MAP_RW_OK", "OTP debug access status path"),
    ],
    "smu_lifecycle_debug_policy_test": [
        ("CHK-FEAT-FAB-DENY", "FEAT_FAB_DENY", "lifecycle/feat gate deny contrast"),
    ],
    "smu_jtag_reset_override_test": [
        ("CHK-IC-DEFAULT", "IC_RESET_DEFAULT", "IC_RESET default all-ones"),
        ("CHK-IC-DOMAIN", "IC_RESET_DOMAIN_EXCL", "single domain override exclusive"),
    ],
    "smu_smc_dtp_jtag2axi_security_test": [
        ("CHK-FEAT-FAB-ALLOW", "FEAT_FAB_ALLOW", "security allow path SUCCESS"),
        ("CHK-FEAT-FAB-DENY", "FEAT_FAB_DENY", "security deny contrast"),
    ],
    "smu_smc_reset_ctrl_test": [
        ("CHK-RST-PRIMARY", "RST_PRIMARY_SMC_1", "SMC primary reset released"),
        ("CHK-RST-COLD-STABLE", "RST_COLD_STABLE_1", "cold stable released"),
    ],
    "smu_smc_mailbox_int_test": [
        (
            "CHK-SMC-MBX-IRQ-EXT-S2",
            "CHK-SMC-MBX-IRQ-EXT-S2",
            "ext_mailbox_interrupts is NUM_MAILBOXES=32 wide; mailbox 0 / 31 IRQs move bits 0 / 31",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK-TIMEOUT-PATHS", "bounded waits with last-state"),
        ("CHK-NONVAC", "CHK-NONVAC", "ordered fence S1<S2<S3<S4<PASS"),
    ],
    "smu_smc_gpio_strap_sanity_test": [
        ("CHK-SMC-STRAP", "SMC_STRAP_OK", "GPIO strap observe"),
    ],
    "smc_efuse_reg_sanity_test": [
        ("CHK-SMC-EFUSE-CSR", "SMC_EFUSE_CSR_OK", "eFuse CSR sanity"),
    ],
    "smu_smc_wdt_sanity_test": [
        ("CHK-WDT-UNLOCK", "WDT_UNLOCK_OK", "WDT unlock SUCCESS"),
    ],
    "smu_smc_security_demote_pm_test": [
        ("CHK-DEMOTE-TIEOFF", "DEMOTE_TIEOFF_OBS", "SEP=0 demote hardwire observe"),
    ],
    "smc_cpu_traffic_ext_axi_test": [
        ("CHK-AXI-ID-WIDTH", "AXI_ID_WIDTH_OK", "CPU/ext AXI traffic completes"),
    ],
    "smu_axi_id_width_conversion_test": [
        ("CHK-AXI-ID-WIDTH", "AXI_ID_WIDTH_OK", "ID width conversion completes"),
    ],
    "smu_axi_crossbar_error_handling_test": [
        (
            "CHK-SMC-PWRGOOD-DTP-POR-S2",
            "CHK-SMC-PWRGOOD-DTP-POR-S2",
            "PTAP leave-TLR with power-good + TRST released",
        ),
        ("CHK-NONVAC", "CHK-NONVAC", "ordered fence S1<PASS after leave-TLR"),
    ],
    "smu_axi_external_port_connectivity_test": [
        (
            "CHK-SMU-PORT-SMN-AXI-S1",
            "CHK-SMU-PORT-SMN-AXI-S1",
            "SEP=0 inbound smu_axi_in reaches SMC via direct IW",
        ),
        (
            "CHK-SMU-SEP-PARAM-S2",
            "CHK-SMU-SEP-PARAM-S2",
            "SEP=0 direct SMC↔external ID converters elaborated",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK-TIMEOUT-PATHS", "bounded AXI waits with last-state"),
        ("CHK-NONVAC", "CHK-NONVAC", "ordered fence S1<S2<S3<S4<PASS"),
    ],
    "smu_smc_global_base_remap_test": [
        ("CHK-AXI-REMAP", "AXI_GLOBAL_BASE", "GLOBAL_BASE remap observed"),
    ],
    "smu_axi_atomic_operation_test": [
        ("CHK-AXI-NON-ATOP", "AXI_NON_ATOP_OK", "non-ATOP SMN path completes"),
    ],
    # --- sep0_all rows (tokens match seq expect_*) ---
    "smu_axi_xbar_structure_test": [
        (
            "CHK-XBAR-POS-NO-GEN-SEP",
            "CHK-XBAR-POS-NO-GEN-SEP",
            "gen_sep absent under SEP=0",
        ),
        (
            "CHK-XBAR-POS-IW",
            "CHK-XBAR-POS-IW",
            "gen_no_sep ID converters resolve",
        ),
        (
            "CHK-XBAR-ABSENT-NO-SEP",
            "CHK-XBAR-ABSENT-NO-SEP",
            "smu_axi_xbar absent under gen_no_sep",
        ),
    ],
    "smu_axi_filter_allow_ns_test": [
        ("CHK-SMU-ALLOW-NS-S1", "CHK-SMU-ALLOW-NS-S1", "allow_ns=0 secure OKAY / NS DECERR"),
        ("CHK-SMU-ALLOW-NS-S2", "CHK-SMU-ALLOW-NS-S2", "dual-slot admits secure and NS"),
        ("CHK-SMU-ALLOW-NS-S3", "CHK-SMU-ALLOW-NS-S3", "clear returns DECERR for both"),
    ],
    "smu_axi_prot_encoding_decode_test": [
        (
            "CHK-SMU-PROT-S9-MATRIX",
            "CHK-SMU-PROT-S9-MATRIX",
            "eight-way AxPROT matrix on VERSION_LO",
        ),
    ],
    "smu_axi_filter_in_instance_matrix_test": [
        (
            "CHK-FILTER-IN-INSTANCES-S1",
            "CHK-FILTER-IN-INSTANCES-S1",
            "inbound instance DECODE bases",
        ),
    ],
    "smu_axi_filter_out_instance_matrix_test": [
        (
            "CHK-FILTER-OUT-INSTANCES-S1",
            "CHK-FILTER-OUT-INSTANCES-S1",
            "outbound instance DECODE bases",
        ),
    ],
    "smu_fabric_reg_bar_wr_test": [
        (
            "CHK-SUB-AXIL-LOCAL-S2",
            "CHK-SUB-AXIL-LOCAL-S2",
            "fabric config CSR delivered OKAY",
        ),
    ],
    "smu_axi_alias_remap_manager_scope_test": [
        (
            "CHK-ALIAS-REMAP-SCOPE-S3",
            "CHK-ALIAS-REMAP-SCOPE-S3",
            "jtag2axi alias_remapped write/readback",
        ),
    ],
    "smu_system_timer_octs_test": [
        (
            "CHK-OCTS-PRIMARY-STRAP",
            "CHK-OCTS-PRIMARY-STRAP",
            "primary strap tracks chiplet_is_primary_i",
        ),
        (
            "CHK-OCTS-COUNT-MONOTONIC",
            "CHK-OCTS-COUNT-MONOTONIC",
            "OCTS pin count advances",
        ),
    ],
    "smu_i3c_mem_port_connectivity_test": [
        (
            "CHK-SUB-AXIL-LOCAL-S1",
            "CHK-SUB-AXIL-LOCAL-S1",
            "local peripheral destinations observed OKAY",
        ),
    ],
    "smu_dtp_io_stap_smoke_test": [
        ("CHK-DTP-IO-STAP-SCAN", "CHK-DTP-IO-STAP-SCAN", "IO STAP host TCK observe"),
    ],
    "smu_dtp_smc_stap_smoke_test": [
        (
            "CHK-DTP-SMC-STAP-IDCODE",
            "CHK-DTP-SMC-STAP-IDCODE",
            "SMC STAP selected IDCODE TCK match",
        ),
    ],
    "smu_dtp_bsr_ijtag_scan_test": [
        (
            "CHK-DTP-BSR-EXTEST-SELECT",
            "CHK-DTP-BSR-EXTEST-SELECT",
            "EXTEST selects BSR TCK",
        ),
    ],
    "smu_dtp_otp_smc_map_rw_test": [
        ("CHK-OTP-SMC-MAP-RW", "CHK-OTP-SMC-MAP-RW", "SMC OTP MAP SPARE[0] R/W"),
    ],
    "smu_dtp_otp_smc_series_error_test": [
        (
            "CHK-OTP-SMC-DECODE-SLVERR",
            "CHK-OTP-SMC-DECODE-SLVERR",
            "OTP decode-hole SLVERR",
        ),
    ],
    "smu_smc_dtp_jtag2axi_smoke_test": [
        (
            "CHK-JTAG2AXI-SMOKE-SCRATCH",
            "CHK-JTAG2AXI-SMOKE-SCRATCH",
            "J2A scratch write/readback",
        ),
    ],
    # --- P1 phase2 deepeners ---
    "smu_dtp_jtag2axi_smc_rw_matrix_test": [
        ("CHK-J2A-RW-MATRIX", "J2A_RW_MATRIX_OK", "partial WSTRB 0x55/0xAA merge"),
    ],
    "smu_dtp_jtag2axi_smc_error_path_test": [
        ("CHK-J2A-DECERR", "J2A_DECERR_POISON", "unmapped DECERR + poison"),
        ("CHK-J2A-RECOVERY", "J2A_RECOVERY_OK", "VERSION_LO SUCCESS after error"),
    ],
    "smu_dtp_jtag_smc_cpu_register_test": [
        ("CHK-JTAG2AXI-RW", "JTAG2AXI_RW_OK", "SCRATCH_15 two-pattern R/W"),
        ("CHK-CPU-REG-STALL", "CPU_REG_STALL", "DEBUG_CONTROL boot_stall hold"),
    ],
    "smu_dtp_otp_smc_complete_rw_test": [
        # Gated-deny is not claimed on this leaf (see test docstring); MAP-RW only.
        ("CHK-OTP-MAP-RW", "OTP_MAP_RW_OK", "OTP+fabric+shadow match on RESERVED"),
    ],
    "smu_dtp_ptap_otp_instr_scan_test": [
        ("CHK-PTAP-SEP-OTP-CAPS", "PTAP_SEP_OTP_CAPS_OK", "SEP OTP CAPS packing"),
        ("CHK-PTAP-JTAG-CAPS-SEP-DBG", "PTAP_SEP_DBG_EN_0", "JTAG_CAPS sep_dbg_en=0"),
        (
            "CHK-PTAP-OTP-SINGLE-OP-IRDR",
            "PTAP_OTP_SINGLE_OP_IRDR_OK",
            "SMC SINGLE_OP TDR echo + SEP IR BYPASS",
        ),
    ],
    "smu_jtag_chain_enhanced_test": [
        (
            "CHK-JTAG-CHAIN-ENHANCED",
            "JTAG_CHAIN_ENHANCED_OK",
            "IDCODE+BYPASS at 1/5/10/20 MHz TCK",
        ),
    ],
    "smu_smc_mailbox_sanity_test": [
        ("CHK-MBX-IRQEN", "SMC_MBX_CSR_OK", "outbound-0 IRQEN write/readback"),
    ],
    "smu_dtp_otp_sep0_err_slv_test": [
        ("CHK-OTP-SEP0-ERR", "OTP_SEP0_ERR_SLV", "hier DECERR + poison"),
    ],
    "smu_boot_stall_jtag_cold_reset_matrix_test": [
        ("CHK-STALL-STICKY", "STALL_COLD_STICKY", "stall survives cold"),
        ("CHK-STALL-TRST", "STALL_TRST_CLEAR", "TRST clears stall"),
        ("CHK-STALL-REASSERT", "STALL_REASSERT_STICKY", "re-assert sticky"),
    ],
    "smu_ic_reset_smc_multi_domain_test": [
        ("CHK-IC-DOMAIN", "IC_RESET_DOMAIN_EXCL", "one domain ovrd exclusive"),
    ],
    "smu_dtp_clock_stop_smc_cla_loop_test": [
        ("CHK-CLA-LOOP", "CLA_CLK_STOP_LOOP", "CLA fb -> stop_clks loop"),
    ],
    "smu_xtrig_ctm_four_phase_test": [
        ("CHK-XT-DEST-4PH", "XT_DEST_4PHASE", "dest four-phase"),
        ("CHK-XT-SRC-4PH", "XT_SRC_4PHASE", "src four-phase"),
    ],
    "smu_dtp_xtrigger_smc_cla_test": [
        ("CHK-XT-SMC-GLUE", "XT_SMC_GLUE", "SMC CLA glue [1:0]"),
        ("CHK-XT-ACK-HARDWIRE", "XT_ACK_HARDWIRE_0", "src_ack[1:0]==0"),
    ],
    "smu_dtp_csr_access_test": [
        ("CHK-DTP-ABS-HOLE", "DTP_ABS_HOLE", "abs DTP CSR hole DECERR"),
        ("CHK-DTP-HIER-CTN", "DTP_HIER_CTN_OK", "hier CTN CONFIG OK"),
    ],
    "smu_fabric_smc_dtp_cross_domain_test": [
        ("CHK-XDOM-A", "XDOM_VERSION_OK", "VERSION_LO SUCCESS"),
        ("CHK-XDOM-B", "XDOM_CTN_OK", "CTN CONFIG hier R/W"),
    ],
    "smu_dtp_feat_ctrl_gate_matrix_test": [
        ("CHK-FEAT-NET-GOLDEN", "FEAT_NET_GOLDEN", "disable nets match golden"),
        ("CHK-FEAT-FAB-ALLOW", "FEAT_FAB_ALLOW", "fabric allow"),
        ("CHK-FEAT-FAB-DENY", "FEAT_FAB_DENY", "fabric deny"),
        ("CHK-FEAT-OTP-ALLOW", "FEAT_OTP_ALLOW", "OTP allow"),
        ("CHK-FEAT-OTP-DENY", "FEAT_OTP_DENY", "OTP deny"),
    ],
    "smu_sys_in_filter_program_jtag_test": [
        ("CHK-AXI-FILTER-OKAY", "AXI_FILTER_OKAY", "after program window OKAY"),
    ],
    "smu_smc_wdt_timeout_irq_test": [
        ("CHK-WDT-IP0", "WDT_WDOGIP0", "WDOGIP0 sets after enable+CMP"),
    ],
    "smc_reset_unit_wdt_scratch_test": [
        ("CHK-WDT-SCRATCH", "WDT_SCRATCH_DOMAIN", "cold sticky; warm cleared"),
    ],
    # --- P2 / P3 corners ---
    "smu_dtp_jtag2axi_wstrb_partial_sticky_test": [
        ("CHK-J2A-WSTRB-NBR", "J2A_WSTRB_NEIGHBOR", "partial merge; neighbor intact"),
    ],
    "smu_dtp_jtag2axi_back_to_back_error_ok_test": [
        ("CHK-J2A-B2B", "J2A_B2B_OK", "DECERR then immediate SUCCESS"),
    ],
    "smu_dtp_jtag2axi_abort_mid_op_test": [
        ("CHK-J2A-ABORT", "J2A_ABORT_RECOVER", "abort mid-BUSY recovers"),
    ],
    "smu_feat_ctrl_partial_bit_corner_test": [
        ("CHK-FEAT-PARTIAL", "FEAT_PARTIAL_DENY", "incomplete set does not land MAP"),
    ],
    "smu_feat_ctrl_flip_mid_jtag2axi_test": [
        ("CHK-FEAT-MID-OP", "FEAT_MID_OP_GATE", "mid-BUSY gate flip"),
    ],
    "smu_ic_reset_dual_domain_illegal_test": [
        ("CHK-IC-DUAL", "IC_RESET_DUAL_PACK", "dual packed ovrd; no bleed"),
    ],
    "smu_boot_stall_vs_ic_reset_priority_test": [
        ("CHK-STALL-VS-IC", "STALL_VS_IC_RESET", "IC_RESET does not clear stall"),
    ],
    "smc_wdt_scratch_double_pulse_test": [
        ("CHK-WDT-DOUBLE", "WDT_DOUBLE_PULSE", "two pulses; cold sticky"),
    ],
    "smu_xtrig_ctm_illegal_phase_test": [
        (
            "CHK-XT-ILLEGAL",
            "XT_ILLEGAL_PHASE",
            "DTP[9:2] follows abort/double-req pin patterns",
        ),
    ],
    "smu_cla_and_xtrig_concurrent_test": [
        ("CHK-CLA-CTM-CONC", "CLA_CTM_CONCURRENT", "stop_clks held through CTM"),
    ],
    "smu_clock_stop_jtag_vs_cla_fb_race_test": [
        ("CHK-STOP-OR", "CLOCK_STOP_OR", "stop_clks = JTAG|CLA fb"),
    ],
    "smu_jtag2axi_vs_smn_same_csr_race_test": [
        ("CHK-RACE-J2A-SMN", "RACE_J2A_SMN", "coherent dual-agent winner"),
    ],
    "smu_otp_vs_fabric_map_race_test": [
        ("CHK-RACE-OTP-FAB", "RACE_OTP_FABRIC", "shadow == last writer"),
    ],
    "smu_hier_ctn_vs_jtag2axi_concurrent_test": [
        ("CHK-RACE-CTN-J2A", "RACE_CTN_J2A", "CTN + VERSION both correct"),
    ],
    "smu_sys_in_filter_window_edge_test": [
        (
            "CHK-AXI-FILTER-OKAY",
            "AXI_FILTER_OKAY",
            "page interior OKAY; adjacent page each side DECERR+poison",
        ),
    ],
    "smu_sys_in_filter_reprogram_shrink_test": [
        ("CHK-AXI-FILTER-OKAY", "AXI_FILTER_OKAY", "shrink restores BlockByDefault"),
    ],
    # --- P4 ---
    "smc_efuse_secure_tm_force_test": [
        ("CHK-STM-FORCE", "SECURE_TM_FORCE", "0→1 needs a stimulus path onto secure_tm_i"),
    ],
    "smc_wdt_ip0_isolate_clamp_test": [
        ("CHK-WDT-CLAMP", "WDT_FIRST_CLAMP0", "isolate clamp mux contrast"),
    ],
    "smu_macro_axil_pll_pvt_route_test": [
        ("CHK-MACRO-ROUTE", "MACRO_DECERR_POISON", "macro AXIL DECERR poison"),
    ],
    "smu_octs_timer_count_csr_test": [
        ("CHK-OCTS-ADVANCE", "OCTS_COUNT_ADVANCE", "TIMER_COUNT advances"),
    ],
    "smu_ic_reset_ss_domain_matrix_test": [
        ("CHK-IC-SS", "IC_RESET_SS_COLD_OVRD", "SS cold/warm ovrd exclusive"),
    ],
    "smu_dtp_bsr_extest_loopback_test": [
        (
            "CHK-BSR-EXTEST",
            "BSR_EXTEST_TDO_MATCH",
            "TB BSR scan loopback TDO (declared stub; pad BSR out of scope)",
        ),
    ],
    "smu_telemetry_atb_handshake_test": [
        ("CHK-TEL-ATB", "TEL_ATREADY_HS", "ATB handshake"),
    ],
    # --- wrapper ---
    "smu_wrapper_elaboration_test": [
        ("CHK-WRAP-ELAB", "WRAP_ELAB_OK", "wrapper elab/reset contract"),
    ],
}


def primary_token(testcase: str) -> str | None:
    rows = TEST_EVIDENCE.get(testcase)
    return rows[0][1] if rows else None


def tokens_for(testcase: str) -> list[str]:
    return [t for _, t, _ in TEST_EVIDENCE.get(testcase, [])]
