// Copyright 2023 ETH Zurich and University of Bologna.
// Solderpad Hardware License, Version 0.51, see LICENSE for details.
// SPDX-License-Identifier: SHL-0.51

// Author: Michael Rogenmoser <michaero@iis.ee.ethz.ch>

/// Bare bus error unit without register port
module bus_err_unit_bare #(
  parameter int unsigned AddrWidth       = 48,
  parameter int unsigned MetaDataWidth   = 1,
  parameter int unsigned ErrBits         = 3,
  parameter int unsigned NumOutstanding  = 4,
  parameter int unsigned NumStoredErrors = 4,
  parameter int unsigned NumReqPorts     = 1,
  parameter int unsigned NumChannels     = 1, // Channels are one-hot!
  parameter bit          DropOldest      = 1'b0
) (
  input  logic                                      clk_i,
  input  logic                                      rst_ni,
  input  logic                                      testmode_i,

  input  logic [NumReqPorts-1:0][  NumChannels-1:0] req_hs_valid_i,
  input  logic [NumReqPorts-1:0][    AddrWidth-1:0] req_addr_i,
  input  logic [NumReqPorts-1:0][MetaDataWidth-1:0] req_meta_i,
  input  logic                  [  NumChannels-1:0] rsp_hs_valid_i,
  input  logic                  [  NumChannels-1:0] rsp_burst_last_i,
  input  logic                  [      ErrBits-1:0] rsp_err_i,

  output logic                                      err_irq_o,

  input  logic                                      err_fifo_pop_i,
  output logic                  [      ErrBits-1:0] err_code_o,
  output logic                  [    AddrWidth-1:0] err_addr_o,
  output logic                  [MetaDataWidth-1:0] err_meta_o,
  output logic                                      err_fifo_overflow_o
);
  `ifndef SYNTHESIS
    for (genvar i = 0; i < NumReqPorts; i++) begin : gen_check_onehot
      assert final ($onehot0(req_hs_valid_i[i])) else $fatal(1, "Bus Error unit requires one-hot!");
    end
    assert final ($onehot0(rsp_hs_valid_i)) else $fatal(1, "Bus Error unit requires one-hot!");
  `endif

  typedef struct packed {
    logic [      ErrBits-1:0] err;
    logic [    AddrWidth-1:0] addr;
    logic [MetaDataWidth-1:0] meta;
  } err_addr_t;

  logic [NumChannels-1:0][    AddrWidth-1:0] err_addr;
  logic [NumChannels-1:0][MetaDataWidth-1:0] err_meta;
  logic [NumChannels-1:0]                    addr_fifo_dead;
  err_addr_t read_err_addr;
  logic bus_unit_full;
  logic err_fifo_empty;
  logic err_fifo_overflow_d, err_fifo_overflow_q;

  assign err_irq_o = ~err_fifo_empty;

  for (genvar i = 0; i < NumChannels; i++) begin : gen_addr_fifo
    logic addr_fifo_full;
    logic addr_fifo_push;
    logic [NumReqPorts-1:0]                         req_port_onehot;
    logic [cf_math_pkg::idx_width(NumReqPorts)-1:0] req_port_idx;

    for (genvar j = 0; j < NumReqPorts; j++) begin : gen_req_port_onehot
      assign req_port_onehot[j] = req_hs_valid_i[j][i];
    end

    onehot_to_bin #(
      .ONEHOT_WIDTH(NumReqPorts)
    ) i_req_port_select (
      .onehot(req_port_onehot),
      .bin   (req_port_idx)
    );

    assign addr_fifo_push = |req_port_onehot & ~addr_fifo_full & ~addr_fifo_dead[i];

    `ifndef SYNTHESIS
      full_write : assert property(
          @(posedge clk_i) disable iff (~rst_ni) (addr_fifo_full |-> ~|req_port_onehot))
          else $warning("Bus Error Unit exceeded number of outstanding transactions, please tune appropriately.");
    `endif

    always_ff @(posedge clk_i or negedge rst_ni) begin : proc_addr_fifo_dead
      if(~rst_ni) begin
        addr_fifo_dead[i] <= '0;
      end else begin
        if (|req_port_onehot & addr_fifo_full) begin
          addr_fifo_dead[i] <= 1'b1;
        end
      end
    end

    fifo_v3 #(
      .FALL_THROUGH ( 1'b0                    ),
      .DATA_WIDTH   ( AddrWidth+MetaDataWidth ),
      .DEPTH        ( NumOutstanding          )
    ) i_addr_fifo (
      .clk_i,
      .rst_ni,
      .flush_i   (1'b0),
      .testmode_i(testmode_i),
      .full_o    (addr_fifo_full),
      .empty_o   (),
      .usage_o   (),
      .data_i    ({req_addr_i[req_port_idx], req_meta_i[req_port_idx]}),
      .push_i    (addr_fifo_push),
      .data_o    ({err_addr[i], err_meta[i]}),
      .pop_i     (rsp_burst_last_i[i] & ~addr_fifo_dead[i])
    );
  end

  logic [cf_math_pkg::idx_width(NumChannels)-1:0] chan_select;

  onehot_to_bin #(
    .ONEHOT_WIDTH(NumChannels)
  ) i_rsp_chan_select (
    .onehot(rsp_hs_valid_i),
    .bin   (chan_select)
  );

  logic bus_err;
  logic push_err_fifo, pop_err_fifo;
  err_addr_t fifo_data;

  assign bus_err = (|rsp_hs_valid_i) & (|rsp_err_i);
  assign push_err_fifo = bus_err & (DropOldest | ~bus_unit_full);
  assign pop_err_fifo  = (err_fifo_pop_i & ~err_fifo_empty) | (DropOldest & bus_unit_full);

  assign fifo_data = '{err:  rsp_err_i,
                       addr: addr_fifo_dead[chan_select] ? '0 : err_addr[chan_select],
                       meta: addr_fifo_dead[chan_select] ? '0 : err_meta[chan_select]};

  always_ff @(posedge clk_i or negedge rst_ni) begin : proc_err_fifo_overflow_ff
    if(~rst_ni) begin
      err_fifo_overflow_q <= '0;
    end else begin
      err_fifo_overflow_q <= err_fifo_overflow_d;
    end
  end

  always_comb begin : proc_err_fifo_overflow
    err_fifo_overflow_d = err_fifo_overflow_q;
    if (pop_err_fifo) begin
      err_fifo_overflow_d = 1'b0;
    end
    if (bus_err & bus_unit_full) begin
      err_fifo_overflow_d = 1'b1;
    end
  end

  fifo_v3 #(
    .FALL_THROUGH ( 1'b0            ),
    .dtype        ( err_addr_t      ),
    .DEPTH        ( NumStoredErrors )
  ) i_err_fifo (
    .clk_i,
    .rst_ni,
    .flush_i   ( 1'b0           ),
    .testmode_i( testmode_i     ),
    .full_o    ( bus_unit_full  ),
    .empty_o   ( err_fifo_empty ),
    .usage_o   (),
    .data_i    ( fifo_data      ),
    .push_i    ( push_err_fifo  ),
    .data_o    ( read_err_addr  ),
    .pop_i     ( pop_err_fifo   )
  );

  assign err_code_o = err_fifo_empty ? '0 : read_err_addr.err;
  assign err_addr_o = err_fifo_empty ? '0 : read_err_addr.addr;
  assign err_meta_o = err_fifo_empty ? '0 : read_err_addr.meta;

  assign err_fifo_overflow_o = err_fifo_overflow_q;

endmodule
