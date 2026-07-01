// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

/*************************************************************************
 * I3C Core Wrapper Testbench - Lightweight testbench for i3ccore_wrapper
 *
 * This testbench instantiates the i3ccore_wrapper module and provides:
 * - Clock and reset generation
 * - Flattened AXI-Lite signals for cocotb access
 * - I3C bus signals with open-drain modeling
 * - FSDB waveform dumping support
 *************************************************************************/

module tb_i3ccore;

    import i3ccore_wrap_pkg::*;

    // Parameters matching DUT defaults
    localparam int unsigned NUM_I3C = 2;
    localparam int unsigned I3C_REG_ADDR_WIDTH = 12;
    localparam int unsigned BASE_ADDR = 0;

    // Clock and reset
    logic clk;
    logic rst_n;

    // Generate clock - 100MHz (10ns period)
    initial begin
        clk = 0;
        forever #5 clk = ~clk;
    end

    // Reset generation - release after 10 clock cycles
    initial begin
        rst_n = 0;
        repeat (10) @(posedge clk);
        rst_n = 1;
    end

    //--------------------------------------------------------------------------
    // AXI-Lite interface signals - flattened for cocotb AxiLiteBus.from_prefix
    // Prefix: axi (for AxiLiteBus.from_prefix(dut, "axi"))
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
    // I3C bus signals - directly connected (no struct unpacking needed)
    //--------------------------------------------------------------------------
    logic [NUM_I3C-1:0] scl_i;
    logic [NUM_I3C-1:0] sda_i;
    logic [NUM_I3C-1:0] scl_o;
    logic [NUM_I3C-1:0] sda_o;
    logic [NUM_I3C-1:0] scl_oe;
    logic [NUM_I3C-1:0] sda_oe;
    logic [NUM_I3C-1:0] sel_od_pp;

    // Combined bus signals for open-drain modeling
    // The bus value is the AND of all drivers (open-drain with pull-up)
    logic [NUM_I3C-1:0] scl_bus;
    logic [NUM_I3C-1:0] sda_bus;

    //--------------------------------------------------------------------------
    // Interrupt and recovery signals
    //--------------------------------------------------------------------------
    logic [NUM_I3C-1:0] irq;
    logic [NUM_I3C-1:0] recovery_payload_available;
    logic [NUM_I3C-1:0] recovery_image_activated;
    logic [NUM_I3C-1:0] peripheral_reset;
    logic [NUM_I3C-1:0] peripheral_reset_done;
    logic [NUM_I3C-1:0] escalated_reset;

    //--------------------------------------------------------------------------
    // DAT/DCT external memory interface
    // The i3ccore_wrapper expects the Device Address Table / Device
    // Characteristics Table SRAMs to be instantiated externally (as the SMC
    // integration does). Without them, DAT reads return X and SETDASA sends an
    // X address. Modeled by the behavioral SRAM in gen_i3c_mem below.
    //--------------------------------------------------------------------------
    i3c_pkg::dat_mem_src_t  [NUM_I3C-1:0] dat_mem_src;
    i3c_pkg::dat_mem_sink_t [NUM_I3C-1:0] dat_mem_sink;
    i3c_pkg::dct_mem_src_t  [NUM_I3C-1:0] dct_mem_src;
    i3c_pkg::dct_mem_sink_t [NUM_I3C-1:0] dct_mem_sink;

    //--------------------------------------------------------------------------
    // I3C Shared Bus Model for Controller-Target Communication
    // Instance 0 = Controller, Instance 1 = Target
    //--------------------------------------------------------------------------

    // SCL: Controller (instance 0) drives, target (instance 1) only reads
    // (I3C targets cannot drive SCL - no clock stretching)
    assign scl_i[0] = scl_o[0];  // Controller sees its own SCL
    assign scl_i[1] = scl_o[0];  // Target sees controller's SCL

    // SDA: Open-drain, both can drive (target needs to ACK/send data)
    // Bus is LOW if either device pulls it low, otherwise HIGH (pull-up)
    wire sda_shared = ((sda_oe[0] && !sda_o[0]) || (sda_oe[1] && !sda_o[1])) ? 1'b0 : 1'b1;
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
        .NUM_I3C(NUM_I3C),
        .I3C_REG_ADDR_WIDTH(I3C_REG_ADDR_WIDTH),
        .BASE_ADDR(BASE_ADDR),
        // Instance window must match the per-instance register map (DAT@0x400,
        // DCT@0x800-0xBFF) and the cocotb API's TGT_BASE=0x1000. The wrapper
        // default (0x500) is too small, so target accesses (0x1xxx) miss the
        // decode and fall through to instance 0, clobbering the controller.
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
        .dct_mem_sink_o(dct_mem_sink)
    );

    //--------------------------------------------------------------------------
    // DAT/DCT memory. Default: the same SRAM the SMC integration uses
    // (prim_ram_1p_adv_i3ccore). Define I3C_BEHAV_DAT_MEM to use a simple
    // single-cycle write-forwarding behavioral RAM instead (debug: isolate
    // read-after-write behavior of the SRAM).
    //--------------------------------------------------------------------------
