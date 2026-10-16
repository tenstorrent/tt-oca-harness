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
is enrolled in ``testlists/all.toml`` or has a body under
``cocotb_wrapper/tests``. This package is the ``env`` namespace package: the
scoreboard, this map and the FCOV ledger live here under ``cocotb/env`` and
the wrapper's env config, boot scoreboard and trace monitor under
``cocotb_wrapper/env``; both directories are on the flow's path. A testcase
that builds an ``SmuScoreboard`` and carries no rows here must be listed in
``UNMAPPED_TESTS``;
``prove_mapped_features`` raises otherwise, and it also raises for a row whose
token reached the log only through a check-name match with no ``evidence=``.
The base test calls ``prove_mapped_features`` after the scenario for leaves
that score through the shared ``SmuScoreboard``. The wrapper-native leaves
(``use_shared_env = False``) are gated by the base test another way: every
token their sequence declares in its ``EVIDENCE`` tuple, every
``required_evidence`` token on the test, and every row here must have been
logged as an ``EVIDENCE: <TOKEN>`` line before the leaf passes.
"""

from __future__ import annotations

# testcase -> recorded reason for running with no (CHK_ID, TOKEN, EXPECT) rows
UNMAPPED_TESTS: dict[str, str] = {}

# testcase -> ordered checkbox contracts (FEATURE_LIST / VPLAN aligned)
TEST_EVIDENCE: dict[str, list[tuple[str, str, str]]] = {
    "smu_alias_cache_reset_test": [
        (
            "CHK-ALIAS-RESET-TRANSPARENT",
            "ALIAS_RESET_TRANSPARENT",
            "with every alias region invalid the outbound address is unchanged and VERSION_LO "
            "at the local alias reads its reset value",
        ),
        (
            "CHK-ALIAS-CACHE-HIT",
            "ALIAS_CACHE_HIT",
            "an alias hit carries the programmed cacheable value 0..15 on AW and AR",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK_TIMEOUT_PATHS", "bounded J2A and AXI waits with last state"),
    ],
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
    "smu_axi_filter_allow_ns_test": [
        ("CHK-SMU-ALLOW-NS-S1", "CHK-SMU-ALLOW-NS-S1", "allow_ns=0 secure OKAY / NS DECERR"),
        ("CHK-SMU-ALLOW-NS-S2", "CHK-SMU-ALLOW-NS-S2", "dual-slot admits secure and NS"),
        ("CHK-SMU-ALLOW-NS-S3", "CHK-SMU-ALLOW-NS-S3", "clear returns DECERR for both"),
    ],
    "smu_axi_in_attribute_sweep_test": [
        (
            "CHK-AXIIN-ATTR-PROT",
            "CHK-AXIIN-ATTR-PROT",
            "all eight AxPROT encodings are admitted on AR and AW when one entry matches "
            "each prot[1] polarity, the reads returning the VERSION_LO RDL reset value",
        ),
        (
            "CHK-AXIIN-ATTR-QUAL",
            "CHK-AXIIN-ATTR-QUAL",
            "AxREGION, AxQOS and AxCACHE at 0x0 and 0xF and AxLOCK at 0 and 1 leave the "
            "response and the data unchanged, on AR and AW",
        ),
        (
            "CHK-AXIIN-ATTR-SIZE",
            "CHK-AXIIN-ATTR-SIZE",
            "AxSIZE 0..3 each return the byte slice of the VERSION_LO RDL reset value the "
            "size selects",
        ),
        (
            "CHK-AXIIN-ATTR-LEN",
            "CHK-AXIIN-ATTR-LEN",
            "with allow_burst=0 the AxLEN 0xFF, 0xAA and 0x55 transfers are refused with "
            "DECERR while AxLEN 0 at the same address is admitted",
        ),
        (
            "CHK-AXIIN-ATTR-BURST",
            "CHK-AXIIN-ATTR-BURST",
            "the same entries refuse a multi-beat FIXED, INCR and WRAP transfer with DECERR",
        ),
        (
            "CHK-AXIOUT-WRITE",
            "CHK-AXIOUT-WRITE",
            "one SMC write above the shrunk local aperture crosses smu_axi_out, the bench "
            "responder holds the word and the B response returns OKAY",
        ),
    ],
    "smu_aperture_map_walk_test": [
        (
            "CHK-SMCMAP-WALK-PORT",
            "CHK-SMCMAP-WALK-PORT",
            "every programmed GLOBAL_BASE and REGION_SIZE reaches smc_global_base_o and "
            "smc_region_size_o and reads back over JTAG2AXI",
        ),
        (
            "CHK-SMCMAP-WALK-INSIDE",
            "CHK-SMCMAP-WALK-INSIDE",
            "at every setting the rebased VERSION_LO read returns its RDL reset value and "
            "the rebased SCRATCH_COLD write reads back, all OKAY",
        ),
        (
            "CHK-SMCMAP-WALK-EDGE",
            "CHK-SMCMAP-WALK-EDGE",
            "at every setting the first address of the window reaches the SMC once and the word "
            "below and the address past it do not and return DECERR",
        ),
        (
            "CHK-SMCMAP-RESTORE",
            "CHK-SMCMAP-RESTORE",
            "GLOBAL_BASE and REGION_SIZE written back to LOCAL_BASE and the RDL reset "
            "reach the ports and read back",
        ),
    ],
    "smu_axi_out_addr_len_size_test": [
        (
            "CHK-AXIOUT-SIZE",
            "CHK-AXIOUT-SIZE",
            "each JTAG2AXI write and read of 1, 2, 4 and 8 bytes at two 56-bit addresses "
            "crosses smu_axi_out once with its address and AxSIZE, and the bytes land and "
            "read back",
        ),
        (
            "CHK-AXIOUT-LEN",
            "CHK-AXIOUT-LEN",
            "a 2 KiB iDMA copy crosses smu_axi_out as bursts covering the block both ways, "
            "and the destination holds the source",
        ),
        (
            "CHK-AXIOUT-BACKPRESSURE",
            "CHK-AXIOUT-BACKPRESSURE",
            "the iDMA copy completes intact while the responder stalls every AW, W and AR, "
            "and also with only the write handshakes stalled",
        ),
        (
            "CHK-AXIOUT-ERROR-RESP",
            "CHK-AXIOUT-ERROR-RESP",
            "responder SLVERR and DECERR on a read and a write reach JTAG2AXI as that status",
        ),
        (
            "CHK-AXIOUT-ZEROER",
            "CHK-AXIOUT-ZEROER",
            "the SMC zeroer clears 512 bytes at the responder and its busy bit returns low",
        ),
        (
            "CHK-AXIOUT-OUTPUT-REMAP",
            "CHK-AXIOUT-OUTPUT-REMAP",
            "M-mode and Xvisor output-remap region 0 accesses reach the responder at the "
            "programmed target, and a following access leaves by the default path",
        ),
    ],
    "smu_axi_out_outstanding_test": [
        (
            "CHK-AXIOUT-OUTSTANDING",
            "CHK-AXIOUT-OUTSTANDING",
            "an iDMA copy against a responder of depth 8 that delays every response "
            "completes intact with more than 3 and at most 8 writes and reads in flight "
            "at once, counted at the wires and by the responder",
        ),
        (
            "CHK-AXIOUT-OUTSTANDING-ORDER",
            "CHK-AXIOUT-OUTSTANDING-ORDER",
            "every R beat carries the data of the oldest outstanding read of its RID, "
            "every B answers an outstanding write of its BID, and none is left over",
        ),
    ],
    "smu_smc_inbound_window_sweep_test": [
        (
            "CHK-SMC-WINDOW-PROT",
            "CHK-SMC-WINDOW-PROT",
            "under every AxPROT the SMC external window's base word and a DTP port CONFIG "
            "word read and write back OKAY unchanged, and the external target and eFuse "
            "SPARE[0] accesses complete",
        ),
        (
            "CHK-SMC-WINDOW-EXTERNAL-SIZE",
            "CHK-SMC-WINDOW-EXTERNAL-SIZE",
            "every AxSIZE with each of address bits [6:0] set and cleared completes at the "
            "SMC external target",
        ),
        (
            "CHK-SMC-WINDOW-AWID-TRAIN",
            "CHK-SMC-WINDOW-AWID-TRAIN",
            "sixteen SPM writes under distinct AWIDs in flight with BREADY held are OKAY "
            "and read back",
        ),
        (
            "CHK-SMC-WINDOW-HELD-TRAIN",
            "CHK-SMC-WINDOW-HELD-TRAIN",
            "sixty-four reads and sixty-four writes launched together with responses held at "
            "the external target and at the DTP CONFIG word all complete, and the DTP word "
            "is unchanged",
        ),
        (
            "CHK-SMC-WINDOW-COOL-RESET",
            "CHK-SMC-WINDOW-COOL-RESET",
            "the held cool reset pin holds the SMC primary reset asserted and its release "
            "releases it",
        ),
    ],
    "smu_cla_action_test": [
        (
            "CHK-CLA-CUSTOM-ACTION",
            "CHK-CLA-CUSTOM-ACTION",
            "each CLA custom action programmed alone drives exactly its bit of the custom "
            "action bus, and a pair with no custom enable clears it",
        ),
        (
            "CHK-CLA-XTRIGGER",
            "CHK-CLA-XTRIGGER",
            "with every halt mask bit clear the cross-trigger pair leaves both SMC "
            "cross-trigger lanes into the DTP low",
        ),
        (
            "CHK-CLA-CLOCK-HALT",
            "CHK-CLA-CLOCK-HALT",
            "with the clock-stop enable set and no action the report and DTP clock-stop "
            "lane 0 are low, and with the enable clear lane 0 stays low under the action",
        ),
    ],
    "smu_octs_reset_and_secondary_hold_test": [
        (
            "CHK-OCTSR-RESET-CSR",
            "OCTSR_RESET_CSR",
            "OCTS CTRL reads its RDL reset word, the seven other CSRs read 0 and STATUS.RUNNING is "
            "0",
        ),
        (
            "CHK-OCTSR-RESET-PIN",
            "OCTSR_RESET_PIN",
            "timer_count_o is 0 on every clk_smu sample from the bench's reset-done indication "
            "until the START write",
        ),
        (
            "CHK-OCTSR-STRAP-LOW",
            "OCTSR_STRAP_LOW",
            "SMC_ATTRIBUTES.chiplet_is_primary and STATUS.MODE read 1 and PRIMARY at the default "
            "strap, and 0 and SECONDARY with the strap low",
        ),
        (
            "CHK-OCTSR-SECONDARY-HOLD",
            "OCTSR_SECONDARY_HOLD",
            "SECONDARY ignores TIMER_START: STATUS.RUNNING 0 and timer_count_o 0 for 1024 cycles; "
            "a PRIMARY START sets RUNNING and moves timer_count_o within 1024 cycles",
        ),
        (
            "CHK-TIMEOUT-PATHS",
            "CHK_TIMEOUT_PATHS",
            "bounded J2A waits and pin samplers with last state",
        ),
    ],
    "smu_otp_prod_error_resp_test": [
        (
            "CHK-OTP-PROD-SMC-REFUSED",
            "CHK-OTP-PROD-SMC-REFUSED",
            "under PROD an SMC OTP read and write of MAP SPARE[0] are refused, the read "
            "with 0xBADCAB1E, and a JTAG_PUBLIC_IDENTITY read returns SUCCESS",
        ),
        (
            "CHK-OTP-PROD-SEP-REFUSED",
            "CHK-OTP-PROD-SEP-REFUSED",
            "under PROD a SEP OTP read and write of MAP SPARE0 are refused, the read with "
            "0xBADCAB1E, and a write and read in the eFuse MMR token block return SUCCESS",
        ),
        (
            "CHK-OTP-PROD-SMC-RESET",
            "CHK-OTP-PROD-SMC-RESET",
            "the SMC is in reset while the cool reset pin is held, and after it a "
            "JTAG_PUBLIC_IDENTITY read over the SMC OTP bridge returns SUCCESS",
        ),
        (
            "CHK-OTP-PROD-SMC-SERIES",
            "CHK-OTP-PROD-SMC-SERIES",
            "an SMC OTP series read of JTAG_PUBLIC_IDENTITY with pipeline depth 3 completes "
            "with SUCCESS",
        ),
    ],
    "smu_lc_rma_chip_1_export_test": [
        (
            "CHK-LCG-RMACHIP1-LC-EXPORT",
            "CHK-LCG-RMACHIP1-LC-EXPORT",
            "under the RMA_CHIPLET raw 4'b0111 image lc_state_o, obs_sep_lc_state_o and "
            "smc_lc_state_in_o each equal 0x87 on one sampled cycle",
        ),
        (
            "CHK-TIMEOUT-PATHS",
            "CHK-TIMEOUT-PATHS",
            "bounded lc_settle and dbg_settle waits with last state",
        ),
        ("CHK-NONVAC", "CHK-NONVAC", "ordered sim-time fence S1<S2<S3<PASS"),
    ],
    "smu_lc_rma_sip_1_export_test": [
        (
            "CHK-LCG-RMASIP1-LC-EXPORT",
            "CHK-LCG-RMASIP1-LC-EXPORT",
            "under the RMA_SIP raw 4'b0011 image lc_state_o, obs_sep_lc_state_o and "
            "smc_lc_state_in_o each equal 0xC3 on one sampled cycle",
        ),
        (
            "CHK-TIMEOUT-PATHS",
            "CHK-TIMEOUT-PATHS",
            "bounded lc_settle and dbg_settle waits with last state",
        ),
        ("CHK-NONVAC", "CHK-NONVAC", "ordered sim-time fence S1<S2<S3<PASS"),
    ],
    "smu_lc_sigint_fail_closed_test": [
        (
            "CHK-LC-SIGINT-LEGAL-PAIR",
            "CHK-LC-SIGINT-LEGAL-PAIR",
            "with the legal TEST_DEV pair lc_sigint_err_o is 0, an SMC OTP write and "
            "readback of MAP SPARE[0] and a JTAG_PUBLIC_IDENTITY read return SUCCESS, and a "
            "SEP OTP write of a non-zero pattern to SPARE0 reads back that pattern",
        ),
        (
            "CHK-LC-SIGINT-RAISED",
            "CHK-LC-SIGINT-RAISED",
            "with the n rail of LC_STATE bit 0 inverted at the SMC's LC_STATE input, "
            "lc_sigint_err_o is 1",
        ),
        (
            "CHK-LC-SIGINT-SMC-OTP-CLOSED",
            "CHK-LC-SIGINT-SMC-OTP-CLOSED",
            "under the broken pair the SMC OTP read of SPARE[0] is refused with 0xBADCAB1E, "
            "the write is refused, and the JTAG_PUBLIC_IDENTITY read is refused",
        ),
        (
            "CHK-LC-SIGINT-SEP-OTP-OPEN",
            "CHK-LC-SIGINT-SEP-OTP-OPEN",
            "under the broken pair a SEP OTP read of SPARE0 returns SUCCESS with the "
            "pattern written in S1 while lc_sigint_err_o is still 1",
        ),
        (
            "CHK-LC-SIGINT-RELEASED",
            "CHK-LC-SIGINT-RELEASED",
            "with the legal pair restored lc_sigint_err_o is 0, SPARE[0] reads back the "
            "pattern written before the fault, JTAG_PUBLIC_IDENTITY returns SUCCESS, and "
            "SEP SPARE0 still reads the S1 pattern",
        ),
    ],
    "smu_smc_fabric_test": [
        (
            "CHK-SEP-DMI-DMSTATUS",
            "CHK-SEP-DMI-DMSTATUS",
            "SEP TAP dmi read of dmstatus completes with status 0 and version 2 (spec 0.13)",
        ),
        (
            "CHK-SMC-FW-FABRIC-PASS",
            "CHK-SMC-FW-FABRIC-PASS",
            "the SMC ROM image posts READY, and after GO every hart's SEP SRAM and ext_out "
            "read-backs match and hart 0 posts TEST_PASS",
        ),
        (
            "CHK-SMC-FW-FABRIC-CROSSCHECK",
            "CHK-SMC-FW-FABRIC-CROSSCHECK",
            "all four hart words pass, the responder and SEP SRAM hold each hart's words, "
            "and ext_out carried writes and reads from every hart",
        ),
    ],
    "smu_axi_in_burst_outstanding_test": [
        (
            "CHK-AXIIN-SPM-SWEEP",
            "CHK-AXIIN-SPM-SWEEP",
            "every SPM size and address cell reads back, an INCR burst reads back its beats, "
            "and an INCR write after a WRAP write is OKAY",
        ),
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
            "INCR bursts at the register targets are OKAY and a WRAP burst read of the same "
            "shape is refused with SLVERR",
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
    "smu_dtp_debug_control_fields_test": [
        (
            "CHK-DBGCTL-RESET-VALUES",
            "CHK-DBGCTL-RESET-VALUES",
            "DEBUG_CONTROL bits 3:0 and bit 4 read 0 after reset with every request idle",
        ),
        (
            "CHK-DBGCTL-RW-BITS",
            "CHK-DBGCTL-RW-BITS",
            "bits 0..3 each read back the written 1 and the written 0 with the other bits 0",
        ),
        (
            "CHK-DBGCTL-BIT4-READONLY",
            "CHK-DBGCTL-BIT4-READONLY",
            "bit 4 reads 0 on the read that follows a scan shifting 1 into it with no request, "
            "and 1 with a lane request while 0 is shifted in",
        ),
        (
            "CHK-JTAG-STOP-LATENCY",
            "CHK-JTAG-STOP-LATENCY",
            "dtp_stop_clks_o rises and falls within 64 clk_smu of the jtag_clock_stop TDR update",
        ),
        (
            "CHK-DBGCTL-RESET-CLEARS",
            "CHK-DBGCTL-RESET-CLEARS",
            "jtag_clock_stop and dtp_stop_clks_o read 0 after each of TRST, Test-Logic-Reset via "
            "TMS and power-on reset; cla_clock_stop_en is logged",
        ),
        (
            "CHK-TIMEOUT-PATHS",
            "CHK_TIMEOUT_PATHS",
            "bounded stop-output, Update-DR and reset waits with last state",
        ),
        ("CHK-NONVAC", "CHK-NONVAC", "ordered fence S1<S2<S3<S4<S5<S6<S7<PASS"),
    ],
    "smu_dtp_scan_chain_boundary_test": [
        (
            "CHK-SMU-IJTAG-GATE",
            "CHK-SMU-IJTAG-GATE",
            "under SELECT_IJTAG with all three SIBs open every host select is high on at least as "
            "many TCKs as the scan shifts and the scan returns the open-chain word; from the "
            "Update-IR that loads IDCODE, none of the three selects asserts over an IDCODE DR "
            "scan and the IR scan of a second IDCODE load, counted on jtag_tck, and the "
            "open-chain word returns again afterwards",
        ),
        (
            "CHK-SMU-IJTAG-CHAIN",
            "CHK-SMU-IJTAG-CHAIN",
            "open pass: with all three SIBs held open the DR is six cells "
            "(three SIB bits and the three bench loop cells), each payload "
            "returns six bits late after the captured 0b101010, and the "
            "dfd, dft and dft_secure host scan-out pins each carry the "
            "modelled SIB stream on every Shift-DR TCK, count-gated; closed "
            "pass, the control: with every SIB shut the DR is three cells "
            "and each payload returns three bits late after 0b000; five "
            "directed and three seeded-random nonzero payloads per pass",
        ),
        (
            "CHK-SMU-IJTAG-SIB",
            "CHK-SMU-IJTAG-SIB",
            "Update-DR latches the SIB enables and the next scan returns "
            "them, each open SIB followed by its bench cell, for each SIB "
            "alone, all three, and none; the matching host select asserts "
            "only while that SIB is open",
        ),
        (
            "CHK-SMU-STAP-IO-SELECT",
            "CHK-SMU-STAP-IO-SELECT",
            "an unselected I/O STAP drives no TDO enable and its host TMS holds the TMS-Hold "
            "reset value 0 on every TCK of an IDCODE scan; selected over TAP_3DCR, a network "
            "IDCODE scan of 37 cells (the PTAP register, the I/O STAP's TDO and TDI lockup pair "
            "over the bare bench return, one TCK, and four SIBs) and an 8-bit tail returns four "
            "SIB bits of 0, the masked lockup bit, the IDCODE and the tail 37 bits late, "
            "tb_stap_io_tdo carries the IDCODE LSB first then the tail and the zero fill behind "
            "it on all 45 Shift-DR TCKs, the enable is high on every Shift-IR and Shift-DR TCK "
            "and low on every other TCK, read against the PTAP state, and covers exactly the 6 + "
            "45 shift TCKs, host TMS matches the primary TAP on every TCK, and the extra STAP "
            "drives no TDO enable",
        ),
        (
            "CHK-SMU-STAP-EXTRA-SELECT",
            "CHK-SMU-STAP-EXTRA-SELECT",
            "an unselected extra STAP drives no TDO enable and its host TMS holds the TMS-Hold "
            "reset value 0 on every TCK of an IDCODE scan; selected over TAP_3DCR without "
            "Config-Hold, a network IDCODE scan of 36 cells (the PTAP register, three SIBs ahead, "
            "the bare bench return and its own SIB) and an 8-bit tail returns four SIB bits of 0, "
            "the IDCODE and the tail 36 bits late, tb_stap_extra0_tdo carries three SIB captures, "
            "the IDCODE LSB first, the tail and the zero fill behind it on all 44 Shift-DR TCKs, "
            "the enable is high on every Shift-IR and Shift-DR TCK and low on every other TCK, "
            "read against the PTAP state, and covers exactly the 6 + 44 shift TCKs, host TMS "
            "matches the primary TAP on every TCK, and the I/O STAP drives no TDO enable",
        ),
    ],
    "smu_dtp_bsr_ijtag_scan_test": [
        ("CHK-DTP-BSR-EXTEST-SELECT", "CHK-DTP-BSR-EXTEST-SELECT", "EXTEST selects BSR TCK"),
    ],
    "smu_dtp_io_stap_smoke_test": [
        ("CHK-DTP-IO-STAP-SCAN", "CHK-DTP-IO-STAP-SCAN", "IO STAP host TCK observe"),
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
    "smu_dtp_smc_stap_smoke_test": [
        (
            "CHK-DTP-SMC-STAP-IDCODE",
            "CHK-DTP-SMC-STAP-IDCODE",
            "selected SMC STAP sees the same TMS edge count as the PTAP during IDCODE",
        ),
        (
            "CHK-DTP-SMC-STAP-TRST-DESEL",
            "CHK-DTP-SMC-STAP-TRST-DESEL",
            "after TRST and before any re-select, an IDCODE scan leaves SMC STAP TMS and "
            "tdo_oen quiet",
        ),
    ],
    "smu_dtp_sep_dm_dmi_test": [
        (
            "CHK-SEP-DMI-DMSTATUS",
            "CHK-SEP-DMI-DMSTATUS",
            "SEP TAP dmi read of dmstatus completes with status 0 and version 2 (spec 0.13)",
        ),
    ],
    "smu_axi_in_sep_aperture_test": [
        (
            "CHK-AXIIN-SEP-ROUND-TRIP",
            "CHK-AXIIN-SEP-ROUND-TRIP",
            "ext_in writes and reads SEP SRAM OKAY under every id, qualifier, AxPROT, AxSIZE "
            "and byte offset swept, and every read returns the bytes written",
        ),
        (
            "CHK-AXIIN-SEP-BURST",
            "CHK-AXIIN-SEP-BURST",
            "INCR bursts of AxLEN 0x00/0x55/0xAA/0xFF round-trip SEP SRAM, also under response "
            "backpressure",
        ),
        (
            "CHK-AXIIN-SEP-ERRORS",
            "CHK-AXIIN-SEP-ERRORS",
            "an entropy pool write is SLVERR and SEP-local 0x0 is not OKAY",
        ),
        (
            "CHK-AXIIN-SEP-ADDRESS-BITS",
            "CHK-AXIIN-SEP-ADDRESS-BITS",
            "every walked SEP aperture address arrives at the SEP inbound port on both "
            "channels and no other address does",
        ),
        (
            "CHK-AXIIN-SEP-EXTERNAL",
            "CHK-AXIIN-SEP-EXTERNAL",
            "inbound writes to the SEP external aperture end in error responses and, per R "
            "beat tapped on ext_in and paired with its AR, no external-aperture read beat is "
            "OKAY and every TRNG-window read beat is DECERR; TRNG-window writes are recorded, "
            "not graded",
        ),
        (
            "CHK-AXIIN-SEP-ID-TRAIN",
            "CHK-AXIIN-SEP-ID-TRAIN",
            "reads and writes under distinct IDs in flight together complete and read back",
        ),
        (
            "CHK-AXIIN-SEP-SMC-DMA",
            "CHK-AXIIN-SEP-SMC-DMA",
            "an ext_in read of the SMC returns VERSION_LO, an SMC iDMA copy from SEP SRAM to "
            "ext_out lands, a copy back into SEP SRAM reads back, and a SEP egress follows",
        ),
        (
            "CHK-AXIIN-SEP-SHIM",
            "CHK-AXIIN-SEP-SHIM",
            "the eFuse shim word reads and writes back OKAY under every AxPROT, in held "
            "trains and in a read-against-lagged-write sweep, and a system-bus read and "
            "write of a closed window return sberror",
        ),
    ],
    "smu_efuse_command_test": [
        (
            "CHK-SEP-DMI-DMSTATUS",
            "CHK-SEP-DMI-DMSTATUS",
            "SEP TAP dmi read of dmstatus completes with status 0 and version 2 (spec 0.13)",
        ),
        (
            "CHK-EFUSE-CMD-READ",
            "CHK-EFUSE-CMD-READ",
            "a read at bit 0 and at every address bit of the spare middle of the array completes",
        ),
        (
            "CHK-EFUSE-CMD-PROGRAM",
            "CHK-EFUSE-CMD-PROGRAM",
            "programs of the middle fuse word complete and a read returns every programmed bit",
        ),
        (
            "CHK-EFUSE-CMD-OOB",
            "CHK-EFUSE-CMD-OOB",
            "an out-of-range read and program fail, set the sticky address errors, and clear",
        ),
        (
            "CHK-EFUSE-CMD-PROGRAM-FAIL",
            "CHK-EFUSE-CMD-PROGRAM-FAIL",
            "with the bank failing one program, a program with read-back reports error "
            "status 1 and the word reads 0",
        ),
        (
            "CHK-EFUSE-CMD-WORD",
            "CHK-EFUSE-CMD-WORD",
            "programming all 32 bits of a word reads back 0xFFFFFFFF and the next word reads 0",
        ),
    ],
    "smu_sep_inbound_burst_extension_test": [
        (
            "CHK-DBG-EXT-BURST",
            "DBG_EXT_BURST",
            "an INCR burst at SEP-local 0x2000_1000 reaches the extension port routed on its "
            "first address with its length, size and beats, and nothing reaches the SHIM port",
        ),
        (
            "CHK-DBG-SHIM-BURST",
            "DBG_SHIM_BURST",
            "an INCR burst from the SHIM base carries every beat to the eFuse bank control port "
            "at advancing addresses and none to the extension port",
        ),
        (
            "CHK-TIMEOUT-PATHS",
            "CHK_TIMEOUT_PATHS",
            "bounded SBA/burst/beat/posture waits with last state",
        ),
        ("CHK-NONVAC", "CHK-NONVAC", "ordered sim-time fence S1<...<S5<PASS"),
    ],
    "smu_sep_lsu_fabric_test": [
        (
            "CHK-SEP-DMI-DMSTATUS",
            "CHK-SEP-DMI-DMSTATUS",
            "SEP TAP dmi read of dmstatus completes with status 0 and version 2 (spec 0.13)",
        ),
        (
            "CHK-SEP-LSU-HALT",
            "CHK-SEP-LSU-HALT",
            "a halt request halts the SEP hart",
        ),
        (
            "CHK-SEP-LSU-OUT",
            "CHK-SEP-LSU-OUT",
            "the probe completes through a stalling responder, which holds every byte, and each load "
            "returns the store word",
        ),
        (
            "CHK-SEP-LSU-OUT-SIDE-EFFECT",
            "CHK-SEP-LSU-OUT-SIDE-EFFECT",
            "with the side-effect bit the probe completes and each load returns the store word",
        ),
        (
            "CHK-SEP-LSU-SMC",
            "CHK-SEP-LSU-SMC",
            "the probe completes against the SEP view of the SMC SPM",
        ),
        (
            "CHK-SEP-LSU-EXTERNAL",
            "CHK-SEP-LSU-EXTERNAL",
            "each external-aperture run halts at one of the two ebreaks and no load of any "
            "run returns the store word",
        ),
        (
            "CHK-SEP-LSU-SBA-MIX",
            "CHK-SEP-LSU-SBA-MIX",
            "system-bus accesses on each probe path complete before and after the probe runs",
        ),
    ],
    "smu_sep_mailbox_sba_readback_test": [
        (
            "CHK-COMP-SEP-WIRQT-READBACK",
            "COMP_SEP_WIRQT_READBACK",
            "WIRQT of all sixteen SEP mailbox ports reads 0, then reads back a value below the "
            "FIFO depth written over the debug system bus, with sberror 0",
        ),
        (
            "CHK-TIMEOUT-PATHS",
            "CHK_TIMEOUT_PATHS",
            "bounded SBA and DMI waits with last state",
        ),
    ],
    "smu_sep_sba_fabric_sweep_test": [
        (
            "CHK-SEP-DMI-DMSTATUS",
            "CHK-SEP-DMI-DMSTATUS",
            "SEP TAP dmi read of dmstatus completes with status 0 and version 2 (spec 0.13)",
        ),
        (
            "CHK-SEP-SBA-OUT-SWEEP",
            "CHK-SEP-SBA-OUT-SWEEP",
            "every size, offset and free SMU-aperture address bit is held by the responder and reads back",
        ),
        (
            "CHK-SEP-SBA-REMAP-HIGH",
            "CHK-SEP-SBA-REMAP-HIGH",
            "an alias region offset of each power of two from 2^32 to 2^55 reaches the responder there",
        ),
        (
            "CHK-SEP-SBA-REMAP-CACHEABLE",
            "CHK-SEP-SBA-REMAP-CACHEABLE",
            "cacheable raises AxCACHE[3:2] on the remapped write and read",
        ),
        (
            "CHK-SEP-SBA-REMAP-SMC",
            "CHK-SEP-SBA-REMAP-SMC",
            "a wrapping offset moves a page into the SMC SPM view; the word reads back both ways",
        ),
        (
            "CHK-SEP-SBA-OUTPUT-REMAP",
            "CHK-SEP-SBA-OUTPUT-REMAP",
            "AP and STEE output-remap region 0 accesses reach the responder at the programmed target",
        ),
        (
            "CHK-SEP-SBA-OUT-ERROR",
            "CHK-SEP-SBA-OUT-ERROR",
            "responder SLVERR and DECERR on a read and a write each return a system-bus error",
        ),
        (
            "CHK-SEP-SBA-SMC-WINDOW",
            "CHK-SEP-SBA-SMC-WINDOW",
            "every size, offset and SPM address bit reads back through the SEP view of the SMC window",
        ),
        (
            "CHK-SEP-SBA-EXTERNAL-DECERR",
            "CHK-SEP-SBA-EXTERNAL-DECERR",
            "every external-aperture and TRNG-window access returns a system-bus error",
        ),
    ],
    "smu_sep_external_irq_pins_test": [
        (
            "CHK-SEP-EXTIRQ-WIDTH",
            "CHK-SEP-EXTIRQ-WIDTH",
            "precondition: the external band is 212 lanes and every pin reads low before the first "
            "drive; earns no feature credit",
        ),
        (
            "CHK-SEP-EXTIRQ-RISE",
            "CHK-SEP-EXTIRQ-RISE",
            "for every lane the pending bit of source 44+i reads 0 before the pin is driven and 1 "
            "within the bounded wait; the pin-to-pending cycles are measured and logged only",
        ),
        (
            "CHK-SEP-EXTIRQ-ONEHOT",
            "CHK-SEP-EXTIRQ-ONEHOT",
            "with only lane i high the external-band pending bitmap is the one-hot value at "
            "source 44+i",
        ),
        (
            "CHK-SEP-EXTIRQ-CORE-PORT",
            "CHK-SEP-EXTIRQ-CORE-PORT",
            "the core external-request port bit of source 44+i equals the pending bit, both 1, "
            "and the port's external band is the same one-hot value",
        ),
        (
            "CHK-SEP-EXTIRQ-FALL",
            "CHK-SEP-EXTIRQ-FALL",
            "after lane i returns low its pending bit reads 0 within the bounded wait with no "
            "gateway or clear register written; the fall cycles are measured and logged only",
        ),
        (
            "CHK-SEP-EXTIRQ-ZERO",
            "CHK-SEP-EXTIRQ-ZERO",
            "after lane i showed 1 and every lane is low the external-band pending bitmap is "
            "all-zero",
        ),
        (
            "CHK-SEP-EXTIRQ-WALK",
            "CHK-SEP-EXTIRQ-WALK",
            "lanes 0 to W-1 are visited once each in ascending order with at most one lane high "
            "and W unchanged",
        ),
        (
            "CHK-NONVAC",
            "CHK-NONVAC",
            "ordered simulation-time fence S1<S2<S3<S4<S5<S6<S7<S8; "
            "the PASS stamp is two clk_smu_i cycles after S7",
        ),
        (
            "CHK-TIMEOUT-PATHS",
            "CHK-TIMEOUT-PATHS",
            "bounded pending-rise and pending-fall waits, 212 sites each, none expired, with "
            "the last state recorded",
        ),
    ],
    "smu_sep_wdt_bite_to_smc_reset_test": [
        (
            "CHK-SEP-WDT-SMC-REQ",
            "CHK-SEP-WDT-SMC-REQ",
            "the SEP watchdog request reads 0 before the enable write and 1 within the bounded "
            "wait after it, and falls to 0 only once the SMC primary reset asserted; bite cycles "
            "are measured and logged only",
        ),
        (
            "CHK-SEP-WDT-SMC-ASSERT",
            "CHK-SEP-WDT-SMC-ASSERT",
            "after the request first reads 1 the SMC watchdog-term net and the warm net each read "
            "0 within their bounded waits; the cycles to each fall are measured and logged only",
        ),
        (
            "CHK-SEP-WDT-SMC-TERM-WARM",
            "CHK-SEP-WDT-SMC-TERM-WARM",
            "watchdog-term and warm nets read 1 at the baseline and 0 at the settled sample after "
            "the bite, with the request 1 and the SMC watchdog second timeout 0",
        ),
        (
            "CHK-SEP-WDT-SMC-PRIMARY-COLD",
            "CHK-SEP-WDT-SMC-PRIMARY-COLD",
            "the SMC primary reset and the stable cold reset read 1 at every sample of the hold "
            "window that began after the request and both nets changed",
        ),
        (
            "CHK-SEP-WDT-SMC-HOLD",
            "CHK-SEP-WDT-SMC-HOLD",
            "while the watchdog-term and warm nets read 0 the request reads 1 at every sample of "
            "the hold window",
        ),
        (
            "CHK-SEP-WDT-SMC-RELEASE",
            "CHK-SEP-WDT-SMC-RELEASE",
            "the held cool-reset pin drives the primary reset to 0 and the request to 0; after "
            "the pin is released primary, watchdog-term and warm nets each read 1; the order and "
            "cycles are measured and logged only",
        ),
        (
            "CHK-SEP-WDT-SMC-ORDER",
            "CHK-SEP-WDT-SMC-ORDER",
            "from the request's first 1 sample to the end of the release no sample has the warm "
            "net 1 while the watchdog-term net is 0, with no sampling gap",
        ),
        (
            "CHK-SEP-WDT-SMC-CONVERGE",
            "CHK-SEP-WDT-SMC-CONVERGE",
            "in the closing window the request stays 0 and every reset net 1, and the request "
            "rose exactly once from the baseline",
        ),
        (
            "CHK-SEP-WDT-SMC-WARMVEC",
            "CHK-SEP-WDT-SMC-WARMVEC",
            "the per-subsystem warm vector reads 0xFFFFFFFF at the baseline; its level during and "
            "after the bite and the SEP reset level are measured and logged only",
        ),
        (
            "CHK-NONVAC",
            "CHK-NONVAC",
            "ordered simulation-time fence S1<S2<S3<S4<S5<S6<S7<S8<S9<S10<S11<S12; "
            "the PASS stamp is two clk_smu_i cycles after S11",
        ),
        (
            "CHK-TIMEOUT-PATHS",
            "CHK-TIMEOUT-PATHS",
            "eight bounded waits in five kinds (request rise 1, assert 2, primary assert 1, "
            "request fall 1, release 3), none expired, with the last state recorded",
        ),
    ],
    "smu_xtrig_ctm_self_loop_test": [
        (
            "CHK-XT-SELFLOOP-READBACK",
            "CHK-XT-SELFLOOP-READBACK",
            "every CT_SRC[n].CONFIG_0 and CONFIG write of the leaf reads back as written, the "
            "mask 1<<n and RESET set included, and the restore writes read 0",
        ),
        (
            "CHK-XT-SELFLOOP-CONTROL",
            "CHK-XT-SELFLOOP-CONTROL",
            "with the mask 0 one external assertion makes ct_dst[n] rise once and the lane "
            "request-output enable has zero rises over the window",
        ),
        (
            "CHK-XT-SELFLOOP-RETRIGGER",
            "CHK-XT-SELFLOOP-RETRIGGER",
            "with the mask 1<<n the first request-output pulse is STRETCH_MULT+1 = 1 clk_smu_i "
            "cycle wide and a second rise follows within the bounded wait; width and gap are "
            "logged",
        ),
        (
            "CHK-XT-SELFLOOP-ALIVE",
            "CHK-XT-SELFLOOP-ALIVE",
            "a request-output rise occurs in the last sub-window of the fixed loop window; the "
            "total rise count is measured and logged only",
        ),
        (
            "CHK-XT-SELFLOOP-STOP",
            "CHK-XT-SELFLOOP-STOP",
            "the request output is sampled every cycle from the first loop rise to the S7 write "
            "issue and rises within the last 12 cycles before it; the mask written 0 reads back "
            "0, the last pulse ends within the bounded wait and the quiet window has zero rises",
        ),
        (
            "CHK-XT-SELFLOOP-MEASURED",
            "CHK-XT-SELFLOOP-MEASURED",
            "the S2 precondition reads, the total rise count, the STATUS sample and the rises "
            "after CONFIG.RESET are measured and logged only; only their presence is compared",
        ),
        (
            "CHK-NONVAC",
            "CHK-NONVAC",
            "ordered simulation-time fence S1<S2<S3<S4<S5<S6<S7<S8<S9<S10<S11; "
            "the PASS stamp is two clk_smu_i cycles after S10",
        ),
        (
            "CHK-TIMEOUT-PATHS",
            "CHK-TIMEOUT-PATHS",
            "three bounded waits, one each for the ct_dst rise, the second rise and the last "
            "pulse end, and every JTAG2AXI poll, none expired, with the last state recorded",
        ),
    ],
    "smu_sep_rma_token_match_test": [
        (
            "CHK-SEP-RMA-PRECOND",
            "CHK-SEP-RMA-PRECOND",
            "sep_fuse_sense_done_o reads 1 before the first token write and the first and last "
            "word of the RMA SIP digest read back as laid out in the image; precondition "
            "observation, no feature credit",
        ),
        (
            "CHK-SEP-RMA-IDLE",
            "CHK-SEP-RMA-IDLE",
            "the SIP result reads 0x00 with eight words written and no TOKEN_EOP, and the chiplet "
            "result reads 0x00 while the SIP result holds its match",
        ),
        (
            "CHK-SEP-RMA-START",
            "CHK-SEP-RMA-START",
            "TOKEN_EOP 0x1 gives a SIP result while the chiplet result stays 0x00, and TOKEN_EOP "
            "0x100 gives a chiplet result while the SIP result keeps 0x15",
        ),
        (
            "CHK-SEP-RMA-SIP-MATCH",
            "CHK-SEP-RMA-SIP-MATCH",
            "after the eight words of the SIP token and TOKEN_EOP 0x1 the SIP result reads 0x15, "
            "having read 0x00 before TOKEN_EOP",
        ),
        (
            "CHK-SEP-RMA-CHIP-MISMATCH",
            "CHK-SEP-RMA-CHIP-MISMATCH",
            "the chiplet token one bit off, written and started, reads 0x2a, having read 0x00 "
            "before",
        ),
        (
            "CHK-SEP-RMA-CHIP-MATCH",
            "CHK-SEP-RMA-CHIP-MATCH",
            "the correct chiplet token written and started reads 0x15, having read 0x2a in the "
            "leg before",
        ),
        (
            "CHK-SEP-RMA-INDEP",
            "CHK-SEP-RMA-INDEP",
            "the SIP result reads 0x15 again after the chiplet mismatch and match legs while the "
            "chiplet result changed",
        ),
        (
            "CHK-SEP-RMA-SETTLE",
            "CHK-SEP-RMA-SETTLE",
            "in each of the three started legs the result leaves 0x00 within the bounded poll "
            "count; the polls used are logged and no cycle count is compared",
        ),
        (
            "CHK-SEP-RMA-FAULT-LOG",
            "CHK-SEP-RMA-FAULT-LOG",
            "TOKEN_MATCH_FAULT is read once after the last leg and its value is measured and "
            "logged only; only the presence of the log is compared",
        ),
        (
            "CHK-NONVAC",
            "CHK-NONVAC",
            "ordered simulation-time fence S1<S2<S3<S4<S5<S6<S7<S8<S9<S10; the PASS stamp is two "
            "clk_smu_i cycles after S9",
        ),
        (
            "CHK-TIMEOUT-PATHS",
            "CHK-TIMEOUT-PATHS",
            "three bounded result polls, one each for the SIP match, the chiplet mismatch and the "
            "chiplet match, none expired, with the poll bound, polls used and last value recorded",
        ),
    ],
    "smu_sep_sba_peripheral_test": [
        (
            "CHK-SEP-DMI-DMSTATUS",
            "CHK-SEP-DMI-DMSTATUS",
            "SEP TAP dmi read of dmstatus completes with status 0 and version 2 (spec 0.13)",
        ),
        (
            "CHK-SEP-MBOX-IRQ",
            "CHK-SEP-MBOX-IRQ",
            "the mailbox interrupt vector is 0 with IRQEN set and the FIFO empty, a write into "
            "each outbound mailbox raises only its own interrupt lane, and flush, acknowledge "
            "and disable return every lane low",
        ),
        (
            "CHK-SEP-SPI-QUAD",
            "CHK-SEP-SPI-QUAD",
            "quad-mode transmits drive all four data lanes high and off their pre-command "
            "idle level, and raise their enables, a quad receive "
            "fills one RX FIFO word and completes with every enable low, and "
            "INTR_STATE.SPI_EVENT and the interrupt stay "
            "high across a write to INTR_STATE and fall when EVENT_ENABLE.IDLE is cleared",
        ),
        (
            "CHK-SEP-SECURITY-DISABLE",
            "CHK-SEP-SECURITY-DISABLE",
            "a token matching the digest reports the match code and raises the disable level, "
            "a token one bit off reports the mismatch code, and the security-disable net reads "
            "0 before the token and 1 after the match at the SEP eFuse controller's output, "
            "the smu wire and the SMC input",
        ),
        (
            "CHK-SEP-WDT-BITE",
            "CHK-SEP-WDT-BITE",
            "the SEP watchdog reset request is low before the watchdog is enabled and rises "
            "when it bites",
        ),
    ],
    "smu_sep_stap_hold_reset_test": [
        (
            "CHK-DBG-STAP-TMS-HOLD",
            "DBG_STAP_TMS_HOLD",
            "with the SEP STAP deselected its host TMS holds the TMS-Hold value (0 and 1) with no "
            "edges while the PTAP TMS toggles, and the scan path is the PTAP register plus the "
            "SIB bits",
        ),
        (
            "CHK-DBG-STAP-3DCR-RESET",
            "DBG_STAP_3DCR_RESET",
            "the SEP STAP 3DCR reads 3'b111 before a TRST pulse and 0 after it, survives "
            "Test-Logic-Reset with Config-Hold set and clears on it with Config-Hold clear",
        ),
        (
            "CHK-TIMEOUT-PATHS",
            "CHK_TIMEOUT_PATHS",
            "bounded posture/TMS-window/TRST waits with last state",
        ),
        ("CHK-NONVAC", "CHK-NONVAC", "ordered sim-time fence S1<...<S6<PASS"),
    ],
    "smu_dtp_sep_dm_sba_test": [
        (
            "CHK-SEP-DMI-DMSTATUS",
            "CHK-SEP-DMI-DMSTATUS",
            "SEP TAP dmi read of dmstatus completes with status 0 and version 2 (spec 0.13)",
        ),
        (
            "CHK-SEP-SBA-GLOBAL-BASE",
            "CHK-SEP-SBA-GLOBAL-BASE",
            "system-bus write of SEP_GLOBAL_BASE_ADDR reaches sep_global_base_o and reads back",
        ),
        (
            "CHK-SEP-SBA-GLOBAL-BASE-RESTORE",
            "CHK-SEP-SBA-GLOBAL-BASE-RESTORE",
            "writing the RDL reset value returns sep_global_base_o to it",
        ),
        (
            "CHK-SEP-SBA-DEMOTE2-ALONE",
            "CHK-SEP-SBA-DEMOTE2-ALONE",
            "DEMOTE_2 alone complements lcc_demote_state_2_o while lane 1 and DEMOTE_1 hold",
        ),
        (
            "CHK-SEP-SBA-EGRESS",
            "CHK-SEP-SBA-EGRESS",
            "a SEP read and write outside the SMC window each cross smu_axi_out once and "
            "the read returns the written word",
        ),
        (
            "CHK-SEP-SBA-APERTURE-WALK",
            "CHK-SEP-SBA-APERTURE-WALK",
            "SEP_GLOBAL_BASE_ADDR and SEP_REGION_SIZE walk to all-ones and back through "
            "windows clear of the SMC window, each step on the ports and by readback",
        ),
        (
            "CHK-SEP-SBA-DEMOTE-COLD-RESET",
            "CHK-SEP-SBA-DEMOTE-COLD-RESET",
            "a cold reset returns both demoted lanes to the codes they had before S5",
        ),
    ],
    "smu_ext_boot_seq_gate_test": [
        (
            "CHK-BOOT-SEQ-REGATE",
            "CHK-BOOT-SEQ-REGATE",
            "ext_boot_seq_done_i low across a cold reset holds the fuse reset until it rises",
        ),
        ("CHK-BOOT-SEQ-GATE", "CHK-BOOT-SEQ-GATE", "gate holds then releases fuse_reset"),
        ("CHK-PRIMARY-NOT-GATED", "CHK-PRIMARY-NOT-GATED", "primary still releases while gated"),
        (
            "CHK-TIMEOUT-PATHS",
            "CHK-TIMEOUT-PATHS",
            "both bounded waits completed within RELEASE_BOUND, none expired",
        ),
        (
            "CHK-NONVAC",
            "CHK-NONVAC",
            "DUT-edge ordered fence: primary release < ungate drive < fuse release",
        ),
    ],
    "smu_fabric_reg_bar_wr_test": [
        (
            "CHK-SUB-AXIL-LOCAL-S2",
            "CHK-SUB-AXIL-LOCAL-S2",
            "fabric config CSR write/readback held at every listed destination",
        ),
    ],
    "smu_filter_cfg_register_map_test": [
        (
            "CHK-CFG-RESET-CONFIG",
            "CFG_RESET_CONFIG",
            "FILTER_CONFIG reads the reset value on all 32 entries of both instances",
        ),
        (
            "CHK-CFG-RESET-RANGE",
            "CFG_RESET_RANGE",
            "START_ADDR reads 0x0 and END_ADDR 0x7 on all 32 entries",
        ),
        (
            "CHK-CFG-RW-FIELDS",
            "CFG_RW_FIELDS",
            "one-hot walk of the read-write fields reads back; locked reads 1",
        ),
        (
            "CHK-CFG-DBW-RO",
            "CFG_DBW_RO",
            "all-ones write to data_bus_width still reads the reset value",
        ),
        (
            "CHK-CFG-ADDR-56",
            "CFG_ADDR_56",
            "START_ADDR and END_ADDR bits [55:0] store and read back a full bit walk",
        ),
        (
            "CHK-CFG-ENTRY-STRIDE",
            "CFG_ENTRY_STRIDE",
            "unique value per entry reads back at its own 0x20-stride address only",
        ),
        (
            "CHK-CFG-HALF-WORD",
            "CFG_HALF_WORD",
            "32-bit halves match the 64-bit value; half-only writes leave the other half",
        ),
        (
            "CHK-CFG-GROUPID-RB",
            "CFG_GROUPID_RB",
            "group_id written 0xA reads back 0xA on both instances",
        ),
        (
            "CHK-TIMEOUT-PATHS",
            "CHK_TIMEOUT_PATHS",
            "bounded J2A and AXI waits with last state",
        ),
    ],
    "smu_smc_unmapped_response_test": [
        (
            "CHK-UNMAP-BETWEEN",
            "CHK-UNMAP-BETWEEN",
            "between-unit ext_in reads answer DECERR/0xBADCAB1E and writes DECERR",
        ),
        (
            "CHK-UNMAP-PAST-EXTENT",
            "CHK-UNMAP-PAST-EXTENT",
            "past-extent reads answer DECERR/0xBADCAB1E and DECERR-declared writes answer DECERR; "
            "the writes the RDL and memmap declare SLVERR are logged and answered DECERR in this "
            "run, a mismatch recorded for the owner",
        ),
        (
            "CHK-UNMAP-MMODE-XVISOR",
            "CHK-UNMAP-MMODE-XVISOR",
            "M-mode and Xvisor window reads and writes from ext_in answer DECERR",
        ),
        (
            "CHK-TIMEOUT-PATHS",
            "CHK_TIMEOUT_PATHS",
            "bounded J2A and AXI waits with last state",
        ),
    ],
    "smu_filter_lock_test": [
        (
            "CHK-LOCK-SET",
            "LOCK_SET",
            "locked reads 1 on entry 5 of both filter instances after the locking write",
        ),
        (
            "CHK-LOCK-CONFIG-DECERR",
            "LOCK_CONFIG_DECERR",
            "FILTER_CONFIG writes to the locked entry return DECERR and the value stays",
        ),
        (
            "CHK-LOCK-ADDR-DECERR",
            "LOCK_ADDR_DECERR",
            "START_ADDR and END_ADDR writes to the locked entry return DECERR, values unchanged",
        ),
        (
            "CHK-LOCK-READBACK",
            "LOCK_READBACK",
            "the three locked registers read OKAY with the locked configuration",
        ),
        (
            "CHK-LOCK-ISOLATION",
            "LOCK_ISOLATION",
            "entries 4 and 6 stay writable and read back on both instances",
        ),
        (
            "CHK-LOCK-STILL-FILTERS",
            "LOCK_STILL_FILTERS",
            "locked inbound entry admits its page and locked outbound entry blocks its page",
        ),
        (
            "CHK-LOCK-PARITY",
            "LOCK_PARITY",
            "response and value sequence of S2 to S6 equal on inbound and outbound",
        ),
        (
            "CHK-TIMEOUT-PATHS",
            "CHK_TIMEOUT_PATHS",
            "the bounded AXI write, read and probe wait sites each completed their declared "
            "access count",
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
    "smu_jtag_ic_reset_ext_override_test": [
        ("CHK-ICEXT-EXT-ON", "ICEXT_EXT_ON", "enable=0 drives ovrd=1, ctrl_n follows control"),
        ("CHK-ICEXT-EXT-OFF", "ICEXT_EXT_OFF", "enable=1 keeps ovrd=0, ctrl_n follows control"),
        (
            "CHK-ICEXT-EXT-INDEP",
            "ICEXT_EXT_INDEP",
            "single 0 and single 1 on the one external port, readback unchanged elsewhere",
        ),
        ("CHK-ICEXT-EXT-2STEP", "ICEXT_EXT_2STEP", "control moves val first, enable moves ovrd"),
        (
            "CHK-ICEXT-EXT-BOTH",
            "ICEXT_EXT_BOTH",
            "enable and control in one Update-DR settle to the written values",
        ),
        (
            "CHK-ICEXT-EXT-UPDONLY",
            "ICEXT_EXT_UPDONLY",
            "outputs hold through Capture-DR, Shift-DR and Pause-DR",
        ),
        ("CHK-ICEXT-HOLD-1", "ICEXT_HOLD_1", "reset_hold=1: Test-Logic-Reset restores all ones"),
        ("CHK-ICEXT-HOLD-0", "ICEXT_HOLD_0", "reset_hold=0: Test-Logic-Reset keeps the override"),
        ("CHK-ICEXT-HOLD-TRST", "ICEXT_HOLD_TRST", "TRST_n restores every bit including hold"),
        (
            "CHK-ICEXT-HOLD-POR",
            "ICEXT_HOLD_POR",
            "power-on reset restores every bit including hold",
        ),
        (
            "CHK-ICEXT-HOLD-SELF",
            "ICEXT_HOLD_SELF",
            "Test-Logic-Reset leaves reset_hold unchanged at 0 and at 1",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK-TIMEOUT-PATHS", "bounded JTAG waits with last TAP state"),
    ],
    "smu_jtag_ic_reset_layout_caps_test": [
        ("CHK-ICLAY-IC-LEN", "ICLAY_IC_LEN", "163-bit marker emerges after exactly 155 TCKs"),
        (
            "CHK-ICLAY-IC-SLICE",
            "ICLAY_IC_SLICE",
            "cleared control bit lands at each slice boundary position",
        ),
        (
            "CHK-ICLAY-IC-PAIR",
            "ICLAY_IC_PAIR",
            "reset_control is bit 2n+2 and reset_enable bit 2n+1 of the external pair",
        ),
        (
            "CHK-ICLAY-IC-NAMED",
            "ICLAY_IC_NAMED",
            "ten named ports sit at their documented TDR positions",
        ),
        ("CHK-ICLAY-IC-IMG", "ICLAY_IC_IMG", "all-ones image after power-on reset and TRST_n"),
        (
            "CHK-ICLAY-IC-RECAP",
            "ICLAY_IC_RECAP",
            "recapture returns the written image, no output moves",
        ),
        (
            "CHK-ICLAY-CAPS-DEF",
            "ICLAY_CAPS_DEF",
            "JTAG_CAPS equals the default-configuration field map",
        ),
        (
            "CHK-ICLAY-CAPS-RO",
            "ICLAY_CAPS_RO",
            "JTAG_CAPS ignores shifted-in bits and is exactly 60 bits",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK-TIMEOUT-PATHS", "bounded JTAG waits with last TAP state"),
    ],
    "smu_jtag_trst_por_reset_test": [
        (
            "CHK-RSTH-POR-ONLY",
            "RSTH_POR_ONLY",
            "powergood_i drop holds the TAP in TLR, IR decodes IDCODE, DR scan returns IDCODE",
        ),
        (
            "CHK-RSTH-TRST-ONLY",
            "RSTH_TRST_ONLY",
            "TRST_n low gives TLR with TCK running at TMS 0, TMS 1 and with TCK stopped",
        ),
        (
            "CHK-RSTH-RST-COMB",
            "RSTH_RST_COMB",
            "either reset alone holds TLR across TMS-low TCKs; first TMS-low after both gives RTI",
        ),
        (
            "CHK-RSTH-RST-RELEASE",
            "RSTH_RST_RELEASE",
            "TLR under TMS high after release, first TMS-low gives RTI, DR scan returns IDCODE",
        ),
        (
            "CHK-RSTH-TLR-IDCODE",
            "RSTH_TLR_IDCODE",
            "TLR loads IDCODE for each of seven prior instructions",
        ),
        (
            "CHK-RSTH-TDO-RST",
            "RSTH_TDO_RST",
            "the (jtag_tdo, jtag_tdo_oen) pair after TRST_n equals the pair after power-on reset "
            "and after both",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK-TIMEOUT-PATHS", "bounded JTAG waits with last TAP state"),
    ],
    "smu_jtag_reset_override_test": [
        (
            "CHK-IC-DEFAULT",
            "IC_RESET_DEFAULT",
            "IC_RESET default all-ones, every driven TDO bit of the scan resolvable",
        ),
        (
            "CHK-IC-EXT-STAGED",
            "IC_RESET_EXT_STAGED",
            "EXT control staged low reaches ctrl_n while the override stays off",
        ),
        (
            "CHK-IC-EXT-RELEASE-STAGED",
            "IC_RESET_EXT_RELEASE_STAGED",
            "EXT control staged high reaches ctrl_n while the override stays on",
        ),
        (
            "CHK-IC-DOMAIN",
            "IC_RESET_DOMAIN_EXCL",
            "an applied EXT or SMC cold override is the only bit set across the EXT override "
            "and the whole SMC and SEP override halves",
        ),
        (
            "CHK-IC-SS-SEP-WALK",
            "IC_RESET_SS_SEP_WALK",
            "every SS and SEP port staged, applied, released and cleared, with every "
            "SMC and SEP slice port's override and value following",
        ),
    ],
    "smu_dtp_jtag2axi_address_walk_test": [
        (
            "CHK-J2A-WALK-FABRIC",
            "CHK-J2A-WALK-FABRIC",
            "SMC fabric bridge bytes written at offsets 1-3 read back and land in the word; an "
            "off-map write completes",
        ),
        (
            "CHK-J2A-WALK-EXTERNAL",
            "CHK-J2A-WALK-EXTERNAL",
            "a write and a read at every address bit of the adopter window arrive at that "
            "offset on the external bus or the eFuse SHIM link",
        ),
        (
            "CHK-J2A-WALK-DTP-CSR",
            "CHK-J2A-WALK-DTP-CSR",
            "a read and a zero-strobe write at every address bit of the DTP CSR window arrive at "
            "that offset on the DTP CSR link",
        ),
        (
            "CHK-J2A-WALK-SMC-OTP",
            "CHK-J2A-WALK-SMC-OTP",
            "SMC OTP bridge reads and zero-strobe writes at every address bit arrive with that "
            "address on the DTP-to-OTP link",
        ),
        (
            "CHK-J2A-WALK-SEP-OTP",
            "CHK-J2A-WALK-SEP-OTP",
            "SEP OTP bridge reads and zero-strobe writes at every address bit arrive with that "
            "address on the DTP-to-OTP link",
        ),
        (
            "CHK-J2A-WALK-COLD-RESET",
            "CHK-J2A-WALK-COLD-RESET",
            "a cold reset takes the primary SMC reset low and releases it",
        ),
    ],
    "smu_dtp_ptap_ir_walk_test": [
        (
            "CHK-PTAP-STATE-WALK",
            "CHK-PTAP-STATE-WALK",
            "Pause-DR, Exit2-DR, Pause-IR and Exit2-IR reach jtag_ptap_state_o",
        ),
        (
            "CHK-PTAP-IR-DECODE-WALK",
            "CHK-PTAP-IR-DECODE-WALK",
            "each of the 64 IR encodings decodes to its own one-hot bit; TLR loads IDCODE",
        ),
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
            "STRAPS_LO and STRAPS_HI at the boot-ROM documented mandatory-region "
            "address both answer SUCCESS",
        ),
        (
            "CHK-PERIPH-EXT-UNMAPPED",
            "CHK-PERIPH-EXT-UNMAPPED",
            "the first word past the straps pair, which no block claims, DECERRs "
            "(DV rule; see the VPLAN specification gap)",
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
            "CHK-SEP-BOOT-ROM",
            "SEP_BOOT_ROM_OK",
            "SEP reset observed asserted then released; first fetch in the boot-ROM window",
        ),
        (
            "CHK-SEP-ICCM",
            "SEP_ICCM_OK",
            "SEP executed in the ICCM range: >=256 retires over >=16 distinct PCs",
        ),
        ("CHK-SEP-DCCM-WRITE", "SEP_DCCM_WRITE_OK", "SEP firmware stored results into DCCM"),
        ("CHK-NONVAC", "CHK-NONVAC", "boot scoreboard verdict with the SMC arm TEST_PASS seen"),
    ],
    "smu_smc_aperture_reset_state_test": [
        (
            "CHK-APRT-BASES",
            "APRT_BASES",
            "GLOBAL_BASE, LOCAL_BASE and REGION_SIZE read their RDL reset values over JTAG2AXI",
        ),
        (
            "CHK-APRT-REGION-PIN",
            "APRT_REGION_PIN",
            "smc_region_size_o carries the REGION_SIZE reset value 0x0100_0000",
        ),
        (
            "CHK-APRT-CLOCK-GATES",
            "APRT_CLOCK_GATES",
            "the five peripheral cg_en bits read 0 and cg_hysteresis reads its reset value",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK_TIMEOUT_PATHS", "bounded J2A waits with last state"),
    ],
    "smu_smc_base_config_state_test": [
        (
            "CHK-BOOT-BASECFG-APERTURE",
            "BOOT_BASECFG_APERTURE",
            "GLOBAL_BASE, LOCAL_BASE and the REGION_SIZE size field read their RDL reset values",
        ),
        (
            "CHK-BOOT-BASECFG-REGION-PORT",
            "BOOT_BASECFG_REGION_PORT",
            "smc_region_size_o equals 0x0100_0000 and the REGION_SIZE value read over JTAG2AXI",
        ),
        (
            "CHK-BOOT-BASECFG-CG-HANG",
            "BOOT_BASECFG_CG_HANG",
            "CLOCK_GATE_CONTROL, the three hang-detector controls and the three thresholds "
            "read their RDL reset values",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK_TIMEOUT_PATHS", "bounded J2A waits with last state"),
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
        (
            "CHK-SMU-SS-RESET-COMPLETE",
            "CHK-SMU-SS-RESET-COMPLETE",
            "RESET_UNIT.SS_RESET_COMPLETE mirrors ss_reset_complete_i lane for lane over "
            "three patterns and returns to all-ones with the pins released",
        ),
        (
            "CHK-SMU-CHIPLET-STRAP",
            "CHK-SMU-CHIPLET-STRAP",
            "CPU_CTRL.SMC_ATTRIBUTES.chiplet_is_primary follows chiplet_is_primary_i low "
            "and back to set",
        ),
    ],
    "smu_isolation_retention_test": [
        (
            "CHK-ISO-RETAIN-S1",
            "ISO_RETAIN_S1",
            "ISOLATE_REQ_REG, PINEN, SMC and SMCEN read their programmed values after a cool reset",
        ),
        (
            "CHK-ISO-RETAIN-S2",
            "ISO_RETAIN_S2",
            "ISOLATE_REQ_REG, SMC and SMCEN read 0 after a cold reset with GPIO 53 low",
        ),
        (
            "CHK-ISO-RETAIN-S3",
            "ISO_RETAIN_S3",
            "ISOLATE_REQ_PINEN_REG reads 0 after a cold reset with GPIO 53 low and keeps its "
            "value after one with GPIO 53 high",
        ),
        (
            "CHK-ISO-RETAIN-S4",
            "ISO_RETAIN_S4",
            "both FLR counters keep 5 and 7 across a cool reset and read 0 after a cold reset",
        ),
    ],
    "smu_ndm_reset_handshake_test": [
        (
            "CHK-NDM-REQUEST-S1",
            "NDM_REQUEST_S1",
            "NDMRESET_REQUEST follows request pin 0 and pin 3 high and low",
        ),
        (
            "CHK-NDM-REQUEST-S2",
            "NDM_REQUEST_S2",
            "NDMRESET_REQUEST reads 0xF with all four request pins high",
        ),
        ("CHK-NDM-REQUEST-S3", "NDM_REQUEST_S3", "NDMRESET_CLUSTER_COUNT reads 4"),
        (
            "CHK-NDM-REQUEST-S4",
            "NDM_REQUEST_S4",
            "NDMRESET_REQUEST reads 0 with all request pins low after a cold reset and follows "
            "request pin 0 high again",
        ),
        (
            "CHK-NDM-PROCESS-S1",
            "NDM_PROCESS_S1",
            "NDMRESET_PROCESS bit 0 and bit 3 drive only their own process lane",
        ),
        (
            "CHK-NDM-PROCESS-S2",
            "NDM_PROCESS_S2",
            "NDMRESET_PROCESS stores 32 bits and only bits 3:0 reach the port",
        ),
        (
            "CHK-NDM-PROCESS-S3",
            "NDM_PROCESS_S3",
            "NDMRESET_PROCESS and the process port read 0 after a cold reset",
        ),
    ],
    "smu_remap_cfg_register_map_test": [
        (
            "CHK-ALIAS-REGS-RESET",
            "ALIAS_REGS_RESET",
            "all 24 alias REGION_START/END/ATTRS registers read 0 before any write",
        ),
        (
            "CHK-OREMAP-REGS-RESET",
            "OREMAP_REGS_RESET",
            "all 16 output remap REGION_ATTRS registers read 0 before any write",
        ),
        (
            "CHK-ALIAS-REGS-PLACEMENT",
            "ALIAS_REGS_PLACEMENT",
            "unique alias register values read back at their own address only",
        ),
        (
            "CHK-OREMAP-REGS-PLACEMENT",
            "OREMAP_REGS_PLACEMENT",
            "unique output remap offsets read back at their own address only",
        ),
        (
            "CHK-ALIAS-REGS-MASKS",
            "ALIAS_REGS_MASKS",
            "alias start, end, offset, cacheable and valid bits store and read back",
        ),
        (
            "CHK-OREMAP-REGS-MASKS",
            "OREMAP_REGS_MASKS",
            "output remap offset[55:0] and valid[63] store and read back",
        ),
        (
            "CHK-TIMEOUT-PATHS",
            "CHK_TIMEOUT_PATHS",
            "every bounded AXI wait site completed its declared access count",
        ),
    ],
    "smu_reset_csr_access_test": [
        (
            "CHK-CSR-RESET-VALUES-S2",
            "CSR_RESET_VALUES_S2",
            "isolation registers and both FLR counters read 0 after the bring-up cold reset",
        ),
        (
            "CHK-CSR-RESET-VALUES-S3",
            "CSR_RESET_VALUES_S3",
            "NDMRESET_REQUEST and NDMRESET_PROCESS read 0 and NDMRESET_CLUSTER_COUNT reads 4",
        ),
        (
            "CHK-CSR-RESET-VALUES-S4",
            "CSR_RESET_VALUES_S4",
            "SYNC_REG reads 0 and ISOLATE_REQ_VIS reads the pin level and 1 on bits 4 and 8",
        ),
        (
            "CHK-CSR-ACCESS-S1",
            "CSR_ACCESS_S1",
            "random data reads back masked from SS_CONFIG, SS_WARM_RESET_N, NDMRESET_PROCESS "
            "and the FLR counter",
        ),
        (
            "CHK-CSR-ACCESS-S2",
            "CSR_ACCESS_S2",
            "read-only registers keep their value after a write of all ones",
        ),
        (
            "CHK-CSR-ACCESS-S3",
            "CSR_ACCESS_S3",
            "defined reset-unit registers keep their value across accesses to unmapped offsets",
        ),
        (
            "CHK-SYNC-IRQ-S1",
            "SYNC_IRQ_S1",
            "sync_irq_o follows SYNC_REG.sync written 1 then 0",
        ),
        (
            "CHK-SYNC-IRQ-S2",
            "SYNC_IRQ_S2",
            "SYNC_REG and sync_irq_o read 0 after a primary reset",
        ),
    ],
    "smu_dtp_sysreset_stop_clks_test": [
        (
            "CHK-DTP-SYSRESET-S1",
            "DTP_SYSRESET_S1",
            "dtp_stop_clks_o reads 1 with jtag_clock_stop set and 0 on every clk_smu_i edge "
            "inside the primary reset",
        ),
        (
            "CHK-DTP-SYSRESET-S2",
            "DTP_SYSRESET_S2",
            "dtp_stop_clks_o first reads 1 on the third clk_smu_i edge after the primary reset "
            "releases",
        ),
    ],
    "smu_smc_cold_boot_release_order_test": [
        (
            "CHK-BOOT-PG-HOLD",
            "BOOT_PG_HOLD",
            "with powergood_i low and rst_cold_ni high for 600 clk_ref the stable power-good "
            "and the stable cold reset read 0 at every sample",
        ),
        (
            "CHK-BOOT-PG-STRETCH",
            "BOOT_PG_STRETCH",
            "the stable power-good reads 0 for the first 32 clk_ref after powergood_i rises "
            "and rises once",
        ),
        (
            "CHK-BOOT-COLD-HELD",
            "BOOT_COLD_HELD",
            "the stable cold reset reads 0 at every sample from its assertion (after the "
            "32-sample de-glitch) while rst_cold_ni is low, and stays 0 through the extension "
            "window after the first release request",
        ),
        (
            "CHK-BOOT-COLD-EXT",
            "BOOT_COLD_EXT",
            "the stable cold reset reads 0 for the first 255 clk_ref after the later of the "
            "powergood_i and rst_cold_ni rises",
        ),
        (
            "CHK-BOOT-COLD-REASSERT",
            "BOOT_COLD_REASSERT",
            "a 64-clk_ref rst_cold_ni pulse inside the extension: the stable cold reset stays "
            "0 from the first release request through the pulse, and rises within the bound "
            "and no earlier than 255 clk_ref after the later release",
        ),
        (
            "CHK-BOOT-PRIM-SMC-ORDER",
            "BOOT_PRIM_SMC_ORDER",
            "rst_primary_smc_clk_n_o reads 0 at every sample while the cold reset is asserted",
        ),
        (
            "CHK-BOOT-PRIM-REF-ORDER",
            "BOOT_PRIM_REF_ORDER",
            "rst_primary_ref_clk_no reads 0 at every sample while the cold reset is asserted "
            "and at every clk_ref sample where the stable cold reset reads 0",
        ),
        (
            "CHK-BOOT-PRIM-EDGE",
            "BOOT_PRIM_EDGE",
            "each primary reset has one 0 to 1 edge per boot on its destination clock and "
            "does not read 0 afterwards",
        ),
        (
            "CHK-BOOT-COLD-TO-PRIMARY",
            "BOOT_COLD_TO_PRIMARY",
            "each primary reset rises within its bounded wait and reads 1 at the end of each boot",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK_TIMEOUT_PATHS", "bounded reset-pin waits with last state"),
    ],
    "smu_smc_cool_reset_pin_test": [
        (
            "CHK-SMU-COOL-PIN-DEGLITCH",
            "CHK-SMU-COOL-PIN-DEGLITCH",
            "a 28-clk_ref rst_cool_n_from_pin_i pulse leaves the SMC primary reset "
            "released, during the pulse and after it",
        ),
        (
            "CHK-SMU-COOL-PIN-RESET",
            "CHK-SMU-COOL-PIN-RESET",
            "rst_cool_n_from_pin_i held past that pulse asserts the SMC primary reset no "
            "earlier than 28 clk_ref, holds it while low, and the SMC leaves reset after "
            "the pin releases",
        ),
        (
            "CHK-SMU-DFT-DONE-STATUS",
            "CHK-SMU-DFT-DONE-STATUS",
            "DFX_CTRL.STATUS_SMU reads mem_repair_done, mem_repair_success, mbist_done and "
            "mbist_pass clear after a primary reset with the straps low; each pair sets when "
            "its straps rise and holds when they drop again",
        ),
    ],
    "smu_smc_cpu_ctrl_boot_state_test": [
        (
            "CHK-BOOT-SCRATCH0-RESET",
            "BOOT_SCRATCH0_RESET",
            "SCRATCH[0] bits[31:0] read 0 after boot over JTAG2AXI",
        ),
        (
            "CHK-BOOT-RESET-VECTORS",
            "BOOT_RESET_VECTORS",
            "RESET_VECTOR[0..3] each read 0xC004_0000",
        ),
        (
            "CHK-BOOT-RESET-CTRL-VALUES",
            "BOOT_RESET_CTRL_VALUES",
            "RESET_CTRL, CORE_RESET_PULSE_COUNT and RESET_TIMEOUT read their RDL reset values",
        ),
        (
            "CHK-BOOT-WDT-TIMEOUT-RESET",
            "BOOT_WDT_TIMEOUT_RESET",
            "WDT_TIMEOUT reads 0x4000 and WDT_TIMEOUT_RESET reads 0",
        ),
        (
            "CHK-BOOT-SCRATCH-1-15",
            "BOOT_SCRATCH_1_15",
            "SCRATCH[1..15] bits[31:0] read 0, upper words logged",
        ),
        (
            "CHK-BOOT-ATTRIBUTES",
            "BOOT_ATTRIBUTES",
            "SMC_ATTRIBUTES cores, sram_size, mailboxes, mailbox depth, ext interrupts and the "
            "primary strap decode to their documented values",
        ),
        (
            "CHK-BOOT-DUMMY-ROM",
            "BOOT_DUMMY_ROM",
            "DUMMY_ROM_0..3 read their words and DUMMY_ROM_NULL[0..3] read 0",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK_TIMEOUT_PATHS", "bounded J2A waits with last state"),
    ],
    "smu_smc_dtp_jtag2axi_smoke_test": [
        ("CHK-JTAG2AXI-SMOKE-SCRATCH", "CHK-JTAG2AXI-SMOKE-SCRATCH", "J2A scratch write/readback"),
    ],
    "smu_smc_mailbox_aperture_layout_test": [
        (
            "CHK-MBX-OFFSET-MAP",
            "MBX_OFFSET_MAP",
            "ten offsets of outbound mailbox 0 answer as distinct registers, WIRQT and IRQEN read "
            "back",
        ),
        (
            "CHK-MBX-STRIDE-WIRQT",
            "MBX_STRIDE_WIRQT",
            "WIRQT of mailbox 0, 1 and 31 at the 0x1000 stride is independent",
        ),
        (
            "CHK-MBX-IRQEN-INDEP",
            "MBX_IRQEN_INDEP",
            "IRQEN of mailbox 0, 1 and 31 is independent",
        ),
        (
            "CHK-MBX-INBOUND-INDEP",
            "MBX_INBOUND_INDEP",
            "inbound aperture of pair 0 at +0x800 is independent of the outbound aperture",
        ),
        (
            "CHK-MBX-SMC-ATTRIBUTES",
            "MBX_SMC_ATTRIBUTES",
            "SMC_ATTRIBUTES reports 32 mailboxes of depth 2",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK_TIMEOUT_PATHS", "bounded J2A waits with last state"),
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
    "smu_smc_mailbox_status_error_test": [
        (
            "CHK-MBX-ERR-READ-EMPTY",
            "MBX_ERR_READ_EMPTY",
            "empty READ_DATA read is SLVERR with 0xFEEDDEAD, ERROR_FLAGS 0x1, IRQS bit 2 set",
        ),
        (
            "CHK-MBX-STATUS-LEVELS",
            "MBX_STATUS_LEVELS",
            "STATUS reads 0x5 after one push and 0x7 after two (depth 2)",
        ),
        (
            "CHK-MBX-ERR-WRITE-FULL",
            "MBX_ERR_WRITE_FULL",
            "write to the full FIFO is SLVERR, ERROR_FLAGS 0x2, IRQS bit 2 set, STATUS 0x7",
        ),
        (
            "CHK-MBX-ERR-CLEAR-ON-READ",
            "MBX_ERR_CLEAR_ON_READ",
            "second ERROR_FLAGS read is 0 while IRQS bit 2 stays set",
        ),
        (
            "CHK-MBX-ERR-IRQ-ACK",
            "MBX_ERR_IRQ_ACK",
            "IRQEN.eirq raises lane 0, IRQS write-one acknowledge clears bit 2 and drops lane 0",
        ),
        (
            "CHK-MBX-STATUS-FLUSH",
            "MBX_STATUS_FLUSH",
            "wflush leaves STATUS 0x1 and the latched IRQS bit 0 set",
        ),
        (
            "CHK-MBX-RO-WRITES",
            "MBX_RO_WRITES",
            "writes to STATUS, READ_DATA, ERROR_FLAGS and IRQP are SLVERR and change nothing",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK_TIMEOUT_PATHS", "bounded J2A and lane-0 waits with last state"),
    ],
    "smu_smc_mailbox_threshold_lane_test": [
        (
            "CHK-MBX-WT-LATCH-GATED",
            "MBX_WT_LATCH_GATED",
            "with IRQEN 0 and one word queued IRQS bit 0 and STATUS bit 2 read 1, lane 0 stays low",
        ),
        (
            "CHK-MBX-IRQP-GATING",
            "MBX_IRQP_GATING",
            "IRQP reads 0 with IRQEN 0 and 1 after IRQEN is set, lane 0 rises",
        ),
        (
            "CHK-MBX-WT-ENABLE-DROP",
            "MBX_WT_ENABLE_DROP",
            "clearing IRQEN drops lane 0 while STATUS bit 2 stays 1",
        ),
        (
            "CHK-MBX-WT-ACK-BASELINE",
            "MBX_WT_ACK_BASELINE",
            "flush empties STATUS, IRQS stays latched until the write-one acknowledge drops lane 0",
        ),
        (
            "CHK-MBX-WT-CLAMP",
            "MBX_WT_CLAMP",
            "WIRQT 5 clamps to depth - 1: one word no IRQ, two words raise lane 0",
        ),
        (
            "CHK-MBX-WT-REASSERT-LOG",
            "MBX_WT_REASSERT_LOG",
            "acknowledge with occupancy above WIRQT observed and logged, STATUS bit 2 stays 1",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK_TIMEOUT_PATHS", "bounded J2A and lane-0 waits with last state"),
    ],
    "smu_smc_reset_ctrl_test": [
        ("CHK-RST-PRIMARY", "RST_PRIMARY_SMC_1", "SMC primary reset released"),
        ("CHK-RST-COLD-STABLE", "RST_COLD_STABLE_1", "cold stable released"),
    ],
    "smu_smc_reset_unit_state_test": [
        (
            "CHK-BOOT-RSTUNIT-CONFIG",
            "BOOT_RSTUNIT_CONFIG",
            "SS_CONFIG, locks, cold reset and force read 0 and SS_WARM_RESET_N reads all ones",
        ),
        (
            "CHK-BOOT-RSTUNIT-HOLDS",
            "BOOT_RSTUNIT_HOLDS",
            "the four hold registers read their RDL reset value 0",
        ),
        (
            "CHK-BOOT-RSTUNIT-ISOLATION",
            "BOOT_RSTUNIT_ISOLATION",
            "the four isolation registers, the two FLR counter registers and SYNC_REG read their "
            "RDL reset value 0",
        ),
        (
            "CHK-BOOT-RSTUNIT-VIS",
            "BOOT_RSTUNIT_VIS",
            "ISOLATE_REQ_VIS bits 4 and 8 read their RDL reset value 1; bit 0 reads the idle pin "
            "level 0, which differs from the RDL reset value 1 of this hardware-written field; "
            "logged, not compared",
        ),
        (
            "CHK-BOOT-RSTUNIT-IDLE-OUTPUTS",
            "BOOT_RSTUNIT_IDLE_OUTPUTS",
            "isolate_req_o, skip_mem_repair_o and sync_irq_o are 0 with the pins idle",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK_TIMEOUT_PATHS", "bounded J2A waits with last state"),
    ],
    "smu_smc_gpio_pad_output_test": [
        (
            "CHK-SMU-LANE-GPIO-OUT",
            "CHK-SMU-LANE-GPIO-OUT",
            "every pad driven from its own DATA_CTRL with a per-pad code follows CORE2PAD and "
            "loops it back to its own gpio_interrupt_o lane, and transmit alone drives the pad "
            "with that lane low",
        ),
    ],
    "smu_smc_gpio_spi_pad_ownership_test": [
        (
            "CHK-DBG-GPIO-SPI-OWNED",
            "DBG_GPIO_SPI_OWNED",
            "pads 0-3, 8 and 9 read lsio_enable 1 and keep their level under core2pad 1 and 0",
        ),
        (
            "CHK-DBG-GPIO-SPI-DISABLE",
            "DBG_GPIO_SPI_DISABLE",
            "lsio_disable clears lsio_enable on pads 0, 8 and 9 and the pad follows core2pad",
        ),
        (
            "CHK-DBG-GPIO-SPI-UNDRIVEN",
            "DBG_GPIO_SPI_UNDRIVEN",
            "pads 4-7, 10 and 54 are not driven by the SPI host in either direction until "
            "lsio_disable is set",
        ),
        (
            "CHK-DBG-GPIO-SPI-PRIORITY",
            "DBG_GPIO_SPI_PRIORITY",
            "the same register write is ignored with lsio_disable clear and obeyed with it set",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK_TIMEOUT_PATHS", "bounded J2A/AXI/settle waits with last state"),
        ("CHK-NONVAC", "CHK-NONVAC", "ordered sim-time fence S1<...<S6<PASS"),
    ],
    "smu_smc_gpio_access_filter_test": [
        (
            "CHK-DBG-GPIO-FILTER-RESET",
            "DBG_GPIO_FILTER_RESET",
            "ACCESS_FILTER of pad 11 reads its reset value and AxPROT 0 and 7 are admitted "
            "with both filters disabled",
        ),
        (
            "CHK-DBG-GPIO-FILTER-WRITE",
            "DBG_GPIO_FILTER_WRITE",
            "with write_filter_enable set only AWPROT equal to awprot_requirement is admitted "
            "and the other seven values are refused without changing the pad",
        ),
        (
            "CHK-DBG-GPIO-FILTER-READ",
            "DBG_GPIO_FILTER_READ",
            "with read_filter_enable set only ARPROT equal to arprot_requirement returns the "
            "DATA_CTRL value and the other seven values are refused",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK_TIMEOUT_PATHS", "bounded J2A/AXI/settle waits with last state"),
        ("CHK-NONVAC", "CHK-NONVAC", "ordered sim-time fence S1<...<S5<PASS"),
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
    "smu_secure_tm_real_sense_window_test": [
        (
            "CHK-SEP-SECURE-TM-CLEAR-REAL",
            "SEP_SECURE_TM_CLEAR_REAL",
            "secure_tm_o latches 1 in leg 1, reads 0 under the second cold reset and stays 0 "
            "from release to the real done rise",
        ),
        (
            "CHK-SEP-SECURE-TM-NO-EARLY-FOLLOW",
            "SEP_SECURE_TM_NO_EARLY_FOLLOW",
            "a strap pulse between response strobes 100 and 180 and the strap at 0 after done "
            "leave secure_tm_o at 0",
        ),
        (
            "CHK-TIMEOUT-PATHS",
            "CHK_TIMEOUT_PATHS",
            "bounded done/reset/strobe/TAP waits with last state",
        ),
        ("CHK-NONVAC", "CHK-NONVAC", "ordered sim-time fence S1<...<S7<PASS"),
    ],
    "smu_sep_cold_reassert_during_sense_test": [
        (
            "CHK-SEP-RESET-REASSERT",
            "SEP_RESET_REASSERT",
            "sep_reset_n_o reads 0 on every sample while the cold reset is re-asserted after done "
            "and after response words 0 and 128, and near 255 when that fall lands before the "
            "256th strobe",
        ),
        (
            "CHK-SEP-DONE-COLD-CLEAR",
            "SEP_DONE_COLD_CLEAR",
            "done reads 0 under the re-asserted cold reset and rises once, after at least 256 "
            "response strobes, in the second sense",
        ),
        (
            "CHK-SEP-SENSE-ABORT-RESTART",
            "SEP_SENSE_ABORT_RESTART",
            "an aborted sense leaves done at 0 with no rise and the final sense restarts and "
            "delivers at least 256 strobes before its single done rise",
        ),
        (
            "CHK-TIMEOUT-PATHS",
            "CHK_TIMEOUT_PATHS",
            "bounded done/strobe/cold-reset/TAP waits with last state",
        ),
        ("CHK-NONVAC", "CHK-NONVAC", "ordered sim-time fence S1<...<S8<PASS"),
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
    "smu_smc_scratch_bridge_readback_test": [
        (
            "CHK-COMP-SCRATCH-READBACK",
            "COMP_SCRATCH_READBACK",
            "SCRATCH[0..15] read 0 at reset and read back the written pattern over JTAG2AXI",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK_TIMEOUT_PATHS", "bounded J2A waits with last state"),
    ],
    "smu_smc_smoke_test": [
        ("CHK-SMC-ROM-READ", "SMC_ROM_READ_OK", "SMC ROM read activity observed"),
        (
            "CHK-SMC-SCRATCH-WRITE",
            "SMC_SCRATCH_WRITE_OK",
            "SMC scratch SRAM write activity observed",
        ),
        (
            "CHK-SMC-TEST-PASS",
            "SMC_TEST_PASS_OK",
            "SMC firmware wrote TEST_PASS and never TEST_FAIL",
        ),
        ("CHK-NONVAC", "CHK-NONVAC", "boot scoreboard verdict on the SEP=1 wrapper"),
    ],
    "smu_smc_sram_init_sequence_test": [
        (
            "CHK-BOOT-INIT-DONE-ONCE",
            "BOOT_INIT_DONE_ONCE",
            "smc_init_mem_done_o rises once on the cold boot, with scratch writes above 0 at the "
            "rise and none in the next 64 clk_smu",
        ),
        (
            "CHK-BOOT-INIT-BEFORE-FETCH",
            "BOOT_INIT_BEFORE_FETCH",
            "smc_rom_read_count_o is 0 until the done rise and first increments after it",
        ),
        (
            "CHK-BOOT-INIT-REARM",
            "BOOT_INIT_REARM",
            "after a second cold reset done rises once more with a write count above the count "
            "read during the reset",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK_TIMEOUT_PATHS", "bounded done/ROM-read waits with last state"),
    ],
    "smu_smc_ss_reset_ctrl_sweep_test": [
        (
            "CHK-SMU-SSRST-RESET",
            "CHK-SMU-SSRST-RESET",
            "each of the seven reset-unit registers owning an ss_reset_ctrl_o field, and "
            "SS_COLD_RESET_LOCK, reads the reset value reset_unit.h states, and the "
            "boundary word carries that value on all 32 lanes",
        ),
        (
            "CHK-SMU-SSRST-LANE",
            "CHK-SMU-SSRST-LANE",
            "ss_reset_ctrl_o[i].<field> carries bit i of the register that owns the field "
            "through five binary-code patterns and their complements, so each lane answers "
            "with a signature unique to its index, and back to the RDL reset value",
        ),
        (
            "CHK-SMU-SSRST-LOCK",
            "CHK-SMU-SSRST-LOCK",
            "a set SS_COLD_RESET_LOCK bit cannot be cleared and blocks its own lane of "
            "SS_COLD_RESET_N while the same write reaches every unlocked lane, at the "
            "register and at the boundary",
        ),
        (
            "CHK-SMU-SSRST-TOGGLE",
            "CHK-SMU-SSRST-TOGGLE",
            "ss_reset_ctrl_o was sampled once per register state the sweep left behind, and "
            "all 32x7 field bits were observed both rising and falling",
        ),
    ],
    "smu_smc_wdt_boundary_timeout_test": [
        (
            "CHK-SMU-WDT-RELEASE",
            "CHK-SMU-WDT-RELEASE",
            "the warm reset clears the first watchdog timeout",
        ),
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
            "to smc_wdt_second_timeout_o, and the SMC warm reset drops",
        ),
    ],
    "smu_smc_wdt_sanity_test": [
        ("CHK-WDT-UNLOCK", "WDT_UNLOCK_OK", "WDT unlock SUCCESS"),
    ],
    "smu_smc_wdt_timeout_irq_test": [
        ("CHK-WDT-IP0", "WDT_WDOGIP0", "WDOGIP0 sets after enable+CMP"),
    ],
    "smu_ss_config_lane_drive_test": [
        (
            "CHK-COMP-SS-CONFIG-SINGLE-LANE",
            "COMP_SS_CONFIG_SINGLE_LANE",
            "writing SS_CONFIG = 1 << i leaves ss_config_o equal to 1 << i for each of the 32 "
            "lanes",
        ),
        (
            "CHK-COMP-SS-CONFIG-ALL-ONES-ZERO",
            "COMP_SS_CONFIG_ALL_ONES_ZERO",
            "all-ones then all-zeros writes drive ss_config_o to the same value and SS_CONFIG "
            "reads 0",
        ),
        (
            "CHK-TIMEOUT-PATHS",
            "CHK_TIMEOUT_PATHS",
            "bounded J2A and pin waits with last state",
        ),
        (
            "CHK-NONVAC",
            "CHK-NONVAC",
            "ordered fence S1<S2<S3<S4 with positive simulated time between steps",
        ),
    ],
    "smu_sys_in_filter_program_jtag_test": [
        ("CHK-AXI-FILTER-OKAY", "AXI_FILTER_OKAY", "after program window OKAY"),
    ],
    "smu_sys_in_filter_reprogram_shrink_test": [
        ("CHK-AXI-FILTER-OKAY", "AXI_FILTER_OKAY", "shrink restores BLOCK_BY_DEFAULT"),
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
            "CHK-SMU-TEL-EVERY-RECEIVER",
            "CHK-SMU-TEL-EVERY-RECEIVER",
            "each receiver takes a message on its own ATB lane and reports its probe id",
        ),
        (
            "CHK-SMU-TEL-BACKPRESSURE",
            "CHK-SMU-TEL-BACKPRESSURE",
            "back-to-back beats on a faster telemetry clock make telemetry_atready_o fall and "
            "rise, the RX flush empties a queued buffer, and the next message reads back whole",
        ),
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
            "holds while telemetry_afready_i is low, the pin still high when it "
            "rises; raising it retires the "
            "request at the pin and clears the register field, and lowering it "
            "again at the wrapper pin leaves the request retired",
        ),
    ],
    "smu_telemetry_queue_threshold_test": [
        (
            "CHK-TELQ-POP-EMPTY",
            "TELQ_POP_EMPTY",
            "a pop on the empty queue leaves BUFFER_EMPTY set and PROBE_ID 0",
        ),
        (
            "CHK-TELQ-EMPTY-FULL",
            "TELQ_EMPTY_FULL",
            "BUFFER_EMPTY drops after the first message and BUFFER_FULL sets only on the eighth",
        ),
        (
            "CHK-TELQ-THRESHOLD-LIVE",
            "TELQ_THRESHOLD_LIVE",
            "INTR_STATUS.BUFFER_THRESHOLD is 0 up to three queued and 1 above the threshold",
        ),
        (
            "CHK-TELQ-ORDER",
            "TELQ_ORDER",
            "successive pops expose probe ids 2 to 8 in arrival order, then 0 when empty",
        ),
        (
            "CHK-TELQ-THRESHOLD-CLEAR",
            "TELQ_THRESHOLD_CLEAR",
            "a write of 1 leaves the status at 1; draining to the threshold or raising it reads 0",
        ),
        (
            "CHK-TELQ-THRESHOLD-TEST",
            "TELQ_THRESHOLD_TEST",
            "INTR_TEST.BUFFER_THRESHOLD forces the status to 1 and releases it to 0",
        ),
        (
            "CHK-TIMEOUT-PATHS",
            "CHK_TIMEOUT_PATHS",
            "bounded J2A and ATB waits with last state",
        ),
    ],
    "smu_telemetry_reset_state_test": [
        (
            "CHK-TELR-CTRL-STATUS",
            "TELR_CTRL_STATUS",
            "STATUS reads BUFFER_EMPTY set and BUFFER_FULL clear, and CTRL, INTR_STATUS, "
            "INTR_ENABLE and INTR_TEST read 0, on all three receivers",
        ),
        (
            "CHK-TELR-MESSAGE-ZERO",
            "TELR_MESSAGE_ZERO",
            "PROBE_ID, COUNTER_VLDS and the counters read 0 on the empty queue",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK_TIMEOUT_PATHS", "bounded J2A waits with last state"),
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
        (
            "CHK-OCTS-PRESET-EXTREMES",
            "CHK-OCTS-PRESET-EXTREMES",
            "an all-high and a zero PRESET each load timer_count_o within the reload slack, "
            "and the free run shows each of bits 0..12 at 0 and at 1",
        ),
    ],
    # --- P0 composition and bring-up leaves on the production wrapper ---
    # These set use_shared_env = True, so prove_mapped_features runs for them
    # and every row below has to be logged by a passing compare.
    # CHK-NONVAC has no row here: SmuScoreboard.check_phase logs it after
    # run_phase has run the prover, so a row for it could never be proved, and
    # its own zero-check refusal covers the same ground.
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
        (
            "CHK-SMU-XTRIG-CTP-S6",
            "CHK-SMU-XTRIG-CTP-S6",
            "bench-held resting CTP data inputs leave the CTP outputs static (live control: "
            "smu_xtrig_ctp_pad_test)",
        ),
        ("CHK-SMU-LC-STATE-S1", "CHK-SMU-LC-STATE-S1", "lc_state_o is 8 bits, 2*LC_STATE_WIDTH"),
        (
            "CHK-SMU-LC-DEMOTE-S1",
            "CHK-SMU-LC-DEMOTE-S1",
            "both lcc_demote_state outputs are 2 bits",
        ),
        (
            "CHK-SMU-EFUSE-SHIM-SMC-S3",
            "CHK-SMU-EFUSE-SHIM-SMC-S3",
            "smc_shadow_regs reaches the smu_wrapper port and the boundary at full width and, "
            "after the sense, carries the non-zero image",
        ),
        (
            "CHK-SMU-FUSE-SENSE-S4",
            "CHK-SMU-FUSE-SENSE-S4",
            "skip_mem_repair_o is one bit and clear with no isolation request pending",
        ),
        (
            "CHK-SMU-SSRESET-S2",
            "CHK-SMU-SSRESET-S2",
            "ss_reset_ctrl_o has 32 elements",
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
    "smu_composition_parameter_test": [
        (
            "CHK-SMU-SEC-TOKEN-S2",
            "CHK-SMU-SEC-TOKEN-S2",
            "SEP_SEC_DISABLE_TOKEN is 256 bits at the SEP eFuse controller and is the digest "
            "the bench binds in CFG",
        ),
        (
            "CHK-SMU-OTPAXI-SEP-S3",
            "CHK-SMU-OTPAXI-SEP-S3",
            "DTP SEP OTP pipeline depths are the specified fixed 3",
        ),
        (
            "CHK-SMU-NOSEP-S4",
            "CHK-SMU-NOSEP-S4",
            "CFG reaches smu unchanged and each consumer parameter is its specified default",
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
    "smu_smc_efuse_shadow_map_readback_test": [
        (
            "CHK-BOOT-SHADOW-SAMPLES",
            "BOOT_SHADOW_SAMPLES",
            "sampled SMC eFuse map words read over JTAG2AXI and the stream words of the same "
            "index equal the words of the eFuse image the run loads, and the map words equal "
            "the stream words",
        ),
        (
            "CHK-BOOT-SHADOW-ELEMENTS",
            "BOOT_SHADOW_ELEMENTS",
            "the first word of each named smc_efuse_map element equals its word in the eFuse "
            "image the run loads",
        ),
        (
            "CHK-BOOT-SENSE-STATUS",
            "BOOT_SENSE_STATUS",
            "EFUSE_INTERFACE_CTRL_STATUS.efuse_sense_done reads 1 after smc_fuse_sense_done_o rose",
        ),
        (
            "CHK-TIMEOUT-PATHS",
            "CHK_TIMEOUT_PATHS",
            "bounded sense, capture and J2A waits with last state",
        ),
    ],
    "smu_smc_efuse_shadow_sense_reset_test": [
        (
            "CHK-SMU-EFUSE-SHADOW-SENSE",
            "CHK-SMU-EFUSE-SHADOW-SENSE",
            "with +skip_fuse_sense unset, smc_shadow_regs carries the whole "
            "SMC_TOP_SMC_EFUSE_MAP_SIZE-wide sensed image, register slice by register "
            "slice at the byte offsets smc_addr.h gives them, and holds it after the sense",
        ),
        (
            "CHK-SMU-EFUSE-SHADOW-RESET",
            "CHK-SMU-EFUSE-SHADOW-RESET",
            "smc_shadow_regs reads the zero every smc_efuse_map.rdl field resets to, both "
            "before the sense completes and for the whole time rst_cold_ni is held after it",
        ),
        (
            "CHK-SMU-EFUSE-SHADOW-TOGGLE",
            "CHK-SMU-EFUSE-SHADOW-TOGGLE",
            "the image programs every bit of the map, and every one of them is observed "
            "going 0 -> 1 on the sense and 1 -> 0 on the cold reset",
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
            "CHK-SMU-MEMINIT-RESTORED",
            "CHK-SMU-MEMINIT-RESTORED",
            "with the input lowered again a cold reset starts the zeroing sweep",
        ),
        (
            "CHK-SMU-MEMINIT-DISABLED",
            "CHK-SMU-MEMINIT-DISABLED",
            "with smc_disable_sram_auto_init_i high the zeroing sweep never "
            "starts and no zeroing write reaches the scratch RAM, and "
            "smc_init_mem_done_o reads low while the cold reset is asserted; "
            "what it read beforehand and how it behaves after the release is "
            "recorded, not compared",
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
            "CHK-SMU-CTM-EVERY-LANE",
            "CHK-SMU-CTM-EVERY-LANE",
            "a trigger routed into each DTP internal lane raises that lane once and no other",
        ),
        (
            "CHK-SMU-CTP-EVERY-LANE",
            "CHK-SMU-CTP-EVERY-LANE",
            "each lane in point-to-point moves its pads, acknowledges and routes to its successor",
        ),
        (
            "CHK-SMU-CTP-WIRE-RX-EVERY-LANE",
            "CHK-SMU-CTP-WIRE-RX-EVERY-LANE",
            "a pull of each lane's private wire raises that lane's ct_dst once at the latency",
        ),
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
            "wire-OR pull of lane 2's shared wire routes the same way, the "
            "pulse following the pull rather than the release",
        ),
        (
            "CHK-SMU-CTP-WIRE-IDLE",
            "CHK-SMU-CTP-WIRE-IDLE",
            "with every CT_Req_out wire resting at its pull after reset, no "
            "wire-OR lane's ct_dst rises and the wire-mismatch flag is 0",
        ),
        (
            "CHK-SMU-CTP-WIRE-RX",
            "CHK-SMU-CTP-WIRE-RX",
            "a chiplet pull of lane 2's private wire raises tb_xtrig_ctp_ct_dst[2] "
            "exactly CT_DST_LATENCY clocks after the wire is first seen asserted, "
            "once, and the release raises nothing further",
        ),
        (
            "CHK-SMU-CTP-WIRE-SHARED",
            "CHK-SMU-CTP-WIRE-SHARED",
            "three wire-OR lanes on one group wire: one chiplet pull reaches "
            "every member's ct_dst once at the same latency and leaves every "
            "non-member lane quiet; two members pulled in overlapping windows "
            "still reach every member exactly once and leave every non-member "
            "lane quiet",
        ),
    ],
    "smu_xtrig_cold_reset_clears_ctn_test": [
        (
            "CHK-CTN-RESET-CLEARS-REGS",
            "CHK-CTN-RESET-CLEARS-REGS",
            "CT_SRC[0], CTP[0].CONFIG and STRETCH_MULT read their programmed values before the "
            "cold reset and their RDL reset value 0 after it",
        ),
        (
            "CHK-CTP-RESET-MID-REQUEST",
            "CHK-CTP-RESET-MID-REQUEST",
            "xtrig_ctp_req_out_dout_o[1] is low within 16 clk_smu of the reset and stays low, "
            "CTP[1].STATUS reads 0 (only ACK_IN while the acknowledge is still held), from "
            "REQ_ASSERTED and WAIT_ACK_DEASSERT",
        ),
        (
            "CHK-CLKSTOP-RESET-LOW",
            "CHK-CLKSTOP-RESET-LOW",
            "dtp_stop_clks_o is 0 while the DTP reset is asserted with the lane request held "
            "and on the first edge after release",
        ),
        (
            "CHK-TIMEOUT-PATHS",
            "CHK_TIMEOUT_PATHS",
            "bounded J2A, reset and pin waits with last state",
        ),
    ],
    "smu_xtrig_ctm_illegal_phase_test": [
        ("CHK-XT-ILLEGAL", "XT_ILLEGAL_PHASE", "DTP[9:2] follows abort/double-req pin patterns"),
    ],
    "smu_xtrig_ctm_remap_test": [
        ("CHK-XT-CTM-REMAP", "XT_CTM_REMAP", "product-pin CTM remap"),
    ],
    "smu_xtrig_ctm_select_walk_test": [
        (
            "CHK-CT-SRC-WALK",
            "CHK-CT-SRC-WALK",
            "CT_DST_SELECT[25:0] stores each walked bit and reads it back exactly",
        ),
        (
            "CHK-CT-SRC-KINDS",
            "CHK-CT-SRC-KINDS",
            "each of the three CT_SRC index kinds reads back its walked bits and reads 0 after "
            "the clear",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK_TIMEOUT_PATHS", "bounded J2A waits with last state"),
    ],
    "smu_xtrig_ctn_csr_rw_test": [
        (
            "CHK-CTP-CFG-STRETCH-RW",
            "CHK-CTP-CFG-STRETCH-RW",
            "port 3 CONFIG reads back 0x7 and 0x0 and STRETCH_MULT reads back 0, 1 and 0xFFFF as "
            "written",
        ),
        (
            "CHK-CTP-STATUS-WRITE-IGNORED",
            "CHK-CTP-STATUS-WRITE-IGNORED",
            "a STATUS write completes with success and the next read equals the read before it",
        ),
        (
            "CHK-CTP-WINDOW-INDEPENDENCE",
            "CHK-CTP-WINDOW-INDEPENDENCE",
            "each of 16 ports reads back its own STRETCH_MULT and ports 0 and 15 their own CONFIG",
        ),
        (
            "CHK-CTN-SERIALISED-ACCESS",
            "CHK-CTN-SERIALISED-ACCESS",
            "interleaved CT_SRC and CTP accesses over JTAG2AXI return the values last written to "
            "each register",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK_TIMEOUT_PATHS", "bounded J2A waits with last state"),
    ],
    "smu_xtrig_ctn_reset_values_test": [
        (
            "CHK-CTN-CTSRC-RESET",
            "CHK-CTN-CTSRC-RESET",
            "all 26 CT_SRC CONFIG_0 reads succeed and return 0",
        ),
        (
            "CHK-CTN-CTP-RESET",
            "CHK-CTN-CTP-RESET",
            "CONFIG, STATUS and STRETCH_MULT of all 16 CTPs read 0",
        ),
        ("CHK-TIMEOUT-PATHS", "CHK_TIMEOUT_PATHS", "bounded J2A waits with last state"),
    ],
    "smu_xtrig_ctp_status_reset_test": [
        (
            "CHK-STATUS-BUSY",
            "CHK-STATUS-BUSY",
            "STATUS.BUSY reads 1 while the request is outstanding and 0 after the handshake "
            "completes",
        ),
        (
            "CHK-STATUS-LEVELS",
            "CHK-STATUS-LEVELS",
            "REQ_OUT, ACK_IN, REQ_IN and ACK_OUT read 1 at INVERT 0 and 1; REQ_OUT and ACK_OUT "
            "read 0 in wire-OR",
        ),
        (
            "CHK-HS-RESET-RECOVER",
            "CHK-HS-RESET-RECOVER",
            "RESET drops a stuck req_out and REQ_OUT; the first trigger after RESET clears raises "
            "it again",
        ),
        (
            "CHK-HS-RESET-DISCARD",
            "CHK-HS-RESET-DISCARD",
            "req_out_dout[2] stays low for 64 clk_smu while a trigger arrives with RESET = 1, "
            "and for 64 clk_smu after RESET clears with the wire released",
        ),
        (
            "CHK-HS-RESET-RX",
            "CHK-HS-RESET-RX",
            "with RESET = 1 a request in is acknowledged and BUSY holds until it is released",
        ),
        (
            "CHK-TIMEOUT-PATHS",
            "CHK_TIMEOUT_PATHS",
            "bounded J2A and pad waits with last state",
        ),
    ],
}


def primary_token(testcase: str) -> str | None:
    rows = TEST_EVIDENCE.get(testcase)
    return rows[0][1] if rows else None


def tokens_for(testcase: str) -> list[str]:
    return [t for _, t, _ in TEST_EVIDENCE.get(testcase, [])]
