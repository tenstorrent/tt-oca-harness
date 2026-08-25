// SPDX-License-Identifier: Apache-2.0
//
// DTP (Debug & Test Ports) open-source testbench top, shared between the
// cocotb (PyUVM) and SystemVerilog UVM flows. ONE module, two shapes:
//
//   * default (cocotb, `--dut dtp`): the module exposes the full pin-level
//     port list below and cocotb drives/samples the toplevel ports.
//   * `UVM` (SV-UVM, `--dut dtp --framework uvm`): the port list is replaced by
//     internal TB signals, and the harness block at the end of the module
//     adds the clock, ocah_jtag_if/dtp_tb_if instances, quiescent tie-offs,
//     and run_test(). Test classes are compiled via `include "dtp_tests.sv".
//
// Exposes the DTP DUT's primary JTAG TAP at pin level so the TB BFM can
// drive it, plus system clock/reset. The JTAG TAP FSM lives *inside* `dtp`
// (jtag_tap_ctrlr in jtag_intf_unit), so the client port is the decoded
// {tms,trst_n,tck} struct plus tdi/tdo -- effectively raw JTAG pins.
//
// This first bring-up top is JTAG-only: the STAP/iJTAG scan chains are
// looped back (scan_in = scan_out), the cross-trigger (CTM/CTP) and clock-stop
// inputs are tied off, and the JTAG2AXI manager response channels are tied
// idle. The JTAG2AXI functional path uses cocotb AXI memory BFMs on flattened
// struct <-> signal adapters.

