// SPDX-License-Identifier: Apache-2.0
//
// DV-only compile-time STUB of sep_cpu (no VeeR EL2) for the no_cpu
// (Verilator and VCS) targets.
//
// The real sep_cpu (hw/sys/sep/rtl/sep_cpu.sv) instantiates el2_veer_wrapper (the full
// VeeR EL2 RISC-V core complex), which is heavy to elaborate/build and is not
// needed by the no_cpu testbench. Because the stub is the sole driver of the
// CPU's LSU master, it drives the LSU request net directly from the tb's
// assembled cocotb-AXI struct (sep_uvm_top.lsu_req_drive, an upward reference)
// and the tb reads back the LSU response net by hierarchical name
// (u_dut.u_sep_cpu.lsu_axi_resp). No `force` is used in the stub model -- the LSU
// request is single-driven, so it is driven, not forced.
//
// This stub removes el2_veer_wrapper, the IFU demux, the debug/DMI logic, and
// the LSU/IFU/DBG local-alias remappers, but faithfully reproduces the LSU AXI
// ROM/xbar demux + response mux VERBATIM from sep_cpu.sv so that the no_cpu LSU
// path behaves identically to the full CPU for fabric accesses. The
// `lsu_axi_req`/`lsu_axi_resp` internal nets exist with the same names/types as
// the real module so the tb probe hierarchy matches.
//
// Selection (sep_sim_cfg.toml target lsu_stub_all_live): that target sets
// +define+SEP_CPU_STUB, drops the real hw/sys/sep/rtl/sep_cpu.sv via per-target
// `exclude_files`, and appends THIS file via per-target `sources` (after the bender
// filelist, so all DUT packages are already declared). So this stub is the single
// `sep_cpu` definition for that target -- no -Wno-MODDUP/first-wins reliance. The
// `ifdef SEP_CPU_STUB wrapper keeps the file inert if it is ever compiled without
// the macro (e.g. the full-CPU `default` target, which does not list it).

