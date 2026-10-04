// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC OSS TB top shared by the native cocotb / PyUVM flow and the
// SystemVerilog UVM flow. ONE module, two shapes:
//   * default (cocotb, `--dut smc`): the pin-level ANSI port list cocotb
//     drives and samples;
//   * `UVM` (SV-UVM, `--dut smc --framework uvm`): the port list is replaced
//     by internal TB signals and the harness block at the end of the module
//     adds the clocks, the shared-VIP interfaces, quiescent tie-offs,
//     uvm_config_db publication, and run_test(). Test classes are compiled
//     via `include "smc_tests.sv".
// Every TB signal is declared once, in tb/smc_tb_signal_list.svh, and
// expanded into the selected shape by the SMC_TB_* macros below.
//
// Instantiates hw/top/smc_wrapper.sv (smc + smc_ip_integration). File name is
// tb_top.sv / module smc_uvm_top so `--dut smc_wrapper` +
// smc_wrapper_sim_cfg.toml is the single launch entry.
//
// Cocotb port surface keeps the SmcEnv catalog pin names. Hierarchical XMRs
// into the core use u_dut.u_smc.*.
//
// PLL/PVT/adopter-extension/GPIO-ctrl AXI-Lite macros, eFuse, I3C DAT/DCT/RLT
// table memories and CPU ROM/scratch/L1$ macros live inside
// smc_ip_integration. DTP CSR is a smc_wrapper boundary port whose response is
// tied idle (no TB placeholder): SMU wires DTP internally, this DUT does not.
// smc_cpu_mem_dv.sv binds into the integration for the CPU-memory DV hooks.
//
// Additive elaboration-alias outputs (dut_present_o / powergood_o / ...) sit
// at the end of the port list for the thin elaboration smoke.

`timescale 1ps/1fs

// Shape selection for smc_tb_signal_list.svh: the same list expands as the
// ANSI port list (cocotb) or as internal TB signals (`UVM`). The macros live
// only from here to the `undef block after the module header.
`ifndef UVM
    // cocotb shape: every entry is a pin-level ANSI port, published to cocotb
    // through the Verilator metacomment (smc_public_scope.vlt publishes the
    // whole module as well).
    `define SMC_TB_IN_FIRST(dtype, name) input  wire dtype name /*verilator public_flat_rw*/
    `define SMC_TB_IN(dtype, name)     , input  wire dtype name /*verilator public_flat_rw*/
    `define SMC_TB_OUT(dtype, name)    , output dtype name /*verilator public_flat_rw*/
`else
    // SV-UVM shape: every entry is an internal TB signal for the harness
    // block at the end of this module.
    `define SMC_TB_IN_FIRST(dtype, name) dtype name;
    `define SMC_TB_IN(dtype, name) dtype name;
    `define SMC_TB_OUT(dtype, name) dtype name;
`endif

module smc_uvm_top
    import smc_pkg::*;
    import smc_efuse_pkg::*;
    import smc_4core_cpu_pkg::*;
`ifndef UVM
(
`ifndef SMC_DUAL
    `include "smc_tb_signal_list.svh"
`else  // SMC_DUAL
    // ==================================================================
    // Dual-instance port surface.
    //
    // Only the surface the OCCP boot flow needs is lifted: clocks/resets, one
    // inbound AXI manager per instance, the shared I3C pads, and
    // scratch/ROM-fetch observability. The clock inputs toggle both
    // instances' pll_wrap oscillators; clk_*_o export the target instance's
    // generated clocks.
    input wire logic clk_smc_i /*verilator public_flat_rw*/,
    input wire logic clk_ref_i /*verilator public_flat_rw*/,
    input wire logic clk_periph_i /*verilator public_flat_rw*/,
    output logic clk_smc_o /*verilator public_flat_rw*/,
    output logic clk_ref_o /*verilator public_flat_rw*/,
    output logic clk_periph_o /*verilator public_flat_rw*/,

    input wire logic powergood_i /*verilator public_flat_rw*/,
    input wire logic rst_cold_ni /*verilator public_flat_rw*/,
    input wire logic rst_cool_ni /*verilator public_flat_rw*/,

    // Per-instance bring-up observability.
    output logic dut_powergood_stable_o /*verilator public_flat_rw*/,
    output logic bfm_powergood_stable_o /*verilator public_flat_rw*/,
    output logic dut_rst_primary_smc_clk_no /*verilator public_flat_rw*/,
    output logic bfm_rst_primary_smc_clk_no /*verilator public_flat_rw*/,
    output logic dut_fuse_sense_done_o /*verilator public_flat_rw*/,
    output logic bfm_fuse_sense_done_o /*verilator public_flat_rw*/,
    output logic dut_init_mem_done_o /*verilator public_flat_rw*/,
    output logic bfm_init_mem_done_o /*verilator public_flat_rw*/,
    // Fault outputs, latched sticky per instance until cold reset.
    output logic dut_cluster_ded_seen_o /*verilator public_flat_rw*/,
    output logic bfm_cluster_ded_seen_o /*verilator public_flat_rw*/,
    output logic dut_wdt_first_timeout_seen_o /*verilator public_flat_rw*/,
    output logic bfm_wdt_first_timeout_seen_o /*verilator public_flat_rw*/,
    output logic dut_wdt_second_timeout_seen_o /*verilator public_flat_rw*/,
    output logic bfm_wdt_second_timeout_seen_o /*verilator public_flat_rw*/,

    // Shared I3C0 bus. *_ext_low lets a cocotb VIP join the same
    // wired-AND as a third driver; unused by the dual-firmware flow.
    input  wire logic tb_i3c0_scl_ext_low /*verilator public_flat_rw*/,
    input  wire logic tb_i3c0_sda_ext_low /*verilator public_flat_rw*/,
    output logic      tb_i3c0_scl /*verilator public_flat_rw*/,
    output logic      tb_i3c0_sda /*verilator public_flat_rw*/,
    output logic      tb_i3c0_scl_dut_low /*verilator public_flat_rw*/,
    output logic      tb_i3c0_sda_dut_low /*verilator public_flat_rw*/,
    output logic      tb_i3c0_scl_bfm_low /*verilator public_flat_rw*/,
    output logic      tb_i3c0_sda_bfm_low /*verilator public_flat_rw*/,
    // Bus activity counters: proof that the two instances actually talked,
    // independent of any firmware-reported result.
    // Per-channel view of the three cross-wired I3C channels {0, 1, 3}. Index
    // is the position in that list, not the I3C instance number.
    //
    // Per-channel I3C activity, one flat scalar per position. An unpacked-array
    // port (`logic [7:0] x [3]` assigned '{0,1,3}) reads back through cocotb as
    // [0,0,0], silently mis-attributing every per-channel count, so the counts
    // are flat scalars and tb_i3c_channel_id_N carries the instance each
    // position watches, asserted by smc_dual_elaboration_test rather than
    // assumed.
    output logic [7:0]      tb_i3c_channel_id_0 /*verilator public_flat_rw*/,
    output logic [7:0]      tb_bfm_i3c_wsel /*verilator public_flat_rw*/,
    output logic [7:0]      tb_i3c_channel_id_1 /*verilator public_flat_rw*/,
    output logic [7:0]      tb_i3c_channel_id_2 /*verilator public_flat_rw*/,
    output logic [31:0]     tb_i3c_scl_fall_count_0 /*verilator public_flat_rw*/,
    output logic [31:0]     tb_i3c_scl_fall_count_1 /*verilator public_flat_rw*/,
    output logic [31:0]     tb_i3c_scl_fall_count_2 /*verilator public_flat_rw*/,
    output logic [31:0]     tb_i3c_start_count_0 /*verilator public_flat_rw*/,
    output logic [31:0]     tb_i3c_start_count_1 /*verilator public_flat_rw*/,
    output logic [31:0]     tb_i3c_start_count_2 /*verilator public_flat_rw*/,

    // Strap-capture gate per instance. cocotb holds the strap pads until this
    // rises, which is when the padring latches them.
    output logic            dut_rst_cold_stable_ref_clk_no /*verilator public_flat_rw*/,
    output logic            bfm_rst_cold_stable_ref_clk_no /*verilator public_flat_rw*/,

    // One pair per I2C channel, since each channel is its own point-to-point bus.
    output logic [31:0]     tb_i2c_scl_fall_count_0 /*verilator public_flat_rw*/,
    output logic [31:0]     tb_i2c_scl_fall_count_1 /*verilator public_flat_rw*/,
    output logic [31:0]     tb_i2c_start_count_0 /*verilator public_flat_rw*/,
    output logic [31:0]     tb_i2c_start_count_1 /*verilator public_flat_rw*/,

    // Last AXI-Lite write seen by the controller's I3C CSR wrapper, and the
    // instance its decode selected. Direct evidence for "the firmware wrote
    // instance N's window; which core actually got it?".
    output logic [31:0]     tb_bfm_i3c_awaddr /*verilator public_flat_rw*/,

    // OCCP target-up pad (58), target -> controller.
    output logic tb_gpio58_from_dut /*verilator public_flat_rw*/,
    output logic tb_gpio58_bus /*verilator public_flat_rw*/,

    // Runtime primary/secondary strap per instance.
    input wire logic dut_chiplet_is_primary /*verilator public_flat_rw*/,
    input wire logic bfm_chiplet_is_primary /*verilator public_flat_rw*/,

    // Per-instance boot-stall hold, driven by cocotb during bring-up.
    input wire logic dut_boot_stall_hold /*verilator public_flat_rw*/,
    input wire logic bfm_boot_stall_hold /*verilator public_flat_rw*/,

    // Per-instance GPIO strap override (pads read by smc_padring straps).
    input wire logic [smc_pkg::NumGpioWraps-1:0] dut_gpio_ext_drive_en /*verilator public_flat_rw*/,
    input wire logic [smc_pkg::NumGpioWraps-1:0] dut_gpio_ext_drive_value /*verilator public_flat_rw*/,
    input wire logic [smc_pkg::NumGpioWraps-1:0] bfm_gpio_ext_drive_en /*verilator public_flat_rw*/,
    input wire logic [smc_pkg::NumGpioWraps-1:0] bfm_gpio_ext_drive_value /*verilator public_flat_rw*/,

    // Per-instance product lifecycle state, {diff_n, diff_p}. The ROM reads it
    // through CHIP_CONFIG.LC_STATE to decide whether the part is in a secure
    // lifecycle, so a test that needs the secure branch -- or an illegal
    // encoding -- has to change it before cold reset is released.
    input wire logic [2*smc_pkg::LcStateWidth-1:0] dut_lc_state /*verilator public_flat_rw*/,
    input wire logic [2*smc_pkg::LcStateWidth-1:0] bfm_lc_state /*verilator public_flat_rw*/,

    // Per-instance BISR/MBIST result reporting. The boot sequencer waits for
    // the two `done` lines and then branches on `success`/`pass`, so the DFT
    // tests drive failure here and a timeout is simply `done` never arriving.
    // Idle values are set by SmcDualHarness.idle_pins(): done/success/pass high
    // and abort low, which is the "no external BISR/MBIST agent" posture every
    // other test needs to boot at all.
    input wire logic dut_mem_repair_done /*verilator public_flat_rw*/,
    input wire logic dut_mem_repair_success /*verilator public_flat_rw*/,
    input wire logic dut_mem_repair_abort /*verilator public_flat_rw*/,
    input wire logic dut_mbist_done /*verilator public_flat_rw*/,
    input wire logic dut_mbist_pass /*verilator public_flat_rw*/,
    input wire logic dut_mbist_abort /*verilator public_flat_rw*/,
    input wire logic bfm_mem_repair_done /*verilator public_flat_rw*/,
    input wire logic bfm_mem_repair_success /*verilator public_flat_rw*/,
    input wire logic bfm_mem_repair_abort /*verilator public_flat_rw*/,
    input wire logic bfm_mbist_done /*verilator public_flat_rw*/,
    input wire logic bfm_mbist_pass /*verilator public_flat_rw*/,
    input wire logic bfm_mbist_abort /*verilator public_flat_rw*/,

    // ------------------------------------------------------------------
    // Inbound AXI manager into u_dut (SEP_IN). Same flat shape and prefix as
    // the single-instance half's s_axi so the existing SmcSysAxiAgent binds
    // unchanged.
    // ------------------------------------------------------------------
    input  wire logic [5:0]   s_axi_awid /*verilator public_flat_rw*/,
    input  wire logic [55:0]  s_axi_awaddr /*verilator public_flat_rw*/,
    input  wire logic [7:0]   s_axi_awlen /*verilator public_flat_rw*/,
    input  wire logic [2:0]   s_axi_awsize /*verilator public_flat_rw*/,
    input  wire logic [1:0]   s_axi_awburst /*verilator public_flat_rw*/,
    input  wire logic         s_axi_awlock /*verilator public_flat_rw*/,
    input  wire logic [3:0]   s_axi_awcache /*verilator public_flat_rw*/,
    input  wire logic [2:0]   s_axi_awprot /*verilator public_flat_rw*/,
    input  wire logic [3:0]   s_axi_awqos /*verilator public_flat_rw*/,
    input  wire logic [3:0]   s_axi_awregion /*verilator public_flat_rw*/,
    input  wire logic [11:0]  s_axi_awuser /*verilator public_flat_rw*/,
    input  wire logic         s_axi_awvalid /*verilator public_flat_rw*/,
    output logic              s_axi_awready /*verilator public_flat_rw*/,
    input  wire logic [63:0]  s_axi_wdata /*verilator public_flat_rw*/,
    input  wire logic [7:0]   s_axi_wstrb /*verilator public_flat_rw*/,
    input  wire logic         s_axi_wlast /*verilator public_flat_rw*/,
    input  wire logic [11:0]  s_axi_wuser /*verilator public_flat_rw*/,
    input  wire logic         s_axi_wvalid /*verilator public_flat_rw*/,
    output logic              s_axi_wready /*verilator public_flat_rw*/,
    output logic [5:0]        s_axi_bid /*verilator public_flat_rw*/,
    output logic [1:0]        s_axi_bresp /*verilator public_flat_rw*/,
    output logic [11:0]       s_axi_buser /*verilator public_flat_rw*/,
    output logic              s_axi_bvalid /*verilator public_flat_rw*/,
    input  wire logic         s_axi_bready /*verilator public_flat_rw*/,
    input  wire logic [5:0]   s_axi_arid /*verilator public_flat_rw*/,
    input  wire logic [55:0]  s_axi_araddr /*verilator public_flat_rw*/,
    input  wire logic [7:0]   s_axi_arlen /*verilator public_flat_rw*/,
    input  wire logic [2:0]   s_axi_arsize /*verilator public_flat_rw*/,
    input  wire logic [1:0]   s_axi_arburst /*verilator public_flat_rw*/,
    input  wire logic         s_axi_arlock /*verilator public_flat_rw*/,
    input  wire logic [3:0]   s_axi_arcache /*verilator public_flat_rw*/,
    input  wire logic [2:0]   s_axi_arprot /*verilator public_flat_rw*/,
    input  wire logic [3:0]   s_axi_arqos /*verilator public_flat_rw*/,
    input  wire logic [3:0]   s_axi_arregion /*verilator public_flat_rw*/,
    input  wire logic [11:0]  s_axi_aruser /*verilator public_flat_rw*/,
    input  wire logic         s_axi_arvalid /*verilator public_flat_rw*/,
    output logic              s_axi_arready /*verilator public_flat_rw*/,
    output logic [5:0]        s_axi_rid /*verilator public_flat_rw*/,
    output logic [63:0]       s_axi_rdata /*verilator public_flat_rw*/,
    output logic [1:0]        s_axi_rresp /*verilator public_flat_rw*/,
    output logic              s_axi_rlast /*verilator public_flat_rw*/,
    output logic [11:0]       s_axi_ruser /*verilator public_flat_rw*/,
    output logic              s_axi_rvalid /*verilator public_flat_rw*/,
    input  wire logic         s_axi_rready /*verilator public_flat_rw*/,

    // ------------------------------------------------------------------
    // Inbound AXI manager into u_bfm (SEP_IN). This is how cocotb seeds the
    // controller: payload into its SRAM and the scratch 5-8 boot protocol.
    // Prefix `bfm_axi` -> SmcSysAxiAgent(bus_prefix="bfm_axi").
    // ------------------------------------------------------------------
    input  wire logic [5:0]   bfm_axi_awid /*verilator public_flat_rw*/,
    input  wire logic [55:0]  bfm_axi_awaddr /*verilator public_flat_rw*/,
    input  wire logic [7:0]   bfm_axi_awlen /*verilator public_flat_rw*/,
    input  wire logic [2:0]   bfm_axi_awsize /*verilator public_flat_rw*/,
    input  wire logic [1:0]   bfm_axi_awburst /*verilator public_flat_rw*/,
    input  wire logic         bfm_axi_awlock /*verilator public_flat_rw*/,
    input  wire logic [3:0]   bfm_axi_awcache /*verilator public_flat_rw*/,
    input  wire logic [2:0]   bfm_axi_awprot /*verilator public_flat_rw*/,
    input  wire logic [3:0]   bfm_axi_awqos /*verilator public_flat_rw*/,
    input  wire logic [3:0]   bfm_axi_awregion /*verilator public_flat_rw*/,
    input  wire logic [11:0]  bfm_axi_awuser /*verilator public_flat_rw*/,
    input  wire logic         bfm_axi_awvalid /*verilator public_flat_rw*/,
    output logic              bfm_axi_awready /*verilator public_flat_rw*/,
    input  wire logic [63:0]  bfm_axi_wdata /*verilator public_flat_rw*/,
    input  wire logic [7:0]   bfm_axi_wstrb /*verilator public_flat_rw*/,
    input  wire logic         bfm_axi_wlast /*verilator public_flat_rw*/,
    input  wire logic [11:0]  bfm_axi_wuser /*verilator public_flat_rw*/,
    input  wire logic         bfm_axi_wvalid /*verilator public_flat_rw*/,
    output logic              bfm_axi_wready /*verilator public_flat_rw*/,
    output logic [5:0]        bfm_axi_bid /*verilator public_flat_rw*/,
    output logic [1:0]        bfm_axi_bresp /*verilator public_flat_rw*/,
    output logic [11:0]       bfm_axi_buser /*verilator public_flat_rw*/,
    output logic              bfm_axi_bvalid /*verilator public_flat_rw*/,
    input  wire logic         bfm_axi_bready /*verilator public_flat_rw*/,
    input  wire logic [5:0]   bfm_axi_arid /*verilator public_flat_rw*/,
    input  wire logic [55:0]  bfm_axi_araddr /*verilator public_flat_rw*/,
    input  wire logic [7:0]   bfm_axi_arlen /*verilator public_flat_rw*/,
    input  wire logic [2:0]   bfm_axi_arsize /*verilator public_flat_rw*/,
    input  wire logic [1:0]   bfm_axi_arburst /*verilator public_flat_rw*/,
    input  wire logic         bfm_axi_arlock /*verilator public_flat_rw*/,
    input  wire logic [3:0]   bfm_axi_arcache /*verilator public_flat_rw*/,
    input  wire logic [2:0]   bfm_axi_arprot /*verilator public_flat_rw*/,
    input  wire logic [3:0]   bfm_axi_arqos /*verilator public_flat_rw*/,
    input  wire logic [3:0]   bfm_axi_arregion /*verilator public_flat_rw*/,
    input  wire logic [11:0]  bfm_axi_aruser /*verilator public_flat_rw*/,
    input  wire logic         bfm_axi_arvalid /*verilator public_flat_rw*/,
    output logic              bfm_axi_arready /*verilator public_flat_rw*/,
    output logic [5:0]        bfm_axi_rid /*verilator public_flat_rw*/,
    output logic [63:0]       bfm_axi_rdata /*verilator public_flat_rw*/,
    output logic [1:0]        bfm_axi_rresp /*verilator public_flat_rw*/,
    output logic              bfm_axi_rlast /*verilator public_flat_rw*/,
    output logic [11:0]       bfm_axi_ruser /*verilator public_flat_rw*/,
    output logic              bfm_axi_rvalid /*verilator public_flat_rw*/,
    input  wire logic         bfm_axi_rready /*verilator public_flat_rw*/,

    // ------------------------------------------------------------------
    // Firmware observability, per instance.
    // ------------------------------------------------------------------
    // Scratch 2 is the firmware virtual console (smc_scratchpad.h
    // SMC_SCRATCH_SIM_VIRT_CONSOLE). The DV firmware's simputs() is
    // unconditional, so the controller's own OCCP trace streams out here; the
    // cocotb side decodes it. Lifted for both instances so the target's trace
    // is available too if its ROM is ever built with prints enabled.
    output logic [31:0] dut_scratch2 /*verilator public_flat_rw*/,
    output logic [31:0] bfm_scratch2 /*verilator public_flat_rw*/,
    output logic [31:0] dut_rom_read_count /*verilator public_flat_rw*/,
    output logic [31:0] bfm_rom_read_count /*verilator public_flat_rw*/,
    output logic [31:0] dut_scratch_write_count /*verilator public_flat_rw*/,
    // Scratch RAM reads are the instruction-fetch signal for an SRAM-resident
    // image: it separates "the core never started" from "the core fetched and
    // then died", which the retired-PC value alone cannot.
    output logic [31:0] dut_scratch_read_count /*verilator public_flat_rw*/,
    output logic [57:0] dut_wb_pc0 /*verilator public_flat_rw*/,
    output logic [57:0] bfm_wb_pc0 /*verilator public_flat_rw*/,
    // Hart 0 retirement record per instance (Rocket CSR trace bundle) and the
    // core reset that masks it; the writeback registers behind the bundle have
    // no reset. Consumer: cocotb/env/smc_cpu_trace_monitor.py.
    output logic        dut_cpu_core_reset_n /*verilator public_flat_rw*/,
    output logic        dut_cpu_trace_valid /*verilator public_flat_rw*/,
    output logic [57:0] dut_cpu_trace_pc /*verilator public_flat_rw*/,
    output logic [31:0] dut_cpu_trace_insn /*verilator public_flat_rw*/,
    output logic        dut_cpu_trace_exc /*verilator public_flat_rw*/,
    output logic [63:0] dut_cpu_trace_cause /*verilator public_flat_rw*/,
    output logic [57:0] dut_cpu_trace_tval /*verilator public_flat_rw*/,
    output logic        bfm_cpu_core_reset_n /*verilator public_flat_rw*/,
    output logic        bfm_cpu_trace_valid /*verilator public_flat_rw*/,
    output logic [57:0] bfm_cpu_trace_pc /*verilator public_flat_rw*/,
    output logic [31:0] bfm_cpu_trace_insn /*verilator public_flat_rw*/,
    output logic        bfm_cpu_trace_exc /*verilator public_flat_rw*/,
    output logic [63:0] bfm_cpu_trace_cause /*verilator public_flat_rw*/,
    output logic [57:0] bfm_cpu_trace_tval /*verilator public_flat_rw*/,

    // ------------------------------------------------------------------
    // Read-only peek into the TARGET's scratch SRAM.
    //
    // Evidence only. The OCCP boot flow has two failure modes that look
    // identical from the outside -- "the bytes never arrived" and "the bytes
    // arrived but did not execute" -- and nothing else on this top can tell
    // them apart. The decode below is only known-correct at offset 0, so this is
    // evidence for triage and never a gate -- see smc_dual_axi_sram_probe_test,
    // which measures both the striped decode and the AXI path into this window.
    //
    // Strictly a read. It must never be used to deposit the payload, flush a
    // cache, or otherwise help the DUT reach a pass -- that would hide the very
    // defect this port exists to identify.
    input  wire logic [19:0] tb_dut_scratch_peek_offset /*verilator public_flat_rw*/,
    output logic [63:0]      tb_dut_scratch_peek_data /*verilator public_flat_rw*/,
    output logic [7:0]       tb_dut_scratch_peek_ecc /*verilator public_flat_rw*/,
    // Same, for the CONTROLLER. Needed to prove the payload is where scratch 5
    // says it is before blaming the transfer: the controller reads the image out
    // of its own SRAM with ordinary loads, and a preload that landed in the
    // wrong place would send zeros while every OCCP header still looked perfect.
    input  wire logic [19:0] tb_bfm_scratch_peek_offset /*verilator public_flat_rw*/,
    output logic [63:0]      tb_bfm_scratch_peek_data /*verilator public_flat_rw*/,
    output logic [7:0]       tb_bfm_scratch_peek_ecc /*verilator public_flat_rw*/,

    // ------------------------------------------------------------------
    // Controller I3C TX-port snoop (read-only).
    //
    // The one link in the OCCP chain that nothing else can observe: what the
    // controller actually pushes into the I3C core's PIO TX port. It separates
    // "the controller read zeros out of its own SRAM and streamed zeros" from
    // "the controller streamed the payload and it was lost on the bus or in the
    // target's receive path".
    //
    // Snoops the AXI-Lite write channel into u_bfm's I3C wrapper, filtered to
    // the TX_PORT offset (0x088). Captures the first words of each transfer;
    // for a 100-byte OCCP WRITE frame the first 8 DWORDs cover the 8-byte
    // request header, the 12 metadata bytes, and the first 12 payload bytes --
    // exactly the boundary where the data goes missing.
    output logic [31:0] tb_bfm_i3c_tx_count /*verilator public_flat_rw*/,
    output logic [31:0] tb_bfm_i3c_tx_word_0 /*verilator public_flat_rw*/,
    output logic [31:0] tb_bfm_i3c_tx_word_1 /*verilator public_flat_rw*/,
    output logic [31:0] tb_bfm_i3c_tx_word_2 /*verilator public_flat_rw*/,
    output logic [31:0] tb_bfm_i3c_tx_word_3 /*verilator public_flat_rw*/,
    output logic [31:0] tb_bfm_i3c_tx_word_4 /*verilator public_flat_rw*/,
    output logic [31:0] tb_bfm_i3c_tx_word_5 /*verilator public_flat_rw*/,
    output logic [31:0] tb_bfm_i3c_tx_word_6 /*verilator public_flat_rw*/,
    output logic [31:0] tb_bfm_i3c_tx_word_7 /*verilator public_flat_rw*/,

    // Elaboration alias.
    output logic dual_present_o /*verilator public_flat_rw*/
`endif  // SMC_DUAL
);
`else
;
    `include "smc_tb_signal_list.svh"
`endif

`undef SMC_TB_IN_FIRST
`undef SMC_TB_IN
`undef SMC_TB_OUT

    // The three domain clocks, taken from the pll_wrap inside the DUT (the
    // target instance under SMC_DUAL) and exported on clk_*_o.
    logic clk_smc, clk_ref, clk_periph;

