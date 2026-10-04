// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//==================================================
// DTP VCS coverage waivers: points the bench reaches by no stimulus the DTP's
// interface contract allows, for the fact the ANNOTATION before each item
// states. They are DTP inputs, bench checkers, assertions, or points the
// cross-trigger network's register map and crossbar flow control rule out,
// none of which the formal unreachability analysis proves, so they are not
// in dtp_unreachable.el.
// Format Version: 2
// ExclMode: default
//
// Each CHECKSUM pair is the one `urg -dump full_exclusions` reports for the
// scope; build a changed entry from that dump, never by hand.
//==================================================

CHECKSUM: "662344282 920999053"
INSTANCE: dtp_uvm_top.u_dut
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle axi_smc_dbg_resp_i.b.id "logic axi_smc_dbg_resp_i.b.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle axi_smc_dbg_resp_i.r.id "logic axi_smc_dbg_resp_i.r.id[1:0]"
ANNOTATION: "CT_Ack_out is output-only: the cross-trigger network holds every CT_Ack_out pad input enable low and reads the pad inputs only into its lint sink, so no DTP logic observes them."
Toggle xtrig_ctp_ack_out_din_i "logic xtrig_ctp_ack_out_din_i[15:0]"

CHECKSUM: "282421448 501317893"
INSTANCE: dtp_uvm_top.u_dut.u_jtag_intf_unit
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle axi_smc_dbg_resp_i.b.id "logic axi_smc_dbg_resp_i.b.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle axi_smc_dbg_resp_i.r.id "logic axi_smc_dbg_resp_i.r.id[1:0]"

CHECKSUM: "4175005557 2956291194"
INSTANCE: dtp_uvm_top.u_dut.u_jtag_intf_unit.u_jtag_ptap
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle axi_smc_dbg_resp_i.b.id "logic axi_smc_dbg_resp_i.b.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle axi_smc_dbg_resp_i.r.id "logic axi_smc_dbg_resp_i.r.id[1:0]"

CHECKSUM: "1790303334 176340070"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network
ANNOTATION: "CT_Ack_out is output-only: the cross-trigger network holds every CT_Ack_out pad input enable low and reads the pad inputs only into its lint sink, so no DTP logic observes them."
Toggle ctp_ack_out_din_i "logic ctp_ack_out_din_i[15:0]"

CHECKSUM: "4028293086 1223236143"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[0].u_ctp.u_reg
ANNOTATION: "The crossbar demux forwards a W only after it presented the W's AW, and only once the previous write's B has left the block, by which time the block has taken that AW, so the block never holds W without AW."
Condition 13 "2222823787" "(axil_awvalid && axil_wvalid) 1 -1" (1 "01")

CHECKSUM: "4028293086 1223236143"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[1].u_ctp.u_reg
ANNOTATION: "The crossbar demux forwards a W only after it presented the W's AW, and only once the previous write's B has left the block, by which time the block has taken that AW, so the block never holds W without AW."
Condition 13 "2222823787" "(axil_awvalid && axil_wvalid) 1 -1" (1 "01")

CHECKSUM: "4028293086 1223236143"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[2].u_ctp.u_reg
ANNOTATION: "The crossbar demux forwards a W only after it presented the W's AW, and only once the previous write's B has left the block, by which time the block has taken that AW, so the block never holds W without AW."
Condition 13 "2222823787" "(axil_awvalid && axil_wvalid) 1 -1" (1 "01")

CHECKSUM: "4028293086 1223236143"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[3].u_ctp.u_reg
ANNOTATION: "The crossbar demux forwards a W only after it presented the W's AW, and only once the previous write's B has left the block, by which time the block has taken that AW, so the block never holds W without AW."
Condition 13 "2222823787" "(axil_awvalid && axil_wvalid) 1 -1" (1 "01")

CHECKSUM: "4028293086 1223236143"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[4].u_ctp.u_reg
ANNOTATION: "The crossbar demux forwards a W only after it presented the W's AW, and only once the previous write's B has left the block, by which time the block has taken that AW, so the block never holds W without AW."
Condition 13 "2222823787" "(axil_awvalid && axil_wvalid) 1 -1" (1 "01")