`ifdef I3C_BEHAV_DAT_MEM
    for (genvar gi = 0; gi < NUM_I3C; gi++) begin : gen_i3c_mem
        logic [63:0]  dat_arr [0:(1<<i3c_pkg::DatAw)-1];
        logic [127:0] dct_arr [0:(1<<i3c_pkg::DctAw)-1];
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                for (int k = 0; k < (1<<i3c_pkg::DatAw); k++) dat_arr[k] <= '0;
                dat_mem_src[gi].rdata <= '0; dat_mem_src[gi].rvalid <= 1'b0; dat_mem_src[gi].rerror <= '0;
            end else begin
                dat_mem_src[gi].rvalid <= 1'b0; dat_mem_src[gi].rerror <= '0;
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
                for (int k = 0; k < (1<<i3c_pkg::DctAw); k++) dct_arr[k] <= '0;
                dct_mem_src[gi].rdata <= '0; dct_mem_src[gi].rvalid <= 1'b0; dct_mem_src[gi].rerror <= '0;
            end else begin
                dct_mem_src[gi].rvalid <= 1'b0; dct_mem_src[gi].rerror <= '0;
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
    end : gen_i3c_mem
`else
    for (genvar gi = 0; gi < NUM_I3C; gi++) begin : gen_i3c_mem
        // DAT memory (64-bit wide)
        prim_ram_1p_adv_i3ccore #(
            .Depth              (I3CCSR_pkg::dat_depth + 1),
            .Width              (64),
            .DataBitsPerMask    (32),
            .EnableOutputPipeline(1)
        ) i3c_dat_memory (
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
        prim_ram_1p_adv_i3ccore #(
            .Depth              (I3CCSR_pkg::dct_depth + 1),
            .Width              (128),
            .DataBitsPerMask    (32),
            .EnableOutputPipeline(1)
        ) i3c_dct_memory (
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
    end : gen_i3c_mem
`endif

    //--------------------------------------------------------------------------
    // Functional coverage interface (sampling guarded by +define+I3C_COVERAGE)
    // Observes the shared I3C bus, OD/PP mode, interrupts, and AXI cmd/resp ports.
    //--------------------------------------------------------------------------
    i3c_coverage_if u_i3c_cov (
        .clk      (clk),
        .scl      (scl_o[0]),
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

    //--------------------------------------------------------------------------
    // Simple test: let it run for basic compilation check
    //--------------------------------------------------------------------------
    initial begin
        $display("I3C Core Wrapper Testbench starting...");

        // Wait for reset release
        wait (rst_n);
        repeat (100) @(posedge clk);

        $display("I3C Core Wrapper Testbench completed - basic compilation check passed!");
    end

    //--------------------------------------------------------------------------
    // FSDB waveform dumping for VCS (Verdi-compatible)
    //--------------------------------------------------------------------------
    initial begin
        if ($test$plusargs("waves")) begin
            string wave_file;
            if (!$value$plusargs("WAVE_FILE=%s", wave_file)) begin
                wave_file = "test.fsdb";
            end
            $display("[I3C TB] FSDB waveform dumping enabled: %s", wave_file);
            $fsdbDumpfile(wave_file);
            $fsdbDumpvars(0, tb_i3ccore);
            $fsdbDumpvars("+all");
        end
    end

endmodule : tb_i3ccore
