// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//==================================================
// SEP VCS coverage exclusions -- sep_crypto structural ties (ABR wrapper, KV shim,
// OTBN wrapper, TRNG/DRBG, KM mailbox SEP regblock, sep_crypto top).
// Format Version: 2
// ExclMode: default
//
// Scope: the cocotb VCS elaboration of sep_uvm_top, target `default`, applied on top
// of the other cov/config/vcs exclusion files and sep_cov_scope.hier. TOGGLE only, INSTANCE-scoped.
// Only TT-owned instances carry entries; no entry is written inside a vendor module.
//
// Honesty rule 1: every block waives a bit that a constant, a parameter or a
// width cast in SEP RTL fixes for every legal input. A bit that a test, a fault,
// an error response, an illegal CSR value, an integrator, JTAG or a second master
// can move is a test gap and is NOT in this file.
// Honesty rule 2: this file was applied with urg -excl_strict, which refuses to
// exclude any object some leaf already covered. A strict-mode refusal means the
// reason is wrong; remove the entry, do not weaken the check.
// Every ANNOTATION cites the tie as file:line.
//==================================================

CHECKSUM: "3163693320 1642766038"
ANNOTATION: "SEP-KVSHIM-HWIF-DEFAULT: sep_abr_kv_shim drives hwif_o to '{default: 0} and assigns only KEY[*].data.next/we, KEY_CTRL.key_valid.hwset and IRQ_STATUS.key_valid.hwset; KEY[*].data.hwclr and IRQ_STATUS.key_valid.next are never assigned and hold 0. The wrapper wires hwif_o straight into abr_wrapper_key_reg hwif_in. hw/sys/sep/rtl/sep_abr_kv_shim.sv:145-155, hw/sys/sep/rtl/sep_crypto_abr_wrapper.sv:242,265-272"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_abr_wrapper_s3c_scan.u_sep_abr_kv_shim
Toggle hwif_o.MLKEM_SHARED_KEY.KEY[0].data.hwclr "logic hwif_o.MLKEM_SHARED_KEY.KEY[0].data.hwclr"
Toggle hwif_o.MLKEM_SHARED_KEY.KEY[1].data.hwclr "logic hwif_o.MLKEM_SHARED_KEY.KEY[1].data.hwclr"
Toggle hwif_o.MLKEM_SHARED_KEY.KEY[2].data.hwclr "logic hwif_o.MLKEM_SHARED_KEY.KEY[2].data.hwclr"
Toggle hwif_o.MLKEM_SHARED_KEY.KEY[3].data.hwclr "logic hwif_o.MLKEM_SHARED_KEY.KEY[3].data.hwclr"
Toggle hwif_o.MLKEM_SHARED_KEY.KEY[4].data.hwclr "logic hwif_o.MLKEM_SHARED_KEY.KEY[4].data.hwclr"
Toggle hwif_o.MLKEM_SHARED_KEY.KEY[5].data.hwclr "logic hwif_o.MLKEM_SHARED_KEY.KEY[5].data.hwclr"
Toggle hwif_o.MLKEM_SHARED_KEY.KEY[6].data.hwclr "logic hwif_o.MLKEM_SHARED_KEY.KEY[6].data.hwclr"
Toggle hwif_o.MLKEM_SHARED_KEY.KEY[7].data.hwclr "logic hwif_o.MLKEM_SHARED_KEY.KEY[7].data.hwclr"
Toggle hwif_o.MLKEM_SHARED_KEY.IRQ_STATUS.key_valid.next "logic hwif_o.MLKEM_SHARED_KEY.IRQ_STATUS.key_valid.next"

CHECKSUM: "3163693320 1642766038"
ANNOTATION: "SEP-KVSHIM-WRRESP-TIE: kv_wr_resp is the constant '{error: 1'b0}. hw/sys/sep/rtl/sep_abr_kv_shim.sv:158, hw/sys/sep/rtl/sep_crypto_abr_wrapper.sv:271"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_abr_wrapper_s3c_scan.u_sep_abr_kv_shim
Toggle kv_wr_resp_o.error "logic kv_wr_resp_o.error"

CHECKSUM: "3163693320 1642766038"
ANNOTATION: "SEP-KV-OFFSET-WIDTH: abr_ctrl instantiates the ML-DSA seed and ML-KEM msg kv_read_client and the shared-key kv_write_client with DATA_WIDTH=8*32, so their offset counter is $clog2(8)=3 bits and is zero-extended to KV_ENTRY_SIZE_W=4; offset bit 3 holds 0 (the ML-KEM seed lane is 16 dwords and is not listed). vendor/chipsalliance/adams-bridge/upstream/src/abr_top/rtl/abr_ctrl.sv:320-321,378-379,406-407, abr_ctrl_pkg.sv:35,58,67; vendor/chipsalliance/caliptra-rtl/upstream/src/keyvault/rtl/kv_read_client.sv:26,104, kv_write_client.sv:23,101, kv_defines_pkg.sv:20,25"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_abr_wrapper_s3c_scan.u_sep_abr_kv_shim
Toggle kv_read_i[0].read_offset [3] "logic kv_read_i[0].read_offset[3:0]"
Toggle kv_read_i[2].read_offset [3] "logic kv_read_i[2].read_offset[3:0]"
Toggle kv_write_i.write_offset [3] "logic kv_write_i.write_offset[3:0]"

CHECKSUM: "692244178 3042302331"
ANNOTATION: "SEP-KVSHIM-HWIF-DEFAULT: sep_abr_kv_shim drives hwif_o to '{default: 0} and assigns only KEY[*].data.next/we, KEY_CTRL.key_valid.hwset and IRQ_STATUS.key_valid.hwset; KEY[*].data.hwclr and IRQ_STATUS.key_valid.next are never assigned and hold 0. The wrapper wires hwif_o straight into abr_wrapper_key_reg hwif_in. hw/sys/sep/rtl/sep_abr_kv_shim.sv:145-155, hw/sys/sep/rtl/sep_crypto_abr_wrapper.sv:242,265-272"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_abr_wrapper_s3c_scan
Toggle abr_key_hwif_in.MLKEM_SHARED_KEY.KEY[0].data.hwclr "logic abr_key_hwif_in.MLKEM_SHARED_KEY.KEY[0].data.hwclr"
Toggle abr_key_hwif_in.MLKEM_SHARED_KEY.KEY[1].data.hwclr "logic abr_key_hwif_in.MLKEM_SHARED_KEY.KEY[1].data.hwclr"
Toggle abr_key_hwif_in.MLKEM_SHARED_KEY.KEY[2].data.hwclr "logic abr_key_hwif_in.MLKEM_SHARED_KEY.KEY[2].data.hwclr"
Toggle abr_key_hwif_in.MLKEM_SHARED_KEY.KEY[3].data.hwclr "logic abr_key_hwif_in.MLKEM_SHARED_KEY.KEY[3].data.hwclr"
Toggle abr_key_hwif_in.MLKEM_SHARED_KEY.KEY[4].data.hwclr "logic abr_key_hwif_in.MLKEM_SHARED_KEY.KEY[4].data.hwclr"
Toggle abr_key_hwif_in.MLKEM_SHARED_KEY.KEY[5].data.hwclr "logic abr_key_hwif_in.MLKEM_SHARED_KEY.KEY[5].data.hwclr"
Toggle abr_key_hwif_in.MLKEM_SHARED_KEY.KEY[6].data.hwclr "logic abr_key_hwif_in.MLKEM_SHARED_KEY.KEY[6].data.hwclr"
Toggle abr_key_hwif_in.MLKEM_SHARED_KEY.KEY[7].data.hwclr "logic abr_key_hwif_in.MLKEM_SHARED_KEY.KEY[7].data.hwclr"
Toggle abr_key_hwif_in.MLKEM_SHARED_KEY.IRQ_STATUS.key_valid.next "logic abr_key_hwif_in.MLKEM_SHARED_KEY.IRQ_STATUS.key_valid.next"