CHECKSUM: "4028293086 1223236143"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[5].u_ctp.u_reg
ANNOTATION: "The crossbar demux forwards a W only after it presented the W's AW, and only once the previous write's B has left the block, by which time the block has taken that AW, so the block never holds W without AW."
Condition 13 "2222823787" "(axil_awvalid && axil_wvalid) 1 -1" (1 "01")

CHECKSUM: "4028293086 1223236143"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[6].u_ctp.u_reg
ANNOTATION: "The crossbar demux forwards a W only after it presented the W's AW, and only once the previous write's B has left the block, by which time the block has taken that AW, so the block never holds W without AW."
Condition 13 "2222823787" "(axil_awvalid && axil_wvalid) 1 -1" (1 "01")

CHECKSUM: "4028293086 1223236143"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[7].u_ctp.u_reg
ANNOTATION: "The crossbar demux forwards a W only after it presented the W's AW, and only once the previous write's B has left the block, by which time the block has taken that AW, so the block never holds W without AW."
Condition 13 "2222823787" "(axil_awvalid && axil_wvalid) 1 -1" (1 "01")

CHECKSUM: "4028293086 1223236143"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[8].u_ctp.u_reg
ANNOTATION: "The crossbar demux forwards a W only after it presented the W's AW, and only once the previous write's B has left the block, by which time the block has taken that AW, so the block never holds W without AW."
Condition 13 "2222823787" "(axil_awvalid && axil_wvalid) 1 -1" (1 "01")

CHECKSUM: "4028293086 1223236143"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[9].u_ctp.u_reg
ANNOTATION: "The crossbar demux forwards a W only after it presented the W's AW, and only once the previous write's B has left the block, by which time the block has taken that AW, so the block never holds W without AW."
Condition 13 "2222823787" "(axil_awvalid && axil_wvalid) 1 -1" (1 "01")

CHECKSUM: "4028293086 1223236143"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[10].u_ctp.u_reg
ANNOTATION: "The crossbar demux forwards a W only after it presented the W's AW, and only once the previous write's B has left the block, by which time the block has taken that AW, so the block never holds W without AW."
Condition 13 "2222823787" "(axil_awvalid && axil_wvalid) 1 -1" (1 "01")

CHECKSUM: "4028293086 1223236143"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[11].u_ctp.u_reg
ANNOTATION: "The crossbar demux forwards a W only after it presented the W's AW, and only once the previous write's B has left the block, by which time the block has taken that AW, so the block never holds W without AW."
Condition 13 "2222823787" "(axil_awvalid && axil_wvalid) 1 -1" (1 "01")

CHECKSUM: "4028293086 1223236143"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[12].u_ctp.u_reg
ANNOTATION: "The crossbar demux forwards a W only after it presented the W's AW, and only once the previous write's B has left the block, by which time the block has taken that AW, so the block never holds W without AW."
Condition 13 "2222823787" "(axil_awvalid && axil_wvalid) 1 -1" (1 "01")

CHECKSUM: "4028293086 1223236143"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[13].u_ctp.u_reg
ANNOTATION: "The crossbar demux forwards a W only after it presented the W's AW, and only once the previous write's B has left the block, by which time the block has taken that AW, so the block never holds W without AW."
Condition 13 "2222823787" "(axil_awvalid && axil_wvalid) 1 -1" (1 "01")

CHECKSUM: "4028293086 1223236143"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[14].u_ctp.u_reg
ANNOTATION: "The crossbar demux forwards a W only after it presented the W's AW, and only once the previous write's B has left the block, by which time the block has taken that AW, so the block never holds W without AW."
Condition 13 "2222823787" "(axil_awvalid && axil_wvalid) 1 -1" (1 "01")

CHECKSUM: "4028293086 1223236143"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[15].u_ctp.u_reg
ANNOTATION: "The crossbar demux forwards a W only after it presented the W's AW, and only once the previous write's B has left the block, by which time the block has taken that AW, so the block never holds W without AW."
Condition 13 "2222823787" "(axil_awvalid && axil_wvalid) 1 -1" (1 "01")

CHECKSUM: "3626248416 1227050992"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.u_ctm.u_reg
ANNOTATION: "The crossbar demux forwards a W only after it presented the W's AW, and only once the previous write's B has left the block, by which time the block has taken that AW, so the block never holds W without AW."
Condition 13 "2222823787" "(axil_awvalid && axil_wvalid) 1 -1" (1 "01")

