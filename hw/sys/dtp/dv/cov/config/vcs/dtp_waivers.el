// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//==================================================
// DTP VCS coverage waivers: points the bench reaches by no stimulus the DTP's
// interface contract allows, for the fact the ANNOTATION before each item
// states. They are DTP inputs, JTAG2AXI bridge points that only a response
// outside the AXI protocol reaches, bench checkers, assertions, or points the
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

CHECKSUM: "817838655 1854703041"
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

CHECKSUM: "3654346658 1710099946"
INSTANCE: dtp_uvm_top.u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi
ANNOTATION: "The JTAG2AXI bridge issues every write as a normal access, with AWLOCK 0, and an AXI subordinate returns EXOKAY only to an exclusive access, so no B response reaches the EXOKAY fall-through."
Condition 28 "4088657890" "((src_resp.b.resp == 2'b11) ? CaptureStatusDecerr : CaptureStatusSlverr) 1 -1" (1 "0")
ANNOTATION: "The JTAG2AXI bridge issues every write as a normal access, with AWLOCK 0, and an AXI subordinate returns EXOKAY only to an exclusive access, so no B response reaches the EXOKAY fall-through."
Condition 29 "3394942711" "(src_resp.b.resp == 2'b11) 1 -1" (1 "0")
ANNOTATION: "The JTAG2AXI bridge issues every read as a normal access, with ARLOCK 0, and an AXI subordinate returns EXOKAY only to an exclusive access, so no R response reaches the EXOKAY fall-through."
Condition 37 "291669865" "((src_resp.r.resp == 2'b11) ? CaptureStatusDecerr : CaptureStatusSlverr) 1 -1" (1 "0")
ANNOTATION: "The JTAG2AXI bridge issues every read as a normal access, with ARLOCK 0, and an AXI subordinate returns EXOKAY only to an exclusive access, so no R response reaches the EXOKAY fall-through."
Condition 38 "3057482173" "(src_resp.r.resp == 2'b11) 1 -1" (1 "0")

CHECKSUM: "3654346658 1710099946"
INSTANCE: dtp_uvm_top.u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi
ANNOTATION: "The JTAG2AXI bridge issues every write as a normal access, with AWLOCK 0, and an AXI subordinate returns EXOKAY only to an exclusive access, so no B response reaches the EXOKAY fall-through."
Condition 28 "4088657890" "((src_resp.b.resp == 2'b11) ? CaptureStatusDecerr : CaptureStatusSlverr) 1 -1" (1 "0")
ANNOTATION: "The JTAG2AXI bridge issues every write as a normal access, with AWLOCK 0, and an AXI subordinate returns EXOKAY only to an exclusive access, so no B response reaches the EXOKAY fall-through."
Condition 29 "3394942711" "(src_resp.b.resp == 2'b11) 1 -1" (1 "0")
ANNOTATION: "The JTAG2AXI bridge issues every read as a normal access, with ARLOCK 0, and an AXI subordinate returns EXOKAY only to an exclusive access, so no R response reaches the EXOKAY fall-through."
Condition 37 "291669865" "((src_resp.r.resp == 2'b11) ? CaptureStatusDecerr : CaptureStatusSlverr) 1 -1" (1 "0")
ANNOTATION: "The JTAG2AXI bridge issues every read as a normal access, with ARLOCK 0, and an AXI subordinate returns EXOKAY only to an exclusive access, so no R response reaches the EXOKAY fall-through."
Condition 38 "3057482173" "(src_resp.r.resp == 2'b11) 1 -1" (1 "0")

CHECKSUM: "3654346658 3828155932"
INSTANCE: dtp_uvm_top.u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi
ANNOTATION: "The JTAG2AXI bridge issues every write as a normal access, with AWLOCK 0, and an AXI subordinate returns EXOKAY only to an exclusive access, so no B response reaches the EXOKAY fall-through."
Condition 28 "4088657890" "((src_resp.b.resp == 2'b11) ? CaptureStatusDecerr : CaptureStatusSlverr) 1 -1" (1 "0")
ANNOTATION: "The JTAG2AXI bridge issues every write as a normal access, with AWLOCK 0, and an AXI subordinate returns EXOKAY only to an exclusive access, so no B response reaches the EXOKAY fall-through."
Condition 29 "3394942711" "(src_resp.b.resp == 2'b11) 1 -1" (1 "0")
ANNOTATION: "The JTAG2AXI bridge issues every read as a normal access, with ARLOCK 0, and an AXI subordinate returns EXOKAY only to an exclusive access, so no R response reaches the EXOKAY fall-through."
Condition 37 "291669865" "((src_resp.r.resp == 2'b11) ? CaptureStatusDecerr : CaptureStatusSlverr) 1 -1" (1 "0")
ANNOTATION: "The JTAG2AXI bridge issues every read as a normal access, with ARLOCK 0, and an AXI subordinate returns EXOKAY only to an exclusive access, so no R response reaches the EXOKAY fall-through."
Condition 38 "3057482173" "(src_resp.r.resp == 2'b11) 1 -1" (1 "0")

