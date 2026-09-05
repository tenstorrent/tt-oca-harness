// Copyright 2023 ETH Zurich and University of Bologna.
// Solderpad Hardware License, Version 0.51, see LICENSE for details.
// SPDX-License-Identifier: SHL-0.51

// Authors:
// - Michael Rogenmoser <michaero@iis.ee.ethz.ch>
// - Thomas Benz <tbenz@iis.ee.ethz.ch>

/// Description: Register-based front-end for iDMA
module idma_${identifier} #(
  /// Number of configuration register ports
  parameter int unsigned NumRegs        = 32'd1,
  /// Number of streams (max 16)
  parameter int unsigned NumStreams     = 32'd1,
  /// Width of the transfer id (max 32-bit)
  parameter int unsigned IdCounterWidth = 32'd32,
  /// Dependent parameter: Stream Idx
  parameter int unsigned StreamWidth    = cf_math_pkg::idx_width(NumStreams),
  /// Register_interface request type
  parameter type         reg_req_t      = logic,
  /// Register_interface response type
  parameter type         reg_rsp_t      = logic,
  /// DMA 1d or ND burst request type
  parameter type         dma_req_t      = logic,
  /// Dependent type for IdCounterWidth
  parameter type         cnt_width_t    = logic [IdCounterWidth-1:0],
  /// Dependent type for StreamWidth
  parameter type         stream_t       = logic [StreamWidth-1:0]
) (
  input  logic clk_i,
  input  logic rst_ni,
  /// Register interface control slave
  input  reg_req_t [NumRegs-1:0] dma_ctrl_req_i,
  output reg_rsp_t [NumRegs-1:0] dma_ctrl_rsp_o,
  /// Request signals
  output dma_req_t   dma_req_o,
  output logic       req_valid_o,
  input  logic       req_ready_i,
  input  cnt_width_t next_id_i,
  output stream_t    stream_idx_o,
  /// Status signals
  input  cnt_width_t           [NumStreams-1:0] done_id_i,
  input  idma_pkg::idma_busy_t [NumStreams-1:0] busy_i,
  input  logic                 [NumStreams-1:0] midend_busy_i
);

  /// Maximum number of streams is set to 16. It can be enlarged, but the register file
  /// needs to be adapted too.
  localparam int unsigned MaxNumStreams = 32'd16;

  // register connections
  idma_${identifier}_reg_pkg::idma_${identifier}_reg2hw_t [NumRegs-1:0] dma_reg2hw;
  idma_${identifier}_reg_pkg::idma_${identifier}_hw2reg_t [NumRegs-1:0] dma_hw2reg;

  // arbitration output
  dma_req_t [NumRegs-1:0] arb_dma_req;
  logic     [NumRegs-1:0] arb_valid;
  logic     [NumRegs-1:0] arb_ready;

  // register signals
  reg_rsp_t [NumRegs-1:0] dma_ctrl_rsp;

  always_comb begin
      stream_idx_o = '0;
      for (int r = 0; r < NumRegs; r++) begin
          for (int c = 0; c < NumStreams; c++) begin
          end
      end
  end

  // generate the registers
  for (genvar i = 0; i < NumRegs; i++) begin : gen_core_regs

    idma_${identifier}_reg_top #(
      .reg_req_t ( reg_req_t ),
      .reg_rsp_t ( reg_rsp_t )
    ) i_idma_${identifier}_reg_top (
      .clk_i,
      .rst_ni,
      .reg_req_i ( dma_ctrl_req_i   [i] ),
      .reg_rsp_o ( dma_ctrl_rsp     [i] ),
      .reg2hw    ( dma_reg2hw       [i] ),
      .hw2reg    ( dma_hw2reg       [i] ),
      .devmode_i ( 1'b0                 )
    );

    logic read_happens;
    // DMA backpressure
    always_comb begin : proc_dma_backpressure
      // ready signal
      dma_ctrl_rsp_o[i]       = dma_ctrl_rsp[i];
      //Two cases for setting ready:
      // 1. Reading next_id: Detected by read_happens == 1 and use the backpressure from arbiter
      //        read_happens && arb_ready[i] ()
      // 2. Reading or writing to other registers Detected by read_happens == 0 and respond immediately on receiving a request
      //        dma_ctrl_req_i[i].valid && ~read_happens
      dma_ctrl_rsp_o[i].ready =  ( read_happens && arb_ready[i] || ~read_happens && dma_ctrl_req_i[i].valid ) ;
    end

    logic [MaxNumStreams-1:0] next_id_re_temp;
    assign next_id_re_temp[0] = dma_reg2hw[i].next_id_0.re;
    assign next_id_re_temp[1] = dma_reg2hw[i].next_id_1.re;
    assign next_id_re_temp[2] = dma_reg2hw[i].next_id_2.re;
    assign next_id_re_temp[3] = dma_reg2hw[i].next_id_3.re;
    assign next_id_re_temp[4] = dma_reg2hw[i].next_id_4.re;
    assign next_id_re_temp[5] = dma_reg2hw[i].next_id_5.re;
    assign next_id_re_temp[6] = dma_reg2hw[i].next_id_6.re;
    assign next_id_re_temp[7] = dma_reg2hw[i].next_id_7.re;
    assign next_id_re_temp[8] = dma_reg2hw[i].next_id_8.re;
    assign next_id_re_temp[9] = dma_reg2hw[i].next_id_9.re;
    assign next_id_re_temp[10] = dma_reg2hw[i].next_id_10.re;
    assign next_id_re_temp[11] = dma_reg2hw[i].next_id_11.re;
    assign next_id_re_temp[12] = dma_reg2hw[i].next_id_12.re;
    assign next_id_re_temp[13] = dma_reg2hw[i].next_id_13.re;
    assign next_id_re_temp[14] = dma_reg2hw[i].next_id_14.re;
    assign next_id_re_temp[15] = dma_reg2hw[i].next_id_15.re;

    // valid signals

    always_comb begin : proc_launch
        read_happens = 1'b0;
        for (int c = 0; c < NumStreams; c++) begin
            read_happens |= next_id_re_temp[c];
            if (next_id_re_temp[c]) begin
                stream_idx_o = stream_t'(c);
            end
        end
        arb_valid[i] = read_happens;
    end

    // assign request struct
    always_comb begin : proc_hw_req_conv
      // all fields are zero per default
      arb_dma_req[i] = '0;

      // address and length
% if bit_width == '32':
      arb_dma_req[i]${sep}length   = dma_reg2hw[i].length_low.q;
      arb_dma_req[i]${sep}src_addr = dma_reg2hw[i].src_addr_low.q;
      arb_dma_req[i]${sep}dst_addr = dma_reg2hw[i].dst_addr_low.q;
% else:
      arb_dma_req[i]${sep}length   = $bits(arb_dma_req[i]${sep}length)'(
          {dma_reg2hw[i].length_high.q, dma_reg2hw[i].length_low.q});
      arb_dma_req[i]${sep}src_addr = $bits(arb_dma_req[i]${sep}src_addr)'(
          {dma_reg2hw[i].src_addr_high.q, dma_reg2hw[i].src_addr_low.q});
      arb_dma_req[i]${sep}dst_addr = $bits(arb_dma_req[i]${sep}dst_addr)'(
          {dma_reg2hw[i].dst_addr_high.q, dma_reg2hw[i].dst_addr_low.q});