CHECKSUM: "3383160667 1364527541"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[0].u_ctp.u_core.u_handshake_ctrl
ANNOTATION: "The receiver enters WAIT_REQ_DEASSERT with CT_Req_in low, and this arm needs CT_Req_in high on the next cycle. A four-phase sender raises its next request only after it sees CT_Ack_out fall, which the receiver drives low in that same transition, so the request stays low for longer."
Branch 1 "2756334046" "receiver_state_q" (5) "receiver_state_q RECEIVER_WAIT_REQ_DEASSERT ,-,-,0"

CHECKSUM: "3383160667 1364527541"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[1].u_ctp.u_core.u_handshake_ctrl
ANNOTATION: "The receiver enters WAIT_REQ_DEASSERT with CT_Req_in low, and this arm needs CT_Req_in high on the next cycle. A four-phase sender raises its next request only after it sees CT_Ack_out fall, which the receiver drives low in that same transition, so the request stays low for longer."
Branch 1 "2756334046" "receiver_state_q" (5) "receiver_state_q RECEIVER_WAIT_REQ_DEASSERT ,-,-,0"

CHECKSUM: "3383160667 1364527541"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[2].u_ctp.u_core.u_handshake_ctrl
ANNOTATION: "The receiver enters WAIT_REQ_DEASSERT with CT_Req_in low, and this arm needs CT_Req_in high on the next cycle. A four-phase sender raises its next request only after it sees CT_Ack_out fall, which the receiver drives low in that same transition, so the request stays low for longer."
Branch 1 "2756334046" "receiver_state_q" (5) "receiver_state_q RECEIVER_WAIT_REQ_DEASSERT ,-,-,0"

CHECKSUM: "3383160667 1364527541"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[3].u_ctp.u_core.u_handshake_ctrl
ANNOTATION: "The receiver enters WAIT_REQ_DEASSERT with CT_Req_in low, and this arm needs CT_Req_in high on the next cycle. A four-phase sender raises its next request only after it sees CT_Ack_out fall, which the receiver drives low in that same transition, so the request stays low for longer."
Branch 1 "2756334046" "receiver_state_q" (5) "receiver_state_q RECEIVER_WAIT_REQ_DEASSERT ,-,-,0"

CHECKSUM: "3383160667 1364527541"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[4].u_ctp.u_core.u_handshake_ctrl
ANNOTATION: "The receiver enters WAIT_REQ_DEASSERT with CT_Req_in low, and this arm needs CT_Req_in high on the next cycle. A four-phase sender raises its next request only after it sees CT_Ack_out fall, which the receiver drives low in that same transition, so the request stays low for longer."
Branch 1 "2756334046" "receiver_state_q" (5) "receiver_state_q RECEIVER_WAIT_REQ_DEASSERT ,-,-,0"

CHECKSUM: "3383160667 1364527541"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[5].u_ctp.u_core.u_handshake_ctrl
ANNOTATION: "The receiver enters WAIT_REQ_DEASSERT with CT_Req_in low, and this arm needs CT_Req_in high on the next cycle. A four-phase sender raises its next request only after it sees CT_Ack_out fall, which the receiver drives low in that same transition, so the request stays low for longer."
Branch 1 "2756334046" "receiver_state_q" (5) "receiver_state_q RECEIVER_WAIT_REQ_DEASSERT ,-,-,0"

CHECKSUM: "3383160667 1364527541"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[6].u_ctp.u_core.u_handshake_ctrl
ANNOTATION: "The receiver enters WAIT_REQ_DEASSERT with CT_Req_in low, and this arm needs CT_Req_in high on the next cycle. A four-phase sender raises its next request only after it sees CT_Ack_out fall, which the receiver drives low in that same transition, so the request stays low for longer."
Branch 1 "2756334046" "receiver_state_q" (5) "receiver_state_q RECEIVER_WAIT_REQ_DEASSERT ,-,-,0"

