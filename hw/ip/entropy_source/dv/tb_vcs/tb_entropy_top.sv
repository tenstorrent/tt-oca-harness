// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

`timescale 1ns / 1ps

// Testbench wrapper for entropy_source using APB interface
module tb_entropy_top;
  import entropy_source_pkg::*;

  localparam int N_RO = 12;  // Number of ring oscillators (12 channels)

  // APB interface instance
  apb_intf #(
    .ADDR_WIDTH(12),
    .DATA_WIDTH(32)
  ) apb ();

  // Other DUT IO
  logic rosc_sample_clk;
  logic signal_monitor;
  logic [31:0] entropy_stream_data;
  logic        entropy_stream_vld;
  logic irq;

  // Optional RO jitter model configuration and outputs (exposed to cocotb)
  // 12-channel RO model to match DUT
  ro_cfg_if #(.N(N_RO)) ro_cfg ();
  logic [N_RO-1:0] ro_bits;
  logic [N_RO-1:0] ro_vlds;
  // RO model injection control (exposed to cocotb)
  // 0: No injection - use DUT's real ring oscillators
  // 1: Inject model - force RO model outputs into DUT decorrelators (default)
  // NOTE: Power-on default below; actual runtime default from test_config.py (ROConfig.inject_model = 1)
  logic ro_inject_enable = 1'b1;  // Power-on fallback (avoids X propagation)
  // Decorrelator configuration (exposed to cocotb)
  decor_cfg_if decor_cfg ();
  // Decorrelator outputs (for reference model)
  logic [N_RO-1:0][7:0] entropy_bytes;
  logic                 entropy_bytes_vld;
  // Flattened view to ease waveform visibility in some tools
  logic [N_RO*8-1:0]    entropy_bytes_flat;
  // RTL clock divider probes (alias to debug_clk_divider from debug_signals.svh)
  logic [7:0] rtl_clk_dividers [N_RO];
  // RTL detune status probes (alias to debug_detune from debug_signals.svh)
  // Shows actual detune applied to each RO (FSM state when autotune enabled, register when disabled)
  logic rtl_detune [N_RO];
  // Flattened detune vector for cocotb access (cocotb can't access unpacked arrays)
  logic [N_RO-1:0] rtl_detune_flat;
  // Clock divider checker disable control (exposed to cocotb)
  // 0: Checker enabled (default - normal operation)
  // 1: Checker disabled (for tests that change divider on-the-fly)
  logic disable_clk_divider_check = 1'b0;
  genvar gi;
  generate
    for (gi = 0; gi < N_RO; gi++) begin : gen_flat_bytes
      assign entropy_bytes_flat[gi*8+:8] = entropy_bytes[gi];
    end
  endgenerate

  // RO jitter model array - 12 channels to match DUT
  // Enable is connected directly to DUT's ring_osc_enable signal,
  // so the model automatically follows DUT register state
  RO_Jitter_Array #(
    .N(N_RO)
  ) u_ro_model (
    .clk_i   (apb.pclk),
    .rstn_i  (apb.presetn),  // Use system reset to properly initialize counters
    .enable_i(dut.reg_out.RING_OSC_ENABLE.ENABLE.value),  // Auto-sync with DUT enable state
    .cfg     (ro_cfg),
    .bit_o   (ro_bits),
    .vld_o   (ro_vlds)
  );

  // Decorrelator Reference Model (Golden Data Generator)
  // NOTE: This is a simulation-only model for generating golden entropy data.
  //       It is NOT the actual RTL design.
  // Synchronized with RTL clock dividers (lane 0; gen_clk_divider_check warns on divergence)
  // Sampling timing determined entirely by probing RTL divider, no fixed period parameter
  Serial_Decorrelator_RefModel #(
    .N(N_RO),
    .DEPTH(29)
  ) u_decorrelator_refmodel (
    .clk_i (apb.pclk),
    .rstn_i(apb.presetn),
    .bit_i (ro_bits),
    .vld_i (ro_vlds),
    .mode_i(decor_cfg.mode),  // Configurable from Python via decor_cfg interface
    .shift_dir_i(decor_cfg.shift_dir),  // Shift direction from config interface
    .bypass_mask_i(decor_cfg.bypass_mask),  // Per-lane bypass control for mixed modes
    .rtl_clk_divider_i(rtl_clk_dividers[0]),  // Lane 0; gen_clk_divider_check warns on divergence
    .sample_vld_o(entropy_bytes_vld),
    .bytes_o(entropy_bytes)
  );

  // ============================================================================
  // Apply Byte Mask to Decorrelator Reference Output
  // ============================================================================
  // The DUT decorrelator applies byte_mask_i in hardware, so DUT compressor
  // receives masked data. We must apply the same mask to reference decorrelator
  // output before feeding it to the reference compressor for correct comparison.

  logic [N_RO-1:0][7:0] entropy_bytes_masked;
  logic [N_RO*8-1:0]    entropy_bytes_masked_flat;  // Flattened view for Python/waveforms

  generate
    for (gi = 0; gi < N_RO; gi++) begin : gen_apply_byte_mask
      assign entropy_bytes_masked[gi] = entropy_bytes[gi] & dut.reg_out.DECORRELATOR_MASK.ENTROPY_BYTE_MASK.value;
      assign entropy_bytes_masked_flat[gi*8 +: 8] = entropy_bytes_masked[gi];
    end
  endgenerate

  // ============================================================================
  // Entropy Compressor Reference Model (BIW Extractor)
  // ============================================================================
  // Compresses 12 decorrelator byte streams into 32-bit word using BIW extraction
  // Provides golden data for verifying DUT's entropy_stream output

  // Compressor configuration interface (exposed to cocotb)
  compressor_cfg_if compressor_cfg ();

  // Compressor outputs
  logic [31:0] compressed_word;
  logic        compressed_vld;

  // Compressor Reference Model (Fully Combinational)
  Entropy_Compressor_RefModel #(
    .N_LANES(N_RO)
  ) u_compressor_refmodel (
    .bytes_i(entropy_bytes_masked),   // Use MASKED decorrelator output (DUT applies mask in hardware)
    .vld_i  (entropy_bytes_vld),
    .cfg    (compressor_cfg.slave),
    .word_o (compressed_word),        // 32-bit compressed output
    .vld_o  (compressed_vld)
  );

  // Compressor configuration managed through Python test_config.py
  // See CompressorConfig class for default values and configuration options

  // ============================================================================
  // Compressor Output Checker (DUT vs Reference Model)
  // ============================================================================
  // Compares DUT compressor output against reference model
  // Reports mismatches immediately using $error
  // Control: compressor_cfg.checker_enable (default: 1, enabled)

  // Checker status outputs
  logic [31:0] compressor_check_count;
  logic [31:0] compressor_mismatch_count;

  // Instantiate checker module
  Compressor_Checker u_compressor_checker (
    .clk_i              (apb.pclk),
    .rstn_i             (apb.presetn),
    .enable_i           (compressor_cfg.checker_enable),  // Master enable
    .verbose_i          (compressor_cfg.checker_verbose), // Show MATCH messages if enabled
    .dut_word_i         (entropy_stream_data),            // DUT output (32-bit word)
    .dut_vld_i          ({31'b0, entropy_stream_vld}),    // DUT valid (extend 1-bit to 32-bit, checker uses bit [0])
    .ref_word_i         (compressed_word),                // Reference model output
    .ref_vld_i          (compressed_vld),                 // Ref model valid
    .check_count_o      (compressor_check_count),         // Status output
    .mismatch_count_o   (compressor_mismatch_count)       // Status output
  );

  // DUT instance
  // Note: Real RTL uses types from entropy_source_pkg (reg_addr_t, reg_data_t, reg_strb_t)
  entropy_source dut (
    .clk_i                  (apb.pclk),
    .rst_ni                 (apb.presetn),
    .paddr_i                (reg_addr_t'(apb.paddr[REG_ADDR_WIDTH-1:0])),
    .pprot_i                (3'b000),
    .psel_i                 (apb.psel),
    .penable_i              (apb.penable),
    .pwrite_i               (apb.pwrite),
    .pwdata_i               (reg_data_t'(apb.pwdata)),
    .pstrb_i                (reg_strb_t'(4'hF)),
    .pready_o               (apb.pready),
    .prdata_o               (apb.prdata),
    .pslverr_o              (apb.pslverr),
    .signal_monitor_o       (signal_monitor),
    .rosc_sample_clk_i      (rosc_sample_clk),
    .entropy_stream_data_o  (entropy_stream_data),
    .entropy_stream_vld_o   (entropy_stream_vld),
    .irq_o                  (irq)
  );

  // Debug signals for nWave visibility (flattens nested structs)
  `include "debug_signals.svh"

  // ============================================================================
  // RTL Clock Divider Probes (for synchronization and debug)
  // ============================================================================
  // Note: debug_clk_divider[12] is declared and assigned in debug_signals.svh above
  // rtl_clk_dividers aliases it for the decorrelator reference model and the
  // verification checks below.

  generate
    for (gi = 0; gi < N_RO; gi++) begin : gen_clk_divider_alias
      assign rtl_clk_dividers[gi] = debug_clk_divider[gi];
    end
  endgenerate

  // ============================================================================
  // RTL Detune Status Probes (for autotune verification)
  // ============================================================================
  // Note: debug_detune[12] is declared and assigned in debug_signals.svh above
  // We create rtl_detune as an alias for use in Python tests via cocotb
  // This shows the ACTUAL detune applied (FSM state when autotune enabled)

  generate
    for (gi = 0; gi < N_RO; gi++) begin : gen_detune_alias
      assign rtl_detune[gi] = debug_detune[gi];
      // Also flatten into packed vector for cocotb access (cocotb can't access unpacked arrays)
      assign rtl_detune_flat[gi] = debug_detune[gi];
    end
  endgenerate

  // Verification: All lanes should have synchronized clock dividers
  // (only check when not in reset and ROs are enabled, and checker not disabled)
  // NOTE: Checker disabled for tests that change divider on-the-fly (health tests)
  generate
    for (gi = 1; gi < N_RO; gi++) begin : gen_clk_divider_check
      always @(posedge apb.pclk) begin
        if (!disable_clk_divider_check && apb.presetn &&
            dut.reg_out.RING_OSC_ENABLE.ENABLE.value[gi] &&
            dut.reg_out.RING_OSC_ENABLE.ENABLE.value[0]) begin
          if (rtl_clk_dividers[gi] != rtl_clk_dividers[0]) begin
            $warning("[TB] Clock divider mismatch: lane[%0d]=0x%02X, lane[0]=0x%02X", gi,
                     rtl_clk_dividers[gi], rtl_clk_dividers[0]);
          end
        end
      end
    end
  endgenerate

  // ============================================================================
  // Decorrelator Output Checker (DUT vs Reference Model)
  // ============================================================================
  // Compares DUT decorrelator outputs against reference model for all lanes
  // Synchronized using reference model valid signal
  // Reports mismatches immediately using $error
  // Control: decor_cfg.checker_enable (default: 1, enabled)

  // Collect DUT decorrelator outputs from all lanes (no valid signal in DUT)
  logic [N_RO-1:0][7:0] dut_entropy_bytes;

  generate
    for (gi = 0; gi < N_RO; gi++) begin : gen_dut_entropy_probe
      assign dut_entropy_bytes[gi] = dut.egen.gen_ecmplx[gi].gen_inst.dcor.entropy_byte_sample_o;
    end
  endgenerate

  // Checker status outputs
  logic [31:0] checker_check_count;
  logic [31:0] checker_mismatch_count;
  logic        checker_warmup_done;

  // Instantiate checker module
  // Warmup samples calculated dynamically based on SAMPLE_CLK_DIV:
  //   - clk_div=0x7 (div-8):  need ceil(29/8)+2 = 6 samples
  //   - clk_div=0x63 (div-100): need ceil(29/100)+2 = 3 samples
  Decorrelator_Checker #(
    .N_LANES(N_RO),
    .MAX_DEPTH(29),      // Maximum decorrelator depth (DECOR_29 mode)
    .SAFETY_MARGIN(2)    // Extra samples for safety beyond calculated minimum
  ) u_decorrelator_checker (
    .clk_i              (apb.pclk),
    .rstn_i             (apb.presetn),
    .enable_i           (decor_cfg.checker_enable),  // Master enable (ANDed with warmup_done)
    .verbose_i          (decor_cfg.checker_verbose), // Show MATCH messages if enabled
    .rtl_clk_divider_i  (rtl_clk_dividers[0]),       // Monitor RTL programming (waits for != 0)
    .byte_mask_i        (dut.reg_out.DECORRELATOR_MASK.ENTROPY_BYTE_MASK.value),  // DECORRELATOR_MASK register
    .dut_bytes_i        (dut_entropy_bytes),         // DUT outputs (no valid signal)
    .ref_bytes_i        (entropy_bytes),             // Reference model outputs
    .ref_vld_i          (entropy_bytes_vld),         // Ref model valid (sync point)
    .check_count_o      (checker_check_count),       // Status output
    .mismatch_count_o   (checker_mismatch_count),    // Status output
    .warmup_done_o      (checker_warmup_done)        // Warmup complete flag
  );

  // ============================================================================
  // RO Model Injection into DUT
  // ============================================================================
  // Force RO model outputs into DUT decorrelator inputs at:
  // dut.egen.gen_ecmplx[0-11].gen_inst.dcor.noise_i
  // This allows testing with behavioral RO model instead of real ring oscillators
  //
  // Control: Set ro_inject_enable from cocotb to enable/disable injection
  //   ro_inject_enable = 1: Inject RO model (default)
  //   ro_inject_enable = 0: Use DUT's real ring oscillators

  generate
    for (gi = 0; gi < N_RO; gi++) begin : gen_ro_inject
      always_comb begin
        if (ro_inject_enable) begin
          // Force the noise_i input of each decorrelator with RO model output
          // Path: tb_entropy_top.dut.egen.gen_ecmplx[i].gen_inst.dcor.noise_i
          force dut.egen.gen_ecmplx[gi].gen_inst.dcor.noise_i = ro_bits[gi];
        end else begin
          // Release force to use DUT's real ring oscillators
          release dut.egen.gen_ecmplx[gi].gen_inst.dcor.noise_i;
        end
      end
    end
  endgenerate

  // ============================================================================
  // Health Test Direct Injection (32-bit Word Mode)
  // ============================================================================
  // Optional injection of 32-bit words directly into health test input
  // Bypasses decorrelator and compressor for controlled failure testing
  //
  // Normal mode (ro_cfg.word32_enable = 0):
  //   Health test receives: fifo_wdata (from compressor)
  //
  // Injection mode (ro_cfg.word32_enable = 1):
  //   Health test receives: ro_cfg.word32_data (from RO model word generator)
  //
  // This allows Suite 3 tests to inject controlled entropy patterns
  // without decorrelator/compressor variability

  always_comb begin
    if (ro_cfg.word32_enable) begin
      // Force health test input with 32-bit word from RO model
      force dut.htst.entropy_i = ro_cfg.word32_data;
      force dut.htst.entropy_valid_i = ro_cfg.word32_valid;
    end else begin
      // Release force to allow normal operation
      release dut.htst.entropy_i;
      release dut.htst.entropy_valid_i;
    end
  end

  // Clocks are driven by cocotb; provide stable initial values
  initial begin
    apb.pclk = 0;
    apb.presetn = 0;
    apb.paddr = '0;
    apb.psel = 0;
    apb.penable = 0;
    apb.pwrite = 0;
    apb.pwdata = '0;
    rosc_sample_clk = 0;
  end

`ifdef FSDB_DUMP
  // FSDB waveform dump (enabled via +define+FSDB_DUMP)
  // FSDB file location can be overridden with FSDB_FILE plusarg
  initial begin
    string fsdb_file;
    if (!$value$plusargs("FSDB_FILE=%s", fsdb_file)) begin
      fsdb_file = "sim/tb_entropy_top.fsdb";
    end
    $fsdbDumpfile(fsdb_file);
    $fsdbDumpvars(0, tb_entropy_top);
  end
`elsif VCD_DUMP
  // Optional VCD dump fallback
  initial begin
    string vcd_file;
    if (!$value$plusargs("VCD_FILE=%s", vcd_file)) begin
      vcd_file = "sim/tb_entropy_top.vcd";
    end
    $dumpfile(vcd_file);
    $dumpvars(0, tb_entropy_top);
  end
`endif


endmodule
