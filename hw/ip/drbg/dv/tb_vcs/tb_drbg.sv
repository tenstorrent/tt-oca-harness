// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//----------------------------------------------------------
// Copyright 2026 Tenstorrent Inc.
// tb_drbg
//
// Cocotb-oriented SystemVerilog harness for the DRBG wrapper.
//----------------------------------------------------------

/**
 * @file tb_drbg.sv
 * @brief Cocotb-friendly wrapper harness for `drbg`.
 *
 * @details Provides a single-clock testbench harness with flattened AXI-Lite
 *          stimulus signals, entropy injection hooks, AXI-Stream outputs, and
 *          direct observability of wrapper-local routing, seed-queue, TL-UL,
 *          interrupt, and alert activity. The harness uses constructs that are
 *          compatible with both VCS and Verilator.
 *
 * @param INGRESS_FIFO_DEPTH Shared depth for both entropy ingress FIFOs.
 * @param SEED_FIFO_DEPTH Depth of the complete-seed FIFO.
 * @param EDN_ENDPOINT_COUNT Number of exposed EDN endpoint AXI-Stream outputs.
 * @param ENDPOINT_FIFO_DEPTH Depth of each endpoint AXI-Stream FIFO.
 */
module tb_drbg
  import drbg_pkg::*;
#(
  parameter int unsigned INGRESS_FIFO_DEPTH = DRBG_DEFAULT_INGRESS_FIFO_DEPTH,
  parameter int unsigned SEED_FIFO_DEPTH = DRBG_DEFAULT_SEED_FIFO_DEPTH,
  parameter int unsigned EDN_ENDPOINT_COUNT = DRBG_DEFAULT_EDN_ENDPOINT_COUNT,
  parameter int unsigned ENDPOINT_FIFO_DEPTH = DRBG_DEFAULT_ENDPOINT_FIFO_DEPTH
);

  localparam int unsigned CSRNG_NUM_HW_APPS = csrng_reg_pkg::NumApps - 1;

  logic clk_i;
  logic rst_ni;

  logic [31:0] entropy_stream_data_i;
  logic        entropy_stream_vld_i;
  logic        entropy_axis_tvalid_o;
  logic [31:0] entropy_axis_tdata_o;
  logic [3:0]  entropy_axis_tstrb_o;
  logic        entropy_axis_tready_i;
  drbg_axis_req_t entropy_axis;
  drbg_axis_rsp_t entropy_axis_rsp;

  logic [EDN_ENDPOINT_COUNT-1:0]       edn_axis_tvalid_o;
  logic [EDN_ENDPOINT_COUNT-1:0][31:0] edn_axis_tdata_o;
  logic [EDN_ENDPOINT_COUNT-1:0][3:0]  edn_axis_tstrb_o;
  logic [EDN_ENDPOINT_COUNT-1:0]       edn_axis_tready_i;
  drbg_axis_req_t [EDN_ENDPOINT_COUNT-1:0] edn_axis;
  drbg_axis_rsp_t [EDN_ENDPOINT_COUNT-1:0] edn_axis_rsp;

  logic        csrng_axil_awvalid_i;
  logic        csrng_axil_awready_o;
  logic [31:0] csrng_axil_awaddr_i;
  logic [2:0]  csrng_axil_awprot_i;
  logic        csrng_axil_wvalid_i;
  logic        csrng_axil_wready_o;
  logic [63:0] csrng_axil_wdata_i;
  logic [7:0]  csrng_axil_wstrb_i;
  logic        csrng_axil_bvalid_o;
  logic        csrng_axil_bready_i;
  logic [1:0]  csrng_axil_bresp_o;
  logic        csrng_axil_arvalid_i;
  logic        csrng_axil_arready_o;
  logic [31:0] csrng_axil_araddr_i;
  logic [2:0]  csrng_axil_arprot_i;
  logic        csrng_axil_rvalid_o;
  logic        csrng_axil_rready_i;
  logic [63:0] csrng_axil_rdata_o;
  logic [1:0]  csrng_axil_rresp_o;
  drbg_axil64_req_t  csrng_axil_req;
  drbg_axil64_resp_t csrng_axil_rsp;

  logic        edn_axil_awvalid_i;
  logic        edn_axil_awready_o;
  logic [31:0] edn_axil_awaddr_i;
  logic [2:0]  edn_axil_awprot_i;
  logic        edn_axil_wvalid_i;
  logic        edn_axil_wready_o;
  logic [63:0] edn_axil_wdata_i;
  logic [7:0]  edn_axil_wstrb_i;
  logic        edn_axil_bvalid_o;
  logic        edn_axil_bready_i;
  logic [1:0]  edn_axil_bresp_o;
  logic        edn_axil_arvalid_i;
  logic        edn_axil_arready_o;
  logic [31:0] edn_axil_araddr_i;
  logic [2:0]  edn_axil_arprot_i;
  logic        edn_axil_rvalid_o;
  logic        edn_axil_rready_i;
  logic [63:0] edn_axil_rdata_o;
  logic [1:0]  edn_axil_rresp_o;
  drbg_axil64_req_t  edn_axil_req;
  drbg_axil64_resp_t edn_axil_rsp;

  prim_mubi_pkg::mubi8_t otp_en_csrng_sw_app_read_i;
  lc_ctrl_pkg::lc_tx_t   lc_hw_debug_en_i;

  prim_alert_pkg::alert_rx_t [csrng_reg_pkg::NumAlerts-1:0] csrng_alert_rx_i;
  prim_alert_pkg::alert_tx_t [csrng_reg_pkg::NumAlerts-1:0] csrng_alert_tx_o;
  prim_alert_pkg::alert_rx_t [edn_reg_pkg::NumAlerts-1:0]   edn_alert_rx_i;
  prim_alert_pkg::alert_tx_t [edn_reg_pkg::NumAlerts-1:0]   edn_alert_tx_o;

  logic intr_cs_cmd_req_done_o;
  logic intr_cs_entropy_req_o;
  logic intr_cs_hw_inst_exc_o;
  logic intr_cs_fatal_err_o;
  logic intr_edn_cmd_req_done_o;
  logic intr_edn_fatal_err_o;
  logic csrng_bus_err_o;
  logic edn_bus_err_o;
  // Initialised: an X here would propagate into the bridge's sticky-error latch.
  logic csrng_bus_err_clr_i = 1'b0;
  logic edn_bus_err_clr_i = 1'b0;
  logic [csrng_reg_pkg::NumAlerts-1:0] csrng_alert_p_o;
  logic [csrng_reg_pkg::NumAlerts-1:0] csrng_alert_n_o;
  logic [csrng_reg_pkg::NumAlerts-1:0] csrng_inner_alert_p_o;
  logic [csrng_reg_pkg::NumAlerts-1:0] csrng_inner_alert_n_o;
  logic [edn_reg_pkg::NumAlerts-1:0]   edn_alert_p_o;
  logic [edn_reg_pkg::NumAlerts-1:0]   edn_alert_n_o;
  logic [edn_reg_pkg::NumAlerts-1:0]   edn_inner_alert_p_o;
  logic [edn_reg_pkg::NumAlerts-1:0]   edn_inner_alert_n_o;

  // Wrapper-local observability hooks for cocotb.
  logic route_distribution_pulse_o;
  logic route_csrng_pulse_o;
  logic route_drop_pulse_o;
  logic distribution_fifo_full_o;
  logic csrng_fifo_full_o;
  logic [$clog2(INGRESS_FIFO_DEPTH + 1)-1:0] distribution_fifo_depth_o;
  logic [$clog2(INGRESS_FIFO_DEPTH + 1)-1:0] csrng_fifo_depth_o;
  logic seed_queue_valid_o;
  logic [383:0] seed_queue_bits_o;
  logic seed_queue_fips_o;
  logic seed_push_pulse_o;
  logic [4:0] seed_packer_word_count_o;
  logic [$clog2(SEED_FIFO_DEPTH + 1)-1:0] seed_queue_depth_o;
  logic csrng_tl_a_valid_o;
  logic edn_tl_a_valid_o;
  logic csrng_unsupported_access_pulse_o;
  logic edn_unsupported_access_pulse_o;
  logic [EDN_ENDPOINT_COUNT-1:0] endpoint_fifo_full_o;
  logic [EDN_ENDPOINT_COUNT-1:0][$clog2(ENDPOINT_FIFO_DEPTH + 1)-1:0] endpoint_fifo_depth_o;
  logic [EDN_ENDPOINT_COUNT-1:0] edn_req_valid_o;
  logic [CSRNG_NUM_HW_APPS-1:0] csrng_hw_req_valid_o;
  logic [EDN_ENDPOINT_COUNT-1:0][31:0] edn_endpoint_bus_i;
  logic [EDN_ENDPOINT_COUNT-1:0]       edn_endpoint_fips_i;
  logic [EDN_ENDPOINT_COUNT-1:0]       edn_endpoint_ack_i;
  logic [EDN_ENDPOINT_COUNT-1:0]       edn_endpoint_force_i;

  // Keep the cocotb surface flattened while the DUT uses typed AXI-Lite ports.
  assign csrng_axil_req.aw_valid = csrng_axil_awvalid_i;
  assign csrng_axil_req.aw.addr = csrng_axil_awaddr_i;
  assign csrng_axil_req.aw.prot = csrng_axil_awprot_i;
  assign csrng_axil_req.w_valid = csrng_axil_wvalid_i;
  assign csrng_axil_req.w.data = csrng_axil_wdata_i;
  assign csrng_axil_req.w.strb = csrng_axil_wstrb_i;
  assign csrng_axil_req.b_ready = csrng_axil_bready_i;
  assign csrng_axil_req.ar_valid = csrng_axil_arvalid_i;
  assign csrng_axil_req.ar.addr = csrng_axil_araddr_i;
  assign csrng_axil_req.ar.prot = csrng_axil_arprot_i;
  assign csrng_axil_req.r_ready = csrng_axil_rready_i;

  assign csrng_axil_awready_o = csrng_axil_rsp.aw_ready;
  assign csrng_axil_wready_o = csrng_axil_rsp.w_ready;
  assign csrng_axil_bvalid_o = csrng_axil_rsp.b_valid;
  assign csrng_axil_bresp_o = csrng_axil_rsp.b.resp;
  assign csrng_axil_arready_o = csrng_axil_rsp.ar_ready;
  assign csrng_axil_rvalid_o = csrng_axil_rsp.r_valid;
  assign csrng_axil_rdata_o = csrng_axil_rsp.r.data;
  assign csrng_axil_rresp_o = csrng_axil_rsp.r.resp;

  assign edn_axil_req.aw_valid = edn_axil_awvalid_i;
  assign edn_axil_req.aw.addr = edn_axil_awaddr_i;
  assign edn_axil_req.aw.prot = edn_axil_awprot_i;
  assign edn_axil_req.w_valid = edn_axil_wvalid_i;
  assign edn_axil_req.w.data = edn_axil_wdata_i;
  assign edn_axil_req.w.strb = edn_axil_wstrb_i;
  assign edn_axil_req.b_ready = edn_axil_bready_i;
  assign edn_axil_req.ar_valid = edn_axil_arvalid_i;
  assign edn_axil_req.ar.addr = edn_axil_araddr_i;
  assign edn_axil_req.ar.prot = edn_axil_arprot_i;
  assign edn_axil_req.r_ready = edn_axil_rready_i;

  assign edn_axil_awready_o = edn_axil_rsp.aw_ready;
  assign edn_axil_wready_o = edn_axil_rsp.w_ready;
  assign edn_axil_bvalid_o = edn_axil_rsp.b_valid;
  assign edn_axil_bresp_o = edn_axil_rsp.b.resp;
  assign edn_axil_arready_o = edn_axil_rsp.ar_ready;
  assign edn_axil_rvalid_o = edn_axil_rsp.r_valid;
  assign edn_axil_rdata_o = edn_axil_rsp.r.data;
  assign edn_axil_rresp_o = edn_axil_rsp.r.resp;

  // Keep the cocotb surface flattened while the DUT uses typed AXI-Stream ports.
  assign entropy_axis_tvalid_o = entropy_axis.tvalid;
  assign entropy_axis_tdata_o = entropy_axis.tdata;
  assign entropy_axis_tstrb_o = entropy_axis.tstrb;
  assign entropy_axis_rsp.tready = entropy_axis_tready_i;

  for (genvar i = 0; i < EDN_ENDPOINT_COUNT; i++) begin : gen_edn_axis_flatten
    assign edn_axis_tvalid_o[i] = edn_axis[i].tvalid;
    assign edn_axis_tdata_o[i] = edn_axis[i].tdata;
    assign edn_axis_tstrb_o[i] = edn_axis[i].tstrb;
    assign edn_axis_rsp[i].tready = edn_axis_tready_i[i];
  end

  drbg #(
    .INGRESS_FIFO_DEPTH (INGRESS_FIFO_DEPTH),
    .SEED_FIFO_DEPTH    (SEED_FIFO_DEPTH),
    .EDN_ENDPOINT_COUNT (EDN_ENDPOINT_COUNT),
    .ENDPOINT_FIFO_DEPTH(ENDPOINT_FIFO_DEPTH)
  ) u_dut (
    .clk_i,
    .rst_ni,
    .entropy_stream_data_i,
    .entropy_stream_vld_i,
    .entropy_axis_o          (entropy_axis),
    .entropy_axis_i          (entropy_axis_rsp),
    .edn_axis_o              (edn_axis),
    .edn_axis_i              (edn_axis_rsp),
    .csrng_axil_req_i        (csrng_axil_req),
    .csrng_axil_rsp_o        (csrng_axil_rsp),
    .edn_axil_req_i          (edn_axil_req),
    .edn_axil_rsp_o          (edn_axil_rsp),
    .otp_en_csrng_sw_app_read_i,
    .lc_hw_debug_en_i,
    .csrng_alert_rx_i,
    .csrng_alert_tx_o,
    .edn_alert_rx_i,
    .edn_alert_tx_o,
    .intr_cs_cmd_req_done_o,
    .intr_cs_entropy_req_o,
    .intr_cs_hw_inst_exc_o,
    .intr_cs_fatal_err_o,
    .intr_edn_cmd_req_done_o,
    .intr_edn_fatal_err_o,
    .csrng_bus_err_o,
    .csrng_bus_err_clr_i,
    .edn_bus_err_o,
    .edn_bus_err_clr_i
  );

  // Allow cocotb to inject endpoint responses without masking the real EDN path by default.
  for (genvar i = 0; i < EDN_ENDPOINT_COUNT; i++) begin : gen_edn_endpoint_rsp_force
    always_comb begin
      if (edn_endpoint_force_i[i]) begin
        force u_dut.edn_endpoint_rsp[i].edn_bus = edn_endpoint_bus_i[i];
        force u_dut.edn_endpoint_rsp[i].edn_fips = edn_endpoint_fips_i[i];
        force u_dut.edn_endpoint_rsp[i].edn_ack = edn_endpoint_ack_i[i];
      end else begin
        release u_dut.edn_endpoint_rsp[i].edn_bus;
        release u_dut.edn_endpoint_rsp[i].edn_fips;
        release u_dut.edn_endpoint_rsp[i].edn_ack;
      end
    end
  end

  assign route_distribution_pulse_o = u_dut.entropy_route_distribution_pulse;
  assign route_csrng_pulse_o = u_dut.entropy_route_csrng_pulse;
  assign route_drop_pulse_o = u_dut.entropy_drop_pulse;
  assign distribution_fifo_full_o = u_dut.distribution_fifo_full;
  assign csrng_fifo_full_o = u_dut.csrng_fifo_full;
  assign distribution_fifo_depth_o = u_dut.distribution_fifo_depth;
  assign csrng_fifo_depth_o = u_dut.csrng_fifo_depth;
  assign seed_queue_valid_o = u_dut.seed_queue_valid;
  assign seed_queue_bits_o = u_dut.seed_queue_bits;
  assign seed_queue_fips_o = u_dut.seed_queue_fips;
  assign seed_push_pulse_o = u_dut.seed_push_pulse;
  assign seed_packer_word_count_o = u_dut.seed_packer_word_count;
  assign seed_queue_depth_o = u_dut.seed_queue_depth;
  assign csrng_tl_a_valid_o = u_dut.csrng_tl_h2d.a_valid;
  assign edn_tl_a_valid_o = u_dut.edn_tl_h2d.a_valid;
  assign csrng_unsupported_access_pulse_o = u_dut.csrng_bridge_unsupported_pulse;
  assign edn_unsupported_access_pulse_o = u_dut.edn_bridge_unsupported_pulse;
  assign endpoint_fifo_full_o = u_dut.endpoint_fifo_full;
  assign endpoint_fifo_depth_o = u_dut.endpoint_fifo_depth;
  for (genvar i = 0; i < csrng_reg_pkg::NumAlerts; i++) begin : gen_csrng_alert_flatten
    assign csrng_alert_p_o[i] = csrng_alert_tx_o[i].alert_p;
    assign csrng_alert_n_o[i] = csrng_alert_tx_o[i].alert_n;
    assign csrng_inner_alert_p_o[i] = u_dut.u_csrng.alert_tx_o[i].alert_p;
    assign csrng_inner_alert_n_o[i] = u_dut.u_csrng.alert_tx_o[i].alert_n;
  end
  for (genvar i = 0; i < edn_reg_pkg::NumAlerts; i++) begin : gen_edn_alert_flatten
    assign edn_alert_p_o[i] = edn_alert_tx_o[i].alert_p;
    assign edn_alert_n_o[i] = edn_alert_tx_o[i].alert_n;
    assign edn_inner_alert_p_o[i] = u_dut.u_edn.alert_tx_o[i].alert_p;
    assign edn_inner_alert_n_o[i] = u_dut.u_edn.alert_tx_o[i].alert_n;
  end
  for (genvar i = 0; i < EDN_ENDPOINT_COUNT; i++) begin : gen_edn_req_valid
    assign edn_req_valid_o[i] = u_dut.edn_endpoint_req[i].edn_req;
  end
  for (genvar i = 0; i < CSRNG_NUM_HW_APPS; i++) begin : gen_csrng_hw_req_valid
    assign csrng_hw_req_valid_o[i] = u_dut.csrng_hw_req[i].csrng_req_valid;
  end

  initial begin
    clk_i = 1'b0;
    rst_ni = 1'b0;

    entropy_stream_data_i = '0;
    entropy_stream_vld_i = 1'b0;
    entropy_axis_tready_i = 1'b0;
    edn_axis_tready_i = '0;

    csrng_axil_awvalid_i = 1'b0;
    csrng_axil_awaddr_i = '0;
    csrng_axil_awprot_i = '0;
    csrng_axil_wvalid_i = 1'b0;
    csrng_axil_wdata_i = '0;
    csrng_axil_wstrb_i = '0;
    csrng_axil_bready_i = 1'b0;
    csrng_axil_arvalid_i = 1'b0;
    csrng_axil_araddr_i = '0;
    csrng_axil_arprot_i = '0;
    csrng_axil_rready_i = 1'b0;

    edn_axil_awvalid_i = 1'b0;
    edn_axil_awaddr_i = '0;
    edn_axil_awprot_i = '0;
    edn_axil_wvalid_i = 1'b0;
    edn_axil_wdata_i = '0;
    edn_axil_wstrb_i = '0;
    edn_axil_bready_i = 1'b0;
    edn_axil_arvalid_i = 1'b0;
    edn_axil_araddr_i = '0;
    edn_axil_arprot_i = '0;
    edn_axil_rready_i = 1'b0;

    otp_en_csrng_sw_app_read_i = prim_mubi_pkg::mubi8_t'(8'h96);
    lc_hw_debug_en_i = lc_ctrl_pkg::Off;
    edn_endpoint_bus_i = '0;
    edn_endpoint_fips_i = '0;
    edn_endpoint_ack_i = '0;
    edn_endpoint_force_i = '0;

    for (int i = 0; i < csrng_reg_pkg::NumAlerts; i++) begin
      csrng_alert_rx_i[i] = prim_alert_pkg::ALERT_RX_DEFAULT;
    end
    for (int i = 0; i < edn_reg_pkg::NumAlerts; i++) begin
      edn_alert_rx_i[i] = prim_alert_pkg::ALERT_RX_DEFAULT;
    end
  end

  always #5 clk_i = ~clk_i;

`ifndef VERILATOR
  initial begin
    if ($test$plusargs("waves")) begin
      $dumpfile("tb_drbg.vcd");
      $dumpvars(0, tb_drbg);
    end
  end
`endif

endmodule : tb_drbg
