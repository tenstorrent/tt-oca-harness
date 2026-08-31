// SPDX-License-Identifier: Apache-2.0
//
// DTP (Debug & Test Ports) open-source testbench top, shared between the
// cocotb (PyUVM) and SystemVerilog UVM flows. ONE module, two shapes:
//
//   * default (cocotb, `--dut dtp`): the module exposes the full pin-level
//     port list and cocotb drives/samples the toplevel ports.
//   * `UVM` (SV-UVM, `--dut dtp --framework uvm`): the port list is replaced by
//     internal TB signals, and the harness block at the end of the module
//     adds the clock, ocah_jtag_if/dtp_tb_if instances, quiescent tie-offs,
//     and run_test(). Test classes are compiled via `include "dtp_tests.sv".
//
// Both shapes expand the same signal list, dtp_tb_signal_list.svh, through
// the DTP_TB_* macros defined just below -- each TB signal is declared in
// exactly one place and the two shapes cannot drift apart.
//
// Exposes the DTP DUT's primary JTAG TAP at pin level so the TB BFM can
// drive it, plus system clock/reset. The JTAG TAP FSM lives *inside* `dtp`
// (jtag_tap_ctrlr in jtag_intf_unit), so the client port is the decoded
// {tms,trst_n,tck} struct plus tdi/tdo -- effectively raw JTAG pins.
//
// The STAP/iJTAG scan chains are looped back (scan_in = scan_out). The
// functional ports are otherwise pin-exposed: the JTAG2AXI and SMC/SEP OTP
// AXI-Lite managers are answered by AXI memory/RAM BFMs on flattened
// struct <-> signal adapters, and the XTRIG CSR AXI-Lite and clock-stop
// request inputs are driven by the env (the UVM shape ties them off below).

`timescale 1ps/1fs

// Shape selection for dtp_tb_signal_list.svh: the same list expands as the
// ANSI port list (cocotb) or as internal TB signals (`UVM`). The macros live
// only from here to the `undef block after the module header.
`ifndef UVM
    // cocotb shape: every entry is a pin-level ANSI port.
    `define DTP_TB_IN_FIRST(dtype, name) input  wire dtype name
    `define DTP_TB_IN(dtype, name)     , input  wire dtype name
    `define DTP_TB_OUT(dtype, name)    , output dtype name
    `define DTP_TB_IN_COCOTB(dtype, name) , input  wire dtype name
`else
    // SV-UVM shape: every entry is an internal TB signal for the harness
    // block at the end of this module; cocotb-only stimulus expands to
    // nothing (the harness drives the typed struct directly).
    `define DTP_TB_IN_FIRST(dtype, name) dtype name;
    `define DTP_TB_IN(dtype, name) dtype name;
    `define DTP_TB_OUT(dtype, name) dtype name;
    `define DTP_TB_IN_COCOTB(dtype, name)
