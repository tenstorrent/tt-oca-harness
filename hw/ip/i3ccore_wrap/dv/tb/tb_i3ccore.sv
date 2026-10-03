// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

`timescale 1ns / 1ps

/*************************************************************************
 * Testbench for i3ccore_wrapper.
 *
 * BEHAVIORAL STUB / PEER TOPOLOGY:
 *   NumI3c=2 instances of the same i3ccore RTL act as controller + target
 *   peers on a shared open-drain bus. This is a same-RTL loopback peer, NOT
 *   an independent third-party I3C target model. Interop / multi-vendor
 *   claims are out of scope for tests that only exercise this harness.
 *
 *   +i3c_vip_target replaces the instance-1 peer with a cocotb VIP target
 *   driving vip_scl_o / vip_sda_o, which makes the responder independent of
 *   the RTL under test.
 *************************************************************************/

// DAT/DCT depths and the rest of the core's build-time configuration come from the
// vendored i3c-core header, not I3CCSR_pkg, which PeakRDL populates with only
// I3CCSR_DATA_WIDTH / I3CCSR_MIN_ADDR_WIDTH. The `I3C_CONFIG` guard makes this
// include safe after i3c.sv has already pulled it into the compile unit.
`include "i3c_defines.svh"

module tb_i3ccore;

  import i3ccore_wrap_pkg::*;

  // Parameters matching DUT defaults
  localparam int unsigned NumI3c = 2;
  localparam int unsigned I3cRegAddrWidth = 12;
  localparam int unsigned BaseAddr = 0;

  // Clock and reset
  logic clk;
  logic rst_n;

  // Generate clock - 100MHz (10ns period)
  initial begin
    clk = 0;
    forever #5 clk = ~clk;
  end

  // Reset generation
  initial begin
    rst_n = 0;
    repeat (10) @(posedge clk);
    rst_n = 1;
  end

  //--------------------------------------------------------------------------
  // AXI-Lite signals, flattened with the "axi" prefix that cocotb's
  // AxiLiteBus.from_prefix(dut, "axi") expects.
  //--------------------------------------------------------------------------

  // Write Address Channel
  logic [31:0] axi_awaddr;
  logic [2:0]  axi_awprot;
  logic        axi_awvalid;
  logic        axi_awready;

  // Write Data Channel
  logic [31:0] axi_wdata;
  logic [3:0]  axi_wstrb;
  logic        axi_wvalid;
  logic        axi_wready;

  // Write Response Channel
  logic [1:0]  axi_bresp;
  logic        axi_bvalid;
  logic        axi_bready;

  // Read Address Channel
  logic [31:0] axi_araddr;
  logic [2:0]  axi_arprot;
  logic        axi_arvalid;
  logic        axi_arready;

  // Read Data Channel
  logic [31:0] axi_rdata;
  logic [1:0]  axi_rresp;
  logic        axi_rvalid;
  logic        axi_rready;

  //--------------------------------------------------------------------------
  // I3C bus signals
  //--------------------------------------------------------------------------
  logic [NumI3c-1:0] scl_i;
  logic [NumI3c-1:0] sda_i;
  logic [NumI3c-1:0] scl_o;
  logic [NumI3c-1:0] sda_o;
  logic [NumI3c-1:0] scl_oe;
  logic [NumI3c-1:0] sda_oe;
  logic [NumI3c-1:0] sel_od_pp;

  //--------------------------------------------------------------------------
  // Interrupt and recovery signals
  //--------------------------------------------------------------------------
  logic [NumI3c-1:0] irq;
  logic [NumI3c-1:0] recovery_payload_available;
  logic [NumI3c-1:0] recovery_image_activated;
  logic [NumI3c-1:0] peripheral_reset;
  logic [NumI3c-1:0] peripheral_reset_done;
  logic [NumI3c-1:0] escalated_reset;

  //--------------------------------------------------------------------------
  // DAT/DCT external memory: the wrapper expects these SRAMs instantiated
  // externally (as the SMC does); modeled by gen_i3c_mem below.
  //--------------------------------------------------------------------------
  i3c_pkg::dat_mem_src_t  [NumI3c-1:0] dat_mem_src;
  i3c_pkg::dat_mem_sink_t [NumI3c-1:0] dat_mem_sink;
  i3c_pkg::dct_mem_src_t  [NumI3c-1:0] dct_mem_src;
  i3c_pkg::dct_mem_sink_t [NumI3c-1:0] dct_mem_sink;
  i3c_pkg::rlt_mem_src_t  [NumI3c-1:0] rlt_mem_src;
  i3c_pkg::rlt_mem_sink_t [NumI3c-1:0] rlt_mem_sink;

  //--------------------------------------------------------------------------
  // I3C Shared Bus Model for Controller-Target Communication
  // Instance 0 = Controller, Instance 1 = Target
  //--------------------------------------------------------------------------

  // Independent bus partner: a cocotb VIP target drives these open-drain lines in
  // place of instance 1. Released high, so a run without a VIP attached leaves the
  // shared bus unchanged.
  logic vip_scl_o;
  logic vip_sda_o;
  initial begin
    vip_scl_o = 1'b1;
    vip_sda_o = 1'b1;
  end

  // +i3c_vip_target takes the RTL target peer off the bus so the VIP is the only
  // responder. Sampled at time 0 to keep the bus expressions continuous.
  logic rtl_tgt_on_bus;
  initial rtl_tgt_on_bus = !$test$plusargs("i3c_vip_target");

  // SCL: open-drain with pull-up (like SDA) — pulled low only when a device's pad
  // is enabled and driving 0 (scl_o tied 0, OE carries drive). scl_oe must not
  // feed scl_i directly, or a device would see its own drive as the bus level.
  wire scl_shared = ((scl_oe[0] && !scl_o[0]) ||
                       (rtl_tgt_on_bus && scl_oe[1] && !scl_o[1]) ||
                       !vip_scl_o) ? 1'b0 : 1'b1;
  assign scl_i[0] = scl_shared;
  assign scl_i[1] = scl_shared;

  // SDA: Open-drain, both can drive (target needs to ACK/send data)
  wire sda_raw = ((sda_oe[0] && !sda_o[0]) ||
                    (rtl_tgt_on_bus && sda_oe[1] && !sda_o[1]) ||
                    !vip_sda_o) ? 1'b0 : 1'b1;

  // Bus-level bit-flip injection for error tests: cocotb drives sda_corrupt, so it
  // must keep no continuous driver. A zero value leaves the shared SDA unchanged.
  logic sda_corrupt;
  initial sda_corrupt = 1'b0;

  wire sda_shared = sda_raw ^ sda_corrupt;
  assign sda_i[0] = sda_shared;
  assign sda_i[1] = sda_shared;

  //--------------------------------------------------------------------------
  // Initialize inputs
  //--------------------------------------------------------------------------
  initial begin
    // AXI-Lite inputs - all invalid/idle
    axi_awaddr = '0;
    axi_awprot = '0;
    axi_awvalid = 1'b0;

    axi_wdata = '0;
    axi_wstrb = 4'hF;
    axi_wvalid = 1'b0;

    axi_bready = 1'b1;

    axi_araddr = '0;
    axi_arprot = '0;
    axi_arvalid = 1'b0;

    axi_rready = 1'b1;

    // Recovery interface - tie off
    peripheral_reset_done = '0;
  end

  //--------------------------------------------------------------------------
  // DUT instantiation
  //--------------------------------------------------------------------------
  i3ccore_wrapper #(
    .NUM_I3C(NumI3c),
    .I3C_REG_ADDR_WIDTH(I3cRegAddrWidth),
    .BASE_ADDR(BaseAddr),
    // The spacing must cover each instance's 0x1000-byte address window.
    .INSTANCE_SPACING(32'h1000)
  ) u_dut (
    .clk_i(clk),
    .rst_ni(rst_n),

    // AXI-Lite Write Address Channel
    .awvalid_i(axi_awvalid),
    .awready_o(axi_awready),
    .awaddr_i(axi_awaddr),
    .awprot_i(axi_awprot),

    // AXI-Lite Write Data Channel
    .wvalid_i(axi_wvalid),
    .wready_o(axi_wready),
    .wdata_i(axi_wdata),
    .wstrb_i(axi_wstrb),

    // AXI-Lite Write Response Channel
    .bvalid_o(axi_bvalid),
    .bready_i(axi_bready),
    .bresp_o(axi_bresp),

    // AXI-Lite Read Address Channel
    .arvalid_i(axi_arvalid),
    .arready_o(axi_arready),
    .araddr_i(axi_araddr),
    .arprot_i(axi_arprot),

    // AXI-Lite Read Data Channel
    .rvalid_o(axi_rvalid),
    .rready_i(axi_rready),
    .rdata_o(axi_rdata),
    .rresp_o(axi_rresp),

    // I3C bus signals
    .scl_i(scl_i),
    .sda_i(sda_i),
    .scl_o(scl_o),
    .sda_o(sda_o),
    .scl_oe_o(scl_oe),
    .sda_oe_o(sda_oe),
    .sel_od_pp_o(sel_od_pp),

    // Interrupts
    .irq_o(irq),

    // Recovery interface
    .recovery_payload_available_o(recovery_payload_available),
    .recovery_image_activated_o(recovery_image_activated),
    .peripheral_reset_o(peripheral_reset),
    .peripheral_reset_done_i(peripheral_reset_done),
    .escalated_reset_o(escalated_reset),

    // DAT/DCT external memory interface (modeled below)
    .dat_mem_src_i (dat_mem_src),
    .dat_mem_sink_o(dat_mem_sink),
    .dct_mem_src_i (dct_mem_src),
    .dct_mem_sink_o(dct_mem_sink),
    .rlt_mem_src_i (rlt_mem_src),
    .rlt_mem_sink_o(rlt_mem_sink)
  );

  //--------------------------------------------------------------------------
  // DAT/DCT/RLT memory. DAT and DCT default to single-cycle write-forwarding behavioral
  // models: read data must be valid one cycle after the request, because flow_active
  // captures it on the following cycle. Define I3C_SRAM_DAT_MEM to select compatible
  // SRAM implementations instead.
  //--------------------------------------------------------------------------