CHECKSUM: "3654346658 2238901397"
INSTANCE: dtp_uvm_top.u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi
ANNOTATION: "The JTAG2AXI bridge issues every write as a normal access, with AWLOCK 0, and an AXI subordinate returns EXOKAY only to an exclusive access, so no B response reaches the EXOKAY fall-through."
Branch 16 "1709732032" "axi_state_q_tclk" (16) "axi_state_q_tclk AXI_WAIT_BRESP ,-,-,-,-,-,-,-,-,-,-,1,0,0,0,-,-,-,-,-,-,-,-"
ANNOTATION: "The JTAG2AXI bridge issues every read as a normal access, with ARLOCK 0, and an AXI subordinate returns EXOKAY only to an exclusive access, so no R response reaches the EXOKAY fall-through."
Branch 16 "1709732032" "axi_state_q_tclk" (27) "axi_state_q_tclk AXI_WAIT_RDATA ,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,1,-,0,0,0,-"

CHECKSUM: "3654346658 1198256725"
INSTANCE: dtp_uvm_top.u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi
ANNOTATION: "The JTAG2AXI bridge issues every write as a normal access, with AWLOCK 0, and an AXI subordinate returns EXOKAY only to an exclusive access, so no B response reaches the EXOKAY fall-through."
Branch 16 "1709732032" "axi_state_q_tclk" (16) "axi_state_q_tclk AXI_WAIT_BRESP ,-,-,-,-,-,-,-,-,-,-,1,0,0,0,-,-,-,-,-,-,-,-"
ANNOTATION: "The JTAG2AXI bridge issues every read as a normal access, with ARLOCK 0, and an AXI subordinate returns EXOKAY only to an exclusive access, so no R response reaches the EXOKAY fall-through."
Branch 16 "1709732032" "axi_state_q_tclk" (27) "axi_state_q_tclk AXI_WAIT_RDATA ,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,1,-,0,0,0,-"

CHECKSUM: "3654346658 884625925"
INSTANCE: dtp_uvm_top.u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi
ANNOTATION: "The JTAG2AXI bridge issues every write as a normal access, with AWLOCK 0, and an AXI subordinate returns EXOKAY only to an exclusive access, so no B response reaches the EXOKAY fall-through."
Branch 16 "1709732032" "axi_state_q_tclk" (16) "axi_state_q_tclk AXI_WAIT_BRESP ,-,-,-,-,-,-,-,-,-,-,1,0,0,0,-,-,-,-,-,-,-,-"
ANNOTATION: "The JTAG2AXI bridge issues every read as a normal access, with ARLOCK 0, and an AXI subordinate returns EXOKAY only to an exclusive access, so no R response reaches the EXOKAY fall-through."
Branch 16 "1709732032" "axi_state_q_tclk" (27) "axi_state_q_tclk AXI_WAIT_RDATA ,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,1,-,0,0,0,-"