CHECKSUM: "692244178 3042302331"
ANNOTATION: "SEP-KVSHIM-WRRESP-TIE: kv_wr_resp is the constant '{error: 1'b0}. hw/sys/sep/rtl/sep_abr_kv_shim.sv:158, hw/sys/sep/rtl/sep_crypto_abr_wrapper.sv:271"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_abr_wrapper_s3c_scan
Toggle ab_kv_wr_resp.error "logic ab_kv_wr_resp.error"

CHECKSUM: "692244178 3042302331"
ANNOTATION: "SEP-KV-OFFSET-WIDTH: abr_ctrl instantiates the ML-DSA seed and ML-KEM msg kv_read_client and the shared-key kv_write_client with DATA_WIDTH=8*32, so their offset counter is $clog2(8)=3 bits and is zero-extended to KV_ENTRY_SIZE_W=4; offset bit 3 holds 0 (the ML-KEM seed lane is 16 dwords and is not listed). vendor/chipsalliance/adams-bridge/upstream/src/abr_top/rtl/abr_ctrl.sv:320-321,378-379,406-407, abr_ctrl_pkg.sv:35,58,67; vendor/chipsalliance/caliptra-rtl/upstream/src/keyvault/rtl/kv_read_client.sv:26,104, kv_write_client.sv:23,101, kv_defines_pkg.sv:20,25"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_abr_wrapper_s3c_scan
Toggle ab_kv_read[0].read_offset [3] "logic ab_kv_read[0].read_offset[3:0]"
Toggle ab_kv_read[2].read_offset [3] "logic ab_kv_read[2].read_offset[3:0]"
Toggle ab_kv_write.write_offset [3] "logic ab_kv_write.write_offset[3:0]"

CHECKSUM: "692244178 3042302331"
ANNOTATION: "SEP-AHB-CTRL-TIE: axi_lite_to_ahb drives hburst=HBURST_SINGLE and hmastlock=0, hprot[3:2]=2'b00, htrans only IDLE(00)/NONSEQ(10) so bit 0 is 0, and hsize only BYTE/HALF/WORD (req_size from wr_strb_size or HSIZE_WORD) so bit 2 is 0. ahb_addr_ctrl[3:2] and [6] are those hprot and hsize bits. hw/common/axi/axi_lite_to_ahb.sv:79-84,146,166-187,209-213,244,253,336"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_abr_wrapper_s3c_scan
Toggle ab_hburst "logic ab_hburst[2:0]"
Toggle ab_hmastlock "logic ab_hmastlock"
Toggle ab_hprot [3:2] "logic ab_hprot[3:0]"
Toggle ab_htrans [0] "logic ab_htrans[1:0]"
Toggle ab_hsize [2] "logic ab_hsize[2:0]"

CHECKSUM: "692244178 3042302331"
ANNOTATION: "SEP-AHB-RESP-BIT0: axi_lite_to_ahb returns only AXI_RESP_OKAY=2'b00 or AXI_RESP_SLVERR=2'b10, so resp bit 0 holds 0 (bit 1 is the reachable SLVERR and is not listed). hw/common/axi/axi_lite_to_ahb.sv:76-77,234-235,288,313"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_abr_wrapper_s3c_scan
Toggle abr_axil_resp.r.resp [0] "logic abr_axil_resp.r.resp[1:0]"
Toggle abr_axil_resp.b.resp [0] "logic abr_axil_resp.b.resp[1:0]"

CHECKSUM: "692244178 3042302331"
ANNOTATION: "SEP-REGBLOCK-RESP-BIT0: the PeakRDL AXI4-Lite cpuif assigns s_axil_bresp/s_axil_rresp only 2'b10 or 2'b00, so bit 0 holds 0 (bit 1 is the reachable SLVERR of this error-decoding block and is not listed). hw/ip/key_manager/regs/gen/sv/abr_wrapper_key_reg.sv:209-215, otbn_wrapper_key_reg.sv:208-214, km_mailbox_sep_reg.sv:209-215; wired out at hw/sys/sep/rtl/sep_crypto_abr_wrapper.sv:227,239"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_abr_wrapper_s3c_scan
Toggle abr_key_axil_resp_o.r.resp [0] "logic abr_key_axil_resp_o.r.resp[1:0]"
Toggle abr_key_axil_resp_o.b.resp [0] "logic abr_key_axil_resp_o.b.resp[1:0]"

CHECKSUM: "692244178 3042302331"
ANNOTATION: "SEP-ABR-MEM-ADDR-PAD: the ABR INST0 address is $clog2(832)=10 bits and INST1 is $clog2(64)=6 bits; the wrapper casts both to SEP_CRYPTO_ABR_INST2_ADDR_W=11, so INST0 bit 10 and INST1 bits 10:6 hold 0. hw/sys/sep/rtl/sep_crypto_abr_wrapper.sv:297-312,321-337, hw/sys/sep/rtl/sep_crypto_pkg.sv:238-240, vendor/chipsalliance/adams-bridge/upstream/src/abr_top/rtl/abr_params_pkg.sv:64-68"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_abr_wrapper_s3c_scan
Toggle abr_mem_req_o.mem_inst0_bank0.waddr [10] "logic abr_mem_req_o.mem_inst0_bank0.waddr[10:0]"
Toggle abr_mem_req_o.mem_inst0_bank0.raddr [10] "logic abr_mem_req_o.mem_inst0_bank0.raddr[10:0]"
Toggle abr_mem_req_o.mem_inst0_bank1.waddr [10] "logic abr_mem_req_o.mem_inst0_bank1.waddr[10:0]"
Toggle abr_mem_req_o.mem_inst0_bank1.raddr [10] "logic abr_mem_req_o.mem_inst0_bank1.raddr[10:0]"
Toggle abr_mem_req_o.mem_inst0_bank0_masked.waddr [10] "logic abr_mem_req_o.mem_inst0_bank0_masked.waddr[10:0]"
Toggle abr_mem_req_o.mem_inst0_bank0_masked.raddr [10] "logic abr_mem_req_o.mem_inst0_bank0_masked.raddr[10:0]"
Toggle abr_mem_req_o.mem_inst0_bank1_masked.waddr [10] "logic abr_mem_req_o.mem_inst0_bank1_masked.waddr[10:0]"
Toggle abr_mem_req_o.mem_inst0_bank1_masked.raddr [10] "logic abr_mem_req_o.mem_inst0_bank1_masked.raddr[10:0]"
Toggle abr_mem_req_o.mem_inst1.waddr [10:6] "logic abr_mem_req_o.mem_inst1.waddr[10:0]"
Toggle abr_mem_req_o.mem_inst1.raddr [10:6] "logic abr_mem_req_o.mem_inst1.raddr[10:0]"
Toggle abr_mem_req_o.mem_inst1_masked.waddr [10:6] "logic abr_mem_req_o.mem_inst1_masked.waddr[10:0]"
Toggle abr_mem_req_o.mem_inst1_masked.raddr [10:6] "logic abr_mem_req_o.mem_inst1_masked.raddr[10:0]"

