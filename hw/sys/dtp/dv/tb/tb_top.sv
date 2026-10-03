// SPDX-License-Identifier: Apache-2.0
//
// DTP (Debug & Test Ports) open-source testbench top, shared by the cocotb
// (PyUVM) and SystemVerilog UVM flows as ONE framework-neutral core: the
// module has no ports. It instantiates the TB interfaces, the DUT, the
// struct <-> flat-signal adapters, the request-activity, READY-stall,
// reset, and stop_clks change counters, the functional-coverage modules,
// and the protocol SVA checkers; both frameworks consume the same
// interface instances.
//
//   * dtp_tb_if     control domain: system clock and resets, lifecycle
//                   dbg_disable, TAP-state and debug-TDR observables,
//                   request-activity and READY-stall counters, SVA enables.
//   * dtp_scan_if   scan domain: boundary-scan, iJTAG SIB, and STAP host
//                   scan controls, forwarded STAP TAP pins, downstream-TAP
//                   attach enables.
//   * dtp_xtrig_if  cross-trigger domain: CTM req/ack pairs and CTP pad
//                   quartets.
//   * ocah_jtag_if  the primary TAP and one downstream TAP per STAP port.
//   * ocah_axi_if   one active and one passive instance per DTP bus at the
//                   interface's default geometry (the SV-UVM layer sees one
//                   virtual type; cocotb binds them through OcahAxiConfig at
//                   the real bus geometry).
//
// cocotb (`--dut dtp`) drives the clock, resets, and stimulus members by
// hierarchical handle and attaches its BFMs to the interface scopes. The
// `UVM` define (`--framework uvm`) adds the harness block at the end of the
// module: the clock generator, the test classes, the uvm_config_db
// publication of every instance, and run_test().
//
// Exposes the DTP DUT's primary JTAG TAP at pin level so the shared JTAG
// master can drive it, plus system clock/reset. The JTAG TAP FSM lives
// *inside* `dtp` (jtag_tap_ctrlr in jtag_intf_unit), so the client port is
// the decoded {tms,trst_n,tck} struct plus tdi/tdo -- effectively raw JTAG
// pins.
//
// The BSR scan chain is looped back (scan_in = scan_out). Each iJTAG SIB
// drives an instrument stub: a scan register of a distinct width (4, 5, 6
// bits) that captures its own update register, so open-SIB subsets have
// unique chain lengths and a value written through an open SIB reads back
// on the next scan. The extended STAP host scan loops scan_out back onto
// scan_in by default; dtp_scan_if.stap_host_seg_en instead inserts a 7-bit
// scan register of the same kind, the host segment, so a scan shows which
// return path the PTAP takes. Each STAP host port loops its TDO back onto
// its TDI by default; the per-port dtp_scan_if.stap_<x>_ds_en instead
// splices the downstream ocah_jtag_if TAP behind the port, so the
// STAP-selection scenarios prove forwarding against a real IEEE 1149.1
// device. The JTAG2AXI and SMC/SEP OTP AXI-Lite managers are answered by the
// shared AXI responders on their slave interfaces, the XTRIG CSR AXI-Lite
// port is driven by the shared AXI-Lite master, and the cross-trigger
// CTM/CTP pins and clock-stop requests ride dtp_xtrig_if and dtp_tb_if.

