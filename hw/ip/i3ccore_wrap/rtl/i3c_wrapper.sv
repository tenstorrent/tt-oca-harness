// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Wrap one I3C core with AXI-Lite CSRs and exported DAT/DCT/RLT memories.
//
// Adapted from i3c-core/src/i3c_wrapper.sv and maintained in-tree for the full-AXI4 core
// with open-drain SCL.
// Each AXI-Lite access reaches the core as a single-beat AXI4 burst with ID and user zero.
// SCL is open-drain: scl_o is tied low and scl_oe_o pulls the line; SDA drives through
// sda_oe_o in push-pull mode or when low.
// DummyParam exists only for trailing-comma handling in the parameter list.
// The DAT, DCT, and RLT memory ports require the CONTROLLER_SUPPORT macro, since the core
// declares them only when it is defined.

module i3c_wrapper #(
  parameter int unsigned AxiLiteDataWidth = 32,             // Data width of the AXI-Lite CSR port;
                                                            // also sets the beat size given to the
                                                            // core.
  parameter int unsigned AxiLiteAddrWidth = 32,             // AXI-Lite address width.
  parameter int unsigned DatAw = i3c_pkg::DatAw,            // DAT memory address width.
  parameter int unsigned DctAw = i3c_pkg::DctAw,            // DCT memory address width.

  parameter int unsigned CsrAddrWidth = I3CCSR_pkg::I3CCSR_MIN_ADDR_WIDTH, // CSR address width.
  parameter int unsigned CsrDataWidth = I3CCSR_pkg::I3CCSR_DATA_WIDTH, // Data width of the I3C core's internal CSR interface.

  parameter int unsigned DummyParam = 0                     // Trailing-comma placeholder.
) (
  input clk_i,                                              // System clock.
  input rst_ni,                                             // Async reset, active-low.

  input  logic                           awvalid_i,         // Write-address valid.
  output logic                           awready_o,         // Write-address ready.
  input  logic [AxiLiteAddrWidth-1:0]    awaddr_i,          // Write byte address into the I3C
                                                            // core's CSR space.
  input  logic [2:0]                     awprot_i,          // Write-address protection; not used.

  input  logic                           wvalid_i,          // Write-data valid.
  output logic                           wready_o,          // Write-data ready.
  input  logic [AxiLiteDataWidth-1:0]    wdata_i,           // Write data.
  input  logic [AxiLiteDataWidth/8-1:0]  wstrb_i,           // Write strobe.

  output logic                           bvalid_o,          // Write-response valid.
  input  logic                           bready_i,          // Write-response ready.
  output logic [1:0]                     bresp_o,           // Write response.

  input  logic                           arvalid_i,         // Read-address valid.
  output logic                           arready_o,         // Read-address ready.
  input  logic [AxiLiteAddrWidth-1:0]    araddr_i,          // Read address.
  input  logic [2:0]                     arprot_i,          // Read-address protection; not used.

  output logic                           rvalid_o,          // Read-data valid.
  input  logic                           rready_i,          // Read-data ready.
  output logic [AxiLiteDataWidth-1:0]    rdata_o,           // Read data.
  output logic [1:0]                     rresp_o,           // Read response.

  input  logic scl_i,                                       // SCL pad input, passed straight to the
                                                            // core.
  input  logic sda_i,                                       // SDA pad input, passed straight to the
                                                            // core.
  output logic scl_o,                                       // SCL pad output, tied low; scl_oe_o
                                                            // controls the line.
  output logic sda_o,                                       // SDA bus level from the core; the pad
                                                            // drives it while sda_oe_o is high.
  output logic scl_oe_o,                                    // SCL output enable, high while the
                                                            // core pulls SCL low.
  output logic sda_oe_o,                                    // SDA output enable, high in push-pull
                                                            // mode or while sda_o is low.

  output logic sel_od_pp_o,                                 // Driver mode from the core: 0
                                                            // open-drain, 1 push-pull.

  output logic recovery_payload_available_o,                // High when the recovery handler has a
                                                            // payload available for the recovery
                                                            // agent.
  output logic recovery_image_activated_o,                  // High while
                                                            // RECOVERY_CTRL.ACTIVATE_REC_IMG holds
                                                            // the activate-image value 0x0F.

  output logic peripheral_reset_o,                          // Set on a target reset pattern
                                                            // selecting peripheral reset; cleared
                                                            // by peripheral_reset_done_i.
  input  logic peripheral_reset_done_i,                     // Acknowledges peripheral_reset_o and
                                                            // clears it.
  output logic escalated_reset_o,                           // Set on an escalated target reset
                                                            // pattern; stays high until rst_ni.

  output irq_o,                                             // OR of the core's controller, target
                                                            // transaction and recovery interrupts.

  input  i3c_pkg::dat_mem_src_t  dat_mem_src_i,             // DAT memory read data; requires
                                                            // CONTROLLER_SUPPORT.
  output i3c_pkg::dat_mem_sink_t dat_mem_sink_o,            // DAT memory request; requires
                                                            // CONTROLLER_SUPPORT.

  input  i3c_pkg::dct_mem_src_t  dct_mem_src_i,             // DCT memory read data; requires
                                                            // CONTROLLER_SUPPORT.
  output i3c_pkg::dct_mem_sink_t dct_mem_sink_o,            // DCT memory request; requires
                                                            // CONTROLLER_SUPPORT.

  input  i3c_pkg::rlt_mem_src_t  rlt_mem_src_i,             // Reverse-lookup table memory read
                                                            // data; requires CONTROLLER_SUPPORT.
  output i3c_pkg::rlt_mem_sink_t rlt_mem_sink_o             // Reverse-lookup table memory request;
                                                            // requires CONTROLLER_SUPPORT.
);

  logic core_scl_o;   // core SCL output is the bus level (1=release), not a pad OE
  logic core_sda_oe;  // core drives this only in target mode (tied 0 for active controller)

  i3c #(
    .AxiDataWidth(AxiLiteDataWidth),
    .AxiAddrWidth(AxiLiteAddrWidth),
    .AxiUserWidth(32),
    .AxiIdWidth(1),

    .CsrDataWidth(CsrDataWidth),
    .CsrAddrWidth(CsrAddrWidth),
    .DatAw(DatAw),
    .DctAw(DctAw)
  ) u_i3c (
    .clk_i,
    .rst_ni,

    // AXI4 Write Address Channel (AXI-Lite -> AXI4, single beat)
    .awaddr_i (AxiLiteAddrWidth'(awaddr_i)),
    .awburst_i(2'b01),                       // INCR; irrelevant for awlen==0
    .awsize_i (3'($clog2(AxiLiteDataWidth/8))),
    .awlen_i  (8'd0),
    .awuser_i ({32{1'b0}}),
    .awid_i   ({1{1'b0}}),
    .awlock_i (1'b0),
    .awvalid_i(awvalid_i),
    .awready_o(awready_o),

    // AXI4 Write Data Channel
    .wdata_i (wdata_i),
    .wstrb_i (wstrb_i),
    .wuser_i ({32{1'b0}}),
    .wlast_i (1'b1),
    .wvalid_i(wvalid_i),
    .wready_o(wready_o),

    // AXI4 Write Response Channel
    .bresp_o (bresp_o),
    .bid_o   (),
    .buser_o (),
    .bvalid_o(bvalid_o),
    .bready_i(bready_i),

    // AXI4 Read Address Channel
    .araddr_i (AxiLiteAddrWidth'(araddr_i)),
    .arburst_i(2'b01),
    .arsize_i (3'($clog2(AxiLiteDataWidth/8))),
    .arlen_i  (8'd0),
    .aruser_i ({32{1'b0}}),
    .arid_i   ({1{1'b0}}),
    .arlock_i (1'b0),
    .arvalid_i(arvalid_i),
    .arready_o(arready_o),

    // AXI4 Read Data Channel
    .rdata_o (rdata_o),
    .rresp_o (rresp_o),
    .rid_o   (),
    .ruser_o (),
    .rlast_o (),
    .rvalid_o(rvalid_o),
    .rready_i(rready_i),


    .i3c_scl_i  (scl_i),
    .i3c_scl_o  (core_scl_o),
    .i3c_sda_i  (sda_i),
    .i3c_sda_o  (sda_o),
    .sel_od_pp_o(sel_od_pp_o),
    .i3c_sda_oe_o(core_sda_oe),

    .dat_mem_src_i (dat_mem_src_i),   // Pass through from wrapper ports
    .dat_mem_sink_o(dat_mem_sink_o),  // Pass through to wrapper ports (driven by i3c.sv)

    .dct_mem_src_i (dct_mem_src_i),   // Pass through from wrapper ports
    .dct_mem_sink_o(dct_mem_sink_o),  // Pass through to wrapper ports (driven by i3c.sv)

    .rlt_mem_src_i (rlt_mem_src_i),   // Pass through from wrapper ports
    .rlt_mem_sink_o(rlt_mem_sink_o),  // Pass through to wrapper ports (driven by i3c.sv)

    .recovery_payload_available_o(recovery_payload_available_o),
    .recovery_image_activated_o  (recovery_image_activated_o),

    .peripheral_reset_o(peripheral_reset_o),
    .peripheral_reset_done_i(peripheral_reset_done_i),
    .escalated_reset_o(escalated_reset_o),
    .irq_o(irq_o)
  );

  // Open-drain pad OE derived here (core gives bus levels, not OE, in controller mode):
  // drive low only; push-pull (sel_od_pp_o) drives both.
  assign scl_o    = 1'b0;
  assign scl_oe_o = ~core_scl_o;
  assign sda_oe_o = sel_od_pp_o | ~sda_o;

endmodule