CHECKSUM: "2662093143 2179785762"
ANNOTATION: "SEP-KVSHIM-HWIF-DEFAULT: sep_abr_kv_shim drives hwif_o to '{default: 0} and assigns only KEY[*].data.next/we, KEY_CTRL.key_valid.hwset and IRQ_STATUS.key_valid.hwset; KEY[*].data.hwclr and IRQ_STATUS.key_valid.next are never assigned and hold 0. The wrapper wires hwif_o straight into abr_wrapper_key_reg hwif_in. hw/sys/sep/rtl/sep_abr_kv_shim.sv:145-155, hw/sys/sep/rtl/sep_crypto_abr_wrapper.sv:242,265-272"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_abr_wrapper_s3c_scan.u_abr_key_csr
Toggle hwif_in.MLKEM_SHARED_KEY.KEY[0].data.hwclr "logic hwif_in.MLKEM_SHARED_KEY.KEY[0].data.hwclr"
Toggle hwif_in.MLKEM_SHARED_KEY.KEY[1].data.hwclr "logic hwif_in.MLKEM_SHARED_KEY.KEY[1].data.hwclr"
Toggle hwif_in.MLKEM_SHARED_KEY.KEY[2].data.hwclr "logic hwif_in.MLKEM_SHARED_KEY.KEY[2].data.hwclr"
Toggle hwif_in.MLKEM_SHARED_KEY.KEY[3].data.hwclr "logic hwif_in.MLKEM_SHARED_KEY.KEY[3].data.hwclr"
Toggle hwif_in.MLKEM_SHARED_KEY.KEY[4].data.hwclr "logic hwif_in.MLKEM_SHARED_KEY.KEY[4].data.hwclr"
Toggle hwif_in.MLKEM_SHARED_KEY.KEY[5].data.hwclr "logic hwif_in.MLKEM_SHARED_KEY.KEY[5].data.hwclr"
Toggle hwif_in.MLKEM_SHARED_KEY.KEY[6].data.hwclr "logic hwif_in.MLKEM_SHARED_KEY.KEY[6].data.hwclr"
Toggle hwif_in.MLKEM_SHARED_KEY.KEY[7].data.hwclr "logic hwif_in.MLKEM_SHARED_KEY.KEY[7].data.hwclr"
Toggle hwif_in.MLKEM_SHARED_KEY.IRQ_STATUS.key_valid.next "logic hwif_in.MLKEM_SHARED_KEY.IRQ_STATUS.key_valid.next"

CHECKSUM: "2662093143 2179785762"
ANNOTATION: "SEP-REGBLOCK-RESP-BIT0: the PeakRDL AXI4-Lite cpuif assigns s_axil_bresp/s_axil_rresp only 2'b10 or 2'b00, so bit 0 holds 0 (bit 1 is the reachable SLVERR of this error-decoding block and is not listed). hw/ip/key_manager/regs/gen/sv/abr_wrapper_key_reg.sv:209-215, otbn_wrapper_key_reg.sv:208-214, km_mailbox_sep_reg.sv:209-215; wired out at hw/sys/sep/rtl/sep_crypto_abr_wrapper.sv:227,239"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_abr_wrapper_s3c_scan.u_abr_key_csr
Toggle s_axil_bresp [0] "logic s_axil_bresp[1:0]"
Toggle s_axil_rresp [0] "logic s_axil_rresp[1:0]"

CHECKSUM: "3248781186 4236053843"
ANNOTATION: "SEP-AHB-CTRL-TIE: axi_lite_to_ahb drives hburst=HBURST_SINGLE and hmastlock=0, hprot[3:2]=2'b00, htrans only IDLE(00)/NONSEQ(10) so bit 0 is 0, and hsize only BYTE/HALF/WORD (req_size from wr_strb_size or HSIZE_WORD) so bit 2 is 0. ahb_addr_ctrl[3:2] and [6] are those hprot and hsize bits. hw/common/axi/axi_lite_to_ahb.sv:79-84,146,166-187,209-213,244,253,336"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_abr_wrapper_s3c_scan.u_axi_lite_to_ahb
Toggle ahb_hburst_o "logic ahb_hburst_o[2:0]"
Toggle ahb_hmastlock_o "logic ahb_hmastlock_o"
Toggle ahb_hprot_o [3:2] "logic ahb_hprot_o[3:0]"
Toggle ahb_hsize_o [2] "logic ahb_hsize_o[2:0]"
Toggle ahb_htrans_o [0] "logic ahb_htrans_o[1:0]"
Toggle req_size_q [2] "logic req_size_q[2:0]"
Toggle req_size_d [2] "logic req_size_d[2:0]"
Toggle wr_strb_size [2] "logic wr_strb_size[2:0]"
Toggle ahb_addr_ctrl [3:2] "logic ahb_addr_ctrl[39:0]"
Toggle ahb_addr_ctrl [6] "logic ahb_addr_ctrl[39:0]"

CHECKSUM: "3248781186 4236053843"
ANNOTATION: "SEP-AHB-RESP-BIT0: axi_lite_to_ahb returns only AXI_RESP_OKAY=2'b00 or AXI_RESP_SLVERR=2'b10, so resp bit 0 holds 0 (bit 1 is the reachable SLVERR and is not listed). hw/common/axi/axi_lite_to_ahb.sv:76-77,234-235,288,313"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_abr_wrapper_s3c_scan.u_axi_lite_to_ahb
Toggle axi_lite_rsp_o.r.resp [0] "logic axi_lite_rsp_o.r.resp[1:0]"
Toggle axi_lite_rsp_o.b.resp [0] "logic axi_lite_rsp_o.b.resp[1:0]"

CHECKSUM: "2772866781 740540854"
ANNOTATION: "SEP-MBOX-HWIF-TIE: km_mailbox ties the .next input of every hwset-only overflow/underflow/flushed_by_km field of the SEP-port regblock to 1'b0. hw/ip/key_manager/rtl/km_mailbox.sv:574-587"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_key_manager_s3c_scan.u_mailbox.u_sep_regs
Toggle hwif_in.SEP_STATUS.inbound_overflow.next "logic hwif_in.SEP_STATUS.inbound_overflow.next"
Toggle hwif_in.SEP_STATUS.inbound_underflow.next "logic hwif_in.SEP_STATUS.inbound_underflow.next"
Toggle hwif_in.SEP_STATUS.outbound_overflow.next "logic hwif_in.SEP_STATUS.outbound_overflow.next"
Toggle hwif_in.SEP_STATUS.outbound_underflow.next "logic hwif_in.SEP_STATUS.outbound_underflow.next"
Toggle hwif_in.SEP_IRQ_STATUS.inbound_overflow.next "logic hwif_in.SEP_IRQ_STATUS.inbound_overflow.next"
Toggle hwif_in.SEP_IRQ_STATUS.outbound_underflow.next "logic hwif_in.SEP_IRQ_STATUS.outbound_underflow.next"
Toggle hwif_in.SEP_IRQ_STATUS.flushed_by_km.next "logic hwif_in.SEP_IRQ_STATUS.flushed_by_km.next"

CHECKSUM: "2772866781 740540854"
ANNOTATION: "SEP-MBOX-DEPTH-PAD: the depth fields are {(8-FIFO_DEPTH_W) zeros, depth} with FIFO_DEPTH_W=$clog2(MAILBOX_DEPTH+1)=$clog2(17)=5, so bits 7:5 hold 0. hw/ip/key_manager/rtl/km_mailbox.sv:33,78,413-414"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_key_manager_s3c_scan.u_mailbox.u_sep_regs
Toggle hwif_in.SEP_STATUS.inbound_depth.next [7:5] "logic hwif_in.SEP_STATUS.inbound_depth.next[7:0]"
Toggle hwif_in.SEP_STATUS.outbound_depth.next [7:5] "logic hwif_in.SEP_STATUS.outbound_depth.next[7:0]"

