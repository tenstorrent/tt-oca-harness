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
    "smu_dtp_scan_chain_boundary_test": [
        (
            "CHK-SMU-IJTAG-GATE",
            "CHK-SMU-IJTAG-GATE",
            "under SELECT_IJTAG with all three SIBs open every host select "
            "asserts for at least the DR shift TCKs and the scan returns "
            "the open-chain word; from the Update-IR that loads IDCODE, "
            "none of the three selects asserts over an IDCODE DR scan and "
            "the IR scan of a second IDCODE load, counted on jtag_tck, and "
            "the open-chain word returns again afterwards",
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
            "an unselected I/O STAP drives no TDO enable and its host TMS "
            "holds the TMS-Hold reset value 0 on every TCK of an IDCODE "
            "scan; selected over TAP_3DCR, a network IDCODE scan of 37 "
            "cells (the PTAP register, the I/O STAP's TDO and TDI lockup "
            "pair over the bare bench return, one TCK, and four SIBs) and "
            "an 8-bit tail returns four SIB bits of 0, the masked lockup "
            "bit, the IDCODE and the tail 37 bits late, tb_stap_io_tdo "
            "carries the IDCODE LSB first then the tail on all 45 Shift-DR "
            "TCKs, the enable is high on every Shift-IR and Shift-DR TCK "
            "and low on every other TCK, read against the PTAP state, and "
            "covers exactly the 6 + 45 shift TCKs, host TMS matches the "
            "primary TAP on every TCK, and the extra STAP stays quiet",
        ),
        (
            "CHK-SMU-STAP-EXTRA-SELECT",
            "CHK-SMU-STAP-EXTRA-SELECT",
            "an unselected extra STAP drives no TDO enable and its host TMS "
            "holds the TMS-Hold reset value 0 on every TCK of an IDCODE "
            "scan; selected over TAP_3DCR without Config-Hold, a network "
            "IDCODE scan of 36 cells (the PTAP register, three SIBs ahead, "
            "the bare bench return and its own SIB) and an 8-bit tail "
            "returns four SIB bits of 0, the IDCODE and the tail 36 bits "
            "late, tb_stap_extra0_tdo carries three SIB captures, the "
            "IDCODE LSB first and the tail on all 44 Shift-DR TCKs, the "
            "enable is high on every Shift-IR and Shift-DR TCK and low on "
            "every other TCK, read against the PTAP state, and covers "
            "exactly the 6 + 44 shift TCKs, host TMS matches the primary "
            "TAP on every TCK, and the I/O STAP stays quiet",
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
    "smu_smc_gpio_pad_output_test": [
        (
            "CHK-SMU-LANE-GPIO-OUT",
            "CHK-SMU-LANE-GPIO-OUT",
            "every pad driven from its own DATA_CTRL with a per-pad code follows CORE2PAD and "
            "loops it back to its own gpio_interrupt_o lane, and transmit alone drives the pad "
            "with that lane low",
        ),
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
    # CHK-SMU-SEC-TOKEN-S1 is logged by the body as an observation the card does not
    # claim, so it is not a row here.
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
