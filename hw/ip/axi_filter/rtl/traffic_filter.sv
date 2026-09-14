// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Traffic Filter

module traffic_filter #(
  parameter bit EnSrcIdFilter = 1'b0,
  parameter bit EnNsFilter = 1'b0,
  parameter bit EnGroupIdFilter = 1'b0,
  parameter int unsigned AddrWidth = 64,
  parameter int unsigned SrcIdWidth = 4,
  parameter int unsigned GroupIdWidth = 4,
  parameter int unsigned DataBusWidthLog2 = 3,

  localparam type addr_t     = logic [AddrWidth-1:0],
  localparam type src_id_t   = logic [SrcIdWidth-1:0],
  localparam type group_id_t = logic [GroupIdWidth-1:0]
) (
  input logic             cfg_allow_traffic_type_i,
  input addr_t            cfg_start_addr_i,          // spyglass disable W240
  input addr_t            cfg_end_addr_i,            // spyglass disable W240
  input logic             cfg_entry_enabled_i,
  input logic             cfg_burst_en_i,
  input src_id_t          cfg_src_id_i,
  input group_id_t        cfg_group_id_i,
  input logic             cfg_allow_ns_i,

  input logic             tx_valid_i,
  input addr_t            tx_addr_i,   // spyglass disable W240
  input src_id_t          tx_src_id_i,
  input group_id_t        tx_group_id_i,
  input logic             tx_ns_initiator_i,
  input axi_pkg::len_t    tx_len_i,

  output logic            filter_hit_o,
  output logic            tx_rule_pass_o
);

  logic tx_in_range;
  always_comb begin
    if (cfg_burst_en_i) begin
      tx_in_range = (tx_addr_i[AddrWidth-1:12] >= cfg_start_addr_i[AddrWidth-1:12]) &&
                        (tx_addr_i[AddrWidth-1:12] <= cfg_end_addr_i[AddrWidth-1:12]);
    end else begin
      tx_in_range = (tx_addr_i[AddrWidth-1:DataBusWidthLog2] >= cfg_start_addr_i[AddrWidth-1:DataBusWidthLog2]) &&
                        (tx_addr_i[AddrWidth-1:DataBusWidthLog2] <= cfg_end_addr_i[AddrWidth-1:DataBusWidthLog2]);
    end
  end

  logic pass_src_id, pass_burst, pass_ns, pass_group_id;
  always_comb begin
    // If NS filtering is enabled, we only let traffic matching the secure level pass if the filter allows it
    pass_ns = EnNsFilter ? (tx_ns_initiator_i == cfg_allow_ns_i) : 1'b1;

    // If Group ID filtering is enabled, we ignore if all input bits are set to 0,
    // otherwise traffic with matching group_id is needed
    pass_group_id = EnGroupIdFilter ? !(|tx_group_id_i) | (tx_group_id_i == cfg_group_id_i) : 1'b1;

    // If SRC ID filtering is enabled, we ignore if all cfg bits are set to 0,
    // otherwise traffic with matching src_id is needed
    pass_src_id = EnSrcIdFilter ? !(|cfg_src_id_i) | (tx_src_id_i == cfg_src_id_i) : 1'b1;

    // If bursts are not enabled, we only pass with tx_len == 0
    pass_burst = cfg_burst_en_i | (tx_len_i == axi_pkg::len_t'(0));
  end

  assign tx_rule_pass_o = cfg_allow_traffic_type_i && tx_valid_i;
  assign filter_hit_o   = &{cfg_entry_enabled_i, tx_in_range, pass_src_id, pass_ns, pass_burst, pass_group_id};

endmodule