CHECKSUM: "3383160667 1364527541"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[7].u_ctp.u_core.u_handshake_ctrl
ANNOTATION: "The receiver enters WAIT_REQ_DEASSERT with CT_Req_in low, and this arm needs CT_Req_in high on the next cycle. A four-phase sender raises its next request only after it sees CT_Ack_out fall, which the receiver drives low in that same transition, so the request stays low for longer."
Branch 1 "2756334046" "receiver_state_q" (5) "receiver_state_q RECEIVER_WAIT_REQ_DEASSERT ,-,-,0"

CHECKSUM: "3383160667 1364527541"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[8].u_ctp.u_core.u_handshake_ctrl
ANNOTATION: "The receiver enters WAIT_REQ_DEASSERT with CT_Req_in low, and this arm needs CT_Req_in high on the next cycle. A four-phase sender raises its next request only after it sees CT_Ack_out fall, which the receiver drives low in that same transition, so the request stays low for longer."
Branch 1 "2756334046" "receiver_state_q" (5) "receiver_state_q RECEIVER_WAIT_REQ_DEASSERT ,-,-,0"

CHECKSUM: "3383160667 1364527541"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[9].u_ctp.u_core.u_handshake_ctrl
ANNOTATION: "The receiver enters WAIT_REQ_DEASSERT with CT_Req_in low, and this arm needs CT_Req_in high on the next cycle. A four-phase sender raises its next request only after it sees CT_Ack_out fall, which the receiver drives low in that same transition, so the request stays low for longer."
Branch 1 "2756334046" "receiver_state_q" (5) "receiver_state_q RECEIVER_WAIT_REQ_DEASSERT ,-,-,0"

CHECKSUM: "3383160667 1364527541"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[10].u_ctp.u_core.u_handshake_ctrl
ANNOTATION: "The receiver enters WAIT_REQ_DEASSERT with CT_Req_in low, and this arm needs CT_Req_in high on the next cycle. A four-phase sender raises its next request only after it sees CT_Ack_out fall, which the receiver drives low in that same transition, so the request stays low for longer."
Branch 1 "2756334046" "receiver_state_q" (5) "receiver_state_q RECEIVER_WAIT_REQ_DEASSERT ,-,-,0"

CHECKSUM: "3383160667 1364527541"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[11].u_ctp.u_core.u_handshake_ctrl
ANNOTATION: "The receiver enters WAIT_REQ_DEASSERT with CT_Req_in low, and this arm needs CT_Req_in high on the next cycle. A four-phase sender raises its next request only after it sees CT_Ack_out fall, which the receiver drives low in that same transition, so the request stays low for longer."
Branch 1 "2756334046" "receiver_state_q" (5) "receiver_state_q RECEIVER_WAIT_REQ_DEASSERT ,-,-,0"

CHECKSUM: "3383160667 1364527541"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[12].u_ctp.u_core.u_handshake_ctrl
ANNOTATION: "The receiver enters WAIT_REQ_DEASSERT with CT_Req_in low, and this arm needs CT_Req_in high on the next cycle. A four-phase sender raises its next request only after it sees CT_Ack_out fall, which the receiver drives low in that same transition, so the request stays low for longer."
Branch 1 "2756334046" "receiver_state_q" (5) "receiver_state_q RECEIVER_WAIT_REQ_DEASSERT ,-,-,0"

CHECKSUM: "3383160667 1364527541"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[13].u_ctp.u_core.u_handshake_ctrl
ANNOTATION: "The receiver enters WAIT_REQ_DEASSERT with CT_Req_in low, and this arm needs CT_Req_in high on the next cycle. A four-phase sender raises its next request only after it sees CT_Ack_out fall, which the receiver drives low in that same transition, so the request stays low for longer."
Branch 1 "2756334046" "receiver_state_q" (5) "receiver_state_q RECEIVER_WAIT_REQ_DEASSERT ,-,-,0"

CHECKSUM: "3383160667 1364527541"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[14].u_ctp.u_core.u_handshake_ctrl
ANNOTATION: "The receiver enters WAIT_REQ_DEASSERT with CT_Req_in low, and this arm needs CT_Req_in high on the next cycle. A four-phase sender raises its next request only after it sees CT_Ack_out fall, which the receiver drives low in that same transition, so the request stays low for longer."
Branch 1 "2756334046" "receiver_state_q" (5) "receiver_state_q RECEIVER_WAIT_REQ_DEASSERT ,-,-,0"