CHECKSUM: "2772866781 740540854"
ANNOTATION: "SEP-REGBLOCK-RESP-BIT0: the PeakRDL AXI4-Lite cpuif assigns s_axil_bresp/s_axil_rresp only 2'b10 or 2'b00, so bit 0 holds 0 (bit 1 is the reachable SLVERR of this error-decoding block and is not listed). hw/ip/key_manager/regs/gen/sv/abr_wrapper_key_reg.sv:209-215, otbn_wrapper_key_reg.sv:208-214, km_mailbox_sep_reg.sv:209-215; wired out at hw/sys/sep/rtl/sep_crypto_abr_wrapper.sv:227,239"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_key_manager_s3c_scan.u_mailbox.u_sep_regs
Toggle s_axil_bresp [0] "logic s_axil_bresp[1:0]"
Toggle s_axil_rresp [0] "logic s_axil_rresp[1:0]"

CHECKSUM: "3854019001 2705449490"
ANNOTATION: "SEP-ALERT-PING-TIE: every sep_crypto alert receiver has ping_req_i=1'b0, so ping_rise and ping_pending stay 0, send_ping never fires and the ping diff pair keeps its reset value 2'b10 (ping_p=0, ping_n=1). hw/sys/sep/rtl/sep_crypto.sv:287-302; vendor/lowRISC/opentitan/upstream/hw/ip/prim/rtl/prim_alert_receiver.sv:108-111,130-140,147,153-154,169,226"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_otbn_wrapper_s3c_scan
Toggle alert_rx_i[0].ping_p "logic alert_rx_i[0].ping_p"
Toggle alert_rx_i[0].ping_n "logic alert_rx_i[0].ping_n"
Toggle alert_rx_i[1].ping_p "logic alert_rx_i[1].ping_p"
Toggle alert_rx_i[1].ping_n "logic alert_rx_i[1].ping_n"
Toggle otbn_alert_rx[0].ping_p "logic otbn_alert_rx[0].ping_p"
Toggle otbn_alert_rx[0].ping_n "logic otbn_alert_rx[0].ping_n"
Toggle otbn_alert_rx[1].ping_p "logic otbn_alert_rx[1].ping_p"
Toggle otbn_alert_rx[1].ping_n "logic otbn_alert_rx[1].ping_n"

CHECKSUM: "3854019001 2705449490"
ANNOTATION: "SEP-OTBN-OTP-KEY-TIE: the OTBN OTP scramble-key response carries constant key, nonce and seed_valid=1. hw/sys/sep/rtl/sep_crypto_otbn_wrapper.sv:161-163"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_otbn_wrapper_s3c_scan
Toggle otbn_otp_key_rsp.key "logic otbn_otp_key_rsp.key[127:0]"
Toggle otbn_otp_key_rsp.nonce "logic otbn_otp_key_rsp.nonce[63:0]"
Toggle otbn_otp_key_rsp.seed_valid "logic otbn_otp_key_rsp.seed_valid"

CHECKSUM: "3854019001 2705449490"
ANNOTATION: "SEP-TLUL-A-CONST: axi_lite_to_tlul starts tl_o from '0 and only sets a_size=2, a_user.instr_type=MuBi4False, the integrity fields, address, data, mask and a_opcode in {Get=4, PutFullData=0, PutPartialData=1}; a_source, a_param and a_user.rsvd stay 0, a_size and instr_type are constant, and a_opcode bit 1 holds 0. hw/common/axi/axi_lite_to_tlul.sv:132-136,173,213,215"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_otbn_wrapper_s3c_scan
Toggle tl_req.a_user.instr_type "logic tl_req.a_user.instr_type[3:0]"
Toggle tl_req.a_user.rsvd "logic tl_req.a_user.rsvd[9:0]"
Toggle tl_req.a_source "logic tl_req.a_source[7:0]"
Toggle tl_req.a_size "logic tl_req.a_size[1:0]"
Toggle tl_req.a_param "logic tl_req.a_param[2:0]"
Toggle tl_req.a_opcode [1] "logic tl_req.a_opcode[2:0]"

CHECKSUM: "3854019001 2705449490"
ANNOTATION: "SEP-TLUL-RESP-BIT0: axi_lite_to_tlul returns only AXI_RESP_OKAY=2'b00 or AXI_RESP_SLVERR=2'b10, so resp bit 0 holds 0 (bit 1 is the reachable SLVERR and is not listed). hw/common/axi/axi_lite_to_tlul.sv:54-55,128-129,195,234"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_otbn_wrapper_s3c_scan
Toggle otbn_axil_resp_o.r.resp [0] "logic otbn_axil_resp_o.r.resp[1:0]"
Toggle otbn_axil_resp_o.b.resp [0] "logic otbn_axil_resp_o.b.resp[1:0]"

CHECKSUM: "3854019001 2705449490"
ANNOTATION: "SEP-REGBLOCK-RESP-BIT0: the PeakRDL AXI4-Lite cpuif assigns s_axil_bresp/s_axil_rresp only 2'b10 or 2'b00, so bit 0 holds 0 (bit 1 is the reachable SLVERR of this error-decoding block and is not listed). hw/ip/key_manager/regs/gen/sv/abr_wrapper_key_reg.sv:209-215, otbn_wrapper_key_reg.sv:208-214, km_mailbox_sep_reg.sv:209-215; wired out at hw/sys/sep/rtl/sep_crypto_abr_wrapper.sv:227,239"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_otbn_wrapper_s3c_scan
Toggle otbn_key_axil_resp_o.r.resp [0] "logic otbn_key_axil_resp_o.r.resp[1:0]"
Toggle otbn_key_axil_resp_o.b.resp [0] "logic otbn_key_axil_resp_o.b.resp[1:0]"

CHECKSUM: "3313930772 2110593416"
ANNOTATION: "SEP-REGBLOCK-RESP-BIT0: the PeakRDL AXI4-Lite cpuif assigns s_axil_bresp/s_axil_rresp only 2'b10 or 2'b00, so bit 0 holds 0 (bit 1 is the reachable SLVERR of this error-decoding block and is not listed). hw/ip/key_manager/regs/gen/sv/abr_wrapper_key_reg.sv:209-215, otbn_wrapper_key_reg.sv:208-214, km_mailbox_sep_reg.sv:209-215; wired out at hw/sys/sep/rtl/sep_crypto_abr_wrapper.sv:227,239"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_otbn_wrapper_s3c_scan.u_otbn_wrapper_key_reg
Toggle s_axil_bresp [0] "logic s_axil_bresp[1:0]"
Toggle s_axil_rresp [0] "logic s_axil_rresp[1:0]"

CHECKSUM: "2097437693 2552262841"
ANNOTATION: "SEP-TLUL-A-CONST: axi_lite_to_tlul starts tl_o from '0 and only sets a_size=2, a_user.instr_type=MuBi4False, the integrity fields, address, data, mask and a_opcode in {Get=4, PutFullData=0, PutPartialData=1}; a_source, a_param and a_user.rsvd stay 0, a_size and instr_type are constant, and a_opcode bit 1 holds 0. hw/common/axi/axi_lite_to_tlul.sv:132-136,173,213,215"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_otbn_wrapper_s3c_scan.u_axi_lite_to_tlul
Toggle tl_o.a_user.instr_type "logic tl_o.a_user.instr_type[3:0]"
Toggle tl_o.a_user.rsvd "logic tl_o.a_user.rsvd[9:0]"
Toggle tl_o.a_source "logic tl_o.a_source[7:0]"
Toggle tl_o.a_size "logic tl_o.a_size[1:0]"
Toggle tl_o.a_param "logic tl_o.a_param[2:0]"
Toggle tl_o.a_opcode [1] "logic tl_o.a_opcode[2:0]"