`ifndef SMC_DUAL
    /* verilator public_module */

    // Cocotb drives rst_cold_ni / rst_cool_ni / powergood_i after time 0.
    // Until then each input wire is Z, and PeakRDL immediate asserts in an
    // always_ff else treat `if (~arst_n)` as false when arst_n is X/Z. Hold
    // the safe idle (resets asserted, powergood low) until the port is a
    // known 0/1, then follow. An X/Z after cocotb has driven the port is a
    // testbench defect: latching the last good level would hide it, so it
    // fails here instead.
    //
    // $fatal, not $error: $error only prints on Xcelium and VCS -- the run
    // would go green with the DUT on a stale reset level. It is also not a DUT
    // finding that a scoreboard should weigh; the stimulus is wrong and nothing
    // after it means anything.
    //
    // Each block is sensitive to its input alone rather than @(*). Under @(*)
    // the *_driven flag it writes is also in its own inferred sensitivity
    // list, which makes the block self-retriggering and draws UNOPTFLAT and
    // LATCH from Verilator; *_int holds the last known level between events.
    logic rst_cold_n_int = 1'b0;
    logic rst_cold_n_driven = 1'b0;
    always @(rst_cold_ni) begin
        if ((rst_cold_ni === 1'b0) || (rst_cold_ni === 1'b1)) begin
            rst_cold_n_int = rst_cold_ni;
            rst_cold_n_driven = 1'b1;
        end else if (rst_cold_n_driven) begin
            $fatal(1, "%0t: rst_cold_ni went %b after being driven; the DUT would run on the last known level",
                   $time, rst_cold_ni);
        end
    end

    logic rst_cool_n_int = 1'b0;
    logic rst_cool_n_driven = 1'b0;
    always @(rst_cool_ni) begin
        if ((rst_cool_ni === 1'b0) || (rst_cool_ni === 1'b1)) begin
            rst_cool_n_int = rst_cool_ni;
            rst_cool_n_driven = 1'b1;
        end else if (rst_cool_n_driven) begin
            $fatal(1, "%0t: rst_cool_ni went %b after being driven; the DUT would run on the last known level",
                   $time, rst_cool_ni);
        end
    end

    logic powergood_int = 1'b0;
    logic powergood_driven = 1'b0;
    always @(powergood_i) begin
        if ((powergood_i === 1'b0) || (powergood_i === 1'b1)) begin
            powergood_int = powergood_i;
            powergood_driven = 1'b1;
        end else if (powergood_driven) begin
            $fatal(1, "%0t: powergood_i went %b after being driven; the DUT would run on the last known level",
                   $time, powergood_i);
        end
    end

    // Assertion classes held off, and why each is not a DUT contract here.
    //
    // noXOnCsI: prim_rom.sv:40 is `assert property (@(posedge clk_i)
    // disable iff (('0) !== '0) !$isunknown(req_i))`. The disable is never
    // true, so the reset hold above cannot gate it, and req_i is X until
    // the TileLink converter leaves reset. Hold this one assertion off
    // until cold reset has released and one SMC clock edge has sampled a
    // known req_i, then re-arm by the assertion's own hierarchical name
    // so a later X still fails. $assertcontrol is not used: the commercial
    // compile timescale is 1ns/1ps, and Xcelium rejects $assertcontrol(4, 31).
`ifndef VERILATOR
    initial begin
        $assertoff(0, u_dut.u_smc_ip_integration.u_mems.u_rom_mem.u_mem.noXOnCsI);
        wait (rst_cold_n_int === 1'b1);
        @(posedge clk_smc);
        $asserton(0, u_dut.u_smc_ip_integration.u_mems.u_rom_mem.u_mem.noXOnCsI);
    end
`endif

    // The force-mode CPU reset withdraws the R beat the CPU is presenting to
    // the front-port demux without `ready`
    // (cocotb/seq_lib/README_cpu_isolate_flush.md), and the R arbiter's
    // request-stability assertions report that withdrawal. Only the leaf that
    // reaches the state on purpose asks for that arbiter's checks off; the
    // scope is the one arbiter instance, so every other assertion stays armed.
`ifndef VERILATOR
    initial begin
        if ($test$plusargs("smc_front_port_r_arb_assertoff")) begin
            $assertoff(0, u_dut.u_smc.u_smc_cpu_wrapper.u_front_port_demux
                .i_demux_simple.genblk1.i_r_mux);
        end
    end
`endif

    localparam logic [31:0] SmcTestPass = 32'hACAF_ACA1;
    localparam logic [31:0] SmcTestFail = 32'hFFFF_FFFF;

    smc_sep_in_56_64_6_12_axi_req_t  sep_axi_in_req;
    smc_sep_in_56_64_6_12_axi_resp_t sep_axi_in_resp;
    smc_sys_in_56_64_6_12_axi_req_t  sys_axi_in_req;
    smc_sys_in_56_64_6_12_axi_resp_t sys_axi_in_resp;
    smc_jtag_56_64_2_12_axi_req_t    jtag_axi_in_req;
    smc_jtag_56_64_2_12_axi_resp_t   jtag_axi_in_resp;
    smc_sys_out_56_64_8_12_axi_req_t  output_axi_req;
    smc_sys_out_56_64_8_12_axi_resp_t output_axi_resp;

    // Physical GPIO pad bus between smc_wrapper's internal smc <->
    // smc_ip_integration prim_pad_shim instances and this TB. Driven by the
    // per-pin injection block below; see header risk note.
    wire [smc_pkg::NumGpioWraps-1:0] gpio_pad_io;
    logic [smc_pkg::NumGpioWraps-1:0] tb_pad_drive_en;
    logic [smc_pkg::NumGpioWraps-1:0] tb_pad_drive_val;

    // Telemetry ATB bundle. Every receiver's AT channel is lifted to the signal
    // list; the AF channel is lifted for receiver 0 only and every receiver
    // above index 2 keeps the constants the tie-off below presented.
    telemetry_receiver_pkg::telemetry_data_t
        [smc_config_pkg::NumTelemetryReceivers-1:0] tb_telemetry_atdata;
    telemetry_receiver_pkg::atb_id_t
        [smc_config_pkg::NumTelemetryReceivers-1:0] tb_telemetry_atid;
    logic [smc_config_pkg::NumTelemetryReceivers-1:0] tb_telemetry_atvalid;
    logic [smc_config_pkg::NumTelemetryReceivers-1:0] tb_telemetry_atready;
    logic [smc_config_pkg::NumTelemetryReceivers-1:0] tb_telemetry_afvalid;
    logic [smc_config_pkg::NumTelemetryReceivers-1:0] tb_telemetry_afready;

    assign tb_telemetry_atdata[0] = tb_telemetry0_atdata;
    assign tb_telemetry_atid[0] = tb_telemetry0_atid;
    assign tb_telemetry_atvalid[0] = tb_telemetry0_atvalid;
    assign tb_telemetry0_atready = tb_telemetry_atready[0];
    assign tb_telemetry0_afvalid = tb_telemetry_afvalid[0];
    assign tb_telemetry_afready[0] = tb_telemetry0_afready;
    if (smc_config_pkg::NumTelemetryReceivers > 1) begin : gen_tel1_lift
        assign tb_telemetry_atdata[1] = tb_telemetry1_atdata;
        assign tb_telemetry_atid[1] = tb_telemetry1_atid;
        assign tb_telemetry_atvalid[1] = tb_telemetry1_atvalid;
        assign tb_telemetry1_atready = tb_telemetry_atready[1];
    end else begin : gen_tel1_absent
        assign tb_telemetry1_atready = 1'b0;
    end
    if (smc_config_pkg::NumTelemetryReceivers > 2) begin : gen_tel2_lift
        assign tb_telemetry_atdata[2] = tb_telemetry2_atdata;
        assign tb_telemetry_atid[2] = tb_telemetry2_atid;
        assign tb_telemetry_atvalid[2] = tb_telemetry2_atvalid;
        assign tb_telemetry2_atready = tb_telemetry_atready[2];
    end else begin : gen_tel2_absent
        assign tb_telemetry2_atready = 1'b0;
    end
    // Receivers past index 2 keep the AT tie-off; the AF channel of every
    // receiver except 0 keeps its ready high, exactly as before the lift.
    for (genvar tel_i = 3; tel_i < smc_config_pkg::NumTelemetryReceivers; tel_i++) begin : gen_tel_at_tie
        assign tb_telemetry_atdata[tel_i] = '0;
        assign tb_telemetry_atid[tel_i] = '0;
        assign tb_telemetry_atvalid[tel_i] = 1'b0;
    end
    for (genvar tel_i = 1; tel_i < smc_config_pkg::NumTelemetryReceivers; tel_i++) begin : gen_tel_af_tie
        assign tb_telemetry_afready[tel_i] = 1'b1;
    end

    // The adopter external window (PLL / PVT / GPIO ctrl) and the eFuse
    // bank/shim macro live inside hw/top/smc_ip_integration.sv (u_smc's
    // smc_external_req_o feeds u_smc_ip_integration directly inside
    // smc_wrapper), so they are not boundary ports of smc_wrapper and nothing
    // is declared or terminated for them at this TB level (see header comment).
    // DTP CSR (axil_dtp_csr_req_o) is a smc_wrapper boundary port.
    smc_axil_32_32_req_t  axil_dtp_csr_req;
    smc_axil_32_32_resp_t axil_dtp_csr_resp;

    // Direct smc_wrapper boundary ports (top-level outputs).
    logic sync_irq;
    logic [smc_pkg::NumGpioWraps-1:0]     gpio_interrupt;
    logic [smc_config_pkg::NumUart-1:0]   uart_interrupt;
    // Boundary ports observed only by the cov/sv functional-coverage modules.
    logic                                  rst_primary_periph_clk_n;
    smc_efuse_pkg::efuse_map_t             shadow_regs;
    logic [31:0]                           smc_region_size;
    logic [31:0]                           ss_config;
    logic [63:0]                           timer_count;
    logic                                  lc_sigint_err;
    logic [cla_pkg::CLA_NUMBER_OF_CUSTOM_ACTIONS-1:0] cla_ext_action_custom;
    logic                                  ext_boot_seq_done;

    localparam int unsigned I2c0SclPad = 37;
    localparam int unsigned I2c0SdaPad = 38;
    localparam int unsigned I2c0SmbAlertPad = 39;
    localparam int unsigned I2c0SmbSusPad = 40;
    // I2C1 pads (padring: 37+4*i / 38+4*i). Commercial TB shorts I2C0/1/2
    // SCL/SDA via tranif1 for internal P0 controller↔target loops.
    localparam int unsigned I2c1SclPad = 41;
    localparam int unsigned I2c1SdaPad = 42;
    localparam int unsigned I2c1SmbAlertPad = 43;
    localparam int unsigned I2c1SmbSusPad = 44;
    localparam int unsigned I2c2SclPad = 45;
    localparam int unsigned I2c2SdaPad = 46;
    localparam int unsigned I2c2SmbAlertPad = 47;
    localparam int unsigned I2c2SmbSusPad = 48;
    localparam int unsigned I3c0SclPad = 27;
    localparam int unsigned I3c0SdaPad = 28;
    // Per smc_padring.sv gen_uart_connections (base 11+4*u): RX is pad -> core,
    // TX is core -> pad.
    localparam int unsigned Uart0RxPad = 11;
    localparam int unsigned Uart0TxPad = 12;
    localparam int unsigned Uart1RxPad = 11 + (1 * 4); // pad 15
    localparam int unsigned Uart1TxPad = 12 + (1 * 4); // pad 16
    localparam int unsigned Uart2RxPad = 11 + (2 * 4); // pad 19
    localparam int unsigned Uart2TxPad = 12 + (2 * 4); // pad 20
    localparam int unsigned Uart3RxPad = 11 + (3 * 4); // pad 23
    localparam int unsigned Uart3TxPad = 12 + (3 * 4); // pad 24
    // smc_padring.sv: boot_stall is an lsio pad, active-high.
    // Default pullup/'1 would sticky-stall fuse_reset_n and hold the warm
    // reset domain (SCRATCH_COLD_WARM hang). Drive 0 unless +smc_hold_cpu_boot.
    localparam int unsigned BootStallPad = 57;
    bit tb_hold_cpu_boot /*verilator public_flat_rw*/;
    // +smc_hold_ext_boot: keep ext_boot_seq_done_i=0 from t=0 so
    // fuse_reset_n stays low after sense (efuse_interface_controller
    // reset_n = sense && rst_ni && ext_boot_seq_done).
    bit tb_hold_ext_boot /*verilator public_flat_rw*/;
    // ext_interrupts_i[16:2], PLIC sources 3-17; bits 1 and 0 keep their own pins.
    bit [16:2] tb_ext_interrupts_hi_i /*verilator public_flat_rw*/;
    // +smc_uart_cross_3to0: short commercial UART pairs 0↔3 and 1↔2
    // (TX of each into RX of the peer).
    bit tb_uart_cross_3to0;
    initial begin
        tb_hold_cpu_boot = 1'b0;
        if ($test$plusargs("smc_hold_cpu_boot")) begin
            tb_hold_cpu_boot = 1'b1;
            $display("[tb_top] +smc_hold_cpu_boot: pad57 boot_stall held until TB release");
        end
        tb_hold_ext_boot = 1'b0;
        if ($test$plusargs("smc_hold_ext_boot")) begin
            tb_hold_ext_boot = 1'b1;
            $display("[tb_top] +smc_hold_ext_boot: ext_boot_seq_done held 0 until TB release");
        end
        tb_uart_cross_3to0 = 1'b0;
        if ($test$plusargs("smc_uart_cross_3to0")) begin
            tb_uart_cross_3to0 = 1'b1;
            $display("[tb_top] +smc_uart_cross_3to0: UART0<->3 and UART1<->2 TX/RX short");
        end
    end

    // Minimal LSIO open-drain resolver for I2C0. The SMC padring maps I2C0
    // SCL/SDA to the I2C0 GPIO pads. Released lines resolve high; either the DUT
    // or cocotb side may pull a line low.
    //
    // +smc_i2c_shared_bus: OR I2C1/I2C2 open-drain pulls into the same resolved
    // bus and drive those pads with that value (commercial tranif1 short).
    // Default off so existing I2C0↔VIP tests stay isolated.
    logic tb_i2c_shared_bus;
    logic tb_i2c1_scl_dut_low;
    logic tb_i2c1_sda_dut_low;
    logic tb_i2c2_scl_dut_low;
    logic tb_i2c2_sda_dut_low;
    initial begin
        tb_i2c_shared_bus = 1'b0;
        if ($test$plusargs("smc_i2c_shared_bus")) begin
            tb_i2c_shared_bus = 1'b1;
            $display("[tb_top] +smc_i2c_shared_bus: I2C0/I2C1/I2C2 pads share OD bus (SCL/SDA + SMBus alert/suspend)");
        end
    end
    assign tb_i2c0_scl_dut_low = !u_dut.u_smc.u_smc_peripherals.i2c_scl_o[0];
    assign tb_i2c0_sda_dut_low = !u_dut.u_smc.u_smc_peripherals.i2c_sda_o[0];
    assign tb_i2c1_scl_dut_low = !u_dut.u_smc.u_smc_peripherals.i2c_scl_o[1];
    assign tb_i2c1_sda_dut_low = !u_dut.u_smc.u_smc_peripherals.i2c_sda_o[1];
    assign tb_i2c2_scl_dut_low = !u_dut.u_smc.u_smc_peripherals.i2c_scl_o[2];
    assign tb_i2c2_sda_dut_low = !u_dut.u_smc.u_smc_peripherals.i2c_sda_o[2];
    assign tb_i2c0_scl = !(tb_i2c0_scl_dut_low || tb_i2c0_scl_ext_low ||
                           (tb_i2c_shared_bus && (tb_i2c1_scl_dut_low ||
                                                  tb_i2c2_scl_dut_low)));
    assign tb_i2c0_sda = !(tb_i2c0_sda_dut_low || tb_i2c0_sda_ext_low ||
                           (tb_i2c_shared_bus && (tb_i2c1_sda_dut_low ||
                                                  tb_i2c2_sda_dut_low)));
    // SMBus sideband OD (commercial tranif1 on i2c_smbus_alert / suspend):
    // wrap *_no is 0 while that controller asserts the open-drain line.
    logic tb_i2c0_smbalert_dut_low;
    logic tb_i2c1_smbalert_dut_low;
    logic tb_i2c2_smbalert_dut_low;
    logic tb_i2c0_smbsus_dut_low;
    logic tb_i2c1_smbsus_dut_low;
    logic tb_i2c2_smbsus_dut_low;
    logic tb_i2c_smbalert;
    logic tb_i2c_smbsus;
    assign tb_i2c0_smbalert_dut_low =
        !u_dut.u_smc.u_smc_peripherals.i2c_smbalert_no[0];
    assign tb_i2c1_smbalert_dut_low =
        !u_dut.u_smc.u_smc_peripherals.i2c_smbalert_no[1];
    assign tb_i2c2_smbalert_dut_low =
        !u_dut.u_smc.u_smc_peripherals.i2c_smbalert_no[2];
    assign tb_i2c0_smbsus_dut_low =
        !u_dut.u_smc.u_smc_peripherals.i2c_smbsus_no[0];
    assign tb_i2c1_smbsus_dut_low =
        !u_dut.u_smc.u_smc_peripherals.i2c_smbsus_no[1];
    assign tb_i2c2_smbsus_dut_low =
        !u_dut.u_smc.u_smc_peripherals.i2c_smbsus_no[2];
    assign tb_i2c_smbalert = !(tb_i2c0_smbalert_dut_low ||
                               (tb_i2c_shared_bus &&
                                (tb_i2c1_smbalert_dut_low ||
                                 tb_i2c2_smbalert_dut_low)));
    assign tb_i2c_smbsus = !(tb_i2c0_smbsus_dut_low ||
                             (tb_i2c_shared_bus &&
                              (tb_i2c1_smbsus_dut_low ||
                               tb_i2c2_smbsus_dut_low)));
    assign tb_i2c0_enable = u_dut.u_smc.u_smc_peripherals.i2c_enable_smc_clk[0];
    assign tb_i2c0_scl_i  = u_dut.u_smc.u_smc_peripherals.i2c_scl_i[0];
    assign tb_i2c0_sda_i  = u_dut.u_smc.u_smc_peripherals.i2c_sda_i[0];
    assign tb_i3c0_scl_dut_low = u_dut.u_smc.u_smc_peripherals.i3c_scl_oe_to_pad[0] &&
                                  !u_dut.u_smc.u_smc_peripherals.i3c_scl_to_pad[0];
    assign tb_i3c0_sda_dut_low = u_dut.u_smc.u_smc_peripherals.i3c_sda_oe_to_pad[0] &&
                                  !u_dut.u_smc.u_smc_peripherals.i3c_sda_to_pad[0];
    assign tb_i3c0_scl = !(tb_i3c0_scl_dut_low || tb_i3c0_scl_ext_low);
    assign tb_i3c0_sda = !(tb_i3c0_sda_dut_low || tb_i3c0_sda_ext_low);

    // ------------------------------------------------------------------
    // Pad injection (KNOWN RISK).
    //
    // pad2core/core2pad are internal smc_wrapper nets routed through one
    // prim_pad_shim.sv per pin (hw/top/smc_ip_integration.sv) onto the
    // physical `gpio_pad_io` inout bus. There is no legal way to XMR-assign
    // `u_dut.u_smc.pad2core_i` (it is already driven by u_smc_ip_integration's
    // pad2core_o), so external stimulus must be injected onto `gpio_pad_io`
    // itself:
    //   - A weak `pullup` per pin gives idle/unconnected pads a defined '1
    //     without ever contending with a real (strength-1) driver.
    //   - `tb_pad_drive_en/val` strongly drive only the specific pins this
    //     TB wants to inject (GPIO overrides, I2C0/I3C0 open-drain lines,
    //     UART0 RX, SPI DQ0 MISO, AVSBus sdata, OCTS secondary inject,
    //     boot-stall hold).
    //   - For I2C0/I3C0, the resolved value (DUT-low XMR probe OR ext-low)
    //     is *always* strongly driven back onto the pad so pad2core reads
    //     the correct bus state for ACK / clock-stretch. This assumes the
    //     digital I2C/I3C core only asserts its own pad OE while driving
    //     logic 0 (never asserts OE to push a logic 1); if that assumption is
    //     ever violated, the DUT's own strong '1 push and this block's strong
    //     '0 pull could momentarily contend (X) around edges.
    //   - All other DUT-owned output pads (UART0 TX, AVS clk/mdata, OCTS
    //     observe, general GPIO outputs) are left un-driven here (Z) and
    //     read back via XMR into u_dut.u_smc.core2pad_o/core2pad_en_o, so
    //     this injection block never contends with the DUT's own output drive
    //     on those pins.
    // ------------------------------------------------------------------
    always_comb begin
        tb_pad_drive_en  = '0;
        tb_pad_drive_val = '1;

        for (int unsigned gpio_idx = 0; gpio_idx < smc_pkg::NumGpioWraps; gpio_idx++) begin
            if (tb_gpio_ext_drive_en[gpio_idx]) begin
                tb_pad_drive_en[gpio_idx]  = 1'b1;
                tb_pad_drive_val[gpio_idx] = tb_gpio_ext_drive_value[gpio_idx];
            end
        end

        // I2C0 / I3C0 open-drain pads: Verilator ignores `pullup`, so always
        // strongly drive the resolved OD value (0 when DUT or VIP pulls low,
        // 1 when both released). Safe because the digital I2C/I3C core only
        // asserts OE while driving logic 0 (never pushes a strong 1).
        tb_pad_drive_en[I2c0SclPad]  = 1'b1;
        tb_pad_drive_val[I2c0SclPad] = tb_i2c0_scl;
        tb_pad_drive_en[I2c0SdaPad]  = 1'b1;
        tb_pad_drive_val[I2c0SdaPad] = tb_i2c0_sda;
        if (tb_i2c_shared_bus) begin
            tb_pad_drive_en[I2c1SclPad]  = 1'b1;
            tb_pad_drive_val[I2c1SclPad] = tb_i2c0_scl;
            tb_pad_drive_en[I2c1SdaPad]  = 1'b1;
            tb_pad_drive_val[I2c1SdaPad] = tb_i2c0_sda;
            tb_pad_drive_en[I2c2SclPad]  = 1'b1;
            tb_pad_drive_val[I2c2SclPad] = tb_i2c0_scl;
            tb_pad_drive_en[I2c2SdaPad]  = 1'b1;
            tb_pad_drive_val[I2c2SdaPad] = tb_i2c0_sda;
            // Shared SMBus alert / suspend (commercial i2c_smbus_alert/suspend).
            tb_pad_drive_en[I2c0SmbAlertPad]  = 1'b1;
            tb_pad_drive_val[I2c0SmbAlertPad] = tb_i2c_smbalert;
            tb_pad_drive_en[I2c1SmbAlertPad]  = 1'b1;
            tb_pad_drive_val[I2c1SmbAlertPad] = tb_i2c_smbalert;
            tb_pad_drive_en[I2c2SmbAlertPad]  = 1'b1;
            tb_pad_drive_val[I2c2SmbAlertPad] = tb_i2c_smbalert;
            tb_pad_drive_en[I2c0SmbSusPad]  = 1'b1;
            tb_pad_drive_val[I2c0SmbSusPad] = tb_i2c_smbsus;
            tb_pad_drive_en[I2c1SmbSusPad]  = 1'b1;
            tb_pad_drive_val[I2c1SmbSusPad] = tb_i2c_smbsus;
            tb_pad_drive_en[I2c2SmbSusPad]  = 1'b1;
            tb_pad_drive_val[I2c2SmbSusPad] = tb_i2c_smbsus;
        end
        tb_pad_drive_en[I3c0SclPad]  = 1'b1;
        tb_pad_drive_val[I3c0SclPad] = tb_i3c0_scl;
        tb_pad_drive_en[I3c0SdaPad]  = 1'b1;
        tb_pad_drive_val[I3c0SdaPad] = tb_i3c0_sda;

        // UART0 RX: external VIP, or UART3 TX when +smc_uart_cross_3to0.
        tb_pad_drive_en[Uart0RxPad]  = 1'b1;
        tb_pad_drive_val[Uart0RxPad] = tb_uart_cross_3to0
            ? u_dut.u_smc.core2pad_o[Uart3TxPad]
            : tb_uart0_rx_ext_drive;
        if (tb_uart_cross_3to0) begin
            // Pair 0↔3
            tb_pad_drive_en[Uart3RxPad]  = 1'b1;
            tb_pad_drive_val[Uart3RxPad] = u_dut.u_smc.core2pad_o[Uart0TxPad];
            // Pair 1↔2
            tb_pad_drive_en[Uart2RxPad]  = 1'b1;
            tb_pad_drive_val[Uart2RxPad] = u_dut.u_smc.core2pad_o[Uart1TxPad];
            tb_pad_drive_en[Uart1RxPad]  = 1'b1;
            tb_pad_drive_val[Uart1RxPad] = u_dut.u_smc.core2pad_o[Uart2TxPad];
        end

        // Boot stall: released by default; held when +smc_hold_cpu_boot is set
        // unless a test explicitly drives BootStallPad via GPIO override.
        if (!tb_gpio_ext_drive_en[BootStallPad]) begin
            tb_pad_drive_en[BootStallPad]  = 1'b1;
            tb_pad_drive_val[BootStallPad] = tb_hold_cpu_boot;
        end

        // SPI DQ0 MISO from flash BFM when SPI mux is enabled (pads 0-7).
        if (tb_spi_enable) begin
            tb_pad_drive_en[0]  = 1'b1;
            tb_pad_drive_val[0] = tb_spi_miso_ext;
        end

        // AVSBus sdata (pad 51): external slave ACK BFM into DUT.
        tb_pad_drive_en[51]  = 1'b1;
        tb_pad_drive_val[51] = tb_avs_sdata_ext;

        // OCTS dual-chiplet secondary inject (pads 55/56). Harmless when
        // primary (padring disables pad2core on these pads).
        tb_pad_drive_en[55]  = 1'b1;
        tb_pad_drive_val[55] = tb_octs_sync_load_ext;
        tb_pad_drive_en[56]  = 1'b1;
        tb_pad_drive_val[56] = tb_octs_cnt_credit_ext;
    end

    for (genvar gpio_idx = 0; gpio_idx < smc_pkg::NumGpioWraps; gpio_idx++) begin : gen_gpio_pad_drive
        // Weak pull-up default (never contends with any real driver) plus a
        // strong TB-owned drive only where tb_pad_drive_en requests one.
        pullup u_pad_pullup (gpio_pad_io[gpio_idx]);
        assign gpio_pad_io[gpio_idx] = tb_pad_drive_en[gpio_idx] ? tb_pad_drive_val[gpio_idx] : 1'bz;
    end

    // UART0 TX: the DUT drives one line out to the external world.
    assign tb_uart0_tx_from_dut = u_dut.u_smc.core2pad_o[Uart0TxPad];
    assign tb_uart0_tx_ready = u_dut.u_smc.u_smc_peripherals.u_uart_wrap
        .gen_uart_log_engine_wraps[0].u_uart_log_engine_wrap.uart_txrdy_o;
    // A fetched byte waits at the head of the engine's read-data FIFO while the
    // UART cannot accept it: the write FSM stays in its request state on these
    // cycles (log_engine.sv advances only on rdata valid AND uart_tx_ready).
    assign tb_uart0_log_write_stalled = u_dut.u_smc.u_smc_peripherals.u_uart_wrap
        .gen_uart_log_engine_wraps[0].u_uart_log_engine_wrap.gen_log_engine.u_log_engine.rdata_fifo_rd_valid
        & ~tb_uart0_tx_ready;
    // I2C0 SMBALERT#: OE-aware resolve (active-low when DUT drives).
    // core2pad_en_o is active-high (~lsio_core2pad_en_ni); data is 0 when OE.
    // Under +smc_i2c_shared_bus the pad is TB-driven with the shared OD net.
    assign tb_i2c0_smbalert = tb_i2c_shared_bus
                              ? tb_i2c_smbalert
                              : (u_dut.u_smc.core2pad_en_o[I2c0SmbAlertPad]
                                 ? u_dut.u_smc.core2pad_o[I2c0SmbAlertPad]
                                 : 1'b1);
    // AVSBus pads 49/50 (clk/mdata) and OCTS pads 55/56 (sync/credit) observe.
    assign tb_avs_clk_from_dut = u_dut.u_smc.core2pad_o[49];
    assign tb_avs_mdata_from_dut = u_dut.u_smc.core2pad_o[50];
    assign tb_octs_sync_load_from_dut = u_dut.u_smc.core2pad_o[55];
    assign tb_octs_cnt_credit_from_dut = u_dut.u_smc.core2pad_o[56];

    assign sep_axi_in_req.aw.id     = s_axi_awid;
    assign sep_axi_in_req.aw.addr   = s_axi_awaddr;
    assign sep_axi_in_req.aw.len    = s_axi_awlen;
    assign sep_axi_in_req.aw.size   = s_axi_awsize;
    assign sep_axi_in_req.aw.burst  = s_axi_awburst;
    assign sep_axi_in_req.aw.lock   = s_axi_awlock;
    assign sep_axi_in_req.aw.cache  = s_axi_awcache;
    assign sep_axi_in_req.aw.prot   = s_axi_awprot;
    assign sep_axi_in_req.aw.qos    = s_axi_awqos;
    assign sep_axi_in_req.aw.region = s_axi_awregion;
    assign sep_axi_in_req.aw.user   = s_axi_awuser;
    // Pack ATOP=0 on all AXI ingresses; the outbound filter's err_slv is
    // built with `.ATOPs(1'b0)` and its `assume` on `atop == '0 fires a
    // fatal on Xcelium when the field is left X-propagating.
    assign sep_axi_in_req.aw.atop   = '0;
    assign sep_axi_in_req.aw_valid  = s_axi_awvalid;
    assign s_axi_awready            = sep_axi_in_resp.aw_ready;

    assign sep_axi_in_req.w.data    = s_axi_wdata;
    assign sep_axi_in_req.w.strb    = s_axi_wstrb;
    assign sep_axi_in_req.w.last    = s_axi_wlast;
    assign sep_axi_in_req.w.user    = s_axi_wuser;
    assign sep_axi_in_req.w_valid   = s_axi_wvalid;
    assign s_axi_wready             = sep_axi_in_resp.w_ready;

    assign s_axi_bid                = sep_axi_in_resp.b.id;
    assign s_axi_bresp              = sep_axi_in_resp.b.resp;
    assign s_axi_buser              = sep_axi_in_resp.b.user;
    assign s_axi_bvalid             = sep_axi_in_resp.b_valid & ~tb_sep_axi_b_hold;
    assign sep_axi_in_req.b_ready   = s_axi_bready & ~tb_sep_axi_b_hold;

    assign sep_axi_in_req.ar.id     = s_axi_arid;
    assign sep_axi_in_req.ar.addr   = s_axi_araddr;
    assign sep_axi_in_req.ar.len    = s_axi_arlen;
    assign sep_axi_in_req.ar.size   = s_axi_arsize;
    assign sep_axi_in_req.ar.burst  = s_axi_arburst;
    assign sep_axi_in_req.ar.lock   = s_axi_arlock;
    assign sep_axi_in_req.ar.cache  = s_axi_arcache;
    assign sep_axi_in_req.ar.prot   = s_axi_arprot;
    assign sep_axi_in_req.ar.qos    = s_axi_arqos;
    assign sep_axi_in_req.ar.region = s_axi_arregion;
    assign sep_axi_in_req.ar.user   = s_axi_aruser;
    assign sep_axi_in_req.ar_valid  = s_axi_arvalid;
    assign s_axi_arready            = sep_axi_in_resp.ar_ready;

    assign s_axi_rid                = sep_axi_in_resp.r.id;
    assign s_axi_rdata              = sep_axi_in_resp.r.data;
    assign s_axi_rresp              = sep_axi_in_resp.r.resp;
    assign s_axi_rlast              = sep_axi_in_resp.r.last;
    assign s_axi_ruser              = sep_axi_in_resp.r.user;
    assign tb_sep_axi_r_raw_valid   = sep_axi_in_resp.r_valid;
    assign s_axi_rvalid = sep_axi_in_resp.r_valid &
                          ~(tb_sep_axi_r_hold | tb_sep_axi_r_drop);
    assign sep_axi_in_req.r_ready = tb_sep_axi_r_drop |
                                    (s_axi_rready & ~tb_sep_axi_r_hold);

    assign sys_axi_in_req.aw.id     = sys_axi_awid;
    assign sys_axi_in_req.aw.addr   = sys_axi_awaddr;
    assign sys_axi_in_req.aw.len    = sys_axi_awlen;
    assign sys_axi_in_req.aw.size   = sys_axi_awsize;
    assign sys_axi_in_req.aw.burst  = sys_axi_awburst;
    assign sys_axi_in_req.aw.lock   = sys_axi_awlock;
    assign sys_axi_in_req.aw.cache  = sys_axi_awcache;
    assign sys_axi_in_req.aw.prot   = sys_axi_awprot;
    assign sys_axi_in_req.aw.qos    = sys_axi_awqos;
    assign sys_axi_in_req.aw.region = sys_axi_awregion;
    assign sys_axi_in_req.aw.user   = sys_axi_awuser;
    assign sys_axi_in_req.aw.atop   = '0;
    assign sys_axi_in_req.aw_valid  = sys_axi_awvalid;
    assign sys_axi_awready          = sys_axi_in_resp.aw_ready;

    assign sys_axi_in_req.w.data    = sys_axi_wdata;
    assign sys_axi_in_req.w.strb    = sys_axi_wstrb;
    assign sys_axi_in_req.w.last    = sys_axi_wlast;
    assign sys_axi_in_req.w.user    = sys_axi_wuser;
    assign sys_axi_in_req.w_valid   = sys_axi_wvalid;
    assign sys_axi_wready           = sys_axi_in_resp.w_ready;

    assign sys_axi_bid              = sys_axi_in_resp.b.id;
    assign sys_axi_bresp            = sys_axi_in_resp.b.resp;
    assign sys_axi_buser            = sys_axi_in_resp.b.user;
    assign sys_axi_bvalid           = sys_axi_in_resp.b_valid;
    assign sys_axi_in_req.b_ready   = sys_axi_bready;

    assign sys_axi_in_req.ar.id     = sys_axi_arid;
    assign sys_axi_in_req.ar.addr   = sys_axi_araddr;
    assign sys_axi_in_req.ar.len    = sys_axi_arlen;
    assign sys_axi_in_req.ar.size   = sys_axi_arsize;
    assign sys_axi_in_req.ar.burst  = sys_axi_arburst;
    assign sys_axi_in_req.ar.lock   = sys_axi_arlock;
    assign sys_axi_in_req.ar.cache  = sys_axi_arcache;
    assign sys_axi_in_req.ar.prot   = sys_axi_arprot;
    assign sys_axi_in_req.ar.qos    = sys_axi_arqos;
    assign sys_axi_in_req.ar.region = sys_axi_arregion;
    assign sys_axi_in_req.ar.user   = sys_axi_aruser;
    assign sys_axi_in_req.ar_valid  = sys_axi_arvalid;
    assign sys_axi_arready          = sys_axi_in_resp.ar_ready;

    assign sys_axi_rid              = sys_axi_in_resp.r.id;
    assign sys_axi_rdata            = sys_axi_in_resp.r.data;
    assign sys_axi_rresp            = sys_axi_in_resp.r.resp;
    assign sys_axi_rlast            = sys_axi_in_resp.r.last;
    assign sys_axi_ruser            = sys_axi_in_resp.r.user;
    assign tb_sys_axi_r_raw_valid   = sys_axi_in_resp.r_valid;
    assign sys_axi_rvalid = sys_axi_in_resp.r_valid &
                            ~(tb_sys_axi_r_hold | tb_sys_axi_r_drop);
    assign sys_axi_in_req.r_ready = tb_sys_axi_r_drop |
                                    (sys_axi_rready & ~tb_sys_axi_r_hold);

    assign jtag_axi_in_req.aw.id     = jtag_axi_awid;
    assign jtag_axi_in_req.aw.addr   = jtag_axi_awaddr;
    assign jtag_axi_in_req.aw.len    = jtag_axi_awlen;
    assign jtag_axi_in_req.aw.size   = jtag_axi_awsize;
    assign jtag_axi_in_req.aw.burst  = jtag_axi_awburst;
    assign jtag_axi_in_req.aw.lock   = jtag_axi_awlock;
    assign jtag_axi_in_req.aw.cache  = jtag_axi_awcache;
    assign jtag_axi_in_req.aw.prot   = jtag_axi_awprot;
    assign jtag_axi_in_req.aw.qos    = jtag_axi_awqos;
    assign jtag_axi_in_req.aw.region = jtag_axi_awregion;
    assign jtag_axi_in_req.aw.user   = jtag_axi_awuser;
    assign jtag_axi_in_req.aw.atop   = '0;
    assign jtag_axi_in_req.aw_valid  = jtag_axi_awvalid;
    assign jtag_axi_awready          = jtag_axi_in_resp.aw_ready;

    assign jtag_axi_in_req.w.data    = jtag_axi_wdata;
    assign jtag_axi_in_req.w.strb    = jtag_axi_wstrb;
    assign jtag_axi_in_req.w.last    = jtag_axi_wlast;
    assign jtag_axi_in_req.w.user    = jtag_axi_wuser;
    assign jtag_axi_in_req.w_valid   = jtag_axi_wvalid;
    assign jtag_axi_wready           = jtag_axi_in_resp.w_ready;

    assign jtag_axi_bid              = jtag_axi_in_resp.b.id;
    assign jtag_axi_bresp            = jtag_axi_in_resp.b.resp;
    assign jtag_axi_buser            = jtag_axi_in_resp.b.user;
    assign jtag_axi_bvalid           = jtag_axi_in_resp.b_valid;
    assign jtag_axi_in_req.b_ready   = jtag_axi_bready;

    assign jtag_axi_in_req.ar.id     = jtag_axi_arid;
    assign jtag_axi_in_req.ar.addr   = jtag_axi_araddr;
    assign jtag_axi_in_req.ar.len    = jtag_axi_arlen;
    assign jtag_axi_in_req.ar.size   = jtag_axi_arsize;
    assign jtag_axi_in_req.ar.burst  = jtag_axi_arburst;
    assign jtag_axi_in_req.ar.lock   = jtag_axi_arlock;
    assign jtag_axi_in_req.ar.cache  = jtag_axi_arcache;
    assign jtag_axi_in_req.ar.prot   = jtag_axi_arprot;
    assign jtag_axi_in_req.ar.qos    = jtag_axi_arqos;
    assign jtag_axi_in_req.ar.region = jtag_axi_arregion;
    assign jtag_axi_in_req.ar.user   = jtag_axi_aruser;
    assign jtag_axi_in_req.ar_valid  = jtag_axi_arvalid;
    assign jtag_axi_arready          = jtag_axi_in_resp.ar_ready;

    assign jtag_axi_rid              = jtag_axi_in_resp.r.id;
    assign jtag_axi_rdata            = jtag_axi_in_resp.r.data;
    assign jtag_axi_rresp            = jtag_axi_in_resp.r.resp;
    assign jtag_axi_rlast            = jtag_axi_in_resp.r.last;
    assign jtag_axi_ruser            = jtag_axi_in_resp.r.user;
    assign jtag_axi_rvalid           = jtag_axi_in_resp.r_valid;
    assign jtag_axi_in_req.r_ready   = jtag_axi_rready;

    // ------------------------------------------------------------------
    // SYS_OUT AXI4 egress: the shared slave agent answers on u_output_axi_if
    // in both realizations (cocotb binds the instance, SV-UVM takes the vif
    // from uvm_config_db); the bridge places the wrapper's struct port on it.
    // Preload and fault programming go through the agent's slave sequence.
    // The TB-owned R/B hold sits between the struct and the bridge.
    //
    // The responder follows the SMC primary reset: a cool reset drops the
    // outstanding SYS_OUT responses instead of returning them into the reset
    // CPU cluster, whose AXI4 user-yanker asserts on a response with no
    // queued request.
    // ------------------------------------------------------------------
    smc_sys_out_56_64_8_12_axi_req_t  output_mem_req_n;
    smc_sys_out_56_64_8_12_axi_resp_t output_mem_resp;
    smc_sys_out_56_64_8_12_axi_resp_t output_axi_resp_n;

    always_comb begin
        output_mem_req_n         = output_axi_req;
        output_mem_req_n.r_ready = output_axi_req.r_ready & ~tb_output_axi_resp_hold;
        output_mem_req_n.b_ready = output_axi_req.b_ready & ~tb_output_axi_resp_hold;
    end
    always_comb begin
        output_axi_resp_n         = output_mem_resp;
        output_axi_resp_n.r_valid = output_mem_resp.r_valid & ~tb_output_axi_resp_hold;
        output_axi_resp_n.b_valid = output_mem_resp.b_valid & ~tb_output_axi_resp_hold;
    end
    assign output_axi_resp = output_axi_resp_n;

    ocah_axi_if u_output_axi_if (
        .aclk    (clk_smc),
        .aresetn (rst_primary_smc_clk_no)
    );

    ocah_axi_struct_bridge #(
        .axi_req_t  (smc_sys_out_56_64_8_12_axi_req_t),
        .axi_resp_t (smc_sys_out_56_64_8_12_axi_resp_t)
    ) u_output_bridge (
        .axi_req_i  (output_mem_req_n),
        .axi_resp_o (output_mem_resp),
        .axi_if     (u_output_axi_if)
    );

    // Observability: SEP KM-style beat counts on lifted SYS_OUT wires.
    logic [55:0] output_aw_addr_q;
    logic [63:0] output_w_data_q;
    logic [55:0] output_ar_addr_q;

    always_ff @(posedge clk_smc or negedge rst_cold_n_int) begin
        if (!rst_cold_n_int) begin
            output_aw_addr_q          <= '0;
            output_w_data_q           <= '0;
            output_ar_addr_q          <= '0;
            tb_output_axi_write_count <= '0;
            tb_output_axi_read_count  <= '0;
            tb_output_axi_last_addr   <= '0;
            tb_output_axi_last_wdata  <= '0;
        end else begin
            if (output_axi_req.aw_valid && output_axi_resp.aw_ready) begin
                output_aw_addr_q <= output_axi_req.aw.addr;
            end
            if (output_axi_req.w_valid && output_axi_resp.w_ready) begin
                output_w_data_q <= output_axi_req.w.data;
            end
            if (output_axi_req.ar_valid && output_axi_resp.ar_ready) begin
                output_ar_addr_q <= output_axi_req.ar.addr;
            end
            if (output_axi_resp.b_valid && output_axi_req.b_ready) begin
                tb_output_axi_write_count <= tb_output_axi_write_count + 32'd1;
                tb_output_axi_last_addr   <= output_aw_addr_q;
                tb_output_axi_last_wdata  <= output_w_data_q;
            end
            if (output_axi_resp.r_valid && output_axi_req.r_ready &&
                    output_axi_resp.r.last) begin
                tb_output_axi_read_count <= tb_output_axi_read_count + 32'd1;
                tb_output_axi_last_addr  <= output_ar_addr_q;
            end
        end
    end

    // U6-2: lift SYS_OUT AXI for SmcOutputAxiMonitor (SEP-style observe ports).
    assign tb_output_axi_bvalid  = output_axi_resp.b_valid;
    assign tb_output_axi_bready  = output_axi_req.b_ready;
    assign tb_output_axi_bresp   = output_axi_resp.b.resp;
    assign tb_output_axi_rvalid  = output_axi_resp.r_valid;
    assign tb_output_axi_rready  = output_axi_req.r_ready;
    assign tb_output_axi_rresp   = output_axi_resp.r.resp;
    assign tb_output_axi_awaddr  = output_axi_req.aw.addr;
    assign tb_output_axi_awvalid = output_axi_req.aw_valid;
    assign tb_output_axi_awready = output_axi_resp.aw_ready;
    assign tb_output_axi_araddr  = output_axi_req.ar.addr;
    assign tb_output_axi_arvalid = output_axi_req.ar_valid;
    assign tb_output_axi_arready = output_axi_resp.ar_ready;
    assign tb_output_axi_wdata   = output_axi_req.w.data;
    assign tb_output_axi_wvalid  = output_axi_req.w_valid;
    assign tb_output_axi_wready  = output_axi_resp.w_ready;

    // Product lc_state_i = {diff_n, diff_p}. Default idle is packed by
    // smc_base_test as complementary TEST_DEV ({~0, 0}).
    logic [2*smc_pkg::LcStateWidth-1:0] lc_state_drv;
    assign lc_state_drv = tb_lc_state;

    // P2-15 JTAG-side eFuse AXI-Lite master pack/unpack.
    smc_axil_32_32_req_t  ej_axi_req;
    smc_axil_32_32_resp_t ej_axi_resp;
    assign ej_axi_req.aw.addr  = ej_axi_awaddr;
    assign ej_axi_req.aw.prot  = ej_axi_awprot;
    assign ej_axi_req.aw_valid = ej_axi_awvalid;
    assign ej_axi_awready      = ej_axi_resp.aw_ready;
    assign ej_axi_req.w.data   = ej_axi_wdata;
    assign ej_axi_req.w.strb   = ej_axi_wstrb;
    assign ej_axi_req.w_valid  = ej_axi_wvalid;
    assign ej_axi_wready       = ej_axi_resp.w_ready;
    assign ej_axi_bresp        = ej_axi_resp.b.resp;
    assign ej_axi_bvalid       = ej_axi_resp.b_valid;
    assign ej_axi_req.b_ready  = ej_axi_bready;
    assign ej_axi_req.ar.addr  = ej_axi_araddr;
    assign ej_axi_req.ar.prot  = ej_axi_arprot;
    assign ej_axi_req.ar_valid = ej_axi_arvalid;
    assign ej_axi_arready      = ej_axi_resp.ar_ready;
    assign ej_axi_rdata        = ej_axi_resp.r.data;
    assign ej_axi_rresp        = ej_axi_resp.r.resp;
    assign ej_axi_rvalid       = ej_axi_resp.r_valid;
    assign ej_axi_req.r_ready  = ej_axi_rready;

    // ------------------------------------------------------------------
    // CPU ROM/scratch/L1$ macros live inside smc_ip_integration (so both this
    // DUT and smu_wrapper get them from one place). The TB adds no memory of
    // its own; the DV collateral -- counters, FW mailbox, the inject hook and
    // the image backdoors -- binds into that module.
    // ------------------------------------------------------------------
    logic        cpu_scratch0_inject_fire;
    logic [31:0] ecc_inject_fire_count_q;

    // Port expressions here are elaborated in smc_ip_integration's scope, so
    // they name that module's own memory interfaces.
    bind smc_ip_integration smc_cpu_mem_dv u_smc_cpu_mem_dv (
        .clk_i                (clk_sys_o),
        .rst_ni               (rst_primary_smc_clk_ni),
        .rom_req_i            (rom_intf_req),
        .scratch_ram_req_i    (scratch_ram_intf_req),
        .l1_dcache_data_req_i (l1_dcache_data_intf_req),
        .ecc_inject_sbe_i     (smc_uvm_top.tb_cpu_ecc_inject_sbe),
        .ecc_inject_dbe_i     (smc_uvm_top.tb_cpu_ecc_inject_dbe),
        .ecc_poke_en_i        (smc_uvm_top.tb_cpu_ecc_poke_en),
        .ecc_poke_entry_i     (smc_uvm_top.tb_cpu_ecc_poke_entry),
        .ecc_poke_mask_i      (smc_uvm_top.tb_cpu_ecc_poke_mask)
    );

    // Cluster DED from the CPU (smc_4core_cpu.sv flops
    // |{io_errors_uncorrectable_valid, uncorrectable_2} into it). Sticky, so a
    // polling test cannot miss it.
    logic cpu_cluster_ded;
    logic cpu_cluster_ded_seen_q;
    always_ff @(posedge clk_smc or negedge rst_cold_n_int) begin
        if (!rst_cold_n_int) begin
            cpu_cluster_ded_seen_q <= 1'b0;
        end else if (cpu_cluster_ded) begin
            cpu_cluster_ded_seen_q <= 1'b1;
        end
    end
    assign tb_cluster_ded      = cpu_cluster_ded;
    assign tb_cluster_ded_seen = cpu_cluster_ded_seen_q;

    // Bound-instance observability -> the cocotb pins.
    `define CPU_MEM_DV u_dut.u_smc_ip_integration.u_smc_cpu_mem_dv
    assign tb_cpu_rom_read_count      = `CPU_MEM_DV.rom_read_count_q;
    assign tb_cpu_scratch_read_count  = `CPU_MEM_DV.scratch_ram_read_count_q;
    assign tb_cpu_scratch_bank_read_count = `CPU_MEM_DV.scratch_ram_bank_read_count_q;
    assign tb_cpu_scratch_write_count = `CPU_MEM_DV.scratch_ram_write_count_q;
    assign tb_cpu_dcache_write_count  = `CPU_MEM_DV.dcache_data_write_count_q;
    assign tb_cpu_fw_mailbox          = `CPU_MEM_DV.fw_mailbox_q;
    assign tb_cpu_fw_mailbox_valid    = `CPU_MEM_DV.fw_mailbox_valid_q;
    assign cpu_scratch0_inject_fire   = `CPU_MEM_DV.scratch0_inject_fire_q;
    `undef CPU_MEM_DV

    // Probe pin on the cocotb init surface; do not OR into the score.
    logic unused_ecc_probe;
    assign unused_ecc_probe = tb_cpu_ecc_inject_probe;

    always_ff @(posedge clk_smc or negedge rst_cold_n_int) begin
        if (!rst_cold_n_int) begin
            ecc_inject_fire_count_q <= '0;
        end else if (cpu_scratch0_inject_fire) begin
            ecc_inject_fire_count_q <= ecc_inject_fire_count_q + 32'd1;
        end
    end
    assign tb_cpu_ecc_inject_fire_count = ecc_inject_fire_count_q;
    assign tb_cpu_scratch0_inject_fire = cpu_scratch0_inject_fire;

    // Watchdog timeout pins at the smc_wrapper boundary. The second timeout
    // warm-resets the cluster, which clears the WDT and drops both live pins
    // again, so each one is also latched sticky until cold reset.
    logic cpu_wdt_first_timeout;
    logic cpu_wdt_second_timeout;
    logic cpu_wdt_first_timeout_seen_q;
    logic cpu_wdt_second_timeout_seen_q;
    always_ff @(posedge clk_smc or negedge rst_cold_n_int) begin
        if (!rst_cold_n_int) begin
            cpu_wdt_first_timeout_seen_q  <= 1'b0;
            cpu_wdt_second_timeout_seen_q <= 1'b0;
        end else begin
            if (cpu_wdt_first_timeout)  cpu_wdt_first_timeout_seen_q  <= 1'b1;
            if (cpu_wdt_second_timeout) cpu_wdt_second_timeout_seen_q <= 1'b1;
        end
    end
    assign tb_wdt_first_timeout       = cpu_wdt_first_timeout;
    assign tb_wdt_first_timeout_seen  = cpu_wdt_first_timeout_seen_q;
    assign tb_wdt_second_timeout      = cpu_wdt_second_timeout;
    assign tb_wdt_second_timeout_seen = cpu_wdt_second_timeout_seen_q;

    // ------------------------------------------------------------------
    // DTP CSR boundary (smc_wrapper only): NO TB err_slv (policy: no
    // placeholder); resp is idle. smu.sv connects SMC axil_dtp_csr to DTP.
    // ------------------------------------------------------------------
    assign axil_dtp_csr_resp = '0;

    // +smc_hold_ext_boot keeps the boot-sequence gate closed until released.
    assign ext_boot_seq_done = ~tb_hold_ext_boot;

    smc_reset_unit_pkg::reset_ctrl_t ss_reset_ctrl [31:0];

    // ------------------------------------------------------------------
    // DUT: smc_wrapper (smc + smc_ip_integration).
    //
    // Ports absorbed by smc_ip_integration and NOT present on this boundary:
    // smc_external_*, efuse_bank_ctrl_*, efuse_shim_command_*, pad2core_i, core2pad_o,
    // pad2core_en_o, core2pad_en_o (internal smc_wrapper nets → gpio_pad_io).
    // CPU ROM/scratch/L1$ macros and the trace sink RAMs are inside
    // smc_ip_integration.
    // ------------------------------------------------------------------
    smc_wrapper u_dut (
        .powergood_i                (powergood_int),
        .powergood_stable_o,
        .rst_cold_ni                (rst_cold_n_int),
        .rst_cold_stable_ref_clk_no,
        .rst_primary_ref_clk_no,
        .rst_primary_smc_clk_no,
        .rst_wdt_smc_clk_no,
        .rst_primary_periph_clk_no  (rst_primary_periph_clk_n),
        .sys_axi_in_req_i           (sys_axi_in_req),
        .sys_axi_in_resp_o          (sys_axi_in_resp),
        .jtag_axi_in_req_i          (jtag_axi_in_req),
        .jtag_axi_in_resp_o         (jtag_axi_in_resp),
        // P2-15 lifecycle-gated eFuse JTAG access-control path.
        .axil_smc_otp_jtag_req_i    (ej_axi_req),
        .axil_smc_otp_jtag_resp_o   (ej_axi_resp),
        .sep_axi_in_req_i           (sep_axi_in_req),
        .sep_axi_in_resp_o          (sep_axi_in_resp),
        .output_axi_req_o           (output_axi_req),
        .output_axi_resp_i          (output_axi_resp),
        .axil_dtp_csr_req_o         (axil_dtp_csr_req),
        .axil_dtp_csr_resp_i        (axil_dtp_csr_resp),
        .shadow_regs_o              (shadow_regs),
        .lsio_interface_select_o    (tb_lsio_interface_select),
        .gpio_pad_io                (gpio_pad_io),
        .rst_cool_n_from_pin_i      (rst_cool_n_int),
        // SPI octal-flash pads (U2-1). Cocotb drives tb_spi_*; idle default is
        // inactive CS/enable (tests that do not touch SPI leave them at 0).
        .spi_enable_i               (tb_spi_enable),
        .spi_clk_i                  (tb_spi_clk),
        .spi_txd_i                  (tb_spi_txd),
        .spi_cs_n_i                 (tb_spi_cs_n),
        .spi_cs_oe_n_i              (tb_spi_cs_oe_n),
        .spi_cs_ie_n_i              (tb_spi_cs_ie_n),
        .spi_clk_ie_n_i             (tb_spi_clk_ie_n),
        .spi_clk_oe_n_i             (tb_spi_clk_oe_n),
        .spi_dqs_ie_n_i             (tb_spi_dqs_ie_n),
        .spi_dqs_oe_n_i             (tb_spi_dqs_oe_n),
        .spi_dq_ie_n_i              (tb_spi_dq_ie_n),
        .spi_dq_oe_n_i              (tb_spi_dq_oe_n),
        .spi_rxd_o                  (tb_spi_rxd),
        .spi_rxds_o                 (tb_spi_rxds),
        .spi_mem_rebar_oepad_i      (1'b0),
        .spi_mem_rebar_opad_i       (1'b0),
        .spi_mem_rebar_iepad_i      (1'b0),
        .spi_mem_rebar_ipad_o       (tb_spi_mem_rebar_ipad),
        // Telemetry ATB: clock/reset async write domain; receiver 0 driven by
        // tb_telemetry0_* (U4-6); receivers 1/2 remain quiet.
        .clk_telemetry_i            (clk_smc),
        .rst_telemetry_ni           (rst_cold_n_int),
        .telemetry_atdata_i         (tb_telemetry_atdata),
        .telemetry_atid_i           (tb_telemetry_atid),
        .telemetry_atready_o       (tb_telemetry_atready),
        .telemetry_atvalid_i        (tb_telemetry_atvalid),
        .telemetry_afvalid_o        (tb_telemetry_afvalid),
        .telemetry_afready_i        (tb_telemetry_afready),
        .smc_cluster_ded_o          (cpu_cluster_ded),
        .smc_wdt_first_timeout_o    (cpu_wdt_first_timeout),
        .smc_wdt_second_timeout_o   (cpu_wdt_second_timeout),
        .smc_global_base_o          (),
        .smc_region_size_o          (smc_region_size),
        .smc_ext_interrupts_i       ({{(smc_4core_cpu_pkg::NumExtInterrupts-17){1'b0}},
                                       tb_ext_interrupts_hi_i, tb_temp_interrupt_i,
                                       tb_ext_interrupt_0_i}),
        .sep_mailbox_interrupts_i   (tb_sep_mailbox_interrupts),
        .sep_wdt_reset_n_i          (tb_sep_wdt_reset_n),
        .smc_fuse_sense_done_o,
        .smc_fuse_reset_n_delayed_o (tb_fuse_reset_n),
        .skip_mem_repair_o          (tb_skip_mem_repair_o),
        .ext_boot_seq_done_i        (ext_boot_seq_done),
        // Tied low: the eFuse sense bypass (sense FSM never routed to the bank,
        // shadow regs exposed unsensed, warm domain held in reset) is unreachable
        // here; docs/SMC_VPLAN.adoc Known Limitations "Bench tie-offs" carries the row.
        .sep_security_disable_i     (1'b0),
        .lc_state_i                 (lc_state_drv),
        .lc_sigint_err_o            (lc_sigint_err),
        .smc_ndmreset_request_i     (tb_ndmreset_request),
        .smc_ndmreset_process_o     (tb_ndmreset_process),
        .smc_ext_mailbox_interrupts_o (),
        .cfg_flr_pf_active_i        (tb_cfg_flr_pf_active),
        .isolate_req_o              (tb_isolate_req_o),
        .ss_reset_complete_i        (tb_ss_reset_complete),
        .ss_config_o                (ss_config),
        .ss_reset_ctrl_o            (ss_reset_ctrl),
        .sync_irq_o                 (sync_irq),
        .smc_disable_sram_auto_init_i (1'b1),
        .smc_init_mem_done_o,
        .chiplet_is_primary_i       (tb_chiplet_is_primary),
        .timer_count_o              (timer_count),
        .boot_stall_jtag_ovrd_i     (tb_boot_stall_jtag_ovrd_i),
        .boot_stall_jtag_val_i      (tb_boot_stall_jtag_val_i),
        .boot_stall_combined_o      (tb_boot_stall_combined_o),
        .jtag_reset_ctrl_i          (jtag_smc_reset_ctrl_t'(tb_jtag_reset_ctrl)),
        .cla_ext_action_custom_o    (cla_ext_action_custom),
        .xtrigger_ss_o              (),
        .xtrigger_ss_i              ('0),
        .tdr_dbg_ctrl_clock_stop_en_i (1'b0),
        .tdr_dbg_ctrl_clocks_stopped_by_cla_o (),
        .ext_debug_bus_i            ('0),
        // DFT scan controls: cocotb drives tb_test_en_i (default 0 in bring-up).
        // scan reset deasserted -- matches smc.sv port names (test_en_i / scan_rst_ni).
        .test_en_i                  (tb_test_en_i),
        .scan_rst_ni                (1'b1),
        // Without an external BISR/MBIST agent the boot sequencer would wait
        // forever if these stayed low (CPU never fetches ROM) -- same fix as
        // hw/sys/smu/dv/tb/tb_wrapper_top.sv's smu_wrapper instance.
        .mem_repair_done_i          (1'b1),
        .mem_repair_success_i       (1'b1),
        .mem_repair_abort_i         (tb_mem_repair_abort),
        .mbist_done_i               (1'b1),
        .mbist_pass_i               (1'b1),
        .mbist_abort_i              (tb_mbist_abort),
        .smc_cpu_jtag_TCK_i         (tb_cpu_jtag_tck),
        .smc_cpu_jtag_TMS_i         (tb_cpu_jtag_tms),
        .smc_cpu_jtag_TDI_i         (tb_cpu_jtag_tdi),
        .smc_cpu_jtag_TDO_data_o    (tb_cpu_jtag_tdo),
        .smc_cpu_jtag_reset_i       (tb_cpu_jtag_reset),
        .smc_cpu_jtag_mfr_id_i      (11'h2AA),
        .smc_cpu_jtag_part_number_i (16'h0CA0),
        .smc_cpu_jtag_version_i     (4'h1),
        .gpio_interrupt_o           (gpio_interrupt),
        .uart_interrupt_o           (uart_interrupt),
        .efuse_debug_bus_o          ()
    );

    assign clk_smc    = u_dut.clk_sys;
    assign clk_ref    = u_dut.clk_ref;
    assign clk_periph = u_dut.clk_periph;

`ifndef UVM
    // cocotb toggles the model oscillators through the clock inputs, with
    // +pll_osc_bench selecting these nets over pll_wrap's own generators:
    // under Verilator, cocotb observes the pre-edge state only on a clock its
    // own write toggles.
    assign u_dut.u_smc_ip_integration.u_pll_wrap.osc_ref_bench    = clk_ref_i;
    assign u_dut.u_smc_ip_integration.u_pll_wrap.osc_sys_bench    = clk_smc_i;
    assign u_dut.u_smc_ip_integration.u_pll_wrap.osc_periph_bench = clk_periph_i;
`endif

    // Sense-done pin and the sensed eFuse shadow (XMR into the controller
    // shadow regs under u_dut.u_smc.u_smc_peripherals).
    assign tb_fuse_sense_done = smc_fuse_sense_done_o;
    // Warm domain leave-reset (post sync). Hierarchical observe for CSR waits.
    assign tb_rst_warm_smc_clk_n = u_dut.u_smc.rst_warm_smc_clk_n;
    assign efuse_shadow_probe_o =
        u_dut.u_smc.u_smc_peripherals.u_smc_efuse_wrapper.u_efuse_interface_controller
            .u_efuse_shadow_regs.shadow_efuse_o;
    // eFuse bank storage is smc_ip_integration's efuse_bank_model
    // (hw/ip/efuse/dv/models/efuse_bank_model.sv). Its "programmed" and "OTP"
    // storage collapse into the same register file, so programmed_word0
    // mirrors otp_word0.
    assign tb_efuse_otp_word0 =
        u_dut.u_smc_ip_integration.u_efuse_bank_model.u_efuse_bank_reg
            .field_storage.EFUSE_BANK_REG[0].dout.value;
    assign tb_efuse_programmed_word0 = tb_efuse_otp_word0;

    assign tb_i2c_debug_lo    = u_dut.u_smc.i2c_debug[0];
    assign tb_i2c_cg_en       = u_dut.u_smc.cg_ctrl_i2c_cg_en;
    // Shared DMA gated clock = prim_clk_gater_hysteresis in idma_wrapper
    // (request_manager + backend domain). Passive-only assign; no force/deposit.
    assign tb_dma_cg_en = u_dut.u_smc.u_smc_base.cg_ctrl_dma_cg_en;
    assign tb_dma_gated_clk =
        u_dut.u_smc.u_smc_base.u_smc_data_accelerator_wrap.u_dma_wrap
            .u_request_maneger_cg.gated_clk_o;
    assign tb_dma_busy = u_dut.u_smc.u_smc_base.dma_busy;
    assign tb_dma_frontend_busy =
        u_dut.u_smc.u_smc_base.u_smc_data_accelerator_wrap.u_dma_wrap
            .dma_frontend_busy;
    assign tb_dma_backend_busy =
        u_dut.u_smc.u_smc_base.u_smc_data_accelerator_wrap.u_dma_wrap
            .dma_backend_busy;
    assign tb_dma_gater_busy =
        u_dut.u_smc.u_smc_base.u_smc_data_accelerator_wrap.u_dma_wrap
            .dma_busy;
    // Zeroer gated clocks / busy / enable — read-only assign; no force/deposit.
    assign tb_zeroer_cg_en = u_dut.u_smc.u_smc_base.cg_ctrl_zeroer_cg_en;
    assign tb_zeroer_gated_axi_clk =
        u_dut.u_smc.u_smc_base.u_smc_data_accelerator_wrap.u_zeroer.axi_clk;
    assign tb_zeroer_gated_reg_clk =
        u_dut.u_smc.u_smc_base.u_smc_data_accelerator_wrap.u_zeroer.reg_clk;
    assign tb_zeroer_busy = u_dut.u_smc.u_smc_base.zeroer_busy;
    assign tb_zeroer_bus_active = u_dut.u_smc.u_smc_base.zeroer_bus_active;

    // State-corruption hooks force the state flops from the TB because no legal
    // transaction can create an unused FSM encoding or make the bank model
    // return an error. Requests and output checks stay on the real DUT paths;
    // forcing is limited to the state flops and read-error inputs, and every
    // force is released by its enable.
`define SMC_ZEROER u_dut.u_smc.u_smc_base.u_smc_data_accelerator_wrap.u_zeroer
    assign tb_zeroer_state = `SMC_ZEROER.cur_state;
    assign tb_zeroer_intp = `SMC_ZEROER.zeroer_intp_o;
    assign tb_zeroer_awvalid = `SMC_ZEROER.mst_awvalid;
    assign tb_zeroer_wvalid = `SMC_ZEROER.mst_wvalid;
    always @(posedge clk_smc) begin
        if (tb_zeroer_state_inject_en === 1'b1) begin
            force `SMC_ZEROER.cur_state[2:0] = tb_zeroer_state_inject;
        end else begin
            release `SMC_ZEROER.cur_state[2:0];
        end
    end
`undef SMC_ZEROER

`define SMC_EFUSE_IFC \
    u_dut.u_smc.u_smc_peripherals.u_smc_efuse_wrapper.u_efuse_interface_controller
`define SMC_EFUSE_PROGRAM `SMC_EFUSE_IFC.u_efuse_program_interface
`define SMC_EFUSE_READ    `SMC_EFUSE_IFC.u_efuse_read_interface
    assign tb_efuse_program_state = `SMC_EFUSE_PROGRAM.program_state_q;
    assign tb_efuse_program_req_valid = `SMC_EFUSE_PROGRAM.fuse_command_req_o.valid;
    assign tb_efuse_program_busy = `SMC_EFUSE_PROGRAM.program_busy_o;
    assign tb_efuse_program_done = `SMC_EFUSE_PROGRAM.program_done_o;
    assign tb_efuse_program_error = `SMC_EFUSE_PROGRAM.program_error_o;
    assign tb_efuse_program_readback = `SMC_EFUSE_PROGRAM.program_read_back_data_o;
    assign tb_efuse_read_state = `SMC_EFUSE_READ.read_state_q;
    assign tb_efuse_read_req_valid = `SMC_EFUSE_READ.fuse_command_req_o.valid;
    assign tb_efuse_read_busy = `SMC_EFUSE_READ.read_busy_o;
    assign tb_efuse_read_done = `SMC_EFUSE_READ.read_done_o;
    assign tb_efuse_read_error = `SMC_EFUSE_READ.read_error_o;
    assign tb_efuse_readback = `SMC_EFUSE_READ.read_back_data_o;
    assign tb_efuse_read_addr = 16'(`SMC_EFUSE_IFC.reg_interface_read_addr_csr);
    assign tb_efuse_program_addr = 16'(`SMC_EFUSE_IFC.reg_interface_program_addr_csr);
    always @(posedge clk_smc) begin
        if (tb_efuse_program_state_inject_en === 1'b1) begin
            force `SMC_EFUSE_PROGRAM.program_state_q[1:0] = tb_efuse_program_state_inject;
        end else begin
            release `SMC_EFUSE_PROGRAM.program_state_q[1:0];
        end
        if (tb_efuse_read_state_inject_en === 1'b1) begin
            force `SMC_EFUSE_READ.read_state_q[1:0] = tb_efuse_read_state_inject;
        end else begin
            release `SMC_EFUSE_READ.read_state_q[1:0];
        end
        if (tb_efuse_read_error_inject === 2'b01) begin
            force `SMC_EFUSE_IFC.fuse_command_resp_interface_ctrl_r.status = 1'b1;
        end else begin
            release `SMC_EFUSE_IFC.fuse_command_resp_interface_ctrl_r.status;
        end
        if (tb_efuse_read_error_inject === 2'b10) begin
            force `SMC_EFUSE_READ.efuse_req_err_i = 1'b1;
        end else begin
            release `SMC_EFUSE_READ.efuse_req_err_i;
        end
        if (tb_efuse_read_error_inject === 2'b11) begin
            force `SMC_EFUSE_READ.secure_tm_blocked_i = 1'b1;
        end else begin
            release `SMC_EFUSE_READ.secure_tm_blocked_i;
        end
    end
`undef SMC_EFUSE_READ
`undef SMC_EFUSE_PROGRAM
`undef SMC_EFUSE_IFC

    assign tb_sync_irq        = sync_irq;
    assign tb_gpio_irq_any    = |gpio_interrupt;
    assign tb_axi_hang_irq      = u_dut.u_smc.u_smc_base.axi_hang_irq_o;
    assign tb_axi_hang_irq_sys  = u_dut.u_smc.u_smc_base.hang_irq_sys_axi;
    assign tb_axi_hang_irq_sep  = u_dut.u_smc.u_smc_base.hang_irq_sep_axi;
    assign tb_axi_hang_irq_data = u_dut.u_smc.u_smc_base.hang_irq_data_accel;
    assign tb_axi_hang_irq_periph30 = u_dut.u_smc.peripheral_interrupts[30];
    assign tb_axi_hang_irq_plic_src =
        u_dut.u_smc.cpu_interrupts[smc_4core_cpu_pkg::NumExtInterrupts + 30];
    assign tb_gpio_pad57      = u_dut.u_smc.pad2core_i[BootStallPad];
    assign tb_uart_irq_any    = |uart_interrupt;
    assign tb_uart_irq_combined = u_dut.u_smc.peripheral_interrupts[21:18];
    assign tb_i2c_irq = u_dut.u_smc.peripheral_interrupts[25:23];
    assign tb_mailbox_irq_any = |u_dut.u_smc.peripheral_interrupts[7:0];
    assign tb_avsbus_irq      = u_dut.u_smc.peripheral_interrupts[22];
    assign tb_telemetry_irq_any = |u_dut.u_smc.peripheral_interrupts[10:8];
    assign tb_efuse_locked_access_irq = u_dut.u_smc.peripheral_interrupts[27];
    assign tb_temp_interrupt_irq = u_dut.u_smc.u_smc_base.ext_interrupts_smc_clk[1];
    assign tb_ext_interrupt_0_sync = u_dut.u_smc.u_smc_base.ext_interrupts_smc_clk[0];
    assign tb_ss0_warm_reset_n = ss_reset_ctrl[0].warm_reset_n;
    assign tb_ndmreset_irq = u_dut.u_smc.peripheral_interrupts[11];
    assign tb_rst_cool_from_flr =
        u_dut.u_smc.u_smc_peripherals.u_smc_reset_unit.rst_cool_no;
    assign tb_avsbus_cur_state_debug = u_dut.u_smc.avsbus_cur_state_debug;

    assign tb_gpio_core2pad_any    = |u_dut.u_smc.core2pad_o;
    assign tb_gpio_core2pad_en_any = |u_dut.u_smc.core2pad_en_o;
    assign tb_gpio_pad2core_en_any = |u_dut.u_smc.pad2core_en_o;
    assign tb_core2pad_o           = u_dut.u_smc.core2pad_o;
    assign tb_core2pad_en_o        = u_dut.u_smc.core2pad_en_o;
    assign tb_pad2core_en_o        = u_dut.u_smc.pad2core_en_o;

    // Per-interface idle observability -- drives the per-module sanity
    // tests. Sample all four external-macro masters from real smc ports so
    // the active pulse is visible even when a wrapper/TB wire does not track
    // the same cycle as the cocotb latch.
    assign tb_axil_dtp_csr_active    = u_dut.u_smc.axil_dtp_csr_req_o.aw_valid
                                     | u_dut.u_smc.axil_dtp_csr_req_o.w_valid
                                     | u_dut.u_smc.axil_dtp_csr_req_o.ar_valid;
    assign tb_axil_external_active   = u_dut.u_smc.smc_external_req_o.aw_valid
                                     | u_dut.u_smc.smc_external_req_o.w_valid
                                     | u_dut.u_smc.smc_external_req_o.ar_valid;
    assign tb_axil_external_arvalid  = u_dut.u_smc.smc_external_req_o.ar_valid;
    assign tb_axil_external_araddr   = u_dut.u_smc.smc_external_req_o.ar.addr;
    assign tb_axil_external_awvalid  = u_dut.u_smc.smc_external_req_o.aw_valid;
    assign tb_axil_external_awaddr   = u_dut.u_smc.smc_external_req_o.aw.addr;
    assign tb_axil_efuse_bank_active = u_dut.u_smc.efuse_bank_ctrl_req_o.aw_valid | u_dut.u_smc.efuse_bank_ctrl_req_o.w_valid |
                                       u_dut.u_smc.efuse_bank_ctrl_req_o.ar_valid;
    assign tb_axil_any_master_active = tb_axil_dtp_csr_active | tb_axil_external_active | tb_axil_efuse_bank_active;

    // Hierarchical CPU debug (pre-isolate-clamp PC + boundary isolate).
    assign tb_cpu_wb_pc0 =
        u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu.wb_reg_pc_raw[0];
    assign tb_cpu_wb_pc1 =
        u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu.wb_reg_pc_raw[1];
    assign tb_cpu_wb_pc2 =
        u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu.wb_reg_pc_raw[2];
    assign tb_cpu_wb_pc3 =
        u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu.wb_reg_pc_raw[3];
    // Core 0's tile domain carries no suffix; 1-3 are _1.._3
    // (OCAH4CORECluster_DigitalTop.sv:3975-4218).
    assign tb_cpu_mcause0 = u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu
        .u_digital_top.tile_prci_domain.element_reset_domain_rockettile.core.csr.reg_mcause;
    assign tb_cpu_mcause1 = u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu
        .u_digital_top.tile_prci_domain_1.element_reset_domain_rockettile.core.csr.reg_mcause;
    assign tb_cpu_mcause2 = u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu
        .u_digital_top.tile_prci_domain_2.element_reset_domain_rockettile.core.csr.reg_mcause;
    assign tb_cpu_mcause3 = u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu
        .u_digital_top.tile_prci_domain_3.element_reset_domain_rockettile.core.csr.reg_mcause;
    assign tb_cpu_mepc0 = u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu
        .u_digital_top.tile_prci_domain.element_reset_domain_rockettile.core.csr.reg_mepc;
    assign tb_cpu_mepc1 = u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu
        .u_digital_top.tile_prci_domain_1.element_reset_domain_rockettile.core.csr.reg_mepc;
    assign tb_cpu_mepc2 = u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu
        .u_digital_top.tile_prci_domain_2.element_reset_domain_rockettile.core.csr.reg_mepc;
    assign tb_cpu_mepc3 = u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu
        .u_digital_top.tile_prci_domain_3.element_reset_domain_rockettile.core.csr.reg_mepc;
    assign tb_cpu_cluster_isolate =
        u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu.cluster_boundary_isolate;
`define SMC_CPU_WRAP u_dut.u_smc.u_smc_cpu_wrapper
`define SMC_CPU      `SMC_CPU_WRAP.u_smc_cpu
`define SMC_CPU_CTRL `SMC_CPU_WRAP.u_smc_cpu_ctrl_wrap
`define SMC_L2_ISO   `SMC_CPU.u_l2_frontend_axi_isolate
`define SMC_MMIO_ISO `SMC_CPU.u_mmio_axi_isolate
    assign tb_cpu_isolate_req      = `SMC_CPU_WRAP.isolate_req;
    assign tb_cpu_drained          = `SMC_CPU_WRAP.drained;
    assign tb_cpu_reset_timeout    = `SMC_CPU_CTRL.reset_timeout;
    assign tb_cpu_reset_applied    = `SMC_CPU_CTRL.reset_applied;
    assign tb_cpu_uncore_reset_n   = `SMC_CPU_WRAP.cluster_uncore_reset_n;
    assign tb_cpu_core_resets_n    = `SMC_CPU_WRAP.core_reset_n;
    assign tb_cpu_l2_isolated      = `SMC_CPU.l2_frontend_isolated;
    assign tb_cpu_l2_pending_aw    = `SMC_L2_ISO.i_axi_isolate.pending_aw_q;
    assign tb_cpu_l2_pending_w     = `SMC_L2_ISO.i_axi_isolate.pending_w_q;
    assign tb_cpu_l2_pending_ar    = `SMC_L2_ISO.i_axi_isolate.pending_ar_q;
    assign tb_cpu_l2_flush_active  = `SMC_L2_ISO.flush_active_q;
    assign tb_cpu_mmio_isolated    = `SMC_CPU.mmio_isolated;
    assign tb_cpu_mmio_pending_aw  = `SMC_MMIO_ISO.i_axi_isolate.pending_aw_q;
    assign tb_cpu_mmio_pending_w   = `SMC_MMIO_ISO.i_axi_isolate.pending_w_q;
    assign tb_cpu_mmio_pending_ar  = `SMC_MMIO_ISO.i_axi_isolate.pending_ar_q;
    assign tb_cpu_mmio_flush_active = `SMC_MMIO_ISO.flush_active_q;
`undef SMC_MMIO_ISO
`undef SMC_L2_ISO
`undef SMC_CPU_CTRL
`undef SMC_CPU
`undef SMC_CPU_WRAP
    assign tb_cpu_debug_dmactive =
        u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu.debug_dmactive;
    assign tb_cpu_debug_dmactive_ack =
        u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu.debug_dmactiveAck;

    // Hart 0 retirement record (Rocket CSR trace bundle), masked while the
    // core is in reset.
    `define SMC_HART0_CSR u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu.u_digital_top.tile_prci_domain.element_reset_domain_rockettile.core.csr
    assign tb_cpu_core_reset_n = u_dut.u_smc.u_smc_cpu_wrapper.core_reset_n[0];
    assign tb_cpu_trace_valid  = tb_cpu_core_reset_n ? `SMC_HART0_CSR.io_trace_0_valid : 1'b0;
    assign tb_cpu_trace_valid_unmasked = `SMC_HART0_CSR.io_trace_0_valid;
    assign tb_cpu_trace_pc_unmasked    = `SMC_HART0_CSR.io_trace_0_iaddr;
    assign tb_cpu_trace_pc     = tb_cpu_core_reset_n ? `SMC_HART0_CSR.io_trace_0_iaddr : '0;
    assign tb_cpu_trace_insn   = tb_cpu_core_reset_n ? `SMC_HART0_CSR.io_trace_0_insn : '0;
    assign tb_cpu_trace_exc    = tb_cpu_core_reset_n ? `SMC_HART0_CSR.io_trace_0_exception : 1'b0;
    assign tb_cpu_trace_cause  = tb_cpu_core_reset_n ? `SMC_HART0_CSR.io_cause : '0;
    assign tb_cpu_trace_tval   = tb_cpu_core_reset_n ? `SMC_HART0_CSR.io_tval : '0;
    `undef SMC_HART0_CSR
    assign tb_cpu_scratch2 =
        u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu_ctrl_wrap.scratch_reg[2];

    // ------------------------------------------------------------------
    // P1 interrupt-vector observability. The per-source scalars above are
    // single slices picked by hand; the interrupt chapters are written in
    // terms of bit indices, so the whole vectors are published here.
    // ------------------------------------------------------------------
    assign tb_cpu_interrupts        = u_dut.u_smc.cpu_interrupts;
    assign tb_peripheral_interrupts = u_dut.u_smc.peripheral_interrupts;
    assign tb_mailbox_interrupts    = u_dut.u_smc.u_smc_base.mailbox_interrupts;
    assign tb_ext_mailbox_interrupts = u_dut.u_smc.smc_ext_mailbox_interrupts_o;
    assign tb_gpio_interrupt        = u_dut.u_smc.u_smc_peripherals.gpio_interrupt;
    assign tb_ndmreset_request_sync =
        u_dut.u_smc.u_smc_peripherals.ndmreset_request_smc_clk;
    assign tb_uart_irq_raw      = u_dut.u_smc.u_smc_peripherals.uart_irq_periph_clk;
    assign tb_uart_err_raw      = u_dut.u_smc.u_smc_peripherals.uart_err_periph_clk;
    assign tb_logengine_irq_raw = u_dut.u_smc.u_smc_peripherals.log_engine_irq_periph_clk;
    assign tb_telemetry_irq     = u_dut.u_smc.u_smc_peripherals.telemetry_irq;
    assign tb_sep_wdt_irq_sync  = u_dut.u_smc.u_smc_peripherals.rst_ext_wdt_smc_clk;
    assign tb_cla_interrupt     = u_dut.u_smc.u_smc_base.cla_interrupt;
    assign tb_cla_clock_stop = u_dut.u_smc.u_smc_base.u_internal_regs.u_smc_dfd_wrap
        .tdr_dbg_ctrl_clocks_stopped_by_cla_o;
    assign tb_cla_halt_clock_global =
        u_dut.u_smc.u_smc_base.u_internal_regs.u_smc_dfd_wrap.halt_clock_global_or_o;
    assign tb_dma_intp = u_dut.u_smc.u_smc_base.dma_intp;

    // PLIC and CLINT live inside the generated cluster; the names below are
    // the generated ones (MTIMECMP is `pad`, contexts are numbered 0..7).
    `define SMC_PLIC u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu.u_digital_top.plic_domain.plic
    `define SMC_CLINT u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu.u_digital_top.clint_domain.clint
    assign tb_plic_meip = {`SMC_PLIC.auto_int_out_6_0, `SMC_PLIC.auto_int_out_4_0,
                           `SMC_PLIC.auto_int_out_2_0, `SMC_PLIC.auto_int_out_0_0};
    assign tb_plic_seip = {`SMC_PLIC.auto_int_out_7_0, `SMC_PLIC.auto_int_out_5_0,
                           `SMC_PLIC.auto_int_out_3_0, `SMC_PLIC.auto_int_out_1_0};
    assign tb_plic_threshold0   = `SMC_PLIC.threshold_0;
    assign tb_plic_maxdev0      = `SMC_PLIC.maxDevs_0;
    assign tb_plic_enables0_w0  = `SMC_PLIC.enables_0_0;
    assign tb_plic_claim0       = `SMC_PLIC.claimer_0;
    assign tb_plic_complete0    = `SMC_PLIC.completer_0;
    assign tb_plic_completer_dev = `SMC_PLIC.completerDev;
    // The PLIC's pending_N and priority_N registers hold source N + 1, since
    // source 0 is reserved.
    assign tb_plic_pending_low  = {`SMC_PLIC.pending_2, `SMC_PLIC.pending_1,
                                   `SMC_PLIC.pending_0};
    assign tb_plic_priority_low = {`SMC_PLIC.priority_2[0], `SMC_PLIC.priority_1[0],
                                   `SMC_PLIC.priority_0[0]};
    assign tb_plic_pending_331  = `SMC_PLIC.pending_330;
    assign tb_plic_pending_324  = `SMC_PLIC.pending_323;

    assign tb_clint_mtime      = `SMC_CLINT.time_0;
    assign tb_clint_mtimecmp0  = `SMC_CLINT.pad;
    assign tb_clint_mtimecmp1  = `SMC_CLINT.pad_1;
    assign tb_clint_msip = {`SMC_CLINT.ipi_3, `SMC_CLINT.ipi_2, `SMC_CLINT.ipi_1,
                            `SMC_CLINT.ipi_0};
    assign tb_clint_mtip = {`SMC_CLINT.auto_int_out_3_1, `SMC_CLINT.auto_int_out_2_1,
                            `SMC_CLINT.auto_int_out_1_1, `SMC_CLINT.auto_int_out_0_1};
    `undef SMC_PLIC
    `undef SMC_CLINT

    // Per-core direct interrupt pins. The generate loop is unrolled in the
    // generated cluster, so the four tiles are four named instances.
    `define SMC_CORE0 u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu.u_digital_top.tile_prci_domain.element_reset_domain_rockettile.core
    `define SMC_CORE1 u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu.u_digital_top.tile_prci_domain_1.element_reset_domain_rockettile.core
    `define SMC_CORE2 u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu.u_digital_top.tile_prci_domain_2.element_reset_domain_rockettile.core
    `define SMC_CORE3 u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu.u_digital_top.tile_prci_domain_3.element_reset_domain_rockettile.core
    assign tb_core_mtip = {`SMC_CORE3.io_interrupts_mtip, `SMC_CORE2.io_interrupts_mtip,
                           `SMC_CORE1.io_interrupts_mtip, `SMC_CORE0.io_interrupts_mtip};
    assign tb_core_msip = {`SMC_CORE3.io_interrupts_msip, `SMC_CORE2.io_interrupts_msip,
                           `SMC_CORE1.io_interrupts_msip, `SMC_CORE0.io_interrupts_msip};
    assign tb_core_meip = {`SMC_CORE3.io_interrupts_meip, `SMC_CORE2.io_interrupts_meip,
                           `SMC_CORE1.io_interrupts_meip, `SMC_CORE0.io_interrupts_meip};
    assign tb_core_buserror = {`SMC_CORE3.io_interrupts_buserror,
                               `SMC_CORE2.io_interrupts_buserror,
                               `SMC_CORE1.io_interrupts_buserror,
                               `SMC_CORE0.io_interrupts_buserror};
    `undef SMC_CORE0
    `undef SMC_CORE1
    `undef SMC_CORE2
    `undef SMC_CORE3

    // ------------------------------------------------------------------
    // P1 DMA: stream-0 command registers, the frontend handshake and the
    // AXI master port the transfer moves on.
    // ------------------------------------------------------------------
    `define SMC_DMA u_dut.u_smc.u_smc_base.u_smc_data_accelerator_wrap.u_dma_wrap
    `define SMC_DMA_FE `SMC_DMA.u_idma_frontend_wrapper
    `define SMC_DMA_REG `SMC_DMA_FE.gen_axi_to_iDMA_fe[0].u_iDMA_frontend.gen_core_regs[0].i_idma_reg64_2d_reg_top
    assign tb_dma_next_id_re = `SMC_DMA_REG.next_id_0_re;
    assign tb_dma_next_id    = `SMC_DMA_REG.next_id_0_qs;
    assign tb_dma_status0    = `SMC_DMA_REG.status_0_qs;
    assign tb_dma_done_id    = `SMC_DMA_REG.done_id_0_qs;
    assign tb_dma_done_id_re = `SMC_DMA_REG.done_id_0_re;
    assign tb_dma_src_addr   = {`SMC_DMA_REG.src_addr_high_qs, `SMC_DMA_REG.src_addr_low_qs};
    assign tb_dma_dst_addr   = {`SMC_DMA_REG.dst_addr_high_qs, `SMC_DMA_REG.dst_addr_low_qs};
    assign tb_dma_length     = {`SMC_DMA_REG.length_high_qs, `SMC_DMA_REG.length_low_qs};
    assign tb_dma_reps       = {`SMC_DMA_REG.reps_2_high_qs, `SMC_DMA_REG.reps_2_low_qs};
    assign tb_dma_fe_req_valid   = `SMC_DMA_FE.fe_req_valid[0];
    assign tb_dma_fe_req_ready   = `SMC_DMA_FE.fe_req_ready[0];
    assign tb_dma_trans_complete = `SMC_DMA_FE.trans_complete[0];
    assign tb_dma_frontend_wakeup   = `SMC_DMA.dma_frontend_wakeup;
    assign tb_dma_frontend_gated_clk = `SMC_DMA.frontend_clock;
    assign tb_dma_mst_awvalid = `SMC_DMA.dma_mst_axi_req_o[0].aw_valid;
    assign tb_dma_mst_awready = `SMC_DMA.dma_mst_axi_resp_i[0].aw_ready;
    assign tb_dma_mst_awaddr  = `SMC_DMA.dma_mst_axi_req_o[0].aw.addr;
    assign tb_dma_mst_awlen   = `SMC_DMA.dma_mst_axi_req_o[0].aw.len;
    assign tb_dma_mst_wvalid  = `SMC_DMA.dma_mst_axi_req_o[0].w_valid;
    assign tb_dma_mst_wready  = `SMC_DMA.dma_mst_axi_resp_i[0].w_ready;
    assign tb_dma_mst_wlast   = `SMC_DMA.dma_mst_axi_req_o[0].w.last;
    assign tb_dma_mst_wstrb   = `SMC_DMA.dma_mst_axi_req_o[0].w.strb;
    assign tb_dma_mst_wdata   = `SMC_DMA.dma_mst_axi_req_o[0].w.data;
    assign tb_dma_mst_bvalid  = `SMC_DMA.dma_mst_axi_resp_i[0].b_valid;
    `undef SMC_DMA_REG
    `undef SMC_DMA_FE
    `undef SMC_DMA

    // Zeroer master port, outstanding counter and command registers.
    `define SMC_ZEROER u_dut.u_smc.u_smc_base.u_smc_data_accelerator_wrap.u_zeroer
    assign tb_zeroer_awready = `SMC_ZEROER.mst_axi_resp_i.aw_ready;
    assign tb_zeroer_awaddr  = `SMC_ZEROER.mst_axi_req_o.aw.addr;
    assign tb_zeroer_awlen   = `SMC_ZEROER.mst_axi_req_o.aw.len;
    assign tb_zeroer_wready  = `SMC_ZEROER.mst_axi_resp_i.w_ready;
    assign tb_zeroer_wlast   = `SMC_ZEROER.mst_axi_req_o.w.last;
    assign tb_zeroer_wstrb   = `SMC_ZEROER.mst_axi_req_o.w.strb;
    assign tb_zeroer_wdata   = `SMC_ZEROER.mst_axi_req_o.w.data;
    assign tb_zeroer_bvalid  = `SMC_ZEROER.mst_axi_resp_i.b_valid;
    assign tb_zeroer_outstanding = `SMC_ZEROER.outstanding_reqs;
    assign tb_zeroer_dest_addr   = `SMC_ZEROER.dest_addr;
    assign tb_zeroer_size        = `SMC_ZEROER.size;
    assign tb_zeroer_trigger     = `SMC_ZEROER.status_swacc[1];
    assign tb_zeroer_status_read = `SMC_ZEROER.status_swacc[0];
    assign tb_zeroer_strb_dest   = `SMC_ZEROER.u_zeroer_reg.decoded_reg_strb.DEST_ADDR;
    assign tb_zeroer_strb_size   = `SMC_ZEROER.u_zeroer_reg.decoded_reg_strb.SIZE;
    assign tb_zeroer_req_is_wr   = `SMC_ZEROER.u_zeroer_reg.decoded_req_is_wr;
    assign tb_zeroer_disable_cg  = `SMC_ZEROER.disable_cg;
    assign tb_zeroer_axi_clk_enable = `SMC_ZEROER.axi_clk_enable;
    `undef SMC_ZEROER

    // GPIO wrap 0 AXI-Lite protection filter.
    `define SMC_GPIO0 u_dut.u_smc.u_smc_peripherals.u_smc_padring.gen_gpio_intf[0].u_gpio_interface
    assign tb_gpio0_awvalid    = `SMC_GPIO0.axil_req_i.aw_valid;
    assign tb_gpio0_arvalid    = `SMC_GPIO0.axil_req_i.ar_valid;
    assign tb_gpio0_awprot     = `SMC_GPIO0.axil_req_i.aw.prot;
    assign tb_gpio0_arprot     = `SMC_GPIO0.axil_req_i.ar.prot;
    assign tb_gpio0_awprot_req = `SMC_GPIO0.filter__awprot_requirement;
    assign tb_gpio0_arprot_req = `SMC_GPIO0.filter__arprot_requirement;
    assign tb_gpio0_wr_filter_en = `SMC_GPIO0.filter__write_filter_enable;
    assign tb_gpio0_rd_filter_en = `SMC_GPIO0.filter__read_filter_enable;
    `undef SMC_GPIO0

    // Inbound fabric filter decisions, and the JTAG leg of the alias remap.
    `define SMC_INB u_dut.u_smc.u_smc_base.u_smc_fabric.u_smc_input_fabric
    assign tb_inb_write_hit     = `SMC_INB.u_smc_sys_inbound_filter.write_filter_hit;
    assign tb_inb_read_hit      = `SMC_INB.u_smc_sys_inbound_filter.read_filter_hit;
    assign tb_inb_isolate_write = `SMC_INB.u_smc_sys_inbound_filter.isolate_write;
    assign tb_inb_isolate_read  = `SMC_INB.u_smc_sys_inbound_filter.isolate_read;
    assign tb_remap_jtag_aw_hit =
        `SMC_INB.u_smc_alias_remap_wrap.remap_debug_jtag_o.aw_remap_hit_debug;
    assign tb_remap_jtag_ar_hit =
        `SMC_INB.u_smc_alias_remap_wrap.remap_debug_jtag_o.ar_remap_hit_debug;
    `undef SMC_INB

    // Isolation / FLR sequencing state. The two watchdog timeout pins are
    // already exported from the wrapper boundary above.
    `define SMC_COOL u_dut.u_smc.u_smc_peripherals.u_smc_reset_unit.u_smc_cool_reset_wrap
    assign tb_isolate_req_reg       = `SMC_COOL.isolate_req_reg;
    assign tb_isolate_req_smcen_reg = `SMC_COOL.isolate_req_smcen_reg;
    assign tb_isolate_req_smc_reg   = `SMC_COOL.isolate_req_smc_reg;
    assign tb_flr_sync_ref          = `SMC_COOL.cfg_flr_pf_active_sync_ref;
    assign tb_flr_posedge_ref       = `SMC_COOL.cfg_flr_pf_active_sync_ref_posedge;
    assign tb_flr_counter_state     = `SMC_COOL.flr_counter_state;
    `undef SMC_COOL

    // Peripherals: ATB per receiver, I2C mode enables, mailbox 0 FIFO levels,
    // UART TX lines, and the I2C leg of the peripheral-domain AXI-Lite CDC.
    `define SMC_PERIPH u_dut.u_smc.u_smc_peripherals
    assign tb_telem_atvalid = `SMC_PERIPH.telemetry_atvalid_i;
    assign tb_telem_atready = `SMC_PERIPH.telemetry_atready_o;
    assign tb_telem_atid0   = `SMC_PERIPH.telemetry_atid_i[0];
    assign tb_telem_atid1   = `SMC_PERIPH.telemetry_atid_i[1];
    assign tb_telem_atid2   = `SMC_PERIPH.telemetry_atid_i[2];
    assign tb_i2c_host_enable[0] = `SMC_PERIPH.u_i2c_wrap.gen_i2cs[0].u_i2c.u_i2c_core.host_enable;
    assign tb_i2c_host_enable[1] = `SMC_PERIPH.u_i2c_wrap.gen_i2cs[1].u_i2c.u_i2c_core.host_enable;
    assign tb_i2c_host_enable[2] = `SMC_PERIPH.u_i2c_wrap.gen_i2cs[2].u_i2c.u_i2c_core.host_enable;
    assign tb_i2c_target_enable[0] = `SMC_PERIPH.u_i2c_wrap.gen_i2cs[0].u_i2c.u_i2c_core.target_enable;
    assign tb_i2c_target_enable[1] = `SMC_PERIPH.u_i2c_wrap.gen_i2cs[1].u_i2c.u_i2c_core.target_enable;
    assign tb_i2c_target_enable[2] = `SMC_PERIPH.u_i2c_wrap.gen_i2cs[2].u_i2c.u_i2c_core.target_enable;
    assign tb_uart_tx = `SMC_PERIPH.uart_tx;
    assign tb_periph_cdc_awvalid = `SMC_PERIPH.axil_i2c_req_periph_clk.aw_valid;
    assign tb_periph_cdc_awready = `SMC_PERIPH.axil_i2c_resp_periph_clk.aw_ready;
    assign tb_periph_cdc_wvalid  = `SMC_PERIPH.axil_i2c_req_periph_clk.w_valid;
    assign tb_periph_cdc_bvalid  = `SMC_PERIPH.axil_i2c_resp_periph_clk.b_valid;
    assign tb_periph_cdc_arvalid = `SMC_PERIPH.axil_i2c_req_periph_clk.ar_valid;
    assign tb_periph_cdc_arready = `SMC_PERIPH.axil_i2c_resp_periph_clk.ar_ready;
    assign tb_periph_cdc_rvalid  = `SMC_PERIPH.axil_i2c_resp_periph_clk.r_valid;
    assign tb_efuse_bank_awvalid = u_dut.u_smc.efuse_bank_ctrl_req_o.aw_valid;
    assign tb_efuse_bank_wvalid  = u_dut.u_smc.efuse_bank_ctrl_req_o.w_valid;
    assign tb_efuse_bank_arvalid = u_dut.u_smc.efuse_bank_ctrl_req_o.ar_valid;
    assign tb_efuse_bank_bvalid  = u_dut.u_smc.efuse_bank_ctrl_resp_i.b_valid;
    assign tb_efuse_bank_rvalid  = u_dut.u_smc.efuse_bank_ctrl_resp_i.r_valid;
    assign tb_efuse_shim_cmd_valid =
        `SMC_PERIPH.u_smc_efuse_wrapper.efuse_shim_command_req_o.valid;
    assign tb_efuse_shim_resp_valid =
        `SMC_PERIPH.u_smc_efuse_wrapper.efuse_shim_command_resp_i.valid;
    assign tb_efuse_shim_resp_status =
        `SMC_PERIPH.u_smc_efuse_wrapper.efuse_shim_command_resp_i.status;
    assign tb_efuse_locks = shadow_regs.locks.locks;
    `define SMC_MBX0 u_dut.u_smc.u_smc_base.u_internal_regs.u_smc_axil_mailbox.gen_mailbox[0].u_axi_lite_mailbox
    assign tb_mbx0_full  = `SMC_MBX0.mbox_full;
    assign tb_mbx0_empty = `SMC_MBX0.mbox_empty;
    `undef SMC_MBX0
    `undef SMC_PERIPH

    // TB glue: pulse tb_dfd_fault_inject to latch a deterministic token. This
    // is NOT smc_dfd_wrap / hw/ip/dfd coverage.
    // Hart0 PC can be X before CPU bring-up, so do not sample hierarchical PC
    // into the public capture port (cocotb cannot int() X).
    always_ff @(posedge clk_smc or negedge rst_cold_n_int) begin
        if (!rst_cold_n_int) begin
            tb_dbs_capture_valid <= 1'b0;
            tb_dbs_capture_data  <= '0;
        end else if (tb_dfd_fault_inject) begin
            tb_dbs_capture_valid <= 1'b1;
            tb_dbs_capture_data  <= 32'hDB5C_AFE1;  // TB token, not DUT DFD
        end
    end

    // ------------------------------------------------------------------
    // Elaboration aliases (additive; see header comment).
    // ------------------------------------------------------------------
    assign dut_present_o = 1'b1;
    assign powergood_o    = powergood_stable_o;
    assign rst_cold_n_o   = rst_cold_stable_ref_clk_no;
    assign smc_reset_n_o  = rst_primary_smc_clk_no;
    assign smc_scratch_0_o =
        u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu_ctrl_wrap.scratch_reg[0];
    assign smc_test_pass_o = (smc_scratch_0_o == SmcTestPass);
    assign smc_test_fail_o = (smc_scratch_0_o == SmcTestFail);
    assign output_axi_write_count_o = tb_output_axi_write_count;
    assign output_axi_read_count_o  = tb_output_axi_read_count;

    // ------------------------------------------------------------------
    // Functional coverage (SMC_FCOV.adoc): shared by both tb shapes. Each
    // module carries Verilator-safe cover-property points -- which land in
    // the `user` metric family under --coverage-user -- plus commercial-only
    // covergroups internally. Every port below is a smc_tb_signal_list.svh
    // signal, so no hierarchical reference and no smc_public_scope.vlt
    // change is needed.
    //
    // Single-instance body only: the SMC_DUAL port surface is narrower and
    // does not carry these observables.
    // ------------------------------------------------------------------
    smc_reset_fcov #(
        .CPU_CLUSTER_COUNT ($bits(tb_ndmreset_request))
    ) u_smc_reset_fcov (
        .clk_ref_i                   (clk_ref),
        .clk_smc_i                   (clk_smc),
        .powergood_i                 (powergood_i),
        .rst_cold_ni                 (rst_cold_ni),
        .rst_cool_ni                 (rst_cool_ni),
        .sep_wdt_reset_ni            (tb_sep_wdt_reset_n),
        .cfg_flr_pf_active_i         (tb_cfg_flr_pf_active),
        .ndmreset_request_i          (tb_ndmreset_request),
        .powergood_stable_i          (powergood_stable_o),
        .rst_cold_stable_ref_clk_ni  (rst_cold_stable_ref_clk_no),
        .rst_primary_ref_clk_ni      (rst_primary_ref_clk_no),
        .rst_primary_smc_clk_ni      (rst_primary_smc_clk_no),
        .rst_wdt_smc_clk_ni          (rst_wdt_smc_clk_no),
        .rst_warm_smc_clk_ni         (tb_rst_warm_smc_clk_n),
        .rst_cool_from_flr_ni        (tb_rst_cool_from_flr),
        .fuse_reset_ni               (tb_fuse_reset_n),
        .ss0_warm_reset_ni           (tb_ss0_warm_reset_n),
        .ndmreset_process_i          (tb_ndmreset_process),
        .ndmreset_irq_i              (tb_ndmreset_irq)
    );

    smc_clk_fcov u_smc_clk_fcov (
        .clk_ref_i                (clk_ref),
        .clk_smc_i                (clk_smc),
        .clk_periph_i             (clk_periph),
        .rst_cold_ni              (rst_cold_n_int),
        .test_en_i                (tb_test_en_i),
        .i2c_cg_en_i              (tb_i2c_cg_en),
        .dma_cg_en_i              (tb_dma_cg_en),
        .dma_gated_clk_i          (tb_dma_gated_clk),
        .dma_busy_i               (tb_dma_busy),
        .dma_frontend_busy_i      (tb_dma_frontend_busy),
        .dma_backend_busy_i       (tb_dma_backend_busy),
        .dma_gater_busy_i         (tb_dma_gater_busy),
        .zeroer_cg_en_i           (tb_zeroer_cg_en),
        .zeroer_gated_axi_clk_i   (tb_zeroer_gated_axi_clk),
        .zeroer_gated_reg_clk_i   (tb_zeroer_gated_reg_clk),
        .zeroer_busy_i            (tb_zeroer_busy),
        .zeroer_bus_active_i      (tb_zeroer_bus_active),
        .telemetry_atvalid_i      (tb_telemetry0_atvalid),
        .telemetry_atready_i      (tb_telemetry0_atready),
        .telemetry_atdata_i       (tb_telemetry0_atdata)
    );

    smc_periph_fcov #(
        .GPIO_WIDTH (smc_pkg::NumGpioWraps)
    ) u_smc_periph_fcov (
        .clk_periph_i                (clk_periph),
        .clk_smc_i                   (clk_smc),
        .rst_cold_ni                 (rst_cold_n_int),
        .i2c0_scl_i                  (tb_i2c0_scl),
        .i2c0_sda_i                  (tb_i2c0_sda),
        .i2c0_scl_dut_low_i          (tb_i2c0_scl_dut_low),
        .i2c0_sda_dut_low_i          (tb_i2c0_sda_dut_low),
        .i2c0_scl_ext_low_i          (tb_i2c0_scl_ext_low),
        .i2c0_sda_ext_low_i          (tb_i2c0_sda_ext_low),
        .i2c0_scl_sense_i            (tb_i2c0_scl_i),
        .i2c0_sda_sense_i            (tb_i2c0_sda_i),
        .i2c0_enable_i               (tb_i2c0_enable),
        .i2c0_smbalert_i             (tb_i2c0_smbalert),
        .i3c0_scl_i                  (tb_i3c0_scl),
        .i3c0_sda_i                  (tb_i3c0_sda),
        .i3c0_scl_dut_low_i          (tb_i3c0_scl_dut_low),
        .i3c0_sda_dut_low_i          (tb_i3c0_sda_dut_low),
        .gpio_core2pad_any_i         (tb_gpio_core2pad_any),
        .gpio_core2pad_en_any_i      (tb_gpio_core2pad_en_any),
        .gpio_pad2core_en_any_i      (tb_gpio_pad2core_en_any),
        .core2pad_i                  (tb_core2pad_o),
        .core2pad_en_i               (tb_core2pad_en_o),
        .lsio_select_i               (tb_lsio_interface_select),
        .gpio_pad57_i                (tb_gpio_pad57),
        .sync_irq_i                  (tb_sync_irq),
        .gpio_irq_any_i              (tb_gpio_irq_any),
        .uart_irq_any_i              (tb_uart_irq_any),
        .mailbox_irq_any_i           (tb_mailbox_irq_any),
        .avsbus_irq_i                (tb_avsbus_irq),
        .telemetry_irq_any_i         (tb_telemetry_irq_any),
        .temp_interrupt_irq_i        (tb_temp_interrupt_irq),
        .efuse_locked_access_irq_i   (tb_efuse_locked_access_irq),
        .axi_hang_irq_i              (tb_axi_hang_irq),
        .axi_hang_irq_sys_i          (tb_axi_hang_irq_sys),
        .axi_hang_irq_sep_i          (tb_axi_hang_irq_sep),
        .axi_hang_irq_data_i         (tb_axi_hang_irq_data),
        .axi_hang_irq_periph30_i     (tb_axi_hang_irq_periph30),
        .axi_hang_irq_plic_src_i     (tb_axi_hang_irq_plic_src),
        .ext_interrupt_0_sync_i      (tb_ext_interrupt_0_sync),
        .cdc_awvalid_i               (tb_periph_cdc_awvalid),
        .cdc_awready_i               (tb_periph_cdc_awready),
        .cdc_wvalid_i                (tb_periph_cdc_wvalid),
        .cdc_bvalid_i                (tb_periph_cdc_bvalid),
        .cdc_arvalid_i               (tb_periph_cdc_arvalid),
        .cdc_arready_i               (tb_periph_cdc_arready),
        .cdc_rvalid_i                (tb_periph_cdc_rvalid),
        .mbx0_full_i                 (tb_mbx0_full),
        .mbx0_empty_i                (tb_mbx0_empty),
        .mailbox_interrupts_i        (tb_mailbox_interrupts),
        .telem_atvalid_i             (tb_telem_atvalid),
        .telem_atready_i             (tb_telem_atready),
        .telem_atid0_i               (tb_telem_atid0),
        .telem_atid1_i               (tb_telem_atid1),
        .telem_atid2_i               (tb_telem_atid2),
        .uart_tx_i                   (tb_uart_tx),
        .i2c_host_enable_i           (tb_i2c_host_enable),
        .i2c_target_enable_i         (tb_i2c_target_enable),
        .clk_ref_i                   (clk_ref),
        .timer_count_i               (timer_count)
    );

    smc_int_fcov #(
        .CPU_INTERRUPT_COUNT (smc_4core_cpu_pkg::NumCpuInterrupts),
        .EXT_INTERRUPT_COUNT (smc_4core_cpu_pkg::NumExtInterrupts),
        .CPU_CLUSTER_COUNT   ($bits(tb_ndmreset_request))
    ) u_smc_int_fcov (
        .clk_smc_i                 (clk_smc),
        .rst_cold_ni               (rst_cold_n_int),
        .cpu_interrupts_i          (tb_cpu_interrupts),
        .hang_sys_i                (tb_axi_hang_irq_sys),
        .hang_sep_i                (tb_axi_hang_irq_sep),
        .hang_data_i               (tb_axi_hang_irq_data),
        .plic_pending_low_i        (tb_plic_pending_low),
        .plic_pending_324_i        (tb_plic_pending_324),
        .plic_claim0_i             (tb_plic_claim0),
        .plic_maxdev0_i            (tb_plic_maxdev0),
        .plic_threshold0_i         (tb_plic_threshold0),
        .plic_enables0_i           (tb_plic_enables0_w0),
        .plic_meip_i               (tb_plic_meip),
        .ndmreset_request_i        (tb_ndmreset_request),
        .ndmreset_request_sync_i   (tb_ndmreset_request_sync),
        .sync_irq_i                (tb_sync_irq)
    );

    smc_dma_fcov u_smc_dma_fcov (
        .clk_smc_i             (clk_smc),
        .rst_cold_ni           (rst_cold_n_int),
        .next_id_re_i          (tb_dma_next_id_re),
        .next_id_i             (tb_dma_next_id),
        .status0_i             (tb_dma_status0),
        .done_id_i             (tb_dma_done_id),
        .done_id_re_i          (tb_dma_done_id_re),
        .src_addr_i            (tb_dma_src_addr),
        .dst_addr_i            (tb_dma_dst_addr),
        .length_i              (tb_dma_length),
        .fe_req_valid_i        (tb_dma_fe_req_valid),
        .fe_req_ready_i        (tb_dma_fe_req_ready),
        .trans_complete_i      (tb_dma_trans_complete),
        .mst_awvalid_i         (tb_dma_mst_awvalid),
        .mst_awready_i         (tb_dma_mst_awready),
        .mst_awaddr_i          (tb_dma_mst_awaddr),
        .mst_awlen_i           (tb_dma_mst_awlen),
        .mst_wvalid_i          (tb_dma_mst_wvalid),
        .mst_wready_i          (tb_dma_mst_wready),
        .mst_wlast_i           (tb_dma_mst_wlast),
        .mst_wstrb_i           (tb_dma_mst_wstrb),
        .cg_en_i               (tb_dma_cg_en),
        .gated_clk_i           (tb_dma_gated_clk),
        .frontend_gated_clk_i  (tb_dma_frontend_gated_clk),
        .frontend_wakeup_i     (tb_dma_frontend_wakeup),
        .backend_busy_i        (tb_dma_backend_busy)
    );

    smc_zeroer_fcov u_smc_zeroer_fcov (
        .clk_smc_i               (clk_smc),
        .rst_cold_ni             (rst_cold_n_int),
        .rst_primary_smc_clk_ni  (rst_primary_smc_clk_no),
        .dest_addr_i             (tb_zeroer_dest_addr),
        .size_i                  (tb_zeroer_size),
        .strb_dest_i             (tb_zeroer_strb_dest),
        .strb_size_i             (tb_zeroer_strb_size),
        .req_is_wr_i             (tb_zeroer_req_is_wr),
        .trigger_i               (tb_zeroer_trigger),
        .status_read_i           (tb_zeroer_status_read),
        .state_i                 (tb_zeroer_state),
        .busy_i                  (tb_zeroer_busy),
        .intp_i                  (tb_zeroer_intp),
        .outstanding_i           (tb_zeroer_outstanding),
        .awvalid_i               (tb_zeroer_awvalid),
        .awready_i               (tb_zeroer_awready),
        .awaddr_i                (tb_zeroer_awaddr),
        .awlen_i                 (tb_zeroer_awlen),
        .wvalid_i                (tb_zeroer_wvalid),
        .wready_i                (tb_zeroer_wready),
        .wlast_i                 (tb_zeroer_wlast),
        .wstrb_i                 (tb_zeroer_wstrb),
        .wdata_i                 (tb_zeroer_wdata),
        .bvalid_i                (tb_zeroer_bvalid),
        .disable_cg_i            (tb_zeroer_disable_cg),
        .axi_clk_enable_i        (tb_zeroer_axi_clk_enable),
        .gated_axi_clk_i         (tb_zeroer_gated_axi_clk),
        .gated_reg_clk_i         (tb_zeroer_gated_reg_clk),
        .bus_active_i            (tb_zeroer_bus_active)
    );

    smc_iso_fcov u_smc_iso_fcov (
        .clk_smc_i                 (clk_smc),
        .clk_ref_i                 (clk_ref),
        .powergood_i               (powergood_i),
        .isolate_req_i             (tb_isolate_req_o),
        .isolate_req_reg_i         (tb_isolate_req_reg),
        .isolate_req_smcen_reg_i   (tb_isolate_req_smcen_reg),
        .isolate_req_smc_reg_i     (tb_isolate_req_smc_reg),
        .cfg_flr_pf_active_i       (tb_cfg_flr_pf_active),
        .flr_sync_ref_i            (tb_flr_sync_ref),
        .flr_posedge_ref_i         (tb_flr_posedge_ref),
        .flr_counter_state_i       (tb_flr_counter_state),
        .rst_cool_ni               (rst_cool_ni),
        .rst_primary_smc_clk_ni    (rst_primary_smc_clk_no),
        .rst_warm_smc_clk_ni       (tb_rst_warm_smc_clk_n),
        .sep_wdt_reset_ni          (tb_sep_wdt_reset_n),
        .wdt_first_timeout_i       (tb_wdt_first_timeout),
        .wdt_second_timeout_i      (tb_wdt_second_timeout)
    );

    smc_filt_fcov u_smc_filt_fcov (
        .clk_smc_i              (clk_smc),
        .rst_cold_ni            (rst_cold_n_int),
        .gpio_awvalid_i         (tb_gpio0_awvalid),
        .gpio_arvalid_i         (tb_gpio0_arvalid),
        .gpio_awprot_i          (tb_gpio0_awprot),
        .gpio_arprot_i          (tb_gpio0_arprot),
        .gpio_awprot_req_i      (tb_gpio0_awprot_req),
        .gpio_arprot_req_i      (tb_gpio0_arprot_req),
        .gpio_wr_filter_en_i    (tb_gpio0_wr_filter_en),
        .gpio_rd_filter_en_i    (tb_gpio0_rd_filter_en),
        .jtag_awvalid_i         (jtag_axi_awvalid),
        .jtag_arvalid_i         (jtag_axi_arvalid),
        .remap_jtag_aw_hit_i    (tb_remap_jtag_aw_hit),
        .remap_jtag_ar_hit_i    (tb_remap_jtag_ar_hit),
        .inb_write_hit_i        (tb_inb_write_hit),
        .inb_read_hit_i         (tb_inb_read_hit),
        .inb_isolate_write_i    (tb_inb_isolate_write),
        .inb_isolate_read_i     (tb_inb_isolate_read)
    );

    smc_fabric_fcov u_smc_fabric_fcov (
        .clk_smc_i                  (clk_smc),
        .rst_cold_ni                (rst_cold_n_int),

        .axil_dtp_csr_active_i      (tb_axil_dtp_csr_active),
        .axil_external_active_i     (tb_axil_external_active),
        .axil_efuse_bank_active_i   (tb_axil_efuse_bank_active),
        .axil_any_master_active_i   (tb_axil_any_master_active),

        .sep_awvalid_i              (s_axi_awvalid),
        .sep_awready_i              (s_axi_awready),
        .sep_awlen_i                (s_axi_awlen),
        .sep_awsize_i               (s_axi_awsize),
        .sep_awburst_i              (s_axi_awburst),
        .sep_wvalid_i               (s_axi_wvalid),
        .sep_wready_i               (s_axi_wready),
        .sep_wlast_i                (s_axi_wlast),
        .sep_wstrb_i                (s_axi_wstrb),
        .sep_bvalid_i               (s_axi_bvalid),
        .sep_bready_i               (s_axi_bready),
        .sep_bresp_i                (s_axi_bresp),
        .sep_arvalid_i              (s_axi_arvalid),
        .sep_arready_i              (s_axi_arready),
        .sep_arlen_i                (s_axi_arlen),
        .sep_arsize_i               (s_axi_arsize),
        .sep_rvalid_i               (s_axi_rvalid),
        .sep_rready_i               (s_axi_rready),
        .sep_rlast_i                (s_axi_rlast),
        .sep_rresp_i                (s_axi_rresp),
        .sep_r_hold_i               (tb_sep_axi_r_hold),
        .sep_awaddr_i               (s_axi_awaddr),
        .sep_araddr_i               (s_axi_araddr),
        .sep_awid_i                 (s_axi_awid),
        .sep_arid_i                 (s_axi_arid),
        .sep_bid_i                  (s_axi_bid),
        .sep_rid_i                  (s_axi_rid),

        .sys_awvalid_i              (sys_axi_awvalid),
        .sys_awready_i              (sys_axi_awready),
        .sys_awlen_i                (sys_axi_awlen),
        .sys_wvalid_i               (sys_axi_wvalid),
        .sys_wready_i               (sys_axi_wready),
        .sys_wlast_i                (sys_axi_wlast),
        .sys_bvalid_i               (sys_axi_bvalid),
        .sys_bready_i               (sys_axi_bready),
        .sys_bresp_i                (sys_axi_bresp),
        .sys_arvalid_i              (sys_axi_arvalid),
        .sys_arready_i              (sys_axi_arready),
        .sys_arlen_i                (sys_axi_arlen),
        .sys_rvalid_i               (sys_axi_rvalid),
        .sys_rready_i               (sys_axi_rready),
        .sys_rlast_i                (sys_axi_rlast),
        .sys_rresp_i                (sys_axi_rresp),
        .sys_r_hold_i               (tb_sys_axi_r_hold),

        .jtag_awvalid_i             (jtag_axi_awvalid),
        .jtag_awready_i             (jtag_axi_awready),
        .jtag_awlen_i               (jtag_axi_awlen),
        .jtag_wvalid_i              (jtag_axi_wvalid),
        .jtag_wready_i              (jtag_axi_wready),
        .jtag_wlast_i               (jtag_axi_wlast),
        .jtag_bvalid_i              (jtag_axi_bvalid),
        .jtag_bready_i              (jtag_axi_bready),
        .jtag_bresp_i               (jtag_axi_bresp),
        .jtag_arvalid_i             (jtag_axi_arvalid),
        .jtag_arready_i             (jtag_axi_arready),
        .jtag_arlen_i               (jtag_axi_arlen),
        .jtag_rvalid_i              (jtag_axi_rvalid),
        .jtag_rready_i              (jtag_axi_rready),
        .jtag_rlast_i               (jtag_axi_rlast),
        .jtag_rresp_i               (jtag_axi_rresp),

        .ej_awvalid_i               (ej_axi_awvalid),
        .ej_awready_i               (ej_axi_awready),
        .ej_wvalid_i                (ej_axi_wvalid),
        .ej_wready_i                (ej_axi_wready),
        .ej_bvalid_i                (ej_axi_bvalid),
        .ej_bready_i                (ej_axi_bready),
        .ej_bresp_i                 (ej_axi_bresp),
        .ej_arvalid_i               (ej_axi_arvalid),
        .ej_arready_i               (ej_axi_arready),
        .ej_rvalid_i                (ej_axi_rvalid),
        .ej_rready_i                (ej_axi_rready),
        .ej_rresp_i                 (ej_axi_rresp),

        .out_awvalid_i              (tb_output_axi_awvalid),
        .out_awready_i              (tb_output_axi_awready),
        .out_wvalid_i               (tb_output_axi_wvalid),
        .out_wready_i               (tb_output_axi_wready),
        .out_bvalid_i               (tb_output_axi_bvalid),
        .out_bready_i               (tb_output_axi_bready),
        .out_bresp_i                (tb_output_axi_bresp),
        .out_arvalid_i              (tb_output_axi_arvalid),
        .out_arready_i              (tb_output_axi_arready),
        .out_rvalid_i               (tb_output_axi_rvalid),
        .out_rready_i               (tb_output_axi_rready),
        .out_rresp_i                (tb_output_axi_rresp),
        .out_resp_hold_i            (tb_output_axi_resp_hold),
        .out_write_count_i          (tb_output_axi_write_count),
        .out_read_count_i           (tb_output_axi_read_count)
    );

    // Spec-derived P0 coverage: address map over SEP_IN, reset sequencing,
    // clock domains, CPU/boot, GPIO pads and eFuse/lifecycle. Same port rule
    // as above: tb signals and smc_wrapper boundary ports only.
    smc_map_fcov u_smc_map_fcov (
        .clk_smc_i      (clk_smc),
        .rst_cold_ni    (rst_cold_n_int),
        .sep_awvalid_i  (s_axi_awvalid),
        .sep_awready_i  (s_axi_awready),
        .sep_awaddr_i   (s_axi_awaddr),
        .sep_wvalid_i   (s_axi_wvalid),
        .sep_wready_i   (s_axi_wready),
        .sep_wlast_i    (s_axi_wlast),
        .sep_wdata_i    (s_axi_wdata),
        .sep_bvalid_i   (s_axi_bvalid),
        .sep_bready_i   (s_axi_bready),
        .sep_bresp_i    (s_axi_bresp),
        .sep_arvalid_i  (s_axi_arvalid),
        .sep_arready_i  (s_axi_arready),
        .sep_araddr_i   (s_axi_araddr),
        .sep_rvalid_i   (s_axi_rvalid),
        .sep_rready_i   (s_axi_rready),
        .sep_rlast_i    (s_axi_rlast),
        .sep_rresp_i    (s_axi_rresp),
        .sep_rdata_i    (s_axi_rdata),
        .sys_bvalid_i   (sys_axi_bvalid),
        .sys_bready_i   (sys_axi_bready),
        .sys_rvalid_i   (sys_axi_rvalid),
        .sys_rready_i   (sys_axi_rready),
        .sys_rlast_i    (sys_axi_rlast),
        .jtag_awvalid_i (jtag_axi_awvalid),
        .jtag_awready_i (jtag_axi_awready),
        .jtag_awaddr_i  (jtag_axi_awaddr),
        .jtag_arvalid_i (jtag_axi_arvalid),
        .jtag_arready_i (jtag_axi_arready),
        .jtag_araddr_i  (jtag_axi_araddr),
        .jtag_bresp_i   (jtag_axi_bresp),
        .jtag_rresp_i   (jtag_axi_rresp),
        .jtag_bvalid_i  (jtag_axi_bvalid),
        .jtag_bready_i  (jtag_axi_bready),
        .jtag_rvalid_i  (jtag_axi_rvalid),
        .jtag_rready_i  (jtag_axi_rready),
        .jtag_rlast_i   (jtag_axi_rlast),
        .lc_state_i     (tb_lc_state),
        .region_size_i  (smc_region_size),
        .ext_active_i   (tb_axil_external_active)
    );

    smc_rst_seq_fcov u_smc_rst_seq_fcov (
        .clk_ref_i                  (clk_ref),
        .clk_smc_i                  (clk_smc),
        .clk_periph_i               (clk_periph),
        .powergood_i                (powergood_i),
        .rst_cold_ni                (rst_cold_ni),
        .ext_boot_seq_done_i        (ext_boot_seq_done),
        .rst_telemetry_ni           (rst_cold_n_int),
        .powergood_stable_i         (powergood_stable_o),
        .rst_cold_stable_ref_clk_ni (rst_cold_stable_ref_clk_no),
        .rst_primary_smc_clk_ni     (rst_primary_smc_clk_no),
        .rst_primary_periph_clk_ni  (rst_primary_periph_clk_n),
        .rst_warm_smc_clk_ni        (tb_rst_warm_smc_clk_n),
        .fuse_sense_done_i          (smc_fuse_sense_done_o),
        .fuse_reset_ni              (tb_fuse_reset_n),
        .cpu_core_reset_ni          (tb_cpu_core_reset_n),
        .sep_awready_i              (s_axi_awready),
        .sep_arready_i              (s_axi_arready),
        .region_size_i              (smc_region_size),
        .scratch_0_i                (smc_scratch_0_o),
        .ss_config_i                (ss_config)
    );

    smc_clk_domain_fcov u_smc_clk_domain_fcov (
        .clk_ref_i          (clk_ref),
        .clk_smc_i          (clk_smc),
        .clk_periph_i       (clk_periph),
        .rst_cold_ni        (rst_cold_n_int),
        .cpu_trace_valid_i  (tb_cpu_trace_valid),
        .timer_count_i      (timer_count),
        .avs_clk_i          (tb_avs_clk_from_dut),
        .uart0_tx_i         (tb_uart0_tx_from_dut)
    );

    smc_cpu_fcov #(
        .CUSTOM_ACTION_WIDTH (cla_pkg::CLA_NUMBER_OF_CUSTOM_ACTIONS)
    ) u_smc_cpu_fcov (
        .clk_smc_i               (clk_smc),
        .rst_cold_ni             (rst_cold_n_int),
        .rst_primary_smc_clk_ni  (rst_primary_smc_clk_no),
        .powergood_stable_i      (powergood_stable_o),
        .fuse_sense_done_i       (smc_fuse_sense_done_o),
        .core_reset_ni           (tb_cpu_core_reset_n),
        .init_mem_done_i         (smc_init_mem_done_o),
        .cluster_isolate_i       (tb_cpu_cluster_isolate),
        .cpu_trace_valid_i       (tb_cpu_trace_valid),
        .cpu_trace_pc_i          (tb_cpu_trace_pc),
        .wb_pc1_i                (tb_cpu_wb_pc1),
        .wb_pc2_i                (tb_cpu_wb_pc2),
        .wb_pc3_i                (tb_cpu_wb_pc3),
        .rom_read_count_i        (tb_cpu_rom_read_count),
        .scratch_read_count_i    (tb_cpu_scratch_read_count),
        .scratch_write_count_i   (tb_cpu_scratch_write_count),
        .scratch_0_i             (smc_scratch_0_o),
        .scratch_2_i             (tb_cpu_scratch2),
        .sep_awvalid_i           (s_axi_awvalid),
        .sep_awready_i           (s_axi_awready),
        .sep_bvalid_i            (s_axi_bvalid),
        .sep_bready_i            (s_axi_bready),
        .sys_awvalid_i           (sys_axi_awvalid),
        .sys_awready_i           (sys_axi_awready),
        .sys_bvalid_i            (sys_axi_bvalid),
        .sys_bready_i            (sys_axi_bready),
        .jtag_awvalid_i          (jtag_axi_awvalid),
        .jtag_awready_i          (jtag_axi_awready),
        .jtag_bvalid_i           (jtag_axi_bvalid),
        .jtag_bready_i           (jtag_axi_bready),
        .zeroer_intp_i           (tb_zeroer_intp),
        .cla_custom_action_i     (cla_ext_action_custom)
    );

    smc_gpio_fcov #(
        .GPIO_WIDTH        (smc_pkg::NumGpioWraps),
        .DEFAULT_INPUT_MAP (smc_padring_pkg::DefaultDirectionMap)
    ) u_smc_gpio_fcov (
        .clk_smc_i               (clk_smc),
        .rst_cold_ni             (rst_cold_n_int),
        .rst_primary_smc_clk_ni  (rst_primary_smc_clk_no),
        .core2pad_i              (tb_core2pad_o),
        .core2pad_en_i           (tb_core2pad_en_o),
        .pad2core_en_i           (tb_pad2core_en_o),
        .pad_i                   (gpio_pad_io),
        .lsio_select_i           (tb_lsio_interface_select)
    );

    smc_efuse_fcov #(
        .SHADOW_WIDTH   ($bits(smc_efuse_pkg::efuse_map_t)),
        .LC_STATE_WIDTH ($bits(tb_lc_state))
    ) u_smc_efuse_fcov (
        .clk_smc_i          (clk_smc),
        .rst_cold_ni        (rst_cold_n_int),
        .fuse_sense_done_i  (smc_fuse_sense_done_o),
        .fuse_reset_ni      (tb_fuse_reset_n),
        .skip_mem_repair_i  (tb_skip_mem_repair_o),
        .shadow_regs_i      (shadow_regs),
        .lc_state_i         (tb_lc_state),
        .lc_sigint_err_i    (lc_sigint_err),
        .bank_awvalid_i     (tb_efuse_bank_awvalid),
        .bank_wvalid_i      (tb_efuse_bank_wvalid),
        .bank_arvalid_i     (tb_efuse_bank_arvalid),
        .bank_bvalid_i      (tb_efuse_bank_bvalid),
        .bank_rvalid_i      (tb_efuse_bank_rvalid),
        .shim_cmd_valid_i   (tb_efuse_shim_cmd_valid),
        .shim_resp_valid_i  (tb_efuse_shim_resp_valid),
        .shim_resp_status_i (tb_efuse_shim_resp_status),
        .jtag_otp_awvalid_i (ej_axi_awvalid),
        .jtag_otp_awready_i (ej_axi_awready),
        .jtag_otp_bvalid_i  (ej_axi_bvalid),
        .jtag_otp_arvalid_i (ej_axi_arvalid),
        .jtag_otp_arready_i (ej_axi_arready),
        .jtag_otp_rvalid_i  (ej_axi_rvalid),
        .locks_i            (tb_efuse_locks),
        .locked_access_irq_i (tb_efuse_locked_access_irq),
        .read_done_i        (tb_efuse_read_done),
        .readback_i         (tb_efuse_readback),
        .program_done_i     (tb_efuse_program_done),
        .read_error_i       (tb_efuse_read_error),
        .program_error_i    (tb_efuse_program_error),
        .read_addr_i        (tb_efuse_read_addr),
        .program_addr_i     (tb_efuse_program_addr)
    );

`else  // SMC_DUAL
    // ==================================================================
    // Dual-instance body: two smc_dual_inst on a shared I3C bus.
    //
    // ------------------------------------------------------------------
    // Shared-pad model (KNOWN RISK -- the most delicate logic in this file)
    // ------------------------------------------------------------------
    // The single-instance half above already reconstructs the I2C/I3C
    // open-drain bus by hand (because `pullup` is ignored under Verilator).
    // Here the same reconstruction has to resolve *two* real drivers instead
    // of one DUT plus an external VIP:
    //
    //     scl = !(dut_pulls_low || bfm_pulls_low || ext_low)
    //
    // where "<x>_pulls_low" is that instance's own pad OE asserted while its
    // pad data is 0. The resolved value is then driven strongly onto the pads
    // of BOTH instances, so each one's input buffer sees the true bus state.
    // This assumes the I3C core only asserts pad OE while driving a logic 0
    // and never pushes a strong 1 -- the same assumption the single-instance
    // half documents. If that is ever violated, the two strong drives can
    // contend. Confirm on waveforms.
    //
    // OccpTargetUpPad is the OCCP "target up" pad (smc_padring.sv: software
    // GPIO). The controller firmware polls it in
    // wait_for_target_up_gpio() (fw/common/occp/occp_interfaces.c), and the
    // target's production ROM drives it from set_gpio_status(OCCP_ERROR_NONE)
    // (bootrom/prod/lib/src/occp.c) on the success path of OCCP init.
    //
    // The undriven value is 0, matching the reference environment's pulldown
    // on this pad. It must NOT default high: a target that never asserts
    // readiness would then be indistinguishable from one that does, and in
    // silicon a real host would hang forever waiting for it.
    // ==================================================================

    /* verilator public_module */

    // I3C pad numbers live in SharedI3c*Pad below, next to the channel list.
    localparam int unsigned OccpTargetUpPad = 58;
    localparam int unsigned BootStallPad = 57;

    // ------------------------------------------------------------------
    // Per-instance AXI bundles
    // ------------------------------------------------------------------
    smc_sep_in_56_64_6_12_axi_req_t  dut_sep_axi_req, bfm_sep_axi_req;
    smc_sep_in_56_64_6_12_axi_resp_t dut_sep_axi_resp, bfm_sep_axi_resp;
    smc_sys_out_56_64_8_12_axi_req_t  dut_out_axi_req, bfm_out_axi_req;
    smc_sys_out_56_64_8_12_axi_resp_t dut_out_axi_resp, bfm_out_axi_resp;

    // ------------------------------------------------------------------
    // Flat -> struct packing. `atop` is forced to 0 on both ingresses for the
    // same reason the single-instance half does it: the outbound filter's
    // err_slv assumes atop == '0 and a fatal fires if the field X-propagates.
    // ------------------------------------------------------------------
    `define OCAH_DUAL_PACK_AXI(BUNDLE, RESP, PFX)                       \
        assign BUNDLE.aw.id     = PFX``_awid;                           \
        assign BUNDLE.aw.addr   = PFX``_awaddr;                         \
        assign BUNDLE.aw.len    = PFX``_awlen;                          \
        assign BUNDLE.aw.size   = PFX``_awsize;                         \
        assign BUNDLE.aw.burst  = PFX``_awburst;                        \
        assign BUNDLE.aw.lock   = PFX``_awlock;                         \
        assign BUNDLE.aw.cache  = PFX``_awcache;                        \
        assign BUNDLE.aw.prot   = PFX``_awprot;                         \
        assign BUNDLE.aw.qos    = PFX``_awqos;                          \
        assign BUNDLE.aw.region = PFX``_awregion;                       \
        assign BUNDLE.aw.user   = PFX``_awuser;                         \
        assign BUNDLE.aw.atop   = '0;                                   \
        assign BUNDLE.aw_valid  = PFX``_awvalid;                        \
        assign PFX``_awready    = RESP.aw_ready;                        \
        assign BUNDLE.w.data    = PFX``_wdata;                          \
        assign BUNDLE.w.strb    = PFX``_wstrb;                          \
        assign BUNDLE.w.last    = PFX``_wlast;                          \
        assign BUNDLE.w.user    = PFX``_wuser;                          \
        assign BUNDLE.w_valid   = PFX``_wvalid;                         \
        assign PFX``_wready     = RESP.w_ready;                         \
        assign PFX``_bid        = RESP.b.id;                            \
        assign PFX``_bresp      = RESP.b.resp;                          \
        assign PFX``_buser      = RESP.b.user;                          \
        assign PFX``_bvalid     = RESP.b_valid;                         \
        assign BUNDLE.b_ready   = PFX``_bready;                         \
        assign BUNDLE.ar.id     = PFX``_arid;                           \
        assign BUNDLE.ar.addr   = PFX``_araddr;                         \
        assign BUNDLE.ar.len    = PFX``_arlen;                          \
        assign BUNDLE.ar.size   = PFX``_arsize;                         \
        assign BUNDLE.ar.burst  = PFX``_arburst;                        \
        assign BUNDLE.ar.lock   = PFX``_arlock;                         \
        assign BUNDLE.ar.cache  = PFX``_arcache;                        \
        assign BUNDLE.ar.prot   = PFX``_arprot;                         \
        assign BUNDLE.ar.qos    = PFX``_arqos;                          \
        assign BUNDLE.ar.region = PFX``_arregion;                       \
        assign BUNDLE.ar.user   = PFX``_aruser;                         \
        assign BUNDLE.ar_valid  = PFX``_arvalid;                        \
        assign PFX``_arready    = RESP.ar_ready;                        \
        assign PFX``_rid        = RESP.r.id;                            \
        assign PFX``_rdata      = RESP.r.data;                          \
        assign PFX``_rresp      = RESP.r.resp;                          \
        assign PFX``_rlast      = RESP.r.last;                          \
        assign PFX``_ruser      = RESP.r.user;                          \
        assign PFX``_rvalid     = RESP.r_valid;                         \
        assign BUNDLE.r_ready   = PFX``_rready;

    `OCAH_DUAL_PACK_AXI(dut_sep_axi_req, dut_sep_axi_resp, s_axi)
    `OCAH_DUAL_PACK_AXI(bfm_sep_axi_req, bfm_sep_axi_resp, bfm_axi)

    `undef OCAH_DUAL_PACK_AXI

    // ------------------------------------------------------------------
    // SYS_OUT AXI4 egress, one responder per instance: the shared slave agent
    // answers on u_dut_output_axi_if / u_bfm_output_axi_if (cocotb binds both
    // instances); each bridge places its wrapper's struct port on the interface.
    // Each responder follows its instance's primary reset so a cool reset drops
    // the outstanding SYS_OUT responses (see the single-instance half).
    // ------------------------------------------------------------------
    ocah_axi_if u_dut_output_axi_if (
        .aclk    (clk_smc),
        .aresetn (dut_rst_primary_smc_clk_no)
    );

    ocah_axi_struct_bridge #(
        .axi_req_t  (smc_sys_out_56_64_8_12_axi_req_t),
        .axi_resp_t (smc_sys_out_56_64_8_12_axi_resp_t)
    ) u_dut_output_bridge (
        .axi_req_i  (dut_out_axi_req),
        .axi_resp_o (dut_out_axi_resp),
        .axi_if     (u_dut_output_axi_if)
    );

    ocah_axi_if u_bfm_output_axi_if (
        .aclk    (clk_smc),
        .aresetn (bfm_rst_primary_smc_clk_no)
    );

    ocah_axi_struct_bridge #(
        .axi_req_t  (smc_sys_out_56_64_8_12_axi_req_t),
        .axi_resp_t (smc_sys_out_56_64_8_12_axi_resp_t)
    ) u_bfm_output_bridge (
        .axi_req_i  (bfm_out_axi_req),
        .axi_resp_o (bfm_out_axi_resp),
        .axi_if     (u_bfm_output_axi_if)
    );

    // ------------------------------------------------------------------
    // Shared I3C open-drain resolve (see the risk note above).
    //
    // Three channels are cross-wired, not one, because both firmware halves
    // choose among exactly channels {0, 1, 3} and they do not coordinate:
    //   * the target ROM brings all three up as SUBORDINATE
    //     (smc_occp_init in hw/sys/smc/bootrom/prod/lib/src/occp.c calls
    //      smc_occp_init_i3c_channel for 0, 1 and 3)
    //   * the controller picks ONE of the three at random
    //     (initialize_i3c_controller in
    //      hw/sys/smc/dv/fw/common/occp/occp_interfaces.c: get_random_int() % 3
    //      -> I3C_RECOVERY_CONTROLLER_ID 0 / I3C_CONTROLLER_ID 1 /
    //      I3C_BACKUP_CONTROLLER_ID 3)
    // Wiring only channel 0 would make the test pass or hang depending on the
    // firmware's RNG, so all three selectable channels are wired.
    //
    // Channel-to-pad mapping is smc_padring.sv's, not smc_rom_defs.h's:
    //   I3C[0] -> 27/28, I3C[1] -> 63/64, I3C[2] -> 29/30, I3C[3] -> 31/32.
    // ------------------------------------------------------------------
    localparam int unsigned NumSharedI3c = 3;
    localparam int unsigned SharedI3cIdx    [NumSharedI3c] = '{0,  1,  3};
    localparam int unsigned SharedI3cSclPad [NumSharedI3c] = '{27, 63, 31};
    localparam int unsigned SharedI3cSdaPad [NumSharedI3c] = '{28, 64, 32};

    logic [NumSharedI3c-1:0] i3c_scl_dut_low, i3c_sda_dut_low;
    logic [NumSharedI3c-1:0] i3c_scl_bfm_low, i3c_sda_bfm_low;
    logic [NumSharedI3c-1:0] i3c_scl_bus, i3c_sda_bus;

    for (genvar ch = 0; ch < NumSharedI3c; ch++) begin : gen_i3c_resolve
        localparam int unsigned Idx = SharedI3cIdx[ch];

        assign i3c_scl_dut_low[ch] =
            u_dut.u_smc_wrapper.u_smc.u_smc_peripherals.i3c_scl_oe_to_pad[Idx] &&
            !u_dut.u_smc_wrapper.u_smc.u_smc_peripherals.i3c_scl_to_pad[Idx];
        assign i3c_sda_dut_low[ch] =
            u_dut.u_smc_wrapper.u_smc.u_smc_peripherals.i3c_sda_oe_to_pad[Idx] &&
            !u_dut.u_smc_wrapper.u_smc.u_smc_peripherals.i3c_sda_to_pad[Idx];
        assign i3c_scl_bfm_low[ch] =
            u_bfm.u_smc_wrapper.u_smc.u_smc_peripherals.i3c_scl_oe_to_pad[Idx] &&
            !u_bfm.u_smc_wrapper.u_smc.u_smc_peripherals.i3c_scl_to_pad[Idx];
        assign i3c_sda_bfm_low[ch] =
            u_bfm.u_smc_wrapper.u_smc.u_smc_peripherals.i3c_sda_oe_to_pad[Idx] &&
            !u_bfm.u_smc_wrapper.u_smc.u_smc_peripherals.i3c_sda_to_pad[Idx];

        // Channel 0 also takes the external *_ext_low vote so a cocotb VIP can
        // join the same wired-AND as a third driver.
        if (ch == 0) begin : gen_ch0_ext
            assign i3c_scl_bus[ch] = !(i3c_scl_dut_low[ch] || i3c_scl_bfm_low[ch] ||
                                       tb_i3c0_scl_ext_low);
            assign i3c_sda_bus[ch] = !(i3c_sda_dut_low[ch] || i3c_sda_bfm_low[ch] ||
                                       tb_i3c0_sda_ext_low);
        end else begin : gen_ch_n
            assign i3c_scl_bus[ch] = !(i3c_scl_dut_low[ch] || i3c_scl_bfm_low[ch]);
            assign i3c_sda_bus[ch] = !(i3c_sda_dut_low[ch] || i3c_sda_bfm_low[ch]);
        end
    end

    // Channel 0 is lifted under the tb_i3c0_* names of the single-instance TB
    // so cocotb code written against it reads the same signals.
    assign tb_i3c0_scl_dut_low = i3c_scl_dut_low[0];
    assign tb_i3c0_sda_dut_low = i3c_sda_dut_low[0];
    assign tb_i3c0_scl_bfm_low = i3c_scl_bfm_low[0];
    assign tb_i3c0_sda_bfm_low = i3c_sda_bfm_low[0];
    assign tb_i3c0_scl         = i3c_scl_bus[0];
    assign tb_i3c0_sda         = i3c_sda_bus[0];


    // ------------------------------------------------------------------
    // Cross-wired I2C buses
    // ------------------------------------------------------------------
    // One independent wired-AND per channel, like the I3C block above: each
    // channel is its own point-to-point bus between the two instances' I2C
    // controllers.
    //
    // The channels must stay separate. The target listens on all of them at
    // once while the controller drives one at a time, so an idle channel must
    // not be able to hold down an active one.
    //
    // The latch tests tell the two channels apart by target address, which is
    // not automatic: the ROM falls back to 0x55 for both when the eFuse slots
    // are unprogrammed, so those tests also pass +fuse_i2c_ids. See
    // randomize_efuse.py.
    //
    // "Pulls low" reads i2c_scl_o, which despite the name is the controller's
    // output ENABLE: smc_peripherals.sv wires it to the padring's i2c_scl_oen_i,
    // and the padring always drives data 0 because a board would have pullups.
    localparam int unsigned NumTargetI2c = 2;
    localparam int unsigned TargetI2cIdx    [NumTargetI2c] = '{0,  1};
    localparam int unsigned TargetI2cSclPad [NumTargetI2c] = '{37, 41};
    localparam int unsigned TargetI2cSdaPad [NumTargetI2c] = '{38, 42};

    logic [NumTargetI2c-1:0] i2c_scl_dut_low, i2c_sda_dut_low;
    logic [NumTargetI2c-1:0] i2c_scl_bfm_low, i2c_sda_bfm_low;
    logic [NumTargetI2c-1:0] i2c_scl_bus, i2c_sda_bus;

    for (genvar ch = 0; ch < NumTargetI2c; ch++) begin : gen_i2c_target_drivers
        localparam int unsigned Idx = TargetI2cIdx[ch];

        assign i2c_scl_dut_low[ch] =
            !u_dut.u_smc_wrapper.u_smc.u_smc_peripherals.i2c_scl_o[Idx];
        assign i2c_sda_dut_low[ch] =
            !u_dut.u_smc_wrapper.u_smc.u_smc_peripherals.i2c_sda_o[Idx];
        assign i2c_scl_bfm_low[ch] =
            !u_bfm.u_smc_wrapper.u_smc.u_smc_peripherals.i2c_scl_o[Idx];
        assign i2c_sda_bfm_low[ch] =
            !u_bfm.u_smc_wrapper.u_smc.u_smc_peripherals.i2c_sda_o[Idx];

        // No external vote: the tb_i2c0_*_ext_low signals belong to the
        // single-instance half and are not in scope here, and this configuration
        // has no I2C VIP to be a third driver. Add one the way I3C channel 0 does
        // if that changes.
        assign i2c_scl_bus[ch] = !(i2c_scl_dut_low[ch] || i2c_scl_bfm_low[ch]);
        assign i2c_sda_bus[ch] = !(i2c_sda_dut_low[ch] || i2c_sda_bfm_low[ch]);
    end

    // Per-channel bus-activity counters, one set per I3C and per I2C channel. A
    // firmware "pass" with a static SCL would mean the two halves never met on
    // the wire, so count SCL falls and START conditions (SDA falling while SCL
    // high) independently of anything the firmware reports. The per-channel
    // split also tells the test which channel the controller's RNG picked.
    logic [NumSharedI3c-1:0] scl_q, sda_q;
    logic [31:0] scl_fall_q [NumSharedI3c];
    logic [31:0] start_q    [NumSharedI3c];

    logic [NumTargetI2c-1:0] i2c_scl_q, i2c_sda_q;
    logic [31:0] i2c_scl_fall_q [NumTargetI2c];
    logic [31:0] i2c_start_q    [NumTargetI2c];

    always_ff @(posedge clk_periph or negedge rst_cold_ni) begin
        if (!rst_cold_ni) begin
            scl_q <= '1;
            sda_q <= '1;
            i2c_scl_q <= '1;
            i2c_sda_q <= '1;
            for (int unsigned ch = 0; ch < NumTargetI2c; ch++) begin
                i2c_scl_fall_q[ch] <= '0;
                i2c_start_q[ch]    <= '0;
            end
            for (int unsigned ch = 0; ch < NumSharedI3c; ch++) begin
                scl_fall_q[ch] <= '0;
                start_q[ch]    <= '0;
            end
        end else begin
            for (int unsigned ch = 0; ch < NumTargetI2c; ch++) begin
                if (i2c_scl_q[ch] && !i2c_scl_bus[ch]) begin
                    i2c_scl_fall_q[ch] <= i2c_scl_fall_q[ch] + 32'd1;
                end
                if (i2c_scl_bus[ch] && i2c_scl_q[ch] && i2c_sda_q[ch] && !i2c_sda_bus[ch]) begin
                    i2c_start_q[ch] <= i2c_start_q[ch] + 32'd1;
                end
            end
            i2c_scl_q <= i2c_scl_bus;
            i2c_sda_q <= i2c_sda_bus;
            for (int unsigned ch = 0; ch < NumSharedI3c; ch++) begin
                if (scl_q[ch] && !i3c_scl_bus[ch]) begin
                    scl_fall_q[ch] <= scl_fall_q[ch] + 32'd1;
                end
                if (i3c_scl_bus[ch] && scl_q[ch] && sda_q[ch] && !i3c_sda_bus[ch]) begin
                    start_q[ch] <= start_q[ch] + 32'd1;
                end
            end
            scl_q <= i3c_scl_bus;
            sda_q <= i3c_sda_bus;
        end
    end

    // Latch the address and the decoded instance select together, on the AW
    // handshake, so they cannot be sampled from different transactions.
    logic [31:0] bfm_i3c_awaddr_q;
    logic [7:0]  bfm_i3c_wsel_q;
    always_ff @(posedge clk_periph or negedge rst_cold_ni) begin
        if (!rst_cold_ni) begin
            bfm_i3c_awaddr_q <= '0;
            bfm_i3c_wsel_q   <= '0;
        end else if (u_bfm.u_smc_wrapper.u_smc.u_smc_peripherals.u_i3ccore_wrapper.awvalid_i &&
                     u_bfm.u_smc_wrapper.u_smc.u_smc_peripherals.u_i3ccore_wrapper.awready_o) begin
            bfm_i3c_awaddr_q <= 32'(u_bfm.u_smc_wrapper.u_smc.u_smc_peripherals.u_i3ccore_wrapper.awaddr_i);
            bfm_i3c_wsel_q   <= 8'(u_bfm.u_smc_wrapper.u_smc.u_smc_peripherals.u_i3ccore_wrapper.write_select);
        end
    end
    assign tb_bfm_i3c_awaddr = bfm_i3c_awaddr_q;
    assign tb_bfm_i3c_wsel   = bfm_i3c_wsel_q;

    assign tb_i3c_channel_id_0     = 8'(SharedI3cIdx[0]);
    assign tb_i3c_channel_id_1     = 8'(SharedI3cIdx[1]);
    assign tb_i3c_channel_id_2     = 8'(SharedI3cIdx[2]);
    assign tb_i3c_scl_fall_count_0 = scl_fall_q[0];
    assign tb_i3c_scl_fall_count_1 = scl_fall_q[1];
    assign tb_i3c_scl_fall_count_2 = scl_fall_q[2];
    assign tb_i3c_start_count_0    = start_q[0];
    assign tb_i3c_start_count_1    = start_q[1];
    assign tb_i3c_start_count_2    = start_q[2];
    assign tb_i2c_scl_fall_count_0 = i2c_scl_fall_q[0];
    assign tb_i2c_scl_fall_count_1 = i2c_scl_fall_q[1];
    assign tb_i2c_start_count_0    = i2c_start_q[0];
    assign tb_i2c_start_count_1    = i2c_start_q[1];

    // ------------------------------------------------------------------
    // OCCP target-up pad: the target drives, the controller senses.
    // Undriven resolves LOW (pulldown semantics) so the handshake reflects the
    // target rather than the testbench -- see the header note.
    // ------------------------------------------------------------------
    assign tb_gpio58_from_dut = u_dut.u_smc_wrapper.u_smc.core2pad_en_o[OccpTargetUpPad]
                                ? u_dut.u_smc_wrapper.u_smc.core2pad_o[OccpTargetUpPad]
                                : 1'b0;
    assign tb_gpio58_bus = tb_gpio58_from_dut;

    // ------------------------------------------------------------------
    // Per-instance pad buses. Only 27/28 (shared I3C0) and 58 (target-up) are
    // cross-driven; every other pad is that instance's own.
    // ------------------------------------------------------------------
    wire [smc_pkg::NumGpioWraps-1:0] dut_gpio_pad_io;
    wire [smc_pkg::NumGpioWraps-1:0] bfm_gpio_pad_io;

    logic [smc_pkg::NumGpioWraps-1:0] dut_pad_drive_en, dut_pad_drive_val;
    logic [smc_pkg::NumGpioWraps-1:0] bfm_pad_drive_en, bfm_pad_drive_val;

    always_comb begin
        dut_pad_drive_en  = '0;
        dut_pad_drive_val = '1;
        bfm_pad_drive_en  = '0;
        bfm_pad_drive_val = '1;

        for (int unsigned i = 0; i < smc_pkg::NumGpioWraps; i++) begin
            if (dut_gpio_ext_drive_en[i]) begin
                dut_pad_drive_en[i]  = 1'b1;
                dut_pad_drive_val[i] = dut_gpio_ext_drive_value[i];
            end
            if (bfm_gpio_ext_drive_en[i]) begin
                bfm_pad_drive_en[i]  = 1'b1;
                bfm_pad_drive_val[i] = bfm_gpio_ext_drive_value[i];
            end
        end

        // Shared I3C channels: always drive each channel's resolved wired-AND
        // value into both instances, so every input buffer sees the true bus
        // state for the channel the firmware happens to pick.
        for (int unsigned ch = 0; ch < NumSharedI3c; ch++) begin
            dut_pad_drive_en[SharedI3cSclPad[ch]]  = 1'b1;
            dut_pad_drive_val[SharedI3cSclPad[ch]] = i3c_scl_bus[ch];
            dut_pad_drive_en[SharedI3cSdaPad[ch]]  = 1'b1;
            dut_pad_drive_val[SharedI3cSdaPad[ch]] = i3c_sda_bus[ch];
            bfm_pad_drive_en[SharedI3cSclPad[ch]]  = 1'b1;
            bfm_pad_drive_val[SharedI3cSclPad[ch]] = i3c_scl_bus[ch];
            bfm_pad_drive_en[SharedI3cSdaPad[ch]]  = 1'b1;
            bfm_pad_drive_val[SharedI3cSdaPad[ch]] = i3c_sda_bus[ch];
        end

        // Shared I2C: one resolved value onto every participating pad of both
        // instances, so each controller's input buffer sees the same bus.
        for (int unsigned ch = 0; ch < NumTargetI2c; ch++) begin
            dut_pad_drive_en[TargetI2cSclPad[ch]]  = 1'b1;
            dut_pad_drive_val[TargetI2cSclPad[ch]] = i2c_scl_bus[ch];
            dut_pad_drive_en[TargetI2cSdaPad[ch]]  = 1'b1;
            dut_pad_drive_val[TargetI2cSdaPad[ch]] = i2c_sda_bus[ch];
            bfm_pad_drive_en[TargetI2cSclPad[ch]]  = 1'b1;
            bfm_pad_drive_val[TargetI2cSclPad[ch]] = i2c_scl_bus[ch];
            bfm_pad_drive_en[TargetI2cSdaPad[ch]]  = 1'b1;
            bfm_pad_drive_val[TargetI2cSdaPad[ch]] = i2c_sda_bus[ch];
        end

        // Target-up: the controller senses what the target drives, unless a
        // test is holding the pad itself. Guarded exactly like BOOT_STALL
        // below: unguarded, this assignment comes after the ext-override loop
        // above and silently wins, making set_gpio_override(..., 58, ...) dead
        // and turning the payload staging window into a race against the
        // controller firmware.
        if (!bfm_gpio_ext_drive_en[OccpTargetUpPad]) begin
            bfm_pad_drive_en[OccpTargetUpPad]  = 1'b1;
            bfm_pad_drive_val[OccpTargetUpPad] = tb_gpio58_bus;
        end

        // Boot stall, per instance, unless a test overrides the pad directly.
        if (!dut_gpio_ext_drive_en[BootStallPad]) begin
            dut_pad_drive_en[BootStallPad]  = 1'b1;
            dut_pad_drive_val[BootStallPad] = dut_boot_stall_hold;
        end
        if (!bfm_gpio_ext_drive_en[BootStallPad]) begin
            bfm_pad_drive_en[BootStallPad]  = 1'b1;
            bfm_pad_drive_val[BootStallPad] = bfm_boot_stall_hold;
        end
    end

    for (genvar i = 0; i < smc_pkg::NumGpioWraps; i++) begin : gen_pad_drive
        pullup u_dut_pu (dut_gpio_pad_io[i]);
        pullup u_bfm_pu (bfm_gpio_pad_io[i]);
        assign dut_gpio_pad_io[i] = dut_pad_drive_en[i] ? dut_pad_drive_val[i] : 1'bz;
        assign bfm_gpio_pad_io[i] = bfm_pad_drive_en[i] ? bfm_pad_drive_val[i] : 1'bz;
    end

    // ------------------------------------------------------------------
    // The two SMC instances.
    //
    // Every constant tie-off lives once, in smc_dual_inst at the bottom of
    // this file. Only the signals that differ between the controller and the
    // target are ports of that helper.
    // ------------------------------------------------------------------
    smc_dual_inst u_dut (
        .powergood_i          (powergood_i),
        .rst_cold_ni          (rst_cold_ni),
        .rst_cool_ni          (rst_cool_ni),
        .gpio_pad_io          (dut_gpio_pad_io),
        .sep_axi_in_req_i     (dut_sep_axi_req),
        .sep_axi_in_resp_o    (dut_sep_axi_resp),
        .output_axi_req_o     (dut_out_axi_req),
        .output_axi_resp_i    (dut_out_axi_resp),
        .chiplet_is_primary_i (dut_chiplet_is_primary),
        .lc_state_i           (dut_lc_state),
        .mem_repair_done_i    (dut_mem_repair_done),
        .mem_repair_success_i (dut_mem_repair_success),
        .mem_repair_abort_i   (dut_mem_repair_abort),
        .mbist_done_i         (dut_mbist_done),
        .mbist_pass_i         (dut_mbist_pass),
        .mbist_abort_i        (dut_mbist_abort),
        .powergood_stable_o   (dut_powergood_stable_o),
        .rst_primary_smc_clk_no (dut_rst_primary_smc_clk_no),
        .rst_cold_stable_ref_clk_no (dut_rst_cold_stable_ref_clk_no),
        .smc_fuse_sense_done_o (dut_fuse_sense_done_o),
        .smc_init_mem_done_o   (dut_init_mem_done_o),
        .smc_cluster_ded_seen_o        (dut_cluster_ded_seen_o),
        .smc_wdt_first_timeout_seen_o  (dut_wdt_first_timeout_seen_o),
        .smc_wdt_second_timeout_seen_o (dut_wdt_second_timeout_seen_o),
        .rom_read_count_o     (dut_rom_read_count),
        .scratch_write_count_o(dut_scratch_write_count),
        .scratch_read_count_o (dut_scratch_read_count)
    );

    smc_dual_inst u_bfm (
        .powergood_i          (powergood_i),
        .rst_cold_ni          (rst_cold_ni),
        .rst_cool_ni          (rst_cool_ni),
        .gpio_pad_io          (bfm_gpio_pad_io),
        .sep_axi_in_req_i     (bfm_sep_axi_req),
        .sep_axi_in_resp_o    (bfm_sep_axi_resp),
        .output_axi_req_o     (bfm_out_axi_req),
        .output_axi_resp_i    (bfm_out_axi_resp),
        .chiplet_is_primary_i (bfm_chiplet_is_primary),
        .lc_state_i           (bfm_lc_state),
        .mem_repair_done_i    (bfm_mem_repair_done),
        .mem_repair_success_i (bfm_mem_repair_success),
        .mem_repair_abort_i   (bfm_mem_repair_abort),
        .mbist_done_i         (bfm_mbist_done),
        .mbist_pass_i         (bfm_mbist_pass),
        .mbist_abort_i        (bfm_mbist_abort),
        .powergood_stable_o   (bfm_powergood_stable_o),
        .rst_primary_smc_clk_no (bfm_rst_primary_smc_clk_no),
        .rst_cold_stable_ref_clk_no (bfm_rst_cold_stable_ref_clk_no),
        .smc_fuse_sense_done_o (bfm_fuse_sense_done_o),
        .smc_init_mem_done_o   (bfm_init_mem_done_o),
        .smc_cluster_ded_seen_o        (bfm_cluster_ded_seen_o),
        .smc_wdt_first_timeout_seen_o  (bfm_wdt_first_timeout_seen_o),
        .smc_wdt_second_timeout_seen_o (bfm_wdt_second_timeout_seen_o),
        .rom_read_count_o     (bfm_rom_read_count)
    );

    assign clk_smc    = u_dut.u_smc_wrapper.clk_sys;
    assign clk_ref    = u_dut.u_smc_wrapper.clk_ref;
    assign clk_periph = u_dut.u_smc_wrapper.clk_periph;

    // Both instances' model oscillators follow the bench clock inputs (see the
    // single-instance half); the two run in lockstep, as one clock tree.
    assign u_dut.u_smc_wrapper.u_smc_ip_integration.u_pll_wrap.osc_ref_bench    = clk_ref_i;
    assign u_dut.u_smc_wrapper.u_smc_ip_integration.u_pll_wrap.osc_sys_bench    = clk_smc_i;
    assign u_dut.u_smc_wrapper.u_smc_ip_integration.u_pll_wrap.osc_periph_bench = clk_periph_i;
    assign u_bfm.u_smc_wrapper.u_smc_ip_integration.u_pll_wrap.osc_ref_bench    = clk_ref_i;
    assign u_bfm.u_smc_wrapper.u_smc_ip_integration.u_pll_wrap.osc_sys_bench    = clk_smc_i;
    assign u_bfm.u_smc_wrapper.u_smc_ip_integration.u_pll_wrap.osc_periph_bench = clk_periph_i;

    // ------------------------------------------------------------------
    // Firmware observability (scratch 0/1 and retired PC per instance).
    // ------------------------------------------------------------------
    assign dut_scratch2 = u_dut.u_smc_wrapper.u_smc.u_smc_cpu_wrapper.u_smc_cpu_ctrl_wrap.scratch_reg[2];
    assign bfm_scratch2 = u_bfm.u_smc_wrapper.u_smc.u_smc_cpu_wrapper.u_smc_cpu_ctrl_wrap.scratch_reg[2];
    assign dut_wb_pc0 =
        u_dut.u_smc_wrapper.u_smc.u_smc_cpu_wrapper.u_smc_cpu.wb_reg_pc_raw[0];
    assign bfm_wb_pc0 =
        u_bfm.u_smc_wrapper.u_smc.u_smc_cpu_wrapper.u_smc_cpu.wb_reg_pc_raw[0];

    // Hart 0 retirement record per instance, masked while that core is in reset.
    `define SMC_DUT_HART0_CSR u_dut.u_smc_wrapper.u_smc.u_smc_cpu_wrapper.u_smc_cpu.u_digital_top.tile_prci_domain.element_reset_domain_rockettile.core.csr
    `define SMC_BFM_HART0_CSR u_bfm.u_smc_wrapper.u_smc.u_smc_cpu_wrapper.u_smc_cpu.u_digital_top.tile_prci_domain.element_reset_domain_rockettile.core.csr
    assign dut_cpu_core_reset_n = u_dut.u_smc_wrapper.u_smc.u_smc_cpu_wrapper.core_reset_n[0];
    assign dut_cpu_trace_valid  = dut_cpu_core_reset_n ? `SMC_DUT_HART0_CSR.io_trace_0_valid : 1'b0;
    assign dut_cpu_trace_pc     = dut_cpu_core_reset_n ? `SMC_DUT_HART0_CSR.io_trace_0_iaddr : '0;
    assign dut_cpu_trace_insn   = dut_cpu_core_reset_n ? `SMC_DUT_HART0_CSR.io_trace_0_insn : '0;
    assign dut_cpu_trace_exc    = dut_cpu_core_reset_n ? `SMC_DUT_HART0_CSR.io_trace_0_exception : 1'b0;
    assign dut_cpu_trace_cause  = dut_cpu_core_reset_n ? `SMC_DUT_HART0_CSR.io_cause : '0;
    assign dut_cpu_trace_tval   = dut_cpu_core_reset_n ? `SMC_DUT_HART0_CSR.io_tval : '0;
    assign bfm_cpu_core_reset_n = u_bfm.u_smc_wrapper.u_smc.u_smc_cpu_wrapper.core_reset_n[0];
    assign bfm_cpu_trace_valid  = bfm_cpu_core_reset_n ? `SMC_BFM_HART0_CSR.io_trace_0_valid : 1'b0;
    assign bfm_cpu_trace_pc     = bfm_cpu_core_reset_n ? `SMC_BFM_HART0_CSR.io_trace_0_iaddr : '0;
    assign bfm_cpu_trace_insn   = bfm_cpu_core_reset_n ? `SMC_BFM_HART0_CSR.io_trace_0_insn : '0;
    assign bfm_cpu_trace_exc    = bfm_cpu_core_reset_n ? `SMC_BFM_HART0_CSR.io_trace_0_exception : 1'b0;
    assign bfm_cpu_trace_cause  = bfm_cpu_core_reset_n ? `SMC_BFM_HART0_CSR.io_cause : '0;
    assign bfm_cpu_trace_tval   = bfm_cpu_core_reset_n ? `SMC_BFM_HART0_CSR.io_tval : '0;
    `undef SMC_DUT_HART0_CSR
    `undef SMC_BFM_HART0_CSR

    // ------------------------------------------------------------------
    // Controller I3C TX-port snoop (see the port comment). Passive: it only
    // watches the AXI-Lite write handshake, and drives nothing into the DUT.
    // ------------------------------------------------------------------
    localparam logic [31:0] I3cTxPortOffset = 32'h0000_0088;

    logic [31:0] bfm_tx_count_q;
    logic [31:0] bfm_tx_words_q [8];
    logic        bfm_tx_hit;
    logic [31:0] bfm_aw_addr_q;

    // Count completed W-channel handshakes, not cycles where valid happens to
    // be high: AXI-Lite holds valid until ready, so counting cycles inflates
    // (or with a stalled channel, distorts) the total. The address comes from
    // the last accepted AW, since AW and W handshake independently.
    always_ff @(posedge clk_periph or negedge rst_cold_ni) begin
        if (!rst_cold_ni) begin
            bfm_aw_addr_q <= '0;
        end else if (u_bfm.u_smc_wrapper.u_smc.u_smc_peripherals
                         .axil_i3c_req_periph_clk.aw_valid &&
                     u_bfm.u_smc_wrapper.u_smc.u_smc_peripherals
                         .axil_i3c_resp_periph_clk.aw_ready) begin
            bfm_aw_addr_q <= u_bfm.u_smc_wrapper.u_smc.u_smc_peripherals
                                 .axil_i3c_req_periph_clk.aw.addr;
        end
    end

    assign bfm_tx_hit =
        u_bfm.u_smc_wrapper.u_smc.u_smc_peripherals.axil_i3c_req_periph_clk.w_valid &&
        u_bfm.u_smc_wrapper.u_smc.u_smc_peripherals.axil_i3c_resp_periph_clk.w_ready &&
        ((bfm_aw_addr_q & 32'h0000_0FFF) == I3cTxPortOffset);

    always_ff @(posedge clk_periph or negedge rst_cold_ni) begin
        if (!rst_cold_ni) begin
            bfm_tx_count_q <= '0;
            for (int unsigned i = 0; i < 8; i++) begin
                bfm_tx_words_q[i] <= '0;
            end
        end else if (bfm_tx_hit) begin
            if (bfm_tx_count_q < 8) begin
                bfm_tx_words_q[bfm_tx_count_q] <=
                    u_bfm.u_smc_wrapper.u_smc.u_smc_peripherals
                        .axil_i3c_req_periph_clk.w.data;
            end
            bfm_tx_count_q <= bfm_tx_count_q + 32'd1;
        end
    end

    assign tb_bfm_i3c_tx_count = bfm_tx_count_q;
    assign tb_bfm_i3c_tx_word_0 = bfm_tx_words_q[0];
    assign tb_bfm_i3c_tx_word_1 = bfm_tx_words_q[1];
    assign tb_bfm_i3c_tx_word_2 = bfm_tx_words_q[2];
    assign tb_bfm_i3c_tx_word_3 = bfm_tx_words_q[3];
    assign tb_bfm_i3c_tx_word_4 = bfm_tx_words_q[4];
    assign tb_bfm_i3c_tx_word_5 = bfm_tx_words_q[5];
    assign tb_bfm_i3c_tx_word_6 = bfm_tx_words_q[6];
    assign tb_bfm_i3c_tx_word_7 = bfm_tx_words_q[7];

    assign dual_present_o = 1'b1;

    // Scratch SRAM bank/entry decode. smc_scratch_map_pkg holds the one copy
    // of it and names its sources; see that file before changing anything here.
    localparam int unsigned ScratchNumBanks = chipyard_4core_mem_pkg::NumSramBanks;

    // ------------------------------------------------------------------
    // Target scratch peek (read-only; see the port comment).
    //
    // Same decode the image loader uses, then a per-bank mux. The bank
    // selector has to be a mux over constant generate indices, because a
    // hierarchical reference into a generate block needs a constant index.
    // ------------------------------------------------------------------
    logic [$clog2(ScratchNumBanks)-1:0] peek_bank;
    logic [$clog2(ScratchNumBanks)-1:0] bfm_peek_bank;
    logic [chipyard_4core_mem_pkg::Smc4coreScratchRamAddrWidth-1:0] bfm_peek_entry;
    logic [chipyard_4core_mem_pkg::Smc4coreScratchRamDataWidth-1:0]
        bfm_peek_bank_data [ScratchNumBanks];
    logic [chipyard_4core_mem_pkg::Smc4coreScratchRamDataWidth-1:0] bfm_peek_word;
    logic [chipyard_4core_mem_pkg::Smc4coreScratchRamAddrWidth-1:0] peek_entry;
    logic [chipyard_4core_mem_pkg::Smc4coreScratchRamDataWidth-1:0]
        peek_bank_data [ScratchNumBanks];
    logic [chipyard_4core_mem_pkg::Smc4coreScratchRamDataWidth-1:0] peek_word;

    always_comb begin
        peek_bank  = smc_scratch_map_pkg::smc_scratch_bank(
                         32'(tb_dut_scratch_peek_offset));
        peek_entry = smc_scratch_map_pkg::smc_scratch_entry(
                         32'(tb_dut_scratch_peek_offset));
    end

    // The CPU memory macros live inside smc_ip_integration, so the DV
    // collateral binds into it. One bind statement covers both instances. Dual
    // tests never inject ECC, so those inputs are tied off; the counters and
    // the image backdoors are what this build needs. Port expressions are
    // elaborated in smc_ip_integration's scope.
    bind smc_ip_integration smc_cpu_mem_dv u_smc_cpu_mem_dv (
        .clk_i                (clk_sys_o),
        .rst_ni               (rst_primary_smc_clk_ni),
        .rom_req_i            (rom_intf_req),
        .scratch_ram_req_i    (scratch_ram_intf_req),
        .l1_dcache_data_req_i (l1_dcache_data_intf_req),
        .ecc_inject_sbe_i     (1'b0),
        .ecc_inject_dbe_i     (1'b0),
        .ecc_poke_en_i        (1'b0),
        .ecc_poke_entry_i     (32'd0),
        .ecc_poke_mask_i      (2'd0)
    );

    for (genvar b = 0; b < ScratchNumBanks; b++) begin : gen_peek_bank
        assign peek_bank_data[b] =
            u_dut.u_smc_wrapper.u_smc_ip_integration.u_mems
                .gen_scratch_rams[b].u_mem.u_mem.mem[peek_entry];
    end

    always_comb begin
        bfm_peek_bank  = smc_scratch_map_pkg::smc_scratch_bank(
                             32'(tb_bfm_scratch_peek_offset));
        bfm_peek_entry = smc_scratch_map_pkg::smc_scratch_entry(
                             32'(tb_bfm_scratch_peek_offset));
    end

    for (genvar b = 0; b < ScratchNumBanks; b++) begin : gen_bfm_peek_bank
        assign bfm_peek_bank_data[b] =
            u_bfm.u_smc_wrapper.u_smc_ip_integration.u_mems
                .gen_scratch_rams[b].u_mem.u_mem.mem[bfm_peek_entry];
    end

    assign bfm_peek_word            = bfm_peek_bank_data[bfm_peek_bank];
    assign tb_bfm_scratch_peek_data = bfm_peek_word[63:0];
    assign tb_bfm_scratch_peek_ecc  = bfm_peek_word[71:64];

    assign peek_word = peek_bank_data[peek_bank];
    // Data bits and the Rocket SECDED bits, split out so the test can tell a
    // wrong value from a value that was never written (all-zero ECC on nonzero
    // data means nothing ever stored it through the real write path).
    assign tb_dut_scratch_peek_data = peek_word[63:0];
    assign tb_dut_scratch_peek_ecc  = peek_word[71:64];

    // ------------------------------------------------------------------
    // Controller ROM override.
    //
    // Both instances load the same +rom_bin64 / +rom_hex image through
    // OCAH4CORECluster_rom_ext's own #0.1 plusarg path, which cannot
    // distinguish them. +bfm_rom_hex re-loads u_bfm's array afterwards so the
    // controller runs the OCCP master image while the target keeps the
    // production ROM. Sequenced at #0.3, after both the rom_ext load (#0.1) and
    // smc_cpu_mem_dv's backdoor (#0.2), so this override always wins.
    // ------------------------------------------------------------------
    initial begin : bfm_rom_override
        string bfm_rom_path;
        int    bfm_rom_fd;
        #0.3;
        if ($value$plusargs("bfm_rom_hex=%s", bfm_rom_path)) begin
            bfm_rom_fd = $fopen(bfm_rom_path, "r");
            if (bfm_rom_fd != 0) begin
                $fclose(bfm_rom_fd);
                $readmemh(bfm_rom_path,
                          u_bfm.u_smc_wrapper.u_smc_ip_integration.u_mems.u_rom_mem.u_mem.mem);
                $display("[tb_top:dual] u_bfm ROM override (hex) %s", bfm_rom_path);
            end else begin
                $error("[tb_top:dual] missing +bfm_rom_hex image %s", bfm_rom_path);
            end
        end else if ($value$plusargs("bfm_rom_bin64=%s", bfm_rom_path)) begin
            bfm_rom_fd = $fopen(bfm_rom_path, "r");
            if (bfm_rom_fd != 0) begin
                $fclose(bfm_rom_fd);
                $readmemb(bfm_rom_path,
                          u_bfm.u_smc_wrapper.u_smc_ip_integration.u_mems.u_rom_mem.u_mem.mem);
                $display("[tb_top:dual] u_bfm ROM override (bin64) %s", bfm_rom_path);
            end else begin
                $error("[tb_top:dual] missing +bfm_rom_bin64 image %s", bfm_rom_path);
            end
        end else begin
            $display("[tb_top:dual] no +bfm_rom_hex/+bfm_rom_bin64: both instances run the same image");
        end
    end

`endif  // SMC_DUAL

    assign clk_smc_o    = clk_smc;
    assign clk_ref_o    = clk_ref;
    assign clk_periph_o = clk_periph;

`ifdef UVM
    // ------------------------------------------------------------------
    // SV-UVM harness (`--dut smc --framework uvm`): clocks, the shared-VIP
    // interface instances on the SEP_IN AXI4 ingress, quiescent tie-offs
    // for every other cocotb-driven stimulus pin, uvm_config_db
    // publication (u_output_axi_if on the SYS_OUT egress lives above, in
    // both shapes), and run_test(). Compiled only when the native uvm flow
    // defines UVM; the cocotb flow sees only the ported module above.
    // ------------------------------------------------------------------
    import uvm_pkg::*;

    smc_tb_if u_tb_if ();

    // The model free-runs under SV-UVM; the bench-side clock nets mirror it.
    assign clk_ref_i    = clk_ref;
    assign clk_smc_i    = clk_smc;
    assign clk_periph_i = clk_periph;

    // Power-good and the cold/cool reset pins are test-sequenced through
    // smc_tb_if; the reset-unit outputs and the fuse-sense / warm-domain
    // release observables are mirrored back for the sequences and the
    // scoreboard.
    assign powergood_i = u_tb_if.powergood;
    assign rst_cold_ni = u_tb_if.rst_cold_n;
    assign rst_cool_ni = u_tb_if.rst_cool_n;
    assign u_tb_if.powergood_stable          = powergood_stable_o;
    assign u_tb_if.rst_cold_stable_ref_clk_n = rst_cold_stable_ref_clk_no;
    assign u_tb_if.rst_primary_ref_clk_n     = rst_primary_ref_clk_no;
    assign u_tb_if.rst_primary_smc_clk_n     = rst_primary_smc_clk_no;
    assign u_tb_if.rst_wdt_smc_clk_n         = rst_wdt_smc_clk_no;
    assign u_tb_if.fuse_sense_done           = tb_fuse_sense_done;
    assign u_tb_if.fuse_reset_n              = tb_fuse_reset_n;
    assign u_tb_if.rst_warm_smc_clk_n        = tb_rst_warm_smc_clk_n;

    // Cold-reset assertion counter: the scoreboard predictors re-baseline
    // their CSR shadows on it.
    logic [31:0] cold_rst_assert_count = '0;
    always @(negedge rst_cold_ni) cold_rst_assert_count <= cold_rst_assert_count + 32'd1;
    assign u_tb_if.cold_rst_assert_count = cold_rst_assert_count;
    logic [31:0] cool_rst_assert_count = '0;
    always @(negedge rst_cool_ni) cool_rst_assert_count <= cool_rst_assert_count + 32'd1;
    assign u_tb_if.cool_rst_assert_count = cool_rst_assert_count;

    // SEP_IN AXI4 initiator: the shared ocah_axi_vip UVM master agent drives
    // the s_axi_* request side (the agent's driver procedurally drives the
    // request payloads and valids plus bready/rready on the master
    // interface, routed out to the DUT here) and the TB wires only the
    // DUT-driven response signals back in. Geometry (56/64/6) lives in the
    // master cfg; the interface uses the default maximum widths.
    ocah_axi_if u_sep_in_master_if (.aclk(clk_smc), .aresetn(rst_primary_smc_clk_no));
    assign s_axi_awid     = u_sep_in_master_if.awid[5:0];
    assign s_axi_awaddr   = u_sep_in_master_if.awaddr[55:0];
    assign s_axi_awlen    = u_sep_in_master_if.awlen;
    assign s_axi_awsize   = u_sep_in_master_if.awsize;
    assign s_axi_awburst  = u_sep_in_master_if.awburst;
    assign s_axi_awlock   = u_sep_in_master_if.awlock;
    assign s_axi_awcache  = u_sep_in_master_if.awcache;
    assign s_axi_awprot   = u_sep_in_master_if.awprot;
    assign s_axi_awqos    = u_sep_in_master_if.awqos;
    assign s_axi_awregion = u_sep_in_master_if.awregion;
    assign s_axi_awuser   = u_sep_in_master_if.awuser[11:0];
    assign s_axi_awvalid  = u_sep_in_master_if.awvalid;
    assign s_axi_wdata    = u_sep_in_master_if.wdata;
    assign s_axi_wstrb    = u_sep_in_master_if.wstrb;
    assign s_axi_wlast    = u_sep_in_master_if.wlast;
    assign s_axi_wuser    = u_sep_in_master_if.wuser[11:0];
    assign s_axi_wvalid   = u_sep_in_master_if.wvalid;
    assign s_axi_bready   = u_sep_in_master_if.bready;
    assign s_axi_arid     = u_sep_in_master_if.arid[5:0];
    assign s_axi_araddr   = u_sep_in_master_if.araddr[55:0];
    assign s_axi_arlen    = u_sep_in_master_if.arlen;
    assign s_axi_arsize   = u_sep_in_master_if.arsize;
    assign s_axi_arburst  = u_sep_in_master_if.arburst;
    assign s_axi_arlock   = u_sep_in_master_if.arlock;
    assign s_axi_arcache  = u_sep_in_master_if.arcache;
    assign s_axi_arprot   = u_sep_in_master_if.arprot;
    assign s_axi_arqos    = u_sep_in_master_if.arqos;
    assign s_axi_arregion = u_sep_in_master_if.arregion;
    assign s_axi_aruser   = u_sep_in_master_if.aruser[11:0];
    assign s_axi_arvalid  = u_sep_in_master_if.arvalid;
    assign s_axi_rready   = u_sep_in_master_if.rready;

    // Response side: DUT subordinate -> agent driver/monitor.
    assign u_sep_in_master_if.awready = s_axi_awready;
    assign u_sep_in_master_if.wready  = s_axi_wready;
    assign u_sep_in_master_if.bid     = 16'(s_axi_bid);
    assign u_sep_in_master_if.bresp   = s_axi_bresp;
    assign u_sep_in_master_if.buser   = 16'(s_axi_buser);
    assign u_sep_in_master_if.bvalid  = s_axi_bvalid;
    assign u_sep_in_master_if.arready = s_axi_arready;
    assign u_sep_in_master_if.rid     = 16'(s_axi_rid);
    assign u_sep_in_master_if.rdata   = s_axi_rdata;
    assign u_sep_in_master_if.rresp   = s_axi_rresp;
    assign u_sep_in_master_if.rlast   = s_axi_rlast;
    assign u_sep_in_master_if.ruser   = 16'(s_axi_ruser);
    assign u_sep_in_master_if.rvalid  = s_axi_rvalid;

    // The SEP_IN response holds are cocotb controls; the UVM shape keeps both
    // channels transparent.
    assign tb_sep_axi_b_hold = 1'b0;
    assign tb_sep_axi_r_hold = 1'b0;
    assign tb_sep_axi_r_drop = 1'b0;
    assign tb_sys_axi_r_drop = 1'b0;

    // Passive mirror of the SEP_IN bus for the shared-VIP monitor (the
    // smc_scoreboard predictors consume its item stream) and the protocol
    // SVA, wired from the DUT-facing flat nets only.
    ocah_axi_if u_sep_in_axi_if (.aclk(clk_smc), .aresetn(rst_primary_smc_clk_no));
    assign u_sep_in_axi_if.awid     = 16'(s_axi_awid);
    assign u_sep_in_axi_if.awaddr   = 64'(s_axi_awaddr);
    assign u_sep_in_axi_if.awlen    = s_axi_awlen;
    assign u_sep_in_axi_if.awsize   = s_axi_awsize;
    assign u_sep_in_axi_if.awburst  = s_axi_awburst;
    assign u_sep_in_axi_if.awlock   = s_axi_awlock;
    assign u_sep_in_axi_if.awcache  = s_axi_awcache;
    assign u_sep_in_axi_if.awprot   = s_axi_awprot;
    assign u_sep_in_axi_if.awqos    = s_axi_awqos;
    assign u_sep_in_axi_if.awregion = s_axi_awregion;
    assign u_sep_in_axi_if.awuser   = 16'(s_axi_awuser);
    assign u_sep_in_axi_if.awvalid  = s_axi_awvalid;
    assign u_sep_in_axi_if.awready  = s_axi_awready;
    assign u_sep_in_axi_if.wdata    = s_axi_wdata;
    assign u_sep_in_axi_if.wstrb    = s_axi_wstrb;
    assign u_sep_in_axi_if.wlast    = s_axi_wlast;
    assign u_sep_in_axi_if.wuser    = 16'(s_axi_wuser);
    assign u_sep_in_axi_if.wvalid   = s_axi_wvalid;
    assign u_sep_in_axi_if.wready   = s_axi_wready;
    assign u_sep_in_axi_if.bid      = 16'(s_axi_bid);
    assign u_sep_in_axi_if.bresp    = s_axi_bresp;
    assign u_sep_in_axi_if.buser    = 16'(s_axi_buser);
    assign u_sep_in_axi_if.bvalid   = s_axi_bvalid;
    assign u_sep_in_axi_if.bready   = s_axi_bready;
    assign u_sep_in_axi_if.arid     = 16'(s_axi_arid);
    assign u_sep_in_axi_if.araddr   = 64'(s_axi_araddr);
    assign u_sep_in_axi_if.arlen    = s_axi_arlen;
    assign u_sep_in_axi_if.arsize   = s_axi_arsize;
    assign u_sep_in_axi_if.arburst  = s_axi_arburst;
    assign u_sep_in_axi_if.arlock   = s_axi_arlock;
    assign u_sep_in_axi_if.arcache  = s_axi_arcache;
    assign u_sep_in_axi_if.arprot   = s_axi_arprot;
    assign u_sep_in_axi_if.arqos    = s_axi_arqos;
    assign u_sep_in_axi_if.arregion = s_axi_arregion;
    assign u_sep_in_axi_if.aruser   = 16'(s_axi_aruser);
    assign u_sep_in_axi_if.arvalid  = s_axi_arvalid;
    assign u_sep_in_axi_if.arready  = s_axi_arready;
    assign u_sep_in_axi_if.rid      = 16'(s_axi_rid);
    assign u_sep_in_axi_if.rdata    = s_axi_rdata;
    assign u_sep_in_axi_if.rresp    = s_axi_rresp;
    assign u_sep_in_axi_if.rlast    = s_axi_rlast;
    assign u_sep_in_axi_if.ruser    = 16'(s_axi_ruser);
    assign u_sep_in_axi_if.rvalid   = s_axi_rvalid;
    assign u_sep_in_axi_if.rready   = s_axi_rready;

    ocah_axi_sva #(
        .IS_LITE    (1'b0),
        .ADDR_WIDTH (56),
        .DATA_WIDTH (64),
        .ID_WIDTH   (6)
    ) u_sep_in_axi_sva (
        .aclk    (clk_smc),
        .aresetn (rst_primary_smc_clk_no),
        .en_i    (u_tb_if.axi_sva_en),
        .awid    (s_axi_awid),
        .awaddr  (s_axi_awaddr),
        .awlen   (s_axi_awlen),
        .awsize  (s_axi_awsize),
        .awburst (s_axi_awburst),
        .awlock  (s_axi_awlock),
        .awprot  (s_axi_awprot),
        .awvalid (s_axi_awvalid),
        .awready (s_axi_awready),
        .wdata   (s_axi_wdata),
        .wstrb   (s_axi_wstrb),
        .wlast   (s_axi_wlast),
        .wvalid  (s_axi_wvalid),
        .wready  (s_axi_wready),
        .bid     (s_axi_bid),
        .bresp   (s_axi_bresp),
        .bvalid  (s_axi_bvalid),
        .bready  (s_axi_bready),
        .arid    (s_axi_arid),
        .araddr  (s_axi_araddr),
        .arlen   (s_axi_arlen),
        .arsize  (s_axi_arsize),
        .arburst (s_axi_arburst),
        .arlock  (s_axi_arlock),
        .arprot  (s_axi_arprot),
        .arvalid (s_axi_arvalid),
        .arready (s_axi_arready),
        .rid     (s_axi_rid),
        .rdata   (s_axi_rdata),
        .rresp   (s_axi_rresp),
        .rlast   (s_axi_rlast),
        .rvalid  (s_axi_rvalid),
        .rready  (s_axi_rready)
    );

    // Clean-room JTAG protocol SVA on the CPU TAP pins. The SMC exports no
    // one-hot TAP state, so the state rules are off; the TAP reset pin is
    // active-high, and the TAP drives TDO whenever it is selected, so the
    // reset is inverted and the output enable is tied high.
    ocah_jtag_sva #(
        .EN_STATE_RULES(1'b0)
    ) u_cpu_jtag_sva (
        .tck         (tb_cpu_jtag_tck),
        .tms         (tb_cpu_jtag_tms),
        .tdi         (tb_cpu_jtag_tdi),
        .trst_n      (~tb_cpu_jtag_reset),
        .tdo         (tb_cpu_jtag_tdo),
        .tdo_oen     (1'b1),
        .en_i        (u_tb_if.jtag_sva_en),
        .tap_state_i ('0)
    );

    // ------------------------------------------------------------------
    // Quiescent tie-offs: every other cocotb-driven stimulus pin at the idle
    // value the cocotb smc_base_test bring-up sets. A scenario that needs
    // one of these pins promotes it into smc_tb_if; nothing here is driven
    // from class code.
    // ------------------------------------------------------------------

    // SYS_IN and JTAG AXI4 ingresses and the JTAG-side eFuse AXI-Lite master:
    // no initiator attached, request side idle.
    assign sys_axi_awid     = '0;
    assign sys_axi_awaddr   = '0;
    assign sys_axi_awlen    = '0;
    assign sys_axi_awsize   = '0;
    assign sys_axi_awburst  = '0;
    assign sys_axi_awlock   = 1'b0;
    assign sys_axi_awcache  = '0;
    assign sys_axi_awprot   = '0;
    assign sys_axi_awqos    = '0;
    assign sys_axi_awregion = '0;
    assign sys_axi_awuser   = '0;
    assign sys_axi_awvalid  = 1'b0;
    assign sys_axi_wdata    = '0;
    assign sys_axi_wstrb    = '0;
    assign sys_axi_wlast    = 1'b0;
    assign sys_axi_wuser    = '0;
    assign sys_axi_wvalid   = 1'b0;
    assign sys_axi_bready   = 1'b0;
    assign sys_axi_arid     = '0;
    assign sys_axi_araddr   = '0;
    assign sys_axi_arlen    = '0;
    assign sys_axi_arsize   = '0;
    assign sys_axi_arburst  = '0;
    assign sys_axi_arlock   = 1'b0;
    assign sys_axi_arcache  = '0;
    assign sys_axi_arprot   = '0;
    assign sys_axi_arqos    = '0;
    assign sys_axi_arregion = '0;
    assign sys_axi_aruser   = '0;
    assign sys_axi_arvalid  = 1'b0;
    assign sys_axi_rready   = 1'b0;
    assign tb_sys_axi_r_hold = 1'b0;

    assign jtag_axi_awid     = '0;
    assign jtag_axi_awaddr   = '0;
    assign jtag_axi_awlen    = '0;
    assign jtag_axi_awsize   = '0;
    assign jtag_axi_awburst  = '0;
    assign jtag_axi_awlock   = 1'b0;
    assign jtag_axi_awcache  = '0;
    assign jtag_axi_awprot   = '0;
    assign jtag_axi_awqos    = '0;
    assign jtag_axi_awregion = '0;
    assign jtag_axi_awuser   = '0;
    assign jtag_axi_awvalid  = 1'b0;
    assign jtag_axi_wdata    = '0;
    assign jtag_axi_wstrb    = '0;
    assign jtag_axi_wlast    = 1'b0;
    assign jtag_axi_wuser    = '0;
    assign jtag_axi_wvalid   = 1'b0;
    assign jtag_axi_bready   = 1'b0;
    assign jtag_axi_arid     = '0;
    assign jtag_axi_araddr   = '0;
    assign jtag_axi_arlen    = '0;
    assign jtag_axi_arsize   = '0;
    assign jtag_axi_arburst  = '0;
    assign jtag_axi_arlock   = 1'b0;
    assign jtag_axi_arcache  = '0;
    assign jtag_axi_arprot   = '0;
    assign jtag_axi_arqos    = '0;
    assign jtag_axi_arregion = '0;
    assign jtag_axi_aruser   = '0;
    assign jtag_axi_arvalid  = 1'b0;
    assign jtag_axi_rready   = 1'b0;

    assign ej_axi_awaddr  = '0;
    assign ej_axi_awprot  = '0;
    assign ej_axi_awvalid = 1'b0;
    assign ej_axi_wdata   = '0;
    assign ej_axi_wstrb   = '0;
    assign ej_axi_wvalid  = 1'b0;
    assign ej_axi_bready  = 1'b0;
    assign ej_axi_araddr  = '0;
    assign ej_axi_arprot  = '0;
    assign ej_axi_arvalid = 1'b0;
    assign ej_axi_rready  = 1'b0;

    // SYS_OUT responder control: no response hold.
    assign tb_output_axi_resp_hold = 1'b0;

    // DFT functional mode; open-drain I2C0/I3C0 lines released; CPU JTAG TAP
    // parked (TMS high, reset asserted); UART0 RX idle-high.
    assign tb_test_en_i        = 1'b0;
    assign tb_i2c0_scl_ext_low = 1'b0;
    assign tb_i2c0_sda_ext_low = 1'b0;
    assign tb_i3c0_scl_ext_low = 1'b0;
    assign tb_i3c0_sda_ext_low = 1'b0;
    assign tb_cpu_jtag_tck     = 1'b0;
    assign tb_cpu_jtag_tms     = 1'b1;
    assign tb_cpu_jtag_tdi     = 1'b0;
    assign tb_cpu_jtag_reset   = 1'b1;
    assign tb_uart0_rx_ext_drive = 1'b1;

    // Telemetry ATB receivers quiet with AFREADY high.
    assign tb_telemetry0_atdata  = '0;
    assign tb_telemetry0_atid    = '0;
    assign tb_telemetry0_atvalid = 1'b0;
    assign tb_telemetry0_afready = 1'b1;
    assign tb_telemetry1_atdata  = '0;
    assign tb_telemetry1_atid    = '0;
    assign tb_telemetry1_atvalid = 1'b0;
    assign tb_telemetry2_atdata  = '0;
    assign tb_telemetry2_atid    = '0;
    assign tb_telemetry2_atvalid = 1'b0;

    // SPI octal pads idle-safe: mux off, CS deasserted, OE/IE negated high.
    assign tb_spi_enable   = 1'b0;
    assign tb_spi_clk      = 1'b0;
    assign tb_spi_txd      = '0;
    assign tb_spi_cs_n     = 1'b1;
    assign tb_spi_cs_oe_n  = 1'b1;
    assign tb_spi_cs_ie_n  = 1'b1;
    assign tb_spi_clk_ie_n = 1'b1;
    assign tb_spi_clk_oe_n = 1'b1;
    assign tb_spi_dqs_ie_n = 1'b1;
    assign tb_spi_dqs_oe_n = 1'b1;
    assign tb_spi_dq_ie_n  = '1;
    assign tb_spi_dq_oe_n  = '1;
    assign tb_spi_miso_ext = 1'b0;

    // Boot-stall JTAG override off; SEP WDT reset released; PCIe FLR idle;
    // NDM reset requests idle; interrupt pins idle; straps zero; every
    // subsystem reports reset complete; JTAG reset override off; DFX aborts
    // clear.
    assign tb_boot_stall_jtag_ovrd_i = 1'b0;
    assign tb_boot_stall_jtag_val_i  = 1'b0;
    assign tb_sep_wdt_reset_n        = 1'b1;
    assign tb_cfg_flr_pf_active      = 1'b0;
    assign tb_ndmreset_request       = '0;
    assign tb_temp_interrupt_i       = 1'b0;
    assign tb_ext_interrupt_0_i      = 1'b0;
    assign tb_ss_reset_complete      = '1;
    assign tb_jtag_reset_ctrl        = '0;
    assign tb_mem_repair_abort       = 1'b0;
    assign tb_mbist_abort            = 1'b0;

    // Sideband: AVSBus sdata pull-up high, primary chiplet, OCTS secondary
    // inject idle-low; SEP mailbox interrupts idle; no GPIO external drive.
    assign tb_avs_sdata_ext          = 1'b1;
    assign tb_chiplet_is_primary     = 1'b1;
    assign tb_octs_sync_load_ext     = 1'b0;
    assign tb_octs_cnt_credit_ext    = 1'b0;
    assign tb_sep_mailbox_interrupts = '0;
    assign tb_gpio_ext_drive_en      = '0;
    assign tb_gpio_ext_drive_value   = '0;

    // CPU memory ECC injection and the DFD fault inject off.
    assign tb_cpu_ecc_inject_sbe   = 1'b0;
    assign tb_cpu_ecc_inject_dbe   = 1'b0;
    assign tb_cpu_ecc_inject_probe = 1'b0;
    assign tb_cpu_ecc_poke_en      = 1'b0;
    assign tb_cpu_ecc_poke_entry   = '0;
    assign tb_cpu_ecc_poke_mask    = '0;
    assign tb_dfd_fault_inject     = 1'b0;

    // Product lifecycle state idle: complementary TEST_DEV ({~0, 0}).
    assign tb_lc_state = {{smc_pkg::LcStateWidth{1'b1}}, {smc_pkg::LcStateWidth{1'b0}}};

    // Non-reusable test classes compile as part of this top (module scope).
    `include "smc_tests.sv"

    initial begin
        uvm_config_db#(virtual smc_tb_if)::set(null, "*", "tb_vif", u_tb_if);
        uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "sep_in_master_vif", u_sep_in_master_if);
        uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "sep_in_axi_vif", u_sep_in_axi_if);
        uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "sys_out_vif", u_output_axi_if);
        run_test();
    end
`endif

endmodule : smc_uvm_top

`ifdef SMC_DUAL
//-----------------------------------------------------------------------------
// One SMC instance with every constant tie-off applied.
//
// The dual configuration instantiates it twice. Each tie-off value matches the
// single-instance half of smc_uvm_top above, so a behavioural difference
// between the two configurations cannot come from a stray default. Only the
// ports below differ per instance.
//-----------------------------------------------------------------------------
module smc_dual_inst
    import smc_pkg::*;
(
    input  logic powergood_i,
    input  logic rst_cold_ni,
    input  logic rst_cool_ni,

    inout  wire [smc_pkg::NumGpioWraps-1:0] gpio_pad_io,

    input  smc_sep_in_56_64_6_12_axi_req_t   sep_axi_in_req_i,
    output smc_sep_in_56_64_6_12_axi_resp_t  sep_axi_in_resp_o,
    output smc_sys_out_56_64_8_12_axi_req_t  output_axi_req_o,
    input  smc_sys_out_56_64_8_12_axi_resp_t output_axi_resp_i,

    input  logic chiplet_is_primary_i,

    input  logic [2*smc_pkg::LcStateWidth-1:0] lc_state_i,

    input  logic mem_repair_done_i,
    input  logic mem_repair_success_i,
    input  logic mem_repair_abort_i,
    input  logic mbist_done_i,
    input  logic mbist_pass_i,
    input  logic mbist_abort_i,

    output logic        powergood_stable_o,
    output logic        rst_primary_smc_clk_no,
    // Gates the padring's strap-capture latches, so it is what decides when a
    // strap driven onto a pad is actually sampled. Deasserts later than
    // rst_cold_ni: smc_reset_ctrl deglitches cold reset and then extends it.
    output logic        rst_cold_stable_ref_clk_no,
    output logic        smc_fuse_sense_done_o,
    output logic        smc_init_mem_done_o,
    output logic        smc_cluster_ded_seen_o,
    output logic        smc_wdt_first_timeout_seen_o,
    output logic        smc_wdt_second_timeout_seen_o,
    output logic [31:0] rom_read_count_o,
    output logic [31:0] scratch_write_count_o,
    output logic [31:0] scratch_read_count_o
);

    logic clk_smc;
    logic clk_ref;
    logic clk_periph;

    // Idle inbound buses. Declared rather than inlined as '0 so the struct
    // types are explicit at the tie-off site.
    smc_sys_in_56_64_6_12_axi_req_t sys_axi_idle_req;
    smc_jtag_56_64_2_12_axi_req_t   jtag_axi_idle_req;
    smc_axil_32_32_req_t            axil_idle_req;
    smc_axil_32_32_resp_t           axil_idle_resp;

    assign sys_axi_idle_req  = '0;
    assign jtag_axi_idle_req = '0;
    assign axil_idle_req     = '0;
    // DTP CSR: no TB err_slv, matching the single-instance no-placeholder policy.
    assign axil_idle_resp    = '0;

    telemetry_receiver_pkg::telemetry_data_t
        [smc_config_pkg::NumTelemetryReceivers-1:0] telemetry_idle_data;
    telemetry_receiver_pkg::atb_id_t
        [smc_config_pkg::NumTelemetryReceivers-1:0] telemetry_idle_id;
    assign telemetry_idle_data = '0;
    assign telemetry_idle_id   = '0;

    // Fault outputs of this instance, latched sticky until cold reset. Read by
    // the dual leaves as dut_/bfm_*_seen_o on smc_uvm_top.
    logic cluster_ded;
    logic wdt_first_timeout;
    logic wdt_second_timeout;
    logic cluster_ded_seen_q;
    logic wdt_first_timeout_seen_q;
    logic wdt_second_timeout_seen_q;
    always_ff @(posedge clk_smc or negedge rst_cold_ni) begin
        if (!rst_cold_ni) begin
            cluster_ded_seen_q        <= 1'b0;
            wdt_first_timeout_seen_q  <= 1'b0;
            wdt_second_timeout_seen_q <= 1'b0;
        end else begin
            if (cluster_ded)        cluster_ded_seen_q        <= 1'b1;
            if (wdt_first_timeout)  wdt_first_timeout_seen_q  <= 1'b1;
            if (wdt_second_timeout) wdt_second_timeout_seen_q <= 1'b1;
        end
    end
    assign smc_cluster_ded_seen_o        = cluster_ded_seen_q;
    assign smc_wdt_first_timeout_seen_o  = wdt_first_timeout_seen_q;
    assign smc_wdt_second_timeout_seen_o = wdt_second_timeout_seen_q;

    // The I3C DAT/DCT/RLT table memories live inside smc_ip_integration, so
    // each of u_dut and u_bfm carries its own set. The OCCP flow depends on
    // that: the controller's ENTDAA writes its own DAT and the target's core
    // reads a different one.

    smc_wrapper u_smc_wrapper (
        .powergood_i                (powergood_i),
        .powergood_stable_o         (powergood_stable_o),
        .rst_cold_ni                (rst_cold_ni),
        .rst_cold_stable_ref_clk_no (rst_cold_stable_ref_clk_no),
        .rst_primary_ref_clk_no     (),
        .rst_primary_smc_clk_no     (rst_primary_smc_clk_no),
        .rst_wdt_smc_clk_no         (),
        .rst_primary_periph_clk_no  (),
        .sys_axi_in_req_i           (sys_axi_idle_req),
        .sys_axi_in_resp_o          (),
        .jtag_axi_in_req_i          (jtag_axi_idle_req),
        .jtag_axi_in_resp_o         (),
        .axil_smc_otp_jtag_req_i    (axil_idle_req),
        .axil_smc_otp_jtag_resp_o   (),
        .sep_axi_in_req_i           (sep_axi_in_req_i),
        .sep_axi_in_resp_o          (sep_axi_in_resp_o),
        .output_axi_req_o           (output_axi_req_o),
        .output_axi_resp_i          (output_axi_resp_i),
        .axil_dtp_csr_req_o         (),
        .axil_dtp_csr_resp_i        (axil_idle_resp),
        .shadow_regs_o              (),
        .lsio_interface_select_o    (),
        .gpio_pad_io                (gpio_pad_io),
        .rst_cool_n_from_pin_i      (rst_cool_ni),
        .spi_enable_i               (1'b0),
        .spi_clk_i                  (1'b0),
        .spi_txd_i                  ('0),
        .spi_cs_n_i                 (1'b1),
        .spi_cs_oe_n_i              (1'b1),
        .spi_cs_ie_n_i              (1'b1),
        .spi_clk_ie_n_i             (1'b1),
        .spi_clk_oe_n_i             (1'b1),
        .spi_dqs_ie_n_i             (1'b1),
        .spi_dqs_oe_n_i             (1'b1),
        .spi_dq_ie_n_i              ('1),
        .spi_dq_oe_n_i              ('1),
        .spi_rxd_o                  (),
        .spi_rxds_o                 (),
        .spi_mem_rebar_oepad_i      (1'b0),
        .spi_mem_rebar_opad_i       (1'b0),
        .spi_mem_rebar_iepad_i      (1'b0),
        .spi_mem_rebar_ipad_o       (),
        .clk_telemetry_i            (clk_smc),
        .rst_telemetry_ni           (rst_cold_ni),
        .telemetry_atdata_i         (telemetry_idle_data),
        .telemetry_atid_i           (telemetry_idle_id),
        .telemetry_atready_o        (),
        .telemetry_atvalid_i        ('0),
        .telemetry_afvalid_o        (),
        .telemetry_afready_i        ('1),
        .smc_cluster_ded_o          (cluster_ded),
        .smc_wdt_first_timeout_o    (wdt_first_timeout),
        .smc_wdt_second_timeout_o   (wdt_second_timeout),
        .smc_global_base_o          (),
        .smc_region_size_o          (),
        .smc_ext_interrupts_i       ('0),
        .sep_mailbox_interrupts_i   ('0),
        .sep_wdt_reset_n_i          (1'b1),
        .smc_fuse_sense_done_o      (smc_fuse_sense_done_o),
        .smc_fuse_reset_n_delayed_o (),
        .skip_mem_repair_o          (),
        .ext_boot_seq_done_i        (1'b1),
        // Tied low: the eFuse sense bypass is unreachable here;
        // docs/SMC_VPLAN.adoc Known Limitations "Bench tie-offs" carries the row.
        .sep_security_disable_i     (1'b0),
        .lc_state_i                 (lc_state_i),
        .lc_sigint_err_o            (),
        .smc_ndmreset_request_i     ('0),
        .smc_ndmreset_process_o     (),
        .smc_ext_mailbox_interrupts_o (),
        .cfg_flr_pf_active_i        (1'b0),
        .isolate_req_o              (),
        .ss_reset_complete_i        ('1),
        .ss_config_o                (),
        .sync_irq_o                 (),
        .smc_disable_sram_auto_init_i (1'b1),
        .smc_init_mem_done_o        (smc_init_mem_done_o),
        .chiplet_is_primary_i       (chiplet_is_primary_i),
        .timer_count_o              (),
        .boot_stall_jtag_ovrd_i     (1'b0),
        .boot_stall_jtag_val_i      (1'b0),
        .boot_stall_combined_o      (),
        .jtag_reset_ctrl_i          ('0),
        .cla_ext_action_custom_o    (),
        .xtrigger_ss_o              (),
        .xtrigger_ss_i              ('0),
        .tdr_dbg_ctrl_clock_stop_en_i          (1'b0),
        .tdr_dbg_ctrl_clocks_stopped_by_cla_o  (),
        .ext_debug_bus_i            ('0),
        .test_en_i                  (1'b0),
        .scan_rst_ni                (1'b1),
        // Driven per instance from the top. Idle is done/success/pass high and
        // abort low, because without an external BISR/MBIST agent the boot
        // sequencer waits forever if `done` stays low.
        .mem_repair_done_i          (mem_repair_done_i),
        .mem_repair_success_i       (mem_repair_success_i),
        .mem_repair_abort_i         (mem_repair_abort_i),
        .mbist_done_i               (mbist_done_i),
        .mbist_pass_i               (mbist_pass_i),
        .mbist_abort_i              (mbist_abort_i),
        .smc_cpu_jtag_TCK_i         (1'b0),
        .smc_cpu_jtag_TMS_i         (1'b1),
        .smc_cpu_jtag_TDI_i         (1'b0),
        .smc_cpu_jtag_TDO_data_o    (),
        .smc_cpu_jtag_reset_i       (1'b1),
        .smc_cpu_jtag_mfr_id_i      (11'h2AA),
        .smc_cpu_jtag_part_number_i (16'h0CA0),
        .smc_cpu_jtag_version_i     (4'h1),
        .gated_clk_periph_i3c_o     (),
        .gpio_interrupt_o           (),
        .uart_interrupt_o           (),
        .efuse_debug_bus_o          ()
    );

    assign clk_smc    = u_smc_wrapper.clk_sys;
    assign clk_ref    = u_smc_wrapper.clk_ref;
    assign clk_periph = u_smc_wrapper.clk_periph;

    // The CPU memory macros sit inside smc_ip_integration, so the counters come
    // from the DV collateral bound into it rather than from wrapper ports.
    assign rom_read_count_o =
        u_smc_wrapper.u_smc_ip_integration.u_smc_cpu_mem_dv.rom_read_count_q;
    assign scratch_read_count_o =
        u_smc_wrapper.u_smc_ip_integration.u_smc_cpu_mem_dv.scratch_ram_read_count_q;
    assign scratch_write_count_o =
        u_smc_wrapper.u_smc_ip_integration.u_smc_cpu_mem_dv.scratch_ram_write_count_q;

endmodule : smc_dual_inst
`endif  // SMC_DUAL