`ifndef I3C_SRAM_DAT_MEM
  for (genvar gi = 0; gi < NumI3c; gi++) begin : gen_i3c_mem
    logic [63:0]  dat_arr [0:(1<<i3c_pkg::DatAw)-1];
    logic [127:0] dct_arr [0:(1<<i3c_pkg::DctAw)-1];
    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) begin
        for (int k = 0; k < (1 << i3c_pkg::DatAw); k++) dat_arr[k] <= '0;
        dat_mem_src[gi].rdata <= '0;
        dat_mem_src[gi].rvalid <= 1'b0;
        dat_mem_src[gi].rerror <= '0;
      end else begin
        dat_mem_src[gi].rvalid <= 1'b0;
        dat_mem_src[gi].rerror <= '0;
        if (dat_mem_sink[gi].req) begin
          logic [63:0] nv;
          nv = (dat_mem_sink[gi].wdata & dat_mem_sink[gi].wmask) |
                         (dat_arr[dat_mem_sink[gi].addr] & ~dat_mem_sink[gi].wmask);
          if (dat_mem_sink[gi].write) dat_arr[dat_mem_sink[gi].addr] <= nv;
          dat_mem_src[gi].rdata  <= dat_mem_sink[gi].write ? nv : dat_arr[dat_mem_sink[gi].addr];
          dat_mem_src[gi].rvalid <= 1'b1;
        end
      end
    end
    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) begin
        for (int k = 0; k < (1 << i3c_pkg::DctAw); k++) dct_arr[k] <= '0;
        dct_mem_src[gi].rdata <= '0;
        dct_mem_src[gi].rvalid <= 1'b0;
        dct_mem_src[gi].rerror <= '0;
      end else begin
        dct_mem_src[gi].rvalid <= 1'b0;
        dct_mem_src[gi].rerror <= '0;
        if (dct_mem_sink[gi].req) begin
          logic [127:0] nv;
          nv = (dct_mem_sink[gi].wdata & dct_mem_sink[gi].wmask) |
                         (dct_arr[dct_mem_sink[gi].addr] & ~dct_mem_sink[gi].wmask);
          if (dct_mem_sink[gi].write) dct_arr[dct_mem_sink[gi].addr] <= nv;
          dct_mem_src[gi].rdata  <= dct_mem_sink[gi].write ? nv : dct_arr[dct_mem_sink[gi].addr];
          dct_mem_src[gi].rvalid <= 1'b1;
        end
      end
    end
    // RLT dual-port behavioral model (DatAw-bit wide, addr[6:0] => 128 deep)
    logic [i3c_pkg::DatAw-1:0] rlt_arr[0:127];
    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) begin
        for (int k = 0; k < 128; k++) rlt_arr[k] <= '0;
        rlt_mem_src[gi].a_rdata <= '0;
        rlt_mem_src[gi].b_rdata <= '0;
      end else begin
        if (rlt_mem_sink[gi].a_req) begin
          if (rlt_mem_sink[gi].a_write)
            rlt_arr[rlt_mem_sink[gi].a_addr] <=
                            (rlt_mem_sink[gi].a_wdata &  rlt_mem_sink[gi].a_wmask) |
                            (rlt_arr[rlt_mem_sink[gi].a_addr] & ~rlt_mem_sink[gi].a_wmask);
          rlt_mem_src[gi].a_rdata <= rlt_arr[rlt_mem_sink[gi].a_addr];
        end
        if (rlt_mem_sink[gi].b_req) begin
          if (rlt_mem_sink[gi].b_write)
            rlt_arr[rlt_mem_sink[gi].b_addr] <=
                            (rlt_mem_sink[gi].b_wdata &  rlt_mem_sink[gi].b_wmask) |
                            (rlt_arr[rlt_mem_sink[gi].b_addr] & ~rlt_mem_sink[gi].b_wmask);
          rlt_mem_src[gi].b_rdata <= rlt_arr[rlt_mem_sink[gi].b_addr];
        end
      end
    end
  end : gen_i3c_mem
`else
  for (genvar gi = 0; gi < NumI3c; gi++) begin : gen_i3c_mem
    // DAT memory (64-bit). EnableOutputPipeline=0: flow_active captures DAT data
    // 1 cycle after the read request, so a 2-cycle read makes it sample X.
    prim_ram_1p_adv #(
      .Depth              (`DAT_DEPTH  + 1),
      .Width              (64),
      .DataBitsPerMask    (32),
      .EnableOutputPipeline(0)
    ) u_i3c_dat_memory (
      .clk_i   (clk),
      .rst_ni  (rst_n),
      .req_i   (dat_mem_sink[gi].req),
      .write_i (dat_mem_sink[gi].write),
      .addr_i  (dat_mem_sink[gi].addr),
      .wdata_i (dat_mem_sink[gi].wdata),
      .wmask_i (dat_mem_sink[gi].wmask),
      .rdata_o (dat_mem_src[gi].rdata),
      .rvalid_o(dat_mem_src[gi].rvalid),
      .rerror_o(dat_mem_src[gi].rerror),
      .cfg_i   ('0)
    );

    // DCT memory (128-bit wide)
    prim_ram_1p_adv #(
      .Depth              (`DCT_DEPTH + 1),
      .Width              (128),
      .DataBitsPerMask    (32),
      .EnableOutputPipeline(0)
    ) u_i3c_dct_memory (
      .clk_i   (clk),
      .rst_ni  (rst_n),
      .req_i   (dct_mem_sink[gi].req),
      .write_i (dct_mem_sink[gi].write),
      .addr_i  (dct_mem_sink[gi].addr),
      .wdata_i (dct_mem_sink[gi].wdata),
      .wmask_i (dct_mem_sink[gi].wmask),
      .rdata_o (dct_mem_src[gi].rdata),
      .rvalid_o(dct_mem_src[gi].rvalid),
      .rerror_o(dct_mem_src[gi].rerror),
      .cfg_i   ('0)
    );

    // RLT (reverse-lookup table) memory (dual-port, DatAw-bit wide, addr[6:0] => 128 deep)
    prim_ram_2p #(
      .Depth          (128),
      .Width          (i3c_pkg::DatAw),
      .DataBitsPerMask(1)
    ) u_i3c_rlt_memory (
      .clk_a_i (clk),
      .clk_b_i (clk),
      .a_req_i  (rlt_mem_sink[gi].a_req),
      .a_write_i(rlt_mem_sink[gi].a_write),
      .a_addr_i (rlt_mem_sink[gi].a_addr),
      .a_wdata_i(rlt_mem_sink[gi].a_wdata),
      .a_wmask_i(rlt_mem_sink[gi].a_wmask),
      .a_rdata_o(rlt_mem_src[gi].a_rdata),
      .b_req_i  (rlt_mem_sink[gi].b_req),
      .b_write_i(rlt_mem_sink[gi].b_write),
      .b_addr_i (rlt_mem_sink[gi].b_addr),
      .b_wdata_i(rlt_mem_sink[gi].b_wdata),
      .b_wmask_i(rlt_mem_sink[gi].b_wmask),
      .b_rdata_o(rlt_mem_src[gi].b_rdata),
      .cfg_i    ('0),
      .cfg_rsp_o()
    );
  end : gen_i3c_mem
`endif

  //--------------------------------------------------------------------------
  // Functional coverage interface (sampling guarded by +define+I3C_COVERAGE)
  // Observes the shared I3C bus, OD/PP mode, interrupts, and AXI cmd/resp ports.
  //--------------------------------------------------------------------------
  i3c_coverage_if u_i3c_cov (
    .clk      (clk),
    .scl      (scl_shared),
    .sda      (sda_shared),
    .sel_od_pp(sel_od_pp[0]),
    .irq      (irq),
    .awvalid  (axi_awvalid),
    .awready  (axi_awready),
    .awaddr   (axi_awaddr),
    .wvalid   (axi_wvalid),
    .wready   (axi_wready),
    .wdata    (axi_wdata),
    .arvalid  (axi_arvalid),
    .arready  (axi_arready),
    .araddr   (axi_araddr),
    .rvalid   (axi_rvalid),
    .rready   (axi_rready),
    .rdata    (axi_rdata)
  );

  initial begin
    $display("I3C Core Wrapper Testbench starting...");

    wait (rst_n);
    repeat (100) @(posedge clk);

    $display("I3C Core Wrapper Testbench: basic compilation check finished (not a test verdict)");
  end

endmodule : tb_i3ccore