CHECKSUM: "2097437693 2552262841"
ANNOTATION: "SEP-TLUL-RESP-BIT0: axi_lite_to_tlul returns only AXI_RESP_OKAY=2'b00 or AXI_RESP_SLVERR=2'b10, so resp bit 0 holds 0 (bit 1 is the reachable SLVERR and is not listed). hw/common/axi/axi_lite_to_tlul.sv:54-55,128-129,195,234"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_otbn_wrapper_s3c_scan.u_axi_lite_to_tlul
Toggle axi_lite_rsp_o.r.resp [0] "logic axi_lite_rsp_o.r.resp[1:0]"
Toggle axi_lite_rsp_o.b.resp [0] "logic axi_lite_rsp_o.b.resp[1:0]"

CHECKSUM: "2097437693 2552262841"
ANNOTATION: "SEP-TLUL-A-CONST: axi_lite_to_tlul starts tl_o from '0 and only sets a_size=2, a_user.instr_type=MuBi4False, the integrity fields, address, data, mask and a_opcode in {Get=4, PutFullData=0, PutPartialData=1}; a_source, a_param and a_user.rsvd stay 0, a_size and instr_type are constant, and a_opcode bit 1 holds 0. hw/common/axi/axi_lite_to_tlul.sv:132-136,173,213,215"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_drbg_s3c_scan.u_csrng_axi_lite_to_tlul
Toggle tl_o.a_user.instr_type "logic tl_o.a_user.instr_type[3:0]"
Toggle tl_o.a_user.rsvd "logic tl_o.a_user.rsvd[9:0]"
Toggle tl_o.a_source "logic tl_o.a_source[7:0]"
Toggle tl_o.a_size "logic tl_o.a_size[1:0]"
Toggle tl_o.a_param "logic tl_o.a_param[2:0]"
Toggle tl_o.a_opcode [1] "logic tl_o.a_opcode[2:0]"

CHECKSUM: "2097437693 2552262841"
ANNOTATION: "SEP-TLUL-RESP-BIT0: axi_lite_to_tlul returns only AXI_RESP_OKAY=2'b00 or AXI_RESP_SLVERR=2'b10, so resp bit 0 holds 0 (bit 1 is the reachable SLVERR and is not listed). hw/common/axi/axi_lite_to_tlul.sv:54-55,128-129,195,234"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_drbg_s3c_scan.u_csrng_axi_lite_to_tlul
Toggle axi_lite_rsp_o.r.resp [0] "logic axi_lite_rsp_o.r.resp[1:0]"
Toggle axi_lite_rsp_o.b.resp [0] "logic axi_lite_rsp_o.b.resp[1:0]"

CHECKSUM: "2097437693 2552262841"
ANNOTATION: "SEP-TLUL-A-CONST: axi_lite_to_tlul starts tl_o from '0 and only sets a_size=2, a_user.instr_type=MuBi4False, the integrity fields, address, data, mask and a_opcode in {Get=4, PutFullData=0, PutPartialData=1}; a_source, a_param and a_user.rsvd stay 0, a_size and instr_type are constant, and a_opcode bit 1 holds 0. hw/common/axi/axi_lite_to_tlul.sv:132-136,173,213,215"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_drbg_s3c_scan.u_edn_axi_lite_to_tlul
Toggle tl_o.a_user.instr_type "logic tl_o.a_user.instr_type[3:0]"
Toggle tl_o.a_user.rsvd "logic tl_o.a_user.rsvd[9:0]"
Toggle tl_o.a_source "logic tl_o.a_source[7:0]"
Toggle tl_o.a_size "logic tl_o.a_size[1:0]"
Toggle tl_o.a_param "logic tl_o.a_param[2:0]"
Toggle tl_o.a_opcode [1] "logic tl_o.a_opcode[2:0]"

CHECKSUM: "2097437693 2552262841"
ANNOTATION: "SEP-TLUL-RESP-BIT0: axi_lite_to_tlul returns only AXI_RESP_OKAY=2'b00 or AXI_RESP_SLVERR=2'b10, so resp bit 0 holds 0 (bit 1 is the reachable SLVERR and is not listed). hw/common/axi/axi_lite_to_tlul.sv:54-55,128-129,195,234"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_drbg_s3c_scan.u_edn_axi_lite_to_tlul
Toggle axi_lite_rsp_o.r.resp [0] "logic axi_lite_rsp_o.r.resp[1:0]"
Toggle axi_lite_rsp_o.b.resp [0] "logic axi_lite_rsp_o.b.resp[1:0]"

CHECKSUM: "2550488390 2486335419"
ANNOTATION: "SEP-ALERT-PING-TIE: every sep_crypto alert receiver has ping_req_i=1'b0, so ping_rise and ping_pending stay 0, send_ping never fires and the ping diff pair keeps its reset value 2'b10 (ping_p=0, ping_n=1). hw/sys/sep/rtl/sep_crypto.sv:287-302; vendor/lowRISC/opentitan/upstream/hw/ip/prim/rtl/prim_alert_receiver.sv:108-111,130-140,147,153-154,169,226"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng
Toggle csrng_alert_rx_i[0].ping_p "logic csrng_alert_rx_i[0].ping_p"
Toggle csrng_alert_rx_i[0].ping_n "logic csrng_alert_rx_i[0].ping_n"
Toggle csrng_alert_rx_i[1].ping_p "logic csrng_alert_rx_i[1].ping_p"
Toggle csrng_alert_rx_i[1].ping_n "logic csrng_alert_rx_i[1].ping_n"
Toggle edn_alert_rx_i[0].ping_p "logic edn_alert_rx_i[0].ping_p"
Toggle edn_alert_rx_i[0].ping_n "logic edn_alert_rx_i[0].ping_n"
Toggle edn_alert_rx_i[1].ping_p "logic edn_alert_rx_i[1].ping_p"
Toggle edn_alert_rx_i[1].ping_n "logic edn_alert_rx_i[1].ping_n"

CHECKSUM: "2550488390 2486335419"
ANNOTATION: "SEP-DRBG-TSTRB-TIE: drbg_edn_axis_adapter drives every endpoint tstrb to 4'hF, and drbg/sep_trng pass it through unchanged. hw/ip/drbg/rtl/drbg_edn_axis_adapter.sv:69, hw/ip/drbg/rtl/drbg.sv:185-193, hw/sys/sep/rtl/sep_trng.sv:134, hw/sys/sep/rtl/sep_crypto.sv:453"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng
Toggle drbg_axis_req_o[0].tstrb "logic drbg_axis_req_o[0].tstrb[3:0]"
Toggle drbg_axis_req_o[1].tstrb "logic drbg_axis_req_o[1].tstrb[3:0]"
Toggle drbg_axis_req_o[2].tstrb "logic drbg_axis_req_o[2].tstrb[3:0]"

CHECKSUM: "2550488390 2486335419"
ANNOTATION: "SEP-DRBG-RESP-BIT0: drbg_axil64_lane_adapter returns AXI_RESP_OKAY, AXI_RESP_SLVERR or the axi_lite_to_tlul response, and axi_lite_to_tlul returns only 2'b00 or 2'b10, so resp bit 0 holds 0. hw/ip/drbg/rtl/drbg_axil64_lane_adapter.sv:44-45,112,158-159,214,229,250,280,258,287; hw/common/axi/axi_lite_to_tlul.sv:54-55,128-129,195,234"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng
Toggle csrng_axil_resp_o.r.resp [0] "logic csrng_axil_resp_o.r.resp[1:0]"
Toggle csrng_axil_resp_o.b.resp [0] "logic csrng_axil_resp_o.b.resp[1:0]"
Toggle edn_axil_resp_o.r.resp [0] "logic edn_axil_resp_o.r.resp[1:0]"
Toggle edn_axil_resp_o.b.resp [0] "logic edn_axil_resp_o.b.resp[1:0]"