`ifdef SEP_CPU_STUB

module sep_cpu
  import sep_pkg::*;
  import el2_pkg::*;
#(
  `include "el2_param.vh"
) (
  input logic clk_i,
  input logic rst_ni,
  input logic dbg_rstb_i,  // EL2 debugger reset

  input  logic jtag_tck_i,   // JTAG clk
  input  logic jtag_tms_i,   // JTAG TMS
  input  logic jtag_tdi_i,   // JTAG tdi
  input  logic jtag_trst_ni, // JTAG Reset
  output logic jtag_tdo_o,   // JTAG TDO
  output logic jtag_tdoEn_o, // JTAG Test Data Output enable

  // external MPC halt/run interface
  input  logic mpc_debug_halt_req_i, // Async halt request
  input  logic mpc_debug_run_req_i,  // Async run request
  input  logic mpc_reset_run_req_i,  // Run/halt after reset
  output logic mpc_debug_halt_ack_o, // Halt ack
  output logic mpc_debug_run_ack_o,  // Run ack
  output logic debug_brkpt_status_o, // debug breakpoint

  input  logic cpu_halt_req_i,      // Async halt req to CPU
  output logic cpu_halt_ack_o,      // core response to halt
  output logic cpu_halt_status_o,   // 1'b1 indicates core is halted
  output logic debug_mode_status_o, // Core to the PMU that core is in debug mode. When core is in debug mode, the PMU should refrain from sendng a halt or run request
  input  logic cpu_run_req_i,       // Async restart req to CPU
  output logic cpu_run_ack_o,       // Core response to run req

  // Excluding from coverage as usage is determined by the integrator of the VeeR core.
  // Note: VeeR reset bypass (scan_rst_n) not exposed on the el2_veer_wrapper boundary.
  input logic test_en_i,  // DFT test-enable

  // DMI port for uncore
  input  logic        dmi_core_enable,
  input  logic        dmi_uncore_enable,
  output logic        dmi_uncore_en,
  output logic        dmi_uncore_wr_en,
  output logic [6:0]  dmi_uncore_addr,
  output logic [31:0] dmi_uncore_wdata,
  input  logic [31:0] dmi_uncore_rdata,
  output logic        dmi_active,

  input logic [31:1] rst_vec,  // PC to jump to @ reset (unused: no CPU in the stub)
  input logic [31:1] nmi_vec,  // PC to jump to @ NMI
  input logic [31:1] jtag_id,

  // IRQs
  input logic                       nmi_int,
  input logic                       timer_int,
  input logic                       soft_int,
  input logic [sep_pkg::SEP_CPU_IRQ_WIDTH-1:0] extintsrc_req,

  output sep_cpu_trace_t sep_cpu_trace,

  output logic iccm_ecc_single_error,
  output logic iccm_ecc_double_error,
  output logic dccm_ecc_single_error,
  output logic dccm_ecc_double_error,

  output logic dec_tlu_perfcnt0, // toggles when slot0 perf counter 0 has an event inc
  output logic dec_tlu_perfcnt1,
  output logic dec_tlu_perfcnt2,
  output logic dec_tlu_perfcnt3,

  // Unconditional, matching sep_cpu: the port footprint does not depend on
  // the lockstep build define.
  input  sep_pkg::sep_lockstep_ctrl_t   lockstep_ctrl_i,
  output sep_pkg::sep_lockstep_status_t lockstep_status_o,

  // TCM (ICCM/DCCM) memory interface - routed to sep_wrapper for macro instantiation
  output sep_cpu_tcm_req_t sep_cpu_tcm_req_o,
  input  sep_cpu_tcm_rsp_t sep_cpu_tcm_rsp_i,

  // AXI interfaces (IFU split into ROM and SRAM via internal demux)
  output sep_32_64_3_12_axi_req_t      ifu_rom_axi_req_o,
  input  sep_32_64_3_12_axi_resp_t     ifu_rom_axi_resp_i,

  output sep_32_64_3_12_axi_req_t      ifu_sram_axi_req_o,
  input  sep_32_64_3_12_axi_resp_t     ifu_sram_axi_resp_i,

  output sep_32_64_3_12_axi_req_t      lsu_rom_axi_req_o,
  input  sep_32_64_3_12_axi_resp_t     lsu_rom_axi_resp_i,

  output sep_32_64_3_12_axi_req_t      lsu_xbar_axi_req_o,
  input  sep_32_64_3_12_axi_resp_t     lsu_xbar_axi_resp_i,

  output sep_32_64_3_12_axi_req_t      dbg_axi_req_o,
  input  sep_32_64_3_12_axi_resp_t     dbg_axi_resp_i,

  input  sep_32_64_6_12_axi_req_t      cpu_tcm_axi_req_i,
  output sep_32_64_6_12_axi_resp_t     cpu_tcm_axi_resp_o,

  input  logic [31:0]                 sep_local_base_addr_i,
  input  logic [31:0]                 sep_region_size_i   // unused: alias remap lives in the real CPU wrapper
);

  // -------------------------------------------------------------------------
  // LSU intermediate nets referenced by the no_cpu tb via hierarchical name.
  // Same names/types as the real sep_cpu so force/probe hierarchy is identical.
  // -------------------------------------------------------------------------
  sep_32_64_3_12_axi_req_t  lsu_axi_req;   // driven below from the tb cocotb master
  sep_32_64_3_12_axi_resp_t lsu_axi_resp;  // tb reads this net; driven by demux below

  // The stub is the SOLE driver of the LSU master (no VeeR core), so the
  // request is driven from the tb's assembled cocotb-AXI struct through an
  // upward reference and lsu_axi_req stays single-driven; Verilator cannot
  // force a whole request struct.
  // (Do NOT assign lsu_axi_resp - it is driven by the LSU demux below.)
  assign lsu_axi_req = sep_uvm_top.lsu_req_drive;

  ///////////////////
  // LSU AXI Demux //  (reproduced VERBATIM from hw/sys/sep/rtl/sep_cpu.sv)
  ///////////////////

  sep_32_64_3_12_axi_req_t  [SEP_LSU_DEMUX_NUM_PORTS-1:0] lsu_demux_req;
  sep_32_64_3_12_axi_resp_t [SEP_LSU_DEMUX_NUM_PORTS-1:0] lsu_demux_resp;
  sep_lsu_demux_port_t lsu_aw_select, lsu_ar_select;

  always_comb begin
    if ((lsu_axi_req.aw.addr >= och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_BOOT_ROM_BASE_ADDR) && (lsu_axi_req.aw.addr < och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_BOOT_ROM_BASE_ADDR + och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_BOOT_ROM_SIZE)) begin
      lsu_aw_select = SEP_LSU_DEMUX_PORT_ROM;
    end else begin
      lsu_aw_select = SEP_LSU_DEMUX_PORT_XBAR;
    end

    if ((lsu_axi_req.ar.addr >= och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_BOOT_ROM_BASE_ADDR) && (lsu_axi_req.ar.addr < och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_BOOT_ROM_BASE_ADDR + och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_BOOT_ROM_SIZE)) begin
      lsu_ar_select = SEP_LSU_DEMUX_PORT_ROM;
    end else begin
      lsu_ar_select = SEP_LSU_DEMUX_PORT_XBAR;
    end
  end

  axi_demux #(
    .AxiIdWidth  (SEP_32_64_3_12_ID_WIDTH),
    .AtopSupport (1'b0),
    .aw_chan_t   (sep_32_64_3_12_axi_aw_chan_t),
    .w_chan_t    (sep_32_64_3_12_axi_w_chan_t),
    .b_chan_t    (sep_32_64_3_12_axi_b_chan_t),
    .ar_chan_t   (sep_32_64_3_12_axi_ar_chan_t),
    .r_chan_t    (sep_32_64_3_12_axi_r_chan_t),
    .axi_req_t   (sep_32_64_3_12_axi_req_t),
    .axi_resp_t  (sep_32_64_3_12_axi_resp_t),
    .NoMstPorts  (SEP_LSU_DEMUX_NUM_PORTS),
    .MaxTrans    (4),
    .AxiLookBits (SEP_32_64_3_12_ID_WIDTH),
    .UniqueIds   (1'b0),
    .SpillAw     (1'b0),
    .SpillW      (1'b0),
    .SpillB      (1'b0),
    .SpillAr     (1'b0),
    .SpillR      (1'b0),
    .SelHashIds  (1'b0)
  ) u_lsu_axi_demux (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .test_i          (test_en_i),
    .slv_req_i       (lsu_axi_req),
    .slv_aw_select_i (lsu_aw_select),
    .slv_ar_select_i (lsu_ar_select),
    .sel_hash_i      ('0),
    .slv_resp_o      (lsu_axi_resp),
    .mst_reqs_o      (lsu_demux_req),
    .mst_resps_i     (lsu_demux_resp)
  );

  // Connect demux outputs to module ports
  assign lsu_rom_axi_req_o                      = lsu_demux_req[SEP_LSU_DEMUX_PORT_ROM];
  assign lsu_demux_resp[SEP_LSU_DEMUX_PORT_ROM] = lsu_rom_axi_resp_i;

  assign lsu_xbar_axi_req_o                      = lsu_demux_req[SEP_LSU_DEMUX_PORT_XBAR];
  assign lsu_demux_resp[SEP_LSU_DEMUX_PORT_XBAR] = lsu_xbar_axi_resp_i;

  // -------------------------------------------------------------------------
  // Tie off all OTHER output ports to benign idle values (no VeeR core).
  // -------------------------------------------------------------------------
  // JTAG
  assign jtag_tdo_o          = 1'b0;
  assign jtag_tdoEn_o        = 1'b0;

  // MPC halt/run + debug status
  assign mpc_debug_halt_ack_o = 1'b0;
  assign mpc_debug_run_ack_o  = 1'b0;
  assign debug_brkpt_status_o = 1'b0;

  // CPU halt/run handshake + debug mode
  assign cpu_halt_ack_o      = 1'b0;
  assign cpu_halt_status_o   = 1'b0;
  assign debug_mode_status_o = 1'b0;
  assign cpu_run_ack_o       = 1'b0;

  // DMI uncore port
  assign dmi_uncore_en       = 1'b0;
  assign dmi_uncore_wr_en    = 1'b0;
  assign dmi_uncore_addr     = '0;
  assign dmi_uncore_wdata    = '0;
  assign dmi_active          = 1'b0;

  // Trace
  assign sep_cpu_trace       = '0;

  // ECC error status
  assign iccm_ecc_single_error = 1'b0;
  assign iccm_ecc_double_error = 1'b0;
  assign dccm_ecc_single_error = 1'b0;
  assign dccm_ecc_double_error = 1'b0;

  // Perf counters
  assign dec_tlu_perfcnt0    = 1'b0;
  assign dec_tlu_perfcnt1    = 1'b0;
  assign dec_tlu_perfcnt2    = 1'b0;
  assign dec_tlu_perfcnt3    = 1'b0;

  assign lockstep_status_o = '0;

  logic unused_lockstep_ctrl;
  assign unused_lockstep_ctrl = |lockstep_ctrl_i;

  // TCM (ICCM/DCCM) request to memory macros - idle (no core)
  assign sep_cpu_tcm_req_o   = '0;

  // IFU AXI masters - idle (IFU demux not reproduced in the stub)
  assign ifu_rom_axi_req_o   = '0;
  assign ifu_sram_axi_req_o  = '0;

  // DBG/SB AXI master - idle (debug/SB path not reproduced in the stub)
  assign dbg_axi_req_o       = '0;

  // DMA/TCM AXI slave response - idle (no core consuming the DMA channel)
  assign cpu_tcm_axi_resp_o  = '0;

endmodule

`endif  // SEP_CPU_STUB