`timescale 1ps/1fs

module dtp_uvm_top
    import prim_jtag_pkg::*;
    import jtag_tap_pkg::*;
    import jtag_inst_reg_pkg::*;
    import dtp_pkg::*;
`ifndef UVM
(
    // System clock and reset (driven by cocotb)
    input  wire logic clk_i,
    input  wire logic rst_n_i,
    input  wire logic pwr_on_rst_ni,

    // Primary JTAG TAP pins (driven/sampled by cocotb)
    input  wire logic jtag_tck,
    input  wire logic jtag_tms,
    input  wire logic jtag_trst,   // active-low TAP reset
    input  wire logic jtag_tdi,
    output logic      jtag_tdo,
    output logic      jtag_tdo_oen,

    // TAP state observation for IEEE 1149.1 FSM checks
    output tap_state_e                jtag_ptap_state,
    output jtag_instruction_decoded_e jtag_ptap_inst_decoded,

    // Flattened scan-control observables for DTP-local scan models/checkers.
    output logic jtag_bsr_select,
    output logic jtag_bsr_shift_en,
    output logic jtag_bsr_capture_en,
    output logic jtag_bsr_update_en,
    output logic jtag_ijtag_select,
    output logic jtag_ijtag_shift_en,
    output logic jtag_ijtag_capture_en,
    output logic jtag_ijtag_update_en,
    output logic jtag_dft_secure_select,
    output logic jtag_dft_secure_shift_en,
    output logic jtag_dft_secure_capture_en,
    output logic jtag_dft_secure_update_en,
    output logic jtag_dft_select,
    output logic jtag_dft_shift_en,
    output logic jtag_dft_capture_en,
    output logic jtag_dft_update_en,
    output logic jtag_dfd_select,
    output logic jtag_dfd_shift_en,
    output logic jtag_dfd_capture_en,
    output logic jtag_dfd_update_en,
    output logic jtag_stap_host_select,
    output logic jtag_stap_host_shift_en,
    output logic jtag_stap_host_capture_en,
    output logic jtag_stap_host_update_en,
    output logic jtag_stap_io_tms,
    output logic jtag_stap_io_tck,
    output logic jtag_stap_io_trst_n,
    output logic jtag_stap_io_tdo_oen,
    output logic jtag_stap_smc_tms,
    output logic jtag_stap_smc_tck,
    output logic jtag_stap_smc_trst_n,
    output logic jtag_stap_smc_tdo_oen,
    output logic jtag_stap_sep_tms,
    output logic jtag_stap_sep_tck,
    output logic jtag_stap_sep_trst_n,
    output logic jtag_stap_sep_tdo_oen,
    output logic jtag_stap_extra0_tms,
    output logic jtag_stap_extra0_tck,
    output logic jtag_stap_extra0_trst_n,
    output logic jtag_stap_extra0_tdo_oen,

    // DEBUG_CONTROL / IC_RESET observables and CLA clock-stop stimulus.
    input  wire logic [DEFAULT_NUM_CLK_STOP_REQ-1:0] xtrig_clk_stop_req,
    output logic stop_clks,
    output logic cla_clock_stop_en,
    output logic jtag_boot_stall_ovrd,
    output logic jtag_boot_stall,
    output logic jtag_ic_reset_smc_ovrd,
    output logic jtag_ic_reset_smc_ctrl_n,
    output logic jtag_ic_reset_sep_ovrd,
    output logic jtag_ic_reset_sep_ctrl_n,
    output logic jtag_ic_reset_ext_ovrd,
    output logic jtag_ic_reset_ext_ctrl_n,

    // Lifecycle debug-disable stimulus: the eleven pre-resolved active-high
    // disables of sep_lifecycle_ctrl_pkg::dbg_disable_t, one scalar per field
    // (1 = interface disabled). Packed unchanged into DTP's dbg_disable_i.
    input  wire logic dbg_disable_stap_io,
    input  wire logic dbg_disable_stap_smc,
    input  wire logic dbg_disable_stap_sep,
    input  wire logic dbg_disable_stap_extra,
    input  wire logic dbg_disable_stap_host,
    input  wire logic dbg_disable_dft_secure,
    input  wire logic dbg_disable_dft_nonsecure,
    input  wire logic dbg_disable_dfd,
    input  wire logic dbg_disable_smc_jtag2axi,
    input  wire logic dbg_disable_smc_otp_jtag2axi,
    input  wire logic dbg_disable_sep_otp_jtag2axi,

    // SMC AXI request-valid pulse counters for no-activity security checks.
    output logic [31:0] smc_axi_awvalid_count,
    output logic [31:0] smc_axi_wvalid_count,
    output logic [31:0] smc_axi_arvalid_count,

    // OTP AXI-Lite request-valid pulse counters for no-activity checks.
    output logic [31:0] smc_otp_axil_awvalid_count,
    output logic [31:0] smc_otp_axil_wvalid_count,
    output logic [31:0] smc_otp_axil_arvalid_count,
    output logic [31:0] sep_otp_axil_awvalid_count,
    output logic [31:0] sep_otp_axil_wvalid_count,
    output logic [31:0] sep_otp_axil_arvalid_count,

    // SMC OTP AXI-Lite manager flattened for cocotb AxiLiteRam.
    output logic [31:0] smc_otp_axil_awaddr,
    output logic [2:0]  smc_otp_axil_awprot,
    output logic        smc_otp_axil_awvalid,
    input  wire logic   smc_otp_axil_awready,
    output logic [31:0] smc_otp_axil_wdata,
    output logic [3:0]  smc_otp_axil_wstrb,
    output logic        smc_otp_axil_wvalid,
    input  wire logic   smc_otp_axil_wready,
    input  wire logic [1:0] smc_otp_axil_bresp,
    input  wire logic   smc_otp_axil_bvalid,
    output logic        smc_otp_axil_bready,
    output logic [31:0] smc_otp_axil_araddr,
    output logic [2:0]  smc_otp_axil_arprot,
    output logic        smc_otp_axil_arvalid,
    input  wire logic   smc_otp_axil_arready,
    input  wire logic [31:0] smc_otp_axil_rdata,
    input  wire logic [1:0] smc_otp_axil_rresp,
    input  wire logic   smc_otp_axil_rvalid,
    output logic        smc_otp_axil_rready,

    // SEP OTP AXI-Lite manager flattened for cocotb AxiLiteRam.
    output logic [31:0] sep_otp_axil_awaddr,
    output logic [2:0]  sep_otp_axil_awprot,
    output logic        sep_otp_axil_awvalid,
    input  wire logic   sep_otp_axil_awready,
    output logic [31:0] sep_otp_axil_wdata,
    output logic [3:0]  sep_otp_axil_wstrb,
    output logic        sep_otp_axil_wvalid,
    input  wire logic   sep_otp_axil_wready,
    input  wire logic [1:0] sep_otp_axil_bresp,
    input  wire logic   sep_otp_axil_bvalid,
    output logic        sep_otp_axil_bready,
    output logic [31:0] sep_otp_axil_araddr,
    output logic [2:0]  sep_otp_axil_arprot,
    output logic        sep_otp_axil_arvalid,
    input  wire logic   sep_otp_axil_arready,
    input  wire logic [31:0] sep_otp_axil_rdata,
    input  wire logic [1:0] sep_otp_axil_rresp,
    input  wire logic   sep_otp_axil_rvalid,
    output logic        sep_otp_axil_rready,

    // XTRIG AXI-Lite subordinate flattened for cocotb-driven CSR access.
    input  wire logic [31:0] xtrig_axil_awaddr,
    input  wire logic [2:0]  xtrig_axil_awprot,
    input  wire logic        xtrig_axil_awvalid,
    output logic             xtrig_axil_awready,
    input  wire logic [31:0] xtrig_axil_wdata,
    input  wire logic [3:0]  xtrig_axil_wstrb,
    input  wire logic        xtrig_axil_wvalid,
    output logic             xtrig_axil_wready,
    output logic [1:0]       xtrig_axil_bresp,
    output logic             xtrig_axil_bvalid,
    input  wire logic        xtrig_axil_bready,
    input  wire logic [31:0] xtrig_axil_araddr,
    input  wire logic [2:0]  xtrig_axil_arprot,
    input  wire logic        xtrig_axil_arvalid,
    output logic             xtrig_axil_arready,
    output logic [31:0]      xtrig_axil_rdata,
    output logic [1:0]       xtrig_axil_rresp,
    output logic             xtrig_axil_rvalid,
    input  wire logic        xtrig_axil_rready,
    output logic [31:0]      xtrig_axil_awvalid_count,
    output logic [31:0]      xtrig_axil_wvalid_count,
    output logic [31:0]      xtrig_axil_arvalid_count,

    // XTRIG CTM and CTP GPIO stimulus/observables.
    output logic [DEFAULT_NUM_INT_CT-1:0] xtrig_ctm_src_req,
    input  wire logic [DEFAULT_NUM_INT_CT-1:0] xtrig_ctm_src_ack,
    input  wire logic [DEFAULT_NUM_INT_CT-1:0] xtrig_ctm_dst_req,
    output logic [DEFAULT_NUM_INT_CT-1:0] xtrig_ctm_dst_ack,
    output logic [DEFAULT_NUM_CTP-1:0] xtrig_ctp_req_out_dout,
    output logic [DEFAULT_NUM_CTP-1:0] xtrig_ctp_req_out_dout_en,
    input  wire logic [DEFAULT_NUM_CTP-1:0] xtrig_ctp_req_out_din,
    output logic [DEFAULT_NUM_CTP-1:0] xtrig_ctp_req_out_din_en,
    output logic [DEFAULT_NUM_CTP-1:0] xtrig_ctp_req_in_dout,
    output logic [DEFAULT_NUM_CTP-1:0] xtrig_ctp_req_in_dout_en,
    input  wire logic [DEFAULT_NUM_CTP-1:0] xtrig_ctp_req_in_din,
    output logic [DEFAULT_NUM_CTP-1:0] xtrig_ctp_req_in_din_en,
    output logic [DEFAULT_NUM_CTP-1:0] xtrig_ctp_ack_in_dout,
    output logic [DEFAULT_NUM_CTP-1:0] xtrig_ctp_ack_in_dout_en,
    input  wire logic [DEFAULT_NUM_CTP-1:0] xtrig_ctp_ack_in_din,
    output logic [DEFAULT_NUM_CTP-1:0] xtrig_ctp_ack_in_din_en,
    output logic [DEFAULT_NUM_CTP-1:0] xtrig_ctp_ack_out_dout,
    output logic [DEFAULT_NUM_CTP-1:0] xtrig_ctp_ack_out_dout_en,
    input  wire logic [DEFAULT_NUM_CTP-1:0] xtrig_ctp_ack_out_din,
    output logic [DEFAULT_NUM_CTP-1:0] xtrig_ctp_ack_out_din_en
);
`else
;
    // ------------------------------------------------------------------
    // SV-UVM shape: the cocotb port list above becomes internal TB signals,
    // driven by the harness block at the end of this module. Keep this list
    // in lockstep with the port list — same names, same widths.
    // ------------------------------------------------------------------
    // System clock and reset (harness-generated clock, test-sequenced resets)
    logic clk_i;
    logic rst_n_i;
    logic pwr_on_rst_ni;

    // Primary JTAG TAP pins (driven/sampled via ocah_jtag_if)
    logic jtag_tck;
    logic jtag_tms;
    logic jtag_trst;
    logic jtag_tdi;
    logic jtag_tdo;
    logic jtag_tdo_oen;

    // TAP state observation (exported via dtp_tb_if)
    tap_state_e                jtag_ptap_state;
    jtag_instruction_decoded_e jtag_ptap_inst_decoded;

    // Flattened scan-control observables (unused by the UVM smoke)
    logic jtag_bsr_select, jtag_bsr_shift_en, jtag_bsr_capture_en, jtag_bsr_update_en;
    logic jtag_ijtag_select, jtag_ijtag_shift_en, jtag_ijtag_capture_en, jtag_ijtag_update_en;
    logic jtag_dft_secure_select, jtag_dft_secure_shift_en;
    logic jtag_dft_secure_capture_en, jtag_dft_secure_update_en;
    logic jtag_dft_select, jtag_dft_shift_en, jtag_dft_capture_en, jtag_dft_update_en;
    logic jtag_dfd_select, jtag_dfd_shift_en, jtag_dfd_capture_en, jtag_dfd_update_en;
    logic jtag_stap_host_select, jtag_stap_host_shift_en;
    logic jtag_stap_host_capture_en, jtag_stap_host_update_en;
    logic jtag_stap_io_tms, jtag_stap_io_tck, jtag_stap_io_trst_n, jtag_stap_io_tdo_oen;
    logic jtag_stap_smc_tms, jtag_stap_smc_tck, jtag_stap_smc_trst_n, jtag_stap_smc_tdo_oen;
    logic jtag_stap_sep_tms, jtag_stap_sep_tck, jtag_stap_sep_trst_n, jtag_stap_sep_tdo_oen;
    logic jtag_stap_extra0_tms, jtag_stap_extra0_tck;
    logic jtag_stap_extra0_trst_n, jtag_stap_extra0_tdo_oen;

    // DEBUG_CONTROL / IC_RESET observables and CLA clock-stop stimulus
    logic [DEFAULT_NUM_CLK_STOP_REQ-1:0] xtrig_clk_stop_req;
    logic stop_clks;
    logic cla_clock_stop_en;
    logic jtag_boot_stall_ovrd, jtag_boot_stall;
    logic jtag_ic_reset_smc_ovrd, jtag_ic_reset_smc_ctrl_n;
    logic jtag_ic_reset_sep_ovrd, jtag_ic_reset_sep_ctrl_n;
    logic jtag_ic_reset_ext_ovrd, jtag_ic_reset_ext_ctrl_n;

    // Lifecycle debug-disable stimulus: the UVM harness connects the typed
    // dtp_tb_if.dbg_disable struct straight to the DUT, so the per-field
    // cocotb scalars have no UVM-shape counterparts.

    // Request-valid pulse counters
    logic [31:0] smc_axi_awvalid_count, smc_axi_wvalid_count, smc_axi_arvalid_count;
    logic [31:0] smc_otp_axil_awvalid_count, smc_otp_axil_wvalid_count;
    logic [31:0] smc_otp_axil_arvalid_count;
    logic [31:0] sep_otp_axil_awvalid_count, sep_otp_axil_wvalid_count;
    logic [31:0] sep_otp_axil_arvalid_count;

    // SMC OTP AXI-Lite manager (flattened)
    logic [31:0] smc_otp_axil_awaddr;
    logic [2:0]  smc_otp_axil_awprot;
    logic        smc_otp_axil_awvalid, smc_otp_axil_awready;
    logic [31:0] smc_otp_axil_wdata;
    logic [3:0]  smc_otp_axil_wstrb;
    logic        smc_otp_axil_wvalid, smc_otp_axil_wready;
    logic [1:0]  smc_otp_axil_bresp;
    logic        smc_otp_axil_bvalid, smc_otp_axil_bready;
    logic [31:0] smc_otp_axil_araddr;
    logic [2:0]  smc_otp_axil_arprot;
    logic        smc_otp_axil_arvalid, smc_otp_axil_arready;
    logic [31:0] smc_otp_axil_rdata;
    logic [1:0]  smc_otp_axil_rresp;
    logic        smc_otp_axil_rvalid, smc_otp_axil_rready;

    // SEP OTP AXI-Lite manager (flattened)
    logic [31:0] sep_otp_axil_awaddr;
    logic [2:0]  sep_otp_axil_awprot;
    logic        sep_otp_axil_awvalid, sep_otp_axil_awready;
    logic [31:0] sep_otp_axil_wdata;
    logic [3:0]  sep_otp_axil_wstrb;
    logic        sep_otp_axil_wvalid, sep_otp_axil_wready;
    logic [1:0]  sep_otp_axil_bresp;
    logic        sep_otp_axil_bvalid, sep_otp_axil_bready;
    logic [31:0] sep_otp_axil_araddr;
    logic [2:0]  sep_otp_axil_arprot;
    logic        sep_otp_axil_arvalid, sep_otp_axil_arready;
    logic [31:0] sep_otp_axil_rdata;
    logic [1:0]  sep_otp_axil_rresp;
    logic        sep_otp_axil_rvalid, sep_otp_axil_rready;

    // XTRIG AXI-Lite subordinate (flattened)
    logic [31:0] xtrig_axil_awaddr;
    logic [2:0]  xtrig_axil_awprot;
    logic        xtrig_axil_awvalid, xtrig_axil_awready;
    logic [31:0] xtrig_axil_wdata;
    logic [3:0]  xtrig_axil_wstrb;
    logic        xtrig_axil_wvalid, xtrig_axil_wready;
    logic [1:0]  xtrig_axil_bresp;
    logic        xtrig_axil_bvalid, xtrig_axil_bready;
    logic [31:0] xtrig_axil_araddr;
    logic [2:0]  xtrig_axil_arprot;
    logic        xtrig_axil_arvalid, xtrig_axil_arready;
    logic [31:0] xtrig_axil_rdata;
    logic [1:0]  xtrig_axil_rresp;
    logic        xtrig_axil_rvalid, xtrig_axil_rready;
    logic [31:0] xtrig_axil_awvalid_count, xtrig_axil_wvalid_count, xtrig_axil_arvalid_count;

    // XTRIG CTM and CTP GPIO stimulus/observables
    logic [DEFAULT_NUM_INT_CT-1:0] xtrig_ctm_src_req, xtrig_ctm_src_ack;
    logic [DEFAULT_NUM_INT_CT-1:0] xtrig_ctm_dst_req, xtrig_ctm_dst_ack;
    logic [DEFAULT_NUM_CTP-1:0] xtrig_ctp_req_out_dout, xtrig_ctp_req_out_dout_en;
    logic [DEFAULT_NUM_CTP-1:0] xtrig_ctp_req_out_din, xtrig_ctp_req_out_din_en;
    logic [DEFAULT_NUM_CTP-1:0] xtrig_ctp_req_in_dout, xtrig_ctp_req_in_dout_en;
    logic [DEFAULT_NUM_CTP-1:0] xtrig_ctp_req_in_din, xtrig_ctp_req_in_din_en;
    logic [DEFAULT_NUM_CTP-1:0] xtrig_ctp_ack_in_dout, xtrig_ctp_ack_in_dout_en;
    logic [DEFAULT_NUM_CTP-1:0] xtrig_ctp_ack_in_din, xtrig_ctp_ack_in_din_en;
    logic [DEFAULT_NUM_CTP-1:0] xtrig_ctp_ack_out_dout, xtrig_ctp_ack_out_dout_en;
    logic [DEFAULT_NUM_CTP-1:0] xtrig_ctp_ack_out_din, xtrig_ctp_ack_out_din_en;
`endif

    // ------------------------------------------------------------------
    // Primary JTAG client: pack raw pins into the decoded tap-control struct
    // ------------------------------------------------------------------
    jtag_tap_ctrl_t jtag_ptap_client_tap_ctrl;
    logic           jtag_ptap_client_tdo;
    logic           jtag_ptap_client_tdo_oen;

    assign jtag_ptap_client_tap_ctrl = '{
        tms:    jtag_tms,
        trst_n: jtag_trst,
        tck:    jtag_tck
    };
    assign jtag_tdo = jtag_ptap_client_tdo;
    assign jtag_tdo_oen = jtag_ptap_client_tdo_oen;

    // ------------------------------------------------------------------
    // STAP / iJTAG scan-chain loopback nets (zero-length passthrough)
    // ------------------------------------------------------------------
    // Boundary scan + extended scan + iJTAG: loop scan_in <- scan_out.
    jtag_scan_ctrl_t jtag_bsr_host_scan_ctrl;
    jtag_scan_ctrl_t jtag_stap_host_scan_ctrl;
    jtag_scan_ctrl_t jtag_dfd_host_scan_ctrl;
    jtag_scan_ctrl_t jtag_dft_secure_host_scan_ctrl;
    jtag_scan_ctrl_t jtag_dft_host_scan_ctrl;
    logic bsr_scan_out;
    logic stap_host_scan_out;
    logic dfd_scan_out;
    logic dft_secure_scan_out;
    logic dft_scan_out;

    // STAP TAP host ports: loop tdi <- tdo.
    jtag_tap_ctrl_t stap_io_tap_ctrl;
    jtag_tap_ctrl_t stap_smc_tap_ctrl;
    jtag_tap_ctrl_t stap_sep_tap_ctrl;
    jtag_tap_ctrl_t stap_extra_tap_ctrl [0:0];
    logic stap_io_tdo;
    logic stap_smc_tdo;
    logic stap_sep_tdo;
    logic stap_extra_tdo  [0:0];
    logic stap_extra_tdo_oen [0:0];

    // IC_RESET default slice structs are one `{ovrd, val}` pair per slice in
    // this standalone OSS DTP instantiation. Flatten them for cocotb sampling.
    jtag_ic_reset_default_t jtag_ic_reset_smc;
    jtag_ic_reset_default_t jtag_ic_reset_sep;
    jtag_ic_reset_default_t jtag_ic_reset_ext;
    sep_lifecycle_ctrl_pkg::dbg_disable_t dbg_disable;

    assign jtag_bsr_select     = jtag_bsr_host_scan_ctrl.select;
    assign jtag_bsr_shift_en   = jtag_bsr_host_scan_ctrl.shift_en;
    assign jtag_bsr_capture_en = jtag_bsr_host_scan_ctrl.capture_en;
    assign jtag_bsr_update_en  = jtag_bsr_host_scan_ctrl.update_en;
    assign jtag_ijtag_select     = jtag_dft_host_scan_ctrl.select;
    assign jtag_ijtag_shift_en   = jtag_dft_host_scan_ctrl.shift_en;
    assign jtag_ijtag_capture_en = jtag_dft_host_scan_ctrl.capture_en;
    assign jtag_ijtag_update_en  = jtag_dft_host_scan_ctrl.update_en;
    assign jtag_dft_secure_select     = jtag_dft_secure_host_scan_ctrl.select;
    assign jtag_dft_secure_shift_en   = jtag_dft_secure_host_scan_ctrl.shift_en;
    assign jtag_dft_secure_capture_en = jtag_dft_secure_host_scan_ctrl.capture_en;
    assign jtag_dft_secure_update_en  = jtag_dft_secure_host_scan_ctrl.update_en;
    assign jtag_dft_select     = jtag_dft_host_scan_ctrl.select;
    assign jtag_dft_shift_en   = jtag_dft_host_scan_ctrl.shift_en;
    assign jtag_dft_capture_en = jtag_dft_host_scan_ctrl.capture_en;
    assign jtag_dft_update_en  = jtag_dft_host_scan_ctrl.update_en;
    assign jtag_dfd_select     = jtag_dfd_host_scan_ctrl.select;
    assign jtag_dfd_shift_en   = jtag_dfd_host_scan_ctrl.shift_en;
    assign jtag_dfd_capture_en = jtag_dfd_host_scan_ctrl.capture_en;
    assign jtag_dfd_update_en  = jtag_dfd_host_scan_ctrl.update_en;
    assign jtag_stap_host_select     = jtag_stap_host_scan_ctrl.select;
    assign jtag_stap_host_shift_en   = jtag_stap_host_scan_ctrl.shift_en;
    assign jtag_stap_host_capture_en = jtag_stap_host_scan_ctrl.capture_en;
    assign jtag_stap_host_update_en  = jtag_stap_host_scan_ctrl.update_en;
    assign jtag_stap_io_tms     = stap_io_tap_ctrl.tms;
    assign jtag_stap_io_tck     = stap_io_tap_ctrl.tck;
    assign jtag_stap_io_trst_n  = stap_io_tap_ctrl.trst_n;
    assign jtag_stap_smc_tms    = stap_smc_tap_ctrl.tms;
    assign jtag_stap_smc_tck    = stap_smc_tap_ctrl.tck;
    assign jtag_stap_smc_trst_n = stap_smc_tap_ctrl.trst_n;
    assign jtag_stap_sep_tms    = stap_sep_tap_ctrl.tms;
    assign jtag_stap_sep_tck    = stap_sep_tap_ctrl.tck;
    assign jtag_stap_sep_trst_n = stap_sep_tap_ctrl.trst_n;
    assign jtag_stap_extra0_tms    = stap_extra_tap_ctrl[0].tms;
    assign jtag_stap_extra0_tck    = stap_extra_tap_ctrl[0].tck;
    assign jtag_stap_extra0_trst_n = stap_extra_tap_ctrl[0].trst_n;
    assign jtag_stap_extra0_tdo_oen = stap_extra_tdo_oen[0];
    assign jtag_ic_reset_smc_ovrd   = jtag_ic_reset_smc.ovrd;
    assign jtag_ic_reset_smc_ctrl_n = jtag_ic_reset_smc.val;
    assign jtag_ic_reset_sep_ovrd   = jtag_ic_reset_sep.ovrd;
    assign jtag_ic_reset_sep_ctrl_n = jtag_ic_reset_sep.val;
    assign jtag_ic_reset_ext_ovrd   = jtag_ic_reset_ext.ovrd;
    assign jtag_ic_reset_ext_ctrl_n = jtag_ic_reset_ext.val;

