// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Decide whether one AXI address beat matches a filter rule and may pass.
//
// Compares the address range, the burst length, and the optional source ID, group ID, and
// NS checks against the cfg_* inputs; the module is purely combinational.
// filter_hit_o marks a match; tx_rule_pass_o is the allow decision for that beat.

module traffic_filter #(
  parameter bit EnSrcIdFilter = 1'b0,                       // Match on source ID.
  parameter bit EnNsFilter = 1'b0,                          // Requires the beat NS flag to equal
                                                            // cfg_allow_ns_i.
  parameter bit EnGroupIdFilter = 1'b0,                     // Match on group ID.
  parameter int unsigned AddrWidth = 64,                    // Address compare width.
  parameter int unsigned SrcIdWidth = 4,                    // Source ID width.
  parameter int unsigned GroupIdWidth = 4,                  // Width of the rule and beat group IDs
                                                            // compared under EnGroupIdFilter.
  parameter int unsigned DataBusWidthLog2 = 3,              // log2 of data-bus bytes; address
                                                            // compare granularity when bursts are
                                                            // disabled.

  localparam type addr_t     = logic [AddrWidth-1:0],       // Address type.
  localparam type src_id_t   = logic [SrcIdWidth-1:0],      // Source ID type.
  localparam type group_id_t = logic [GroupIdWidth-1:0]     // Group ID type.
) (
  input logic             cfg_allow_traffic_type_i,         // Allow when this rule hits.
  input addr_t            cfg_start_addr_i,                 // Inclusive start of the address
                                                            // window, compared at 4 KiB granularity
                                                            // with cfg_burst_en_i and at bus-width
                                                            // granularity otherwise; spyglass
                                                            // disable W240.
  input addr_t            cfg_end_addr_i,                   // Inclusive end of the address window,
                                                            // at the same granularity as
                                                            // cfg_start_addr_i; spyglass disable
                                                            // W240.
  input logic             cfg_entry_enabled_i,              // Rule enable; when low, filter_hit_o
                                                            // stays low.
  input logic             cfg_burst_en_i,                   // Admits multi-beat bursts and coarsens
                                                            // the range compare to 4 KiB; when low,
                                                            // only single-beat transfers match.
  input src_id_t          cfg_src_id_i,                     // Source ID a beat must carry under
                                                            // EnSrcIdFilter; all zeros matches any
                                                            // source.
  input group_id_t        cfg_group_id_i,                   // Group ID a beat must carry under
                                                            // EnGroupIdFilter.
  input logic             cfg_allow_ns_i,                   // NS value a beat must carry under
                                                            // EnNsFilter: 1 matches non-secure, 0
                                                            // secure initiators.

  input logic             tx_valid_i,                       // Address-beat valid; gates
                                                            // tx_rule_pass_o but not filter_hit_o.
  input addr_t            tx_addr_i,                        // Address-beat address; spyglass
                                                            // disable W240.
  input src_id_t          tx_src_id_i,                      // Address-beat source ID.
  input group_id_t        tx_group_id_i,                    // Address-beat group ID; all zeros
                                                            // passes the group check regardless of
                                                            // cfg_group_id_i.
  input logic             tx_ns_initiator_i,                // Address-beat non-secure flag, high
                                                            // for a non-secure initiator.
  input axi_pkg::len_t    tx_len_i,                         // AXI burst length; nonzero values
                                                            // match only with cfg_burst_en_i.

  output logic            filter_hit_o,                     // Rule matched this beat; independent
                                                            // of tx_valid_i.
  output logic            tx_rule_pass_o                    // Beat is valid and the rule allows
                                                            // this traffic type; meaningful when
                                                            // filter_hit_o is set.
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
