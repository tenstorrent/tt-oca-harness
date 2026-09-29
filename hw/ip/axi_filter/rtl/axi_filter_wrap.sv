// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Filter AXI traffic through programmable address, ID, and NS rules with an error-slave path.
//
// Each filter_ctrl_i entry programs one write-path and one read-path traffic_filter.
// The lowest-index entry that hits decides whether AW or AR traffic is allowed.
// Denied traffic steers to an error slave that answers DECERR; filter_skip_i bypasses
// matching entirely.
// BlockByDefault denies traffic when no rule hits.

module axi_filter_wrap #(
  parameter int unsigned  NumFilters                = 16,   // Number of programmable filter
                                                            // entries.
  parameter int unsigned  DebugOutput               = 0,    // Value 1 drives the hit indices onto
                                                            // the debug outputs; other values tie
                                                            // them to zero.

  parameter bit           BlockByDefault            = 1'b0, // Deny traffic when no rule hits.

  parameter bit           EnSrcIdFilter             = 1'b0, // Match on AXI user source ID.
  parameter int unsigned  SrcIdUserBitStart         = 0,    // User-bit index of the source ID.
  parameter int unsigned  SrcIdWidth                = 4,    // Source ID width in user bits.

  parameter bit           EnGroupIdFilter           = 1'b0, // Match on AXI user group ID.
  parameter int unsigned  GroupIdUserBitStart       = 4,    // User-bit index of the group ID.
  parameter int unsigned  GroupIdWidth              = 4,    // Group ID width in user bits.

  parameter bit           EnNsFilter                = 1'b0, // Match on the non-secure initiator
                                                            // flag, AxPROT[1].

  parameter int unsigned  AxiAddrWidth              = 64,   // AXI address width.
  parameter int unsigned  AxiIdWidth                = 5,    // ID width of the AXI ports, the demux
                                                            // and the error slave.
  parameter int unsigned  AxiDataWidth              = 64,   // Data-bus width; sets the address
                                                            // granularity of single-beat rules.

  parameter int unsigned  MaxTrans                  = 4,    // Outstanding transactions in the
                                                            // demux.
  parameter int unsigned  AxiLookBits               = (AxiIdWidth > 3) ? 3 : AxiIdWidth, // ID bits used for outstanding tracking.
  parameter int unsigned  ErrSlvMaxTrans            = 32,   // Error-slave outstanding capacity.
  parameter bit           FlopReqEn                 = 1'b0, // Adds spill registers on the demux AW,
                                                            // W and AR channels.
  parameter bit           FlopRespEn                = 1'b0, // Adds spill registers on the demux B
                                                            // and R channels.

  parameter type          filter_axi_req_t          = logic, // Filtered AXI request type.
  parameter type          filter_axi_resp_t         = logic, // Filtered AXI response type.

  parameter type          filter_aw_chan_t          = logic, // AW channel type.
  parameter type          filter_w_chan_t           = logic, // W channel type.
  parameter type          filter_b_chan_t           = logic, // B channel type.
  parameter type          filter_ar_chan_t          = logic, // AR channel type.
  parameter type          filter_r_chan_t           = logic, // R channel type.

  localparam int unsigned AxiStrbWidth             = AxiDataWidth / 8, // Write-strobe width.

  localparam bit [2:0]    DbusWidthLog2            = AxiStrbWidth > 1 ? $clog2(AxiStrbWidth) : 0, // log2 of the data-bus byte width.

  localparam type         select_t                 = logic [$clog2(NumFilters)-1:0] // Filter-select index type; declared but not used.
) (
  input  logic                                    clk_i,    // System clock.
  input  logic                                    rst_ni,   // Async reset, active-low.
  input  logic                                    test_en_i, // DFT test enable.
  input  logic                                    filter_skip_i, // Bypass all filter matching and
                                                                 // route every request to
                                                                 // axi_filtered_out_req_o.

  input  filter_ctrl_reg_pkg::filter_ctrl__out_t  filter_ctrl_i          [NumFilters-1:0], // Per-entry PeakRDL configuration.
  output filter_ctrl_reg_pkg::filter_ctrl__in_t   filter_status_o        [NumFilters-1:0], // Per-entry PeakRDL status: the data-bus width and the programmed range widened to
                                                                                           // the rule granularity when start and end share one granule.

  input  filter_axi_req_t                         axi_in_req_i, // Unfiltered AXI request.
  output filter_axi_resp_t                        axi_in_resp_o, // Unfiltered AXI response.

  output filter_axi_req_t                         axi_filtered_out_req_o, // Allowed AXI request.
  input  filter_axi_resp_t                        axi_filtered_out_resp_i, // Allowed AXI response.

  output logic [$clog2(NumFilters)-1:0]           write_filter_hit_debug_o, // Lowest hitting entry index on the write path; zero when DebugOutput is not 1.
  output logic [$clog2(NumFilters)-1:0]           read_filter_hit_debug_o // Lowest hitting entry index on the read path; zero when DebugOutput is not 1.
);

  //////////////////////////
  // Filter Configuration //
  //////////////////////////

  typedef struct {
    logic [AxiAddrWidth-1:0]    start_addr;
    logic [AxiAddrWidth-1:0]    end_addr;
    logic                       read_allowed;
    logic                       write_allowed;
    logic [SrcIdWidth-1:0]      src_id;
    logic [GroupIdWidth-1:0]    group_id;
    logic                       entry_enabled;
    logic                       allow_ns;
    logic                       allow_burst;
    logic                       locked;
  } filter_rule_t;

  filter_rule_t           filters           [NumFilters];

  logic [NumFilters-1:0]  allow_write;
  logic [NumFilters-1:0]  allow_read;
  logic [NumFilters-1:0]  write_filter_hit;
  logic [NumFilters-1:0]  read_filter_hit;

  generate
    for (genvar f = 0; f < NumFilters; f = f + 1) begin : gen_filter_config

      logic [AxiAddrWidth-1:0] start_addr_converted;
      logic [AxiAddrWidth-1:0] end_addr_converted;

      // always adjust the start and end address such that the range matches the granularity
      // i.e. if bursts are enabled, the finest granularity is 4KB.
      //      so if the range is programmed to be 0x1001 to 0x1002,
      //      adjust the range to be 0x1000 to 0x1FFF instead
      always_comb begin
        start_addr_converted = filters[f].start_addr;
        end_addr_converted = filters[f].end_addr;

        if (filters[f].allow_burst) begin
          if (filters[f].start_addr[AxiAddrWidth-1:12] == filters[f].end_addr[AxiAddrWidth-1:12]) begin
            start_addr_converted = {filters[f].start_addr[AxiAddrWidth-1:12], 12'h0};
            end_addr_converted   = {filters[f].end_addr[AxiAddrWidth-1:12], 12'hFFF};
          end
        end else begin
          if (filters[f].start_addr[AxiAddrWidth-1:DbusWidthLog2] == filters[f].end_addr[AxiAddrWidth-1:DbusWidthLog2]) begin
            start_addr_converted = {filters[f].start_addr[AxiAddrWidth-1:DbusWidthLog2], {DbusWidthLog2{1'b0}}};
            end_addr_converted   = {filters[f].end_addr[AxiAddrWidth-1:DbusWidthLog2], {DbusWidthLog2{1'b1}}};
          end
        end
      end

      always_comb begin
        filter_status_o[f].FILTER_CONFIG.data_bus_width.next  = DbusWidthLog2;

        filter_status_o[f].START_ADDR.start_addr.next         = start_addr_converted;
        filter_status_o[f].END_ADDR.end_addr.next             = end_addr_converted;

        filters[f].start_addr[AxiAddrWidth-1:0]           = filter_ctrl_i[f].START_ADDR.start_addr.value;
        filters[f].end_addr[AxiAddrWidth-1:0]             = filter_ctrl_i[f].END_ADDR.end_addr.value;
        filters[f].read_allowed                           = filter_ctrl_i[f].FILTER_CONFIG.read_allowed.value;
        filters[f].write_allowed                          = filter_ctrl_i[f].FILTER_CONFIG.write_allowed.value;
        filters[f].entry_enabled                          = filter_ctrl_i[f].FILTER_CONFIG.entry_enabled.value;
        filters[f].allow_ns                               = filter_ctrl_i[f].FILTER_CONFIG.allow_ns.value;
        filters[f].src_id                                 = filter_ctrl_i[f].FILTER_CONFIG.src_id.value;
        filters[f].group_id                               = filter_ctrl_i[f].FILTER_CONFIG.group_id.value;
        filters[f].allow_burst                            = filter_ctrl_i[f].FILTER_CONFIG.allow_burst.value;
        filters[f].locked                                 = filter_ctrl_i[f].FILTER_CONFIG.locked.value;
      end

      //////////////////////
      // Filter Detection //
      //////////////////////

      traffic_filter #(
        .EnSrcIdFilter       (EnSrcIdFilter),
        .EnNsFilter          (EnNsFilter),
        .EnGroupIdFilter     (EnGroupIdFilter),
        .AddrWidth           (AxiAddrWidth),
        .SrcIdWidth          (SrcIdWidth),
        .GroupIdWidth        (GroupIdWidth),
        .DataBusWidthLog2    (DbusWidthLog2)
      ) u_write_traffic_filter (
        .cfg_allow_traffic_type_i (filters[f].write_allowed),
        .cfg_start_addr_i         (filters[f].start_addr),
        .cfg_end_addr_i           (filters[f].end_addr),
        .cfg_entry_enabled_i      (filters[f].entry_enabled),
        .cfg_src_id_i             (filters[f].src_id),
        .cfg_group_id_i           (filters[f].group_id),
        .cfg_allow_ns_i           (filters[f].allow_ns),
        .cfg_burst_en_i           (filters[f].allow_burst),
        .tx_valid_i               (axi_in_req_i.aw_valid),
        .tx_addr_i                (axi_in_req_i.aw.addr),
        .tx_src_id_i              (axi_in_req_i.aw.user[SrcIdUserBitStart+:SrcIdWidth]),
        .tx_group_id_i            (axi_in_req_i.aw.user[GroupIdUserBitStart+:GroupIdWidth]),
        .tx_ns_initiator_i        (axi_in_req_i.aw.prot[1]),
        .tx_len_i                 (axi_in_req_i.aw.len),
        .filter_hit_o             (write_filter_hit[f]),
        .tx_rule_pass_o           (allow_write[f])
      );

      traffic_filter #(
        .EnSrcIdFilter       (EnSrcIdFilter),
        .EnNsFilter          (EnNsFilter),
        .EnGroupIdFilter     (EnGroupIdFilter),
        .AddrWidth           (AxiAddrWidth),
        .SrcIdWidth          (SrcIdWidth),
        .GroupIdWidth        (GroupIdWidth),
        .DataBusWidthLog2    (DbusWidthLog2)
      ) u_read_traffic_filter (
        .cfg_allow_traffic_type_i (filters[f].read_allowed),
        .cfg_start_addr_i         (filters[f].start_addr),
        .cfg_end_addr_i           (filters[f].end_addr),
        .cfg_entry_enabled_i      (filters[f].entry_enabled),
        .cfg_src_id_i             (filters[f].src_id),
        .cfg_group_id_i           (filters[f].group_id),
        .cfg_allow_ns_i           (filters[f].allow_ns),
        .cfg_burst_en_i           (filters[f].allow_burst),
        .tx_valid_i               (axi_in_req_i.ar_valid),
        .tx_addr_i                (axi_in_req_i.ar.addr),
        .tx_src_id_i              (axi_in_req_i.ar.user[SrcIdUserBitStart+:SrcIdWidth]),
        .tx_group_id_i            (axi_in_req_i.ar.user[GroupIdUserBitStart+:GroupIdWidth]),
        .tx_ns_initiator_i        (axi_in_req_i.ar.prot[1]),
        .tx_len_i                 (axi_in_req_i.ar.len),
        .filter_hit_o             (read_filter_hit[f]),
        .tx_rule_pass_o           (allow_read[f])
      );

    end
  endgenerate

  localparam int unsigned HitIndexWidth = $clog2(NumFilters);
  logic [HitIndexWidth-1:0] write_filter_hit_idx, read_filter_hit_idx;
  logic no_write_filter_matches, no_read_filter_matches;
  logic isolate_write, isolate_read;

  lzc #(
    .WIDTH (NumFilters),
    .MODE  (1'b0)  // Count leading zeros to find the index of the first filter that contains the request address
  ) u_write_filter_hit_lzc (
    .in_i    (write_filter_hit),
    .cnt_o   (write_filter_hit_idx),
    .empty_o (no_write_filter_matches)
  );
  assign isolate_write = filter_skip_i ? 1'b0 : (no_write_filter_matches ? BlockByDefault : !allow_write[write_filter_hit_idx]);

  lzc #(
    .WIDTH (NumFilters),
    .MODE  (1'b0)  // Count leading zeros to find the index of the first filter that contains the request address
  ) u_read_filter_hit_lzc (
    .in_i    (read_filter_hit),
    .cnt_o   (read_filter_hit_idx),
    .empty_o (no_read_filter_matches)
  );
  assign isolate_read  = filter_skip_i ? 1'b0 : (no_read_filter_matches ? BlockByDefault : !allow_read[read_filter_hit_idx]);

  generate
    if (DebugOutput == 1) begin : gen_filter_hit_debug
      assign write_filter_hit_debug_o = write_filter_hit_idx;
      assign read_filter_hit_debug_o  = read_filter_hit_idx;
    end else begin : gen_no_filter_hit_debug
      assign write_filter_hit_debug_o = '0;
      assign read_filter_hit_debug_o  = '0;
    end
  endgenerate

  ////////////////////////////////////
  // AXI Demux for Filtering Output //
  ////////////////////////////////////

  filter_axi_req_t  err_slv_req;
  filter_axi_resp_t err_slv_resp;

  axi_demux #(
    .AxiIdWidth  (AxiIdWidth),
    .AtopSupport (1'b0),
    .aw_chan_t   (filter_aw_chan_t),
    .w_chan_t    (filter_w_chan_t),
    .b_chan_t    (filter_b_chan_t),
    .ar_chan_t   (filter_ar_chan_t),
    .r_chan_t    (filter_r_chan_t),
    .axi_req_t   (filter_axi_req_t),
    .axi_resp_t  (filter_axi_resp_t),
    .NoMstPorts  (2),
    .MaxTrans    (MaxTrans),
    .AxiLookBits (AxiLookBits),
    .UniqueIds   (1'b0),
    .SpillAw     (FlopReqEn),
    .SpillW      (FlopReqEn),
    .SpillB      (FlopRespEn),
    .SpillAr     (FlopReqEn),
    .SpillR      (FlopRespEn)
  ) u_axi_demux (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .test_i          (test_en_i),
    .sel_hash_i      (2'd0),
    .slv_req_i       (axi_in_req_i),
    .slv_aw_select_i (isolate_write),
    .slv_ar_select_i (isolate_read),
    .slv_resp_o      (axi_in_resp_o),
    .mst_reqs_o      ({err_slv_req, axi_filtered_out_req_o}),
    .mst_resps_i     ({err_slv_resp, axi_filtered_out_resp_i})
  );

  axi_err_slv #(
    .AxiIdWidth (AxiIdWidth),
    .axi_req_t  (filter_axi_req_t),
    .axi_resp_t (filter_axi_resp_t),
    .Resp       (axi_pkg::RESP_DECERR),
    .ATOPs      (1'b0),
    .MaxTrans   (ErrSlvMaxTrans)
  ) u_axi_err_slv (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (test_en_i),
    .slv_req_i  (err_slv_req),
    .slv_resp_o (err_slv_resp)
  );

endmodule