CHECKSUM: "3383160667 1364527541"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.gen_ext_ctp[15].u_ctp.u_core.u_handshake_ctrl
ANNOTATION: "The receiver enters WAIT_REQ_DEASSERT with CT_Req_in low, and this arm needs CT_Req_in high on the next cycle. A four-phase sender raises its next request only after it sees CT_Ack_out fall, which the receiver drives low in that same transition, so the request stays low for longer."
Branch 1 "2756334046" "receiver_state_q" (5) "receiver_state_q RECEIVER_WAIT_REQ_DEASSERT ,-,-,0"

CHECKSUM: "4056390746 1854703041"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.u_axil_xbar.gen_slv_port_demux[0].i_axi_lite_demux.gen_demux.i_r_spill_reg.spill_register_flushable_i
ANNOTATION: "No crossbar subordinate returns R data with bit 26 or 30 set: a CT_SRC select holds 26 bits, every CTP register fewer, and the decode-error subordinate answers 0xBADCAB1E."
Toggle 0to1 gen_spill_reg.a_data_q.data [26] "logic gen_spill_reg.a_data_q.data[31:0]"
ANNOTATION: "No crossbar subordinate returns R data with bit 26 or 30 set: a CT_SRC select holds 26 bits, every CTP register fewer, and the decode-error subordinate answers 0xBADCAB1E."
Toggle 1to0 gen_spill_reg.a_data_q.data [26] "logic gen_spill_reg.a_data_q.data[31:0]"
ANNOTATION: "No crossbar subordinate returns R data with bit 26 or 30 set: a CT_SRC select holds 26 bits, every CTP register fewer, and the decode-error subordinate answers 0xBADCAB1E."
Toggle 0to1 gen_spill_reg.a_data_q.data [30] "logic gen_spill_reg.a_data_q.data[31:0]"
ANNOTATION: "No crossbar subordinate returns R data with bit 26 or 30 set: a CT_SRC select holds 26 bits, every CTP register fewer, and the decode-error subordinate answers 0xBADCAB1E."
Toggle 1to0 gen_spill_reg.a_data_q.data [30] "logic gen_spill_reg.a_data_q.data[31:0]"
ANNOTATION: "No crossbar subordinate returns R data with bit 26 or 30 set: a CT_SRC select holds 26 bits, every CTP register fewer, and the decode-error subordinate answers 0xBADCAB1E."
Toggle 0to1 gen_spill_reg.b_data_q.data [26] "logic gen_spill_reg.b_data_q.data[31:0]"
ANNOTATION: "No crossbar subordinate returns R data with bit 26 or 30 set: a CT_SRC select holds 26 bits, every CTP register fewer, and the decode-error subordinate answers 0xBADCAB1E."
Toggle 1to0 gen_spill_reg.b_data_q.data [26] "logic gen_spill_reg.b_data_q.data[31:0]"
ANNOTATION: "No crossbar subordinate returns R data with bit 26 or 30 set: a CT_SRC select holds 26 bits, every CTP register fewer, and the decode-error subordinate answers 0xBADCAB1E."
Toggle 0to1 gen_spill_reg.b_data_q.data [30] "logic gen_spill_reg.b_data_q.data[31:0]"
ANNOTATION: "No crossbar subordinate returns R data with bit 26 or 30 set: a CT_SRC select holds 26 bits, every CTP register fewer, and the decode-error subordinate answers 0xBADCAB1E."
Toggle 1to0 gen_spill_reg.b_data_q.data [30] "logic gen_spill_reg.b_data_q.data[31:0]"