`endif

module dtp_uvm_top
    import prim_jtag_pkg::*;
    import jtag_tap_pkg::*;
    import jtag_inst_reg_pkg::*;
    import dtp_pkg::*;
`ifndef UVM
(
    `include "dtp_tb_signal_list.svh"
);
`else
;
    `include "dtp_tb_signal_list.svh"
`endif

`undef DTP_TB_IN_FIRST
`undef DTP_TB_IN
`undef DTP_TB_OUT
`undef DTP_TB_IN_COCOTB

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
        .tap_state_i    (jtag_ptap_state),
        .inst_decoded_i (jtag_ptap_inst_decoded),
        .dbg_disable_i  (dbg_disable)
    );

    // JTAG2AXI / OTP bridge coverage. The completed-response boundary comes
    // from each bridge's TCK-domain bookkeeping via hierarchical references
    // (the cocotb Verilator build compiles with --public-flat-rw; VCS
    // resolves them natively); bus-timing bins use the flat AXI pins.
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

    // Debug-TDR coverage (TMP / IC_RESET / DEBUG_CONTROL / CAPS): flattened
    // TDR outputs plus the TMP unit and clock-stop contributions through
    // hierarchical references.
    dtp_debug_tdr_fcov u_dtp_debug_tdr_fcov (
        .tck_i                 (jtag_tck),
        .tdi_i                 (jtag_tdi),
        .tdo_i                 (jtag_tdo),
        .trst_ni               (jtag_trst),
        .clk_i                 (clk_i),
        .rst_ni                (rst_n_i),
        .tap_state_i           (jtag_ptap_state),
        .inst_decoded_i        (jtag_ptap_inst_decoded),
        .ic_reset_smc_ovrd_i   (jtag_ic_reset_smc_ovrd),
        .ic_reset_smc_ctrl_n_i (jtag_ic_reset_smc_ctrl_n),
        .ic_reset_sep_ovrd_i   (jtag_ic_reset_sep_ovrd),
        .ic_reset_sep_ctrl_n_i (jtag_ic_reset_sep_ctrl_n),
        .ic_reset_ext_ovrd_i   (jtag_ic_reset_ext_ovrd),
        .ic_reset_ext_ctrl_n_i (jtag_ic_reset_ext_ctrl_n),
        .boot_stall_ovrd_i     (jtag_boot_stall_ovrd),
        .boot_stall_i          (jtag_boot_stall),
        .stop_clks_i           (stop_clks),
        .cla_clock_stop_en_i   (cla_clock_stop_en),
        .clk_stop_req_i        (xtrig_clk_stop_req),
        .tmp_state_i           (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_tmp_controller.u_jtag_tmp.tmp_state_q_bits),
        .tmp_status_reg_i      (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_tmp_status_reg.u_jtag_tmp_status_reg.tmp_status_reg_q),
        .tmp_escape_cond_i     (u_dut.u_jtag_intf_unit.u_jtag_ptap.gen_tmp_controller.u_jtag_tmp.bypass_escape_condition),
        .jtag_clock_stop_i     (u_dut.jtag_clock_stop),
        .cla_clock_stop_i      (u_dut.cla_clock_stop)
    );

    // Scan-network coverage (iJTAG SIBs / STAP 3DCR): flattened chain
    // controls plus each STAP's stored 3DCR state through hierarchical
    // references (sel_int is the stored select before the security gate).
    dtp_scan_fcov u_dtp_scan_fcov (
        .tck_i                  (jtag_tck),
        .trst_ni                (jtag_trst),
        .tap_state_i            (jtag_ptap_state),
        .inst_decoded_i         (jtag_ptap_inst_decoded),
        .dbg_disable_i          (dbg_disable),
        .dft_secure_select_i    (jtag_dft_secure_select),
        .dft_secure_shift_en_i  (jtag_dft_secure_shift_en),
        .dft_select_i           (jtag_dft_select),
        .dft_shift_en_i         (jtag_dft_shift_en),
        .dfd_select_i           (jtag_dfd_select),
        .dfd_shift_en_i         (jtag_dfd_shift_en),
        .stap_io_tdo_oen_i      (jtag_stap_io_tdo_oen),
        .stap_smc_tdo_oen_i     (jtag_stap_smc_tdo_oen),
        .stap_sep_tdo_oen_i     (jtag_stap_sep_tdo_oen),
        .stap_extra_tdo_oen_i   (jtag_stap_extra0_tdo_oen),
        .stap_io_sel_i         (u_dut.u_jtag_intf_unit.gen_stap_io.u_stap_io.stap_sel),
        .stap_io_sel_int_i      (u_dut.u_jtag_intf_unit.gen_stap_io.u_stap_io.stap_sel_int),
        .stap_io_tms_hold_i     (u_dut.u_jtag_intf_unit.gen_stap_io.u_stap_io.tms_hold),
        .stap_io_config_hold_i  (u_dut.u_jtag_intf_unit.gen_stap_io.u_stap_io.config_hold),
        .stap_smc_sel_i         (u_dut.u_jtag_intf_unit.gen_stap_smc_dbg.u_stap_smc_dbg.stap_sel),
        .stap_smc_sel_int_i     (u_dut.u_jtag_intf_unit.gen_stap_smc_dbg.u_stap_smc_dbg.stap_sel_int),
        .stap_smc_tms_hold_i    (u_dut.u_jtag_intf_unit.gen_stap_smc_dbg.u_stap_smc_dbg.tms_hold),
        .stap_smc_config_hold_i (u_dut.u_jtag_intf_unit.gen_stap_smc_dbg.u_stap_smc_dbg.config_hold),
        .stap_sep_sel_i         (u_dut.u_jtag_intf_unit.gen_stap_sep_dbg.u_stap_sep_dbg.stap_sel),
        .stap_sep_sel_int_i     (u_dut.u_jtag_intf_unit.gen_stap_sep_dbg.u_stap_sep_dbg.stap_sel_int),
        .stap_sep_tms_hold_i    (u_dut.u_jtag_intf_unit.gen_stap_sep_dbg.u_stap_sep_dbg.tms_hold),
        .stap_sep_config_hold_i (u_dut.u_jtag_intf_unit.gen_stap_sep_dbg.u_stap_sep_dbg.config_hold),
        .stap_extra_sel_i       (u_dut.u_jtag_intf_unit.gen_extra_staps.gen_extra_stap[0].u_stap_extra.stap_sel),
        .stap_extra_sel_int_i   (u_dut.u_jtag_intf_unit.gen_extra_staps.gen_extra_stap[0].u_stap_extra.stap_sel_int),
        .stap_extra_tms_hold_i  (u_dut.u_jtag_intf_unit.gen_extra_staps.gen_extra_stap[0].u_stap_extra.tms_hold),
        .stap_extra_config_hold_i (u_dut.u_jtag_intf_unit.gen_extra_staps.gen_extra_stap[0].u_stap_extra.config_hold)
    );

    // Cross-trigger coverage (CTP / CTM): CSR-write decode plus the
    // cross-trigger GPIO and matrix handshake pins, all in the system-clock
    // domain. The SV-UVM shape ties these inputs quiescent, so the bins
    // collect only where the stimulus exists (the cocotb flow today).
    dtp_xtrig_fcov u_dtp_xtrig_fcov (
        .clk_i                 (clk_i),
        .rst_ni                (rst_n_i),
        .axil_awaddr_i         (xtrig_axil_awaddr),
        .axil_awvalid_i        (xtrig_axil_awvalid),
        .axil_awready_i        (xtrig_axil_awready),
        .axil_wdata_i          (xtrig_axil_wdata),
        .axil_wvalid_i         (xtrig_axil_wvalid),
        .axil_wready_i         (xtrig_axil_wready),
        .ctm_src_req_i         (xtrig_ctm_src_req),
        .ctm_dst_req_i         (xtrig_ctm_dst_req),
        .ctp_req_out_dout_i    (xtrig_ctp_req_out_dout),
        .ctp_req_out_dout_en_i (xtrig_ctp_req_out_dout_en),
        .ctp_req_in_din_i      (xtrig_ctp_req_in_din),
        .ctp_ack_in_din_i      (xtrig_ctp_ack_in_din)
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

    // Decoded-IR and boundary-scan control observables: the
    // basic-JTAG instruction checks read these through dtp_tb_if.
    assign u_tb_if.inst_decoded        = jtag_ptap_inst_decoded;
    assign u_tb_if.jtag_bsr_select     = jtag_bsr_select;
    assign u_tb_if.jtag_bsr_shift_en   = jtag_bsr_shift_en;
    assign u_tb_if.jtag_bsr_capture_en = jtag_bsr_capture_en;
    assign u_tb_if.jtag_bsr_update_en  = jtag_bsr_update_en;

    // Lifecycle debug disables and clock-stop requests: sequences drive the
    // typed dbg_disable_t through dtp_tb_if (init '1 = fail-closed, so the
    // sanity test's behavior is unchanged; JTAG2AXI sequences clear the
    // disables they need).
    assign xtrig_clk_stop_req = '0;
    assign dbg_disable        = u_tb_if.dbg_disable;

    // SMC OTP AXI-Lite responder: the shared ocah_axi_vip UVM slave agent
    // answers JTAG2AXI OTP traffic. The slave interface carries
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

    // SEP OTP AXI-Lite responder: a third shared ocah_axi_vip UVM slave
    // agent (same pattern as the SMC OTP port) answers JTAG2AXI SEP OTP
    // traffic.
    ocah_axi_if u_sep_otp_slave_if (.aclk(clk_i), .aresetn(rst_n_i));
    assign u_sep_otp_slave_if.awaddr   = 64'(sep_otp_axil_awaddr);
    assign u_sep_otp_slave_if.awprot   = sep_otp_axil_awprot;
    assign u_sep_otp_slave_if.awvalid  = sep_otp_axil_awvalid;
    assign u_sep_otp_slave_if.awid     = '0;
    assign u_sep_otp_slave_if.awlen    = '0;
    assign u_sep_otp_slave_if.awsize   = 3'd2;
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
    assign u_sep_otp_slave_if.arsize   = 3'd2;
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
    assign sep_otp_axil_bvalid  = u_sep_otp_slave_if.bvalid;
    assign sep_otp_axil_arready = u_sep_otp_slave_if.arready;
    assign sep_otp_axil_rdata   = u_sep_otp_slave_if.rdata[31:0];
    assign sep_otp_axil_rresp   = u_sep_otp_slave_if.rresp;
    assign sep_otp_axil_rvalid  = u_sep_otp_slave_if.rvalid;

    // SMC fabric AXI4 responder: the shared ocah_axi_vip UVM slave agent
    // (same pattern as the SMC OTP port) answers JTAG2AXI fabric traffic.
    // The slave interface carries the connection: the TB wires only the
    // master-driven signals in, and the agent's driver procedurally drives
    // the responder-side signals, routed back to the DUT below. Error
    // injection and backdoor memory access are programmed by sequences via
    // the agent's ocah_axi_slave_sequence, not TB error ports.
    ocah_axi_if u_smc_axi_slave_if (.aclk(clk_i), .aresetn(rst_n_i));
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

    // Responder-side signals: agent driver -> DUT response inputs.
    assign m_axi_awready = u_smc_axi_slave_if.awready;
    assign m_axi_wready  = u_smc_axi_slave_if.wready;
    assign m_axi_bid     = u_smc_axi_slave_if.bid[1:0];
    assign m_axi_bresp   = u_smc_axi_slave_if.bresp;
    assign m_axi_buser   = '0;
    assign m_axi_bvalid  = u_smc_axi_slave_if.bvalid;
    assign m_axi_arready = u_smc_axi_slave_if.arready;
    assign m_axi_rid     = u_smc_axi_slave_if.rid[1:0];
    assign m_axi_rdata   = u_smc_axi_slave_if.rdata;
    assign m_axi_rresp   = u_smc_axi_slave_if.rresp;
    assign m_axi_rlast   = u_smc_axi_slave_if.rlast;
    assign m_axi_ruser   = '0;
    assign m_axi_rvalid  = u_smc_axi_slave_if.rvalid;

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

    ocah_axi_if u_sep_otp_axil_if (.aclk(clk_i), .aresetn(rst_n_i));
    assign u_sep_otp_axil_if.awaddr   = 64'(sep_otp_axil_awaddr);
    assign u_sep_otp_axil_if.awprot   = sep_otp_axil_awprot;
    assign u_sep_otp_axil_if.awvalid  = sep_otp_axil_awvalid;
    assign u_sep_otp_axil_if.awready  = sep_otp_axil_awready;
    assign u_sep_otp_axil_if.awid     = '0;
    assign u_sep_otp_axil_if.awlen    = '0;
    assign u_sep_otp_axil_if.awsize   = 3'd2;
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
    assign u_sep_otp_axil_if.arsize   = 3'd2;
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
        .IS_LITE    (1'b1),
        .ADDR_WIDTH (32),
        .DATA_WIDTH (32),
        .ID_WIDTH   (1)
    ) u_sep_otp_axil_sva (
        .aclk    (clk_i),
        .aresetn (rst_n_i),
        .en_i    (u_tb_if.axi_sva_en),
        .awid    ('0),
        .awaddr  (sep_otp_axil_awaddr),
        .awlen   ('0),
        .awsize  (3'd2),
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
        .arsize  (3'd2),
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
    assign u_tb_if.sep_otp_axil_awvalid_count = sep_otp_axil_awvalid_count;
    assign u_tb_if.sep_otp_axil_wvalid_count  = sep_otp_axil_wvalid_count;
    assign u_tb_if.sep_otp_axil_arvalid_count = sep_otp_axil_arvalid_count;

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
        uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "sep_otp_axil_vif", u_sep_otp_axil_if);
        uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "sep_otp_slave_vif", u_sep_otp_slave_if);
        uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "smc_axi_slave_vif", u_smc_axi_slave_if);
        uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "m_axi_vif", u_m_axi_if);
        run_test();
    end
`endif

endmodule : dtp_uvm_top
