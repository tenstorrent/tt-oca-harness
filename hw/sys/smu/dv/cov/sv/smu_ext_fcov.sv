// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU external-boundary functional coverage, from the SMU-EXT-SMN,
// SMU-MBOX-IRQ-OUT, SMU-SSRESET, SMU-EFUSE-SHIM-SMC and SMU-EFUSE-SHIM-SEP
// scenarios of the feature list: the SMN port ID widths, the mailbox
// interrupt vector, the eFuse bank-control AXI-Lite shims, and the outputs
// the chiplet presents to external systems; and smu_ext_in_error_cg of
// SMU_FCOV.adoc, the responder error codes at the outbound boundary.
//
// One passive, signal-driven module. Every port is a signal the bench
// exposes at its top level; the port
// widths come from the DUT packages, so a width point is unhittable when
// the bench's signal does not match them.
//
// A width point fires on activity through the port, a presence point at the
// event that first presents the output (primary release, fuse sense done);
// neither is true in the quiescent state. Presence is X-aware.
//
// SEP PRESENCE: the SEP eFuse shim points sit in the `g_sep` generate block,
// so a SEP=0 build carries no unhittable point and one coverage policy can
// grade both elaborations.
//
// LENGTH CLASS: smu_ext_in_error_cg classes an outbound burst by the AxLEN
// of its own address phase. Each ID keeps a FIFO of eight length classes,
// pushed at the AR (AW) accept and popped at R-last (B), so a beat takes the
// class of the oldest burst still open under its ID; the ext_out port sees
// at most a few bursts outstanding per ID. A push into a full FIFO is
// dropped, and the bursts after it then take the class of an older entry;
// a pop of an empty FIFO leaves it empty, and an empty FIFO classes a beat
// as single.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use. Every register
// carries a reset branch.