CHECKSUM: "2550488390 2486335419"
ANNOTATION: "SEP-ESRC-NOERR-RESP: entropy_source_reg decodes no error (is_valid_addr/is_valid_rw='1, decoded_err='0, cpuif_wr_err='0, readback_err='0) so its buffered error stays 0 and BRESP/RRESP hold 2'b00; entropy_source and sep_trng pass them through. hw/ip/entropy_source/regs/gen/sv/entropy_source_reg.sv:168,173,200-205,309-310,383,3220,3511,3517; hw/ip/entropy_source/rtl/entropy_source.sv:737,747; hw/sys/sep/rtl/sep_trng.sv:110,118"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng
Toggle esrc_axil_resp_o.r.resp "logic esrc_axil_resp_o.r.resp[1:0]"
Toggle esrc_axil_resp_o.b.resp "logic esrc_axil_resp_o.b.resp[1:0]"

CHECKSUM: "251540385 1629975084"
ANNOTATION: "SEP-ALERT-PING-TIE: every sep_crypto alert receiver has ping_req_i=1'b0, so ping_rise and ping_pending stay 0, send_ping never fires and the ping diff pair keeps its reset value 2'b10 (ping_p=0, ping_n=1). hw/sys/sep/rtl/sep_crypto.sv:287-302; vendor/lowRISC/opentitan/upstream/hw/ip/prim/rtl/prim_alert_receiver.sv:108-111,130-140,147,153-154,169,226"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_drbg_s3c_scan
Toggle csrng_alert_rx_i[0].ping_p "logic csrng_alert_rx_i[0].ping_p"
Toggle csrng_alert_rx_i[0].ping_n "logic csrng_alert_rx_i[0].ping_n"
Toggle csrng_alert_rx_i[1].ping_p "logic csrng_alert_rx_i[1].ping_p"
Toggle csrng_alert_rx_i[1].ping_n "logic csrng_alert_rx_i[1].ping_n"
Toggle edn_alert_rx_i[0].ping_p "logic edn_alert_rx_i[0].ping_p"
Toggle edn_alert_rx_i[0].ping_n "logic edn_alert_rx_i[0].ping_n"
Toggle edn_alert_rx_i[1].ping_p "logic edn_alert_rx_i[1].ping_p"
Toggle edn_alert_rx_i[1].ping_n "logic edn_alert_rx_i[1].ping_n"

CHECKSUM: "251540385 1629975084"
ANNOTATION: "SEP-DRBG-TSTRB-TIE: drbg_edn_axis_adapter drives every endpoint tstrb to 4'hF, and drbg/sep_trng pass it through unchanged. hw/ip/drbg/rtl/drbg_edn_axis_adapter.sv:69, hw/ip/drbg/rtl/drbg.sv:185-193, hw/sys/sep/rtl/sep_trng.sv:134, hw/sys/sep/rtl/sep_crypto.sv:453"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_drbg_s3c_scan
Toggle edn_axis_o[0].tstrb "logic edn_axis_o[0].tstrb[3:0]"
Toggle edn_axis_o[1].tstrb "logic edn_axis_o[1].tstrb[3:0]"
Toggle edn_axis_o[2].tstrb "logic edn_axis_o[2].tstrb[3:0]"

CHECKSUM: "251540385 1629975084"
ANNOTATION: "SEP-DRBG-INPUT-TIE: sep_trng ties edn_native_req_i=EDN_REQ_DEFAULT ('0), otp_en_csrng_sw_app_read_i=MuBi8True and lc_hw_debug_en_i=Off; with EDN_NATIVE_ENDPOINT_COUNT=0 drbg drives edn_native_rsp_o[0]=EDN_RSP_DEFAULT, and every CSRNG HW app above index 0 is CSRNG_REQ_DEFAULT ('0). hw/sys/sep/rtl/sep_trng.sv:126-128,136,142-143; hw/ip/drbg/rtl/drbg.sv:206-213,289-295; vendor/lowRISC/opentitan/upstream/hw/ip/edn/rtl/edn_pkg.sv:26-27, vendor/lowRISC/opentitan/upstream/hw/ip/csrng/rtl/csrng_pkg.sv:74"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_drbg_s3c_scan
Toggle edn_native_req_i[0].edn_req "logic edn_native_req_i[0].edn_req"
Toggle edn_native_rsp_o[0].edn_bus "logic edn_native_rsp_o[0].edn_bus[31:0]"
Toggle edn_native_rsp_o[0].edn_fips "logic edn_native_rsp_o[0].edn_fips"
Toggle edn_native_rsp_o[0].edn_ack "logic edn_native_rsp_o[0].edn_ack"
Toggle otp_en_csrng_sw_app_read_i "logic otp_en_csrng_sw_app_read_i[7:0]"
Toggle lc_hw_debug_en_i "logic lc_hw_debug_en_i[3:0]"
Toggle csrng_hw_req[1].genbits_ready "logic csrng_hw_req[1].genbits_ready"
Toggle csrng_hw_req[1].csrng_req_bus "logic csrng_hw_req[1].csrng_req_bus[31:0]"
Toggle csrng_hw_req[1].csrng_req_valid "logic csrng_hw_req[1].csrng_req_valid"

CHECKSUM: "251540385 1629975084"
ANNOTATION: "SEP-DRBG-RESP-BIT0: drbg_axil64_lane_adapter returns AXI_RESP_OKAY, AXI_RESP_SLVERR or the axi_lite_to_tlul response, and axi_lite_to_tlul returns only 2'b00 or 2'b10, so resp bit 0 holds 0. hw/ip/drbg/rtl/drbg_axil64_lane_adapter.sv:44-45,112,158-159,214,229,250,280,258,287; hw/common/axi/axi_lite_to_tlul.sv:54-55,128-129,195,234"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_drbg_s3c_scan
Toggle csrng_axil_rsp_o.r.resp [0] "logic csrng_axil_rsp_o.r.resp[1:0]"
Toggle csrng_axil_rsp_o.b.resp [0] "logic csrng_axil_rsp_o.b.resp[1:0]"
Toggle edn_axil_rsp_o.r.resp [0] "logic edn_axil_rsp_o.r.resp[1:0]"
Toggle edn_axil_rsp_o.b.resp [0] "logic edn_axil_rsp_o.b.resp[1:0]"
Toggle csrng_axil32_rsp.r.resp [0] "logic csrng_axil32_rsp.r.resp[1:0]"
Toggle csrng_axil32_rsp.b.resp [0] "logic csrng_axil32_rsp.b.resp[1:0]"
Toggle edn_axil32_rsp.r.resp [0] "logic edn_axil32_rsp.r.resp[1:0]"
Toggle edn_axil32_rsp.b.resp [0] "logic edn_axil32_rsp.b.resp[1:0]"

CHECKSUM: "251540385 1629975084"
ANNOTATION: "SEP-TLUL-A-CONST: axi_lite_to_tlul starts tl_o from '0 and only sets a_size=2, a_user.instr_type=MuBi4False, the integrity fields, address, data, mask and a_opcode in {Get=4, PutFullData=0, PutPartialData=1}; a_source, a_param and a_user.rsvd stay 0, a_size and instr_type are constant, and a_opcode bit 1 holds 0. hw/common/axi/axi_lite_to_tlul.sv:132-136,173,213,215"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_drbg_s3c_scan
Toggle csrng_tl_h2d.a_user.instr_type "logic csrng_tl_h2d.a_user.instr_type[3:0]"
Toggle csrng_tl_h2d.a_user.rsvd "logic csrng_tl_h2d.a_user.rsvd[9:0]"
Toggle csrng_tl_h2d.a_source "logic csrng_tl_h2d.a_source[7:0]"
Toggle csrng_tl_h2d.a_size "logic csrng_tl_h2d.a_size[1:0]"
Toggle csrng_tl_h2d.a_param "logic csrng_tl_h2d.a_param[2:0]"
Toggle csrng_tl_h2d.a_opcode [1] "logic csrng_tl_h2d.a_opcode[2:0]"
Toggle edn_tl_h2d.a_user.instr_type "logic edn_tl_h2d.a_user.instr_type[3:0]"
Toggle edn_tl_h2d.a_user.rsvd "logic edn_tl_h2d.a_user.rsvd[9:0]"
Toggle edn_tl_h2d.a_source "logic edn_tl_h2d.a_source[7:0]"
Toggle edn_tl_h2d.a_size "logic edn_tl_h2d.a_size[1:0]"
Toggle edn_tl_h2d.a_param "logic edn_tl_h2d.a_param[2:0]"
Toggle edn_tl_h2d.a_opcode [1] "logic edn_tl_h2d.a_opcode[2:0]"

