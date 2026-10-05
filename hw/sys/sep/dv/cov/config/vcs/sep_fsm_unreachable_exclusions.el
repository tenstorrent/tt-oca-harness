// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//==================================================
// SEP VCS coverage exclusions -- FSM transitions unreachable by elaboration.
// Format Version: 2
// ExclMode: default
//
// Scope: the cocotb VCS elaboration of sep_uvm_top, target `default`.
//
// Waives only FSM transitions that no next-state assignment can reach with the
// parameters SEP elaborates. Reset-in-flight transitions, error/abort paths and
// illegal-input paths are reachable and stay in the denominator as test gaps.
// Honesty rules: (1) never waive an object any leaf covered (checked with
// urg -excl_strict); (2) every entry cites the RTL tie or parameter, file:line.
// Entries are copied from `urg -dump full_exclusions fsm` on the merged VDB.
//==================================================

CHECKSUM: "2097437693 3453034612"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_drbg_s3c_scan.u_csrng_axi_lite_to_tlul
ANNOTATION: "FSM-PARAM-DEAD: IDLE->AXI_B_RESP is the zero-strobe write shortcut at hw/common/axi/axi_lite_to_tlul.sv:158, gated by parameter ACK_ZERO_STROBE_WRITE, default 1'b0 at :30. This instance (hw/ip/drbg/rtl/drbg.sv:236) does not override it, so the branch elaborates to constant false and no next-state assignment reaches AXI_B_RESP from IDLE. AXI_B_RESP stays graded through TL_PUT_ACK->AXI_B_RESP. Only u_spi_axi_lite_to_tlul sets the parameter (hw/sys/sep/rtl/sep_ot_spi_wrap.sv:115) and it is NOT waived."
Fsm state_q "3453034612"
Transition IDLE->AXI_B_RESP "0->6"

CHECKSUM: "2097437693 3453034612"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_drbg_s3c_scan.u_edn_axi_lite_to_tlul
ANNOTATION: "FSM-PARAM-DEAD: IDLE->AXI_B_RESP is the zero-strobe write shortcut at hw/common/axi/axi_lite_to_tlul.sv:158, gated by parameter ACK_ZERO_STROBE_WRITE, default 1'b0 at :30. This instance (hw/ip/drbg/rtl/drbg.sv:269) does not override it, so the branch elaborates to constant false and no next-state assignment reaches AXI_B_RESP from IDLE. AXI_B_RESP stays graded through TL_PUT_ACK->AXI_B_RESP. Only u_spi_axi_lite_to_tlul sets the parameter (hw/sys/sep/rtl/sep_ot_spi_wrap.sv:115) and it is NOT waived."
Fsm state_q "3453034612"
Transition IDLE->AXI_B_RESP "0->6"

CHECKSUM: "2097437693 3453034612"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_hmac_wrapper_s3c_scan.u_hmac_axi_lite_to_tlul
ANNOTATION: "FSM-PARAM-DEAD: IDLE->AXI_B_RESP is the zero-strobe write shortcut at hw/common/axi/axi_lite_to_tlul.sv:158, gated by parameter ACK_ZERO_STROBE_WRITE, default 1'b0 at :30. This instance (hw/sys/sep/rtl/hmac_wrapper.sv:83) does not override it, so the branch elaborates to constant false and no next-state assignment reaches AXI_B_RESP from IDLE. AXI_B_RESP stays graded through TL_PUT_ACK->AXI_B_RESP. Only u_spi_axi_lite_to_tlul sets the parameter (hw/sys/sep/rtl/sep_ot_spi_wrap.sv:115) and it is NOT waived."
Fsm state_q "3453034612"
Transition IDLE->AXI_B_RESP "0->6"

CHECKSUM: "2097437693 3453034612"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_otbn_wrapper_s3c_scan.u_axi_lite_to_tlul
ANNOTATION: "FSM-PARAM-DEAD: IDLE->AXI_B_RESP is the zero-strobe write shortcut at hw/common/axi/axi_lite_to_tlul.sv:158, gated by parameter ACK_ZERO_STROBE_WRITE, default 1'b0 at :30. This instance (hw/sys/sep/rtl/sep_crypto_otbn_wrapper.sv:73) does not override it, so the branch elaborates to constant false and no next-state assignment reaches AXI_B_RESP from IDLE. AXI_B_RESP stays graded through TL_PUT_ACK->AXI_B_RESP. Only u_spi_axi_lite_to_tlul sets the parameter (hw/sys/sep/rtl/sep_ot_spi_wrap.sv:115) and it is NOT waived."
Fsm state_q "3453034612"
Transition IDLE->AXI_B_RESP "0->6"

