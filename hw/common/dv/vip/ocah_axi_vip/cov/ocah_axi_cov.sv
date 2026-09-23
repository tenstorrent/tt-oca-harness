// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Tenstorrent Inc.
//
// Commercial-simulator AXI/AXI-Lite functional coverage hook.
// Do not add this file to Verilator filelists: it uses covergroups.

interface ocah_axi_cov_if #(
  parameter int unsigned ADDR_WIDTH = 64,
  parameter int unsigned DATA_WIDTH = 64,
  parameter int unsigned ID_WIDTH = 8
) (
  input wire logic clk_i,
  input wire logic rst_ni
);

  covergroup axi_write_cg with function sample (
      bit is_lite, bit [1:0] resp, int unsigned size, int unsigned burst_len, bit errored
  );
    option.per_instance = 1;
    cp_protocol: coverpoint is_lite {bins axi4 = {1'b0}; bins axi_lite = {1'b1};}
    cp_resp: coverpoint resp {
      bins okay = {2'd0}; bins exokay = {2'd1}; bins slverr = {2'd2}; bins decerr = {2'd3};
    }
    cp_size: coverpoint size {
      bins byte_1 = {0};
      bins byte_2 = {1};
      bins byte_4 = {2};
      bins byte_8 = {3};
      bins larger[] = {[4 : 7]};
    }
    cp_burst_len: coverpoint burst_len {
      bins single = {1}; bins short[] = {[2 : 4]}; bins long = {[5 : 256]};
    }
    cp_errored: coverpoint errored;
    cx_protocol_resp: cross cp_protocol, cp_resp;
  endgroup

  covergroup axi_read_cg with function sample (
      bit is_lite, bit [1:0] resp, int unsigned size, int unsigned burst_len, bit errored
  );
    option.per_instance = 1;
    cp_protocol: coverpoint is_lite {bins axi4 = {1'b0}; bins axi_lite = {1'b1};}
    cp_resp: coverpoint resp {
      bins okay = {2'd0}; bins exokay = {2'd1}; bins slverr = {2'd2}; bins decerr = {2'd3};
    }
    cp_size: coverpoint size {
      bins byte_1 = {0};
      bins byte_2 = {1};
      bins byte_4 = {2};
      bins byte_8 = {3};
      bins larger[] = {[4 : 7]};
    }
    cp_burst_len: coverpoint burst_len {
      bins single = {1}; bins short[] = {[2 : 4]}; bins long = {[5 : 256]};
    }
    cp_errored: coverpoint errored;
    cx_protocol_resp: cross cp_protocol, cp_resp;
  endgroup

  axi_write_cg write_cg = new();
  axi_read_cg read_cg = new();

  // Functions (no timing controls) so both procedural blocks and UVM
  // subscriber write() functions can sample coverage. `addr` and `id` are
  // part of the sampling contract and feed no bin of the covergroups.
  function automatic void sample_write(input bit is_lite, input logic [ADDR_WIDTH-1:0] addr,
                                       input logic [ID_WIDTH-1:0] id, input int unsigned size,
                                       input int unsigned burst_len, input logic [1:0] resp);
    bit errored;
    if (!rst_ni) begin
      return;
    end
    errored = resp inside {2'd2, 2'd3};
    write_cg.sample(is_lite, resp, size, burst_len, errored);
  endfunction

  function automatic void sample_read(input bit is_lite, input logic [ADDR_WIDTH-1:0] addr,
                                      input logic [ID_WIDTH-1:0] id, input int unsigned size,
                                      input int unsigned burst_len, input logic [1:0] resp);
    bit errored;
    if (!rst_ni) begin
      return;
    end
    errored = resp inside {2'd2, 2'd3};
    read_cg.sample(is_lite, resp, size, burst_len, errored);
  endfunction

endinterface

module ocah_axi_cov #(
  parameter int unsigned ADDR_WIDTH = 64,
  parameter int unsigned DATA_WIDTH = 64,
  parameter int unsigned ID_WIDTH = 8
) (
  input wire logic clk_i,
  input wire logic rst_ni,
  input wire logic write_sample_valid_i,
  input wire logic write_is_lite_i,
  input wire logic [ADDR_WIDTH-1:0] write_addr_i,
  input wire logic [ID_WIDTH-1:0] write_id_i,
  input wire logic [2:0] write_size_i,
  input wire logic [7:0] write_burst_len_i,
  input wire logic [1:0] write_resp_i,
  input wire logic read_sample_valid_i,
  input wire logic read_is_lite_i,
  input wire logic [ADDR_WIDTH-1:0] read_addr_i,
  input wire logic [ID_WIDTH-1:0] read_id_i,
  input wire logic [2:0] read_size_i,
  input wire logic [7:0] read_burst_len_i,
  input wire logic [1:0] read_resp_i
);

  ocah_axi_cov_if #(
    .ADDR_WIDTH(ADDR_WIDTH),
    .DATA_WIDTH(DATA_WIDTH),
    .ID_WIDTH(ID_WIDTH)
  ) cov_if (
    .clk_i(clk_i),
    .rst_ni(rst_ni)
  );

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      // Covergroups are sampled only when reset is deasserted.
    end else begin
      if (write_sample_valid_i) begin
        cov_if.sample_write(write_is_lite_i, write_addr_i, write_id_i, write_size_i,
                            write_burst_len_i, write_resp_i);
      end
      if (read_sample_valid_i) begin
        cov_if.sample_read(read_is_lite_i, read_addr_i, read_id_i, read_size_i, read_burst_len_i,
                           read_resp_i);
      end
    end
  end

endmodule
