// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//==================================================
// SEP VCS coverage exclusions -- structurally tied SEP DMA inputs.
// Format Version: 2
// ExclMode: default
//
// Scope: the cocotb VCS elaboration of sep_uvm_top, target `default`.
// Do not merge a `rom_boot` target run against this file.
//
// Every entry is forced by an RTL tie. Stimulus gaps stay in the denominator.
// Whole modules excluded by sep_cov_scope.hier do not appear here.
// Checksums come from `urg -dump full_exclusions tgl` on the merged VDB.
//==================================================

CHECKSUM: "2718539751 3972236298"

INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_dma_wrap
ANNOTATION: "SEP-DMA-LSIO-TIED: hw/sys/sep/rtl/sep.sv:1106 ties lsio_trigger[10:1] to zero; only bit 0 carries the SPI trigger (:1104). NOT waived: bit 0, which is a live peripheral request."
Toggle lsio_trigger_i [1] "logic lsio_trigger_i[10:0]"
Toggle lsio_trigger_i [2] "logic lsio_trigger_i[10:0]"
Toggle lsio_trigger_i [3] "logic lsio_trigger_i[10:0]"
Toggle lsio_trigger_i [4] "logic lsio_trigger_i[10:0]"
Toggle lsio_trigger_i [5] "logic lsio_trigger_i[10:0]"
Toggle lsio_trigger_i [6] "logic lsio_trigger_i[10:0]"
Toggle lsio_trigger_i [7] "logic lsio_trigger_i[10:0]"
Toggle lsio_trigger_i [8] "logic lsio_trigger_i[10:0]"
Toggle lsio_trigger_i [9] "logic lsio_trigger_i[10:0]"
Toggle lsio_trigger_i [10] "logic lsio_trigger_i[10:0]"
ANNOTATION: "SEP-DMA-CTN-TIED: the CTN TL-UL response is a constant in RTL. hw/sys/sep/rtl/sep_dma_wrap.sv:341-350 drives a_ready 1, d_valid 0, d_opcode ACCESS_ACK and every remaining field to zero, and the request side is unconnected at :160, so these bits cannot present a second value. NOT waived: the DMA's own host TL-UL port, which carries real traffic."
Toggle ctn_tl_d2h.a_ready "logic ctn_tl_d2h.a_ready"
Toggle ctn_tl_d2h.d_error "logic ctn_tl_d2h.d_error"
Toggle ctn_tl_d2h.d_user.data_intg "logic ctn_tl_d2h.d_user.data_intg[6:0]"
Toggle ctn_tl_d2h.d_user.rsp_intg "logic ctn_tl_d2h.d_user.rsp_intg[6:0]"
Toggle ctn_tl_d2h.d_data "logic ctn_tl_d2h.d_data[31:0]"
Toggle ctn_tl_d2h.d_sink "logic ctn_tl_d2h.d_sink[0:0]"
Toggle ctn_tl_d2h.d_source "logic ctn_tl_d2h.d_source[7:0]"
Toggle ctn_tl_d2h.d_size "logic ctn_tl_d2h.d_size[1:0]"
Toggle ctn_tl_d2h.d_param "logic ctn_tl_d2h.d_param[2:0]"
Toggle ctn_tl_d2h.d_opcode "logic ctn_tl_d2h.d_opcode[2:0]"
Toggle ctn_tl_d2h.d_valid "logic ctn_tl_d2h.d_valid"

CHECKSUM: "2718539751 3972236298"

INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_dma_wrap
ANNOTATION: "SEP-DMA-ALERT-PING-TIED: hw/sys/sep/rtl/sep_dma_wrap.sv:364 ties ping_req_i to 1'b0 on every alert receiver, so the ping wires of the receiver's rx struct cannot move. NOT waived: alert_p and ack_p, which move when the DMA actually raises an alert -- that is a fault-injection gap, not dead logic."
Toggle dma_alert_rx[0].ping_n "logic dma_alert_rx[0].ping_n"
Toggle dma_alert_rx[0].ping_p "logic dma_alert_rx[0].ping_p"
