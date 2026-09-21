# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Canonical evidence map for OSS SMU tests.

Each test lists (CHK_ID, TOKEN, EXPECT) triples. Scoreboard logs
``EVIDENCE: <TOKEN>``.
``CHK-NONVAC`` is emitted by SmuScoreboard.check_phase when checks > 0.

What a TOKEN carries: a passing ``expect_*`` compare logged it, bound either
by an explicit ``evidence=`` argument or by the TOKEN/CHK id appearing in the
check name. EXPECT is free-text contract wording for readers and reviewers;
no code compares it against an observed value. It says what the bound compare
proved, not what the test as a whole claims.

Keys name the pyuvm type name of the test body. Every key names a test that
is enrolled in a testlist or has a body under ``cocotb/tests`` or
``cocotb_wrapper/tests``. This package is the ``env`` namespace package: the
shared half lives here under ``cocotb/env`` and the wrapper-only half under
``cocotb_wrapper/env``; both directories are on the wrapper flow's path. A testcase that builds an ``SmuScoreboard`` and
carries no rows here must be listed in ``UNMAPPED_TESTS``;
``prove_mapped_features`` raises otherwise. Both base tests call
``prove_mapped_features`` after the scenario; the wrapper base test does so
only for leaves with ``use_shared_env = True`` and logs one
``EVIDENCE MAP GATE SKIPPED`` line for the others, whose verdict lives in
their own sequence or scoreboard.
"""

from __future__ import annotations

# testcase -> recorded reason for running with no (CHK_ID, TOKEN, EXPECT) rows
UNMAPPED_TESTS: dict[str, str] = {
    "smu_ext_axi_global_addr_smoke_test": (
        "present but not enrolled: the OSS s_axi is a LOCAL aperture, so "
        "GLOBAL_BASE + offset DECERRs. Rows are withheld until enrollment; "
        "disposition in hw/sys/smu/doc/dv/SMU_DEFERRED_DISPOSITION.adoc"
    ),
}

# testcase -> ordered checkbox contracts (FEATURE_LIST / VPLAN aligned)
TEST_EVIDENCE: dict[str, list[tuple[str, str, str]]] = {
    "smu_axi_alias_remap_manager_scope_test": [
        (
            "CHK-ALIAS-REMAP-SCOPE-S3",
            "CHK-ALIAS-REMAP-SCOPE-S3",
            "jtag2axi alias_remapped write/readback",
        ),
    ],
    "smu_axi_atomic_operation_test": [
        ("CHK-AXI-NON-ATOP", "AXI_NON_ATOP_OK", "non-ATOP SMN path completes"),
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
            "SEP=0 inbound smu_axi_in reaches SMC via direct IW: BlockByDefault "
            "DECERR with matching BID/RID, paired with the S1-CONTROL row",
        ),
        (
            "CHK-SMU-PORT-SMN-AXI-S1-CONTROL",
            "CHK-SMU-PORT-SMN-AXI-S1-CONTROL",
            "same master, same probe: inbound0 window opened by JTAG2AXI, read "
            "returns OKAY and the VERSION_LO RDL reset value; window cleared "
            "afterwards and the DECERR returns",
        ),
        (
            "CHK-SMU-SEP-PARAM-S2",
            "CHK-SMU-SEP-PARAM-S2",
            "SEP=0 direct SMC↔external ID converters elaborated",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK-TIMEOUT-PATHS", "bounded AXI waits with last-state"),
        ("CHK-NONVAC", "CHK-NONVAC", "ordered fence S1<S2<S3<S4<PASS"),
    ],
    "smu_axi_filter_allow_ns_test": [
        ("CHK-SMU-ALLOW-NS-S1", "CHK-SMU-ALLOW-NS-S1", "allow_ns=0 secure OKAY / NS DECERR"),
        ("CHK-SMU-ALLOW-NS-S2", "CHK-SMU-ALLOW-NS-S2", "dual-slot admits secure and NS"),
        ("CHK-SMU-ALLOW-NS-S3", "CHK-SMU-ALLOW-NS-S3", "clear returns DECERR for both"),
    ],
    "smu_axi_in_burst_outstanding_test": [
        (
            "CHK-AXIIN-DEPTH",
            "CHK-AXIIN-DEPTH",
            "the inbound port accepts at least two address handshakes before it returns "
            "the first response, on the read train and on the write train, and every "
            "read returns the VERSION_LO RDL reset value with OKAY",
        ),
        (
            "CHK-AXIIN-DEPTH-ORDER",
            "CHK-AXIIN-DEPTH-ORDER",
            "sixty-four inbound writes in flight under one AWID leave the last value "
            "written in SCRATCH_COLD",
        ),
        (
            "CHK-AXIIN-BURST",
            "CHK-AXIIN-BURST",
            "an inbound WRAP burst read at a register target is refused with SLVERR",
        ),
        (
            "CHK-AXIIN-BURST-FIXED",
            "CHK-AXIIN-BURST-FIXED",
            "an inbound multi-beat FIXED burst write at a register target is refused with SLVERR",
        ),
    ],
    "smu_axi_filter_in_instance_matrix_test": [
        (
            "CHK-FILTER-IN-INSTANCES-S1",
            "CHK-FILTER-IN-INSTANCES-S1",
            "inbound filter instances 0,1,7,14,15 programmed and read back at their indexed bases",
        ),
    ],
    "smu_axi_filter_out_instance_matrix_test": [
        (
            "CHK-FILTER-OUT-INSTANCES-S1",
            "CHK-FILTER-OUT-INSTANCES-S1",
            "outbound filter instances 0,1,8,15 programmed and read back at their indexed bases",
        ),
    ],
    "smu_axi_id_width_conversion_test": [
        (
            "CHK-AXI-ID-WIDTH",
            "AXI_ID_WIDTH_OK",
            "an 8-bit-ID ext_in read reaches an SMC register through the SEP=1 crossbar and "
            "returns OKAY with RID == ARID and the RDL reset value",
        ),
    ],
    "smu_axi_prot_encoding_decode_test": [
        (
            "CHK-SMU-PROT-S9-MATRIX",
            "CHK-SMU-PROT-S9-MATRIX",
            "eight-way AxPROT matrix on VERSION_LO",
        ),
    ],
    "smu_axi_xbar_structure_test": [
        ("CHK-XBAR-POS-NO-GEN-SEP", "CHK-XBAR-POS-NO-GEN-SEP", "gen_sep absent under SEP=0"),
        ("CHK-XBAR-POS-IW", "CHK-XBAR-POS-IW", "gen_no_sep ID converters resolve"),
        (
            "CHK-XBAR-ABSENT-NO-SEP",
            "CHK-XBAR-ABSENT-NO-SEP",
            "smu_axi_xbar absent under gen_no_sep",
        ),
    ],
    "smu_boot_stall_jtag_cold_reset_matrix_test": [
        ("CHK-STALL-STICKY", "STALL_COLD_STICKY", "stall survives cold"),
        ("CHK-STALL-TRST", "STALL_TRST_CLEAR", "TRST clears stall"),
        ("CHK-STALL-REASSERT", "STALL_REASSERT_STICKY", "re-assert sticky"),
    ],
    "smu_boot_stall_vs_ic_reset_priority_test": [
        ("CHK-STALL-VS-IC", "STALL_VS_IC_RESET", "IC_RESET does not clear stall"),
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
            "DTP[0] unchanged by the TB clock-stop pins while DTP[8:1] follows them",
        ),
        (
            "CHK-NONVAC",
            "CHK-NONVAC",
            "ordered simulation-time fence S1<S2<S3<S4<S5<S6<S7<S8<S9<PASS",
        ),
    ],
    "smu_dft_dtp_boot_stall_test": [
        ("CHK-STALL-STICKY", "STALL_COLD_STICKY", "stall survives cold"),
        ("CHK-STALL-REASSERT", "STALL_REASSERT_STICKY", "re-assert does not re-gate"),
    ],
    "smu_dft_gpio_boot_stall_test": [
        ("CHK-STALL-STICKY", "STALL_COLD_STICKY", "GPIO stall sticky across cold"),
        ("CHK-STALL-REASSERT", "STALL_REASSERT_STICKY", "re-assert does not re-gate"),
    ],
    "smu_dtp_bsr_extest_loopback_test": [
        (
            "CHK-BSR-EXTEST",
            "BSR_EXTEST_TDO_MATCH",
            "TB BSR scan loopback TDO (declared stub; pad BSR out of scope)",
        ),
    ],
    "smu_dtp_scan_chain_boundary_test": [
        (
            "CHK-SMU-IJTAG-GATE",
            "CHK-SMU-IJTAG-GATE",
            "none of the three iJTAG host selects asserts over a whole IDCODE "
            "IR+DR scan, counted on jtag_tck",
        ),
        (
            "CHK-SMU-IJTAG-CHAIN",
            "CHK-SMU-IJTAG-CHAIN",
            "under SELECT_IJTAG the DR closed through the wrapper scan pins "
            "returns each payload exactly IJTAG_SIB_COUNT bits late, for "
            "five directed and three seeded-random nonzero payloads",
        ),
        (
            "CHK-SMU-IJTAG-SIB",
            "CHK-SMU-IJTAG-SIB",
            "Update-DR latches the SIB enables and the next Capture-DR reads "
            "them back, for each SIB alone, all three, and none; the matching "
            "host select asserts only while that SIB is open",
        ),
        (
            "CHK-SMU-STAP-IO-SELECT",
            "CHK-SMU-STAP-IO-SELECT",
            "an unselected I/O STAP drives no TDO enable and its host TMS does "
            "not follow the primary TAP; after a TAP_3DCR select the enable "
            "covers exactly IR+DR TCKs, host TMS matches on every TCK, and the "
            "extra STAP stays quiet",
        ),
    ],
    "smu_dtp_bsr_ijtag_scan_test": [
        ("CHK-DTP-BSR-EXTEST-SELECT", "CHK-DTP-BSR-EXTEST-SELECT", "EXTEST selects BSR TCK"),
    ],
    "smu_dtp_io_stap_smoke_test": [
        ("CHK-DTP-IO-STAP-SCAN", "CHK-DTP-IO-STAP-SCAN", "IO STAP host TCK observe"),
    ],
    "smu_dtp_jtag2axi_abort_mid_op_test": [
        ("CHK-J2A-ABORT", "J2A_ABORT_RECOVER", "abort mid-BUSY recovers"),
    ],
    "smu_dtp_jtag2axi_back_to_back_error_ok_test": [
        ("CHK-J2A-B2B", "J2A_B2B_OK", "DECERR then immediate SUCCESS"),
    ],
    "smu_dtp_jtag2axi_smc_error_path_test": [
        ("CHK-J2A-DECERR", "J2A_DECERR_POISON", "unmapped access returns DECERR"),
        ("CHK-J2A-RECOVERY", "J2A_RECOVERY_OK", "VERSION_LO SUCCESS after error"),
    ],
    "smu_dtp_jtag2axi_smc_rw_matrix_test": [
        ("CHK-J2A-RW-MATRIX", "J2A_RW_MATRIX_OK", "partial WSTRB 0x55/0xAA merge"),
    ],
    "smu_dtp_jtag2axi_wstrb_partial_sticky_test": [
        ("CHK-J2A-WSTRB-NBR", "J2A_WSTRB_NEIGHBOR", "partial merge; neighbor intact"),
    ],
    "smu_dtp_jtag_smc_cpu_register_test": [
        ("CHK-JTAG2AXI-RW", "JTAG2AXI_RW_OK", "SCRATCH_15 two-pattern R/W"),
        ("CHK-CPU-REG-STALL", "CPU_REG_STALL", "DEBUG_CONTROL boot_stall hold"),
    ],
    "smu_dtp_jtag_smoke_test": [
        (
            "CHK-DTP-JTAG-PTAP-S1",
            "CHK-DTP-JTAG-PTAP-S1",
            "IDCODE instruction returns configured IDCODE fields",
        ),
        ("CHK-DTP-JTAG-PTAP-S2", "CHK-DTP-JTAG-PTAP-S2", "BYPASS single-bit TDI/TDO latency"),
        (
            "CHK-DTP-JTAG-PTAP-S3",
            "CHK-DTP-JTAG-PTAP-S3",
            "TRST and POR return TAP to Test-Logic-Reset",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK-TIMEOUT-PATHS", "bounded JTAG waits with last TAP state"),
        ("CHK-NONVAC", "CHK-NONVAC", "ordered fence S1<S2<S3<S4<S5<PASS"),
    ],
    "smu_dtp_otp_smc_complete_rw_test": [
        ("CHK-OTP-MAP-RW", "OTP_MAP_RW_OK", "OTP+fabric+shadow match on RESERVED"),
    ],
    "smu_dtp_otp_smc_map_rw_test": [
        ("CHK-OTP-SMC-MAP-RW", "CHK-OTP-SMC-MAP-RW", "SMC OTP MAP SPARE[0] R/W"),
    ],
    "smu_dtp_otp_smc_series_error_test": [
        (
            "CHK-OTP-SMC-DECODE-SLVERR",
            "CHK-OTP-SMC-DECODE-SLVERR",
            "OTP decode hole returns SLVERR",
        ),
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
    "smu_dtp_smc_stap_smoke_test": [
        (
            "CHK-DTP-SMC-STAP-IDCODE",
            "CHK-DTP-SMC-STAP-IDCODE",
            "selected SMC STAP sees the same TMS edge count as the PTAP during IDCODE",
        ),
    ],
    "smu_ext_boot_seq_gate_test": [
        ("CHK-BOOT-SEQ-GATE", "CHK-BOOT-SEQ-GATE", "gate holds then releases fuse_reset"),
        ("CHK-PRIMARY-NOT-GATED", "CHK-PRIMARY-NOT-GATED", "primary still releases while gated"),
        ("CHK-TIMEOUT-PATHS", "CHK-TIMEOUT-PATHS", "bounded sample waits with last state"),
        ("CHK-NONVAC", "CHK-NONVAC", "ordered fence S2<S3<S4<PASS"),
    ],
    "smu_fabric_reg_bar_wr_test": [
        (
            "CHK-SUB-AXIL-LOCAL-S2",
            "CHK-SUB-AXIL-LOCAL-S2",
            "fabric config CSR write/readback held at every listed destination",
        ),
    ],
    "smu_i3c_mem_port_connectivity_test": [
        (
            "CHK-SUB-AXIL-LOCAL-S1",
            "CHK-SUB-AXIL-LOCAL-S1",
            "every local peripheral destination answered SUCCESS over JTAG2AXI",
        ),
    ],
    "smu_ic_reset_dual_domain_illegal_test": [
        ("CHK-IC-DUAL", "IC_RESET_DUAL_PACK", "dual packed ovrd; no bleed"),
    ],
    "smu_ic_reset_smc_multi_domain_test": [
        ("CHK-IC-DOMAIN", "IC_RESET_DOMAIN_EXCL", "one domain ovrd exclusive"),
    ],
    "smu_ic_reset_ss_domain_matrix_test": [
        (
            "CHK-IC-SS-COLD",
            "IC_RESET_SS_COLD_OVRD",
            "SS_COLD0 IC_RESET override asserts ss_cold_reset_n_ovrd[0] and drives its value low",
        ),
        (
            "CHK-IC-SS-WARM",
            "IC_RESET_SS_WARM_OVRD",
            "SS_WARM0 IC_RESET override asserts ss_warm_reset_n_ovrd[0] and drives its value low",
        ),
        (
            "CHK-IC-SS-EXCL",
            "IC_RESET_SS_EXCL",
            "fuse/warm/cool/cold and the other SS override stay idle while one SS override asserts",
        ),
    ],
    "smu_jtag2axi_vs_smn_same_csr_race_test": [
        ("CHK-RACE-J2A-SMN", "RACE_J2A_SMN", "coherent dual-agent winner"),
    ],
    "smu_jtag_chain_enhanced_test": [
        (
            "CHK-JTAG-IDCODE",
            "JTAG_IDCODE_OK",
            "IDCODE reads the default DTP IDCODE at every swept TCK period",
        ),
        (
            "CHK-JTAG-BYPASS",
            "JTAG_BYPASS_OK",
            "BYPASS returns the expected shifted pattern at every swept TCK period",
        ),
        (
            "CHK-JTAG-CHAIN-ENHANCED",
            "JTAG_CHAIN_ENHANCED_OK",
            "all required TCK labels ran at their programmed periods",
        ),
    ],
    "smu_jtag_reset_override_test": [
        ("CHK-IC-DEFAULT", "IC_RESET_DEFAULT", "IC_RESET default all-ones"),
        ("CHK-IC-DOMAIN", "IC_RESET_DOMAIN_EXCL", "single domain override exclusive"),
    ],
    "smu_no_sep_configuration_test": [
        ("CHK-SEP0-LC", "CHK-SEP0-LC", "lc_state_o==0xf0 stable >=16 cycles"),
        (
            "CHK-SEP0-EGRESS",
            "CHK-SEP0-EGRESS",
            "a J2A write outside both SMC apertures advances the outbound write "
            "counter and the read brings the pattern back",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK-TIMEOUT-PATHS", "bounded waits with last-state"),
        ("CHK-NONVAC", "CHK-NONVAC", "ordered fence S1<S2<S3<S4<PASS"),
    ],
    "smu_otp_bridges_under_dbg_disable_test": [
        (
            "CHK-OTP-DBG-POSTURE",
            "CHK-OTP-DBG-POSTURE",
            "the SEP shadow image puts the chiplet in a lifecycle state whose posture "
            "disables dbg_disable.smc_jtag2axi, and lc_state carries that state",
        ),
        (
            "CHK-OTP-FABRIC-BLOCKED",
            "CHK-OTP-FABRIC-BLOCKED",
            "a SINGLE_OP on the primary TAP launches neither AW nor AR on the "
            "DTP -> SMC debug AXI port while that posture holds",
        ),
        (
            "CHK-OTP-SMC-RW-WHILE-BLOCKED",
            "CHK-OTP-SMC-RW-WHILE-BLOCKED",
            "SMC OTP JTAG2AXI write and readback of SMC eFuse MAP SPARE[0] both "
            "complete with SUCCESS in the same blocked-fabric state",
        ),
        (
            "CHK-OTP-SEP-LC-READ-WHILE-BLOCKED",
            "CHK-OTP-SEP-LC-READ-WHILE-BLOCKED",
            "SEP OTP JTAG2AXI read of SEP eFuse MAP LC_STATE returns the "
            "{~raw, raw} word the shadow image programmed",
        ),
        (
            "CHK-OTP-SEP-RW-WHILE-BLOCKED",
            "CHK-OTP-SEP-RW-WHILE-BLOCKED",
            "SEP OTP JTAG2AXI write and readback of SEP eFuse MAP SPARE0 both "
            "complete with SUCCESS in the same blocked-fabric state",
        ),
        (
            "CHK-OTP-SEP-BANK-CTRL-READ",
            "CHK-OTP-SEP-BANK-CTRL-READ",
            "a SEP OTP JTAG2AXI read of the shim window leaves the SEP on the "
            "eFuse bank-control port and returns EFUSE_BANK_INIT_TIME's RDL reset",
        ),
        (
            "CHK-OTP-SEP-BANK-CTRL-WRITE",
            "CHK-OTP-SEP-BANK-CTRL-WRITE",
            "the same port takes a written EFUSE_BANK_INIT_TIME value and reads it back",
        ),
        (
            "CHK-OTP-DBG-POSTURE-HELD",
            "CHK-OTP-DBG-POSTURE-HELD",
            "dbg_disable.smc_jtag2axi is still asserted after all OTP traffic, so the "
            "completions above are attributable to the blocked-fabric state",
        ),
    ],
    "smu_otp_vs_fabric_map_race_test": [
        ("CHK-RACE-OTP-FAB", "RACE_OTP_FABRIC", "shadow == last writer"),
    ],
    "smu_periph_ext_window_test": [
        (
            "CHK-PERIPH-EXT-SHIM",
            "CHK-PERIPH-EXT-SHIM",
            "EFUSE_SHIM_CTRL.EFUSE_BANK_INIT_TIME, at the block base the generated SMC "
            "map gives, reads its RDL reset value over the eFuse bank-control AXI-Lite "
            "port, takes a written value and is restored",
        ),
        (
            "CHK-PERIPH-EXT-STRAPS",
            "CHK-PERIPH-EXT-STRAPS",
            "STRAPS_LO and STRAPS_HI at the boot-ROM documented supplementary-region "
            "address both answer SUCCESS",
        ),
        (
            "CHK-PERIPH-EXT-UNMAPPED",
            "CHK-PERIPH-EXT-UNMAPPED",
            "the first page above every allocation the sources record, still inside "
            "the window, DECERRs (DV rule; see the VPLAN specification gap)",
        ),
        (
            "CHK-PERIPH-EXT-APERTURE",
            "CHK-PERIPH-EXT-APERTURE",
            "REGION_SIZE shrunk so the local aperture ends at the window sends the "
            "same shim read out of the chiplet instead",
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
        ("CHK-DTP-XTRIG-CTM-S3", "CHK-DTP-XTRIG-CTM-S3", "Bits [1:0] remain reserved for SMC"),
        ("CHK-TIMEOUT-PATHS", "CHK-TIMEOUT-PATHS", "bounded waits with last-state"),
        ("CHK-NONVAC", "CHK-NONVAC", "ordered fence S1<S2<S3<S4<S5<S6<PASS"),
    ],
    "smu_smc_boundary_io_test": [
        (
            "CHK-SMU-NDMRESET-REQ",
            "CHK-SMU-NDMRESET-REQ",
            "NDMRESET_CLUSTER_COUNT reads within the 1..32 clusters ndm_reset.rdl allows "
            "and NDM_RESET.NDMRESET_REQUEST mirrors smc_ndmreset_request_i over that "
            "many lanes for two patterns and follows it back to zero",
        ),
        (
            "CHK-SMU-NDMRESET-PROC",
            "CHK-SMU-NDMRESET-PROC",
            "smc_ndmreset_process_o carries NDMRESET_PROCESS[NDMRESET_CLUSTER_COUNT-1:0], "
            "including the all-ones write that pins the port width to the reported count",
        ),
        (
            "CHK-SMU-EXT-IRQ",
            "CHK-SMU-EXT-IRQ",
            "smc_ext_interrupts_i lanes appear bit for bit on cpu_interrupts_o[31:0], the "
            "external-interrupt slice of the SMC CPU interrupt vector map, and the level "
            "inputs release with the pins; PLIC pending state is not observed",
        ),
        (
            "CHK-SMU-SS-CONFIG",
            "CHK-SMU-SS-CONFIG",
            "ss_config_o carries RESET_UNIT.SS_CONFIG with SS_CONFIG_LOCK open, and clears with it",
        ),
        (
            "CHK-SMU-SYNC-IRQ",
            "CHK-SMU-SYNC-IRQ",
            "sync_irq_o is RESET_UNIT.SYNC_REG.sync, set and cleared",
        ),
        (
            "CHK-SMU-ISOLATE-REQ",
            "CHK-SMU-ISOLATE-REQ",
            "isolate_req_o carries the ISOLATE_REQ_REG software term",
        ),
        (
            "CHK-SMU-DFT-ABORT",
            "CHK-SMU-DFT-ABORT",
            "mem_repair_abort_i and mbist_abort_i reach DFX_CTRL.STATUS_SMU and "
            "the fields hold after both pins are released",
        ),
        (
            "CHK-SMU-FLR-ISOLATE",
            "CHK-SMU-FLR-ISOLATE",
            "a cfg_flr_pf_active_i rising edge sets ISOLATE_REQ_SMC_REG, which "
            "raises isolate_req_o through ISOLATE_REQ_SMCEN_REG and "
            "skip_mem_repair_o; the latch holds when the pin drops and only a "
            "software write releases both",
        ),
    ],
    "smu_smc_dtp_jtag2axi_smoke_test": [
        ("CHK-JTAG2AXI-SMOKE-SCRATCH", "CHK-JTAG2AXI-SMOKE-SCRATCH", "J2A scratch write/readback"),
    ],
    "smu_smc_mailbox_int_test": [
        (
            "CHK-SMC-MBX-IRQ-EXT-S2",
            "CHK-SMC-MBX-IRQ-EXT-S2",
            "DUT port smc_ext_mailbox_interrupts_o is NUM_MAILBOXES=32 wide; "
            "mailbox 0 / 31 IRQs move bits 0 / 31",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK-TIMEOUT-PATHS", "bounded waits with last-state"),
        ("CHK-NONVAC", "CHK-NONVAC", "ordered fence S1<S2<S3<S4<PASS"),
    ],
    "smu_smc_mailbox_sanity_test": [
        ("CHK-MBX-IRQEN", "SMC_MBX_CSR_OK", "outbound-0 IRQEN write/readback"),
    ],
    "smu_smc_reset_ctrl_test": [
        ("CHK-RST-PRIMARY", "RST_PRIMARY_SMC_1", "SMC primary reset released"),
        ("CHK-RST-COLD-STABLE", "RST_COLD_STABLE_1", "cold stable released"),
    ],
    "smu_smc_security_demote_pm_test": [
        ("CHK-DEMOTE-TIEOFF", "DEMOTE_TIEOFF_OBS", "SEP=0 demote hardwire observe"),
    ],
    "smu_smc_boundary_lane_sweep_test": [
        (
            "CHK-SMU-LANE-EXT-IRQ",
            "CHK-SMU-LANE-EXT-IRQ",
            "all 256 smc_ext_interrupts_i lanes appear bit for bit on the "
            "external-interrupt slice of cpu_interrupts_o for all-ones, all-zeros "
            "and both alternating patterns, and every lane is observed both high "
            "and low",
        ),
        (
            "CHK-SMU-LANE-ISOLATE-REQ",
            "CHK-SMU-LANE-ISOLATE-REQ",
            "isolate_req_o carries the RESET_UNIT.ISOLATE_REQ_REG software term on "
            "all 32 lanes, each lane observed set and cleared against the CSR "
            "read-back",
        ),
        (
            "CHK-SMU-LANE-SS-CONFIG",
            "CHK-SMU-LANE-SS-CONFIG",
            "with SS_CONFIG_LOCK read open, ss_config_o carries RESET_UNIT.SS_CONFIG "
            "on all 32 lanes for all-ones, both alternating patterns and the RDL "
            "reset value it is restored to",
        ),
        (
            "CHK-SMU-LANE-MBX-IRQ",
            "CHK-SMU-LANE-MBX-IRQ",
            "each of the 32 outbound mailboxes raises its own "
            "smc_ext_mailbox_interrupts_o bit through IRQEN.WTIRQ and an outbound "
            "push, and clearing IRQEN retires that bit alone",
        ),
        (
            "CHK-SMU-LANE-GPIO",
            "CHK-SMU-LANE-GPIO",
            "with all 65 pads taken from their LSIO owners and armed as active-high "
            "levels, driving every pad raises every gpio_interrupt_o lane and sets "
            "DATA_CTRL.PAD2CORE on every interface, and both follow the pads back "
            "down",
        ),
        (
            "CHK-SMU-LANE-UART-IRQ",
            "CHK-SMU-LANE-UART-IRQ",
            "each of the four UART instances raises uart_interrupt_o on its own lane "
            "from IER.ETBEI, reports the transmitter-holding-register-empty code in "
            "IIR, and retires that lane on the IIR read",
        ),
    ],
    "smu_smc_peripheral_irq_test": [
        (
            "CHK-SMU-GPIO-IRQ",
            "CHK-SMU-GPIO-IRQ",
            "GPIO pin 0 taken from its LSIO owner and armed as an active-high "
            "level: driving the pad raises gpio_interrupt_o[0] and "
            "DATA_CTRL.PAD2CORE with no other lane moving, and both release "
            "with the pad",
        ),
        (
            "CHK-SMU-UART-IRQ",
            "CHK-SMU-UART-IRQ",
            "with the UART clock gate read open, enabling IER.ETBEI raises "
            "uart_interrupt_o[0] alone, IIR reports pending with the INTERRUPT_ID "
            "code the UART RDL assigns to Transmitter Holding Register Empty, and "
            "the IIR read retires it",
        ),
    ],
    "smu_sep_secure_tm_test": [
        (
            "CHK-SMU-SECURE-TM",
            "CHK-SMU-SECURE-TM",
            "across three cold resets secure_tm_o clears under the reset, stays "
            "low from a strap change made under reset until the SEP "
            "fuse-sense-done edge, carries the changed value after the edge "
            "rather than the value present when the reset asserted, and ignores "
            "the strap between those windows in both directions",
        ),
    ],
    "smu_smc_rom_boot_min_pass_test": [
        (
            "CHK-SMC-ROM-BOOT-MAGIC",
            "CHK-SMC-ROM-BOOT-MAGIC",
            "SMC CPU_CTRL scratch0 reads the word the checked-in ROM stub stores, "
            "so the fetch, the execution and the CSR write all landed",
        ),
        (
            "CHK-SMC-ROM-BOOT-FETCH",
            "CHK-SMC-ROM-BOOT-FETCH",
            "the SMC ROM read counter advanced across the boot, so the instruction "
            "stream came out of the ROM macro rather than a residual scratch image",
        ),
        (
            "CHK-SMC-ROM-BOOT-CSR-VISIBLE",
            "CHK-SMC-ROM-BOOT-CSR-VISIBLE",
            "an external master reading SMC CPU_CTRL scratch0 at its architectural "
            "address over the SMC fabric JTAG2AXI bridge sees the same magic, so the "
            "store landed in the CSR and not only in a testbench mirror",
        ),
    ],
    "smu_smc_smoke_test": [
        (
            "CHK-SMC-FAB-DUAL-NET-S2",
            "CHK-SMC-FAB-DUAL-NET-S2",
            "AXI4-Lite LP to local_peripheral + config_register",
        ),
        ("CHK-SMC-FAB-DUAL-NET-S3", "CHK-SMC-FAB-DUAL-NET-S3", "AXI4 + AXI4-Lite both 64-bit data"),
        ("CHK-TIMEOUT-PATHS", "CHK-TIMEOUT-PATHS", "bounded waits with last-state"),
        ("CHK-NONVAC", "CHK-NONVAC", "ordered fence S1<S2<S3<S4<PASS"),
    ],
    "smu_smc_wdt_boundary_timeout_test": [
        (
            "CHK-SMU-WDT-FIRST",
            "CHK-SMU-WDT-FIRST",
            "CORE0 armed with WDOGRSTEN as well as WDOGENALWAYS and WDOGZEROCMP "
            "raises smc_wdt_first_timeout_o, with WDOGIP0 set at the same time "
            "and both clear beforehand",
        ),
        (
            "CHK-SMU-WDT-SECOND",
            "CHK-SMU-WDT-SECOND",
            "the held first timeout runs the CPU_CTRL.WDT_TIMEOUT counter out "
            "to smc_wdt_second_timeout_o, and the SMC warm reset drops with it",
        ),
    ],
    "smu_smc_wdt_sanity_test": [
        ("CHK-WDT-UNLOCK", "WDT_UNLOCK_OK", "WDT unlock SUCCESS"),
    ],
    "smu_smc_wdt_timeout_irq_test": [
        ("CHK-WDT-IP0", "WDT_WDOGIP0", "WDOGIP0 sets after enable+CMP"),
    ],
    "smu_sys_in_filter_program_jtag_test": [
        ("CHK-AXI-FILTER-OKAY", "AXI_FILTER_OKAY", "after program window OKAY"),
    ],
    "smu_sys_in_filter_reprogram_shrink_test": [
        ("CHK-AXI-FILTER-OKAY", "AXI_FILTER_OKAY", "shrink restores BlockByDefault"),
    ],
    "smu_sys_in_filter_window_edge_test": [
        (
            "CHK-AXI-FILTER-OKAY",
            "AXI_FILTER_OKAY",
            "VERSION_LO inside the programmed page returns OKAY",
        ),
    ],
    "smu_telemetry_atb_capture_test": [
        (
            "CHK-SMU-TEL-RESET",
            "CHK-SMU-TEL-RESET",
            "receiver 0 reads STATUS.BUFFER_EMPTY set with PROBE_ID and "
            "COUNTER_VLDS clear before any beat is driven",
        ),
        (
            "CHK-SMU-TEL-CAPTURE",
            "CHK-SMU-TEL-CAPTURE",
            "with the telemetry clock gate proved open, a complete last-flagged "
            "ATB message whose every beat handshook on telemetry_atready_o "
            "leaves the buffer non-empty, reports the framed probe id and one "
            "valid bit per counter sent, and CTRL.BUFFER_POP returns it to empty",
        ),
        (
            "CHK-SMU-TEL-FLUSH",
            "CHK-SMU-TEL-FLUSH",
            "CTRL.TELEMETRY_TX_FLUSH raises telemetry_afvalid_o and the request "
            "holds while telemetry_afready_i is low; raising it retires the "
            "request at the pin and clears the register field",
        ),
    ],
    "smu_system_timer_octs_test": [
        (
            "CHK-OCTS-PRIMARY-STRAP",
            "CHK-OCTS-PRIMARY-STRAP",
            "SMC_ATTRIBUTES.chiplet_is_primary reads the TB strap value",
        ),
        (
            "CHK-OCTS-COUNT-MONOTONIC",
            "CHK-OCTS-COUNT-MONOTONIC",
            "OCTS timer pin count advances after START",
        ),
        (
            "CHK-OCTS-CSR-COUNT",
            "CHK-OCTS-CSR-COUNT",
            "TIMER_COUNT_{HI,LO} read over J2A lands between the tb_timer_count "
            "samples taken either side of the read",
        ),
    ],
    "smu_telemetry_atb_handshake_test": [
        ("CHK-TEL-ATB", "TEL_ATREADY_HS", "ATB handshake"),
    ],
    # --- P0 composition and bring-up leaves on the production wrapper ---
    # These set use_shared_env = True, so prove_mapped_features runs for them
    # and every row below has to be logged by a passing compare.
    # CHK-NONVAC is deliberately not a row here: SmuScoreboard.check_phase logs
    # it after run_phase has already run the prover, and its own zero-check
    # refusal covers the same ground.
    "smu_boundary_port_composition_test": [
        (
            "CHK-SMU-EXT-SMN-S4",
            "CHK-SMU-EXT-SMN-S4",
            "the SMC-side ID-width converter presents the specified 6-bit subsystem ID",
        ),
        (
            "CHK-SMU-INT-AGG-S1",
            "CHK-SMU-INT-AGG-S1",
            "smc_ext_interrupts_i is 256 wide, the SMC external interrupt count",
        ),
        (
            "CHK-SMU-XTRIG-CTP-S1",
            "CHK-SMU-XTRIG-CTP-S1",
            "all four CTP groups are 16 wide, the XTRIG_NUM_CTP default",
        ),
        ("CHK-SMU-XTRIG-CTP-S6", "CHK-SMU-XTRIG-CTP-S6", "zero-tied CTP data inputs stay static"),
        ("CHK-SMU-LC-STATE-S1", "CHK-SMU-LC-STATE-S1", "lc_state_o is 8 bits, 2*LC_STATE_WIDTH"),
        (
            "CHK-SMU-LC-DEMOTE-S1",
            "CHK-SMU-LC-DEMOTE-S1",
            "both lcc_demote_state outputs are 2 bits",
        ),
        (
            "CHK-SMU-EFUSE-SHIM-SMC-S3",
            "CHK-SMU-EFUSE-SHIM-SMC-S3",
            "smc_shadow_regs reaches the boundary at full width and value",
        ),
        (
            "CHK-SMU-FUSE-SENSE-S4",
            "CHK-SMU-FUSE-SENSE-S4",
            "skip_mem_repair_o is one bit and clear with no isolation request pending",
        ),
        (
            "CHK-SMU-SSRESET-S2",
            "CHK-SMU-SSRESET-S2",
            "ss_reset_ctrl_o has 32 elements that share one width",
        ),
        (
            "CHK-SMU-SSRESET-S4",
            "CHK-SMU-SSRESET-S4",
            "ss_config_o is 32 bits and presents the SS_CONFIG reset value",
        ),
    ],
    "smu_clock_domain_composition_test": [
        (
            "CHK-SMU-CLK-DOMAINS-S2",
            "CHK-SMU-CLK-DOMAINS-S2",
            "secondary clocks toggle at their own rate",
        ),
        (
            "CHK-SMU-CLK-DOMAINS-S3",
            "CHK-SMU-CLK-DOMAINS-S3",
            "each domain reset is released at its consumer",
        ),
        (
            "CHK-SMU-CLK-DOMAINS-S4",
            "CHK-SMU-CLK-DOMAINS-S4",
            "telemetry stays released and clocked while primary/periph fall",
        ),
    ],
    "smu_cold_reset_async_assert_test": [
        (
            "CHK-SMU-RST-COLD-S1",
            "CHK-SMU-RST-COLD-S1",
            "cold reset asserts with every clock static",
        ),
    ],
    # Both testlist entries (SEP=1 and SEP=0) run this one body, and
    # bind_testcase keys the map on the body name, so only the tokens both
    # legs log can be rows here. CHK-SMU-SEC-TOKEN-S1 and CHK-SMU-LC-SECDIS-S1
    # are emitted on the SEP=1 leg alone and are therefore not enforced.
    "smu_composition_parameter_test": [
        (
            "CHK-SMU-SEC-TOKEN-S2",
            "CHK-SMU-SEC-TOKEN-S2",
            "SEP_SEC_DISABLE_TOKEN is 256 bits at the wrapper and at smu and reaches smu unchanged",
        ),
        (
            "CHK-SMU-OTPAXI-SEP-S3",
            "CHK-SMU-OTPAXI-SEP-S3",
            "DTP SEP OTP pipeline depths are the specified fixed 3",
        ),
        (
            "CHK-SMU-NOSEP-S4",
            "CHK-SMU-NOSEP-S4",
            "Cfg reaches smu unchanged and each consumer parameter is its specified default",
        ),
    ],
    "smu_reset_release_sync_test": [
        (
            "CHK-SMU-RST-COLD-S2",
            "CHK-SMU-RST-COLD-S2",
            "cold-stable deassertion lands on a clk_ref_i edge",
        ),
        (
            "CHK-SMU-RST-PRIMARY-S2",
            "CHK-SMU-RST-PRIMARY-S2",
            "primary reset deassertions land on their own domain's edge",
        ),
    ],
    "smu_sep_fuse_sense_done_test": [
        (
            "CHK-SMU-FUSE-SENSE-S2",
            "CHK-SMU-FUSE-SENSE-S2",
            "sep_fuse_sense_done_o rises once, after reset release and after SEP eFuse traffic",
        ),
    ],
    "smu_smc_fuse_sense_sequence_test": [
        (
            "CHK-SMU-FUSE-SENSE-S1",
            "CHK-SMU-FUSE-SENSE-S1",
            "smc_fuse_sense_done_o rises once, after reset release and after SMC eFuse traffic",
        ),
        (
            "CHK-SMU-FUSE-SENSE-S3",
            "CHK-SMU-FUSE-SENSE-S3",
            "smc_fuse_reset_n_delayed_o releases after that rise, not with the cold reset",
        ),
    ],
    "smu_sram_auto_init_disabled_test": [
        (
            "CHK-SMU-MEMINIT-DISABLED",
            "CHK-SMU-MEMINIT-DISABLED",
            "with smc_disable_sram_auto_init_i high the zeroing sweep never "
            "starts and no zeroing write reaches the scratch RAM, yet "
            "smc_init_mem_done_o clears under cold reset and asserts and holds "
            "after release",
        ),
    ],
    "smu_sram_auto_init_done_test": [
        (
            "CHK-SMU-MEMINIT-S1",
            "CHK-SMU-MEMINIT-S1",
            "smc_init_mem_done_o is high after the bring-up sweep, clears under "
            "cold reset, and rises again after release after an observed zeroing "
            "sweep",
        ),
    ],
    "smu_xbar_connectivity_matrix_test": [
        (
            "CHK-SMU-XBAR-CONN-S7",
            "CHK-SMU-XBAR-CONN-S7",
            "unmatched ext_in read and write DECERR with the issued IDs and nothing reaches ext_out",
        ),
    ],
    "smu_xtrig_mode_composition_test": [
        (
            "CHK-SMU-XTRIG-MODE-S1",
            "CHK-SMU-XTRIG-MODE-S1",
            "the 2 SMC-reserved mode bits into DTP are zero and a pulse-sync lane never acknowledges",
        ),
        (
            "CHK-SMU-XTRIG-MODE-S2",
            "CHK-SMU-XTRIG-MODE-S2",
            "a handshake lane acknowledges and holds; the observed ack-lane count is the mode popcount",
        ),
    ],
    # --- wrapper ---
    "smu_wrapper_elaboration_test": [
        ("CHK-WRAP-ELAB", "WRAP_ELAB_OK", "wrapper elab/reset contract"),
    ],
    "smu_xtrig_ctp_pad_test": [
        (
            "CHK-SMU-CTP-DEFAULT",
            "CHK-SMU-CTP-DEFAULT",
            "CONFIG.MODE reads its RDL reset value (wire-OR) and every CTP pad "
            "control sits at the wire-OR level of the CTP signal interface table "
            "on all CROSS_TRIGGER_NETWORK_CTP_NUM lanes",
        ),
        (
            "CHK-SMU-CTP-TIEOFF",
            "CHK-SMU-CTP-TIEOFF",
            "the five pad-ring controls the CTP signal interface defines no "
            "driver for read 0 in both modes",
        ),
        (
            "CHK-SMU-CTP-P2P-MODE",
            "CHK-SMU-CTP-P2P-MODE",
            "CONFIG.MODE=1 moves the written lane's pad controls to the "
            "point-to-point level of the CTP signal interface table and leaves "
            "every other lane at its wire-OR level",
        ),
        (
            "CHK-SMU-CTP-P2P-RX",
            "CHK-SMU-CTP-P2P-RX",
            "a point-to-point request in raises the acknowledge out and shows "
            "in STATUS, and releasing the request retires it",
        ),
        (
            "CHK-SMU-CTP-ROUTE",
            "CHK-SMU-CTP-ROUTE",
            "with CT_SRC[1].CT_DST_SELECT pointing at lane 0, the trigger "
            "appears as lane 1's request out and the acknowledge in retires it",
        ),
        (
            "CHK-SMU-CTM-SRC",
            "CHK-SMU-CTM-SRC",
            "routing lane 0's destination into the CTM port of the first "
            "SMU-exposed internal lane raises xtrig_ctm_src_req_o[0], and a "
            "wire-OR edge on lane 2's request-out data input does the same",
        ),
    ],
    "smu_xtrig_ctm_illegal_phase_test": [
        ("CHK-XT-ILLEGAL", "XT_ILLEGAL_PHASE", "DTP[9:2] follows abort/double-req pin patterns"),
    ],
    "smu_xtrig_ctm_remap_test": [
        ("CHK-XT-CTM-REMAP", "XT_CTM_REMAP", "product-pin CTM remap"),
    ],
}


def primary_token(testcase: str) -> str | None:
    rows = TEST_EVIDENCE.get(testcase)
    return rows[0][1] if rows else None


def tokens_for(testcase: str) -> list[str]:
    return [t for _, t, _ in TEST_EVIDENCE.get(testcase, [])]