CHECKSUM: "3654346658 1009589673"
INSTANCE: dtp_uvm_top.u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle bid_i "logic bid_i[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle rid_i "logic rid_i[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle src_resp.r.id "logic src_resp.r.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle src_resp.b.id "logic src_resp.b.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle dst_resp.r.id "logic dst_resp.r.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle dst_resp.b.id "logic dst_resp.b.id[1:0]"

CHECKSUM: "921158028 2837277208"
INSTANCE: dtp_uvm_top.u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_axi_cdc
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle src_resp_o.r.id "logic src_resp_o.r.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle src_resp_o.b.id "logic src_resp_o.b.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle dst_resp_i.r.id "logic dst_resp_i.r.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle dst_resp_i.b.id "logic dst_resp_i.b.id[1:0]"

CHECKSUM: "2346334635 3239658498"
INSTANCE: dtp_uvm_top.u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_axi_cdc.i_cdc_fifo_gray_clearable_b
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle src_data_i.id "logic src_data_i.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle dst_data_o.id "logic dst_data_o.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle async_data[0].id "logic async_data[0].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle async_data[1].id "logic async_data[1].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle async_data[2].id "logic async_data[2].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle async_data[3].id "logic async_data[3].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle async_data[4].id "logic async_data[4].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle async_data[5].id "logic async_data[5].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle async_data[6].id "logic async_data[6].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle async_data[7].id "logic async_data[7].id[1:0]"

CHECKSUM: "2119109210 1389616029"
INSTANCE: dtp_uvm_top.u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_axi_cdc.i_cdc_fifo_gray_clearable_b.i_src
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle src_data_i.id "logic src_data_i.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle async_data_o[0].id "logic async_data_o[0].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle async_data_o[1].id "logic async_data_o[1].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle async_data_o[2].id "logic async_data_o[2].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle async_data_o[3].id "logic async_data_o[3].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle async_data_o[4].id "logic async_data_o[4].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle async_data_o[5].id "logic async_data_o[5].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle async_data_o[6].id "logic async_data_o[6].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle async_data_o[7].id "logic async_data_o[7].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle data_q[0].id "logic data_q[0].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle data_q[1].id "logic data_q[1].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle data_q[2].id "logic data_q[2].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle data_q[3].id "logic data_q[3].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle data_q[4].id "logic data_q[4].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle data_q[5].id "logic data_q[5].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle data_q[6].id "logic data_q[6].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle data_q[7].id "logic data_q[7].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle data_d[0].id "logic data_d[0].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle data_d[1].id "logic data_d[1].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle data_d[2].id "logic data_d[2].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle data_d[3].id "logic data_d[3].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle data_d[4].id "logic data_d[4].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle data_d[5].id "logic data_d[5].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle data_d[6].id "logic data_d[6].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle data_d[7].id "logic data_d[7].id[1:0]"

CHECKSUM: "813668340 3758863278"
INSTANCE: dtp_uvm_top.u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_axi_cdc.i_cdc_fifo_gray_clearable_b.i_dst
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle dst_data_o.id "logic dst_data_o.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle async_data_i[0].id "logic async_data_i[0].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle async_data_i[1].id "logic async_data_i[1].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle async_data_i[2].id "logic async_data_i[2].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle async_data_i[3].id "logic async_data_i[3].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle async_data_i[4].id "logic async_data_i[4].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle async_data_i[5].id "logic async_data_i[5].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle async_data_i[6].id "logic async_data_i[6].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle async_data_i[7].id "logic async_data_i[7].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle dst_data.id "logic dst_data.id[1:0]"

CHECKSUM: "817838655 3201749725"
INSTANCE: dtp_uvm_top.u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_axi_cdc.i_cdc_fifo_gray_clearable_b.i_dst.i_spill_register
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle data_i.id "logic data_i.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle data_o.id "logic data_o.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle gen_spill_reg.a_data_q.id "logic gen_spill_reg.a_data_q.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle gen_spill_reg.b_data_q.id "logic gen_spill_reg.b_data_q.id[1:0]"

CHECKSUM: "2346334635 3206091600"
INSTANCE: dtp_uvm_top.u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_axi_cdc.i_cdc_fifo_gray_clearable_r
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle src_data_i.id "logic src_data_i.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle dst_data_o.id "logic dst_data_o.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle async_data[0].id "logic async_data[0].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle async_data[1].id "logic async_data[1].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle async_data[2].id "logic async_data[2].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle async_data[3].id "logic async_data[3].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle async_data[4].id "logic async_data[4].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle async_data[5].id "logic async_data[5].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle async_data[6].id "logic async_data[6].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle async_data[7].id "logic async_data[7].id[1:0]"

CHECKSUM: "2119109210 4098467387"
INSTANCE: dtp_uvm_top.u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_axi_cdc.i_cdc_fifo_gray_clearable_r.i_src
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle src_data_i.id "logic src_data_i.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle async_data_o[0].id "logic async_data_o[0].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle async_data_o[1].id "logic async_data_o[1].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle async_data_o[2].id "logic async_data_o[2].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle async_data_o[3].id "logic async_data_o[3].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle async_data_o[4].id "logic async_data_o[4].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle async_data_o[5].id "logic async_data_o[5].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle async_data_o[6].id "logic async_data_o[6].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle async_data_o[7].id "logic async_data_o[7].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle data_q[0].id "logic data_q[0].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle data_q[1].id "logic data_q[1].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle data_q[2].id "logic data_q[2].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle data_q[3].id "logic data_q[3].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle data_q[4].id "logic data_q[4].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle data_q[5].id "logic data_q[5].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle data_q[6].id "logic data_q[6].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle data_q[7].id "logic data_q[7].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle data_d[0].id "logic data_d[0].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle data_d[1].id "logic data_d[1].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle data_d[2].id "logic data_d[2].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle data_d[3].id "logic data_d[3].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle data_d[4].id "logic data_d[4].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle data_d[5].id "logic data_d[5].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle data_d[6].id "logic data_d[6].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle data_d[7].id "logic data_d[7].id[1:0]"

CHECKSUM: "813668340 1252119231"
INSTANCE: dtp_uvm_top.u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_axi_cdc.i_cdc_fifo_gray_clearable_r.i_dst
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle dst_data_o.id "logic dst_data_o.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle async_data_i[0].id "logic async_data_i[0].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle async_data_i[1].id "logic async_data_i[1].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle async_data_i[2].id "logic async_data_i[2].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle async_data_i[3].id "logic async_data_i[3].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle async_data_i[4].id "logic async_data_i[4].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle async_data_i[5].id "logic async_data_i[5].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle async_data_i[6].id "logic async_data_i[6].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle async_data_i[7].id "logic async_data_i[7].id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle dst_data.id "logic dst_data.id[1:0]"

CHECKSUM: "817838655 3644409070"
INSTANCE: dtp_uvm_top.u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_axi_cdc.i_cdc_fifo_gray_clearable_r.i_dst.i_spill_register
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle data_i.id "logic data_i.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle data_o.id "logic data_o.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle gen_spill_reg.a_data_q.id "logic gen_spill_reg.a_data_q.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle gen_spill_reg.b_data_q.id "logic gen_spill_reg.b_data_q.id[1:0]"

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