`ifndef UVM
    // Pack the cocotb-driven per-field scalars unchanged into dbg_disable_i.
    always_comb begin
        dbg_disable.stap_io          = dbg_disable_stap_io;
        dbg_disable.stap_smc         = dbg_disable_stap_smc;
        dbg_disable.stap_sep         = dbg_disable_stap_sep;
        dbg_disable.stap_extra       = dbg_disable_stap_extra;
        dbg_disable.stap_host        = dbg_disable_stap_host;
        dbg_disable.dft_secure       = dbg_disable_dft_secure;
        dbg_disable.dft_nonsecure    = dbg_disable_dft_nonsecure;
        dbg_disable.dfd              = dbg_disable_dfd;
        dbg_disable.smc_jtag2axi     = dbg_disable_smc_jtag2axi;
        dbg_disable.smc_otp_jtag2axi = dbg_disable_smc_otp_jtag2axi;
        dbg_disable.sep_otp_jtag2axi = dbg_disable_sep_otp_jtag2axi;
    end
`endif

    // ------------------------------------------------------------------
    // SMC fabric debug AXI4 manager: struct <-> flat-signal adapter so the
    // JTAG2AXI bridge talks to a cocotb AXI RAM BFM bound on the `m_axi_*`
    // prefix. Widths: ID=2, ADDR=56, DATA=64, STRB=8, USER=12 (dtp_pkg).
    // ------------------------------------------------------------------
    jtag_dbg_56_64_2_12_axi_req_t   axi_smc_dbg_req;
    jtag_dbg_56_64_2_12_axi_resp_t  axi_smc_dbg_resp;
    dtp_axil_32_32_req_t            axil_smc_otp_jtag_req;
    dtp_axil_32_32_resp_t           axil_smc_otp_jtag_resp;
    dtp_axil_32_32_req_t            axil_sep_otp_jtag_req;
    dtp_axil_32_32_resp_t           axil_sep_otp_jtag_resp;
    dtp_axil_32_32_req_t            axil_xtrig_req;
    dtp_axil_32_32_resp_t           axil_xtrig_resp;

    // Write address channel
    logic [1:0]   m_axi_awid;
    logic [55:0]  m_axi_awaddr;
    logic [7:0]   m_axi_awlen;
    logic [2:0]   m_axi_awsize;
    logic [1:0]   m_axi_awburst;
    logic         m_axi_awlock;
    logic [3:0]   m_axi_awcache;
    logic [2:0]   m_axi_awprot;
    logic [3:0]   m_axi_awqos;
    logic [3:0]   m_axi_awregion;
    logic [11:0]  m_axi_awuser;
    logic         m_axi_awvalid;
    logic         m_axi_awready;
    // Write data channel
    logic [63:0]  m_axi_wdata;
    logic [7:0]   m_axi_wstrb;
    logic         m_axi_wlast;
    logic [11:0]  m_axi_wuser;
    logic         m_axi_wvalid;
    logic         m_axi_wready;
    // Write response channel
    logic [1:0]   m_axi_bid;
    logic [1:0]   m_axi_bresp;
    logic [11:0]  m_axi_buser;
    logic         m_axi_bvalid;
    logic         m_axi_bready;
    // Read address channel
    logic [1:0]   m_axi_arid;
    logic [55:0]  m_axi_araddr;
    logic [7:0]   m_axi_arlen;
    logic [2:0]   m_axi_arsize;
    logic [1:0]   m_axi_arburst;
    logic         m_axi_arlock;
    logic [3:0]   m_axi_arcache;
    logic [2:0]   m_axi_arprot;
    logic [3:0]   m_axi_arqos;
    logic [3:0]   m_axi_arregion;
    logic [11:0]  m_axi_aruser;
    logic         m_axi_arvalid;
    logic         m_axi_arready;
    // Read data channel
    logic [1:0]   m_axi_rid;
    logic [63:0]  m_axi_rdata;
    logic [1:0]   m_axi_rresp;
    logic         m_axi_rlast;
    logic [11:0]  m_axi_ruser;
    logic         m_axi_rvalid;
    logic         m_axi_rready;

    // DUT req struct -> flat master outputs
    assign m_axi_awid     = axi_smc_dbg_req.aw.id;
    assign m_axi_awaddr   = axi_smc_dbg_req.aw.addr;
    assign m_axi_awlen    = axi_smc_dbg_req.aw.len;
    assign m_axi_awsize   = axi_smc_dbg_req.aw.size;
    assign m_axi_awburst  = axi_smc_dbg_req.aw.burst;
    assign m_axi_awlock   = axi_smc_dbg_req.aw.lock;
    assign m_axi_awcache  = axi_smc_dbg_req.aw.cache;
    assign m_axi_awprot   = axi_smc_dbg_req.aw.prot;
    assign m_axi_awqos    = axi_smc_dbg_req.aw.qos;
    assign m_axi_awregion = axi_smc_dbg_req.aw.region;
    assign m_axi_awuser   = axi_smc_dbg_req.aw.user;
    assign m_axi_awvalid  = axi_smc_dbg_req.aw_valid;
    assign m_axi_wdata    = axi_smc_dbg_req.w.data;
    assign m_axi_wstrb    = axi_smc_dbg_req.w.strb;
    assign m_axi_wlast    = axi_smc_dbg_req.w.last;
    assign m_axi_wuser    = axi_smc_dbg_req.w.user;
    assign m_axi_wvalid   = axi_smc_dbg_req.w_valid;
    assign m_axi_bready   = axi_smc_dbg_req.b_ready;
    assign m_axi_arid     = axi_smc_dbg_req.ar.id;
    assign m_axi_araddr   = axi_smc_dbg_req.ar.addr;
    assign m_axi_arlen    = axi_smc_dbg_req.ar.len;
    assign m_axi_arsize   = axi_smc_dbg_req.ar.size;
    assign m_axi_arburst  = axi_smc_dbg_req.ar.burst;
    assign m_axi_arlock   = axi_smc_dbg_req.ar.lock;
    assign m_axi_arcache  = axi_smc_dbg_req.ar.cache;
    assign m_axi_arprot   = axi_smc_dbg_req.ar.prot;
    assign m_axi_arqos    = axi_smc_dbg_req.ar.qos;
    assign m_axi_arregion = axi_smc_dbg_req.ar.region;
    assign m_axi_aruser   = axi_smc_dbg_req.ar.user;
    assign m_axi_arvalid  = axi_smc_dbg_req.ar_valid;
    assign m_axi_rready   = axi_smc_dbg_req.r_ready;

    always_ff @(posedge clk_i or negedge rst_n_i) begin
        if (!rst_n_i) begin
            smc_axi_awvalid_count <= '0;
            smc_axi_wvalid_count  <= '0;
            smc_axi_arvalid_count <= '0;
        end else begin
            smc_axi_awvalid_count <= smc_axi_awvalid_count + {31'b0, m_axi_awvalid};
            smc_axi_wvalid_count  <= smc_axi_wvalid_count + {31'b0, m_axi_wvalid};
            smc_axi_arvalid_count <= smc_axi_arvalid_count + {31'b0, m_axi_arvalid};
        end
    end

    // Flat slave inputs (from AxiRam) -> DUT resp struct
    always_comb begin
        axi_smc_dbg_resp          = '{default: '0};
        axi_smc_dbg_resp.aw_ready = m_axi_awready;
        axi_smc_dbg_resp.w_ready  = m_axi_wready;
        axi_smc_dbg_resp.b_valid  = m_axi_bvalid;
        axi_smc_dbg_resp.b.id     = m_axi_bid;
        axi_smc_dbg_resp.b.resp   = m_axi_bresp;
        axi_smc_dbg_resp.b.user   = m_axi_buser;
        axi_smc_dbg_resp.ar_ready = m_axi_arready;
        axi_smc_dbg_resp.r_valid  = m_axi_rvalid;
        axi_smc_dbg_resp.r.id     = m_axi_rid;
        axi_smc_dbg_resp.r.data   = m_axi_rdata;
        axi_smc_dbg_resp.r.resp   = m_axi_rresp;
        axi_smc_dbg_resp.r.last   = m_axi_rlast;
        axi_smc_dbg_resp.r.user   = m_axi_ruser;
    end

    // ------------------------------------------------------------------
    // OTP debug AXI-Lite managers: struct <-> flat-signal adapters.
    // Both bridges use 32-bit address/data AXI-Lite channels.
    // ------------------------------------------------------------------
    assign smc_otp_axil_awaddr  = axil_smc_otp_jtag_req.aw.addr;
    assign smc_otp_axil_awprot  = axil_smc_otp_jtag_req.aw.prot;
    assign smc_otp_axil_awvalid = axil_smc_otp_jtag_req.aw_valid;
    assign smc_otp_axil_wdata   = axil_smc_otp_jtag_req.w.data;
    assign smc_otp_axil_wstrb   = axil_smc_otp_jtag_req.w.strb;
    assign smc_otp_axil_wvalid  = axil_smc_otp_jtag_req.w_valid;
    assign smc_otp_axil_bready  = axil_smc_otp_jtag_req.b_ready;
    assign smc_otp_axil_araddr  = axil_smc_otp_jtag_req.ar.addr;
    assign smc_otp_axil_arprot  = axil_smc_otp_jtag_req.ar.prot;
    assign smc_otp_axil_arvalid = axil_smc_otp_jtag_req.ar_valid;
    assign smc_otp_axil_rready  = axil_smc_otp_jtag_req.r_ready;

    assign sep_otp_axil_awaddr  = axil_sep_otp_jtag_req.aw.addr;
    assign sep_otp_axil_awprot  = axil_sep_otp_jtag_req.aw.prot;
    assign sep_otp_axil_awvalid = axil_sep_otp_jtag_req.aw_valid;
    assign sep_otp_axil_wdata   = axil_sep_otp_jtag_req.w.data;
    assign sep_otp_axil_wstrb   = axil_sep_otp_jtag_req.w.strb;
    assign sep_otp_axil_wvalid  = axil_sep_otp_jtag_req.w_valid;
    assign sep_otp_axil_bready  = axil_sep_otp_jtag_req.b_ready;
    assign sep_otp_axil_araddr  = axil_sep_otp_jtag_req.ar.addr;
    assign sep_otp_axil_arprot  = axil_sep_otp_jtag_req.ar.prot;
    assign sep_otp_axil_arvalid = axil_sep_otp_jtag_req.ar_valid;
    assign sep_otp_axil_rready  = axil_sep_otp_jtag_req.r_ready;

    always_comb begin
        axil_smc_otp_jtag_resp          = '{default: '0};
        axil_smc_otp_jtag_resp.aw_ready = smc_otp_axil_awready;
        axil_smc_otp_jtag_resp.w_ready  = smc_otp_axil_wready;
        axil_smc_otp_jtag_resp.b_valid  = smc_otp_axil_bvalid;
        axil_smc_otp_jtag_resp.b.resp   = smc_otp_axil_bresp;
        axil_smc_otp_jtag_resp.ar_ready = smc_otp_axil_arready;
        axil_smc_otp_jtag_resp.r_valid  = smc_otp_axil_rvalid;
        axil_smc_otp_jtag_resp.r.data   = smc_otp_axil_rdata;
        axil_smc_otp_jtag_resp.r.resp   = smc_otp_axil_rresp;

        axil_sep_otp_jtag_resp          = '{default: '0};
        axil_sep_otp_jtag_resp.aw_ready = sep_otp_axil_awready;
        axil_sep_otp_jtag_resp.w_ready  = sep_otp_axil_wready;
        axil_sep_otp_jtag_resp.b_valid  = sep_otp_axil_bvalid;
        axil_sep_otp_jtag_resp.b.resp   = sep_otp_axil_bresp;
        axil_sep_otp_jtag_resp.ar_ready = sep_otp_axil_arready;
        axil_sep_otp_jtag_resp.r_valid  = sep_otp_axil_rvalid;
        axil_sep_otp_jtag_resp.r.data   = sep_otp_axil_rdata;
        axil_sep_otp_jtag_resp.r.resp   = sep_otp_axil_rresp;
    end

    // XTRIG CSR AXI-Lite subordinate: flat cocotb master signals -> DUT req
    // struct, with DUT responses exposed back to cocotb.
    always_comb begin
        axil_xtrig_req          = '{default: '0};
        axil_xtrig_req.aw.addr  = xtrig_axil_awaddr;
        axil_xtrig_req.aw.prot  = xtrig_axil_awprot;
        axil_xtrig_req.aw_valid = xtrig_axil_awvalid;
        axil_xtrig_req.w.data   = xtrig_axil_wdata;
        axil_xtrig_req.w.strb   = xtrig_axil_wstrb;
        axil_xtrig_req.w_valid  = xtrig_axil_wvalid;
        axil_xtrig_req.b_ready  = xtrig_axil_bready;
        axil_xtrig_req.ar.addr  = xtrig_axil_araddr;
        axil_xtrig_req.ar.prot  = xtrig_axil_arprot;
        axil_xtrig_req.ar_valid = xtrig_axil_arvalid;
        axil_xtrig_req.r_ready  = xtrig_axil_rready;
    end

    assign xtrig_axil_awready = axil_xtrig_resp.aw_ready;
    assign xtrig_axil_wready  = axil_xtrig_resp.w_ready;
    assign xtrig_axil_bvalid  = axil_xtrig_resp.b_valid;
    assign xtrig_axil_bresp   = axil_xtrig_resp.b.resp;
    assign xtrig_axil_arready = axil_xtrig_resp.ar_ready;
    assign xtrig_axil_rvalid  = axil_xtrig_resp.r_valid;
    assign xtrig_axil_rdata   = axil_xtrig_resp.r.data;
    assign xtrig_axil_rresp   = axil_xtrig_resp.r.resp;

    always_ff @(posedge clk_i or negedge rst_n_i) begin
        if (!rst_n_i) begin
            smc_otp_axil_awvalid_count <= '0;
            smc_otp_axil_wvalid_count  <= '0;
            smc_otp_axil_arvalid_count <= '0;
            sep_otp_axil_awvalid_count <= '0;
            sep_otp_axil_wvalid_count  <= '0;
            sep_otp_axil_arvalid_count <= '0;
            xtrig_axil_awvalid_count   <= '0;
            xtrig_axil_wvalid_count    <= '0;
            xtrig_axil_arvalid_count   <= '0;
        end else begin
            smc_otp_axil_awvalid_count <=
                smc_otp_axil_awvalid_count + {31'b0, smc_otp_axil_awvalid};
            smc_otp_axil_wvalid_count <=
                smc_otp_axil_wvalid_count + {31'b0, smc_otp_axil_wvalid};
            smc_otp_axil_arvalid_count <=
                smc_otp_axil_arvalid_count + {31'b0, smc_otp_axil_arvalid};
            sep_otp_axil_awvalid_count <=
                sep_otp_axil_awvalid_count + {31'b0, sep_otp_axil_awvalid};
            sep_otp_axil_wvalid_count <=
                sep_otp_axil_wvalid_count + {31'b0, sep_otp_axil_wvalid};
            sep_otp_axil_arvalid_count <=
                sep_otp_axil_arvalid_count + {31'b0, sep_otp_axil_arvalid};
            xtrig_axil_awvalid_count <=
                xtrig_axil_awvalid_count + {31'b0, xtrig_axil_awvalid};
            xtrig_axil_wvalid_count <=
                xtrig_axil_wvalid_count + {31'b0, xtrig_axil_wvalid};
            xtrig_axil_arvalid_count <=
                xtrig_axil_arvalid_count + {31'b0, xtrig_axil_arvalid};
        end
    end

    // ------------------------------------------------------------------
    // DTP DUT (default parameters; type params use jtag_tap_pkg/dtp_pkg stubs)
    // ------------------------------------------------------------------
    dtp u_dut (
        .clk_i                            (clk_i),
        .rst_n_i                          (rst_n_i),
        .pwr_on_rst_ni                    (pwr_on_rst_ni),

        // Lifecycle debug gating: active-high disables pre-resolved per
        // interface; '0 == nothing disabled (full debug access).
        .dbg_disable_i                    (dbg_disable),

        // Primary JTAG TAP client
        .jtag_ptap_client_tap_ctrl_i      (jtag_ptap_client_tap_ctrl),
        .jtag_ptap_client_tdi_i           (jtag_tdi),
        .jtag_ptap_client_tdo_o           (jtag_ptap_client_tdo),
        .jtag_ptap_client_tdo_oen_o       (jtag_ptap_client_tdo_oen),

        // Boundary scan host (loopback)
        .jtag_bsr_host_scan_ctrl_o        (jtag_bsr_host_scan_ctrl),
        .jtag_bsr_host_scan_in_i          (bsr_scan_out),
        .jtag_bsr_host_scan_out_o         (bsr_scan_out),

        // I/O STAP host (loopback)
        .jtag_stap_io_host_tap_ctrl_o     (stap_io_tap_ctrl),
        .jtag_stap_io_host_tdi_i          (stap_io_tdo),
        .jtag_stap_io_host_tdo_o          (stap_io_tdo),
        .jtag_stap_io_host_tdo_oen_o      (jtag_stap_io_tdo_oen),

        // SMC debug STAP host (loopback)
        .jtag_stap_smc_host_tap_ctrl_o    (stap_smc_tap_ctrl),
        .jtag_stap_smc_host_tdi_i         (stap_smc_tdo),
        .jtag_stap_smc_host_tdo_o         (stap_smc_tdo),
        .jtag_stap_smc_host_tdo_oen_o     (jtag_stap_smc_tdo_oen),

        // SEP debug STAP host (loopback)
        .jtag_stap_sep_host_tap_ctrl_o    (stap_sep_tap_ctrl),
        .jtag_stap_sep_host_tdi_i         (stap_sep_tdo),
        .jtag_stap_sep_host_tdo_o         (stap_sep_tdo),
        .jtag_stap_sep_host_tdo_oen_o     (jtag_stap_sep_tdo_oen),

        // Extra STAP hosts (loopback, 1 port by default)
        .jtag_stap_extra_host_tap_ctrl_o  (stap_extra_tap_ctrl),
        .jtag_stap_extra_host_tdi_i       (stap_extra_tdo),
        .jtag_stap_extra_host_tdo_o       (stap_extra_tdo),
        .jtag_stap_extra_host_tdo_oen_o   (stap_extra_tdo_oen),

        // Extended STAP scan (loopback)
        .jtag_stap_host_scan_ctrl_o       (jtag_stap_host_scan_ctrl),
        .jtag_stap_host_scan_in_i         (stap_host_scan_out),
        .jtag_stap_host_scan_out_o        (stap_host_scan_out),

        // External DFD iJTAG scan (loopback)
        .jtag_dfd_host_scan_ctrl_o        (jtag_dfd_host_scan_ctrl),
        .jtag_dfd_host_scan_in_i          (dfd_scan_out),
        .jtag_dfd_host_scan_out_o         (dfd_scan_out),

        // External secure DFT iJTAG scan (loopback)
        .jtag_dft_secure_host_scan_ctrl_o (jtag_dft_secure_host_scan_ctrl),
        .jtag_dft_secure_host_scan_in_i   (dft_secure_scan_out),
        .jtag_dft_secure_host_scan_out_o  (dft_secure_scan_out),

        // External non-secure DFT iJTAG scan (loopback)
        .jtag_dft_host_scan_ctrl_o        (jtag_dft_host_scan_ctrl),
        .jtag_dft_host_scan_in_i          (dft_scan_out),
        .jtag_dft_host_scan_out_o         (dft_scan_out),

        // SMC fabric debug AXI manager -> OCAH AXI RAM BFM (flattened above)
        .axi_smc_dbg_req_o                (axi_smc_dbg_req),
        .axi_smc_dbg_resp_i               (axi_smc_dbg_resp),

        // SMC OTP debug AXI-Lite manager -> AXI-Lite RAM BFM
        .axil_smc_otp_jtag_req_o          (axil_smc_otp_jtag_req),
        .axil_smc_otp_jtag_resp_i         (axil_smc_otp_jtag_resp),

        // SEP OTP debug AXI-Lite manager -> AXI-Lite RAM BFM
        .axil_sep_otp_jtag_req_o          (axil_sep_otp_jtag_req),
        .axil_sep_otp_jtag_resp_i         (axil_sep_otp_jtag_resp),

        // Clock / boot-stall / reset control outputs (observed only)
        .stop_clks_o                      (stop_clks),
        .cla_clock_stop_en_o              (cla_clock_stop_en),
        .jtag_boot_stall_ovrd_o           (jtag_boot_stall_ovrd),
        .jtag_boot_stall_o                (jtag_boot_stall),
        .jtag_ic_reset_smc_o              (jtag_ic_reset_smc),
        .jtag_ic_reset_sep_o              (jtag_ic_reset_sep),
        .jtag_ic_reset_ext_o              (jtag_ic_reset_ext),
        .jtag_ptap_state_o                (jtag_ptap_state),
        .jtag_ptap_inst_decoded_o         (jtag_ptap_inst_decoded),

        // Cross-trigger CSR AXI-Lite subordinate -> cocotb BFM
        .axil_xtrig_req_i                 (axil_xtrig_req),
        .axil_xtrig_resp_o                (axil_xtrig_resp),

        // Cross-trigger matrix
        .xtrig_ctm_src_req_o              (xtrig_ctm_src_req),
        .xtrig_ctm_src_ack_i              (xtrig_ctm_src_ack),
        .xtrig_ctm_dst_req_i              (xtrig_ctm_dst_req),
        .xtrig_ctm_dst_ack_o              (xtrig_ctm_dst_ack),

        // CLA clock-stop requests (driven by cocotb for DEBUG_CONTROL tests)
        .xtrig_clk_stop_req_i             (xtrig_clk_stop_req),

        // Cross-trigger port GPIO
        .xtrig_ctp_req_out_dout_o         (xtrig_ctp_req_out_dout),
        .xtrig_ctp_req_out_dout_en_o      (xtrig_ctp_req_out_dout_en),
        .xtrig_ctp_req_out_din_i          (xtrig_ctp_req_out_din),
        .xtrig_ctp_req_out_din_en_o       (xtrig_ctp_req_out_din_en),

        .xtrig_ctp_req_in_dout_o          (xtrig_ctp_req_in_dout),
        .xtrig_ctp_req_in_dout_en_o       (xtrig_ctp_req_in_dout_en),
        .xtrig_ctp_req_in_din_i           (xtrig_ctp_req_in_din),
        .xtrig_ctp_req_in_din_en_o        (xtrig_ctp_req_in_din_en),

        .xtrig_ctp_ack_in_dout_o          (xtrig_ctp_ack_in_dout),
        .xtrig_ctp_ack_in_dout_en_o       (xtrig_ctp_ack_in_dout_en),
        .xtrig_ctp_ack_in_din_i           (xtrig_ctp_ack_in_din),
        .xtrig_ctp_ack_in_din_en_o        (xtrig_ctp_ack_in_din_en),

        .xtrig_ctp_ack_out_dout_o         (xtrig_ctp_ack_out_dout),
        .xtrig_ctp_ack_out_dout_en_o      (xtrig_ctp_ack_out_dout_en),
        .xtrig_ctp_ack_out_din_i          (xtrig_ctp_ack_out_din),
        .xtrig_ctp_ack_out_din_en_o       (xtrig_ctp_ack_out_din_en)
    );

`ifdef UVM
    // ------------------------------------------------------------------
    // SV-UVM harness (`--dut dtp --framework uvm`): clock, interface instances,
    // quiescent tie-offs, config_db publication, and run_test(). Compiled
    // only when the native-uvm flow defines UVM; the cocotb flow
    // sees only the ported module above.
    // ------------------------------------------------------------------
    import uvm_pkg::*;

    // 100 MHz system clock; TCK is bit-banged by the sequence via the vif.
    initial clk_i = 1'b0;
    always #5ns clk_i = ~clk_i;

    ocah_jtag_if u_jtag_if ();
    dtp_tb_if    u_tb_if ();

    // Primary JTAG TAP: TB drives tck/tms/trst_n/tdi, DUT drives tdo/tdo_oen.
    assign jtag_tck  = u_jtag_if.tck;
    assign jtag_tms  = u_jtag_if.tms;
    assign jtag_trst = u_jtag_if.trst_n;
    assign jtag_tdi  = u_jtag_if.tdi;
    assign u_jtag_if.tdo     = jtag_tdo;
    assign u_jtag_if.tdo_oen = jtag_tdo_oen;

    // DTP-local resets (test-sequenced) and TAP-state observable.
    assign rst_n_i           = u_tb_if.sys_rst_n;
    assign pwr_on_rst_ni     = u_tb_if.por_rst_n;
    assign u_tb_if.tap_state = jtag_ptap_state;

    // Lifecycle debug disables and clock-stop requests: sequences drive the
    // typed dbg_disable_t through dtp_tb_if (init '1 = fail-closed, so the
    // sanity test's behavior is unchanged; JTAG2AXI sequences clear the
    // disables they need).
    assign xtrig_clk_stop_req = '0;
    assign dbg_disable        = u_tb_if.dbg_disable;

    // SMC OTP AXI-Lite responder: the shared ocah_axi_vip UVM slave agent
    // answers JTAG2AXI OTP traffic (issue #3295). The slave interface carries
    // the connection: the TB wires only the master-driven signals in, and the
    // agent's driver procedurally drives the responder-side signals, routed
    // back to the DUT below. Error injection is programmed by sequences via
    // the agent's ocah_axi_slave_sequence, not TB error ports.
    ocah_axi_if u_smc_otp_slave_if (.aclk(clk_i), .aresetn(rst_n_i));
    assign u_smc_otp_slave_if.awaddr   = 64'(smc_otp_axil_awaddr);
    assign u_smc_otp_slave_if.awprot   = smc_otp_axil_awprot;
    assign u_smc_otp_slave_if.awvalid  = smc_otp_axil_awvalid;
    assign u_smc_otp_slave_if.awid     = '0;
    assign u_smc_otp_slave_if.awlen    = '0;
    assign u_smc_otp_slave_if.awsize   = 3'd2;
    assign u_smc_otp_slave_if.awburst  = 2'b01;
    assign u_smc_otp_slave_if.awlock   = 1'b0;
    assign u_smc_otp_slave_if.awcache  = '0;
    assign u_smc_otp_slave_if.awqos    = '0;
    assign u_smc_otp_slave_if.awregion = '0;
    assign u_smc_otp_slave_if.awuser   = '0;
    assign u_smc_otp_slave_if.wdata    = 64'(smc_otp_axil_wdata);
    assign u_smc_otp_slave_if.wstrb    = 8'(smc_otp_axil_wstrb);
    assign u_smc_otp_slave_if.wlast    = 1'b1;
    assign u_smc_otp_slave_if.wuser    = '0;
    assign u_smc_otp_slave_if.wvalid   = smc_otp_axil_wvalid;
    assign u_smc_otp_slave_if.bready   = smc_otp_axil_bready;
    assign u_smc_otp_slave_if.araddr   = 64'(smc_otp_axil_araddr);
    assign u_smc_otp_slave_if.arprot   = smc_otp_axil_arprot;
    assign u_smc_otp_slave_if.arvalid  = smc_otp_axil_arvalid;
    assign u_smc_otp_slave_if.arid     = '0;
    assign u_smc_otp_slave_if.arlen    = '0;
    assign u_smc_otp_slave_if.arsize   = 3'd2;
    assign u_smc_otp_slave_if.arburst  = 2'b01;
    assign u_smc_otp_slave_if.arlock   = 1'b0;
    assign u_smc_otp_slave_if.arcache  = '0;
    assign u_smc_otp_slave_if.arqos    = '0;
    assign u_smc_otp_slave_if.arregion = '0;
    assign u_smc_otp_slave_if.aruser   = '0;
    assign u_smc_otp_slave_if.rready   = smc_otp_axil_rready;

    // Responder-side signals: agent driver -> DUT response inputs.
    assign smc_otp_axil_awready = u_smc_otp_slave_if.awready;
    assign smc_otp_axil_wready  = u_smc_otp_slave_if.wready;
    assign smc_otp_axil_bresp   = u_smc_otp_slave_if.bresp;
    assign smc_otp_axil_bvalid  = u_smc_otp_slave_if.bvalid;
    assign smc_otp_axil_arready = u_smc_otp_slave_if.arready;
    assign smc_otp_axil_rdata   = u_smc_otp_slave_if.rdata[31:0];
    assign smc_otp_axil_rresp   = u_smc_otp_slave_if.rresp;
    assign smc_otp_axil_rvalid  = u_smc_otp_slave_if.rvalid;

    // SMC fabric AXI4 responder: drives the previously-undriven m_axi_*
    // response inputs so JTAG2AXI fabric traffic completes in the UVM flow.
    ocah_axi_ram_responder #(
        .ADDR_WIDTH (56),
        .DATA_WIDTH (64),
        .ID_WIDTH   (2)
    ) u_smc_axi_responder (
        .clk_i          (clk_i),
        .rst_ni         (rst_n_i),
        .awid           (m_axi_awid),
        .awaddr         (m_axi_awaddr),
        .awlen          (m_axi_awlen),
        .awsize         (m_axi_awsize),
        .awburst        (m_axi_awburst),
        .awprot         (m_axi_awprot),
        .awvalid        (m_axi_awvalid),
        .awready        (m_axi_awready),
        .wdata          (m_axi_wdata),
        .wstrb          (m_axi_wstrb),
        .wlast          (m_axi_wlast),
        .wvalid         (m_axi_wvalid),
        .wready         (m_axi_wready),
        .bid            (m_axi_bid),
        .bresp          (m_axi_bresp),
        .bvalid         (m_axi_bvalid),
        .bready         (m_axi_bready),
        .arid           (m_axi_arid),
        .araddr         (m_axi_araddr),
        .arlen          (m_axi_arlen),
        .arsize         (m_axi_arsize),
        .arburst        (m_axi_arburst),
        .arprot         (m_axi_arprot),
        .arvalid        (m_axi_arvalid),
        .arready        (m_axi_arready),
        .rid            (m_axi_rid),
        .rdata          (m_axi_rdata),
        .rresp          (m_axi_rresp),
        .rlast          (m_axi_rlast),
        .rvalid         (m_axi_rvalid),
        .rready         (m_axi_rready),
        .err_arm_i      (u_tb_if.smc_axi_err_arm),
        .err_addr_i     (u_tb_if.smc_axi_err_addr),
        .err_resp_i     (u_tb_if.smc_axi_err_resp),
        .err_on_read_i  (u_tb_if.smc_axi_err_on_read),
        .err_on_write_i (u_tb_if.smc_axi_err_on_write)
    );

    // Shared-VIP monitor interfaces (default/maximum parameterization so the
    // UVM layer sees one `virtual ocah_axi_if` type; geometry lives in cfg).
    ocah_axi_if u_smc_otp_axil_if (.aclk(clk_i), .aresetn(rst_n_i));
    assign u_smc_otp_axil_if.awaddr   = 64'(smc_otp_axil_awaddr);
    assign u_smc_otp_axil_if.awprot   = smc_otp_axil_awprot;
    assign u_smc_otp_axil_if.awvalid  = smc_otp_axil_awvalid;
    assign u_smc_otp_axil_if.awready  = smc_otp_axil_awready;
    assign u_smc_otp_axil_if.awid     = '0;
    assign u_smc_otp_axil_if.awlen    = '0;
    assign u_smc_otp_axil_if.awsize   = 3'd2;
    assign u_smc_otp_axil_if.awburst  = 2'b01;
    assign u_smc_otp_axil_if.awlock   = 1'b0;
    assign u_smc_otp_axil_if.awcache  = '0;
    assign u_smc_otp_axil_if.awqos    = '0;
    assign u_smc_otp_axil_if.awregion = '0;
    assign u_smc_otp_axil_if.awuser   = '0;
    assign u_smc_otp_axil_if.wdata    = 64'(smc_otp_axil_wdata);
    assign u_smc_otp_axil_if.wstrb    = 8'(smc_otp_axil_wstrb);
    assign u_smc_otp_axil_if.wlast    = 1'b1;
    assign u_smc_otp_axil_if.wuser    = '0;
    assign u_smc_otp_axil_if.wvalid   = smc_otp_axil_wvalid;
    assign u_smc_otp_axil_if.wready   = smc_otp_axil_wready;
    assign u_smc_otp_axil_if.bid      = '0;
    assign u_smc_otp_axil_if.bresp    = smc_otp_axil_bresp;
    assign u_smc_otp_axil_if.buser    = '0;
    assign u_smc_otp_axil_if.bvalid   = smc_otp_axil_bvalid;
    assign u_smc_otp_axil_if.bready   = smc_otp_axil_bready;
    assign u_smc_otp_axil_if.araddr   = 64'(smc_otp_axil_araddr);
    assign u_smc_otp_axil_if.arprot   = smc_otp_axil_arprot;
    assign u_smc_otp_axil_if.arvalid  = smc_otp_axil_arvalid;
    assign u_smc_otp_axil_if.arready  = smc_otp_axil_arready;
    assign u_smc_otp_axil_if.arid     = '0;
    assign u_smc_otp_axil_if.arlen    = '0;
    assign u_smc_otp_axil_if.arsize   = 3'd2;
    assign u_smc_otp_axil_if.arburst  = 2'b01;
    assign u_smc_otp_axil_if.arlock   = 1'b0;
    assign u_smc_otp_axil_if.arcache  = '0;
    assign u_smc_otp_axil_if.arqos    = '0;
    assign u_smc_otp_axil_if.arregion = '0;
    assign u_smc_otp_axil_if.aruser   = '0;
    assign u_smc_otp_axil_if.rid      = '0;
    assign u_smc_otp_axil_if.rdata    = 64'(smc_otp_axil_rdata);
    assign u_smc_otp_axil_if.rresp    = smc_otp_axil_rresp;
    assign u_smc_otp_axil_if.rlast    = 1'b1;
    assign u_smc_otp_axil_if.ruser    = '0;
    assign u_smc_otp_axil_if.rvalid   = smc_otp_axil_rvalid;
    assign u_smc_otp_axil_if.rready   = smc_otp_axil_rready;

    ocah_axi_if u_m_axi_if (.aclk(clk_i), .aresetn(rst_n_i));
    assign u_m_axi_if.awid     = 16'(m_axi_awid);
    assign u_m_axi_if.awaddr   = 64'(m_axi_awaddr);
    assign u_m_axi_if.awlen    = m_axi_awlen;
    assign u_m_axi_if.awsize   = m_axi_awsize;
    assign u_m_axi_if.awburst  = m_axi_awburst;
    assign u_m_axi_if.awlock   = m_axi_awlock;
    assign u_m_axi_if.awcache  = m_axi_awcache;
    assign u_m_axi_if.awprot   = m_axi_awprot;
    assign u_m_axi_if.awqos    = m_axi_awqos;
    assign u_m_axi_if.awregion = m_axi_awregion;
    assign u_m_axi_if.awuser   = 16'(m_axi_awuser);
    assign u_m_axi_if.awvalid  = m_axi_awvalid;
    assign u_m_axi_if.awready  = m_axi_awready;
    assign u_m_axi_if.wdata    = m_axi_wdata;
    assign u_m_axi_if.wstrb    = m_axi_wstrb;
    assign u_m_axi_if.wlast    = m_axi_wlast;
    assign u_m_axi_if.wuser    = 16'(m_axi_wuser);
    assign u_m_axi_if.wvalid   = m_axi_wvalid;
    assign u_m_axi_if.wready   = m_axi_wready;
    assign u_m_axi_if.bid      = 16'(m_axi_bid);
    assign u_m_axi_if.bresp    = m_axi_bresp;
    assign u_m_axi_if.buser    = 16'(m_axi_buser);
    assign u_m_axi_if.bvalid   = m_axi_bvalid;
    assign u_m_axi_if.bready   = m_axi_bready;
    assign u_m_axi_if.arid     = 16'(m_axi_arid);
    assign u_m_axi_if.araddr   = 64'(m_axi_araddr);
    assign u_m_axi_if.arlen    = m_axi_arlen;
    assign u_m_axi_if.arsize   = m_axi_arsize;
    assign u_m_axi_if.arburst  = m_axi_arburst;
    assign u_m_axi_if.arlock   = m_axi_arlock;
    assign u_m_axi_if.arcache  = m_axi_arcache;
    assign u_m_axi_if.arprot   = m_axi_arprot;
    assign u_m_axi_if.arqos    = m_axi_arqos;
    assign u_m_axi_if.arregion = m_axi_arregion;
    assign u_m_axi_if.aruser   = 16'(m_axi_aruser);
    assign u_m_axi_if.arvalid  = m_axi_arvalid;
    assign u_m_axi_if.arready  = m_axi_arready;
    assign u_m_axi_if.rid      = 16'(m_axi_rid);
    assign u_m_axi_if.rdata    = m_axi_rdata;
    assign u_m_axi_if.rresp    = m_axi_rresp;
    assign u_m_axi_if.rlast    = m_axi_rlast;
    assign u_m_axi_if.ruser    = 16'(m_axi_ruser);
    assign u_m_axi_if.rvalid   = m_axi_rvalid;
    assign u_m_axi_if.rready   = m_axi_rready;

    // Clean-room JTAG protocol SVA checker (ocah_jtag_vip/sva) on the
    // primary TAP pins + the exported one-hot TAP state, enabled via
    // dtp_tb_if.jtag_sva_en.
    ocah_jtag_sva #(
        .EN_STATE_RULES (1'b1)
    ) u_jtag_ptap_sva (
        .tck         (jtag_tck),
        .tms         (jtag_tms),
        .tdi         (jtag_tdi),
        .trst_n      (jtag_trst),
        .tdo         (jtag_tdo),
        .tdo_oen     (jtag_tdo_oen),
        .en_i        (u_tb_if.jtag_sva_en),
        .tap_state_i (jtag_ptap_state)
    );

    // Clean-room AXI protocol SVA checkers (ocah_axi_vip/sva), enabled via
    // dtp_tb_if.axi_sva_en.
    ocah_axi_sva #(
        .IS_LITE    (1'b1),
        .ADDR_WIDTH (32),
        .DATA_WIDTH (32),
        .ID_WIDTH   (1)
    ) u_smc_otp_axil_sva (
        .aclk    (clk_i),
        .aresetn (rst_n_i),
        .en_i    (u_tb_if.axi_sva_en),
        .awid    ('0),
        .awaddr  (smc_otp_axil_awaddr),
        .awlen   ('0),
        .awsize  (3'd2),
        .awburst (2'b01),
        .awlock  (1'b0),
        .awprot  (smc_otp_axil_awprot),
        .awvalid (smc_otp_axil_awvalid),
        .awready (smc_otp_axil_awready),
        .wdata   (smc_otp_axil_wdata),
        .wstrb   (smc_otp_axil_wstrb),
        .wlast   (1'b1),
        .wvalid  (smc_otp_axil_wvalid),
        .wready  (smc_otp_axil_wready),
        .bid     ('0),
        .bresp   (smc_otp_axil_bresp),
        .bvalid  (smc_otp_axil_bvalid),
        .bready  (smc_otp_axil_bready),
        .arid    ('0),
        .araddr  (smc_otp_axil_araddr),
        .arlen   ('0),
        .arsize  (3'd2),
        .arburst (2'b01),
        .arlock  (1'b0),
        .arprot  (smc_otp_axil_arprot),
        .arvalid (smc_otp_axil_arvalid),
        .arready (smc_otp_axil_arready),
        .rid     ('0),
        .rdata   (smc_otp_axil_rdata),
        .rresp   (smc_otp_axil_rresp),
        .rlast   (1'b1),
        .rvalid  (smc_otp_axil_rvalid),
        .rready  (smc_otp_axil_rready)
    );

    ocah_axi_sva #(
        .IS_LITE    (1'b0),
        .ADDR_WIDTH (56),
        .DATA_WIDTH (64),
        .ID_WIDTH   (2)
    ) u_m_axi_sva (
        .aclk    (clk_i),
        .aresetn (rst_n_i),
        .en_i    (u_tb_if.axi_sva_en),
        .awid    (m_axi_awid),
        .awaddr  (m_axi_awaddr),
        .awlen   (m_axi_awlen),
        .awsize  (m_axi_awsize),
        .awburst (m_axi_awburst),
        .awlock  (m_axi_awlock),
        .awprot  (m_axi_awprot),
        .awvalid (m_axi_awvalid),
        .awready (m_axi_awready),
        .wdata   (m_axi_wdata),
        .wstrb   (m_axi_wstrb),
        .wlast   (m_axi_wlast),
        .wvalid  (m_axi_wvalid),
        .wready  (m_axi_wready),
        .bid     (m_axi_bid),
        .bresp   (m_axi_bresp),
        .bvalid  (m_axi_bvalid),
        .bready  (m_axi_bready),
        .arid    (m_axi_arid),
        .araddr  (m_axi_araddr),
        .arlen   (m_axi_arlen),
        .arsize  (m_axi_arsize),
        .arburst (m_axi_arburst),
        .arlock  (m_axi_arlock),
        .arprot  (m_axi_arprot),
        .arvalid (m_axi_arvalid),
        .arready (m_axi_arready),
        .rid     (m_axi_rid),
        .rdata   (m_axi_rdata),
        .rresp   (m_axi_rresp),
        .rlast   (m_axi_rlast),
        .rvalid  (m_axi_rvalid),
        .rready  (m_axi_rready)
    );

    // Request-activity pulse-counter mirrors for sequences (no-activity
    // security-gating evidence without tb_top hierarchy access).
    assign u_tb_if.smc_axi_awvalid_count      = smc_axi_awvalid_count;
    assign u_tb_if.smc_axi_wvalid_count       = smc_axi_wvalid_count;
    assign u_tb_if.smc_axi_arvalid_count      = smc_axi_arvalid_count;
    assign u_tb_if.smc_otp_axil_awvalid_count = smc_otp_axil_awvalid_count;
    assign u_tb_if.smc_otp_axil_wvalid_count  = smc_otp_axil_wvalid_count;
    assign u_tb_if.smc_otp_axil_arvalid_count = smc_otp_axil_arvalid_count;

    // SEP OTP AXI-Lite responder: still idle-ready, never responding (no
    // sep_otp traffic is generated by the UVM flow yet — documented stretch).
    assign sep_otp_axil_awready = 1'b1;
    assign sep_otp_axil_wready  = 1'b1;
    assign sep_otp_axil_bresp   = 2'b00;
    assign sep_otp_axil_bvalid  = 1'b0;
    assign sep_otp_axil_arready = 1'b1;
    assign sep_otp_axil_rdata   = 32'h0;
    assign sep_otp_axil_rresp   = 2'b00;
    assign sep_otp_axil_rvalid  = 1'b0;

    // XTRIG AXI-Lite subordinate: no CSR traffic.
    assign xtrig_axil_awaddr  = 32'h0;
    assign xtrig_axil_awprot  = 3'b000;
    assign xtrig_axil_awvalid = 1'b0;
    assign xtrig_axil_wdata   = 32'h0;
    assign xtrig_axil_wstrb   = 4'h0;
    assign xtrig_axil_wvalid  = 1'b0;
    assign xtrig_axil_bready  = 1'b0;
    assign xtrig_axil_araddr  = 32'h0;
    assign xtrig_axil_arprot  = 3'b000;
    assign xtrig_axil_arvalid = 1'b0;
    assign xtrig_axil_rready  = 1'b0;

    // Cross-trigger CTM/CTP stimulus inputs: quiescent.
    assign xtrig_ctm_src_ack     = '0;
    assign xtrig_ctm_dst_req     = '0;
    assign xtrig_ctp_req_out_din = '0;
    assign xtrig_ctp_req_in_din  = '0;
    assign xtrig_ctp_ack_in_din  = '0;
    assign xtrig_ctp_ack_out_din = '0;

    // Non-reusable test classes compile as part of this top (module scope).
    `include "dtp_tests.sv"

    initial begin
        uvm_config_db#(virtual ocah_jtag_if)::set(null, "*", "jtag_vif", u_jtag_if);
        uvm_config_db#(virtual dtp_tb_if)::set(null, "*", "tb_vif", u_tb_if);
        uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "smc_otp_axil_vif", u_smc_otp_axil_if);
        uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "smc_otp_slave_vif", u_smc_otp_slave_if);
        uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "m_axi_vif", u_m_axi_if);
        run_test();
    end
`endif

endmodule : dtp_uvm_top