`include "ocah_fcov_macros.svh"

module smu_ext_fcov #(
  // 0 on an elaboration without SEP. The SEP eFuse bank-control shim is
  // driven from the SEP subsystem, so smu.sv's gen_no_sep branch ties the
  // request port to '0 and the bench ties the response pins off; the two
  // points on that shim are dropped rather than carried unhittable.
  parameter bit SEP_PRESENT = 1'b1
) (
  input wire clk_smu_i,
  input wire rst_cold_ni,
  input wire rst_primary_smc_clk_ni,
  input wire fuse_sense_done_i,

  // Inbound SMN AW handshake and ID; outbound SMN AW handshake and ID.
  input wire s_axi_awvalid_i,
  input wire s_axi_awready_i,
  input wire [7:0] s_axi_awid_i,
  input wire axi_out_aw_valid_i,
  input wire axi_out_aw_ready_i,
  input wire [9:0] axi_out_aw_id_i,

  // Inbound SMN AR and R handshakes, for the read that leaves an armed
  // responder inject unused.
  input wire s_axi_arvalid_i,
  input wire s_axi_arready_i,
  input wire s_axi_rvalid_i,
  input wire s_axi_rready_i,
  input wire s_axi_rlast_i,
  input wire [1:0] s_axi_rresp_i,

  // Outbound boundary interface (u_axi_out_if): every channel's handshake
  // with the ID, the length and the response code.
  input wire out_awvalid_i,
  input wire out_awready_i,
  input wire [15:0] out_awid_i,
  input wire [7:0] out_awlen_i,
  input wire out_bvalid_i,
  input wire out_bready_i,
  input wire [15:0] out_bid_i,
  input wire [1:0] out_bresp_i,
  input wire out_arvalid_i,
  input wire out_arready_i,
  input wire [15:0] out_arid_i,
  input wire [7:0] out_arlen_i,
  input wire out_rvalid_i,
  input wire out_rready_i,
  input wire [15:0] out_rid_i,
  input wire [1:0] out_rresp_i,
  input wire out_rlast_i,

  // Graded-window gate (tb_fcov_gate), driven by the owning leaf.
  input wire fcov_gate_i,

  // eFuse bank-control AXI-Lite shims at the SMU boundary, one per subsystem.
  input wire smc_efuse_bank_ctrl_awvalid_i,
  input wire smc_efuse_bank_ctrl_arvalid_i,
  input wire smc_efuse_bank_ctrl_bvalid_i,
  input wire smc_efuse_bank_ctrl_bready_i,
  input wire smc_efuse_bank_ctrl_rvalid_i,
  input wire smc_efuse_bank_ctrl_rready_i,
  input wire sep_efuse_bank_ctrl_awvalid_i,
  input wire sep_efuse_bank_ctrl_arvalid_i,
  input wire sep_efuse_bank_ctrl_bvalid_i,
  input wire sep_efuse_bank_ctrl_bready_i,
  input wire sep_efuse_bank_ctrl_rvalid_i,
  input wire sep_efuse_bank_ctrl_rready_i,

  // Outputs to external systems.
  input wire [smc_pkg::NumMailboxes-1:0] ext_mailbox_interrupts_i,
  input wire [31:0] ss_config_i,
  input smc_reset_unit_pkg::reset_ctrl_t ss_reset_ctrl_i[31:0],
  input smc_efuse_pkg::efuse_map_t smc_shadow_regs_i
);

  localparam int unsigned MbxMsb = smc_pkg::NumMailboxes - 1;

  wire in_reset = (rst_cold_ni !== 1'b1);

  wire smc_efuse_req = (smc_efuse_bank_ctrl_awvalid_i === 1'b1)
      || (smc_efuse_bank_ctrl_arvalid_i === 1'b1);

  logic primary_q, fuse_sense_q, mbx_msb_q;
  logic smc_efuse_req_q;
  always_ff @(posedge clk_smu_i) begin
    if (in_reset) begin
      primary_q <= 1'b0;
      fuse_sense_q <= 1'b0;
      mbx_msb_q <= 1'b0;
      smc_efuse_req_q <= 1'b0;
    end else begin
      primary_q <= rst_primary_smc_clk_ni;
      fuse_sense_q <= fuse_sense_done_i;
      mbx_msb_q <= ext_mailbox_interrupts_i[MbxMsb];
      smc_efuse_req_q <= smc_efuse_req;
    end
  end

  wire primary_rose_e = (rst_primary_smc_clk_ni === 1'b1) && (primary_q === 1'b0);
  wire fuse_sense_done_e = (fuse_sense_done_i === 1'b1) && (fuse_sense_q === 1'b0);

  // ------------------------------------------------------------------
  // SMN port ID widths, on the address handshake that carries the ID.
  // ------------------------------------------------------------------
  wire aw_in_accept_e = (s_axi_awvalid_i === 1'b1) && (s_axi_awready_i === 1'b1);
  wire aw_out_fire_e = (axi_out_aw_valid_i === 1'b1) && (axi_out_aw_ready_i === 1'b1);
  wire inbound_id_width_8_e = aw_in_accept_e && ($bits(s_axi_awid_i) == 8);
  `OCAH_FCOV_COVER(c_inbound_id_width_8, inbound_id_width_8_e, clk_smu_i, in_reset)
  // The 10-bit outbound ID is the SEP=0 converter path; with SEP present the
  // crossbar widens it.
  if (!SEP_PRESENT) begin : g_nosep
    wire outbound_id_width_10_e = aw_out_fire_e && ($bits(axi_out_aw_id_i) == 10);
    `OCAH_FCOV_COVER(c_outbound_id_width_10, outbound_id_width_10_e, clk_smu_i, in_reset)
  end

  // ------------------------------------------------------------------
  // Mailbox interrupt vector: its top bit, index NumMailboxes-1, rising.
  // ------------------------------------------------------------------
  wire mailbox_irq_out_width_32_e = (ext_mailbox_interrupts_i[MbxMsb] === 1'b1)
      && (mbx_msb_q === 1'b0) && (smc_pkg::NumMailboxes == 32);
  `OCAH_FCOV_COVER(c_mailbox_irq_out_width_32, mailbox_irq_out_width_32_e, clk_smu_i, in_reset)

  // ------------------------------------------------------------------
  // Subsystem reset-unit outputs at primary release; the eFuse shadow map
  // once the fuses have been sensed.
  // ------------------------------------------------------------------
  wire ss_reset_ctrl_array_32_e = primary_rose_e && ($size(ss_reset_ctrl_i) == 32)
      && !$isunknown(ss_reset_ctrl_i[0]) && !$isunknown(ss_reset_ctrl_i[31]);
  wire ss_config_present_e = primary_rose_e && !$isunknown(ss_config_i);
  wire smc_shadow_regs_present_e = fuse_sense_done_e && !$isunknown(smc_shadow_regs_i);
  `OCAH_FCOV_COVER(c_ss_reset_ctrl_array_32, ss_reset_ctrl_array_32_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_ss_config_present, ss_config_present_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_smc_shadow_regs_present, smc_shadow_regs_present_e, clk_smu_i, in_reset)

  // ------------------------------------------------------------------
  // eFuse bank-control shims: the request appearing at the boundary, and
  // the response coming back on the same AXI-Lite port.
  // ------------------------------------------------------------------
  wire smc_efuse_bank_ctrl_request_observed_e = smc_efuse_req && (smc_efuse_req_q === 1'b0);
  wire smc_efuse_bank_ctrl_response_returned_e =
      ((smc_efuse_bank_ctrl_bvalid_i === 1'b1) && (smc_efuse_bank_ctrl_bready_i === 1'b1))
      || ((smc_efuse_bank_ctrl_rvalid_i === 1'b1) && (smc_efuse_bank_ctrl_rready_i === 1'b1));
  `OCAH_FCOV_COVER(c_smc_efuse_bank_ctrl_request_observed, smc_efuse_bank_ctrl_request_observed_e,
                   clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_smc_efuse_bank_ctrl_response_returned,
                   smc_efuse_bank_ctrl_response_returned_e, clk_smu_i, in_reset)

  // The SEP-side shim, observed the same way. Only elaborated with SEP
  // present: the request port is tied to '0 without it, so nothing is ever
  // launched and nothing comes back.
  if (SEP_PRESENT) begin : g_sep
    wire sep_efuse_req = (sep_efuse_bank_ctrl_awvalid_i === 1'b1)
        || (sep_efuse_bank_ctrl_arvalid_i === 1'b1);

    logic sep_efuse_req_q;
    always_ff @(posedge clk_smu_i) begin
      if (in_reset) sep_efuse_req_q <= 1'b0;
      else sep_efuse_req_q <= sep_efuse_req;
    end

    wire sep_efuse_bank_ctrl_request_observed_e = sep_efuse_req && (sep_efuse_req_q === 1'b0);
    wire sep_efuse_bank_ctrl_response_returned_e =
        ((sep_efuse_bank_ctrl_bvalid_i === 1'b1) && (sep_efuse_bank_ctrl_bready_i === 1'b1))
        || ((sep_efuse_bank_ctrl_rvalid_i === 1'b1) && (sep_efuse_bank_ctrl_rready_i === 1'b1));
    `OCAH_FCOV_COVER(c_sep_efuse_bank_ctrl_request_observed, sep_efuse_bank_ctrl_request_observed_e,
                     clk_smu_i, in_reset)
    `OCAH_FCOV_COVER(c_sep_efuse_bank_ctrl_response_returned,
                     sep_efuse_bank_ctrl_response_returned_e, clk_smu_i, in_reset)
  end

  // ------------------------------------------------------------------
  // Covergroup: the ID values carried on each port.
  // ------------------------------------------------------------------
  covergroup cg_smn_ids with function sample (logic [7:0] in_id, logic [9:0] out_id);
    option.per_instance = 1;
    cp_in_id: coverpoint in_id {bins zero = {8'h00}; bins max = {8'hff}; bins other = default;}
    // The crossbar prefixes each outbound ID with its 2-bit slave-port index.
    // ext_out is reachable from sep_out (index 0) and smc_out (index 1) only,
    // so an outbound ID above 10'h1ff never appears on this port.
    cp_out_id: coverpoint out_id {
      bins from_sep = {[10'h000 : 10'h0ff]};
      bins from_smc = {[10'h100 : 10'h1ff]};
      ignore_bins unrouted_ports = {[10'h200 : 10'h3ff]};
    }
  endgroup

  cg_smn_ids u_cg_smn_ids = new();

  always_ff @(posedge clk_smu_i) begin
    if (!in_reset && (aw_in_accept_e || aw_out_fire_e)) begin
      u_cg_smn_ids.sample(s_axi_awid_i, axi_out_aw_id_i);
    end
  end

  // ------------------------------------------------------------------
  // smu_ext_in_error_cg (SMU_FCOV.adoc, smu_ext_in_error_cg): the error
  // code the responder returns on each read beat class and on the write of
  // each initiator class, and the recovery of the next access, inside the
  // owner's graded window. The initiator is the AxID prefix of cg_smn_ids
  // (from_sep 0x000-0x0ff, from_smc 0x100-0x1ff) with the length of the
  // address phase: the bridge issues single beats, the iDMA copy bursts.
  // The length class of each open read and write is kept per ID in a FIFO
  // (LENGTH CLASS above) and the beat index of each read per ID; the beat
  // index and the burst's error flag restart at each R-last, so reads the
  // iDMA queues under one ID, whose beats return in order, are classed burst
  // by burst.
  // ------------------------------------------------------------------
  localparam logic [1:0] RespOkay = 2'b00;
  localparam logic [1:0] RespSlverr = 2'b10;
  localparam logic [1:0] RespDecerr = 2'b11;
  localparam logic [1:0] PrefixFromSep = 2'b00;
  localparam logic [1:0] PrefixFromSmc = 2'b01;

  wire gate_on = (fcov_gate_i === 1'b1);
  wire out_aw_acc = (out_awvalid_i === 1'b1) && (out_awready_i === 1'b1);
  wire out_ar_acc = (out_arvalid_i === 1'b1) && (out_arready_i === 1'b1);
  wire out_b_acc = (out_bvalid_i === 1'b1) && (out_bready_i === 1'b1);
  wire out_r_acc = (out_rvalid_i === 1'b1) && (out_rready_i === 1'b1);
  wire out_r_last_acc = out_r_acc && (out_rlast_i === 1'b1);
  wire out_b_err = out_b_acc && ((out_bresp_i === RespSlverr) || (out_bresp_i === RespDecerr));
  wire out_r_err = out_r_acc && ((out_rresp_i === RespSlverr) || (out_rresp_i === RespDecerr));

  // A length-class FIFO is {count, entries}; entry 0 is the oldest open
  // burst and holds 1 for a burst of more than one beat.
  localparam int unsigned LenFifoDepth = 8;
  localparam int unsigned LenCntBits = $clog2(LenFifoDepth + 1);
  localparam int unsigned LenFifoBits = LenCntBits + LenFifoDepth;
  localparam int unsigned LenIdxBits = $clog2(LenFifoDepth);

  // One cycle of a FIFO: the pop first, then the push.
  function automatic logic [LenFifoBits-1:0] len_fifo_step(
      input logic [LenFifoBits-1:0] fifo, input logic pop, input logic push, input logic multi);
    logic [LenFifoDepth-1:0] entries;
    logic [LenCntBits-1:0] count;
    entries = fifo[LenFifoDepth-1:0];
    count = fifo[LenFifoBits-1:LenFifoDepth];
    if (pop && (count != '0)) begin
      entries = entries >> 1;
      count = count - LenCntBits'(1);
    end
    if (push && (count < LenCntBits'(LenFifoDepth))) begin
      entries[count[LenIdxBits-1:0]] = multi;
      count = count + LenCntBits'(1);
    end
    return {count, entries};
  endfunction

  logic [LenFifoBits-1:0] aw_len_q[1024];
  logic [LenFifoBits-1:0] ar_len_q[1024];
  wire aw_same_id = out_aw_acc && out_b_acc && (out_awid_i[9:0] == out_bid_i[9:0]);
  wire ar_same_id = out_ar_acc && out_r_last_acc && (out_arid_i[9:0] == out_rid_i[9:0]);
  wire [LenFifoBits-1:0] aw_len_push = len_fifo_step(aw_len_q[out_awid_i[9:0]], aw_same_id,
                                                     1'b1, out_awlen_i != 8'd0);
  wire [LenFifoBits-1:0] ar_len_push = len_fifo_step(ar_len_q[out_arid_i[9:0]], ar_same_id,
                                                     1'b1, out_arlen_i != 8'd0);
  wire [LenFifoBits-1:0] b_len_pop = len_fifo_step(aw_len_q[out_bid_i[9:0]], 1'b1, 1'b0, 1'b0);
  wire [LenFifoBits-1:0] r_len_pop = len_fifo_step(ar_len_q[out_rid_i[9:0]], 1'b1, 1'b0, 1'b0);
  always_ff @(posedge clk_smu_i) begin
    if (in_reset) begin
      for (int unsigned i = 0; i < 1024; i++) begin
        aw_len_q[i] <= '0;
        ar_len_q[i] <= '0;
      end
    end else begin
      if (out_aw_acc) aw_len_q[out_awid_i[9:0]] <= aw_len_push;
      if (out_b_acc && !aw_same_id) aw_len_q[out_bid_i[9:0]] <= b_len_pop;
      if (out_ar_acc) ar_len_q[out_arid_i[9:0]] <= ar_len_push;
      if (out_r_last_acc && !ar_same_id) ar_len_q[out_rid_i[9:0]] <= r_len_pop;
    end
  end

  logic [7:0] r_beat_q[1024];
  logic r_burst_err_q[1024];
  always_ff @(posedge clk_smu_i) begin
    if (in_reset) begin
      for (int unsigned i = 0; i < 1024; i++) begin
        r_beat_q[i] <= '0;
        r_burst_err_q[i] <= 1'b0;
      end
    end else begin
      if (out_r_acc) begin
        r_beat_q[out_rid_i[9:0]] <= (out_rlast_i === 1'b1) ? 8'd0 : r_beat_q[out_rid_i[9:0]] + 8'd1;
        if (out_rlast_i === 1'b1) r_burst_err_q[out_rid_i[9:0]] <= 1'b0;
        else if (out_r_err) r_burst_err_q[out_rid_i[9:0]] <= 1'b1;
      end
    end
  end

  // Read beat classes: single beat by the bridge, single beat by the SEP
  // system bus, first, middle, last beat of an iDMA burst.
  function automatic logic [2:0] read_beat_class(input logic [15:0] id, input logic last);
    if (id[9:8] == PrefixFromSep) return 3'd1;
    if (!ar_len_q[id[9:0]][0]) return 3'd0;
    if (r_beat_q[id[9:0]] == 8'd0) return 3'd2;
    if (last) return 3'd4;
    return 3'd3;
  endfunction

  // Write initiator classes: the bridge, the SEP system bus, an iDMA burst.
  function automatic logic [2:0] write_initiator_class(input logic [15:0] id);
    if (id[9:8] == PrefixFromSep) return 3'd1;
    return aw_len_q[id[9:0]][0] ? 3'd2 : 3'd0;
  endfunction

  function automatic logic resp_code(input logic [1:0] resp);
    return resp == RespDecerr;
  endfunction

  // The last errored completion, until the next completed access answers.
  // A read completes at its last beat, with the code of the beat that
  // carried the error; a write at its one B.
  logic err_pending_q, err_code_q, err_dir_q;
  logic [1:0] r_last_code_q[1024];
  always_ff @(posedge clk_smu_i) begin
    if (in_reset) begin
      for (int unsigned i = 0; i < 1024; i++) r_last_code_q[i] <= RespOkay;
    end else if (out_r_err) begin
      r_last_code_q[out_rid_i[9:0]] <= out_rresp_i;
    end
  end

  wire read_completed_err = out_r_last_acc && (out_r_err || r_burst_err_q[out_rid_i[9:0]]);
  wire read_completed_okay = out_r_last_acc && !out_r_err && !r_burst_err_q[out_rid_i[9:0]];
  wire write_completed_okay = out_b_acc && (out_bresp_i === RespOkay);
  wire [1:0] read_err_code = out_r_err ? out_rresp_i : r_last_code_q[out_rid_i[9:0]];
  wire recovery_e = err_pending_q && (read_completed_okay || write_completed_okay);

  always_ff @(posedge clk_smu_i) begin
    if (in_reset) begin
      err_pending_q <= 1'b0;
      err_code_q <= 1'b0;
      err_dir_q <= 1'b0;
    end else if (out_b_err) begin
      err_pending_q <= 1'b1;
      err_code_q <= resp_code(out_bresp_i);
      err_dir_q <= 1'b1;
    end else if (read_completed_err) begin
      err_pending_q <= 1'b1;
      err_code_q <= resp_code(read_err_code);
      err_dir_q <= 1'b0;
    end else if (recovery_e) begin
      err_pending_q <= 1'b0;
    end
  end

  // An inbound read answered DECERR with no address phase on u_axi_out_if
  // between its AR accept and its R-last accept leaves the armed read inject
  // unused; the next read completed on u_axi_out_if, the bridge's single
  // beat at the armed word, consumes it. The cell is sampled at that beat:
  // SLVERR or DECERR on an SMC-prefixed single-beat read.
  wire in_ar_acc = (s_axi_arvalid_i === 1'b1) && (s_axi_arready_i === 1'b1);
  wire in_r_last_acc = (s_axi_rvalid_i === 1'b1) && (s_axi_rready_i === 1'b1)
      && (s_axi_rlast_i === 1'b1);
  logic in_read_open_q, out_since_in_q;
  always_ff @(posedge clk_smu_i) begin
    if (in_reset) begin
      in_read_open_q <= 1'b0;
      out_since_in_q <= 1'b0;
    end else begin
      if (in_ar_acc) begin
        in_read_open_q <= 1'b1;
        out_since_in_q <= 1'b0;
      end else if (in_r_last_acc) begin
        in_read_open_q <= 1'b0;
      end else if (out_aw_acc || out_ar_acc) begin
        out_since_in_q <= 1'b1;
      end
    end
  end
  wire in_read_unused_e = in_r_last_acc && in_read_open_q && !out_since_in_q
      && (s_axi_rresp_i === RespDecerr) && !(out_aw_acc || out_ar_acc);
  logic hook_left_q;
  always_ff @(posedge clk_smu_i) begin
    if (in_reset) hook_left_q <= 1'b0;
    else if (in_read_unused_e) hook_left_q <= 1'b1;
    else if (out_r_last_acc) hook_left_q <= 1'b0;
  end
  wire hook_unused_e = hook_left_q && out_r_err && (out_rlast_i === 1'b1)
      && !ar_len_q[out_rid_i[9:0]][0] && (out_rid_i[9:8] == PrefixFromSmc);

  // cp_inject is {direction, code, class}: direction 0 read with the beat
  // class, 1 write with the initiator class; code 0 SLVERR, 1 DECERR. OKAY
  // and EXOKAY responses sample nothing. cp_recovery is {kind, code,
  // direction}: kind 0 the next completed access answering OKAY after an
  // errored one, with that one's code and direction; kind 1 the unused hook.
  covergroup smu_ext_in_error_cg with function sample (
      logic dir, logic code, logic [2:0] cls, logic kind, logic rcode, logic rdir
  );
    option.per_instance = 1;
    cp_inject: coverpoint {
      dir, code, cls
    } {
      bins read_slverr_bridge_single = {5'b0_0_000};
      bins read_slverr_sep_single = {5'b0_0_001};
      bins read_slverr_idma_first = {5'b0_0_010};
      bins read_slverr_idma_middle = {5'b0_0_011};
      bins read_slverr_idma_last = {5'b0_0_100};
      bins read_decerr_bridge_single = {5'b0_1_000};
      bins read_decerr_sep_single = {5'b0_1_001};
      bins read_decerr_idma_first = {5'b0_1_010};
      bins read_decerr_idma_middle = {5'b0_1_011};
      bins read_decerr_idma_last = {5'b0_1_100};
      bins write_slverr_bridge = {5'b1_0_000};
      bins write_slverr_sep = {5'b1_0_001};
      bins write_slverr_idma_burst = {5'b1_0_010};
      bins write_decerr_bridge = {5'b1_1_000};
      bins write_decerr_sep = {5'b1_1_001};
      bins write_decerr_idma_burst = {5'b1_1_010};
    }
    cp_recovery: coverpoint {
      kind, rcode, rdir
    } {
      bins slverr_read_then_okay = {3'b0_0_0};
      bins slverr_write_then_okay = {3'b0_0_1};
      bins decerr_read_then_okay = {3'b0_1_0};
      bins decerr_write_then_okay = {3'b0_1_1};
      bins hook_unused_by_ext_in_read = {3'b1_0_0};
    }
  endgroup

  smu_ext_in_error_cg u_cg_ext_in_error = new();

  // Each sample fills one coverpoint and hands the other a value no bin
  // lists (class 7 for cp_inject, kind 1 with code 1 for cp_recovery).
  always_ff @(posedge clk_smu_i) begin
    if (!in_reset && gate_on) begin
      if (out_r_err) begin
        u_cg_ext_in_error.sample(1'b0, resp_code(out_rresp_i), read_beat_class(
                                 out_rid_i, out_rlast_i === 1'b1), 1'b1, 1'b1, 1'b1);
      end
      if (out_b_err) begin
        u_cg_ext_in_error.sample(1'b1, resp_code(out_bresp_i), write_initiator_class(out_bid_i),
                                 1'b1, 1'b1, 1'b1);
      end
      if (recovery_e) u_cg_ext_in_error.sample(1'b0, 1'b0, 3'd7, 1'b0, err_code_q, err_dir_q);
      if (hook_unused_e) u_cg_ext_in_error.sample(1'b0, 1'b0, 3'd7, 1'b1, 1'b0, 1'b0);
    end
  end

endmodule : smu_ext_fcov