CHECKSUM: "1526382007 3216872359"
ANNOTATION: "SEP-DRBG-RESP-BIT0: drbg_axil64_lane_adapter returns AXI_RESP_OKAY, AXI_RESP_SLVERR or the axi_lite_to_tlul response, and axi_lite_to_tlul returns only 2'b00 or 2'b10, so resp bit 0 holds 0. hw/ip/drbg/rtl/drbg_axil64_lane_adapter.sv:44-45,112,158-159,214,229,250,280,258,287; hw/common/axi/axi_lite_to_tlul.sv:54-55,128-129,195,234"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_drbg_s3c_scan.u_csrng_axil_adapter
Toggle axil64_rsp_o.r.resp [0] "logic axil64_rsp_o.r.resp[1:0]"
Toggle axil64_rsp_o.b.resp [0] "logic axil64_rsp_o.b.resp[1:0]"
Toggle axil32_rsp_i.r.resp [0] "logic axil32_rsp_i.r.resp[1:0]"
Toggle axil32_rsp_i.b.resp [0] "logic axil32_rsp_i.b.resp[1:0]"
Toggle resp_code_q [0] "logic resp_code_q[1:0]"
Toggle resp_code_d [0] "logic resp_code_d[1:0]"

CHECKSUM: "1526382007 3216872359"
ANNOTATION: "SEP-DRBG-RESP-BIT0: drbg_axil64_lane_adapter returns AXI_RESP_OKAY, AXI_RESP_SLVERR or the axi_lite_to_tlul response, and axi_lite_to_tlul returns only 2'b00 or 2'b10, so resp bit 0 holds 0. hw/ip/drbg/rtl/drbg_axil64_lane_adapter.sv:44-45,112,158-159,214,229,250,280,258,287; hw/common/axi/axi_lite_to_tlul.sv:54-55,128-129,195,234"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_drbg_s3c_scan.u_edn_axil_adapter
Toggle axil64_rsp_o.r.resp [0] "logic axil64_rsp_o.r.resp[1:0]"
Toggle axil64_rsp_o.b.resp [0] "logic axil64_rsp_o.b.resp[1:0]"
Toggle axil32_rsp_i.r.resp [0] "logic axil32_rsp_i.r.resp[1:0]"
Toggle axil32_rsp_i.b.resp [0] "logic axil32_rsp_i.b.resp[1:0]"
Toggle resp_code_q [0] "logic resp_code_q[1:0]"
Toggle resp_code_d [0] "logic resp_code_d[1:0]"

CHECKSUM: "3888234644 481058055"
ANNOTATION: "SEP-DRBG-TSTRB-TIE: drbg_edn_axis_adapter drives every endpoint tstrb to 4'hF, and drbg/sep_trng pass it through unchanged. hw/ip/drbg/rtl/drbg_edn_axis_adapter.sv:69, hw/ip/drbg/rtl/drbg.sv:185-193, hw/sys/sep/rtl/sep_trng.sv:134, hw/sys/sep/rtl/sep_crypto.sv:453"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_drbg_s3c_scan.u_edn_axis_adapter
Toggle edn_axis_o[0].tstrb "logic edn_axis_o[0].tstrb[3:0]"
Toggle edn_axis_o[1].tstrb "logic edn_axis_o[1].tstrb[3:0]"
Toggle edn_axis_o[2].tstrb "logic edn_axis_o[2].tstrb[3:0]"

CHECKSUM: "3295933835 1628216908"
ANNOTATION: "SEP-ESRC-NOERR-RESP: entropy_source_reg decodes no error (is_valid_addr/is_valid_rw='1, decoded_err='0, cpuif_wr_err='0, readback_err='0) so its buffered error stays 0 and BRESP/RRESP hold 2'b00; entropy_source and sep_trng pass them through. hw/ip/entropy_source/regs/gen/sv/entropy_source_reg.sv:168,173,200-205,309-310,383,3220,3511,3517; hw/ip/entropy_source/rtl/entropy_source.sv:737,747; hw/sys/sep/rtl/sep_trng.sv:110,118"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_entropy_source_s3c_scan
Toggle s_axil_bresp_o "logic s_axil_bresp_o[1:0]"
Toggle s_axil_rresp_o "logic s_axil_rresp_o[1:0]"

CHECKSUM: "3536466054 1976754700"
ANNOTATION: "SEP-ALERT-PING-TIE: every sep_crypto alert receiver has ping_req_i=1'b0, so ping_rise and ping_pending stay 0, send_ping never fires and the ping diff pair keeps its reset value 2'b10 (ping_p=0, ping_n=1). hw/sys/sep/rtl/sep_crypto.sv:287-302; vendor/lowRISC/opentitan/upstream/hw/ip/prim/rtl/prim_alert_receiver.sv:108-111,130-140,147,153-154,169,226"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto
Toggle crypto_alert_rx[0].ping_p "logic crypto_alert_rx[0].ping_p"
Toggle crypto_alert_rx[0].ping_n "logic crypto_alert_rx[0].ping_n"
Toggle crypto_alert_rx[1].ping_p "logic crypto_alert_rx[1].ping_p"
Toggle crypto_alert_rx[1].ping_n "logic crypto_alert_rx[1].ping_n"
Toggle crypto_alert_rx[2].ping_p "logic crypto_alert_rx[2].ping_p"
Toggle crypto_alert_rx[2].ping_n "logic crypto_alert_rx[2].ping_n"
Toggle crypto_alert_rx[3].ping_p "logic crypto_alert_rx[3].ping_p"
Toggle crypto_alert_rx[3].ping_n "logic crypto_alert_rx[3].ping_n"
Toggle crypto_alert_rx[4].ping_p "logic crypto_alert_rx[4].ping_p"
Toggle crypto_alert_rx[4].ping_n "logic crypto_alert_rx[4].ping_n"
Toggle crypto_alert_rx[5].ping_p "logic crypto_alert_rx[5].ping_p"
Toggle crypto_alert_rx[5].ping_n "logic crypto_alert_rx[5].ping_n"
Toggle crypto_alert_rx[6].ping_p "logic crypto_alert_rx[6].ping_p"
Toggle crypto_alert_rx[6].ping_n "logic crypto_alert_rx[6].ping_n"
Toggle crypto_alert_rx[7].ping_p "logic crypto_alert_rx[7].ping_p"
Toggle crypto_alert_rx[7].ping_n "logic crypto_alert_rx[7].ping_n"
Toggle crypto_alert_rx[8].ping_p "logic crypto_alert_rx[8].ping_p"
Toggle crypto_alert_rx[8].ping_n "logic crypto_alert_rx[8].ping_n"
Toggle crypto_alert_rx[9].ping_p "logic crypto_alert_rx[9].ping_p"
Toggle crypto_alert_rx[9].ping_n "logic crypto_alert_rx[9].ping_n"
Toggle crypto_alert_rx[10].ping_p "logic crypto_alert_rx[10].ping_p"
Toggle crypto_alert_rx[10].ping_n "logic crypto_alert_rx[10].ping_n"