% endif

      // Protocols
      arb_dma_req[i]${sep}opt.src_protocol = idma_pkg::protocol_e'(dma_reg2hw[i].conf.src_protocol);
      arb_dma_req[i]${sep}opt.dst_protocol = idma_pkg::protocol_e'(dma_reg2hw[i].conf.dst_protocol);

      // Current backend only supports incremental burst
      arb_dma_req[i]${sep}opt.src.burst = axi_pkg::BURST_INCR;
      arb_dma_req[i]${sep}opt.dst.burst = axi_pkg::BURST_INCR;
        // this frontend currently does not support cache variations
      arb_dma_req[i]${sep}opt.src.cache = axi_pkg::CACHE_MODIFIABLE;
      arb_dma_req[i]${sep}opt.dst.cache = axi_pkg::CACHE_MODIFIABLE;

      // Backend options
      arb_dma_req[i]${sep}opt.beo.decouple_aw    = dma_reg2hw[i].conf.decouple_aw.q;
      arb_dma_req[i]${sep}opt.beo.decouple_rw    = dma_reg2hw[i].conf.decouple_rw.q;
      arb_dma_req[i]${sep}opt.beo.src_max_llen   = dma_reg2hw[i].conf.src_max_llen.q;
      arb_dma_req[i]${sep}opt.beo.dst_max_llen   = dma_reg2hw[i].conf.dst_max_llen.q;
      arb_dma_req[i]${sep}opt.beo.src_reduce_len = dma_reg2hw[i].conf.src_reduce_len.q;
      arb_dma_req[i]${sep}opt.beo.dst_reduce_len = dma_reg2hw[i].conf.dst_reduce_len.q;

% if num_dim != 1:
      // ND connections
