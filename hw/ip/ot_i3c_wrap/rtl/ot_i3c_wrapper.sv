// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Demux one AXI-Lite slave onto NUM_I3C OpenTitan I3C instances by address.
//
// Routes bus requests to individual I3C instances based on BASE_ADDR and
// INSTANCE_SPACING; addresses outside every instance window go to instance 0.
// Each instance receives the address minus its index times INSTANCE_SPACING, truncated to
// I3C_REG_ADDR_WIDTH bits, and bridges it to TL-UL.
// The demux registers every channel and allows eight outstanding transactions.
// Bus, IRQ, and message buffer/DAT/DCT memory export ports are per-instance vectors.

module ot_i3c_wrapper
  import ot_i3c_wrap_pkg::reg_addr_t;
  import ot_i3c_wrap_pkg::reg_data_t;
  import ot_i3c_wrap_pkg::reg_strb_t;
  import ot_i3c_wrap_pkg::axil_req_t;
  import ot_i3c_wrap_pkg::axil_resp_t;
#(
  parameter int unsigned NUM_I3C = 2,                       // Number of I3C instances.
  parameter int unsigned I3C_REG_ADDR_WIDTH = ot_i3c_wrap_pkg::I3cRegAddrWidth, // Width of the instance-relative address given to each instance.
  parameter int unsigned BASE_ADDR = 0,                     // Wrapper decode base address.
  parameter int unsigned INSTANCE_SPACING = ot_i3c_wrap_pkg::I3cInstanceSpacing, // Byte size of each instance's address window.
  parameter int unsigned CLK_FREQ = 200_000_000,            // Frequency of clk_i in Hz; sets the
                                                            // I3C bus timing defaults.
  parameter int unsigned NUM_TARGETS = 2,                   // Number of target addresses each
                                                            // instance presents on the bus.

  localparam int unsigned SelectWidth = (NUM_I3C > 32'd1) ? $clog2(NUM_I3C) : 32'd1, // Instance-select width.
  localparam type select_t = logic [SelectWidth-1:0]        // Instance-select type.
) (
  input logic clk_i,                                        // System clock.
  input logic rst_ni,                                       // Async reset, active-low.
  input logic test_en_i,                                    // DFT test mode to the AXI cells and
                                                            // the instances' scan mode.
  input logic scan_rst_ni,                                  // Scan-mode reset, active-low.

  input  logic           awvalid_i,                         // Write-address valid.
  output logic           awready_o,                         // Write-address ready.
  input  reg_addr_t      awaddr_i,                          // Write address.
  input  logic [2:0]     awprot_i,                          // Write-address protection; forwarded
                                                            // but not used by the instances.

  input  logic           wvalid_i,                          // Write-data valid.
  output logic           wready_o,                          // Write-data ready.
  input  reg_data_t      wdata_i,                           // Write data.
  input  reg_strb_t      wstrb_i,                           // Write strobe.

  output logic           bvalid_o,                          // Write-response valid.
  input  logic           bready_i,                          // Write-response ready.
  output logic [1:0]     bresp_o,                           // Write response.

  input  logic           arvalid_i,                         // Read-address valid.
  output logic           arready_o,                         // Read-address ready.
  input  reg_addr_t      araddr_i,                          // Read address.
  input  logic [2:0]     arprot_i,                          // Read-address protection; forwarded
                                                            // but not used by the instances.

  output logic           rvalid_o,                          // Read-data valid.
  input  logic           rready_i,                          // Read-data ready.
  output reg_data_t      rdata_o,                           // Read data.
  output logic [1:0]     rresp_o,                           // Read response.

  output logic [NUM_I3C-1:0] irq_o,                         // Per-instance interrupt, the OR of
                                                            // the controller and target
                                                            // interrupts.

  input  logic [NUM_I3C-1:0] scl_i,                         // Per-instance SCL in.
  input  logic [NUM_I3C-1:0] sda_i,                         // Per-instance SDA in.
  output logic [NUM_I3C-1:0] scl_o,                         // Per-instance SCL level, driven
                                                            // while scl_oe_o is high.
  output logic [NUM_I3C-1:0] sda_o,                         // Per-instance SDA level, driven
                                                            // while sda_oe_o is high.
  output logic [NUM_I3C-1:0] scl_oe_o,                      // Per-instance SCL output enable.
  output logic [NUM_I3C-1:0] sda_oe_o,                      // Per-instance SDA output enable, high
                                                            // in push-pull mode or while SDA is
                                                            // low.
  output logic [NUM_I3C-1:0] sel_od_pp_o,                   // Per-instance driver mode, tied to 0
                                                            // (open-drain); sda_oe_o already
                                                            // covers push-pull.

  output ot_i3c_wrap_pkg::buf_mem_sink_t [NUM_I3C-1:0] buf_mem_sink_o, // Per-instance message
                                                                       // buffer request.
  input  ot_i3c_wrap_pkg::buf_mem_src_t  [NUM_I3C-1:0] buf_mem_src_i,  // Per-instance message
                                                                       // buffer read data.
  output ot_i3c_wrap_pkg::dat_mem_sink_t [NUM_I3C-1:0] dat_mem_sink_o, // Per-instance DAT request.
  input  ot_i3c_wrap_pkg::dat_mem_src_t  [NUM_I3C-1:0] dat_mem_src_i,  // Per-instance DAT read
                                                                       // data.
  output ot_i3c_wrap_pkg::dct_mem_sink_t [NUM_I3C-1:0] dct_mem_sink_o, // Per-instance DCT request.
  input  ot_i3c_wrap_pkg::dct_mem_src_t  [NUM_I3C-1:0] dct_mem_src_i   // Per-instance DCT read
                                                                       // data.
);

  axil_req_t [NUM_I3C-1:0] axil_req_demuxed;
  axil_resp_t [NUM_I3C-1:0] axil_resp_demuxed;

  axil_req_t axil_req;
  axil_resp_t axil_resp;

  // Pack input signals into request struct
  assign axil_req = '{
    aw: '{addr: awaddr_i, prot: awprot_i},
    aw_valid: awvalid_i,
    w: '{data: wdata_i, strb: wstrb_i},
    w_valid: wvalid_i,
    b_ready: bready_i,
    ar: '{addr: araddr_i, prot: arprot_i},
    ar_valid: arvalid_i,
    r_ready: rready_i
  };

  // Unpack response struct to outputs
  assign awready_o = axil_resp.aw_ready;
  assign wready_o = axil_resp.w_ready;
  assign bvalid_o = axil_resp.b_valid;
  assign bresp_o = axil_resp.b.resp;
  assign arready_o = axil_resp.ar_ready;
  assign rvalid_o = axil_resp.r_valid;
  assign rdata_o = axil_resp.r.data;
  assign rresp_o = axil_resp.r.resp;

  // Calculate the read and write instance selects from their addresses
  select_t read_select, write_select;
  reg_addr_t read_adjusted_addr, write_adjusted_addr;
  assign read_adjusted_addr = araddr_i - BASE_ADDR;
  assign write_adjusted_addr = awaddr_i - BASE_ADDR;

  // Instance selection based on address range (INSTANCE_SPACING per instance)
  always_comb begin
    read_select = '0;
    for (int i = 0; i < NUM_I3C; i++) begin
      if ((read_adjusted_addr >= i * INSTANCE_SPACING) &&
          (read_adjusted_addr < (i + 1) * INSTANCE_SPACING)) begin
        read_select = select_t'(i);
      end
    end

    write_select = '0;
    for (int i = 0; i < NUM_I3C; i++) begin
      if ((write_adjusted_addr >= i * INSTANCE_SPACING) &&
          (write_adjusted_addr < (i + 1) * INSTANCE_SPACING)) begin
        write_select = select_t'(i);
      end
    end
  end

  // AXI-Lite demultiplexer
  axi_lite_demux #(
    .aw_chan_t(ot_i3c_wrap_pkg::axil_aw_chan_t),
    .w_chan_t(ot_i3c_wrap_pkg::axil_w_chan_t),
    .b_chan_t(ot_i3c_wrap_pkg::axil_b_chan_t),
    .ar_chan_t(ot_i3c_wrap_pkg::axil_ar_chan_t),
    .r_chan_t(ot_i3c_wrap_pkg::axil_r_chan_t),
    .axi_req_t(axil_req_t),
    .axi_resp_t(axil_resp_t),
    .NoMstPorts(NUM_I3C),
    .MaxTrans(8),
    .FallThrough(1'b1),
    .SpillAw(1'b1),
    .SpillW(1'b1),
    .SpillB(1'b1),
    .SpillAr(1'b1),
    .SpillR(1'b1)
  ) u_axil_demux (
    .clk_i(clk_i),
    .rst_ni(rst_ni),
    .test_i(test_en_i),
    .slv_req_i(axil_req),
    .slv_aw_select_i(write_select),
    .slv_ar_select_i(read_select),
    .slv_resp_o(axil_resp),
    .mst_reqs_o(axil_req_demuxed),
    .mst_resps_i(axil_resp_demuxed)
  );

  // Generate I3C instances
  for (genvar idx = 0; idx < NUM_I3C; idx++) begin : gen_i3c_inst
    axil_req_t inst_req;
    tlul_pkg::tl_h2d_t tl_h2d;
    tlul_pkg::tl_d2h_t tl_d2h;
    i3c_pkg::i3c_rstdet_req_t rstdet_req;
    i3c_pkg::i3c_rstdet_rsp_t rstdet_rsp;
    logic rstdet_enable;
    logic intr_hci;
    logic intr_targ;

    // Calculate instance-relative addresses by subtracting base offset
    logic [I3C_REG_ADDR_WIDTH-1:0] awaddr_offset;
    logic [I3C_REG_ADDR_WIDTH-1:0] araddr_offset;
    assign awaddr_offset = axil_req_demuxed[idx].aw.addr - idx * INSTANCE_SPACING;
    assign araddr_offset = axil_req_demuxed[idx].ar.addr - idx * INSTANCE_SPACING;

    // The I3C register block decodes 13 address bits; the upper half is the direct
    // message buffer window, which SWDirectMsgBuf = 0 removes.
    always_comb begin
      inst_req = axil_req_demuxed[idx];
      inst_req.aw.addr = reg_addr_t'(awaddr_offset);
      inst_req.ar.addr = reg_addr_t'(araddr_offset);
    end

    axi_lite_to_tlul #(
      .axi_lite_req_t(axil_req_t),
      .axi_lite_rsp_t(axil_resp_t)
    ) u_axil2tl (
      .clk_i(clk_i),
      .rst_ni(rst_ni),
      .axi_lite_req_i(inst_req),
      .axi_lite_rsp_o(axil_resp_demuxed[idx]),
      .tl_o(tl_h2d),
      .tl_i(tl_d2h),
      .err_o(),
      .err_clr_i(1'b0)
    );

    i3c_part_primary #(
      .ClkFreq(CLK_FREQ),
      .NumTargets(NUM_TARGETS),
      .SWDirectMsgBuf(1'b0),
      .EnableRacl(1'b0)
    ) u_i3c (
      .clk_i(clk_i),
      .rst_ni(rst_ni),
      .clk_aon_i(clk_i),
      .rst_aon_ni(rst_ni),

      .tl_i(tl_h2d),
      .tl_o(tl_d2h),

      .alert_rx_i({i3c_reg_pkg::NumAlerts{prim_alert_pkg::ALERT_RX_DEFAULT}}),
      .alert_tx_o(),
      .racl_policies_i('0),
      .racl_error_o(),

      // I3C bus signals
      .cio_scl_i(scl_i[idx]),
      .cio_scl_o(scl_o[idx]),
      .cio_scl_en_o(scl_oe_o[idx]),
      .cio_sda_i(sda_i[idx]),
      .cio_sda_o(sda_o[idx]),
      .cio_sda_en_o(sda_oe_o[idx]),
      .ctrl_scl_pu_en_o(),
      .cio_ctrl_sda_pu_o(),
      .cio_ctrl_sda_pu_en_o(),
      .scl_hk_en_o(),
      .sda_hk_en_o(),

      // Target Reset Detector
      .rstdet_enable_o(rstdet_enable),
      .rstdet_o(rstdet_req),
      .rstdet_i(rstdet_rsp),

      .intr_hci_o(intr_hci),
      .intr_targ_o(intr_targ),

      // Memory interfaces
      .buf_mem_req_o(buf_mem_sink_o[idx].req),
      .buf_mem_write_o(buf_mem_sink_o[idx].write),
      .buf_mem_addr_o(buf_mem_sink_o[idx].addr),
      .buf_mem_wdata_o(buf_mem_sink_o[idx].wdata),
      .buf_mem_wmask_o(buf_mem_sink_o[idx].wmask),
      .buf_mem_rdata_i(buf_mem_src_i[idx].rdata),
      .dat_mem_req_o(dat_mem_sink_o[idx].req),
      .dat_mem_write_o(dat_mem_sink_o[idx].write),
      .dat_mem_addr_o(dat_mem_sink_o[idx].addr),
      .dat_mem_wdata_o(dat_mem_sink_o[idx].wdata),
      .dat_mem_wmask_o(dat_mem_sink_o[idx].wmask),
      .dat_mem_rdata_i(dat_mem_src_i[idx].rdata),
      .dct_mem_req_o(dct_mem_sink_o[idx].req),
      .dct_mem_write_o(dct_mem_sink_o[idx].write),
      .dct_mem_addr_o(dct_mem_sink_o[idx].addr),
      .dct_mem_wdata_o(dct_mem_sink_o[idx].wdata),
      .dct_mem_wmask_o(dct_mem_sink_o[idx].wmask),
      .dct_mem_rdata_i(dct_mem_src_i[idx].rdata),

      // DFT
      .ram_cfg_i('0),
      .ram_cfg_o(),
      .dat_cfg_i('0),
      .dat_cfg_o(),
      .dct_cfg_i('0),
      .dct_cfg_o(),
      .mbist_en_i(1'b0),
      .scan_clk_i(clk_i),
      .scan_rst_ni(scan_rst_ni),
      .scanmode_i(test_en_i ? prim_mubi_pkg::MuBi4True : prim_mubi_pkg::MuBi4False)
    );

    assign buf_mem_sink_o[idx].clk = clk_i;
    assign dat_mem_sink_o[idx].clk = clk_i;
    assign dct_mem_sink_o[idx].clk = clk_i;

    i3c_part_secondary u_i3c_rstdet (
      .clk_aon_i(clk_i),
      .rst_aon_ni(rst_ni),
      .cio_rstdet_scl_i(scl_i[idx]),
      .cio_rstdet_sda_i(sda_i[idx]),
      .rstdet_enable_i(rstdet_enable),
      .rstdet_i(rstdet_req),
      .rstdet_o(rstdet_rsp),
      .rstdet_wkup_req_o(),
      .rstdet_target_rst_o()
    );

    assign sel_od_pp_o[idx] = 1'b0;
    assign irq_o[idx] = intr_hci | intr_targ;

  end : gen_i3c_inst

endmodule
