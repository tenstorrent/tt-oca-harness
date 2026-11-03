// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Four-state data rules for the SMU wrapper bench's AXI links, instantiated
// beside each link's ocah_axi_sva checker on the same clock, reset and enable.
// EN_W_DATA_RULE judges WDATA: every byte lane WSTRB marks active
// (IHI 0022 A3.4.3) is resolved while WVALID is high; an inactive lane carries
// no data and is masked out. EN_R_DATA_RULE judges RDATA: resolved while
// RVALID is high.
//
// Both rules sit on `OCAH_ASSERT, live only where OCAH_INC_ASSERT is defined:
// a four-state simulator, never Verilator. en_i is the runtime suppress knob,
// and the rules are disabled while aresetn is low.

`include "ocah_assert.svh"

module smu_axi_data_known_sva #(
  parameter int unsigned DATA_WIDTH     = 64,    // WDATA and RDATA width in bits
  parameter bit          EN_W_DATA_RULE = 1'b0,  // grade the strobed WDATA lanes
  parameter bit          EN_R_DATA_RULE = 1'b0   // grade RDATA
) (
  input wire logic                    aclk,     // link clock
  input wire logic                    aresetn,  // link reset, active low; rules off while low
  input wire logic                    en_i,     // runtime suppress, rules live while high
  input wire logic [DATA_WIDTH-1:0]   wdata,    // write data beat
  input wire logic [DATA_WIDTH/8-1:0] wstrb,    // write byte-lane strobes
  input wire logic                    wvalid,   // write data valid
  input wire logic [DATA_WIDTH-1:0]   rdata,    // read data beat
  input wire logic                    rvalid    // read data valid
);

  if (EN_W_DATA_RULE) begin : gen_w_data_known
`ifdef OCAH_INC_ASSERT
    logic [DATA_WIDTH-1:0] strobed_wdata;
    for (genvar lane = 0; lane < DATA_WIDTH / 8; lane++) begin : gen_lane
      assign strobed_wdata[8*lane+:8] = wdata[8*lane+:8] & {8{wstrb[lane]}};
    end
`endif
    `OCAH_ASSERT(SMU_AXI_W_STROBED_DATA_KNOWN, (en_i && wvalid) |-> !$isunknown(strobed_wdata),
                 aclk, !aresetn)
  end

  if (EN_R_DATA_RULE) begin : gen_r_data_known
    `OCAH_ASSERT(SMU_AXI_R_DATA_KNOWN, (en_i && rvalid) |-> !$isunknown(rdata), aclk, !aresetn)
  end

endmodule : smu_axi_data_known_sva
