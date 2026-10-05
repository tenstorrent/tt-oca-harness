// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP-local TB interface for the SV-UVM flow: the four harness clock
// periods, the test-sequenced primary reset and boot/run controls, the
// fabric-release and reset observables the sequences and the scoreboard
// read, the reset assertion counter the scoreboard predictors re-baseline
// on, the observation probes the scenario checks read, and the AXI SVA
// enable. Separate from the shared ocah_axi_if, which carries generic AXI
// pins only. Sequences, checkers, and the scoreboard
// reach DUT-local signals only through this interface. The cocotb
// realization exposes the same pins as tb_top ports driven from
// sep_base_test.

interface sep_tb_if;

  // Clock periods the harness generators read, set by the env from
  // sep_env_cfg. clk_i is the 800 MHz silicon target. clk_ref_i is 100 MHz.
  real sys_clk_period_ns             = 1.25;
  int unsigned wdt_clk_period_ns     = 5000;
  int unsigned entropy_clk_period_ns = 3;
  // Reference clock for REFERENCE_COUNTER. Slower than the system clock so the
  // counter's CDC crossing is a real one in both directions.
  real ref_clk_period_ns             = 10.0;

  // Driven by the TB (bring-up owned by the test). rst_n starts released:
  // the bring-up assertion is then a real falling edge, the only event that
  // loads the reset value into an async-reset flop on the slow WDT clock
  // before that clock's first edge.
  logic rst_n = 1'b1;
  // Boot/run controls at the cocotb drive_idle_defaults values: boot
  // sequence done, CPU held off, WDT and EL2 debugger resets released,
  // functional-mode TEST_EN strap.
  logic ext_boot_seq_done = 1'b1;
  logic mpc_reset_run_req = 1'b0;
  logic wdt_rst_n         = 1'b1;
  logic dbg_rstb          = 1'b1;
  logic test_en_strap     = 1'b0;

  // Fabric release (fuse sense done) and the reset observables (driven by
  // the DUT top): the local fabric answers CSR accesses only after
  // fuse_sense_done rises.
  logic fuse_sense_done;
  logic sep_reset_n;
  logic sep_cpu_reset_n;
  logic secure_tm;
  // OTP JTAG2AXIL disable bits of the DUT dbg_disable_o output.
  logic dbg_disable_smc_otp_jtag2axi;
  logic dbg_disable_sep_otp_jtag2axi;

  // Primary-reset assertion counter (driven by tb_top).
  logic [31:0] rst_assert_count;

  // Observation probes mirrored from the shared tb_top probe outputs (driven
  // by tb_top; observation-only, see SEP_TB_ARCH "Observation probes").
  // Interrupt aggregate.
  logic [sep_pkg::NUM_INTERNAL_IRQS-1:0] sep_internal_interrupts;
  // eFuse sensed shadow.
  logic [sep_efuse_pkg::NumEfuseBits-1:0] efuse_shadow;
  // OTBN instruction and data memory request and write counters.
  logic [31:0] otbn_imem_req_count;
  logic [31:0] otbn_imem_write_count;
  logic [31:0] otbn_dmem_req_count;
  logic [31:0] otbn_dmem_write_count;
  // Key Manager ROM and SRAM probes and counters.
  logic [31:0]        km_rom_req_count;
  logic [98*32-1:0]   km_sram_probe;
  logic [31:0]        km_sram_rd_accept_count;
  logic [31:0]        km_sram_rd_b2b_diff_count;
  logic [31:0]        km_sram_rd_lat1_count;
  logic [31:0]        km_sram_rd_lat_err_count;
  logic [31:0]        km_sram_req_count;
  logic [31:0]        km_sram_scr_rd_count;
  logic [4*13-1:0]    km_sram_scr_wr_addr;
  logic [4*32-1:0]    km_sram_scr_wr_cell;
  logic [31:0]        km_sram_scr_wr_count;
  logic [4*32-1:0]    km_sram_scr_wr_data;
  logic [31:0]        km_sram_word0;
  logic [31:0]        km_sram_write_count;

  // Runtime enable for the shared AXI protocol SVA checker on the CPU-LSU
  // splice; tb_top ANDs it with the run-mode gate of u_s_axi_sva.
  logic axi_sva_en = 1'b1;

endinterface : sep_tb_if