`timescale 1ps / 1fs

module dtp_uvm_top
  import prim_jtag_pkg::*;
  import jtag_tap_pkg::*;
  import jtag_inst_reg_pkg::*;
  import dtp_pkg::*;
();

  // ------------------------------------------------------------------
  // TB nets between the interface members and the DUT pins
  // ------------------------------------------------------------------
  // System clock and resets, from dtp_tb_if.
  logic clk_i;
  logic rst_n_i;
  logic pwr_on_rst_ni;

  // Primary JTAG TAP pins, from ocah_jtag_if.
  logic jtag_tck;
  logic jtag_tms;
  logic jtag_trst;  // active-low TAP reset
  logic jtag_tdi;
  logic jtag_tdo;
  logic jtag_tdo_oen;

  // TAP state observation for IEEE 1149.1 FSM checks, mirrored to dtp_tb_if.
  tap_state_e jtag_ptap_state;
  jtag_instruction_decoded_e jtag_ptap_inst_decoded;

  // Flattened scan-control observables for DTP-local scan models/checkers.
  logic jtag_bsr_select;
  logic jtag_bsr_shift_en;
  logic jtag_bsr_capture_en;
  logic jtag_bsr_update_en;
  logic jtag_bsr_run_test_idle;
  logic jtag_bsr_test_logic_reset;
  logic jtag_bsr_runbist;
  logic jtag_bsr_chrst_n;
  logic jtag_ijtag_select;
  logic jtag_ijtag_shift_en;
  logic jtag_ijtag_capture_en;
  logic jtag_ijtag_update_en;
  logic jtag_dft_secure_select;
  logic jtag_dft_secure_shift_en;
  logic jtag_dft_secure_capture_en;
  logic jtag_dft_secure_update_en;
  logic jtag_dft_select;
  logic jtag_dft_shift_en;
  logic jtag_dft_capture_en;
  logic jtag_dft_update_en;
  logic jtag_dft_run_test_idle;
  logic jtag_dft_test_logic_reset;
  logic jtag_dft_runbist;
  logic jtag_dfd_select;
  logic jtag_dfd_shift_en;
  logic jtag_dfd_capture_en;
  logic jtag_dfd_update_en;
  logic jtag_stap_host_select;
  logic jtag_stap_host_shift_en;
  logic jtag_stap_host_capture_en;
  logic jtag_stap_host_update_en;
  logic jtag_stap_io_tms;
  logic jtag_stap_io_tck;
  logic jtag_stap_io_trst_n;
  logic jtag_stap_io_tdo_oen;
  logic jtag_stap_smc_tms;
  logic jtag_stap_smc_tck;
  logic jtag_stap_smc_trst_n;
  logic jtag_stap_smc_tdo_oen;
  logic jtag_stap_sep_tms;
  logic jtag_stap_sep_tck;
  logic jtag_stap_sep_trst_n;
  logic jtag_stap_sep_tdo_oen;
  logic jtag_stap_extra0_tms;
  logic jtag_stap_extra0_tck;
  logic jtag_stap_extra0_trst_n;
  logic jtag_stap_extra0_tdo_oen;

  // Downstream STAP TAP attachment per host port: the host TDO (the
  // downstream TAP's TDI), the downstream TAP's TDO back into the host TDI,
  // and the attach enable from dtp_scan_if. With ds_en=0 the host TDI is
  // the port's own TDO (wire loopback); with ds_en=1 the downstream
  // ocah_jtag_if device answers behind the port.
  logic jtag_stap_io_tdo;
  logic jtag_stap_io_tdi;
  logic jtag_stap_io_ds_en;
  logic jtag_stap_smc_tdo;
  logic jtag_stap_smc_tdi;
  logic jtag_stap_smc_ds_en;
  logic jtag_stap_sep_tdo;
  logic jtag_stap_sep_tdi;
  logic jtag_stap_sep_ds_en;
  logic jtag_stap_extra0_tdo;
  logic jtag_stap_extra0_tdi;
  logic jtag_stap_extra0_ds_en;

  // DEBUG_CONTROL / IC_RESET observables and CLA clock-stop stimulus.
  logic [dtp_dv_cfg_pkg::NumClkStopReq-1:0] xtrig_clk_stop_req = '0;
  logic stop_clks;
  logic cla_clock_stop_en;
  logic jtag_boot_stall_ovrd;
  logic jtag_boot_stall;
  logic jtag_ic_reset_smc_ovrd;
  logic jtag_ic_reset_smc_ctrl_n;
  logic jtag_ic_reset_sep_ovrd;
  logic jtag_ic_reset_sep_ctrl_n;
  logic jtag_ic_reset_ext_ovrd;
  logic jtag_ic_reset_ext_ctrl_n;

  // SMC AXI request-valid pulse counters for no-activity security checks.
  logic [31:0] smc_axi_awvalid_count;
  logic [31:0] smc_axi_wvalid_count;
  logic [31:0] smc_axi_arvalid_count;

  // OTP AXI-Lite request-valid pulse counters for no-activity checks.
  logic [31:0] smc_otp_axil_awvalid_count;
  logic [31:0] smc_otp_axil_wvalid_count;
  logic [31:0] smc_otp_axil_arvalid_count;
  logic [31:0] sep_otp_axil_awvalid_count;
  logic [31:0] sep_otp_axil_wvalid_count;
  logic [31:0] sep_otp_axil_arvalid_count;

  // JTAG2AXI bridge-port READY-stall counters: cycles a request VALID waits
  // on a low READY while dtp_tb_if.axi_sva_en is set, the antecedent of the
  // port's ocah_axi_sva VALID_HELD and PAYLOAD_STABLE rules.
  logic [31:0] smc_axi_aw_stall_count;
  logic [31:0] smc_axi_w_stall_count;
  logic [31:0] smc_axi_ar_stall_count;
  logic [31:0] smc_otp_axil_aw_stall_count;
  logic [31:0] smc_otp_axil_w_stall_count;
  logic [31:0] smc_otp_axil_ar_stall_count;
  logic [31:0] sep_otp_axil_aw_stall_count;
  logic [31:0] sep_otp_axil_w_stall_count;
  logic [31:0] sep_otp_axil_ar_stall_count;

  // SMC OTP AXI-Lite manager flattened for the shared ocah_axi_vip responder.
  logic [dtp_dv_cfg_pkg::OtpAxilAddrWidth-1:0] smc_otp_axil_awaddr;
  logic [2:0] smc_otp_axil_awprot;
  logic smc_otp_axil_awvalid;
  logic smc_otp_axil_awready;
  logic [dtp_dv_cfg_pkg::OtpAxilDataWidth-1:0] smc_otp_axil_wdata;
  logic [dtp_dv_cfg_pkg::OtpAxilDataWidth/8-1:0] smc_otp_axil_wstrb;
  logic smc_otp_axil_wvalid;
  logic smc_otp_axil_wready;
  logic [1:0] smc_otp_axil_bresp;
  logic smc_otp_axil_bvalid;
  logic smc_otp_axil_bready;
  logic [dtp_dv_cfg_pkg::OtpAxilAddrWidth-1:0] smc_otp_axil_araddr;
  logic [2:0] smc_otp_axil_arprot;
  logic smc_otp_axil_arvalid;
  logic smc_otp_axil_arready;
  logic [dtp_dv_cfg_pkg::OtpAxilDataWidth-1:0] smc_otp_axil_rdata;
  logic [1:0] smc_otp_axil_rresp;
  logic smc_otp_axil_rvalid;
  logic smc_otp_axil_rready;

  // SEP OTP AXI-Lite manager flattened for the TB responder.
  logic [dtp_dv_cfg_pkg::OtpAxilAddrWidth-1:0] sep_otp_axil_awaddr;
  logic [2:0] sep_otp_axil_awprot;
  logic sep_otp_axil_awvalid;
  logic sep_otp_axil_awready;
  logic [dtp_dv_cfg_pkg::OtpAxilDataWidth-1:0] sep_otp_axil_wdata;
  logic [dtp_dv_cfg_pkg::OtpAxilDataWidth/8-1:0] sep_otp_axil_wstrb;
  logic sep_otp_axil_wvalid;
  logic sep_otp_axil_wready;
  logic [1:0] sep_otp_axil_bresp;
  logic sep_otp_axil_bvalid;
  logic sep_otp_axil_bready;
  logic [dtp_dv_cfg_pkg::OtpAxilAddrWidth-1:0] sep_otp_axil_araddr;
  logic [2:0] sep_otp_axil_arprot;
  logic sep_otp_axil_arvalid;
  logic sep_otp_axil_arready;
  logic [dtp_dv_cfg_pkg::OtpAxilDataWidth-1:0] sep_otp_axil_rdata;
  logic [1:0] sep_otp_axil_rresp;
  logic sep_otp_axil_rvalid;
  logic sep_otp_axil_rready;

  // XTRIG AXI-Lite subordinate flattened for the shared ocah_axi_vip master.
  logic [31:0] xtrig_axil_awaddr;
  logic [2:0] xtrig_axil_awprot;
  logic xtrig_axil_awvalid;
  logic xtrig_axil_awready;
  logic [31:0] xtrig_axil_wdata;
  logic [3:0] xtrig_axil_wstrb;
  logic xtrig_axil_wvalid;
  logic xtrig_axil_wready;
  logic [1:0] xtrig_axil_bresp;
  logic xtrig_axil_bvalid;
  logic xtrig_axil_bready;
  logic [31:0] xtrig_axil_araddr;
  logic [2:0] xtrig_axil_arprot;
  logic xtrig_axil_arvalid;
  logic xtrig_axil_arready;
  logic [31:0] xtrig_axil_rdata;
  logic [1:0] xtrig_axil_rresp;
  logic xtrig_axil_rvalid;
  logic xtrig_axil_rready;
  logic [31:0] xtrig_axil_awvalid_count;
  logic [31:0] xtrig_axil_wvalid_count;
  logic [31:0] xtrig_axil_arvalid_count;
  logic [31:0] xtrig_axil_aw_stall_count;
  logic [31:0] xtrig_axil_ar_stall_count;
  logic [31:0] xtrig_axil_w_stall_count;
  // Accepted AWs awaiting their W beat and accepted ARs awaiting their R beat
  // at the XTRIG CSR port. AXI4-Lite pairs the n-th W with the n-th AW, so a
  // W accepted ahead of its AW counts negative.
  int xtrig_axil_aw_open;
  int xtrig_axil_ar_open;
  logic [31:0] xtrig_axil_aw_open_stall_count;
  logic [31:0] xtrig_axil_aw_open_accept_count;
  logic [31:0] xtrig_axil_ar_open_stall_count;
  logic [31:0] xtrig_axil_ar_open_accept_count;
  // Handshakes of the crossbar demux behind the XTRIG CSR port's spill
  // registers: AW, W and AR leave their spill registers there, and B and R
  // enter theirs.
  wire xtrig_dmx_aw_valid = u_dut.u_cross_trigger_network.u_axil_xbar.gen_slv_port_demux[0].i_axi_lite_demux.gen_demux.slv_aw_valid;
  wire xtrig_dmx_aw_ready = u_dut.u_cross_trigger_network.u_axil_xbar.gen_slv_port_demux[0].i_axi_lite_demux.gen_demux.slv_aw_ready;
  wire xtrig_dmx_w_valid  = u_dut.u_cross_trigger_network.u_axil_xbar.gen_slv_port_demux[0].i_axi_lite_demux.gen_demux.slv_w_valid;
  wire xtrig_dmx_w_ready  = u_dut.u_cross_trigger_network.u_axil_xbar.gen_slv_port_demux[0].i_axi_lite_demux.gen_demux.slv_w_ready;
  wire xtrig_dmx_b_valid  = u_dut.u_cross_trigger_network.u_axil_xbar.gen_slv_port_demux[0].i_axi_lite_demux.gen_demux.slv_b_valid;
  wire xtrig_dmx_b_ready  = u_dut.u_cross_trigger_network.u_axil_xbar.gen_slv_port_demux[0].i_axi_lite_demux.gen_demux.slv_b_ready;
  wire xtrig_dmx_ar_valid = u_dut.u_cross_trigger_network.u_axil_xbar.gen_slv_port_demux[0].i_axi_lite_demux.gen_demux.slv_ar_valid;
  wire xtrig_dmx_ar_ready = u_dut.u_cross_trigger_network.u_axil_xbar.gen_slv_port_demux[0].i_axi_lite_demux.gen_demux.slv_ar_ready;
  wire xtrig_dmx_r_valid  = u_dut.u_cross_trigger_network.u_axil_xbar.gen_slv_port_demux[0].i_axi_lite_demux.gen_demux.slv_r_valid;
  wire xtrig_dmx_r_ready  = u_dut.u_cross_trigger_network.u_axil_xbar.gen_slv_port_demux[0].i_axi_lite_demux.gen_demux.slv_r_ready;
  wire xtrig_dmx_aw_hs = xtrig_dmx_aw_valid & xtrig_dmx_aw_ready;
  wire xtrig_dmx_w_hs  = xtrig_dmx_w_valid & xtrig_dmx_w_ready;
  wire xtrig_dmx_b_hs  = xtrig_dmx_b_valid & xtrig_dmx_b_ready;
  wire xtrig_dmx_ar_hs = xtrig_dmx_ar_valid & xtrig_dmx_ar_ready;
  wire xtrig_dmx_r_hs  = xtrig_dmx_r_valid & xtrig_dmx_r_ready;
  wire xtrig_port_aw_hs = xtrig_axil_awvalid & xtrig_axil_awready;
  wire xtrig_port_w_hs  = xtrig_axil_wvalid & xtrig_axil_wready;
  wire xtrig_port_b_hs  = xtrig_axil_bvalid & xtrig_axil_bready;
  wire xtrig_port_ar_hs = xtrig_axil_arvalid & xtrig_axil_arready;
  wire xtrig_port_r_hs  = xtrig_axil_rvalid & xtrig_axil_rready;
  // Beats each CSR port spill register holds: those that entered it minus
  // those that left it.
  int xtrig_spill_aw_occ;
  int xtrig_spill_w_occ;
  int xtrig_spill_b_occ;
  int xtrig_spill_ar_occ;
  int xtrig_spill_r_occ;
  // A spill register whose input READY differs from holding fewer than two
  // beats, or whose output VALID differs from holding a beat.
  wire xtrig_spill_err =
      (xtrig_axil_awready != (xtrig_spill_aw_occ < 2))
      || (xtrig_dmx_aw_valid != (xtrig_spill_aw_occ > 0))
      || (xtrig_axil_wready != (xtrig_spill_w_occ < 2))
      || (xtrig_dmx_w_valid != (xtrig_spill_w_occ > 0))
      || (xtrig_dmx_b_ready != (xtrig_spill_b_occ < 2))
      || (xtrig_axil_bvalid != (xtrig_spill_b_occ > 0))
      || (xtrig_axil_arready != (xtrig_spill_ar_occ < 2))
      || (xtrig_dmx_ar_valid != (xtrig_spill_ar_occ > 0))
      || (xtrig_dmx_r_ready != (xtrig_spill_r_occ < 2))
      || (xtrig_axil_rvalid != (xtrig_spill_r_occ > 0));
  // Accepted AWs awaiting their W beat and accepted ARs awaiting their R beat
  // at the demux handshake. The demux queues a locked AW's port selection
  // before its handshake, so a W that passes ahead of its AW counts negative.
  int xtrig_demux_aw_open;
  int xtrig_demux_ar_open;
  logic [31:0] xtrig_axil_spill_err_count;
  logic [31:0] xtrig_axil_w_spill_full_count;
  logic [31:0] xtrig_axil_r_spill_full_count;
  logic [31:0] xtrig_demux_aw_stall_count;
  logic [31:0] xtrig_demux_w_stall_count;
  logic [31:0] xtrig_demux_ar_stall_count;
  logic [31:0] xtrig_demux_aw_open_stall_count;
  logic [31:0] xtrig_demux_aw_open_accept_count;
  logic [31:0] xtrig_demux_ar_open_stall_count;
  logic [31:0] xtrig_demux_ar_open_accept_count;

  // XTRIG CTM and CTP GPIO stimulus and observables, from dtp_xtrig_if.
  logic [dtp_dv_cfg_pkg::NumIntCt-1:0] xtrig_ctm_src_req;
  logic [dtp_dv_cfg_pkg::NumIntCt-1:0] xtrig_ctm_src_ack;
  logic [dtp_dv_cfg_pkg::NumIntCt-1:0] xtrig_ctm_dst_req;
  logic [dtp_dv_cfg_pkg::NumIntCt-1:0] xtrig_ctm_dst_ack;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0] xtrig_ctp_req_out_dout;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0] xtrig_ctp_req_out_dout_en;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0] xtrig_ctp_req_out_din;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0] xtrig_ctp_req_out_din_en;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0] xtrig_ctp_req_in_dout;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0] xtrig_ctp_req_in_dout_en;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0] xtrig_ctp_req_in_din;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0] xtrig_ctp_req_in_din_en;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0] xtrig_ctp_ack_in_dout;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0] xtrig_ctp_ack_in_dout_en;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0] xtrig_ctp_ack_in_din;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0] xtrig_ctp_ack_in_din_en;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0] xtrig_ctp_ack_out_dout;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0] xtrig_ctp_ack_out_dout_en;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0] xtrig_ctp_ack_out_din;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0] xtrig_ctp_ack_out_din_en;
  // CT_Req_out shared wires (ocah_open_drain_bus): a private wire per pad
  // with one chiplet driver, or the group wire the pads in
  // xtrig_ctp_wire_group share; the receive pulse of every port.
  logic [dtp_dv_cfg_pkg::NumCtp-1:0] xtrig_ctp_wire_private;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0] xtrig_ctp_wire_private_mismatch;
  logic                              xtrig_ctp_wire_group_wire;
  logic                              xtrig_ctp_wire_group_mismatch;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0] xtrig_ctp_ct_dst;
  logic [dtp_dv_cfg_pkg::NumIntCt-1:0] xtrig_int_ct_dst;
  // CONFIG.INVERT of every external CTP, from its register field.
  logic [dtp_dv_cfg_pkg::NumCtp-1:0] xtrig_ctp_invert;

  // ------------------------------------------------------------------
  // TB interfaces: both frameworks bind to these instances (SV-UVM through
  // uvm_config_db, cocotb through hierarchical handles).
  // ------------------------------------------------------------------
  dtp_tb_if u_tb_if ();
  dtp_scan_if u_scan_if ();
  dtp_xtrig_if u_xtrig_if ();
  ocah_jtag_if u_jtag_if ();
  ocah_jtag_if u_stap_io_ds_if ();
  ocah_jtag_if u_stap_smc_ds_if ();
  ocah_jtag_if u_stap_sep_ds_if ();
  ocah_jtag_if u_stap_extra0_ds_if ();
  // Active (responder- or initiator-driven) and passive (monitor) AXI
  // instances per bus.
  ocah_axi_if u_smc_otp_slave_if (
    .aclk(clk_i),
    .aresetn(rst_n_i)
  );
  ocah_axi_if u_smc_otp_axil_if (
    .aclk(clk_i),
    .aresetn(rst_n_i)
  );
  ocah_axi_if u_sep_otp_slave_if (
    .aclk(clk_i),
    .aresetn(rst_n_i)
  );
  ocah_axi_if u_sep_otp_axil_if (
    .aclk(clk_i),
    .aresetn(rst_n_i)
  );
  ocah_axi_if u_smc_axi_slave_if (
    .aclk(clk_i),
    .aresetn(rst_n_i)
  );
  ocah_axi_if u_m_axi_if (
    .aclk(clk_i),
    .aresetn(rst_n_i)
  );
  ocah_axi_if u_xtrig_master_if (
    .aclk(clk_i),
    .aresetn(rst_n_i)
  );
  ocah_axi_if u_xtrig_axil_if (
    .aclk(clk_i),
    .aresetn(rst_n_i)
  );

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
  // Scan-chain nets: boundary scan loops scan_in <- scan_out (zero-length
  // passthrough); the extended STAP scan loops the same way or runs
  // through the host segment; each iJTAG host scan chain runs through an
  // instrument stub.
  // ------------------------------------------------------------------
  jtag_scan_ctrl_t jtag_bsr_host_scan_ctrl;
  jtag_scan_ctrl_t jtag_stap_host_scan_ctrl;
  jtag_scan_ctrl_t jtag_dfd_host_scan_ctrl;
  jtag_scan_ctrl_t jtag_dft_secure_host_scan_ctrl;
  jtag_scan_ctrl_t jtag_dft_host_scan_ctrl;
  logic bsr_scan_out;
  logic stap_host_scan_out;
  logic dfd_scan_out;
  logic dfd_scan_in;
  logic dft_secure_scan_out;
  logic dft_secure_scan_in;
  logic dft_scan_out;
  logic dft_scan_in;

  // iJTAG instrument stubs, one per SIB host chain. Distinct widths give
  // every open-SIB subset a unique chain length; each stub captures its own
  // update register, so the value shifted through an open SIB on one scan
  // is the capture of the next. The widths are mirrored in the scan models
  // (env/dtp_scan_ref_model.py, dtp_types.svh).
  localparam int unsigned IjtagDftSecureInstrumentWidth = 4;
  localparam int unsigned IjtagDftInstrumentWidth = 5;
  localparam int unsigned IjtagDfdInstrumentWidth = 6;
  logic [IjtagDftSecureInstrumentWidth-1:0] dft_secure_instrument_q;
  logic [IjtagDftInstrumentWidth-1:0] dft_instrument_q;
  logic [IjtagDfdInstrumentWidth-1:0] dfd_instrument_q;

  prim_jtag_scan_reg #(
    .WIDTH    (IjtagDftSecureInstrumentWidth),
    .RESET_VAL('0)
  ) u_dft_secure_instrument (
    .scan_ctrl_i(jtag_dft_secure_host_scan_ctrl),
    .scan_in_i  (dft_secure_scan_out),
    .scan_out_o (dft_secure_scan_in),
    .data_in_i  (dft_secure_instrument_q),
    .data_out_o (dft_secure_instrument_q)
  );

  prim_jtag_scan_reg #(
    .WIDTH    (IjtagDftInstrumentWidth),
    .RESET_VAL('0)
  ) u_dft_instrument (
    .scan_ctrl_i(jtag_dft_host_scan_ctrl),
    .scan_in_i  (dft_scan_out),
    .scan_out_o (dft_scan_in),
    .data_in_i  (dft_instrument_q),
    .data_out_o (dft_instrument_q)
  );

  prim_jtag_scan_reg #(
    .WIDTH    (IjtagDfdInstrumentWidth),
    .RESET_VAL('0)
  ) u_dfd_instrument (
    .scan_ctrl_i(jtag_dfd_host_scan_ctrl),
    .scan_in_i  (dfd_scan_out),
    .scan_out_o (dfd_scan_in),
    .data_in_i  (dfd_instrument_q),
    .data_out_o (dfd_instrument_q)
  );

  // Extended STAP host segment on the gated host scan control, the TDO end
  // of the TAP_3DCR chain while the PTAP 3DCR select is set: it captures
  // its own update register, which resets in Test-Logic-Reset. The width
  // is mirrored in the STAP chain models (env/dtp_scan_ref_model.py,
  // dtp_types.svh).
  localparam int unsigned StapHostSegmentWidth = 7;
  logic [StapHostSegmentWidth-1:0] stap_host_segment_q;
  logic stap_host_segment_out;
  logic stap_host_scan_in;

  prim_jtag_scan_reg #(
    .WIDTH    (StapHostSegmentWidth),
    .RESET_VAL('0)
  ) u_stap_host_segment (
    .scan_ctrl_i(jtag_stap_host_scan_ctrl),
    .scan_in_i  (stap_host_scan_out),
    .scan_out_o (stap_host_segment_out),
    .data_in_i  (stap_host_segment_q),
    .data_out_o (stap_host_segment_q)
  );

  assign stap_host_scan_in = u_scan_if.stap_host_seg_en ? stap_host_segment_out
                                                        : stap_host_scan_out;

  // STAP TAP host ports: tdi <- tdo loopback, or the attached downstream
  // TAP's TDO when the port's ds_en is set.
  jtag_tap_ctrl_t stap_io_tap_ctrl;
  jtag_tap_ctrl_t stap_smc_tap_ctrl;
  jtag_tap_ctrl_t stap_sep_tap_ctrl;
  jtag_tap_ctrl_t stap_extra_tap_ctrl [0:0];
  logic stap_io_tdo;
  logic stap_smc_tdo;
  logic stap_sep_tdo;
  logic stap_extra_tdo  [0:0];
  logic stap_extra_tdo_oen [0:0];
  logic stap_io_host_tdi;
  logic stap_smc_host_tdi;
  logic stap_sep_host_tdi;
  logic stap_extra_host_tdi [0:0];

  assign jtag_stap_io_tdo     = stap_io_tdo;
  assign jtag_stap_smc_tdo    = stap_smc_tdo;
  assign jtag_stap_sep_tdo    = stap_sep_tdo;
  assign jtag_stap_extra0_tdo = stap_extra_tdo[0];
  assign stap_io_host_tdi      = jtag_stap_io_ds_en     ? jtag_stap_io_tdi     : stap_io_tdo;
  assign stap_smc_host_tdi     = jtag_stap_smc_ds_en    ? jtag_stap_smc_tdi    : stap_smc_tdo;
  assign stap_sep_host_tdi     = jtag_stap_sep_ds_en    ? jtag_stap_sep_tdi    : stap_sep_tdo;
  assign stap_extra_host_tdi[0] = jtag_stap_extra0_ds_en ? jtag_stap_extra0_tdi : stap_extra_tdo[0];

  // IC_RESET slice structs: the bench's one `{ovrd, val}` pair per slice
  // (dtp_dv_cfg_pkg), flattened for sampling.
  dtp_dv_cfg_pkg::ic_reset_smc_t jtag_ic_reset_smc;
  dtp_dv_cfg_pkg::ic_reset_sep_t jtag_ic_reset_sep;
  dtp_dv_cfg_pkg::ic_reset_ext_t jtag_ic_reset_ext;
  sep_lifecycle_ctrl_pkg::dbg_disable_t dbg_disable;

  assign jtag_bsr_select     = jtag_bsr_host_scan_ctrl.select;
  assign jtag_bsr_shift_en   = jtag_bsr_host_scan_ctrl.shift_en;
  assign jtag_bsr_capture_en = jtag_bsr_host_scan_ctrl.capture_en;
  assign jtag_bsr_update_en  = jtag_bsr_host_scan_ctrl.update_en;
  assign jtag_bsr_run_test_idle    = jtag_bsr_host_scan_ctrl.run_test_idle;
  assign jtag_bsr_test_logic_reset = jtag_bsr_host_scan_ctrl.test_logic_reset;
  assign jtag_bsr_runbist          = jtag_bsr_host_scan_ctrl.runbist;
  assign jtag_bsr_chrst_n          = jtag_bsr_host_scan_ctrl.chrst_n;
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
  assign jtag_dft_run_test_idle    = jtag_dft_host_scan_ctrl.run_test_idle;
  assign jtag_dft_test_logic_reset = jtag_dft_host_scan_ctrl.test_logic_reset;
  assign jtag_dft_runbist          = jtag_dft_host_scan_ctrl.runbist;
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



  // ------------------------------------------------------------------
  // SMC fabric debug AXI4 manager: struct <-> flat-signal adapter so the
  // JTAG2AXI bridge talks to the shared AXI responder on u_smc_axi_slave_if.
  // The bridge types and widths are the bench configuration's.
  // ------------------------------------------------------------------
  dtp_dv_cfg_pkg::smc_axi_req_t   axi_smc_dbg_req;
  dtp_dv_cfg_pkg::smc_axi_resp_t  axi_smc_dbg_resp;
  dtp_dv_cfg_pkg::otp_axil_req_t  axil_smc_otp_jtag_req;
  dtp_dv_cfg_pkg::otp_axil_resp_t axil_smc_otp_jtag_resp;
  dtp_dv_cfg_pkg::otp_axil_req_t  axil_sep_otp_jtag_req;
  dtp_dv_cfg_pkg::otp_axil_resp_t axil_sep_otp_jtag_resp;
  // AxSIZE of every OTP AXI-Lite beat: the full data width.
  localparam logic [2:0] OtpAxilBeatSize = 3'($clog2(dtp_dv_cfg_pkg::OtpAxilDataWidth / 8));
  dtp_axil_32_32_req_t            axil_xtrig_req;
  dtp_axil_32_32_resp_t           axil_xtrig_resp;

  // Write address channel
  logic [dtp_dv_cfg_pkg::SmcAxiIdWidth-1:0] m_axi_awid;
  logic [dtp_dv_cfg_pkg::SmcAxiAddrWidth-1:0] m_axi_awaddr;
  logic [7:0]   m_axi_awlen;
  logic [2:0]   m_axi_awsize;
  logic [1:0]   m_axi_awburst;
  logic         m_axi_awlock;
  logic [3:0]   m_axi_awcache;
  logic [2:0]   m_axi_awprot;
  logic [3:0]   m_axi_awqos;
  logic [3:0]   m_axi_awregion;
  logic [dtp_dv_cfg_pkg::SmcAxiUserWidth-1:0] m_axi_awuser;
  logic         m_axi_awvalid;
  logic         m_axi_awready;
  // Write data channel
  logic [dtp_dv_cfg_pkg::SmcAxiDataWidth-1:0] m_axi_wdata;
  logic [dtp_dv_cfg_pkg::SmcAxiDataWidth/8-1:0] m_axi_wstrb;
  logic         m_axi_wlast;
  logic [dtp_dv_cfg_pkg::SmcAxiUserWidth-1:0] m_axi_wuser;
  logic         m_axi_wvalid;
  logic         m_axi_wready;
  // Write response channel
  logic [dtp_dv_cfg_pkg::SmcAxiIdWidth-1:0] m_axi_bid;
  logic [1:0]   m_axi_bresp;
  logic [dtp_dv_cfg_pkg::SmcAxiUserWidth-1:0] m_axi_buser;
  logic         m_axi_bvalid;
  logic         m_axi_bready;
  // Read address channel
  logic [dtp_dv_cfg_pkg::SmcAxiIdWidth-1:0] m_axi_arid;
  logic [dtp_dv_cfg_pkg::SmcAxiAddrWidth-1:0] m_axi_araddr;
  logic [7:0]   m_axi_arlen;
  logic [2:0]   m_axi_arsize;
  logic [1:0]   m_axi_arburst;
  logic         m_axi_arlock;
  logic [3:0]   m_axi_arcache;
  logic [2:0]   m_axi_arprot;
  logic [3:0]   m_axi_arqos;
  logic [3:0]   m_axi_arregion;
  logic [dtp_dv_cfg_pkg::SmcAxiUserWidth-1:0] m_axi_aruser;
  logic         m_axi_arvalid;
  logic         m_axi_arready;
  // Read data channel
  logic [dtp_dv_cfg_pkg::SmcAxiIdWidth-1:0] m_axi_rid;
  logic [dtp_dv_cfg_pkg::SmcAxiDataWidth-1:0] m_axi_rdata;
  logic [1:0]   m_axi_rresp;
  logic         m_axi_rlast;
  logic [dtp_dv_cfg_pkg::SmcAxiUserWidth-1:0] m_axi_ruser;
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
      smc_axi_aw_stall_count <= '0;
      smc_axi_w_stall_count  <= '0;
      smc_axi_ar_stall_count <= '0;
    end else begin
      smc_axi_awvalid_count <= smc_axi_awvalid_count + {31'b0, m_axi_awvalid};
      smc_axi_wvalid_count  <= smc_axi_wvalid_count + {31'b0, m_axi_wvalid};
      smc_axi_arvalid_count <= smc_axi_arvalid_count + {31'b0, m_axi_arvalid};
      smc_axi_aw_stall_count <= smc_axi_aw_stall_count +
                {31'b0, u_tb_if.axi_sva_en & m_axi_awvalid & ~m_axi_awready};
      smc_axi_w_stall_count <= smc_axi_w_stall_count +
                {31'b0, u_tb_if.axi_sva_en & m_axi_wvalid & ~m_axi_wready};
      smc_axi_ar_stall_count <= smc_axi_ar_stall_count +
                {31'b0, u_tb_if.axi_sva_en & m_axi_arvalid & ~m_axi_arready};
    end
  end

  // Reset-assertion counters: observables the scoreboard predictors
  // re-baseline on (CSR shadow, TAP instruction) without an edge wait in
  // class code, assigned into dtp_tb_if in this core for both realizations.
  logic [31:0] sys_rst_assert_count = '0;
  logic [31:0] por_assert_count     = '0;
  always @(negedge rst_n_i) sys_rst_assert_count <= sys_rst_assert_count + 32'd1;
  always @(negedge pwr_on_rst_ni) por_assert_count <= por_assert_count + 32'd1;

  // stop_clks change counters while rst_n_i is high: every change, and the
  // changes at a time other than the latest clk_i rising edge. The rise time
  // takes a blocking assignment when the edge triggers, so a change that
  // edge's nonblocking update applies compares equal.
  realtime clk_i_rise_time = 0.0;
  logic [31:0] stop_clks_change_count   = '0;
  logic [31:0] stop_clks_off_edge_count = '0;
  always @(posedge clk_i) clk_i_rise_time = $realtime;
  always @(posedge stop_clks or negedge stop_clks) begin
    if (rst_n_i === 1'b1) begin
      stop_clks_change_count <= stop_clks_change_count + 32'd1;
      if ($realtime != clk_i_rise_time)
        stop_clks_off_edge_count <= stop_clks_off_edge_count + 32'd1;
    end
  end

  // Flat responder outputs -> DUT resp struct
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
      smc_otp_axil_aw_stall_count <= '0;
      smc_otp_axil_w_stall_count  <= '0;
      smc_otp_axil_ar_stall_count <= '0;
      sep_otp_axil_aw_stall_count <= '0;
      sep_otp_axil_w_stall_count  <= '0;
      sep_otp_axil_ar_stall_count <= '0;
      xtrig_axil_awvalid_count   <= '0;
      xtrig_axil_wvalid_count    <= '0;
      xtrig_axil_arvalid_count   <= '0;
      xtrig_axil_aw_stall_count  <= '0;
      xtrig_axil_ar_stall_count  <= '0;
      xtrig_axil_w_stall_count   <= '0;
      xtrig_axil_aw_open         <= 0;
      xtrig_axil_ar_open         <= 0;
      xtrig_axil_aw_open_stall_count  <= '0;
      xtrig_axil_aw_open_accept_count <= '0;
      xtrig_axil_ar_open_stall_count  <= '0;
      xtrig_axil_ar_open_accept_count <= '0;
      xtrig_spill_aw_occ <= 0;
      xtrig_spill_w_occ  <= 0;
      xtrig_spill_b_occ  <= 0;
      xtrig_spill_ar_occ <= 0;
      xtrig_spill_r_occ  <= 0;
      xtrig_demux_aw_open <= 0;
      xtrig_demux_ar_open <= 0;
      xtrig_axil_spill_err_count <= '0;
      xtrig_axil_w_spill_full_count <= '0;
      xtrig_axil_r_spill_full_count <= '0;
      xtrig_demux_aw_stall_count <= '0;
      xtrig_demux_w_stall_count  <= '0;
      xtrig_demux_ar_stall_count <= '0;
      xtrig_demux_aw_open_stall_count  <= '0;
      xtrig_demux_aw_open_accept_count <= '0;
      xtrig_demux_ar_open_stall_count  <= '0;
      xtrig_demux_ar_open_accept_count <= '0;
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
      smc_otp_axil_aw_stall_count <= smc_otp_axil_aw_stall_count +
                {31'b0, u_tb_if.axi_sva_en & smc_otp_axil_awvalid & ~smc_otp_axil_awready};
      smc_otp_axil_w_stall_count <= smc_otp_axil_w_stall_count +
                {31'b0, u_tb_if.axi_sva_en & smc_otp_axil_wvalid & ~smc_otp_axil_wready};
      smc_otp_axil_ar_stall_count <= smc_otp_axil_ar_stall_count +
                {31'b0, u_tb_if.axi_sva_en & smc_otp_axil_arvalid & ~smc_otp_axil_arready};
      sep_otp_axil_aw_stall_count <= sep_otp_axil_aw_stall_count +
                {31'b0, u_tb_if.axi_sva_en & sep_otp_axil_awvalid & ~sep_otp_axil_awready};
      sep_otp_axil_w_stall_count <= sep_otp_axil_w_stall_count +
                {31'b0, u_tb_if.axi_sva_en & sep_otp_axil_wvalid & ~sep_otp_axil_wready};
      sep_otp_axil_ar_stall_count <= sep_otp_axil_ar_stall_count +
                {31'b0, u_tb_if.axi_sva_en & sep_otp_axil_arvalid & ~sep_otp_axil_arready};
      xtrig_axil_awvalid_count <=
                xtrig_axil_awvalid_count + {31'b0, xtrig_axil_awvalid};
      xtrig_axil_wvalid_count <=
                xtrig_axil_wvalid_count + {31'b0, xtrig_axil_wvalid};
      xtrig_axil_arvalid_count <=
                xtrig_axil_arvalid_count + {31'b0, xtrig_axil_arvalid};
      xtrig_axil_aw_stall_count <=
                xtrig_axil_aw_stall_count + {31'b0, xtrig_axil_awvalid & ~xtrig_axil_awready};
      xtrig_axil_ar_stall_count <=
                xtrig_axil_ar_stall_count + {31'b0, xtrig_axil_arvalid & ~xtrig_axil_arready};
      xtrig_axil_w_stall_count <=
                xtrig_axil_w_stall_count + {31'b0, xtrig_axil_wvalid & ~xtrig_axil_wready};
      xtrig_axil_aw_open <= xtrig_axil_aw_open + int'(xtrig_axil_awvalid & xtrig_axil_awready)
                - int'(xtrig_axil_wvalid & xtrig_axil_wready);
      xtrig_axil_ar_open <= xtrig_axil_ar_open + int'(xtrig_axil_arvalid & xtrig_axil_arready)
                - int'(xtrig_axil_rvalid & xtrig_axil_rready);
      xtrig_axil_aw_open_stall_count <= xtrig_axil_aw_open_stall_count
                + {31'b0, xtrig_axil_awvalid & ~xtrig_axil_awready & (xtrig_axil_aw_open > 0)};
      xtrig_axil_aw_open_accept_count <= xtrig_axil_aw_open_accept_count
                + {31'b0, xtrig_axil_awvalid & xtrig_axil_awready
                   & (xtrig_axil_aw_open - int'(xtrig_axil_wvalid & xtrig_axil_wready) > 0)};
      xtrig_axil_ar_open_stall_count <= xtrig_axil_ar_open_stall_count
                + {31'b0, xtrig_axil_arvalid & ~xtrig_axil_arready & (xtrig_axil_ar_open > 0)};
      xtrig_axil_ar_open_accept_count <= xtrig_axil_ar_open_accept_count
                + {31'b0, xtrig_axil_arvalid & xtrig_axil_arready
                   & (xtrig_axil_ar_open - int'(xtrig_axil_rvalid & xtrig_axil_rready) > 0)};
      xtrig_spill_aw_occ <= xtrig_spill_aw_occ + int'(xtrig_port_aw_hs) - int'(xtrig_dmx_aw_hs);
      xtrig_spill_w_occ  <= xtrig_spill_w_occ + int'(xtrig_port_w_hs) - int'(xtrig_dmx_w_hs);
      xtrig_spill_b_occ  <= xtrig_spill_b_occ + int'(xtrig_dmx_b_hs) - int'(xtrig_port_b_hs);
      xtrig_spill_ar_occ <= xtrig_spill_ar_occ + int'(xtrig_port_ar_hs) - int'(xtrig_dmx_ar_hs);
      xtrig_spill_r_occ  <= xtrig_spill_r_occ + int'(xtrig_dmx_r_hs) - int'(xtrig_port_r_hs);
      xtrig_axil_spill_err_count <= xtrig_axil_spill_err_count + {31'b0, xtrig_spill_err};
      xtrig_axil_w_spill_full_count <=
                xtrig_axil_w_spill_full_count + {31'b0, xtrig_spill_w_occ == 2};
      xtrig_axil_r_spill_full_count <=
                xtrig_axil_r_spill_full_count + {31'b0, xtrig_spill_r_occ == 2};
      xtrig_demux_aw_stall_count <=
                xtrig_demux_aw_stall_count + {31'b0, xtrig_dmx_aw_valid & ~xtrig_dmx_aw_ready};
      xtrig_demux_w_stall_count <=
                xtrig_demux_w_stall_count + {31'b0, xtrig_dmx_w_valid & ~xtrig_dmx_w_ready};
      xtrig_demux_ar_stall_count <=
                xtrig_demux_ar_stall_count + {31'b0, xtrig_dmx_ar_valid & ~xtrig_dmx_ar_ready};
      xtrig_demux_aw_open <= xtrig_demux_aw_open + int'(xtrig_dmx_aw_hs) - int'(xtrig_dmx_w_hs);
      xtrig_demux_ar_open <= xtrig_demux_ar_open + int'(xtrig_dmx_ar_hs) - int'(xtrig_dmx_r_hs);
      xtrig_demux_aw_open_stall_count <= xtrig_demux_aw_open_stall_count
                + {31'b0, xtrig_dmx_aw_valid & ~xtrig_dmx_aw_ready & (xtrig_demux_aw_open > 0)};
      xtrig_demux_aw_open_accept_count <= xtrig_demux_aw_open_accept_count
                + {31'b0, xtrig_dmx_aw_hs & (xtrig_demux_aw_open - int'(xtrig_dmx_w_hs) > 0)};
      xtrig_demux_ar_open_stall_count <= xtrig_demux_ar_open_stall_count
                + {31'b0, xtrig_dmx_ar_valid & ~xtrig_dmx_ar_ready & (xtrig_demux_ar_open > 0)};
      xtrig_demux_ar_open_accept_count <= xtrig_demux_ar_open_accept_count
                + {31'b0, xtrig_dmx_ar_hs & (xtrig_demux_ar_open - int'(xtrig_dmx_r_hs) > 0)};
    end
  end

  // ------------------------------------------------------------------
  // DTP DUT, elaborated from the bench configuration (dtp_dv_cfg_pkg); the
  // TAP-control and AXI struct types are the design packages'.
  // ------------------------------------------------------------------
  dtp #(
    .JTAG_BSR_ENABLE          (dtp_dv_cfg_pkg::BsrEnable),
    .JTAG_EXTEST_TRAIN_ENABLE (dtp_dv_cfg_pkg::ExtestTrainEnable),
    .JTAG_EXTEST_PULSE_ENABLE (dtp_dv_cfg_pkg::ExtestPulseEnable),
    .JTAG_INTEST_ENABLE       (dtp_dv_cfg_pkg::IntestEnable),
    .JTAG_CLAMP_ENABLE        (dtp_dv_cfg_pkg::ClampEnable),
    .JTAG_HIGHZ_ENABLE        (dtp_dv_cfg_pkg::HighzEnable),
    .JTAG_RUNBIST_ENABLE      (dtp_dv_cfg_pkg::RunbistEnable),
    .JTAG_TMP_ENABLE          (dtp_dv_cfg_pkg::TmpEnable),
    .JTAG_IC_RESET_SMC_ENABLE (dtp_dv_cfg_pkg::IcResetSmcEnable),
    .JTAG_IC_RESET_EXT_ENABLE (dtp_dv_cfg_pkg::IcResetExtEnable),
    .JTAG_SMC_DBG_ENABLE      (dtp_dv_cfg_pkg::SmcDbgEnable),
    .JTAG_STAP_IO_ENABLE      (dtp_dv_cfg_pkg::StapIoEnable),
    .JTAG_IC_RESET_SEP_ENABLE (dtp_dv_cfg_pkg::IcResetSepEnable),
    .JTAG_SEP_DBG_ENABLE      (dtp_dv_cfg_pkg::SepDbgEnable),
    .JTAG_NUM_EXTRA_STAPS     (dtp_dv_cfg_pkg::NumExtraStaps),
    .JTAG_IDCODE_MFR_ID       (dtp_dv_cfg_pkg::IdcodeMfrId),
    .JTAG_IDCODE_PART_NUM     (dtp_dv_cfg_pkg::IdcodePartNum),
    .JTAG_IDCODE_SI_REV       (dtp_dv_cfg_pkg::IdcodeSiRev),
    .JTAG_OCH_VER             (dtp_dv_cfg_pkg::OchVer),
    .XTRIG_NUM_CTP            (dtp_dv_cfg_pkg::NumCtp),
    .XTRIG_NUM_INT_CT         (dtp_dv_cfg_pkg::NumIntCt),
    .XTRIG_NUM_CLK_STOP_REQ   (dtp_dv_cfg_pkg::NumClkStopReq),
    .XTRIG_INT_CT_MODE        (dtp_dv_cfg_pkg::IntCtMode),
    .ic_reset_smc_t           (dtp_dv_cfg_pkg::ic_reset_smc_t),
    .ic_reset_sep_t           (dtp_dv_cfg_pkg::ic_reset_sep_t),
    .ic_reset_ext_t           (dtp_dv_cfg_pkg::ic_reset_ext_t),
    .smc_jtag_axi_req_t       (dtp_dv_cfg_pkg::smc_axi_req_t),
    .smc_jtag_axi_resp_t      (dtp_dv_cfg_pkg::smc_axi_resp_t),
    .smc_otp_axil_req_t       (dtp_dv_cfg_pkg::otp_axil_req_t),
    .smc_otp_axil_resp_t      (dtp_dv_cfg_pkg::otp_axil_resp_t),
    .sep_otp_axil_req_t       (dtp_dv_cfg_pkg::otp_axil_req_t),
    .sep_otp_axil_resp_t      (dtp_dv_cfg_pkg::otp_axil_resp_t),
    .SMC_OTP_RD_PL_DEPTH      (dtp_dv_cfg_pkg::SmcOtpRdPlDepth),
    .SMC_OTP_WR_PL_DEPTH      (dtp_dv_cfg_pkg::SmcOtpWrPlDepth),
    .SEP_OTP_RD_PL_DEPTH      (dtp_dv_cfg_pkg::SepOtpRdPlDepth),
    .SEP_OTP_WR_PL_DEPTH      (dtp_dv_cfg_pkg::SepOtpWrPlDepth),
    .SMC_RD_PL_DEPTH          (dtp_dv_cfg_pkg::SmcRdPlDepth),
    .SMC_WR_PL_DEPTH          (dtp_dv_cfg_pkg::SmcWrPlDepth)
  ) u_dut (
    .clk_i                            (clk_i),
    .rst_n_i                          (rst_n_i),
    .pwr_on_rst_ni                    (pwr_on_rst_ni),

    // DFT controls, functional mode unless a scenario drives them
    .test_en_i                        (u_tb_if.test_en),
    .scan_rst_ni                      (u_tb_if.scan_rst_n),

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

    // I/O STAP host (loopback, or the downstream TAP when ds_en)
    .jtag_stap_io_host_tap_ctrl_o     (stap_io_tap_ctrl),
    .jtag_stap_io_host_tdi_i          (stap_io_host_tdi),
    .jtag_stap_io_host_tdo_o          (stap_io_tdo),
    .jtag_stap_io_host_tdo_oen_o      (jtag_stap_io_tdo_oen),

    // SMC debug STAP host (loopback, or the downstream TAP when ds_en)
    .jtag_stap_smc_host_tap_ctrl_o    (stap_smc_tap_ctrl),
    .jtag_stap_smc_host_tdi_i         (stap_smc_host_tdi),
    .jtag_stap_smc_host_tdo_o         (stap_smc_tdo),
    .jtag_stap_smc_host_tdo_oen_o     (jtag_stap_smc_tdo_oen),

    // SEP debug STAP host (loopback, or the downstream TAP when ds_en)
    .jtag_stap_sep_host_tap_ctrl_o    (stap_sep_tap_ctrl),
    .jtag_stap_sep_host_tdi_i         (stap_sep_host_tdi),
    .jtag_stap_sep_host_tdo_o         (stap_sep_tdo),
    .jtag_stap_sep_host_tdo_oen_o     (jtag_stap_sep_tdo_oen),

    // Extra STAP hosts (1 port by default; loopback or downstream TAP)
    .jtag_stap_extra_host_tap_ctrl_o  (stap_extra_tap_ctrl),
    .jtag_stap_extra_host_tdi_i       (stap_extra_host_tdi),
    .jtag_stap_extra_host_tdo_o       (stap_extra_tdo),
    .jtag_stap_extra_host_tdo_oen_o   (stap_extra_tdo_oen),

    // Extended STAP scan (loopback, or the host segment when stap_host_seg_en)
    .jtag_stap_host_scan_ctrl_o       (jtag_stap_host_scan_ctrl),
    .jtag_stap_host_scan_in_i         (stap_host_scan_in),
    .jtag_stap_host_scan_out_o        (stap_host_scan_out),

    // External DFD iJTAG scan (instrument stub)
    .jtag_dfd_host_scan_ctrl_o        (jtag_dfd_host_scan_ctrl),
    .jtag_dfd_host_scan_in_i          (dfd_scan_in),
    .jtag_dfd_host_scan_out_o         (dfd_scan_out),

    // External secure DFT iJTAG scan (instrument stub)
    .jtag_dft_secure_host_scan_ctrl_o (jtag_dft_secure_host_scan_ctrl),
    .jtag_dft_secure_host_scan_in_i   (dft_secure_scan_in),
    .jtag_dft_secure_host_scan_out_o  (dft_secure_scan_out),

    // External non-secure DFT iJTAG scan (instrument stub)
    .jtag_dft_host_scan_ctrl_o        (jtag_dft_host_scan_ctrl),
    .jtag_dft_host_scan_in_i          (dft_scan_in),
    .jtag_dft_host_scan_out_o         (dft_scan_out),

    // SMC fabric debug AXI manager -> shared AXI responder (flattened above)
    .axi_smc_dbg_req_o                (axi_smc_dbg_req),
    .axi_smc_dbg_resp_i               (axi_smc_dbg_resp),

    // SMC OTP debug AXI-Lite manager -> shared AXI-Lite responder
    .axil_smc_otp_jtag_req_o          (axil_smc_otp_jtag_req),
    .axil_smc_otp_jtag_resp_i         (axil_smc_otp_jtag_resp),

    // SEP OTP debug AXI-Lite manager -> shared AXI-Lite responder
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

    // Cross-trigger CSR AXI-Lite subordinate <- shared AXI-Lite master
    .axil_xtrig_req_i                 (axil_xtrig_req),
    .axil_xtrig_resp_o                (axil_xtrig_resp),

    // Cross-trigger matrix
    .xtrig_ctm_src_req_o              (xtrig_ctm_src_req),
    .xtrig_ctm_src_ack_i              (xtrig_ctm_src_ack),
    .xtrig_ctm_dst_req_i              (xtrig_ctm_dst_req),
    .xtrig_ctm_dst_ack_o              (xtrig_ctm_dst_ack),

    // CLA clock-stop requests (driven through dtp_tb_if for DEBUG_CONTROL tests)
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

  // ------------------------------------------------------------------
  // Functional coverage (DTP_FCOV.adoc): shared by both tb shapes. The
  // module carries Verilator-safe cover-property points plus
  // commercial-only covergroups internally.
  // ------------------------------------------------------------------
  dtp_fcov u_dtp_fcov (
    .tck_i          (jtag_tck),
    .tms_i          (jtag_tms),
    .tdi_i          (jtag_tdi),
    .tdo_i          (jtag_tdo),
    .trst_ni        (jtag_trst),
    .por_ni         (pwr_on_rst_ni),
    .tap_state_i    (jtag_ptap_state),
    .inst_decoded_i (jtag_ptap_inst_decoded),
    .stap_select_i  (u_dut.u_jtag_intf_unit.u_jtag_ptap.stap_select),
    .dbg_disable_i  (dbg_disable)
  );

  // JTAG2AXI bridge coverage. The TCK-domain points come from each bridge's
  // own bookkeeping via hierarchical references (the cocotb Verilator build
  // compiles with --public-flat-rw; VCS resolves them natively): the
  // single-op registers, and through the bound dtp_j2a_state_flags the
  // transaction its AXI state machine completes, its SINGLE_OP update and
  // disable, and its CDC's TCK-side clear. Bus-timing bins use the flat AXI
  // pins.
  dtp_jtag2axi_fcov u_dtp_jtag2axi_fcov (
    .tck_i             (jtag_tck),
    .trst_ni           (jtag_trst),
    .clk_i             (clk_i),
    .rst_ni            (rst_n_i),
    .tap_state_i       (jtag_ptap_state),
    .inst_decoded_i    (jtag_ptap_inst_decoded),
    .dbg_disable_i     (dbg_disable),

    .smc_axi_status_i  (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.last_single_op_status_tclk),
    .smc_axi_pending_i (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.single_op_pending_tclk),
    .smc_axi_op_i      (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.single_tx_op_tclk),
    .smc_axi_addr_i    (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.single_tx_addr_tclk),
    .smc_axi_size_i    (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.single_tx_axi_size_tclk),
    .smc_axi_wstrb_i   (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.single_tx_wstrb_tclk),
    .smc_axi_beat_done_i     (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_dv_state_flags.beat_done_o),
    .smc_axi_beat_resp_i     (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_dv_state_flags.beat_resp_o),
    .smc_axi_beat_mode_i     (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_dv_state_flags.beat_mode_o),
    .smc_axi_beat_op_i       (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_dv_state_flags.beat_op_o),
    .smc_axi_beat_size_i     (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_dv_state_flags.beat_size_o),
    .smc_axi_beat_req_size_i (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_dv_state_flags.beat_req_size_o),
    .smc_axi_beat_offset_i   (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_dv_state_flags.beat_offset_o),
    .smc_axi_sticky_i        (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_dv_state_flags.sticky_o),
    .smc_axi_clear_pending_i (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_dv_state_flags.clear_pending_o),
    .smc_axi_abort_i         (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_dv_state_flags.abort_o),
    .smc_axi_single_upd_i    (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_dv_state_flags.single_upd_o),
    .smc_axi_scan_op_i       (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_dv_state_flags.scan_op_o),
    .smc_axi_sec_dis_i       (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_dv_state_flags.sec_dis_o),
    .smc_axi_fsm_idle_i      (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_dv_state_flags.idle_o),
    .smc_axi_awvalid_i (m_axi_awvalid),
    .smc_axi_awready_i (m_axi_awready),
    .smc_axi_wvalid_i  (m_axi_wvalid),
    .smc_axi_wready_i  (m_axi_wready),
    .smc_axi_bvalid_i  (m_axi_bvalid),
    .smc_axi_bready_i  (m_axi_bready),
    .smc_axi_arvalid_i (m_axi_arvalid),
    .smc_axi_arready_i (m_axi_arready),
    .smc_axi_rvalid_i  (m_axi_rvalid),
    .smc_axi_rready_i  (m_axi_rready),

    .smc_otp_status_i  (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.last_single_op_status_tclk),
    .smc_otp_pending_i (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.single_op_pending_tclk),
    .smc_otp_op_i      (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.single_tx_op_tclk),
    .smc_otp_addr_i    (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.single_tx_addr_tclk),
    .smc_otp_size_i    ({1'b0, u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.single_tx_axi_size_tclk}),
    .smc_otp_wstrb_i   (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.single_tx_wstrb_tclk),
    .smc_otp_beat_done_i     (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.u_dv_state_flags.beat_done_o),
    .smc_otp_beat_resp_i     (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.u_dv_state_flags.beat_resp_o),
    .smc_otp_beat_mode_i     (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.u_dv_state_flags.beat_mode_o),
    .smc_otp_beat_op_i       (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.u_dv_state_flags.beat_op_o),
    .smc_otp_beat_size_i     (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.u_dv_state_flags.beat_size_o),
    .smc_otp_beat_req_size_i (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.u_dv_state_flags.beat_req_size_o),
    .smc_otp_beat_offset_i   (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.u_dv_state_flags.beat_offset_o),
    .smc_otp_sticky_i        (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.u_dv_state_flags.sticky_o),
    .smc_otp_clear_pending_i (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.u_dv_state_flags.clear_pending_o),
    .smc_otp_abort_i         (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.u_dv_state_flags.abort_o),
    .smc_otp_single_upd_i    (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.u_dv_state_flags.single_upd_o),
    .smc_otp_scan_op_i       (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.u_dv_state_flags.scan_op_o),
    .smc_otp_sec_dis_i       (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.u_dv_state_flags.sec_dis_o),
    .smc_otp_fsm_idle_i      (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.u_dv_state_flags.idle_o),
    .smc_otp_awvalid_i (smc_otp_axil_awvalid),
    .smc_otp_awready_i (smc_otp_axil_awready),
    .smc_otp_wvalid_i  (smc_otp_axil_wvalid),
    .smc_otp_wready_i  (smc_otp_axil_wready),
    .smc_otp_bvalid_i  (smc_otp_axil_bvalid),
    .smc_otp_bready_i  (smc_otp_axil_bready),
    .smc_otp_arvalid_i (smc_otp_axil_arvalid),
    .smc_otp_arready_i (smc_otp_axil_arready),
    .smc_otp_rvalid_i  (smc_otp_axil_rvalid),
    .smc_otp_rready_i  (smc_otp_axil_rready),

    .sep_otp_status_i  (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.last_single_op_status_tclk),
    .sep_otp_pending_i (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.single_op_pending_tclk),
    .sep_otp_op_i      (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.single_tx_op_tclk),
    .sep_otp_addr_i    (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.single_tx_addr_tclk),
    .sep_otp_size_i    ({1'b0, u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.single_tx_axi_size_tclk}),
    .sep_otp_wstrb_i   (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.single_tx_wstrb_tclk),
    .sep_otp_beat_done_i     (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.u_dv_state_flags.beat_done_o),
    .sep_otp_beat_resp_i     (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.u_dv_state_flags.beat_resp_o),
    .sep_otp_beat_mode_i     (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.u_dv_state_flags.beat_mode_o),
    .sep_otp_beat_op_i       (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.u_dv_state_flags.beat_op_o),
    .sep_otp_beat_size_i     (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.u_dv_state_flags.beat_size_o),
    .sep_otp_beat_req_size_i (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.u_dv_state_flags.beat_req_size_o),
    .sep_otp_beat_offset_i   (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.u_dv_state_flags.beat_offset_o),
    .sep_otp_sticky_i        (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.u_dv_state_flags.sticky_o),
    .sep_otp_clear_pending_i (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.u_dv_state_flags.clear_pending_o),
    .sep_otp_abort_i         (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.u_dv_state_flags.abort_o),
    .sep_otp_single_upd_i    (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.u_dv_state_flags.single_upd_o),
    .sep_otp_scan_op_i       (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.u_dv_state_flags.scan_op_o),
    .sep_otp_sec_dis_i       (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.u_dv_state_flags.sec_dis_o),
    .sep_otp_fsm_idle_i      (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.u_dv_state_flags.idle_o),
    .sep_otp_awvalid_i (sep_otp_axil_awvalid),
    .sep_otp_awready_i (sep_otp_axil_awready),
    .sep_otp_wvalid_i  (sep_otp_axil_wvalid),
    .sep_otp_wready_i  (sep_otp_axil_wready),
    .sep_otp_bvalid_i  (sep_otp_axil_bvalid),
    .sep_otp_bready_i  (sep_otp_axil_bready),
    .sep_otp_arvalid_i (sep_otp_axil_arvalid),
    .sep_otp_arready_i (sep_otp_axil_arready),
    .sep_otp_rvalid_i  (sep_otp_axil_rvalid),
    .sep_otp_rready_i  (sep_otp_axil_rready)
  );

  // Debug-TDR coverage (TMP / IC_RESET / DEBUG_CONTROL / clock stop / CAPS):
  // flattened TDR outputs, the boundary-scan chrst_n and the clock-stop
  // pins, plus the TMP unit, the IC_RESET hold bit, the PTAP 3DCR select
  // and the JTAG clock stop through hierarchical references. The TAP reset
  // is the TRST AND power-on reset the PTAP applies.
  dtp_debug_tdr_fcov u_dtp_debug_tdr_fcov (
    .tck_i                 (jtag_tck),
    .tdi_i                 (jtag_tdi),
    .tdo_i                 (jtag_tdo),
    .tap_rst_ni            (jtag_trst & pwr_on_rst_ni),
    .clk_i                 (clk_i),
    .rst_ni                (rst_n_i),
    .tap_state_i           (jtag_ptap_state),
    .inst_decoded_i        (jtag_ptap_inst_decoded),
    .ptap_stap_select_i    (u_dut.u_jtag_intf_unit.u_jtag_ptap.stap_select),
    .ic_reset_smc_ovrd_i   (jtag_ic_reset_smc_ovrd),
    .ic_reset_smc_ctrl_n_i (jtag_ic_reset_smc_ctrl_n),
    .ic_reset_sep_ovrd_i   (jtag_ic_reset_sep_ovrd),
    .ic_reset_sep_ctrl_n_i (jtag_ic_reset_sep_ctrl_n),
    .ic_reset_ext_ovrd_i   (jtag_ic_reset_ext_ovrd),
    .ic_reset_ext_ctrl_n_i (jtag_ic_reset_ext_ctrl_n),
    .boot_stall_ovrd_i     (jtag_boot_stall_ovrd),
    .boot_stall_i          (jtag_boot_stall),
    .cla_clock_stop_en_i   (cla_clock_stop_en),
    .chrst_n_i             (jtag_bsr_chrst_n),
    .stop_clks_i           (stop_clks),
    .clk_stop_req_i        (xtrig_clk_stop_req),
    .tmp_state_i           (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_tmp_controller.u_jtag_tmp.tmp_state_q_bits),
    .tmp_escape_arm_i      (u_dut.u_jtag_intf_unit.u_jtag_ptap.bypass_escape_bit),
    .tmp_escape_cond_i     (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_tmp_controller.u_jtag_tmp.bypass_escape_condition),
    .ic_reset_hold_i       (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_ic_reset_reg.u_jtag_ic_reset_reg.reset_hold),
    .jtag_clock_stop_i     (u_dut.jtag_clock_stop)
  );

  // Scan-network coverage (iJTAG SIBs / STAP 3DCR / scan-side debug
  // disable): flattened chain controls plus, through hierarchical
  // references, the SIB scan bits, each STAP's SIB and stored 3DCR (sel_int
  // is the stored select before the security gate), the PTAP 3DCR, and the
  // TCK-synchronized disable vector the gates apply.
  dtp_scan_fcov u_dtp_scan_fcov (
    .tck_i                    (jtag_tck),
    .trst_ni                  (jtag_trst),
    .tap_state_i              (jtag_ptap_state),
    .inst_decoded_i           (jtag_ptap_inst_decoded),
    .dbg_disable_sync_i       (u_dut.u_jtag_intf_unit.dbg_disable_q),
    .dft_secure_select_i      (jtag_dft_secure_select),
    .dft_secure_shift_en_i    (jtag_dft_secure_shift_en),
    .dft_select_i             (jtag_dft_select),
    .dft_shift_en_i           (jtag_dft_shift_en),
    .dfd_select_i             (jtag_dfd_select),
    .dfd_shift_en_i           (jtag_dfd_shift_en),
    .dft_secure_sib_bit_i     (u_dut.u_jtag_intf_unit.u_dft_secure_sib.scan_reg_scan_out),
    .dft_nonsecure_sib_bit_i  (u_dut.u_jtag_intf_unit.u_dft_nonsecure_sib.scan_reg_scan_out),
    .dfd_sib_bit_i            (u_dut.u_jtag_intf_unit.u_dfd_sib.scan_reg_scan_out),
    .stap_io_tdo_oen_i        (jtag_stap_io_tdo_oen),
    .stap_smc_tdo_oen_i       (jtag_stap_smc_tdo_oen),
    .stap_sep_tdo_oen_i       (jtag_stap_sep_tdo_oen),
    .stap_extra_tdo_oen_i     (jtag_stap_extra0_tdo_oen),
    .stap_host_shift_en_i     (jtag_stap_host_shift_en),
    .stap_io_sib_i            (u_dut.u_jtag_intf_unit.gen_stap_io.u_stap_io.u_sib_mux_pre.sib_en),
    .stap_io_sel_int_i        (u_dut.u_jtag_intf_unit.gen_stap_io.u_stap_io.stap_sel_int),
    .stap_io_tms_hold_i       (u_dut.u_jtag_intf_unit.gen_stap_io.u_stap_io.tms_hold),
    .stap_io_config_hold_i    (u_dut.u_jtag_intf_unit.gen_stap_io.u_stap_io.config_hold),
    .stap_smc_sib_i           (u_dut.u_jtag_intf_unit.gen_stap_smc_dbg.u_stap_smc_dbg.u_sib_mux_pre.sib_en),
    .stap_smc_sel_int_i       (u_dut.u_jtag_intf_unit.gen_stap_smc_dbg.u_stap_smc_dbg.stap_sel_int),
    .stap_smc_tms_hold_i      (u_dut.u_jtag_intf_unit.gen_stap_smc_dbg.u_stap_smc_dbg.tms_hold),
    .stap_smc_config_hold_i   (u_dut.u_jtag_intf_unit.gen_stap_smc_dbg.u_stap_smc_dbg.config_hold),
    .stap_sep_sib_i           (u_dut.u_jtag_intf_unit.gen_stap_sep_dbg.u_stap_sep_dbg.u_sib_mux_pre.sib_en),
    .stap_sep_sel_int_i       (u_dut.u_jtag_intf_unit.gen_stap_sep_dbg.u_stap_sep_dbg.stap_sel_int),
    .stap_sep_tms_hold_i      (u_dut.u_jtag_intf_unit.gen_stap_sep_dbg.u_stap_sep_dbg.tms_hold),
    .stap_sep_config_hold_i   (u_dut.u_jtag_intf_unit.gen_stap_sep_dbg.u_stap_sep_dbg.config_hold),
    .stap_extra_sib_i         (u_dut.u_jtag_intf_unit.gen_extra_staps.gen_extra_stap[0].u_stap_extra.u_sib_mux_pre.sib_en),
    .stap_extra_sel_int_i     (u_dut.u_jtag_intf_unit.gen_extra_staps.gen_extra_stap[0].u_stap_extra.stap_sel_int),
    .stap_extra_tms_hold_i    (u_dut.u_jtag_intf_unit.gen_extra_staps.gen_extra_stap[0].u_stap_extra.tms_hold),
    .stap_extra_config_hold_i (u_dut.u_jtag_intf_unit.gen_extra_staps.gen_extra_stap[0].u_stap_extra.config_hold),
    .ptap_stap_select_i       (u_dut.u_jtag_intf_unit.u_jtag_ptap.stap_select),
    .ptap_config_hold_i       (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_tap_3dcr_reg.u_jtag_3dcr_reg.config_hold)
  );

  // CONFIG.MODE, CONFIG.RESET, and STRETCH_MULT of every external CTP, from
  // its register fields.
  logic [dtp_dv_cfg_pkg::NumCtp-1:0] xtrig_ctp_mode_p2p;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0] xtrig_ctp_cfg_reset;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0][15:0] xtrig_ctp_stretch;
  for (genvar ctp = 0; ctp < dtp_dv_cfg_pkg::NumCtp; ctp++) begin : gen_xtrig_ctp_cfg
    assign xtrig_ctp_mode_p2p[ctp] =
        ~u_dut.u_cross_trigger_network.gen_ext_ctp[ctp].u_ctp.mode_wire_or;
    assign xtrig_ctp_cfg_reset[ctp] =
        u_dut.u_cross_trigger_network.gen_ext_ctp[ctp].u_ctp.handshake_reset;
    assign xtrig_ctp_stretch[ctp] =
        u_dut.u_cross_trigger_network.gen_ext_ctp[ctp].u_ctp.u_core.stretch_mult_i;
  end

  // Cross-trigger coverage (CTP / CTM / CSR port): the XTRIG CSR port with the
  // spill-register and crossbar-demux mirrors behind it, the cross-trigger
  // GPIO and matrix handshake pins with the CT_Req_out wire grouping, and each
  // CTP's configuration fields, all in the system-clock domain; the stimulus
  // rides dtp_xtrig_if in both frameworks.
  dtp_xtrig_fcov u_dtp_xtrig_fcov (
    .clk_i                 (clk_i),
    .rst_ni                (rst_n_i),
    .axil_awaddr_i         (xtrig_axil_awaddr),
    .axil_awvalid_i        (xtrig_axil_awvalid),
    .axil_awready_i        (xtrig_axil_awready),
    .axil_wdata_i          (xtrig_axil_wdata),
    .axil_wstrb_i          (xtrig_axil_wstrb),
    .axil_wvalid_i         (xtrig_axil_wvalid),
    .axil_wready_i         (xtrig_axil_wready),
    .axil_bresp_i          (xtrig_axil_bresp),
    .axil_bvalid_i         (xtrig_axil_bvalid),
    .axil_bready_i         (xtrig_axil_bready),
    .axil_araddr_i         (xtrig_axil_araddr),
    .axil_arvalid_i        (xtrig_axil_arvalid),
    .axil_arready_i        (xtrig_axil_arready),
    .axil_rdata_i          (xtrig_axil_rdata),
    .axil_rresp_i          (xtrig_axil_rresp),
    .axil_rvalid_i         (xtrig_axil_rvalid),
    .axil_rready_i         (xtrig_axil_rready),
    .axil_w_spill_full_i   (xtrig_spill_w_occ == 2),
    .axil_r_spill_full_i   (xtrig_spill_r_occ == 2),
    .demux_aw_held_i       (xtrig_dmx_aw_valid & ~xtrig_dmx_aw_ready & (xtrig_demux_aw_open > 0)),
    .demux_ar_held_i       (xtrig_dmx_ar_valid & ~xtrig_dmx_ar_ready & (xtrig_demux_ar_open > 0)),
    .ctm_src_req_i         (xtrig_ctm_src_req),
    .ctm_dst_req_i         (xtrig_ctm_dst_req),
    .ctp_req_out_dout_i    (xtrig_ctp_req_out_dout),
    .ctp_req_out_dout_en_i (xtrig_ctp_req_out_dout_en),
    .ctp_req_out_din_en_i  (xtrig_ctp_req_out_din_en),
    .ctp_ack_in_din_i      (xtrig_ctp_ack_in_din),
    .ctp_ack_out_dout_i    (xtrig_ctp_ack_out_dout),
    .ctp_ct_dst_i          (xtrig_ctp_ct_dst),
    .ctp_wire_group_i      (u_xtrig_if.xtrig_ctp_wire_group),
    .ctp_mode_p2p_i        (xtrig_ctp_mode_p2p),
    .ctp_invert_i          (xtrig_ctp_invert),
    .ctp_cfg_reset_i       (xtrig_ctp_cfg_reset),
    .ctp_stretch_i         (xtrig_ctp_stretch)
  );


  // ------------------------------------------------------------------
  // Interface <-> TB net wiring
  // ------------------------------------------------------------------
  // Primary JTAG TAP: the shared JTAG master drives tck/tms/trst_n/tdi,
  // the DUT drives tdo/tdo_oen.
  assign jtag_tck  = u_jtag_if.tck;
  assign jtag_tms  = u_jtag_if.tms;
  assign jtag_trst = u_jtag_if.trst_n;
  assign jtag_tdi  = u_jtag_if.tdi;
  assign u_jtag_if.tdo     = jtag_tdo;
  assign u_jtag_if.tdo_oen = jtag_tdo_oen;

  // System reset pulse armed on a JTAG2AXI read (dtp_tb_if
  // sys_rst_on_ar_arm): it asserts on the clock edge that completes the
  // armed bridge's AR handshake, so the read response is outstanding when
  // the reset lands, and lasts sys_rst_on_ar_cycles clocks; one pulse per
  // arming.
  logic [3:0] ar_rst_count_q;
  logic       ar_rst_fired_q;
  wire  [2:0] j2a_ar_hs = {sep_otp_axil_arvalid & sep_otp_axil_arready,
                           smc_otp_axil_arvalid & smc_otp_axil_arready,
                           m_axi_arvalid & m_axi_arready};
  always_ff @(posedge clk_i or negedge pwr_on_rst_ni) begin
    if (!pwr_on_rst_ni) begin
      ar_rst_count_q <= '0;
      ar_rst_fired_q <= 1'b0;
    end else if (ar_rst_count_q != '0) begin
      ar_rst_count_q <= ar_rst_count_q - 4'd1;
    end else if (u_tb_if.sys_rst_on_ar_arm == '0) begin
      ar_rst_fired_q <= 1'b0;
    end else if (!ar_rst_fired_q && |(u_tb_if.sys_rst_on_ar_arm & j2a_ar_hs)) begin
      ar_rst_count_q <= u_tb_if.sys_rst_on_ar_cycles;
      ar_rst_fired_q <= 1'b1;
    end
  end

  // System clock, DTP-local resets (test-sequenced), reset and stop_clks
  // change counters, and TAP-state observable.
  assign clk_i                        = u_tb_if.clk;
  assign rst_n_i                      = u_tb_if.sys_rst_n && ((ar_rst_count_q == '0) !== 1'b0);
  assign pwr_on_rst_ni                = u_tb_if.por_rst_n;
  assign u_tb_if.sys_rst_assert_count = sys_rst_assert_count;
  assign u_tb_if.rst_n                = rst_n_i;
  assign u_tb_if.por_assert_count     = por_assert_count;
  assign u_tb_if.stop_clks_change_count   = stop_clks_change_count;
  assign u_tb_if.stop_clks_off_edge_count = stop_clks_off_edge_count;
  assign u_tb_if.tap_state            = jtag_ptap_state;

  // Decoded-IR observable (dtp_tb_if) and boundary-scan control
  // observables (dtp_scan_if) for the basic-JTAG instruction checks.
  assign u_tb_if.inst_decoded        = jtag_ptap_inst_decoded;
  assign u_scan_if.jtag_bsr_select     = jtag_bsr_select;
  assign u_scan_if.jtag_bsr_shift_en   = jtag_bsr_shift_en;
  assign u_scan_if.jtag_bsr_capture_en = jtag_bsr_capture_en;
  assign u_scan_if.jtag_bsr_update_en  = jtag_bsr_update_en;
  assign u_scan_if.jtag_bsr_run_test_idle    = jtag_bsr_run_test_idle;
  assign u_scan_if.jtag_bsr_test_logic_reset = jtag_bsr_test_logic_reset;
  assign u_scan_if.jtag_bsr_runbist          = jtag_bsr_runbist;
  assign u_scan_if.jtag_bsr_chrst_n          = jtag_bsr_chrst_n;

  // Lifecycle debug disables and clock-stop requests: sequences drive the
  // named debug disables and the CLA clock-stop request vector through
  // dtp_tb_if, which binds the disables into the typed dbg_disable_t
  // (disables init 1 = fail-closed; clk_stop_req init '0 = quiescent; the
  // debug-TDR sequences drive the requests they need). The request vector
  // reaches xtrig_clk_stop_req_i at clk_i falling edges, so no request change
  // shares a time step with a clk_i rising edge.
  always @(negedge clk_i) xtrig_clk_stop_req <= u_tb_if.xtrig_clk_stop_req;
  assign dbg_disable        = u_tb_if.dbg_disable;

  // Debug-TDR observables: DEBUG_CONTROL clock-stop / boot-stall outputs
  // and the flattened IC_RESET slice outputs for the debug-TDR checks.
  assign u_tb_if.stop_clks                = stop_clks;
  assign u_tb_if.cla_clock_stop_en        = cla_clock_stop_en;
  assign u_tb_if.jtag_boot_stall          = jtag_boot_stall;
  assign u_tb_if.jtag_boot_stall_ovrd     = jtag_boot_stall_ovrd;
  assign u_tb_if.jtag_ic_reset_smc_ovrd   = jtag_ic_reset_smc_ovrd;
  assign u_tb_if.jtag_ic_reset_smc_ctrl_n = jtag_ic_reset_smc_ctrl_n;
  assign u_tb_if.jtag_ic_reset_sep_ovrd   = jtag_ic_reset_sep_ovrd;
  assign u_tb_if.jtag_ic_reset_sep_ctrl_n = jtag_ic_reset_sep_ctrl_n;
  assign u_tb_if.jtag_ic_reset_ext_ovrd   = jtag_ic_reset_ext_ovrd;
  assign u_tb_if.jtag_ic_reset_ext_ctrl_n = jtag_ic_reset_ext_ctrl_n;

  // Scan-network observables: iJTAG SIB scan controls, STAP forwarding
  // pins, and the extended STAP host scan controls for the scan-scenario
  // temporal windows.
  assign u_scan_if.jtag_dft_secure_select     = jtag_dft_secure_select;
  assign u_scan_if.jtag_dft_secure_shift_en   = jtag_dft_secure_shift_en;
  assign u_scan_if.jtag_dft_secure_capture_en = jtag_dft_secure_capture_en;
  assign u_scan_if.jtag_dft_secure_update_en  = jtag_dft_secure_update_en;
  assign u_scan_if.jtag_dft_select            = jtag_dft_select;
  assign u_scan_if.jtag_dft_shift_en          = jtag_dft_shift_en;
  assign u_scan_if.jtag_dft_capture_en        = jtag_dft_capture_en;
  assign u_scan_if.jtag_dft_update_en         = jtag_dft_update_en;
  assign u_scan_if.jtag_dft_run_test_idle     = jtag_dft_run_test_idle;
  assign u_scan_if.jtag_dft_test_logic_reset  = jtag_dft_test_logic_reset;
  assign u_scan_if.jtag_dft_runbist           = jtag_dft_runbist;
  assign u_scan_if.jtag_dfd_select            = jtag_dfd_select;
  assign u_scan_if.jtag_dfd_shift_en          = jtag_dfd_shift_en;
  assign u_scan_if.jtag_dfd_capture_en        = jtag_dfd_capture_en;
  assign u_scan_if.jtag_dfd_update_en         = jtag_dfd_update_en;
  assign u_scan_if.jtag_stap_io_tms           = jtag_stap_io_tms;
  assign u_scan_if.jtag_stap_io_tdo_oen       = jtag_stap_io_tdo_oen;
  assign u_scan_if.jtag_stap_smc_tms          = jtag_stap_smc_tms;
  assign u_scan_if.jtag_stap_smc_tdo_oen      = jtag_stap_smc_tdo_oen;
  assign u_scan_if.jtag_stap_sep_tms          = jtag_stap_sep_tms;
  assign u_scan_if.jtag_stap_sep_tdo_oen      = jtag_stap_sep_tdo_oen;
  assign u_scan_if.jtag_stap_extra0_tms       = jtag_stap_extra0_tms;
  assign u_scan_if.jtag_stap_extra0_tdo_oen   = jtag_stap_extra0_tdo_oen;
  assign u_scan_if.jtag_stap_host_select      = jtag_stap_host_select;
  assign u_scan_if.jtag_stap_host_shift_en    = jtag_stap_host_shift_en;
  assign u_scan_if.jtag_stap_host_capture_en  = jtag_stap_host_capture_en;
  assign u_scan_if.jtag_stap_host_update_en   = jtag_stap_host_update_en;
  assign u_scan_if.jtag_dft_secure_host_scan_out = dft_secure_scan_out;
  assign u_scan_if.jtag_dft_host_scan_out        = dft_scan_out;
  assign u_scan_if.jtag_dfd_host_scan_out        = dfd_scan_out;
  assign u_scan_if.jtag_stap_host_scan_out       = stap_host_scan_out;
  assign u_scan_if.jtag_stap_io_tck         = jtag_stap_io_tck;
  assign u_scan_if.jtag_stap_io_trst_n      = jtag_stap_io_trst_n;
  assign u_scan_if.jtag_stap_smc_tck        = jtag_stap_smc_tck;
  assign u_scan_if.jtag_stap_smc_trst_n     = jtag_stap_smc_trst_n;
  assign u_scan_if.jtag_stap_sep_tck        = jtag_stap_sep_tck;
  assign u_scan_if.jtag_stap_sep_trst_n     = jtag_stap_sep_trst_n;
  assign u_scan_if.jtag_stap_extra0_tck     = jtag_stap_extra0_tck;
  assign u_scan_if.jtag_stap_extra0_trst_n  = jtag_stap_extra0_trst_n;

  // Per-port TMS forwarding flags: each compares the forwarded TMS with the
  // primary TMS as both stand at a rising TCK edge, the edge a downstream
  // TAP samples TMS on, and holds the result until the next rising edge.
  logic [3:0] stap_tms_mismatch_q = '0;
  always @(posedge jtag_tck)
    stap_tms_mismatch_q <= {
      jtag_stap_extra0_tms !== jtag_tms,
      jtag_stap_sep_tms !== jtag_tms,
      jtag_stap_smc_tms !== jtag_tms,
      jtag_stap_io_tms !== jtag_tms
    };
  assign u_scan_if.jtag_stap_io_tms_mismatch     = stap_tms_mismatch_q[0];
  assign u_scan_if.jtag_stap_smc_tms_mismatch    = stap_tms_mismatch_q[1];
  assign u_scan_if.jtag_stap_sep_tms_mismatch    = stap_tms_mismatch_q[2];
  assign u_scan_if.jtag_stap_extra0_tms_mismatch = stap_tms_mismatch_q[3];

  // Per-port host TRST assertion counters: one count per falling edge of the
  // port's forwarded TRST, whether or not TCK runs.
  logic [31:0] stap_io_trst_assert_count     = '0;
  logic [31:0] stap_smc_trst_assert_count    = '0;
  logic [31:0] stap_sep_trst_assert_count    = '0;
  logic [31:0] stap_extra0_trst_assert_count = '0;
  always @(negedge jtag_stap_io_trst_n)
    stap_io_trst_assert_count <= stap_io_trst_assert_count + 32'd1;
  always @(negedge jtag_stap_smc_trst_n)
    stap_smc_trst_assert_count <= stap_smc_trst_assert_count + 32'd1;
  always @(negedge jtag_stap_sep_trst_n)
    stap_sep_trst_assert_count <= stap_sep_trst_assert_count + 32'd1;
  always @(negedge jtag_stap_extra0_trst_n)
    stap_extra0_trst_assert_count <= stap_extra0_trst_assert_count + 32'd1;
  assign u_scan_if.jtag_stap_io_trst_assert_count     = stap_io_trst_assert_count;
  assign u_scan_if.jtag_stap_smc_trst_assert_count    = stap_smc_trst_assert_count;
  assign u_scan_if.jtag_stap_sep_trst_assert_count    = stap_sep_trst_assert_count;
  assign u_scan_if.jtag_stap_extra0_trst_assert_count = stap_extra0_trst_assert_count;

  // Downstream STAP TAPs: one ocah_jtag_if per STAP host port, wired from
  // the port's forwarded tck/tms/trst_n and its TDO; the shared
  // ocah_jtag_vip slave device answers on tdo, routed back into the host
  // TDI when the test sets dtp_scan_if.stap_<x>_ds_en (default 0 keeps
  // the wire loopback).

  assign u_stap_io_ds_if.tck        = jtag_stap_io_tck;
  assign u_stap_io_ds_if.tms        = jtag_stap_io_tms;
  assign u_stap_io_ds_if.trst_n     = jtag_stap_io_trst_n;
  assign u_stap_io_ds_if.tdi        = jtag_stap_io_tdo;
  assign jtag_stap_io_tdi           = u_stap_io_ds_if.tdo;
  assign jtag_stap_io_ds_en         = u_scan_if.stap_io_ds_en;

  assign u_stap_smc_ds_if.tck       = jtag_stap_smc_tck;
  assign u_stap_smc_ds_if.tms       = jtag_stap_smc_tms;
  assign u_stap_smc_ds_if.trst_n    = jtag_stap_smc_trst_n;
  assign u_stap_smc_ds_if.tdi       = jtag_stap_smc_tdo;
  assign jtag_stap_smc_tdi          = u_stap_smc_ds_if.tdo;
  assign jtag_stap_smc_ds_en        = u_scan_if.stap_smc_ds_en;

  assign u_stap_sep_ds_if.tck       = jtag_stap_sep_tck;
  assign u_stap_sep_ds_if.tms       = jtag_stap_sep_tms;
  assign u_stap_sep_ds_if.trst_n    = jtag_stap_sep_trst_n;
  assign u_stap_sep_ds_if.tdi       = jtag_stap_sep_tdo;
  assign jtag_stap_sep_tdi          = u_stap_sep_ds_if.tdo;
  assign jtag_stap_sep_ds_en        = u_scan_if.stap_sep_ds_en;

  assign u_stap_extra0_ds_if.tck    = jtag_stap_extra0_tck;
  assign u_stap_extra0_ds_if.tms    = jtag_stap_extra0_tms;
  assign u_stap_extra0_ds_if.trst_n = jtag_stap_extra0_trst_n;
  assign u_stap_extra0_ds_if.tdi    = jtag_stap_extra0_tdo;
  assign jtag_stap_extra0_tdi       = u_stap_extra0_ds_if.tdo;
  assign jtag_stap_extra0_ds_en     = u_scan_if.stap_extra0_ds_en;

  // SMC OTP AXI-Lite responder: the shared ocah_axi_vip responder (SV-UVM
  // slave agent or cocotb RAM) answers JTAG2AXI OTP traffic. The slave
  // interface carries the connection: the TB wires only the master-driven
  // signals in, and the responder drives the responder-side signals,
  // routed back to the DUT below. Error injection is programmed by
  // sequences via the responder's slave sequence.
  assign u_smc_otp_slave_if.awaddr   = 64'(smc_otp_axil_awaddr);
  assign u_smc_otp_slave_if.awprot   = smc_otp_axil_awprot;
  assign u_smc_otp_slave_if.awvalid  = smc_otp_axil_awvalid;
  assign u_smc_otp_slave_if.awid     = '0;
  assign u_smc_otp_slave_if.awlen    = '0;
  assign u_smc_otp_slave_if.awsize   = OtpAxilBeatSize;
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
  assign u_smc_otp_slave_if.arsize   = OtpAxilBeatSize;
  assign u_smc_otp_slave_if.arburst  = 2'b01;
  assign u_smc_otp_slave_if.arlock   = 1'b0;
  assign u_smc_otp_slave_if.arcache  = '0;
  assign u_smc_otp_slave_if.arqos    = '0;
  assign u_smc_otp_slave_if.arregion = '0;
  assign u_smc_otp_slave_if.aruser   = '0;
  assign u_smc_otp_slave_if.rready   = smc_otp_axil_rready;

  // Responder-side signals: agent driver -> DUT response inputs. An R beat
  // the responder answers with SLVERR or DECERR carries the port's
  // dtp_tb_if errored-beat word in place of the responder's zero data, so
  // the DUT and the passive monitor see the word the sequence chose. On all
  // three bridge ports BVALID and RVALID are low while rst_n_i is low: a
  // responder sees the reset only at its next clock edge.
  assign smc_otp_axil_awready = u_smc_otp_slave_if.awready;
  assign smc_otp_axil_wready  = u_smc_otp_slave_if.wready;
  assign smc_otp_axil_bresp   = u_smc_otp_slave_if.bresp;
  assign smc_otp_axil_bvalid  = u_smc_otp_slave_if.bvalid && rst_n_i;
  assign smc_otp_axil_arready = u_smc_otp_slave_if.arready;
  assign smc_otp_axil_rdata   = (u_smc_otp_slave_if.rvalid && u_smc_otp_slave_if.rresp[1])
                                ? u_tb_if.smc_otp_axil_err_rdata
                                : u_smc_otp_slave_if.rdata[31:0];
  assign smc_otp_axil_rresp   = u_smc_otp_slave_if.rresp;
  assign smc_otp_axil_rvalid  = u_smc_otp_slave_if.rvalid && rst_n_i;

  // SEP OTP AXI-Lite responder: the shared ocah_axi_vip responder
  // (same pattern as the SMC OTP port) answers JTAG2AXI SEP OTP traffic.
  assign u_sep_otp_slave_if.awaddr   = 64'(sep_otp_axil_awaddr);
  assign u_sep_otp_slave_if.awprot   = sep_otp_axil_awprot;
  assign u_sep_otp_slave_if.awvalid  = sep_otp_axil_awvalid;
  assign u_sep_otp_slave_if.awid     = '0;
  assign u_sep_otp_slave_if.awlen    = '0;
  assign u_sep_otp_slave_if.awsize   = OtpAxilBeatSize;
  assign u_sep_otp_slave_if.awburst  = 2'b01;
  assign u_sep_otp_slave_if.awlock   = 1'b0;
  assign u_sep_otp_slave_if.awcache  = '0;
  assign u_sep_otp_slave_if.awqos    = '0;
  assign u_sep_otp_slave_if.awregion = '0;
  assign u_sep_otp_slave_if.awuser   = '0;
  assign u_sep_otp_slave_if.wdata    = 64'(sep_otp_axil_wdata);
  assign u_sep_otp_slave_if.wstrb    = 8'(sep_otp_axil_wstrb);
  assign u_sep_otp_slave_if.wlast    = 1'b1;
  assign u_sep_otp_slave_if.wuser    = '0;
  assign u_sep_otp_slave_if.wvalid   = sep_otp_axil_wvalid;
  assign u_sep_otp_slave_if.bready   = sep_otp_axil_bready;
  assign u_sep_otp_slave_if.araddr   = 64'(sep_otp_axil_araddr);
  assign u_sep_otp_slave_if.arprot   = sep_otp_axil_arprot;
  assign u_sep_otp_slave_if.arvalid  = sep_otp_axil_arvalid;
  assign u_sep_otp_slave_if.arid     = '0;
  assign u_sep_otp_slave_if.arlen    = '0;
  assign u_sep_otp_slave_if.arsize   = OtpAxilBeatSize;
  assign u_sep_otp_slave_if.arburst  = 2'b01;
  assign u_sep_otp_slave_if.arlock   = 1'b0;
  assign u_sep_otp_slave_if.arcache  = '0;
  assign u_sep_otp_slave_if.arqos    = '0;
  assign u_sep_otp_slave_if.arregion = '0;
  assign u_sep_otp_slave_if.aruser   = '0;
  assign u_sep_otp_slave_if.rready   = sep_otp_axil_rready;

  // Responder-side signals: agent driver -> DUT response inputs.
  assign sep_otp_axil_awready = u_sep_otp_slave_if.awready;
  assign sep_otp_axil_wready  = u_sep_otp_slave_if.wready;
  assign sep_otp_axil_bresp   = u_sep_otp_slave_if.bresp;
  assign sep_otp_axil_bvalid  = u_sep_otp_slave_if.bvalid && rst_n_i;
  assign sep_otp_axil_arready = u_sep_otp_slave_if.arready;
  assign sep_otp_axil_rdata   = (u_sep_otp_slave_if.rvalid && u_sep_otp_slave_if.rresp[1])
                                ? u_tb_if.sep_otp_axil_err_rdata
                                : u_sep_otp_slave_if.rdata[31:0];
  assign sep_otp_axil_rresp   = u_sep_otp_slave_if.rresp;
  assign sep_otp_axil_rvalid  = u_sep_otp_slave_if.rvalid && rst_n_i;

  // SMC fabric AXI4 responder: the shared ocah_axi_vip responder (same
  // pattern as the SMC OTP port) answers JTAG2AXI fabric traffic. The
  // slave interface carries the connection: the TB wires only the
  // master-driven signals in, and the responder drives the responder-side
  // signals, routed back to the DUT below. Error injection and backdoor
  // memory access are programmed by sequences via the responder's slave
  // sequence.
  assign u_smc_axi_slave_if.awid     = 16'(m_axi_awid);
  assign u_smc_axi_slave_if.awaddr   = 64'(m_axi_awaddr);
  assign u_smc_axi_slave_if.awlen    = m_axi_awlen;
  assign u_smc_axi_slave_if.awsize   = m_axi_awsize;
  assign u_smc_axi_slave_if.awburst  = m_axi_awburst;
  assign u_smc_axi_slave_if.awlock   = m_axi_awlock;
  assign u_smc_axi_slave_if.awcache  = m_axi_awcache;
  assign u_smc_axi_slave_if.awprot   = m_axi_awprot;
  assign u_smc_axi_slave_if.awqos    = m_axi_awqos;
  assign u_smc_axi_slave_if.awregion = m_axi_awregion;
  assign u_smc_axi_slave_if.awuser   = 16'(m_axi_awuser);
  assign u_smc_axi_slave_if.awvalid  = m_axi_awvalid;
  assign u_smc_axi_slave_if.wdata    = m_axi_wdata;
  assign u_smc_axi_slave_if.wstrb    = m_axi_wstrb;
  assign u_smc_axi_slave_if.wlast    = m_axi_wlast;
  assign u_smc_axi_slave_if.wuser    = 16'(m_axi_wuser);
  assign u_smc_axi_slave_if.wvalid   = m_axi_wvalid;
  assign u_smc_axi_slave_if.bready   = m_axi_bready;
  assign u_smc_axi_slave_if.arid     = 16'(m_axi_arid);
  assign u_smc_axi_slave_if.araddr   = 64'(m_axi_araddr);
  assign u_smc_axi_slave_if.arlen    = m_axi_arlen;
  assign u_smc_axi_slave_if.arsize   = m_axi_arsize;
  assign u_smc_axi_slave_if.arburst  = m_axi_arburst;
  assign u_smc_axi_slave_if.arlock   = m_axi_arlock;
  assign u_smc_axi_slave_if.arcache  = m_axi_arcache;
  assign u_smc_axi_slave_if.arprot   = m_axi_arprot;
  assign u_smc_axi_slave_if.arqos    = m_axi_arqos;
  assign u_smc_axi_slave_if.arregion = m_axi_arregion;
  assign u_smc_axi_slave_if.aruser   = 16'(m_axi_aruser);
  assign u_smc_axi_slave_if.arvalid  = m_axi_arvalid;
  assign u_smc_axi_slave_if.rready   = m_axi_rready;

  // The bridge carries response USER across its CDC and never reads it, so
  // any value is legal. Each channel's value is a 32-bit maximal LFSR
  // (x^32 + x^22 + x^2 + x + 1) that steps only on that channel's handshake,
  // which keeps it stable while a response waits for READY.
  logic [31:0] smc_axi_buser_q;
  logic [31:0] smc_axi_ruser_q;
  always_ff @(posedge clk_i or negedge rst_n_i) begin
    if (!rst_n_i) begin
      smc_axi_buser_q <= 32'h1D87_2B41;
      smc_axi_ruser_q <= 32'h6A0F_93C5;
    end else begin
      if (m_axi_bvalid && m_axi_bready) begin
        smc_axi_buser_q <= {smc_axi_buser_q[30:0], smc_axi_buser_q[31] ^ smc_axi_buser_q[21]
                            ^ smc_axi_buser_q[1] ^ smc_axi_buser_q[0]};
      end
      if (m_axi_rvalid && m_axi_rready) begin
        smc_axi_ruser_q <= {smc_axi_ruser_q[30:0], smc_axi_ruser_q[31] ^ smc_axi_ruser_q[21]
                            ^ smc_axi_ruser_q[1] ^ smc_axi_ruser_q[0]};
      end
    end
  end

  // Responder-side signals: agent driver -> DUT response inputs.
  assign m_axi_awready = u_smc_axi_slave_if.awready;
  assign m_axi_wready  = u_smc_axi_slave_if.wready;
  assign m_axi_bid     = u_smc_axi_slave_if.bid[1:0];
  assign m_axi_bresp   = u_smc_axi_slave_if.bresp;
  assign m_axi_buser   = smc_axi_buser_q[dtp_dv_cfg_pkg::SmcAxiUserWidth-1:0];
  assign m_axi_bvalid  = u_smc_axi_slave_if.bvalid && rst_n_i;
  assign m_axi_arready = u_smc_axi_slave_if.arready;
  assign m_axi_rid     = u_smc_axi_slave_if.rid[1:0];
  assign m_axi_rdata   = (u_smc_axi_slave_if.rvalid && u_smc_axi_slave_if.rresp[1])
                         ? u_tb_if.smc_axi_err_rdata : u_smc_axi_slave_if.rdata;
  assign m_axi_rresp   = u_smc_axi_slave_if.rresp;
  assign m_axi_rlast   = u_smc_axi_slave_if.rlast && m_axi_rvalid;
  assign m_axi_ruser   = smc_axi_ruser_q[dtp_dv_cfg_pkg::SmcAxiUserWidth-1:0];
  assign m_axi_rvalid  = u_smc_axi_slave_if.rvalid && rst_n_i;

  // Shared-VIP passive monitor interfaces at the default geometry (the
  // SV-UVM layer sees one `virtual ocah_axi_if` type and masks in its cfg;
  // cocotb binds them through OcahAxiConfig at the real geometry).
  assign u_smc_otp_axil_if.awaddr   = 64'(smc_otp_axil_awaddr);
  assign u_smc_otp_axil_if.awprot   = smc_otp_axil_awprot;
  assign u_smc_otp_axil_if.awvalid  = smc_otp_axil_awvalid;
  assign u_smc_otp_axil_if.awready  = smc_otp_axil_awready;
  assign u_smc_otp_axil_if.awid     = '0;
  assign u_smc_otp_axil_if.awlen    = '0;
  assign u_smc_otp_axil_if.awsize   = OtpAxilBeatSize;
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
  assign u_smc_otp_axil_if.arsize   = OtpAxilBeatSize;
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

  assign u_sep_otp_axil_if.awaddr   = 64'(sep_otp_axil_awaddr);
  assign u_sep_otp_axil_if.awprot   = sep_otp_axil_awprot;
  assign u_sep_otp_axil_if.awvalid  = sep_otp_axil_awvalid;
  assign u_sep_otp_axil_if.awready  = sep_otp_axil_awready;
  assign u_sep_otp_axil_if.awid     = '0;
  assign u_sep_otp_axil_if.awlen    = '0;
  assign u_sep_otp_axil_if.awsize   = OtpAxilBeatSize;
  assign u_sep_otp_axil_if.awburst  = 2'b01;
  assign u_sep_otp_axil_if.awlock   = 1'b0;
  assign u_sep_otp_axil_if.awcache  = '0;
  assign u_sep_otp_axil_if.awqos    = '0;
  assign u_sep_otp_axil_if.awregion = '0;
  assign u_sep_otp_axil_if.awuser   = '0;
  assign u_sep_otp_axil_if.wdata    = 64'(sep_otp_axil_wdata);
  assign u_sep_otp_axil_if.wstrb    = 8'(sep_otp_axil_wstrb);
  assign u_sep_otp_axil_if.wlast    = 1'b1;
  assign u_sep_otp_axil_if.wuser    = '0;
  assign u_sep_otp_axil_if.wvalid   = sep_otp_axil_wvalid;
  assign u_sep_otp_axil_if.wready   = sep_otp_axil_wready;
  assign u_sep_otp_axil_if.bid      = '0;
  assign u_sep_otp_axil_if.bresp    = sep_otp_axil_bresp;
  assign u_sep_otp_axil_if.buser    = '0;
  assign u_sep_otp_axil_if.bvalid   = sep_otp_axil_bvalid;
  assign u_sep_otp_axil_if.bready   = sep_otp_axil_bready;
  assign u_sep_otp_axil_if.araddr   = 64'(sep_otp_axil_araddr);
  assign u_sep_otp_axil_if.arprot   = sep_otp_axil_arprot;
  assign u_sep_otp_axil_if.arvalid  = sep_otp_axil_arvalid;
  assign u_sep_otp_axil_if.arready  = sep_otp_axil_arready;
  assign u_sep_otp_axil_if.arid     = '0;
  assign u_sep_otp_axil_if.arlen    = '0;
  assign u_sep_otp_axil_if.arsize   = OtpAxilBeatSize;
  assign u_sep_otp_axil_if.arburst  = 2'b01;
  assign u_sep_otp_axil_if.arlock   = 1'b0;
  assign u_sep_otp_axil_if.arcache  = '0;
  assign u_sep_otp_axil_if.arqos    = '0;
  assign u_sep_otp_axil_if.arregion = '0;
  assign u_sep_otp_axil_if.aruser   = '0;
  assign u_sep_otp_axil_if.rid      = '0;
  assign u_sep_otp_axil_if.rdata    = 64'(sep_otp_axil_rdata);
  assign u_sep_otp_axil_if.rresp    = sep_otp_axil_rresp;
  assign u_sep_otp_axil_if.rlast    = 1'b1;
  assign u_sep_otp_axil_if.ruser    = '0;
  assign u_sep_otp_axil_if.rvalid   = sep_otp_axil_rvalid;
  assign u_sep_otp_axil_if.rready   = sep_otp_axil_rready;

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

  // Request-activity pulse-counter mirrors for sequences (no-activity
  // security-gating evidence sampled from the bus pins).
  assign u_tb_if.smc_axi_awvalid_count      = smc_axi_awvalid_count;
  assign u_tb_if.smc_axi_wvalid_count       = smc_axi_wvalid_count;
  assign u_tb_if.smc_axi_arvalid_count      = smc_axi_arvalid_count;
  assign u_tb_if.smc_otp_axil_awvalid_count = smc_otp_axil_awvalid_count;
  assign u_tb_if.smc_otp_axil_wvalid_count  = smc_otp_axil_wvalid_count;
  assign u_tb_if.smc_otp_axil_arvalid_count = smc_otp_axil_arvalid_count;
  assign u_tb_if.sep_otp_axil_awvalid_count = sep_otp_axil_awvalid_count;
  assign u_tb_if.sep_otp_axil_wvalid_count  = sep_otp_axil_wvalid_count;
  assign u_tb_if.sep_otp_axil_arvalid_count = sep_otp_axil_arvalid_count;

  // Bridge-port READY-stall counter mirrors for sequences.
  assign u_tb_if.smc_axi_aw_stall_count      = smc_axi_aw_stall_count;
  assign u_tb_if.smc_axi_w_stall_count       = smc_axi_w_stall_count;
  assign u_tb_if.smc_axi_ar_stall_count      = smc_axi_ar_stall_count;
  assign u_tb_if.smc_otp_axil_aw_stall_count = smc_otp_axil_aw_stall_count;
  assign u_tb_if.smc_otp_axil_w_stall_count  = smc_otp_axil_w_stall_count;
  assign u_tb_if.smc_otp_axil_ar_stall_count = smc_otp_axil_ar_stall_count;
  assign u_tb_if.sep_otp_axil_aw_stall_count = sep_otp_axil_aw_stall_count;
  assign u_tb_if.sep_otp_axil_w_stall_count  = sep_otp_axil_w_stall_count;
  assign u_tb_if.sep_otp_axil_ar_stall_count = sep_otp_axil_ar_stall_count;

  // JTAG2AXI bridge state for the stall and reset-abort scenarios and for
  // the coverage instance. Each bridge's AXI state machine is decoded by
  // state name, inside the bridge's own scope, into idle, write-path
  // (address, data, response wait), and read-path (address, data wait) flags
  // by the bound dtp_j2a_state_flags instance, beside the transaction the
  // state machine completes, the SINGLE_OP update, and the CDC's TCK-side
  // clear; the pending register rides beside them. The sticky flags catch
  // the CDC's TCK-side isolate-and-clear on the system clock.
  bind jtag2axi dtp_j2a_state_flags u_dv_state_flags (
    .idle_i          (axi_state_q_tclk == AXI_IDLE),
    .write_path_i    ((axi_state_q_tclk == AXI_SEND_ADDR_W) || (axi_state_q_tclk == AXI_SEND_DATA_W) ||
                      (axi_state_q_tclk == AXI_WAIT_BRESP)),
    .read_path_i     ((axi_state_q_tclk == AXI_SEND_ADDR_R) || (axi_state_q_tclk == AXI_WAIT_RDATA)),
    .beat_done_i     (fsm_updates_bresp_status_tclk_comb || fsm_updates_rdata_status_tclk_comb),
    .beat_resp_i     (next_status_tclk_comb),
    .beat_mode_i     ({current_tx_is_from_single_buffer_tclk,
                       current_is_series_data_with_error_status_op_tclk,
                       current_incr_series_addr_tclk}),
    .beat_op_i       (current_op_tclk),
    .beat_size_i     (current_axi_axsize_tclk),
    .beat_req_size_i (3'(current_jtag_size_tclk)),
    .beat_offset_i   (3'(current_addr_tclk % (DATA_WIDTH / 8))),
    .sticky_i        (sticky_axi_status_tclk),
    .clear_pending_i (src_clear_pending_tclk),
    .abort_i         ({single_op_aborted_tclk, series_aborted_tclk}),
    .single_upd_i    (update_en_i && select_AXISingleOp_i),
    .scan_op_i       (shift_register_q_tclk[1:0]),
    .sec_dis_i       (security_disable_i),
    .idle_o          (),
    .write_path_o    (),
    .read_path_o     (),
    .beat_done_o     (),
    .beat_resp_o     (),
    .beat_mode_o     (),
    .beat_op_o       (),
    .beat_size_o     (),
    .beat_req_size_o (),
    .beat_offset_o   (),
    .sticky_o        (),
    .clear_pending_o (),
    .abort_o         (),
    .single_upd_o    (),
    .scan_op_o       (),
    .sec_dis_o       ()
  );
  logic smc_axi_cdc_clear_seen;
  logic smc_otp_cdc_clear_seen;
  logic sep_otp_cdc_clear_seen;
  always_ff @(posedge clk_i or negedge pwr_on_rst_ni) begin
    if (!pwr_on_rst_ni || u_tb_if.cdc_clear_seen_clear) begin
      smc_axi_cdc_clear_seen <= 1'b0;
      smc_otp_cdc_clear_seen <= 1'b0;
      sep_otp_cdc_clear_seen <= 1'b0;
    end else begin
      if (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_axi_cdc.src_clear_pending_o)
        smc_axi_cdc_clear_seen <= 1'b1;
      if (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.u_axi_cdc.src_clear_pending_o)
        smc_otp_cdc_clear_seen <= 1'b1;
      if (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.u_axi_cdc.src_clear_pending_o)
        sep_otp_cdc_clear_seen <= 1'b1;
    end
  end
  assign u_tb_if.smc_axi_fsm_idle       = u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_dv_state_flags.idle_o;
  assign u_tb_if.smc_axi_fsm_write_path = u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_dv_state_flags.write_path_o;
  assign u_tb_if.smc_axi_fsm_read_path  = u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.u_dv_state_flags.read_path_o;
  assign u_tb_if.smc_axi_op_pending     = u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_jtag2axi.u_smc_jtag2axi.single_op_pending_tclk;
  assign u_tb_if.smc_axi_cdc_clear_seen = smc_axi_cdc_clear_seen;
  assign u_tb_if.smc_otp_fsm_idle       = u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.u_dv_state_flags.idle_o;
  assign u_tb_if.smc_otp_fsm_write_path = u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.u_dv_state_flags.write_path_o;
  assign u_tb_if.smc_otp_fsm_read_path  = u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.u_dv_state_flags.read_path_o;
  assign u_tb_if.smc_otp_op_pending     = u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.single_op_pending_tclk;
  assign u_tb_if.smc_otp_cdc_clear_seen = smc_otp_cdc_clear_seen;
  assign u_tb_if.sep_otp_fsm_idle       = u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.u_dv_state_flags.idle_o;
  assign u_tb_if.sep_otp_fsm_write_path = u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.u_dv_state_flags.write_path_o;
  assign u_tb_if.sep_otp_fsm_read_path  = u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.u_dv_state_flags.read_path_o;
  assign u_tb_if.sep_otp_op_pending     = u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.single_op_pending_tclk;
  assign u_tb_if.sep_otp_cdc_clear_seen = sep_otp_cdc_clear_seen;

  // XTRIG CSR AXI-Lite initiator: the shared ocah_axi_vip master (SV-UVM
  // agent or cocotb BFM) drives the CSR port (the initiator mirror of the
  // slave-port pattern: the master drives the request-side signals on the
  // master interface, routed out to the DUT here, and the TB wires only
  // the DUT-driven response signals back in).
  assign xtrig_axil_awaddr  = u_xtrig_master_if.awaddr[31:0];
  assign xtrig_axil_awprot  = u_xtrig_master_if.awprot;
  assign xtrig_axil_awvalid = u_xtrig_master_if.awvalid;
  assign xtrig_axil_wdata   = u_xtrig_master_if.wdata[31:0];
  assign xtrig_axil_wstrb   = u_xtrig_master_if.wstrb[3:0];
  assign xtrig_axil_wvalid  = u_xtrig_master_if.wvalid;
  assign xtrig_axil_bready  = u_xtrig_master_if.bready;
  assign xtrig_axil_araddr  = u_xtrig_master_if.araddr[31:0];
  assign xtrig_axil_arprot  = u_xtrig_master_if.arprot;
  assign xtrig_axil_arvalid = u_xtrig_master_if.arvalid;
  assign xtrig_axil_rready  = u_xtrig_master_if.rready;

  // Response-side signals: DUT subordinate -> agent driver/monitor.
  assign u_xtrig_master_if.awready = xtrig_axil_awready;
  assign u_xtrig_master_if.wready  = xtrig_axil_wready;
  assign u_xtrig_master_if.bresp   = xtrig_axil_bresp;
  assign u_xtrig_master_if.bvalid  = xtrig_axil_bvalid;
  assign u_xtrig_master_if.bid     = '0;
  assign u_xtrig_master_if.buser   = '0;
  assign u_xtrig_master_if.arready = xtrig_axil_arready;
  assign u_xtrig_master_if.rdata   = 64'(xtrig_axil_rdata);
  assign u_xtrig_master_if.rresp   = xtrig_axil_rresp;
  assign u_xtrig_master_if.rvalid  = xtrig_axil_rvalid;
  assign u_xtrig_master_if.rid     = '0;
  assign u_xtrig_master_if.rlast   = 1'b1;
  assign u_xtrig_master_if.ruser   = '0;

  assign u_xtrig_axil_if.awaddr   = 64'(xtrig_axil_awaddr);
  assign u_xtrig_axil_if.awprot   = xtrig_axil_awprot;
  assign u_xtrig_axil_if.awvalid  = xtrig_axil_awvalid;
  assign u_xtrig_axil_if.awready  = xtrig_axil_awready;
  assign u_xtrig_axil_if.awid     = '0;
  assign u_xtrig_axil_if.awlen    = '0;
  assign u_xtrig_axil_if.awsize   = 3'd2;
  assign u_xtrig_axil_if.awburst  = 2'b01;
  assign u_xtrig_axil_if.awlock   = 1'b0;
  assign u_xtrig_axil_if.awcache  = '0;
  assign u_xtrig_axil_if.awqos    = '0;
  assign u_xtrig_axil_if.awregion = '0;
  assign u_xtrig_axil_if.awuser   = '0;
  assign u_xtrig_axil_if.wdata    = 64'(xtrig_axil_wdata);
  assign u_xtrig_axil_if.wstrb    = 8'(xtrig_axil_wstrb);
  assign u_xtrig_axil_if.wlast    = 1'b1;
  assign u_xtrig_axil_if.wuser    = '0;
  assign u_xtrig_axil_if.wvalid   = xtrig_axil_wvalid;
  assign u_xtrig_axil_if.wready   = xtrig_axil_wready;
  assign u_xtrig_axil_if.bid      = '0;
  assign u_xtrig_axil_if.bresp    = xtrig_axil_bresp;
  assign u_xtrig_axil_if.buser    = '0;
  assign u_xtrig_axil_if.bvalid   = xtrig_axil_bvalid;
  assign u_xtrig_axil_if.bready   = xtrig_axil_bready;
  assign u_xtrig_axil_if.araddr   = 64'(xtrig_axil_araddr);
  assign u_xtrig_axil_if.arprot   = xtrig_axil_arprot;
  assign u_xtrig_axil_if.arvalid  = xtrig_axil_arvalid;
  assign u_xtrig_axil_if.arready  = xtrig_axil_arready;
  assign u_xtrig_axil_if.arid     = '0;
  assign u_xtrig_axil_if.arlen    = '0;
  assign u_xtrig_axil_if.arsize   = 3'd2;
  assign u_xtrig_axil_if.arburst  = 2'b01;
  assign u_xtrig_axil_if.arlock   = 1'b0;
  assign u_xtrig_axil_if.arcache  = '0;
  assign u_xtrig_axil_if.arqos    = '0;
  assign u_xtrig_axil_if.arregion = '0;
  assign u_xtrig_axil_if.aruser   = '0;
  assign u_xtrig_axil_if.rid      = '0;
  assign u_xtrig_axil_if.rdata    = 64'(xtrig_axil_rdata);
  assign u_xtrig_axil_if.rresp    = xtrig_axil_rresp;
  assign u_xtrig_axil_if.rlast    = 1'b1;
  assign u_xtrig_axil_if.ruser    = '0;
  assign u_xtrig_axil_if.rvalid   = xtrig_axil_rvalid;
  assign u_xtrig_axil_if.rready   = xtrig_axil_rready;

  // XTRIG CSR request-activity pulse-counter, stall-counter, and
  // occupancy-counter mirrors for sequences.
  assign u_tb_if.xtrig_axil_awvalid_count  = xtrig_axil_awvalid_count;
  assign u_tb_if.xtrig_axil_wvalid_count   = xtrig_axil_wvalid_count;
  assign u_tb_if.xtrig_axil_arvalid_count  = xtrig_axil_arvalid_count;
  assign u_tb_if.xtrig_axil_aw_stall_count = xtrig_axil_aw_stall_count;
  assign u_tb_if.xtrig_axil_ar_stall_count = xtrig_axil_ar_stall_count;
  assign u_tb_if.xtrig_axil_w_stall_count  = xtrig_axil_w_stall_count;
  assign u_tb_if.xtrig_axil_aw_open_stall_count  = xtrig_axil_aw_open_stall_count;
  assign u_tb_if.xtrig_axil_aw_open_accept_count = xtrig_axil_aw_open_accept_count;
  assign u_tb_if.xtrig_axil_ar_open_stall_count  = xtrig_axil_ar_open_stall_count;
  assign u_tb_if.xtrig_axil_ar_open_accept_count = xtrig_axil_ar_open_accept_count;
  assign u_tb_if.xtrig_axil_spill_err_count = xtrig_axil_spill_err_count;
  assign u_tb_if.xtrig_axil_w_spill_full_count = xtrig_axil_w_spill_full_count;
  assign u_tb_if.xtrig_axil_r_spill_full_count = xtrig_axil_r_spill_full_count;
  assign u_tb_if.xtrig_demux_aw_stall_count = xtrig_demux_aw_stall_count;
  assign u_tb_if.xtrig_demux_w_stall_count  = xtrig_demux_w_stall_count;
  assign u_tb_if.xtrig_demux_ar_stall_count = xtrig_demux_ar_stall_count;
  assign u_tb_if.xtrig_demux_aw_open_stall_count  = xtrig_demux_aw_open_stall_count;
  assign u_tb_if.xtrig_demux_aw_open_accept_count = xtrig_demux_aw_open_accept_count;
  assign u_tb_if.xtrig_demux_ar_open_stall_count  = xtrig_demux_ar_open_stall_count;
  assign u_tb_if.xtrig_demux_ar_open_accept_count = xtrig_demux_ar_open_accept_count;

  // XTRIG crossbar demux state (the single subordinate port's AXI-Lite
  // demux) and the external CTP busy flops, sampled from the DUT.
  assign u_tb_if.xtrig_demux_aw_lock   = u_dut.u_cross_trigger_network.u_axil_xbar.gen_slv_port_demux[0].i_axi_lite_demux.gen_demux.lock_aw_valid_q;
  assign u_tb_if.xtrig_demux_w_pending = ~u_dut.u_cross_trigger_network.u_axil_xbar.gen_slv_port_demux[0].i_axi_lite_demux.gen_demux.w_fifo_empty;
  for (genvar ctp = 0; ctp < dtp_dv_cfg_pkg::NumCtp; ctp++) begin : gen_xtrig_ctp_busy
    assign u_tb_if.xtrig_ctp_busy[ctp] = u_dut.u_cross_trigger_network.gen_ext_ctp[ctp].u_ctp.busy_o;
  end

  // Cross-trigger CTM/CTP pin surface: sequences drive the request-side
  // vectors and observe the DUT-driven vectors through dtp_xtrig_if (init
  // '0 = quiescent).
  assign xtrig_ctm_src_ack     = u_xtrig_if.xtrig_ctm_src_ack;
  assign xtrig_ctm_dst_req     = u_xtrig_if.xtrig_ctm_dst_req;
  assign xtrig_ctp_req_in_din  = u_xtrig_if.xtrig_ctp_req_in_din;
  assign xtrig_ctp_ack_in_din  = u_xtrig_if.xtrig_ctp_ack_in_din;
  assign xtrig_ctp_ack_out_din = u_xtrig_if.xtrig_ctp_ack_out_din;

  // CT_Req_out shared wires. A chiplet driver pulls towards the level
  // opposite its wire's pull; a pad in the group leaves its private wire.
  for (genvar ctp = 0; ctp < dtp_dv_cfg_pkg::NumCtp; ctp++) begin : gen_xtrig_ctp_wire
    ocah_open_drain_bus #(
      .NUM_DRIVERS (2)
    ) u_wire (
      .pull_i     (u_xtrig_if.xtrig_ctp_wire_pull[ctp]),
      .dout_i     ({~u_xtrig_if.xtrig_ctp_wire_pull[ctp], xtrig_ctp_req_out_dout[ctp]}),
      .dout_en_i  ({u_xtrig_if.xtrig_ctp_wire_ext_assert[ctp], xtrig_ctp_req_out_dout_en[ctp]}
                   & {2{~u_xtrig_if.xtrig_ctp_wire_group[ctp]}}),
      .wire_o     (xtrig_ctp_wire_private[ctp]),
      .mismatch_o (xtrig_ctp_wire_private_mismatch[ctp])
    );
    assign xtrig_ctp_req_out_din[ctp] = u_xtrig_if.xtrig_ctp_wire_group[ctp]
        ? xtrig_ctp_wire_group_wire : xtrig_ctp_wire_private[ctp];
    assign u_xtrig_if.xtrig_ctp_wire_mismatch[ctp] = u_xtrig_if.xtrig_ctp_wire_group[ctp]
        ? xtrig_ctp_wire_group_mismatch : xtrig_ctp_wire_private_mismatch[ctp];
    assign xtrig_ctp_ct_dst[ctp] = u_dut.u_cross_trigger_network.gen_ext_ctp[ctp].u_ctp.ct_dst_o;
    assign xtrig_ctp_invert[ctp] = u_dut.u_cross_trigger_network.gen_ext_ctp[ctp].u_ctp.invert;
  end

  ocah_open_drain_bus #(
    .NUM_DRIVERS (2 * dtp_dv_cfg_pkg::NumCtp)
  ) u_xtrig_ctp_group_wire (
    .pull_i     (u_xtrig_if.xtrig_ctp_wire_group_pull),
    .dout_i     ({{dtp_dv_cfg_pkg::NumCtp{~u_xtrig_if.xtrig_ctp_wire_group_pull}},
                  xtrig_ctp_req_out_dout}),
    .dout_en_i  ({u_xtrig_if.xtrig_ctp_wire_ext_assert & u_xtrig_if.xtrig_ctp_wire_group,
                  xtrig_ctp_req_out_dout_en & u_xtrig_if.xtrig_ctp_wire_group}),
    .wire_o     (xtrig_ctp_wire_group_wire),
    .mismatch_o (xtrig_ctp_wire_group_mismatch)
  );

  for (genvar ict = 0; ict < dtp_dv_cfg_pkg::NumIntCt; ict++) begin : gen_xtrig_int_ct_dst
    assign xtrig_int_ct_dst[ict] =
        u_dut.u_cross_trigger_network.gen_int_ctp[ict].u_int_ctp_core.ct_dst_o;
  end

  assign u_xtrig_if.xtrig_ctp_req_out_din     = xtrig_ctp_req_out_din;
  assign u_xtrig_if.xtrig_ctp_ct_dst          = xtrig_ctp_ct_dst;
  assign u_xtrig_if.xtrig_int_ct_dst          = xtrig_int_ct_dst;
  assign u_xtrig_if.xtrig_ctm_src_req         = xtrig_ctm_src_req;
  assign u_xtrig_if.xtrig_ctm_dst_ack         = xtrig_ctm_dst_ack;
  assign u_xtrig_if.xtrig_ctp_req_out_dout    = xtrig_ctp_req_out_dout;
  assign u_xtrig_if.xtrig_ctp_req_out_dout_en = xtrig_ctp_req_out_dout_en;
  assign u_xtrig_if.xtrig_ctp_req_out_din_en  = xtrig_ctp_req_out_din_en;
  assign u_xtrig_if.xtrig_ctp_req_in_dout     = xtrig_ctp_req_in_dout;
  assign u_xtrig_if.xtrig_ctp_req_in_dout_en  = xtrig_ctp_req_in_dout_en;
  assign u_xtrig_if.xtrig_ctp_req_in_din_en   = xtrig_ctp_req_in_din_en;
  assign u_xtrig_if.xtrig_ctp_ack_in_dout     = xtrig_ctp_ack_in_dout;
  assign u_xtrig_if.xtrig_ctp_ack_in_dout_en  = xtrig_ctp_ack_in_dout_en;
  assign u_xtrig_if.xtrig_ctp_ack_in_din_en   = xtrig_ctp_ack_in_din_en;
  assign u_xtrig_if.xtrig_ctp_ack_out_dout    = xtrig_ctp_ack_out_dout;
  assign u_xtrig_if.xtrig_ctp_ack_out_dout_en = xtrig_ctp_ack_out_dout_en;
  assign u_xtrig_if.xtrig_ctp_ack_out_din_en  = xtrig_ctp_ack_out_din_en;

  // ------------------------------------------------------------------
  // Protocol SVA checkers (ocah_jtag_vip/sva, ocah_axi_vip/sva, and the
  // STAP host-leg rules of tb/dtp_stap_host_sva.sv and the data rules of
  // tb/dtp_axi_data_known_sva.sv), shared by both frameworks. The
  // two-state rules run on every simulator (Verilator evaluates them under
  // --assert); the X-hygiene rules run only on a four-state simulator.
  // dtp_tb_if.jtag_sva_en / axi_sva_en are the runtime suppress knobs.
  // ------------------------------------------------------------------
  // Primary TAP pins plus the exported one-hot TAP state. The TAP controller
  // resets on TRST and on power-on reset (jtag_ptap ANDs them), so the
  // checker's reset is the same AND.
  logic jtag_tap_rst_n;
  assign jtag_tap_rst_n = jtag_trst & pwr_on_rst_ni;

  ocah_jtag_sva #(
    .EN_STATE_RULES(1'b1)
  ) u_jtag_ptap_sva (
    .tck         (jtag_tck),
    .tms         (jtag_tms),
    .tdi         (jtag_tdi),
    .trst_n      (jtag_tap_rst_n),
    .tdo         (jtag_tdo),
    .tdo_oen     (jtag_tdo_oen),
    .en_i        (u_tb_if.jtag_sva_en),
    .tap_state_i (jtag_ptap_state)
  );

  // STAP host legs, each timed and reset by its own forwarded TCK and TRST.
  dtp_stap_host_sva u_stap_io_host_sva (
    .tck    (jtag_stap_io_tck),
    .trst_n (jtag_stap_io_trst_n),
    .tms    (jtag_stap_io_tms),
    .tdo    (jtag_stap_io_tdo),
    .tdo_oen(jtag_stap_io_tdo_oen),
    .en_i   (u_tb_if.jtag_sva_en)
  );

  dtp_stap_host_sva u_stap_smc_host_sva (
    .tck    (jtag_stap_smc_tck),
    .trst_n (jtag_stap_smc_trst_n),
    .tms    (jtag_stap_smc_tms),
    .tdo    (jtag_stap_smc_tdo),
    .tdo_oen(jtag_stap_smc_tdo_oen),
    .en_i   (u_tb_if.jtag_sva_en)
  );

  dtp_stap_host_sva u_stap_sep_host_sva (
    .tck    (jtag_stap_sep_tck),
    .trst_n (jtag_stap_sep_trst_n),
    .tms    (jtag_stap_sep_tms),
    .tdo    (jtag_stap_sep_tdo),
    .tdo_oen(jtag_stap_sep_tdo_oen),
    .en_i   (u_tb_if.jtag_sva_en)
  );

  dtp_stap_host_sva u_stap_extra0_host_sva (
    .tck    (jtag_stap_extra0_tck),
    .trst_n (jtag_stap_extra0_trst_n),
    .tms    (jtag_stap_extra0_tms),
    .tdo    (jtag_stap_extra0_tdo),
    .tdo_oen(jtag_stap_extra0_tdo_oen),
    .en_i   (u_tb_if.jtag_sva_en)
  );

  ocah_axi_sva #(
    .IS_LITE    (1'b1),
    .ADDR_WIDTH (dtp_dv_cfg_pkg::OtpAxilAddrWidth),
    .DATA_WIDTH (dtp_dv_cfg_pkg::OtpAxilDataWidth),
    .ID_WIDTH   (1)
  ) u_smc_otp_axil_sva (
    .aclk    (clk_i),
    .aresetn (rst_n_i),
    .en_i    (u_tb_if.axi_sva_en),
    .awid    ('0),
    .awaddr  (smc_otp_axil_awaddr),
    .awlen   ('0),
    .awsize  (OtpAxilBeatSize),
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
    .arsize  (OtpAxilBeatSize),
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
    .IS_LITE    (1'b1),
    .ADDR_WIDTH (dtp_dv_cfg_pkg::OtpAxilAddrWidth),
    .DATA_WIDTH (dtp_dv_cfg_pkg::OtpAxilDataWidth),
    .ID_WIDTH   (1)
  ) u_sep_otp_axil_sva (
    .aclk    (clk_i),
    .aresetn (rst_n_i),
    .en_i    (u_tb_if.axi_sva_en),
    .awid    ('0),
    .awaddr  (sep_otp_axil_awaddr),
    .awlen   ('0),
    .awsize  (OtpAxilBeatSize),
    .awburst (2'b01),
    .awlock  (1'b0),
    .awprot  (sep_otp_axil_awprot),
    .awvalid (sep_otp_axil_awvalid),
    .awready (sep_otp_axil_awready),
    .wdata   (sep_otp_axil_wdata),
    .wstrb   (sep_otp_axil_wstrb),
    .wlast   (1'b1),
    .wvalid  (sep_otp_axil_wvalid),
    .wready  (sep_otp_axil_wready),
    .bid     ('0),
    .bresp   (sep_otp_axil_bresp),
    .bvalid  (sep_otp_axil_bvalid),
    .bready  (sep_otp_axil_bready),
    .arid    ('0),
    .araddr  (sep_otp_axil_araddr),
    .arlen   ('0),
    .arsize  (OtpAxilBeatSize),
    .arburst (2'b01),
    .arlock  (1'b0),
    .arprot  (sep_otp_axil_arprot),
    .arvalid (sep_otp_axil_arvalid),
    .arready (sep_otp_axil_arready),
    .rid     ('0),
    .rdata   (sep_otp_axil_rdata),
    .rresp   (sep_otp_axil_rresp),
    .rlast   (1'b1),
    .rvalid  (sep_otp_axil_rvalid),
    .rready  (sep_otp_axil_rready)
  );

  ocah_axi_sva #(
    .IS_LITE    (1'b0),
    .ADDR_WIDTH (dtp_dv_cfg_pkg::SmcAxiAddrWidth),
    .DATA_WIDTH (dtp_dv_cfg_pkg::SmcAxiDataWidth),
    .ID_WIDTH   (dtp_dv_cfg_pkg::SmcAxiIdWidth)
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

  ocah_axi_sva #(
    .IS_LITE    (1'b1),
    .ADDR_WIDTH (32),
    .DATA_WIDTH (32),
    .ID_WIDTH   (1)
  ) u_xtrig_axil_sva (
    .aclk    (clk_i),
    .aresetn (rst_n_i),
    .en_i    (u_tb_if.axi_sva_en),
    .awid    ('0),
    .awaddr  (xtrig_axil_awaddr),
    .awlen   ('0),
    .awsize  (3'd2),
    .awburst (2'b01),
    .awlock  (1'b0),
    .awprot  (xtrig_axil_awprot),
    .awvalid (xtrig_axil_awvalid),
    .awready (xtrig_axil_awready),
    .wdata   (xtrig_axil_wdata),
    .wstrb   (xtrig_axil_wstrb),
    .wlast   (1'b1),
    .wvalid  (xtrig_axil_wvalid),
    .wready  (xtrig_axil_wready),
    .bid     ('0),
    .bresp   (xtrig_axil_bresp),
    .bvalid  (xtrig_axil_bvalid),
    .bready  (xtrig_axil_bready),
    .arid    ('0),
    .araddr  (xtrig_axil_araddr),
    .arlen   ('0),
    .arsize  (3'd2),
    .arburst (2'b01),
    .arlock  (1'b0),
    .arprot  (xtrig_axil_arprot),
    .arvalid (xtrig_axil_arvalid),
    .arready (xtrig_axil_arready),
    .rid     ('0),
    .rdata   (xtrig_axil_rdata),
    .rresp   (xtrig_axil_rresp),
    .rlast   (1'b1),
    .rvalid  (xtrig_axil_rvalid),
    .rready  (xtrig_axil_rready)
  );

  // Four-state data rules on the data each port's DUT side drives: the
  // strobed WDATA lanes of the three JTAG2AXI bridge ports and the RDATA of
  // the XTRIG CSR port.
  dtp_axi_data_known_sva #(
    .DATA_WIDTH     (dtp_dv_cfg_pkg::OtpAxilDataWidth),
    .EN_W_DATA_RULE (1'b1)
  ) u_smc_otp_axil_data_sva (
    .aclk    (clk_i),
    .aresetn (rst_n_i),
    .en_i    (u_tb_if.axi_sva_en),
    .wdata   (smc_otp_axil_wdata),
    .wstrb   (smc_otp_axil_wstrb),
    .wvalid  (smc_otp_axil_wvalid),
    .rdata   ('0),
    .rvalid  (1'b0)
  );

  dtp_axi_data_known_sva #(
    .DATA_WIDTH     (dtp_dv_cfg_pkg::OtpAxilDataWidth),
    .EN_W_DATA_RULE (1'b1)
  ) u_sep_otp_axil_data_sva (
    .aclk    (clk_i),
    .aresetn (rst_n_i),
    .en_i    (u_tb_if.axi_sva_en),
    .wdata   (sep_otp_axil_wdata),
    .wstrb   (sep_otp_axil_wstrb),
    .wvalid  (sep_otp_axil_wvalid),
    .rdata   ('0),
    .rvalid  (1'b0)
  );

  dtp_axi_data_known_sva #(
    .DATA_WIDTH     (dtp_dv_cfg_pkg::SmcAxiDataWidth),
    .EN_W_DATA_RULE (1'b1)
  ) u_m_axi_data_sva (
    .aclk    (clk_i),
    .aresetn (rst_n_i),
    .en_i    (u_tb_if.axi_sva_en),
    .wdata   (m_axi_wdata),
    .wstrb   (m_axi_wstrb),
    .wvalid  (m_axi_wvalid),
    .rdata   ('0),
    .rvalid  (1'b0)
  );

  dtp_axi_data_known_sva #(
    .DATA_WIDTH     (32),
    .EN_R_DATA_RULE (1'b1)
  ) u_xtrig_axil_data_sva (
    .aclk    (clk_i),
    .aresetn (rst_n_i),
    .en_i    (u_tb_if.axi_sva_en),
    .wdata   ('0),
    .wstrb   ('0),
    .wvalid  (1'b0),
    .rdata   (xtrig_axil_rdata),
    .rvalid  (xtrig_axil_rvalid)
  );

`ifdef UVM
  // ------------------------------------------------------------------
  // SV-UVM harness (`--framework uvm`): the system clock generator, the
  // test classes, uvm_config_db publication of every interface instance,
  // and run_test().
  // ------------------------------------------------------------------
  import uvm_pkg::*;

  // System clock with the period the env publishes on dtp_tb_if from the
  // seeded test cfg (10..100 ns); TCK is bit-banged by the VIP driver.
  always #(u_tb_if.clk_period_ns * 0.5ns) u_tb_if.clk = ~u_tb_if.clk;

  // Non-reusable test classes compile as part of this top (module scope).
  `include "dtp_tests.sv"

  initial begin
    uvm_config_db#(virtual ocah_jtag_if)::set(null, "*", "jtag_vif", u_jtag_if);
    uvm_config_db#(virtual dtp_tb_if)::set(null, "*", "tb_vif", u_tb_if);
    uvm_config_db#(virtual dtp_scan_if)::set(null, "*", "scan_vif", u_scan_if);
    uvm_config_db#(virtual dtp_xtrig_if)::set(null, "*", "xtrig_vif", u_xtrig_if);
    uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "smc_otp_axil_vif", u_smc_otp_axil_if);
    uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "smc_otp_slave_vif", u_smc_otp_slave_if);
    uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "sep_otp_axil_vif", u_sep_otp_axil_if);
    uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "sep_otp_slave_vif", u_sep_otp_slave_if);
    uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "smc_axi_slave_vif", u_smc_axi_slave_if);
    uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "m_axi_vif", u_m_axi_if);
    uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "xtrig_master_vif", u_xtrig_master_if);
    uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "xtrig_axil_vif", u_xtrig_axil_if);
    uvm_config_db#(virtual ocah_jtag_if)::set(null, "*", "stap_io_ds_vif", u_stap_io_ds_if);
    uvm_config_db#(virtual ocah_jtag_if)::set(null, "*", "stap_smc_ds_vif", u_stap_smc_ds_if);
    uvm_config_db#(virtual ocah_jtag_if)::set(null, "*", "stap_sep_ds_vif", u_stap_sep_ds_if);
    uvm_config_db#(virtual ocah_jtag_if)::set(null, "*", "stap_extra0_ds_vif", u_stap_extra0_ds_if);
    run_test();
  end
`endif

endmodule : dtp_uvm_top