CHECKSUM: "3536466054 1976754700"
ANNOTATION: "SEP-DRBG-TSTRB-TIE: drbg_edn_axis_adapter drives every endpoint tstrb to 4'hF, and drbg/sep_trng pass it through unchanged. hw/ip/drbg/rtl/drbg_edn_axis_adapter.sv:69, hw/ip/drbg/rtl/drbg.sv:185-193, hw/sys/sep/rtl/sep_trng.sv:134, hw/sys/sep/rtl/sep_crypto.sv:453"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto
Toggle drbg_int_axis_req[0].tstrb "logic drbg_int_axis_req[0].tstrb[3:0]"
Toggle drbg_int_axis_req[1].tstrb "logic drbg_int_axis_req[1].tstrb[3:0]"
Toggle drbg_int_axis_req[2].tstrb "logic drbg_int_axis_req[2].tstrb[3:0]"

CHECKSUM: "3536466054 1976754700"
ANNOTATION: "SEP-ABR-MEM-ADDR-PAD: the ABR INST0 address is $clog2(832)=10 bits and INST1 is $clog2(64)=6 bits; the wrapper casts both to SEP_CRYPTO_ABR_INST2_ADDR_W=11, so INST0 bit 10 and INST1 bits 10:6 hold 0. hw/sys/sep/rtl/sep_crypto_abr_wrapper.sv:297-312,321-337, hw/sys/sep/rtl/sep_crypto_pkg.sv:238-240, vendor/chipsalliance/adams-bridge/upstream/src/abr_top/rtl/abr_params_pkg.sv:64-68"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto
Toggle abr_mem_req_o.mem_inst0_bank0.waddr [10] "logic abr_mem_req_o.mem_inst0_bank0.waddr[10:0]"
Toggle abr_mem_req_o.mem_inst0_bank0.raddr [10] "logic abr_mem_req_o.mem_inst0_bank0.raddr[10:0]"
Toggle abr_mem_req_o.mem_inst0_bank1.waddr [10] "logic abr_mem_req_o.mem_inst0_bank1.waddr[10:0]"
Toggle abr_mem_req_o.mem_inst0_bank1.raddr [10] "logic abr_mem_req_o.mem_inst0_bank1.raddr[10:0]"
Toggle abr_mem_req_o.mem_inst0_bank0_masked.waddr [10] "logic abr_mem_req_o.mem_inst0_bank0_masked.waddr[10:0]"
Toggle abr_mem_req_o.mem_inst0_bank0_masked.raddr [10] "logic abr_mem_req_o.mem_inst0_bank0_masked.raddr[10:0]"
Toggle abr_mem_req_o.mem_inst0_bank1_masked.waddr [10] "logic abr_mem_req_o.mem_inst0_bank1_masked.waddr[10:0]"
Toggle abr_mem_req_o.mem_inst0_bank1_masked.raddr [10] "logic abr_mem_req_o.mem_inst0_bank1_masked.raddr[10:0]"
Toggle abr_mem_req_o.mem_inst1.waddr [10:6] "logic abr_mem_req_o.mem_inst1.waddr[10:0]"
Toggle abr_mem_req_o.mem_inst1.raddr [10:6] "logic abr_mem_req_o.mem_inst1.raddr[10:0]"
Toggle abr_mem_req_o.mem_inst1_masked.waddr [10:6] "logic abr_mem_req_o.mem_inst1_masked.waddr[10:0]"
Toggle abr_mem_req_o.mem_inst1_masked.raddr [10:6] "logic abr_mem_req_o.mem_inst1_masked.raddr[10:0]"

CHECKSUM: "3536466054 1976754700"
ANNOTATION: "SEP-ESRC-NOERR-RESP: entropy_source_reg decodes no error (is_valid_addr/is_valid_rw='1, decoded_err='0, cpuif_wr_err='0, readback_err='0) so its buffered error stays 0 and BRESP/RRESP hold 2'b00; entropy_source and sep_trng pass them through. hw/ip/entropy_source/regs/gen/sv/entropy_source_reg.sv:168,173,200-205,309-310,383,3220,3511,3517; hw/ip/entropy_source/rtl/entropy_source.sv:737,747; hw/sys/sep/rtl/sep_trng.sv:110,118"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto
Toggle esrc_axil_isolated_resp.r.resp "logic esrc_axil_isolated_resp.r.resp[1:0]"
Toggle esrc_axil_isolated_resp.b.resp "logic esrc_axil_isolated_resp.b.resp[1:0]"

CHECKSUM: "3536466054 1976754700"
ANNOTATION: "SEP-DRBG-RESP-BIT0: drbg_axil64_lane_adapter returns AXI_RESP_OKAY, AXI_RESP_SLVERR or the axi_lite_to_tlul response, and axi_lite_to_tlul returns only 2'b00 or 2'b10, so resp bit 0 holds 0. hw/ip/drbg/rtl/drbg_axil64_lane_adapter.sv:44-45,112,158-159,214,229,250,280,258,287; hw/common/axi/axi_lite_to_tlul.sv:54-55,128-129,195,234"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto
Toggle csrng_axil_isolated_resp.r.resp [0] "logic csrng_axil_isolated_resp.r.resp[1:0]"
Toggle csrng_axil_isolated_resp.b.resp [0] "logic csrng_axil_isolated_resp.b.resp[1:0]"
Toggle edn_axil_isolated_resp.r.resp [0] "logic edn_axil_isolated_resp.r.resp[1:0]"
Toggle edn_axil_isolated_resp.b.resp [0] "logic edn_axil_isolated_resp.b.resp[1:0]"

CHECKSUM: "3536466054 1976754700"
ANNOTATION: "SEP-TLUL-RESP-BIT0: axi_lite_to_tlul returns only AXI_RESP_OKAY=2'b00 or AXI_RESP_SLVERR=2'b10, so resp bit 0 holds 0 (bit 1 is the reachable SLVERR and is not listed). hw/common/axi/axi_lite_to_tlul.sv:54-55,128-129,195,234"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto
Toggle otbn_axil_isolated_resp.r.resp [0] "logic otbn_axil_isolated_resp.r.resp[1:0]"
Toggle otbn_axil_isolated_resp.b.resp [0] "logic otbn_axil_isolated_resp.b.resp[1:0]"

CHECKSUM: "3536466054 1976754700"
ANNOTATION: "SEP-REGBLOCK-RESP-BIT0: the PeakRDL AXI4-Lite cpuif assigns s_axil_bresp/s_axil_rresp only 2'b10 or 2'b00, so bit 0 holds 0 (bit 1 is the reachable SLVERR of this error-decoding block and is not listed). hw/ip/key_manager/regs/gen/sv/abr_wrapper_key_reg.sv:209-215, otbn_wrapper_key_reg.sv:208-214, km_mailbox_sep_reg.sv:209-215; wired out at hw/sys/sep/rtl/sep_crypto_abr_wrapper.sv:227,239"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto
Toggle otbn_key_axil_isolated_resp.r.resp [0] "logic otbn_key_axil_isolated_resp.r.resp[1:0]"
Toggle otbn_key_axil_isolated_resp.b.resp [0] "logic otbn_key_axil_isolated_resp.b.resp[1:0]"
Toggle abr_key_axil_isolated_resp.r.resp [0] "logic abr_key_axil_isolated_resp.r.resp[1:0]"
Toggle abr_key_axil_isolated_resp.b.resp [0] "logic abr_key_axil_isolated_resp.b.resp[1:0]"