// An Assert entry applies only while its instance checksum matches the design,
// so a change to the checker drops these with a URG warning.
CHECKSUM: "3246710229"
INSTANCE: dtp_uvm_top.u_m_axi_sva
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request as an INCR burst, so the FIXED-burst length rule has no antecedent."
Assert gen_axi4_rules.gen_OCAH_AXI_AW_LEN_FIXED_MAX16.OCAH_AXI_AW_LEN_FIXED_MAX16 "assertion"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request as an INCR burst, so the FIXED-burst length rule has no antecedent."
Assert gen_axi4_rules.gen_OCAH_AXI_AR_LEN_FIXED_MAX16.OCAH_AXI_AR_LEN_FIXED_MAX16 "assertion"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request as an INCR burst, so the WRAP-burst length rule has no antecedent."
Assert gen_axi4_rules.gen_OCAH_AXI_AW_LEN_WRAP_LEGAL.OCAH_AXI_AW_LEN_WRAP_LEGAL "assertion"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request as an INCR burst, so the WRAP-burst length rule has no antecedent."
Assert gen_axi4_rules.gen_OCAH_AXI_AR_LEN_WRAP_LEGAL.OCAH_AXI_AR_LEN_WRAP_LEGAL "assertion"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request as an INCR burst, so the WRAP-burst alignment rule has no antecedent."
Assert gen_axi4_rules.gen_OCAH_AXI_AW_WRAP_ALIGNED.OCAH_AXI_AW_WRAP_ALIGNED "assertion"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request as an INCR burst, so the WRAP-burst alignment rule has no antecedent."
Assert gen_axi4_rules.gen_OCAH_AXI_AR_WRAP_ALIGNED.OCAH_AXI_AR_WRAP_ALIGNED "assertion"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request as one beat, with AWLEN 0, so the multi-beat write cover cannot fire."
Assert gen_axi4_rules.OCAH_AXI_C_AW_MULTI_BEAT "cover property"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request as one beat, with ARLEN 0, so the multi-beat read cover cannot fire."
Assert gen_axi4_rules.OCAH_AXI_C_AR_MULTI_BEAT "cover property"

CHECKSUM: "26180546"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.u_axil_xbar.gen_slv_port_demux[0].i_axi_lite_demux.gen_demux.i_ar_spill_reg.spill_register_flushable_i
ANNOTATION: "The demux spill registers come from the spill_register wrapper, which ties flush_i low, so the flush rule has no antecedent."
Assert gen_spill_reg.flush_valid "assertion"

CHECKSUM: "26180546"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.u_axil_xbar.gen_slv_port_demux[0].i_axi_lite_demux.gen_demux.i_aw_spill_reg.spill_register_flushable_i
ANNOTATION: "The demux spill registers come from the spill_register wrapper, which ties flush_i low, so the flush rule has no antecedent."
Assert gen_spill_reg.flush_valid "assertion"

CHECKSUM: "26180546"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.u_axil_xbar.gen_slv_port_demux[0].i_axi_lite_demux.gen_demux.i_b_spill_reg.spill_register_flushable_i
ANNOTATION: "The demux spill registers come from the spill_register wrapper, which ties flush_i low, so the flush rule has no antecedent."
Assert gen_spill_reg.flush_valid "assertion"

CHECKSUM: "26180546"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.u_axil_xbar.gen_slv_port_demux[0].i_axi_lite_demux.gen_demux.i_r_spill_reg.spill_register_flushable_i
ANNOTATION: "The demux spill registers come from the spill_register wrapper, which ties flush_i low, so the flush rule has no antecedent."
Assert gen_spill_reg.flush_valid "assertion"

CHECKSUM: "26180546"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.u_axil_xbar.gen_slv_port_demux[0].i_axi_lite_demux.gen_demux.i_w_spill_reg.spill_register_flushable_i
ANNOTATION: "The demux spill registers come from the spill_register wrapper, which ties flush_i low, so the flush rule has no antecedent."
Assert gen_spill_reg.flush_valid "assertion"

CHECKSUM: "735799789"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.u_axil_xbar.gen_slv_port_demux[0].i_axi_err_slv.i_b_fifo
ANNOTATION: "The demux presents a W to its decode-error subordinate only while its own one-entry B FIFO is empty, and that FIFO stays full until the write's B, so the subordinate's B FIFO never holds two writes."
Assert full_write "assertion"

CHECKSUM: "1332856517"
INSTANCE: dtp_uvm_top.u_dut.u_cross_trigger_network.u_axil_xbar.gen_slv_port_demux[0].i_axi_lite_demux
ANNOTATION: "The demux presents an AR only while its one-entry R FIFO is empty, and a register block or the decode-error subordinate refuses an AR only while a read it took is owed its R, which keeps that FIFO full, so no presented AR is refused."
Assert gen_demux.ar_select_stable "assertion"