CHECKSUM: "2097437693 3453034612"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_aes_wrapper_s3c_scan.u_aes_axi_lite_to_tlul
ANNOTATION: "FSM-PARAM-DEAD: IDLE->AXI_B_RESP is the zero-strobe write shortcut at hw/common/axi/axi_lite_to_tlul.sv:158, gated by parameter ACK_ZERO_STROBE_WRITE, default 1'b0 at :30. This instance (hw/sys/sep/rtl/aes_wrapper.sv:60) does not override it, so the branch elaborates to constant false and no next-state assignment reaches AXI_B_RESP from IDLE. AXI_B_RESP stays graded through TL_PUT_ACK->AXI_B_RESP. Only u_spi_axi_lite_to_tlul sets the parameter (hw/sys/sep/rtl/sep_ot_spi_wrap.sv:115) and it is NOT waived."
Fsm state_q "3453034612"
Transition IDLE->AXI_B_RESP "0->6"

CHECKSUM: "2097437693 3453034612"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_kmac_wrapper_s3c_scan.u_kmac_axi_lite_to_tlul
ANNOTATION: "FSM-PARAM-DEAD: IDLE->AXI_B_RESP is the zero-strobe write shortcut at hw/common/axi/axi_lite_to_tlul.sv:158, gated by parameter ACK_ZERO_STROBE_WRITE, default 1'b0 at :30. This instance (hw/sys/sep/rtl/kmac_wrapper.sv:93) does not override it, so the branch elaborates to constant false and no next-state assignment reaches AXI_B_RESP from IDLE. AXI_B_RESP stays graded through TL_PUT_ACK->AXI_B_RESP. Only u_spi_axi_lite_to_tlul sets the parameter (hw/sys/sep/rtl/sep_ot_spi_wrap.sv:115) and it is NOT waived."
Fsm state_q "3453034612"
Transition IDLE->AXI_B_RESP "0->6"

CHECKSUM: "2097437693 3453034612"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_wdt_wrap.u_wdt_axi_lite_to_tlul
ANNOTATION: "FSM-PARAM-DEAD: IDLE->AXI_B_RESP is the zero-strobe write shortcut at hw/common/axi/axi_lite_to_tlul.sv:158, gated by parameter ACK_ZERO_STROBE_WRITE, default 1'b0 at :30. This instance (hw/sys/sep/rtl/sep_wdt_wrap.sv:137) does not override it, so the branch elaborates to constant false and no next-state assignment reaches AXI_B_RESP from IDLE. AXI_B_RESP stays graded through TL_PUT_ACK->AXI_B_RESP. Only u_spi_axi_lite_to_tlul sets the parameter (hw/sys/sep/rtl/sep_ot_spi_wrap.sv:115) and it is NOT waived."
Fsm state_q "3453034612"
Transition IDLE->AXI_B_RESP "0->6"

CHECKSUM: "2097437693 3453034612"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_dma_wrap.u_axi_lite_to_tlul_reg
ANNOTATION: "FSM-PARAM-DEAD: IDLE->AXI_B_RESP is the zero-strobe write shortcut at hw/common/axi/axi_lite_to_tlul.sv:158, gated by parameter ACK_ZERO_STROBE_WRITE, default 1'b0 at :30. This instance (hw/sys/sep/rtl/sep_dma_wrap.sv:227) does not override it, so the branch elaborates to constant false and no next-state assignment reaches AXI_B_RESP from IDLE. AXI_B_RESP stays graded through TL_PUT_ACK->AXI_B_RESP. Only u_spi_axi_lite_to_tlul sets the parameter (hw/sys/sep/rtl/sep_ot_spi_wrap.sv:115) and it is NOT waived."
Fsm state_q "3453034612"
Transition IDLE->AXI_B_RESP "0->6"

