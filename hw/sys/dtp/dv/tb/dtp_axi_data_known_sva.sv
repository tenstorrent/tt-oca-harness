// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Four-state data rules for the DTP bench's AXI ports, instantiated beside
// each port's ocah_axi_sva checker on the data the port's DUT side drives.
// EN_W_DATA_RULE judges WDATA where the DUT is the port's manager: every byte
// lane WSTRB marks active (IHI 0022 A3.4.3) is resolved while WVALID is high;
// an inactive lane carries no data and is masked out. EN_R_DATA_RULE judges
// RDATA where the DUT is the port's subordinate: resolved while RVALID is
// high.
//
// Both rules sit on `OCAH_ASSERT, live only where OCAH_INC_ASSERT is defined:
// a four-state simulator, never Verilator. en_i is the runtime suppress knob,
// and the rules are disabled while aresetn is low.

`include "ocah_assert.svh"

module dtp_axi_data_known_sva #(
  parameter int unsigned DATA_WIDTH     = 32,
  parameter bit          EN_W_DATA_RULE = 1'b0,
  parameter bit          EN_R_DATA_RULE = 1'b0
) (
  input wire logic                    aclk,
  input wire logic                    aresetn,
  input wire logic                    en_i,
  input wire logic [DATA_WIDTH-1:0]   wdata,
  input wire logic [DATA_WIDTH/8-1:0] wstrb,
  input wire logic                    wvalid,
  input wire logic [DATA_WIDTH-1:0]   rdata,
  input wire logic                    rvalid
);

  if (EN_W_DATA_RULE) begin : gen_w_data_known
`ifdef OCAH_INC_ASSERT
    logic [DATA_WIDTH-1:0] strobed_wdata;
    for (genvar lane = 0; lane < DATA_WIDTH / 8; lane++) begin : gen_lane
      assign strobed_wdata[8*lane+:8] = wdata[8*lane+:8] & {8{wstrb[lane]}};
    end
`endif
    `OCAH_ASSERT(DTP_AXI_W_STROBED_DATA_KNOWN, (en_i && wvalid) |-> !$isunknown(strobed_wdata),
                 aclk, !aresetn)
  end

  if (EN_R_DATA_RULE) begin : gen_r_data_known
    `OCAH_ASSERT(DTP_AXI_R_DATA_KNOWN, (en_i && rvalid) |-> !$isunknown(rdata), aclk, !aresetn)
  end

endmodule : dtp_axi_data_known_sva