% for nd in range(0, num_dim-1):
% if bit_width == '32':
      arb_dma_req[i].d_req[${nd}].reps = dma_reg2hw[i].reps_${nd+2}_low.q;
      arb_dma_req[i].d_req[${nd}].src_strides = dma_reg2hw[i].src_stride_${nd+2}_low.q;
      arb_dma_req[i].d_req[${nd}].dst_strides = dma_reg2hw[i].dst_stride_${nd+2}_low.q;
% else:
      arb_dma_req[i].d_req[${nd}].reps =
          $bits(arb_dma_req[i].d_req[${nd}].reps)'(
              {dma_reg2hw[i].reps_${nd+2}_high.q, dma_reg2hw[i].reps_${nd+2}_low.q});
      arb_dma_req[i].d_req[${nd}].src_strides =
          $bits(arb_dma_req[i].d_req[${nd}].src_strides)'(
              {dma_reg2hw[i].src_stride_${nd+2}_high.q,
               dma_reg2hw[i].src_stride_${nd+2}_low.q});
      arb_dma_req[i].d_req[${nd}].dst_strides =
          $bits(arb_dma_req[i].d_req[${nd}].dst_strides)'(
              {dma_reg2hw[i].dst_stride_${nd+2}_high.q,
               dma_reg2hw[i].dst_stride_${nd+2}_low.q});
% endif
% endfor

      // Disable higher dimensions
      if ( dma_reg2hw[i].conf.enable_nd.q == 0) begin
% for nd in range(0, num_dim-1):
        arb_dma_req[i].d_req[${nd}].reps = ${"'0" if nd != num_dim-2 else "'d1"};
% endfor
      end
% for nd in range(1, num_dim-1):
      else if ( dma_reg2hw[i].conf.enable_nd.q == ${nd}) begin
% for snd in range(nd, num_dim-1):
        arb_dma_req[i].d_req[${snd}].reps = 'd1;
% endfor
      end
% endfor
% endif
    end

    cnt_width_t [MaxNumStreams-1:0] next_id_temp;
    // observational registers
    for (genvar c = 0; c < NumStreams; c++) begin : gen_hw2reg_connections
        assign dma_hw2reg[i].status[c] =
            $bits(dma_hw2reg[i].status[c])'({midend_busy_i[c], busy_i[c]});
        assign next_id_temp[c] = next_id_i;
        assign dma_hw2reg[i].done_id[c] = done_id_i[c];
    end

    // tie-off unused channels
    for (genvar c = NumStreams; c < MaxNumStreams; c++) begin : gen_hw2reg_unused
        assign dma_hw2reg[i].status[c]  = '0;
        assign next_id_temp[c] = '0;
        assign dma_hw2reg[i].done_id[c] = '0;
    end

    assign dma_hw2reg[i].next_id_0 = next_id_temp[0];
    assign dma_hw2reg[i].next_id_1 = next_id_temp[1];
    assign dma_hw2reg[i].next_id_2 = next_id_temp[2];
    assign dma_hw2reg[i].next_id_3 = next_id_temp[3];
    assign dma_hw2reg[i].next_id_4 = next_id_temp[4];
    assign dma_hw2reg[i].next_id_5 = next_id_temp[5];
    assign dma_hw2reg[i].next_id_6 = next_id_temp[6];
    assign dma_hw2reg[i].next_id_7 = next_id_temp[7];
    assign dma_hw2reg[i].next_id_8 = next_id_temp[8];
    assign dma_hw2reg[i].next_id_9 = next_id_temp[9];
    assign dma_hw2reg[i].next_id_10 = next_id_temp[10];
    assign dma_hw2reg[i].next_id_11 = next_id_temp[11];
    assign dma_hw2reg[i].next_id_12 = next_id_temp[12];
    assign dma_hw2reg[i].next_id_13 = next_id_temp[13];
    assign dma_hw2reg[i].next_id_14 = next_id_temp[14];
    assign dma_hw2reg[i].next_id_15 = next_id_temp[15];

  end

  // arbitration
  rr_arb_tree #(
    .NumIn     ( NumRegs   ),
    .DataType  ( dma_req_t ),
    .ExtPrio   ( 0         ),
    .AxiVldRdy ( 1         ),
    .LockIn    ( 1         )
  ) i_rr_arb_tree (
    .clk_i,
    .rst_ni,
    .flush_i ( 1'b0        ),
    .rr_i    ( '0          ),
    .req_i   ( arb_valid   ),
    .gnt_o   ( arb_ready   ),
    .data_i  ( arb_dma_req ),
    .gnt_i   ( req_ready_i ),
    .req_o   ( req_valid_o ),
    .data_o  ( dma_req_o   ),
    .idx_o   ( /* NC */    )
  );

endmodule
