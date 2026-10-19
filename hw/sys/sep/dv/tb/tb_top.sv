// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP OSS DV testbench top, shared by the native cocotb / PyUVM flow and
// the SystemVerilog UVM flow. ONE module, two shapes:
//   * default (cocotb, `--dut sep`): the pin-level ANSI port list cocotb
//     drives and samples;
//   * `UVM` (SV-UVM, `--dut sep --framework uvm`): the port list is replaced
//     by internal TB signals and the harness block at the end of the module
//     adds the clocks, the shared-VIP interfaces on the CPU-LSU splice,
//     quiescent tie-offs, uvm_config_db publication, and run_test(). Test
//     classes are compiled via `include "sep_tests.sv".
// Every TB signal is declared once, in tb/sep_tb_signal_list.svh, and
// expanded into the selected shape by the SEP_TB_* macros below.
//
// Wraps the `sep_wrapper` DUT (hw/top/sep_wrapper.sv, which instantiates the bare
// `sep` core from hw/sys/sep/rtl/sep.sv). Clocks, reset and boot controls are
// top-level ports. Every unused DUT port is tied to a benign idle value so
// nothing X-props.
//
// The primary stimulus path is the SEP CPU's own LSU AXI master bus
// `SEP_CORE.u_sep_cpu.lsu_axi_req` / `lsu_axi_resp`, sep_32_64_3_12
// (addr32/data64/id3/user12). A cocotbext-axi AxiMaster drives it through the
// flat `s_axi_*` ports. This path reaches the SEP-local fabric through the
// same ROM/xbar routing point as the core, so the external SMN inbound filter
// is NOT in the path. `smn_inbound` is brought out as the flat `m_axi_*`
// master: the DUT's real external inbound port, which traverses the inbound
// filter. It idles unless a test drives it. The inbound-filter-gating test
// uses it to prove that feat_ctrl.sep_debug blocks or allows external AXI.
//
// Two run modes, selected by the `+cpu_boot` plusarg:
//   * no-CPU (default): the core (VeeR EL2) is held off
//     (mpc_reset_run_req=0) and cocotb drives the SEP fabric over s_axi. The
//     stub build (`SEP_CPU_STUB`) is the sole driver of lsu_axi_req and
//     assigns it from the tb's assembled request (`assign`, no `force`; see
//     shims/cpu/sep_cpu_stub.sv). The full-CPU VCS build force-splices the
//     same post-remap `lsu_axi_req` and holds `lsu_axi_resp_raw` idle.
//     The Verilator no_cpu build stays on the stub. The tb reads lsu_axi_resp
//     back by name.
//   * CPU firmware boot (+cpu_boot): runs on the full-CPU build, the core owns all of
//     its master buses, fetches firmware out of the wrapper's real TCM macros, and
//     runs. The boot test backdoor-loads the TCM (tb_backdoor_mem, on tcm_load_i),
//     passes the desired reset vector to this top, which drives the wrapper's
//     direct reset-vector input before reset releases, asserts mpc_reset_run_req,
//     and observes PC advance (sep_cpu_trace) plus the firmware console/PASS
//     magic on the outbound mailbox responder (sep_outbound_mbx).
//
// Boot/reset invariants:
//   * ext_boot_seq_done_i = 1   (DUT port, driven by cocotb)
//   * +skip_fuse_sense          (RTL plusarg, set by tests that bypass real sense)
//   * smc_fuse_sense_done_i     (TB-modelled; +sep_smc_fuse_sense_hold holds it low)
//   * mpc_reset_run_req         (0 = hold the CPU off [no_cpu]; 1 = run [cpu])
//
// The CPU LSU req/resp struct (vendor/pulp-platform/axi AXI_TYPEDEF_ALL) is
// bridged to flat `s_axi_*` ports so cocotb binds via
// AxiBus.from_prefix(dut, "s_axi").

`timescale 1ps/1fs

// Shape selection for sep_tb_signal_list.svh: the same list expands as the
// ANSI port list (cocotb) or as internal TB signals (`UVM`). The macros live
// only from here to the `undef block after the module header.
`ifndef UVM
    // cocotb shape: every entry is a pin-level ANSI port, published to cocotb
    // through the Verilator metacomment (sep_public_scope.vlt publishes the
    // whole module as well).
    `define SEP_TB_IN_FIRST(dtype, name) input  wire dtype name /*verilator public_flat_rw*/
    `define SEP_TB_IN(dtype, name)     , input  wire dtype name /*verilator public_flat_rw*/
    `define SEP_TB_OUT(dtype, name)    , output dtype name /*verilator public_flat_rw*/
`else
    // SV-UVM shape: every entry is an internal TB signal for the harness
    // block at the end of this module.
    `define SEP_TB_IN_FIRST(dtype, name) dtype name;
    `define SEP_TB_IN(dtype, name) dtype name;
    `define SEP_TB_OUT(dtype, name) dtype name;
`endif

// The signal list qualifies every package-scoped type explicitly, so the DUT
// package imports follow the header (a module header that carries imports and
// no port list is rejected by some frontends).
module sep_uvm_top
`ifndef UVM
(
    `include "sep_tb_signal_list.svh"
);
`else
;
    `include "sep_tb_signal_list.svh"
`endif

`undef SEP_TB_IN_FIRST
`undef SEP_TB_IN
`undef SEP_TB_OUT

    import sep_pkg::*;
    import sep_crypto_pkg::*;
    import sep_io_pkg::*;

    // ------------------------------------------------------------------
    // DUT-flavor XMR roots. The DUT is `sep_wrapper`, so sep-internal state lives
    // under u_dut.u_sep and the OSS IP integration (memory macros, generic efuse
    // model) under u_dut.u_sep_ip_integration. The OpenTitan SPI host is inside
    // the `sep` core. Every sep-internal XMR read routes through `SEP_CORE /
    // `SEP_IPI so one probe text is used throughout.
    // ------------------------------------------------------------------
    `define SEP_CORE u_dut.u_sep
    `define SEP_IPI  u_dut.u_sep_ip_integration
    // The entropy complex sits below sep_crypto inside sep_trng, which owns the
    // shared TRNG reset. Naming that level once means a hierarchy change is made
    // here rather than at every entropy probe and assertion scope below.
    `define SEP_ESRC `SEP_CORE.u_sep_crypto.u_sep_trng.u_entropy_source_s3c_scan
    `define SEP_DRBG `SEP_CORE.u_sep_crypto.u_sep_trng.u_drbg_s3c_scan

    // ------------------------------------------------------------------
    // Idle / benign tie-off nets for the unused external ports.
    // ('0 default-init on structs keeps every input req/rsp port at idle.)
    // ------------------------------------------------------------------
    // SMN inbound external AXI: assembled (combinationally, below) from the flat
    // m_axi_* master inputs and read back to the flat m_axi_* outputs. Always wired
    // to the DUT's smn_inbound_axi_req_i port (idles unless a test drives m_axi_*).
    sep_pkg::sep_system_peripherals_internal_axi_req_t  smn_inbound_req_drive;
    sep_pkg::sep_system_peripherals_internal_axi_resp_t smn_inbound_resp_w;
    // SEP->SMC external AXI. With SEP_SMC_MEM_MODEL the shared AXI slave agent
    // responds (real R/W to SMC scratch + SRAM) so the Boot ROM can run its SMC
    // scratch round-trip + non-SPI manifest fetch. Every other build answers
    // through the BH-SMC responder, which is idle unless the hook is enabled.
    sep_pkg::sep_system_peripherals_internal_axi_req_t  ext_to_smc_req_w;
    sep_pkg::sep_system_peripherals_internal_axi_resp_t ext_to_smc_resp_w;
    // BH-SMC (docs/SEP_TB_ARCH.adoc, HDL Top port table): the SMC aperture
    // inputs and the SMC responder for builds without SEP_SMC_MEM_MODEL. A leaf
    // sets bh_smc_en_i, bh_smc_base_i and bh_smc_size_i before it releases
    // reset, or a run passes +sep_smc_aperture_base=<hex> and
    // +sep_smc_aperture_size=<hex>. The port drive wins over the plusargs. With
    // neither, both aperture inputs are 0 and the responder stays idle, as in
    // a build with no SMC.
    logic        bh_smc_en;
    logic [55:0] bh_smc_base;
    logic [55:0] bh_smc_size;
    logic        bh_smc_pa_en = 1'b0;
    logic [55:0] bh_smc_pa_base = '0;
    logic [55:0] bh_smc_pa_size = '0;
    initial begin
        if ($value$plusargs("sep_smc_aperture_base=%h", bh_smc_pa_base) &&
            $value$plusargs("sep_smc_aperture_size=%h", bh_smc_pa_size)) begin
            bh_smc_pa_en = 1'b1;
            $display("[tb] BH-SMC aperture from plusargs: base=0x%0h size=0x%0h",
                     bh_smc_pa_base, bh_smc_pa_size);
        end
    end
    always_comb begin
        if (bh_smc_en_i === 1'b1) begin
            bh_smc_en   = 1'b1;
            bh_smc_base = bh_smc_base_i;
            bh_smc_size = bh_smc_size_i;
        end else if (bh_smc_pa_en) begin
            bh_smc_en   = 1'b1;
            bh_smc_base = bh_smc_pa_base;
            bh_smc_size = bh_smc_pa_size;
        end else begin
            bh_smc_en   = 1'b0;
            bh_smc_base = '0;
            bh_smc_size = '0;
        end
    end
    // SEP-OTP JTAG AXI-Lite: assembled from the flat j_axi_* master inputs (below).
    sep_efuse_pkg::efuse_axil_req_t   j_axil_req_drive;
    sep_efuse_pkg::efuse_axil_resp_t  j_axil_resp_w;
    sep_pkg::jtag_sep_reset_ctrl_t   jtag_sep_reset_ctrl_drive;
    // IC_RESET TDR storage for the SEP slice. Width is the integrator SEP-slice
    // table: 8 ports when SEP=1 (doc/integrator/src/smu.adoc). The TAP
    // instruction that selects the TDR is outside this DUT. tdr_en selects
    // the register; otherwise the per-port pins drive the same struct.
    localparam int unsigned SepIcResetPorts = 8;
    prim_jtag_pkg::jtag_scan_ctrl_t ic_reset_scan_ctrl;
    prim_jtag_pkg::jtag_tap_ctrl_t  ic_reset_tap_ctrl;
    logic [SepIcResetPorts-1:0]     ic_reset_ovrd_w;
    logic [SepIcResetPorts-1:0]     ic_reset_ctrl_n_w;
    sep_pkg::jtag_sep_reset_ctrl_t  ic_reset_sep_packed;
    always_comb begin
        ic_reset_scan_ctrl         = '0;
        ic_reset_scan_ctrl.tck     = jtag_ic_reset_tck_i;
        ic_reset_scan_ctrl.select  = jtag_ic_reset_select_i;
        ic_reset_scan_ctrl.capture_en = jtag_ic_reset_capture_en_i;
        ic_reset_scan_ctrl.shift_en   = jtag_ic_reset_shift_en_i;
        ic_reset_scan_ctrl.update_en  = jtag_ic_reset_update_en_i;
        ic_reset_scan_ctrl.rst_n  = jtag_ic_reset_rst_n_i;
        ic_reset_scan_ctrl.chrst_n = 1'b1;
        ic_reset_tap_ctrl          = '0;
        ic_reset_tap_ctrl.trst_n   = jtag_ic_reset_trst_n_i;
        ic_reset_tap_ctrl.tck      = jtag_ic_reset_tck_i;
    end
    jtag_ic_reset_reg #(
        .NUM_IC_RESET_PORTS(SepIcResetPorts)
    ) u_ic_reset_sep (
        .scan_ctrl_i      (ic_reset_scan_ctrl),
        .scan_in_i        (jtag_ic_reset_tdi_i),
        .scan_out_o       (jtag_ic_reset_tdo_o),
        .tap_ctrl_i       (ic_reset_tap_ctrl),
        .ic_reset_ovrd_o  (ic_reset_ovrd_w),
        .ic_reset_ctrl_n_o(ic_reset_ctrl_n_w)
    );
    assign ic_reset_sep_packed.ovrd = ic_reset_ovrd_w;
    assign ic_reset_sep_packed.val  = ic_reset_ctrl_n_w;
    always_comb begin
        if (jtag_ic_reset_tdr_en_i === 1'b1) begin
            jtag_sep_reset_ctrl_drive = ic_reset_sep_packed;
        end else begin
        jtag_sep_reset_ctrl_drive = '0;
        // Ports are Z until cocotb drive_idle_defaults. Treat only 1 as hold.
        jtag_sep_reset_ctrl_drive.ovrd.otbn_jtag_rst_n_ovrd =
            (jtag_otbn_rst_hold_i === 1'b1);
        jtag_sep_reset_ctrl_drive.ovrd.aes_jtag_rst_n_ovrd =
            (jtag_aes_rst_hold_i === 1'b1);
        jtag_sep_reset_ctrl_drive.ovrd.hmac_jtag_rst_n_ovrd =
            (jtag_hmac_rst_hold_i === 1'b1);
        jtag_sep_reset_ctrl_drive.ovrd.kmac_jtag_rst_n_ovrd =
            (jtag_kmac_rst_hold_i === 1'b1);
        jtag_sep_reset_ctrl_drive.ovrd.trng_jtag_rst_n_ovrd =
            (jtag_trng_rst_hold_i === 1'b1);
        jtag_sep_reset_ctrl_drive.ovrd.abr_jtag_rst_n_ovrd =
            (jtag_abr_rst_hold_i === 1'b1);
        jtag_sep_reset_ctrl_drive.ovrd.sep_reset_n_ovrd =
            (jtag_sep_reset_n_ovrd_i === 1'b1);
        jtag_sep_reset_ctrl_drive.val.sep_reset_n_val =
            (jtag_sep_reset_n_val_i === 1'b1);
        end
    end

    // Outbound mailbox responder buses and CPU trace -- the DUT struct nets the
    // wrapper flow needs.
    sep_pkg::sep_system_peripherals_outbound_axi_req_t  smn_outbound_req_w;
    sep_pkg::sep_system_peripherals_outbound_axi_resp_t smn_outbound_resp_w;
    sep_cpu_trace_t    cpu_trace_w;

    // Cocotb drives rst_ni after time 0. Until then the input wire is Z, and
    // PeakRDL immediate asserts in an always_ff else treat `if (~arst_n)` as
    // false when arst_n is X/Z. Hold 0 until the port is a known 0/1, then
    // follow. The bring-up presents rst_ni high before asserting it, so the
    // assertion is a real falling edge and every async-reset flop loads its
    // reset value (sep_base_test.assert_cold_reset).
    // An X/Z on the port AFTER cocotb has driven it is a testbench defect, not
    // the bring-up window: latching the last good level would hide it for the
    // rest of the run, so it fails here instead. rst_n_driven marks the window
    // closed on the first known level.
    logic rst_n_int = 1'b0;
    logic rst_n_driven = 1'b0;
    always @(*) begin
        if ((rst_ni === 1'b0) || (rst_ni === 1'b1)) begin
            rst_n_int = rst_ni;
            rst_n_driven = 1'b1;
        end else if (rst_n_driven) begin
            $error("%0t: rst_ni went %b after being driven; the DUT is running on the last known level",
                   $time, rst_ni);
        end
    end

    // Assertion classes held off, and why each is not a DUT contract here.
    //
    // AssertConnected_A (every hardened counter under entropy_source,
    // axis_edn_crypto and axis_edn_pool) asks whether the counter's err_o reaches
    // an OpenTitan alert, so it cannot fail on DUT behaviour. It is
    // ASSERT_INIT_NET -- an immediate assert in `initial #1ps`, with no clock and
    // no reset -- so `disable iff` cannot gate it and the scope is the only knob.
    //
    // Where err_o is wired it reaches escalation and irq_o, and SEP's
    // entropy_source has no alert output for the OT convention to test; the
    // declarative escape there is EnableAlertTriggerSVA(0) at the instantiation.
    //
    // The remaining counters raise err_o into a net nothing reads, so a green run
    // is NOT evidence that a glitched health-test counter would be reported. The
    // SPI assertions in this subtree are armed only during reset, so they judge
    // nothing after it.
    //
    // Scope is by subtree because these are generate-loop instances with no single
    // name to target, which also disables every other assertion under those three
    // blocks. The contracts re-armed by name are the EDN arbiter hold-until-grant
    // assume and lock assert, the crypto EDN adapter's clear and per-endpoint
    // cancel contracts, the pool EDN adapter's clear contracts, and
    // FipsWindowFloor_A.
`ifndef VERILATOR
    initial begin
        // Scope-level $assertoff: these instances have no clock or reset for
        // `disable iff` to gate. Re-arm by an assertion's own hierarchical
        // name, never by re-enabling a parent instance.
        $assertoff(0, `SEP_ESRC);
        $assertoff(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan);
        $assertoff(0, `SEP_CORE.u_sep_crypto.u_axis_edn_pool_s3c_scan);
        // The adapter waives the arbiter's request checks only on the first
        // cycle of an endpoint flush, so these two stay live for every other
        // request. The adapter scope stays off because AxisEdnEndpointCount_A
        // is an immediate assert with no reset.
        $asserton(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
            .u_arbiter.ReqStaysHighUntilGranted0_M);
        $asserton(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
            .u_arbiter.LockArbDecision_A);
        // The adapter's own contracts for the shared clear. Without these the
        // scope-level $assertoff above would leave the clear unpoliced: an ack
        // leaking through it, or an ack state machine driven to Error by the
        // one-cycle disable, would both pass silently.
        $asserton(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
            .AxisEdnAllAckSmHealthy_A);
        // Unrolled: a generate-block index must resolve at elaboration, so a
        // procedural loop variable cannot select gen_ep[]. One line per
        // endpoint of SepCryptoAxisEdnClientCount (AES, KMAC, OTBN RND,
        // OTBN URND).
        $asserton(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
            .gen_ep[0].AxisEdnNoAckDuringClear_A);
        $asserton(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
            .gen_ep[1].AxisEdnNoAckDuringClear_A);
        $asserton(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
            .gen_ep[2].AxisEdnNoAckDuringClear_A);
        $asserton(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
            .gen_ep[3].AxisEdnNoAckDuringClear_A);
        // The upstream side of the same clear: neither adapter takes an
        // AXI-Stream beat while clear_i is high. The pool adapter's clear is
        // the TRNG reset (trng_reset_active), so its single endpoint must not
        // acknowledge during it either.
        $asserton(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
            .AxisEdnNoReadyDuringClear_A);
        $asserton(0, `SEP_CORE.u_sep_crypto.u_axis_edn_pool_s3c_scan
            .AxisEdnNoReadyDuringClear_A);
        $asserton(0, `SEP_CORE.u_sep_crypto.u_axis_edn_pool_s3c_scan
            .gen_ep[0].AxisEdnNoAckDuringClear_A);
        // Per-endpoint cancel contracts. A cancelled endpoint neither requests,
        // takes a word, nor acknowledges, and an ungranted request only drops
        // under a flush of that endpoint.
        $asserton(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
            .gen_ep[0].AxisEdnCancelledEndpointIdle_A);
        $asserton(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
            .gen_ep[1].AxisEdnCancelledEndpointIdle_A);
        $asserton(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
            .gen_ep[2].AxisEdnCancelledEndpointIdle_A);
        $asserton(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
            .gen_ep[3].AxisEdnCancelledEndpointIdle_A);
        $asserton(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
            .gen_ep[0].AxisEdnReqStableUnlessEndpointCancelled_A);
        $asserton(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
            .gen_ep[1].AxisEdnReqStableUnlessEndpointCancelled_A);
        $asserton(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
            .gen_ep[2].AxisEdnReqStableUnlessEndpointCancelled_A);
        $asserton(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
            .gen_ep[3].AxisEdnReqStableUnlessEndpointCancelled_A);
        // The pool adapter shares the same arbiter, so its arbiter contracts
        // must be live for the same reason.
        $asserton(0, `SEP_CORE.u_sep_crypto.u_axis_edn_pool_s3c_scan
            .u_arbiter.ReqStaysHighUntilGranted0_M);
        $asserton(0, `SEP_CORE.u_sep_crypto.u_axis_edn_pool_s3c_scan
            .u_arbiter.LockArbDecision_A);
        // A JTAG reset override skips isolation, so an engine can drop an
        // ungranted EDN request with no cancel; no word is lost or misrouted.
        if ($test$plusargs("sep_edn_jtag_reset_waive")) begin
            $display("[tb] crypto EDN request-hold checks off (+sep_edn_jtag_reset_waive)");
            $assertoff(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
                .u_arbiter.ReqStaysHighUntilGranted0_M);
            $assertoff(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
                .u_arbiter.LockArbDecision_A);
            $assertoff(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
                .gen_ep[0].AxisEdnReqStableUnlessEndpointCancelled_A);
            $assertoff(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
                .gen_ep[1].AxisEdnReqStableUnlessEndpointCancelled_A);
            $assertoff(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
                .gen_ep[2].AxisEdnReqStableUnlessEndpointCancelled_A);
            $assertoff(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
                .gen_ep[3].AxisEdnReqStableUnlessEndpointCancelled_A);
        end
        // entropy_source.sv FipsWindowFloor_A -- fips_lock |-> window >= 1024.
        // sep_esrc_fips_lock_test writes FIPS_LOCK.LOCK, so a locked
        // out-of-spec window must fail rather than be swept up by the line above.
        $asserton(0, `SEP_ESRC.FipsWindowFloor_A);
        // SHA-256-only prim_sha2_32 (MultimodeEn=0) ties inner digest_mode_i to
        // SHA2_None. ValidDigestModeFlag_A requires {SHA2_256, SHA2_384, SHA2_512}
        // on every hash beat, so it is not a contract on those instances. HMAC
        // and DMA use MultimodeEn=1 and keep the check. $assertoff scopes are
        // resolved from this module, so these are downward XMRs (a module-name
        // scope does not resolve).
        $assertoff(0, `SEP_ESRC
            .u_sha256_whitener.u_sha2.gen_sha256_logic.u_prim_sha2_256
            .ValidDigestModeFlag_A);
        $assertoff(0, `SEP_ESRC
            .u_sha256_whitener.u_sha2.gen_sha256_logic.u_prim_sha2_256.u_pad
            .ValidDigestModeFlag_A);
        $assertoff(0, `SEP_CORE.u_sep_crypto.u_sep_efuse_wrapper
            .u_efuse_interface_controller.gen_mmr_reg.u_efuse_token_processing
            .u_sha256_rma_sip_token.u_prim_sha2_32.gen_sha256_logic
            .u_prim_sha2_256.ValidDigestModeFlag_A);
        $assertoff(0, `SEP_CORE.u_sep_crypto.u_sep_efuse_wrapper
            .u_efuse_interface_controller.gen_mmr_reg.u_efuse_token_processing
            .u_sha256_rma_sip_token.u_prim_sha2_32.gen_sha256_logic
            .u_prim_sha2_256.u_pad.ValidDigestModeFlag_A);
        $assertoff(0, `SEP_CORE.u_sep_crypto.u_sep_efuse_wrapper
            .u_efuse_interface_controller.gen_mmr_reg.u_efuse_token_processing
            .u_sha256_rma_chiplet_token.u_prim_sha2_32.gen_sha256_logic
            .u_prim_sha2_256.ValidDigestModeFlag_A);
        $assertoff(0, `SEP_CORE.u_sep_crypto.u_sep_efuse_wrapper
            .u_efuse_interface_controller.gen_mmr_reg.u_efuse_token_processing
            .u_sha256_rma_chiplet_token.u_prim_sha2_32.gen_sha256_logic
            .u_prim_sha2_256.u_pad.ValidDigestModeFlag_A);
        $assertoff(0, `SEP_CORE.u_sep_crypto.u_sep_efuse_wrapper
            .u_efuse_interface_controller.gen_mmr_reg.u_efuse_token_processing
            .u_sha256_sec_disable_token.u_prim_sha2_32.gen_sha256_logic
            .u_prim_sha2_256.ValidDigestModeFlag_A);
        $assertoff(0, `SEP_CORE.u_sep_crypto.u_sep_efuse_wrapper
            .u_efuse_interface_controller.gen_mmr_reg.u_efuse_token_processing
            .u_sha256_sec_disable_token.u_prim_sha2_32.gen_sha256_logic
            .u_prim_sha2_256.u_pad.ValidDigestModeFlag_A);

    end

    // otbn_rnd.sv UrndNoReseedOnReset_A cannot pass on this instance. It arms
    // only while OTBN is in reset -- disable iff (rst_ni !== '0) -- and its guard
    // reads CURRENT rst_ni while the property body reads SAMPLED rst_ni. SEP
    // asserts OTBN's reset ON a clk_i edge: the reset is a posedge clk_i flop
    // output (sep_isolate_rst_seq.sv gated_rst_n_q), routed through the JTAG
    // override mux u_otbn_rst_ovrd_mux in sep_reset_ctrl.sv to
    // gated_rst_ni.otbn at sep_crypto.sv. At that edge the guard sees reset
    // active and arms an attempt whose body still sees the pre-reset value and
    // therefore demands seed_en_q be high. It fires on every software reset
    // whatever the DUT does.
    //
    // This holds the property off for the WHOLE RUN, not just that edge, so no
    // in-reset cycle is checked in any test. The seed_en_q flop in otbn_rnd.sv
    // covers the same contract: seed_en_q is asynchronously cleared by the same
    // rst_ni the property checks it against, which is what stops a reseed
    // request held high through reset from starting one mid-reset.
    initial begin
        $assertoff(0, `SEP_CORE.u_sep_crypto.u_sep_crypto_otbn_wrapper_s3c_scan
            .u_otbn.u_otbn_core.u_otbn_rnd.UrndNoReseedOnReset_A);
    end
`endif

    // TB-owned CPU lockstep stimulus/observation. Initialised: an undriven
    // lockstep_ctrl_i would reach the core as X under RV_LOCKSTEP_ENABLE.
    sep_pkg::sep_lockstep_ctrl_t   lockstep_ctrl_i = '0;
    sep_pkg::sep_lockstep_status_t lockstep_status_o;
    sep_lifecycle_ctrl_pkg::dbg_disable_t dbg_disable_w;
    assign dbg_disable_stap_io_o            = dbg_disable_w.stap_io;
    assign dbg_disable_stap_smc_o           = dbg_disable_w.stap_smc;
    assign dbg_disable_stap_sep_o           = dbg_disable_w.stap_sep;
    assign dbg_disable_stap_extra_o         = dbg_disable_w.stap_extra;
    assign dbg_disable_stap_host_o          = dbg_disable_w.stap_host;
    assign dbg_disable_dft_secure_o         = dbg_disable_w.dft_secure;
    assign dbg_disable_dft_nonsecure_o      = dbg_disable_w.dft_nonsecure;
    assign dbg_disable_dfd_o                = dbg_disable_w.dfd;
    assign dbg_disable_smc_jtag2axi_o       = dbg_disable_w.smc_jtag2axi;
    assign dbg_disable_smc_otp_jtag2axi_o   = dbg_disable_w.smc_otp_jtag2axi;
    assign dbg_disable_sep_otp_jtag2axi_o   = dbg_disable_w.sep_otp_jtag2axi;
    assign dbg_disable_all_o                = dbg_disable_w;

    // TB-owned JTAG pins. In +cpu_boot mode the TB shifts a reset-vector TDR
    // sequence (see init_reset_vector_tdr). They remain at the idle TAP-reset
    // values for no-CPU tests. TRST starts high and falls at 1 ps, so the TAP
    // and its reset-vector TDR see a reset edge on a four-state simulator;
    // otherwise the TDR, and the core reset PC it drives, stay X.
    logic jtag_tck   = 1'b0;
    logic jtag_tms   = 1'b0;
    logic jtag_tdi   = 1'b0;
    logic jtag_trst_n = 1'b1;
    initial begin : init_tap_trst
        #1ps;
        jtag_trst_n = 1'b0;
    end

    localparam logic [4:0] ResetVectorTdrIr = 5'h18;

    // Core TAP pin select (top-port drive, docs/SEP_TB_ARCH.adoc). With
    // jtag_bench_own_i = 1 the cocotb pins drive the TAP; otherwise the
    // registers above do, and every leaf that leaves the select at 0 sees the
    // TAP exactly as before.
    logic jtag_core_tck, jtag_core_tms, jtag_core_tdi, jtag_core_trst_n;
    assign jtag_core_tck    = (jtag_bench_own_i === 1'b1) ? jtag_tck_i    : jtag_tck;
    assign jtag_core_tms    = (jtag_bench_own_i === 1'b1) ? jtag_tms_i    : jtag_tms;
    assign jtag_core_tdi    = (jtag_bench_own_i === 1'b1) ? jtag_tdi_i    : jtag_tdi;
    assign jtag_core_trst_n = (jtag_bench_own_i === 1'b1) ? jtag_trst_n_i : jtag_trst_n;

    task automatic jtag_tb_clock(input logic tms, input logic tdi);
        jtag_tms = tms;
        jtag_tdi = tdi;
        #1ps;
        jtag_tck = 1'b1;
        #1ps;
        jtag_tck = 1'b0;
        #1ps;
    endtask

    task automatic program_reset_vector_tdr(input logic [31:0] vector);
        int bit_idx;

        if (vector[0] !== 1'b0) begin
            $fatal(1,
                   "[SEP OSS DV] Reset-vector TDR requires a halfword-aligned address: 0x%08x",
                   vector);
        end

        // Assert and release TRST, then explicitly enter Run-Test/Idle.
        jtag_trst_n = 1'b0;
        jtag_tck = 1'b0;
        #1ps;
        jtag_trst_n = 1'b1;
        repeat (5) jtag_tb_clock(1'b1, 1'b0);
        jtag_tb_clock(1'b0, 1'b0);

        // Select-IR-Scan and load RSTVEC (0x18), LSB first.
        jtag_tb_clock(1'b1, 1'b0); // Select-DR-Scan
        jtag_tb_clock(1'b1, 1'b0); // Select-IR-Scan
        jtag_tb_clock(1'b0, 1'b0); // Capture-IR
        jtag_tb_clock(1'b0, 1'b0); // Shift-IR
        for (bit_idx = 0; bit_idx < 5; bit_idx++) begin
            jtag_tb_clock(bit_idx == 4, ResetVectorTdrIr[bit_idx]);
        end
        jtag_tb_clock(1'b1, 1'b0); // Update-IR
        jtag_tb_clock(1'b0, 1'b0); // Run-Test/Idle

        // Select-DR-Scan and shift the reset vector, LSB first. RSTVEC stores
        // PC[31:1], so bit 0 is reserved and always shifts as zero.
        jtag_tb_clock(1'b1, 1'b0); // Select-DR-Scan
        jtag_tb_clock(1'b0, 1'b0); // Capture-DR
        jtag_tb_clock(1'b0, 1'b0); // Shift-DR
        for (bit_idx = 0; bit_idx < 32; bit_idx++) begin
            jtag_tb_clock(bit_idx == 31, bit_idx == 0 ? 1'b0 : vector[bit_idx]);
        end
        jtag_tb_clock(1'b1, 1'b0); // Update-DR
        jtag_tb_clock(1'b0, 1'b0); // Run-Test/Idle

        jtag_tms = 1'b0;
        jtag_tdi = 1'b0;
        $display("[SEP OSS DV] Reset-vector TDR programmed to 0x%08x", vector);
    endtask

    // The vendored VeeR tap has no reset-vector TDR, so this JTAG sequence
    // shifts into a nonexistent register and is inert. The reset vector reaches
    // the CPU through the wrapper's direct `rst_vec` input (connected from
    // rst_vec_i in the DUT instantiation below).
    // The one-shot runs while the primary reset is asserted, before the cocotb
    // CPU-boot flow releases reset. It polls on the clock edge rather than a
    // bare level `wait`: a cocotb (VPI)-driven rst_vec_i update does not
    // reliably re-trigger a `wait` under Verilator, so the one-shot could fire
    // late (after reset release). It fires exactly once on the first clock where
    // reset is asserted and rst_vec_i is a known non-zero entry (clocks start
    // while rst_ni is still low, so the window is always seen).
    initial begin : init_reset_vector_tdr
        if ($test$plusargs("cpu_boot")) begin
            forever begin
                @(posedge clk_i);
                if ((rst_ni === 1'b0) && !$isunknown(rst_vec_i) && (rst_vec_i !== '0)) begin
                    program_reset_vector_tdr({rst_vec_i, 1'b0});
                    break;
                end
            end
        end
    end

    // ------------------------------------------------------------------
    // SEP DUT = sep_wrapper (smn_inbound driven by the flat m_axi_* external
    // master). Real memory macros + generic efuse model are internal (no
    // mem/efuse responder buses). SPI leaves the wrapper as the sep_io_pkg
    // struct pair (sep_io_spi_req_o / sep_io_spi_rsp_i); the TB bridges it to
    // the scalar pad ports below. The reset vector is a direct rst_vec input
    // (the vendored VeeR tap has no reset-vector TDR).
    // ------------------------------------------------------------------
    sep_io_pkg::sep_io_spi_req_t sep_io_spi_req_w;
    bit         spi_four_lane_q;
    logic [3:0] spi_rsp_sd_w;
    // The irq field of the SPI request, selected by name, so a leaf that
    // samples it does not depend on the struct layout.
    logic sep_io_spi_irq_w;
    assign sep_io_spi_irq_w = sep_io_spi_req_w.irq;
    // EXT_TRNG_NUM_AXIS must equal sep_crypto_pkg::SepCryptoEdnEndpointCount (3):
    // sep_crypto.u_sep_trng binds u_drbg_s3c_scan.edn_axis_o/i to drbg_int_axis_req/rsp as a
    // DIRECT packed-array connection, one mux leg per DRBG EDN endpoint
    // ([0]=Key Manager, [1]=crypto adapter, [2]=entropy pool). Width 2 truncates
    // that bind; sep_crypto.sv's g_drbg_endpoint_mux_width_check catches it under
    // simulators that evaluate elaboration-time $error (VCS). Verilator skips
    // that check, so the width must stay correct here.
    //
    // The third leg is NOT free. sep_entropy_fifo drives edn_req from the first
    // post-reset cycle, so once endpoint [2] is connected the DRBG grants it real
    // genbits blocks and a single seed serves several Generate commands. That is
    // why the CHK4 golden is demand-driven (sep_entropy_golden.genbits_block() /
    // genbits_gen_last()): a fixed glen-blocks-per-seed model desynchronises at
    // the first extra Generate. Truncating to 2 endpoints leaves the third leg's
    // inputs X-driven.
    //
    // SEP_SEC_DISABLE_TOKEN is the metal expected digest, not an AXI register.
    // Product RTL defaults it to 0, which no SHA-256 output matches. Bind the
    // SHA-256 of the all-zero 32-byte token so a frontdoor write of zeros can
    // take the match. This is the TB stand-in for the metal ECO; it does not
    // force security_disable.
    localparam bit [255:0] SecDisTbDigest =
        256'h66687aad_f862bd77_6c8fc18b_8e9f8e20_08971485_6ee233b3_902a591d_0d5f2925;
    // Read-only copy of the bound digest: a localparam has no simulator handle on
    // every tool, a net does. CHK-BIND reads it.
    wire [255:0] sec_dis_digest_probe_o;
    assign sec_dis_digest_probe_o = SecDisTbDigest;
    // SMC fuse-sense completion. No SMC RTL is instantiated in this top, so the TB
    // stands in for what the SoC provides: the SMC finishes sensing its eFuse array
    // after reset and holds the indication high afterwards. Cold reset re-senses;
    // wdt_rst_ni does not, which is why this tracks rst_n_int and not the warm reset.
    //
    // The ROM polls this to completion in [S08] before reading any fuse shadow, so a
    // top that never asserts it hangs every boot. The same invariant is checked from
    // the firmware side as CHK-SEP-HOLD-RELEASE
    // (dv/fw/tests/common/smc_sep_xbar_protocol.h). +sep_smc_fuse_sense_hold keeps it
    // low, which is the stimulus for proving the ROM refuses to advance without it.
    // No declaration initializers: VCS rejects a variable that has both an
    // initializer and a procedural driver (ICPD_INIT). Each of these has exactly
    // one driver, the block that follows it.
    localparam int SmcFuseSenseCycles = 64;
    logic smc_fuse_sense_hold;
    logic smc_fuse_sense_done_model;
    int   smc_fuse_sense_count;
    initial begin
        smc_fuse_sense_hold = $test$plusargs("sep_smc_fuse_sense_hold");
        if (smc_fuse_sense_hold) begin
            $display("[tb] smc_fuse_sense_done held low (+sep_smc_fuse_sense_hold)");
        end
    end
    always_ff @(posedge clk_i or negedge rst_n_int) begin
        if (!rst_n_int) begin
            smc_fuse_sense_count      <= 0;
            smc_fuse_sense_done_model <= 1'b0;
        end else if (smc_fuse_sense_hold) begin
            smc_fuse_sense_done_model <= 1'b0;
        end else if (smc_fuse_sense_count < SmcFuseSenseCycles) begin
            smc_fuse_sense_count <= smc_fuse_sense_count + 1;
        end else begin
            smc_fuse_sense_done_model <= 1'b1;
        end
    end

    // JTAG ID (docs/SEP_TB_ARCH.adoc, HDL Top port table): the TB input
    // jtag_id_i drives the sep_wrapper input jtag_id. An undriven (Verilator 0,
    // VCS z) or unknown value drives 0, so a leaf that does not drive it keeps
    // the ID at 0.
    logic [31:1] jtag_id_drive;
    assign jtag_id_drive = $isunknown(jtag_id_i) ? 31'h0 : jtag_id_i;

    sep_wrapper #(
        .EXT_TRNG_NUM_AXIS     (3),
        .SEP_SEC_DISABLE_TOKEN (SecDisTbDigest)
    ) u_dut (
        // Clocks / resets
        .clk_i                        (clk_i),
        .clk_wdt_i                    (clk_wdt_i),
        .rst_ni                       (rst_n_int),
        .dbg_rstb_i                   (dbg_rstb_i),
        .wdt_rst_ni                   (wdt_rst_ni_i),
        .entropy_rosc_sample_clk_i    (entropy_rosc_sample_clk_i),
        .clk_ref_i                    (clk_ref_i),
        .wdt_timer_rst_req_o          (wdt_timer_rst_req_o),

        // JTAG: the tb_top registers (driven only by the +cpu_boot reset-vector
        // TDR setup) unless a leaf takes the pins with jtag_bench_own_i.
        .jtag_tck_i                   (jtag_core_tck),
        .jtag_tms_i                   (jtag_core_tms),
        .jtag_tdi_i                   (jtag_core_tdi),
        .jtag_trst_ni                 (jtag_core_trst_n),
        .jtag_tdo_o                   (jtag_tdo_o),
        .jtag_tdoEn_o                 (),
        .jtag_sep_reset_ctrl_i        (jtag_sep_reset_ctrl_drive),

`ifdef SEP_JTAG_AXIL_LIVE
        .axil_sep_otp_jtag_req_i      (j_axil_req_drive),
`else
        .axil_sep_otp_jtag_req_i      ('0),
`endif
        .axil_sep_otp_jtag_resp_o     (j_axil_resp_w),

        // MPC halt/run + CPU run (CPU held off; LSU master driven by the stub)
        .mpc_debug_halt_req_i         (1'b0),
        .mpc_debug_run_req_i          (1'b0),
        .mpc_reset_run_req_i          (mpc_reset_run_req),
        .cpu_halt_req_i               (1'b0),
        .cpu_run_req_i                (i_cpu_run_req_i),

        // DFT pins: functional mode (0 and 1) unless a leaf drives them.
        .test_en_i                    (test_en_i === 1'b1),
        .scan_rst_ni                  (scan_rst_ni_i !== 1'b0),
        .ext_boot_seq_done_i          (ext_boot_seq_done_i),

        // DMI enables: 0 unless a leaf drives them. Uncore read data held at 0.
        .dmi_core_enable              (dmi_core_enable_i === 1'b1),
        .dmi_uncore_enable            (dmi_uncore_enable_i === 1'b1),
        .dmi_uncore_en                (dmi_uncore_en_o),
        .dmi_uncore_wr_en             (dmi_uncore_wr_en_o),
        .dmi_uncore_addr              (),
        .dmi_uncore_wdata             (),
        .dmi_uncore_rdata             ('0),
        .dmi_active                   (),

        .sep_cpu_trace                (cpu_trace_w),
        // Direct reset-vector input.
        .rst_vec                      (rst_vec_i),
        .jtag_id                      (jtag_id_drive),

        // Interrupts. timer_int and soft_int are tied to 0. The boundary PIC
        // input is the top-port drive sep_ext_interrupts_i (0 unless a leaf
        // drives it).
        .timer_int                    (1'b0),
        .soft_int                     (1'b0),
        .sep_ext_interrupts_i         (sep_ext_interrupts_i),

        // SMN external AXI (outbound captured by the mailbox responder; inbound
        // driven by the flat m_axi_* master when live).
        .smn_outbound_axi_req_o       (smn_outbound_req_w),
        .smn_outbound_axi_resp_i      (smn_outbound_resp_w),
`ifdef SEP_SMN_INBOUND_AXI_LIVE
        .smn_inbound_axi_req_i        (smn_inbound_req_drive),
`else
        .smn_inbound_axi_req_i        ('0),
`endif
        .smn_inbound_axi_resp_o       (smn_inbound_resp_w),
        .sep_ext_to_smc_axi_req_o     (ext_to_smc_req_w),
        .sep_ext_to_smc_axi_resp_i    (ext_to_smc_resp_w),

        // LC demote. Real DUT outputs, brought out so a ROM boot test can observe
        // what BL0 actually wrote rather than what it said it wrote.
        .lcc_demote_state_1_o         (lcc_demote_state_1_probe_o),
        .lcc_demote_state_2_o         (lcc_demote_state_2_probe_o),

        // SPI: quad-lane struct boundary, bridged below to the pad ports
        // (sck/cs_n from req; MOSI = sd[0] out; MISO returns on rsp.sd[1];
        // spi_sd_o/spi_sd_oe_o and spi_sd_i carry all four lanes).
        .sep_io_spi_req_o             (sep_io_spi_req_w),
        .sep_io_spi_rsp_i             ('{sd: spi_rsp_sd_w}),

        // Wrapper status/debug outputs. Unconnected ports have no consumer
        // in this TB; the rest are real DUT outputs brought to tb ports.
        .lc_state_o                   (),
        .dbg_disable_o                (dbg_disable_w),
        .sep_fuse_dft_disable_o       (sep_fuse_dft_disable_o),
        .smc_fuse_dft_disable_o       (smc_fuse_dft_disable_o),
        .lc_sigint_err_o              (lcc_sigint_err_probe_o),
        .security_disable_o           (lcc_security_disable_probe_o),
        .secure_tm_o                  (secure_tm_o),
        .km_unrecoverable_err_o       (),
        .km_recoverable_err_o         (),
        .efuse_debug_bus_o            (efuse_debug_bus_o),

        // Mailbox interrupts
        .smc_mailbox_interrupt_o      (smc_mailbox_interrupt_o),

        // eFuse status
        .smc_fuse_sense_done_i        (smc_fuse_sense_done_model),
        .sep_fuse_sense_done_o        (sep_fuse_sense_done_o),

        .secure_tm_req_i              (test_en_strap_i),

        // SMC address configuration tied to 0 (identity remap).
`ifdef SEP_SMC_MEM_MODEL
        // Route the SMC region (scratch 0x4003_9080+, straps 0x4040_3000, SMC SRAM
        // 0x4006_0000+ manifest) out the sep_ext_to_smc AXI to the TB's SMC
        // responder. The ROM boots secondary (non-SPI) and DMAs the manifest+BL1
        // from SMC SRAM.
        .smc_global_base_addr_i       (56'h4000_0000),
        .smc_region_size_i            (56'h0100_0000),
`else
        .smc_global_base_addr_i       (bh_smc_base),
        .smc_region_size_i            (bh_smc_size),
`endif
        .sep_global_base_addr_o       (),
        .sep_region_size_o            (),

        // External debug bus
        .ext_debug_bus_o              (ext_debug_bus_o),

        // CPU lockstep control/status
        .lockstep_ctrl_i              (lockstep_ctrl_i),
        .lockstep_status_o            (lockstep_status_o)
    );
    // Scalar SPI pad bridge from the wrapper struct port.
    assign spi_sck_o  = sep_io_spi_req_w.sck;
    assign spi_cs_n_o = sep_io_spi_req_w.cs_n;
    assign spi_mosi_o = sep_io_spi_req_w.sd[0];
    assign spi_sd_o     = sep_io_spi_req_w.sd;
    assign spi_sd_oe_o  = sep_io_spi_req_w.sd_oe;
    assign spi_cs_oe_o  = sep_io_spi_req_w.cs_oe;
    assign spi_sck_oe_o = sep_io_spi_req_w.sck_oe;
    // Response lanes: in a run with +sep_spi_four_lane all four lanes follow
    // spi_sd_i; otherwise lane 1 is spi_miso_i and lanes 0, 2 and 3 read 0.
    // spi_sd_rsp_o is a monitor-only copy of the lanes the DUT receives.
    initial spi_four_lane_q = $test$plusargs("sep_spi_four_lane");
    assign spi_rsp_sd_w = spi_four_lane_q ? spi_sd_i : {2'b00, spi_miso_i, 1'b0};
    assign spi_sd_rsp_o = spi_rsp_sd_w;

    // ------------------------------------------------------------------
    // SEP->SMC external AXI responder (real-ROM boot only).
    // The Boot ROM accesses the SMC scratch registers (0x4003_9080+) and SMC
    // SRAM (0x4006_0000, manifest+BL1) over sep_ext_to_smc_axi. The shared AXI
    // slave agent answers on u_smc_axi_if; the bridge places the wrapper's
    // struct port on it. The agent's memory gives those addresses real R/W, so
    // the ROM's scratch round-trip passes and its non-SPI manifest fetch
    // works. Preload (scratch, status, straps, the +sep_smc_mem_hex image) and
    // fault programming go through the agent's slave sequence
    // (cocotb/env/sep_smc_mem.py).
    // ------------------------------------------------------------------
`ifdef SEP_SMC_MEM_MODEL
    ocah_axi_if u_smc_axi_if (
        .aclk    (clk_i),
        .aresetn (rst_n_int)
    );

    ocah_axi_struct_bridge #(
        .axi_req_t  (sep_pkg::sep_system_peripherals_internal_axi_req_t),
        .axi_resp_t (sep_pkg::sep_system_peripherals_internal_axi_resp_t)
    ) u_smc_bridge (
        .axi_req_i  (ext_to_smc_req_w),
        .axi_resp_o (ext_to_smc_resp_w),
        .axi_if     (u_smc_axi_if)
    );

    // ------------------------------------------------------------------
    // SMC address decode check.
    //
    // The SMC responder is a flat memory: it answers at whatever address the
    // ROM presents, so a wrong SEP<->SMC offset is invisible to the boot flow
    // -- the testbench seeds the wrong address too and every test stays
    // green. This checker supplies the one property a flat memory lacks: an
    // access outside a register window that exists is an ERROR. Block bases
    // and sizes come from the generated SMC address map (smc_top_addrmap_pkg,
    // hw/sys/smc/regs/gen/sv/smc_addrmap_pkg.sv). The package gives SMC-local
    // addresses (0xC000_XXXX); SEP sees them at 0x4000_XXXX, the identity
    // mapping this tb configures via smc_global_base_addr_i. When the ROM needs
    // a new block, add its generated base/size here rather than widening an
    // existing window.
    localparam logic [63:0] SmcLocalBase = 64'hC000_0000;
    localparam logic [63:0] SmcSepViewBase = 64'h4000_0000;
    localparam logic [55:0] SmcStrapsLoAddr = 56'(
        smc_top_addrmap_pkg::SMC_TOP_SMC_EXTERNAL_MANDATORY_STRAPS_BASE_ADDR - SmcLocalBase +
        SmcSepViewBase);
    localparam logic [55:0] SmcStrapsHiAddr = SmcStrapsLoAddr + 4;
    localparam int unsigned SmcNumWindows = 7;
    // {base, size} pairs, SEP-side addresses.
    localparam logic [55:0] SmcWinBase [SmcNumWindows] = '{
        56'(smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_BASE_ADDR - SmcLocalBase + SmcSepViewBase),
        // SMC_MISC_WRAP_CHIP_CONFIG: CHIP_ID, LC_STATE
        56'(smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR - SmcLocalBase +
            SmcSepViewBase),
        // SMC_EFUSE_MAP: chiplet/package ID
        56'(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR - SmcLocalBase + SmcSepViewBase),
        // DFX_CTRL: STATUS_SMU
        56'(smc_top_addrmap_pkg::SMC_TOP_DFX_CTRL_BASE_ADDR - SmcLocalBase + SmcSepViewBase),
        // SMC_CPU_CTRL: scratch[0..15] at +0x80
        56'(smc_top_addrmap_pkg::SMC_TOP_SMC_CPU_CTRL_BASE_ADDR - SmcLocalBase + SmcSepViewBase),
        // SPM_MEMORY: manifest + BL1
        56'(smc_top_addrmap_pkg::SMC_TOP_SPM_MEMORY_BASE_ADDR - SmcLocalBase + SmcSepViewBase),
        SmcStrapsLoAddr  // SMC_EXTERNAL straps (STRAPS_LO/HI)
    };
    localparam logic [55:0] SmcWinSize [SmcNumWindows] = '{
        56'(smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_SIZE),
        56'(smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_SIZE),
        56'(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_SIZE),
        56'(smc_top_addrmap_pkg::SMC_TOP_DFX_CTRL_SIZE),
        56'(smc_top_addrmap_pkg::SMC_TOP_SMC_CPU_CTRL_SIZE),
        56'(smc_top_addrmap_pkg::SMC_TOP_SPM_MEMORY_SIZE),
        56'(smc_top_addrmap_pkg::SMC_TOP_SMC_EXTERNAL_MANDATORY_STRAPS_SIZE)
    };

    // Counted as well as reported: a cocotb test can require this to be 0, so the
    // check cannot be silently lost if $error severity is ever downgraded.
    int unsigned smc_addr_violations;
    assign smc_addr_violations_o = smc_addr_violations;

    function automatic bit smc_addr_mapped(input logic [55:0] a);
        smc_addr_mapped = 1'b0;
        for (int unsigned w = 0; w < SmcNumWindows; w++) begin
            if (a >= SmcWinBase[w] && a < (SmcWinBase[w] + SmcWinSize[w])) begin
                smc_addr_mapped = 1'b1;
            end
        end
    endfunction

    logic smc_aw_violation;
    logic smc_ar_violation;
    assign smc_aw_violation =
        ext_to_smc_req_w.aw_valid && ext_to_smc_resp_w.aw_ready &&
        !smc_addr_mapped(ext_to_smc_req_w.aw.addr);
    assign smc_ar_violation =
        ext_to_smc_req_w.ar_valid && ext_to_smc_resp_w.ar_ready &&
        !smc_addr_mapped(ext_to_smc_req_w.ar.addr);

    always @(posedge clk_i) begin
        if (!rst_ni) begin
            smc_addr_violations <= 0;
        end else begin
            smc_addr_violations <=
                smc_addr_violations + smc_aw_violation + smc_ar_violation;
            if (smc_aw_violation) begin
                $error("[tb] SMC ADDRESS DECODE: write to 0x%0h is outside every SMC register window tb_top maps from smc_top_addrmap_pkg -- the ROM is using an offset this design does not implement",
                       ext_to_smc_req_w.aw.addr);
            end
            if (smc_ar_violation) begin
                $error("[tb] SMC ADDRESS DECODE: read from 0x%0h is outside every SMC register window tb_top maps from smc_top_addrmap_pkg -- the ROM is using an offset this design does not implement",
                       ext_to_smc_req_w.ar.addr);
            end
        end
    end

`else
    // BH-SMC responder. Idle while the hook is off, so the port reads as the
    // tied-off SMC of the default bench. The SMC decode check above belongs to
    // the real-ROM boot target and is not compiled here, so the BH-SMC
    // aperture needs no window of its own.
    sep_smc_route_mem #(
        .axi_req_t  (sep_pkg::sep_system_peripherals_internal_axi_req_t),
        .axi_resp_t (sep_pkg::sep_system_peripherals_internal_axi_resp_t)
    ) u_smc_route_mem (
        .clk_i  (clk_i),
        .rst_ni (rst_n_int),
        .en_i   (bh_smc_en),
        .req_i  (ext_to_smc_req_w),
        .resp_o (ext_to_smc_resp_w)
    );
    // No SMC model, so no SEP->SMC traffic to decode. 0 rather than X: a test
    // asserting "no address violations" must not pass on an undriven port, and
    // must not fail on a build that never had an SMC to address.
    assign smc_addr_violations_o = '0;
`endif

    // ------------------------------------------------------------------
    // tb_backdoor_mem: default-fill + image load for the real memory macros.
    //
    // The wrapper's macros have no runtime init (MemInitFile("")) and power up X
    // on VCS / 0 on Verilator -- both wrong for KM (parity) and OTBN (SECDED),
    // whose valid power-up word is non-zero. Fill patterns include ECC/parity.
    // Array paths are hw/top/sep_ip_integration.sv and sep_tcm_wrapper
    // (TCM per-depth generate arms: gen_ram).
    // Backdoor writes into these DUT arrays need them public under Verilator
    // (sep_public_scope.vlt: prim_ram_1p.mem, prim_rom.mem, ram_16384x39.ram_core).
    // ------------------------------------------------------------------
    // RISC-V SECDED (Hsiao) ECC over a 32-bit word (EL2 TCM encoding).
    function automatic logic [6:0] bd_riscv_ecc32(input logic [31:0] data);
        logic [6:0] synd;
        synd[0] = ^(data & 32'h56aa_ad5b);
        synd[1] = ^(data & 32'h9b33_366d);
        synd[2] = ^(data & 32'he3c3_c78e);
        synd[3] = ^(data & 32'h03fc_07f0);
        synd[4] = ^(data & 32'h03ff_f800);
        synd[5] = ^(data & 32'hfc00_0000);
        synd[6] = ^{data, synd[5:0]};
        return synd;
    endfunction
    // KM per-word odd parity nibble (one bit per byte, inverted XOR reduction).
    function automatic logic [3:0] bd_km_word_parity(input logic [31:0] w);
        for (int unsigned i = 0; i < 4; i++) bd_km_word_parity[i] = ~^w[8*i +: 8];
    endfunction

    localparam logic [38:0] BdOtbnZero = prim_secded_pkg::SecdedInv3932ZeroWord;

`define BD_ICCM(b) `SEP_IPI.u_sep_tcm_wrapper.gen_iccm.gen_bank[b].gen_iccm_ram.u_ram.ram_core
`define BD_DCCM(b) `SEP_IPI.u_sep_tcm_wrapper.gen_dccm.gen_bank[b].gen_dccm_ram.u_ram.ram_core

    // Non-zero valid power-up patterns (both tools: Verilator 0-init and VCS X are
    // both invalid here -> spurious KM SRAM_PARITY / OTBN SECDED faults otherwise).
    initial begin : backdoor_default_fill_nonzero
        for (int i = 0; i < 4096; i++)
            `SEP_IPI.u_km_rom.mem[i] = {bd_km_word_parity(32'h0000_0013), 32'h0000_0013};
        for (int i = 0; i < 8192; i++)
            `SEP_IPI.u_km_sram.gen_ram_inst[0].u_mem.mem[i] = {4'hF, 32'h0};
        for (int i = 0; i < 4096; i++)
            `SEP_IPI.u_otbn_imem_sram.mem[i] = BdOtbnZero;
        for (int i = 0; i < 1024; i++)
            `SEP_IPI.u_otbn_dmem_sram.mem[i] = {8{BdOtbnZero}};
    end

`ifndef VERILATOR
    // Zero-default macros power up X on VCS; zero them. Verilator 0-inits these, so
    // the sweep is compiled only for VCS (a constant-bound Verilator `initial`
    // sweep over ~100k rows unrolls into an uncompilable C++ function).
    initial begin : backdoor_default_fill_zero
        for (int i = 0; i < 32768; i++)
            `SEP_IPI.u_sep_sram.gen_ram_inst[0].u_mem.mem[i] = 64'h0;
        for (
            int i = 0;
            i < sep_top_addrmap_pkg::SEP_TOP_SEP_BOOT_ROM_SIZE / 8;
            i++
        )
            `SEP_IPI.u_sep_boot_rom.mem[i] = 64'h0;
        for (int r = 0; r < 16384; r++) begin
            `BD_ICCM(0)[r] = 39'h0; `BD_ICCM(1)[r] = 39'h0;
            `BD_ICCM(2)[r] = 39'h0; `BD_ICCM(3)[r] = 39'h0;
            `BD_DCCM(0)[r] = 39'h0; `BD_DCCM(1)[r] = 39'h0;
        end
    end
`endif

    // Every file-path plusarg this bench and its models consume; a present one
    // whose file cannot be opened ends the run at time 0.
    `include "ocah_path_plusargs.svh"
    initial begin : path_plusarg_guard
        static string names[] = '{
            "sep_boot_rom_hex", "sep_sram_hex", "km_rom_hex", "sep_efuse_hex",
            "sep_efuse_shadow_hex", "sep_shadow_reg_preload", "sep_smc_mem_hex"
        };
        ocah_require_file_plusargs(names);
    end

    // Image loads into the ROM/SRAM macros at t=0. Honor the plusarg first, else
    // the CWD default filename (tests that stage a committed hex into the sim
    // CWD without a plusarg still get it -- e.g. sep_boot_rom_smoke_test relies
    // on the default sep_boot_rom.hex). A missing default file leaves the
    // default fill intact.
    // A named `+km_rom_hex` file must exist: $readmemh of an absent path leaves
    // the KM ROM empty and the firmware never posts ready.
    initial begin : backdoor_image_loads
        string img;
        int    fd;
        #0;  // let the default-fill initials settle first
        if ($value$plusargs("sep_boot_rom_hex=%s", img)) begin
            $readmemh(img, `SEP_IPI.u_sep_boot_rom.mem);
            $display("[tb_backdoor_mem] boot ROM image loaded (%0s)", img);
        end else begin
            fd = $fopen("sep_boot_rom.hex", "r");
            if (fd != 0) begin
                $fclose(fd);
                $readmemh("sep_boot_rom.hex", `SEP_IPI.u_sep_boot_rom.mem);
                $display("[tb_backdoor_mem] boot ROM image loaded (sep_boot_rom.hex)");
            end
        end
        if ($value$plusargs("sep_sram_hex=%s", img)) begin
            $readmemh(img, `SEP_IPI.u_sep_sram.gen_ram_inst[0].u_mem.mem);
        end else begin
            fd = $fopen("sep_sram.hex", "r");
            if (fd != 0) begin
                $fclose(fd);
                $readmemh("sep_sram.hex", `SEP_IPI.u_sep_sram.gen_ram_inst[0].u_mem.mem);
            end
        end
        if ($value$plusargs("km_rom_hex=%s", img)) begin
            fd = $fopen(img, "r");
            if (fd == 0) begin
                $fatal(1, "[tb_backdoor_mem] +km_rom_hex=%s is not readable", img);
            end
            $fclose(fd);
            $readmemh(img, `SEP_IPI.u_km_rom.mem);
            $display("[tb_backdoor_mem] KM ROM image loaded (%0s)", img);
        end else begin
            fd = $fopen("km_rom.parhex", "r");
            if (fd != 0) begin
                $fclose(fd);
                $readmemh("km_rom.parhex", `SEP_IPI.u_km_rom.mem);
            end
        end
    end

    // TCM bit-flip (error inject, docs/SEP_TB_ARCH.adoc): XOR `mask` into the
    // stored 39-bit word (bits 31:0 data, 38:32 ECC) that holds byte address
    // `addr`, with the bank and row map of the image load below (ICCM at
    // 0xC000_0000, bank off[3:2], row off[17:4]; DCCM at 0xC004_0000, bank
    // off[2], row off[16:3]). An address outside both ends the run.
    localparam logic [31:0] BdIccmBase = 32'hC000_0000;
    localparam logic [31:0] BdDccmBase = 32'hC004_0000;
    task automatic bd_tcm_flip(input logic [31:0] addr, input logic [38:0] mask);
        logic [31:0] off;
        if (addr >= BdIccmBase && addr < BdIccmBase + 32'h0004_0000) begin
            off = addr - BdIccmBase;
            case (off[3:2])
                2'd0: `BD_ICCM(0)[off[17:4]] = `BD_ICCM(0)[off[17:4]] ^ mask;
                2'd1: `BD_ICCM(1)[off[17:4]] = `BD_ICCM(1)[off[17:4]] ^ mask;
                2'd2: `BD_ICCM(2)[off[17:4]] = `BD_ICCM(2)[off[17:4]] ^ mask;
                2'd3: `BD_ICCM(3)[off[17:4]] = `BD_ICCM(3)[off[17:4]] ^ mask;
            endcase
        end else if (addr >= BdDccmBase && addr < BdDccmBase + 32'h0002_0000) begin
            off = addr - BdDccmBase;
            if (off[2]) `BD_DCCM(1)[off[16:3]] = `BD_DCCM(1)[off[16:3]] ^ mask;
            else        `BD_DCCM(0)[off[16:3]] = `BD_DCCM(0)[off[16:3]] ^ mask;
        end else begin
            $fatal(1, "[tb] TCM bit-flip address 0x%08x is outside ICCM and DCCM", addr);
        end
        $display("[tb] TCM bit-flip addr=0x%08x mask=0x%010x", addr, mask);
    endtask

    // Runtime TCM bit-flip on a rising edge of tcm_flip_i.
    always @(posedge tcm_flip_i) begin : tcm_flip_hook
        bd_tcm_flip(tcm_flip_addr_i, tcm_flip_mask_i);
    end

    // Runtime boot ROM bit-flip on a rising edge of rom_flip_i: XOR
    // rom_flip_mask_i into the stored 64-bit word rom_flip_index_i.
    always @(posedge rom_flip_i) begin : rom_flip_hook
        `SEP_IPI.u_sep_boot_rom.mem[rom_flip_index_i] =
            `SEP_IPI.u_sep_boot_rom.mem[rom_flip_index_i] ^ rom_flip_mask_i;
        $display("[tb] ROM bit-flip word=%0d mask=0x%016x", rom_flip_index_i, rom_flip_mask_i);
    end

    // TCM (ICCM/DCCM) firmware backdoor-load on tcm_load_i, de-interleaved into the
    // EL2 bank/row layout with per-word Hsiao ECC (ICCM bank=off[3:2] row=off[17:4],
    // DCCM bank=off[2] row=off[16:3]); byte buffers pre-zeroed so every row is
    // written (imaged or ECC-valid 0). Constant bank indices keep the XMR legal.
    logic [7:0] bd_itcm_buf [262144];
    logic [7:0] bd_dtcm_buf [131072];
    string        iccm_poke_arg;
    logic [31:0]  iccm_poke_addr, iccm_poke_data;
    logic [38:0]  iccm_poke_word;
    int           iccm_poke_off;
    string        tcm_flip_list;
    int           tcm_flip_fd;
    logic [31:0]  tcm_flip_list_addr;
    logic [38:0]  tcm_flip_list_mask;
    always @(posedge tcm_load_i) begin : backdoor_tcm_load
        int off;
        logic [31:0] w;
        logic [38:0] fw;
        for (int i = 0; i < 262144; i++) bd_itcm_buf[i] = 8'h00;
        $readmemh("sep_itcm.hex", bd_itcm_buf);
        for (off = 0; off + 3 < 262144; off += 4) begin
            w  = {bd_itcm_buf[off+3], bd_itcm_buf[off+2], bd_itcm_buf[off+1], bd_itcm_buf[off]};
            fw = (w == 32'h0) ? '0 : {bd_riscv_ecc32(w), w};
            case (off[3:2])
                2'd0: `BD_ICCM(0)[off[17:4]] = fw;
                2'd1: `BD_ICCM(1)[off[17:4]] = fw;
                2'd2: `BD_ICCM(2)[off[17:4]] = fw;
                2'd3: `BD_ICCM(3)[off[17:4]] = fw;
            endcase
        end
        for (int i = 0; i < 131072; i++) bd_dtcm_buf[i] = 8'h00;
        $readmemh("sep_dtcm.hex", bd_dtcm_buf);
        for (off = 0; off + 3 < 131072; off += 4) begin
            w  = {bd_dtcm_buf[off+3], bd_dtcm_buf[off+2], bd_dtcm_buf[off+1], bd_dtcm_buf[off]};
            fw = (w == 32'h0) ? '0 : {bd_riscv_ecc32(w), w};
            if (off[2]) `BD_DCCM(1)[off[16:3]] = fw;
            else        `BD_DCCM(0)[off[16:3]] = fw;
        end
        $display("[tb_backdoor_mem] TCM image loaded (sep_itcm.hex / sep_dtcm.hex)");

        // ICCM single-word poke: +sep_iccm_word=<hexaddr>:<hexdata>
        // The poke follows the bulk load in this block because that load rewrites
        // the entire ICCM. The warm-handler test places an instruction at the
        // seeded address and observes the PC there. The poke uses the TCM's Hsiao
        // SECDED encoding and bank interleave so the core fetches a valid word.
        if ($value$plusargs("sep_iccm_word=%s", iccm_poke_arg)) begin
            if ($sscanf(iccm_poke_arg, "%h:%h", iccm_poke_addr, iccm_poke_data) != 2) begin
                $fatal(1, "[tb] +sep_iccm_word must be <hexaddr>:<hexdata>, got '%s'",
                       iccm_poke_arg);
            end
            iccm_poke_off = int'(iccm_poke_addr - 32'hC000_0000);
            if (iccm_poke_off < 0 || iccm_poke_off + 3 >= 262144) begin
                $fatal(1, "[tb] +sep_iccm_word address 0x%08x is outside ICCM [0xC0000000,0xC0040000)",
                       iccm_poke_addr);
            end
            iccm_poke_word = {bd_riscv_ecc32(iccm_poke_data), iccm_poke_data};
            case (iccm_poke_off[3:2])
                2'd0: `BD_ICCM(0)[iccm_poke_off[17:4]] = iccm_poke_word;
                2'd1: `BD_ICCM(1)[iccm_poke_off[17:4]] = iccm_poke_word;
                2'd2: `BD_ICCM(2)[iccm_poke_off[17:4]] = iccm_poke_word;
                2'd3: `BD_ICCM(3)[iccm_poke_off[17:4]] = iccm_poke_word;
            endcase
            $display("[tb] ICCM[0x%08x] = 0x%08x with ECC, AFTER the bulk load (+sep_iccm_word)",
                     iccm_poke_addr, iccm_poke_data);
        end

        // Time-0 TCM flip list: +sep_tcm_flip_list=<file>, one flip per line as
        // "<hex byte address> <hex 39-bit mask>". Applied after the load and the
        // poke above, so the flips land on the loaded words. The leaf writes the
        // file before it raises tcm_load_i, so the file is checked here and not
        // at time 0.
        if ($value$plusargs("sep_tcm_flip_list=%s", tcm_flip_list)) begin
            tcm_flip_fd = $fopen(tcm_flip_list, "r");
            if (tcm_flip_fd == 0) begin
                $fatal(1, "[tb] +sep_tcm_flip_list=%s is not readable", tcm_flip_list);
            end
            while ($fscanf(tcm_flip_fd, "%h %h\n", tcm_flip_list_addr,
                           tcm_flip_list_mask) == 2) begin
                bd_tcm_flip(tcm_flip_list_addr, tcm_flip_list_mask);
            end
            $fclose(tcm_flip_fd);
        end
    end
`undef BD_ICCM
`undef BD_DCCM

    // ------------------------------------------------------------------
    // CPU-LSU AXI splice.
    //
    // Inject: assemble the LSU req struct from the flat cocotb master inputs into
    // `lsu_req_drive` (always_comb). The sep_cpu stub reads this by upward
    // reference and drives its lsu_axi_req from it (single driver, plain assign,
    // no force -- see shims/cpu/sep_cpu_stub.sv). Whole-signal only; no per-field
    // drive. The no_cpu build replaces the core with a stub, so the bus is
    // single-driven and driven rather than forced.
    // ------------------------------------------------------------------
    sep_32_64_3_12_axi_req_t lsu_req_drive;

    always_comb begin
        lsu_req_drive            = '{default: '0};  // zeros atop and any unused fields
        lsu_req_drive.aw.id      = s_axi_awid;
        lsu_req_drive.aw.addr    = s_axi_awaddr;
        lsu_req_drive.aw.len     = s_axi_awlen;
        lsu_req_drive.aw.size    = s_axi_awsize;
        lsu_req_drive.aw.burst   = s_axi_awburst;
        lsu_req_drive.aw.lock    = s_axi_awlock;
        lsu_req_drive.aw.cache   = s_axi_awcache;
        lsu_req_drive.aw.prot    = s_axi_awprot;
        lsu_req_drive.aw.qos     = s_axi_awqos;
        lsu_req_drive.aw.region  = s_axi_awregion;
        lsu_req_drive.aw.user    = s_axi_awuser;
        // X-harden the handshakes: the drive is active from time 0, before cocotb
        // drives s_axi_*. Assert valid/ready only on a clean 1 so a 4-state sim
        // sees an idle (not X) LSU bus during bring-up instead of an unknown txn.
        lsu_req_drive.aw_valid   = (s_axi_awvalid === 1'b1);
        lsu_req_drive.w.data     = s_axi_wdata;
        lsu_req_drive.w.strb     = s_axi_wstrb;
        lsu_req_drive.w.last     = s_axi_wlast;
        lsu_req_drive.w.user     = s_axi_wuser;
        lsu_req_drive.w_valid    = (s_axi_wvalid === 1'b1);
        lsu_req_drive.b_ready    = (s_axi_bready === 1'b1);
        lsu_req_drive.ar.id      = s_axi_arid;
        lsu_req_drive.ar.addr    = s_axi_araddr;
        lsu_req_drive.ar.len     = s_axi_arlen;
        lsu_req_drive.ar.size    = s_axi_arsize;
        lsu_req_drive.ar.burst   = s_axi_arburst;
        lsu_req_drive.ar.lock    = s_axi_arlock;
        lsu_req_drive.ar.cache   = s_axi_arcache;
        lsu_req_drive.ar.prot    = s_axi_arprot;
        lsu_req_drive.ar.qos     = s_axi_arqos;
        lsu_req_drive.ar.region  = s_axi_arregion;
        lsu_req_drive.ar.user    = s_axi_aruser;
        lsu_req_drive.ar_valid   = (s_axi_arvalid === 1'b1);
        lsu_req_drive.r_ready    = (s_axi_rready === 1'b1);
    end

    // LSU stimulus injection:
    //  * Stub build: the stub is the sole driver of the LSU master and drives
    //    lsu_axi_req from `lsu_req_drive` (upward reference; no force).
    //  * CPU firmware-boot (+cpu_boot): the real VeeR owns LSU/IFU/DBG.
    //  * no_cpu on the full-CPU VCS build: VeeR is held off
    //    (mpc_reset_run_req=0), so the VIP owns the post-remap LSU request.
    //    Same node the stub drives, so VIP addresses do not pass through
    //    u_lsu_local_alias_remap. The raw response is held idle so the halted
    //    core sees no beats it did not issue. Verilator cannot force the whole
    //    request struct; that path stays on the stub.
`ifndef SEP_CPU_STUB
    `ifdef VERILATOR
    initial if (!$test$plusargs("cpu_boot"))
        $fatal(1, "no_cpu test on the full-CPU Verilator build: select target=lsu_stub_all_live or pass +cpu_boot");
    `else
    initial if (!$test$plusargs("cpu_boot")) begin
        force `SEP_CORE.u_sep_cpu.lsu_axi_req      = lsu_req_drive;
        force `SEP_CORE.u_sep_cpu.lsu_axi_resp_raw = '0;
        $display("[tb] no_cpu on full-CPU build: LSU VIP force-splice active");
    end
    `endif
`endif

    // ------------------------------------------------------------------
    // SMN-inbound external AXI master (prefix m_axi).
    //
    // The inbound req struct is assembled combinationally from the flat cocotb
    // master inputs. The DUT's smn_inbound_axi_req_i port uses this live struct
    // only when SEP_SMN_INBOUND_AXI_LIVE is defined; otherwise it ties to
    // compile-time constant idle and the external-master cone can fold.
    // X-harden the handshakes (clean-1 only) so a 4-state sim sees idle, not X,
    // before cocotb drives m_axi_*.
    // ------------------------------------------------------------------
    always_comb begin
        smn_inbound_req_drive           = '{default: '0};  // zeros atop/unused
        smn_inbound_req_drive.aw.id     = m_axi_awid;
        smn_inbound_req_drive.aw.addr   = m_axi_awaddr;
        smn_inbound_req_drive.aw.len    = m_axi_awlen;
        smn_inbound_req_drive.aw.size   = m_axi_awsize;
        smn_inbound_req_drive.aw.burst  = m_axi_awburst;
        smn_inbound_req_drive.aw.lock   = m_axi_awlock;
        smn_inbound_req_drive.aw.cache  = m_axi_awcache;
        smn_inbound_req_drive.aw.prot   = m_axi_awprot;
        smn_inbound_req_drive.aw.qos    = m_axi_awqos;
        smn_inbound_req_drive.aw.region = m_axi_awregion;
        smn_inbound_req_drive.aw.user   = m_axi_awuser;
        smn_inbound_req_drive.aw_valid  = (m_axi_awvalid === 1'b1);
        smn_inbound_req_drive.w.data    = m_axi_wdata;
        smn_inbound_req_drive.w.strb    = m_axi_wstrb;
        smn_inbound_req_drive.w.last    = m_axi_wlast;
        smn_inbound_req_drive.w.user    = m_axi_wuser;
        smn_inbound_req_drive.w_valid   = (m_axi_wvalid === 1'b1);
        smn_inbound_req_drive.b_ready   = (m_axi_bready === 1'b1);
        smn_inbound_req_drive.ar.id     = m_axi_arid;
        smn_inbound_req_drive.ar.addr   = m_axi_araddr;
        smn_inbound_req_drive.ar.len    = m_axi_arlen;
        smn_inbound_req_drive.ar.size   = m_axi_arsize;
        smn_inbound_req_drive.ar.burst  = m_axi_arburst;
        smn_inbound_req_drive.ar.lock   = m_axi_arlock;
        smn_inbound_req_drive.ar.cache  = m_axi_arcache;
        smn_inbound_req_drive.ar.prot   = m_axi_arprot;
        smn_inbound_req_drive.ar.qos    = m_axi_arqos;
        smn_inbound_req_drive.ar.region = m_axi_arregion;
        smn_inbound_req_drive.ar.user   = m_axi_aruser;
        smn_inbound_req_drive.ar_valid  = (m_axi_arvalid === 1'b1);
        smn_inbound_req_drive.r_ready   = (m_axi_rready === 1'b1);
    end

    assign m_axi_awready = smn_inbound_resp_w.aw_ready;
    assign m_axi_wready  = smn_inbound_resp_w.w_ready;
    assign m_axi_bid     = smn_inbound_resp_w.b.id;
    assign m_axi_bresp   = smn_inbound_resp_w.b.resp;
    assign m_axi_buser   = smn_inbound_resp_w.b.user;
    assign m_axi_bvalid  = smn_inbound_resp_w.b_valid;
    assign m_axi_arready = smn_inbound_resp_w.ar_ready;
    assign m_axi_rid     = smn_inbound_resp_w.r.id;
    assign m_axi_rdata   = smn_inbound_resp_w.r.data;
    assign m_axi_rresp   = smn_inbound_resp_w.r.resp;
    assign m_axi_rlast   = smn_inbound_resp_w.r.last;
    assign m_axi_ruser   = smn_inbound_resp_w.r.user;
    assign m_axi_rvalid  = smn_inbound_resp_w.r_valid;

    // ------------------------------------------------------------------
    // SEP-OTP JTAG AXI-Lite master (prefix j_axi). Same scheme as the m_axi master
    // above: the DUT's axil_sep_otp_jtag_req_i port uses this live struct only
    // when SEP_JTAG_AXIL_LIVE is defined; otherwise it ties to compile-time idle.
    // Assemble the efuse_axil req struct from the flat cocotb inputs; plain
    // DUT-port connection.
    // X-harden the handshakes (clean-1 only) so the port idles, not X, before drive.
    // ------------------------------------------------------------------
    always_comb begin
        j_axil_req_drive          = '{default: '0};
        j_axil_req_drive.aw.addr  = j_axi_awaddr;
        j_axil_req_drive.aw.prot  = j_axi_awprot;
        j_axil_req_drive.aw_valid = (j_axi_awvalid === 1'b1);
        j_axil_req_drive.w.data   = j_axi_wdata;
        j_axil_req_drive.w.strb   = j_axi_wstrb;
        j_axil_req_drive.w_valid  = (j_axi_wvalid === 1'b1);
        j_axil_req_drive.b_ready  = (j_axi_bready === 1'b1);
        j_axil_req_drive.ar.addr  = j_axi_araddr;
        j_axil_req_drive.ar.prot  = j_axi_arprot;
        j_axil_req_drive.ar_valid = (j_axi_arvalid === 1'b1);
        j_axil_req_drive.r_ready  = (j_axi_rready === 1'b1);
    end

    assign j_axi_awready = j_axil_resp_w.aw_ready;
    assign j_axi_wready  = j_axil_resp_w.w_ready;
    assign j_axi_bresp   = j_axil_resp_w.b.resp;
    assign j_axi_bvalid  = j_axil_resp_w.b_valid;
    assign j_axi_arready = j_axil_resp_w.ar_ready;
    assign j_axi_rdata   = j_axil_resp_w.r.data;
    assign j_axi_rresp   = j_axil_resp_w.r.resp;
    assign j_axi_rvalid  = j_axil_resp_w.r_valid;

    // ------------------------------------------------------------------
    // CPU firmware-boot responders + observables.
    // ------------------------------------------------------------------
    // PC advance: surface the EL2 retired-instruction trace. cpu_run_ack_o is not
    // a port on bare `sep` (and ext_debug_bus_o is only [383:0]), so tap it by XMR
    // from the CPU wrapper -- the same hierarchical-read style as the LSU
    // response read below.
    assign cpu_trace_valid_o = cpu_trace_w.trace_rv_i_valid_ip;
    assign cpu_trace_addr_o  = cpu_trace_w.trace_rv_i_address_ip;
    // Full retirement record for the cocotb CPU-trace monitor: the instruction
    // encoding drives call/return decode (shadow call stack); ecause/interrupt/
    // tval qualify the exception flag below into a diagnosable trap record.
    assign cpu_trace_insn_o      = cpu_trace_w.trace_rv_i_insn_ip;
    assign cpu_trace_ecause_o    = cpu_trace_w.trace_rv_i_ecause_ip;
    assign cpu_trace_interrupt_o = cpu_trace_w.trace_rv_i_interrupt_ip;
    assign cpu_trace_tval_o      = cpu_trace_w.trace_rv_i_tval_ip;
    assign o_cpu_run_ack_o   = `SEP_CORE.u_sep_cpu.cpu_run_ack_o;

    // SEP resets (internal nets): the reset-independence and wdt-reset-path
    // tests read them. Same XMR-probe style as above.
    assign dbg_sep_reset_n_o = `SEP_CORE.sep_reset_n;
    assign sep_cpu_reset_n_o = `SEP_CORE.sep_cpu_reset_n;

    // IP-interrupt aggregate vector feeding the PIC (sep.sv sep_internal_interrupts):
    // observation-only mirror for the IP->aggregator test. CSRNG INTR sources
    // map to bits [26:23], EDN to [28:27] (the sep_internal_interrupts
    // assignment in sep.sv).
    assign sep_internal_interrupts_probe_o = `SEP_CORE.sep_internal_interrupts;

    // CPU/DMA SRAM contention. BUSY is a job-level status and does not prove
    // that both masters requested the SRAM together; no CSR mirrors per-cycle
    // crossbar arbitration. Count cycles where both local-crossbar inputs
    // present the same SRAM address channel.
    // This monitor observes requests only and drives no DUT signal.
    logic cpu_lsu_sram_aw_pending;
    logic cpu_lsu_sram_ar_pending;
    logic dma_sram_aw_pending;
    logic dma_sram_ar_pending;
    logic dma_cpu_sram_overlap;
    assign cpu_lsu_sram_aw_pending =
        `SEP_CORE.lsu_xbar_axi_req.aw_valid &&
        (`SEP_CORE.lsu_xbar_axi_req.aw.addr >=
            32'(sep_top_addrmap_pkg::SEP_TOP_SEP_SRAM_BASE_ADDR)) &&
        (`SEP_CORE.lsu_xbar_axi_req.aw.addr <
            32'(sep_top_addrmap_pkg::SEP_TOP_SEP_SRAM_BASE_ADDR +
                sep_top_addrmap_pkg::SEP_TOP_SEP_SRAM_SIZE));
    assign cpu_lsu_sram_ar_pending =
        `SEP_CORE.lsu_xbar_axi_req.ar_valid &&
        (`SEP_CORE.lsu_xbar_axi_req.ar.addr >=
            32'(sep_top_addrmap_pkg::SEP_TOP_SEP_SRAM_BASE_ADDR)) &&
        (`SEP_CORE.lsu_xbar_axi_req.ar.addr <
            32'(sep_top_addrmap_pkg::SEP_TOP_SEP_SRAM_BASE_ADDR +
                sep_top_addrmap_pkg::SEP_TOP_SEP_SRAM_SIZE));
    assign dma_sram_aw_pending =
        `SEP_CORE.dma_axi_req.aw_valid &&
        (`SEP_CORE.dma_axi_req.aw.addr >=
            32'(sep_top_addrmap_pkg::SEP_TOP_SEP_SRAM_BASE_ADDR)) &&
        (`SEP_CORE.dma_axi_req.aw.addr <
            32'(sep_top_addrmap_pkg::SEP_TOP_SEP_SRAM_BASE_ADDR +
                sep_top_addrmap_pkg::SEP_TOP_SEP_SRAM_SIZE));
    assign dma_sram_ar_pending =
        `SEP_CORE.dma_axi_req.ar_valid &&
        (`SEP_CORE.dma_axi_req.ar.addr >=
            32'(sep_top_addrmap_pkg::SEP_TOP_SEP_SRAM_BASE_ADDR)) &&
        (`SEP_CORE.dma_axi_req.ar.addr <
            32'(sep_top_addrmap_pkg::SEP_TOP_SEP_SRAM_BASE_ADDR +
                sep_top_addrmap_pkg::SEP_TOP_SEP_SRAM_SIZE));
    assign dma_cpu_sram_overlap =
        (cpu_lsu_sram_aw_pending && dma_sram_aw_pending) ||
        (cpu_lsu_sram_ar_pending && dma_sram_ar_pending);

    always_ff @(posedge clk_i or negedge rst_n_int) begin
        if (!rst_n_int) begin
            dma_cpu_sram_overlap_count_o <= '0;
        end else if (dma_cpu_sram_overlap && !(&dma_cpu_sram_overlap_count_o)) begin
            dma_cpu_sram_overlap_count_o <= dma_cpu_sram_overlap_count_o + 1'b1;
        end
    end

    // SPI-to-DMA transmit pacing probes (read-only XMR, no force).
    assign spi_tx_qd_probe_o =
        `SEP_CORE.u_sep_io.u_sep_ot_spi_wrap.u_spi_host.tx_qd;
    assign spi_lsio_trigger_probe_o = `SEP_CORE.lsio_trigger[0];
    assign dma_busy_probe_o =
        `SEP_CORE.u_sep_dma_wrap.u_secure_dma.reg2hw.status.busy.q;

    // Secure DMA master taps (read-only XMR, no force). dma_axi_req is the
    // request after u_dma_local_alias_remap; the layout is in the signal list.
    assign dma_axi_req_probe_o = {
        `SEP_CORE.dma_axi_resp.b.resp,
        `SEP_CORE.dma_axi_req.b_ready,
        `SEP_CORE.dma_axi_resp.b_valid,
        `SEP_CORE.dma_axi_req.w.last,
        `SEP_CORE.dma_axi_req.w.strb,
        `SEP_CORE.dma_axi_resp.w_ready,
        `SEP_CORE.dma_axi_req.w_valid,
        `SEP_CORE.dma_axi_req.aw.size,
        `SEP_CORE.dma_axi_req.aw.len,
        `SEP_CORE.dma_axi_req.aw.addr[31:0],
        `SEP_CORE.dma_axi_resp.aw_ready,
        `SEP_CORE.dma_axi_req.aw_valid,
        `SEP_CORE.dma_axi_req.ar.size,
        `SEP_CORE.dma_axi_req.ar.len,
        `SEP_CORE.dma_axi_req.ar.addr[31:0],
        `SEP_CORE.dma_axi_resp.ar_ready,
        `SEP_CORE.dma_axi_req.ar_valid
    };
    assign dma_status_probe_o = {
        `SEP_CORE.u_sep_dma_wrap.u_secure_dma.u_secure_dma_reg.status_chunk_done_qs,
        `SEP_CORE.u_sep_dma_wrap.u_secure_dma.u_secure_dma_reg.status_sha2_digest_valid_qs,
        `SEP_CORE.u_sep_dma_wrap.u_secure_dma.u_secure_dma_reg.status_error_qs,
        `SEP_CORE.u_sep_dma_wrap.u_secure_dma.u_secure_dma_reg.status_aborted_qs,
        `SEP_CORE.u_sep_dma_wrap.u_secure_dma.u_secure_dma_reg.status_done_qs,
        `SEP_CORE.u_sep_dma_wrap.u_secure_dma.u_secure_dma_reg.status_busy_qs
    };

    // Mailbox, IRQ and PIC observation taps (docs/SEP_TB_ARCH.adoc). Read-only
    // copies of DUT nets; no force.
    assign crypto_alert_pulse_probe_o = `SEP_CORE.u_sep_crypto.crypto_alert_pulse;
`ifndef SEP_CPU_STUB
`define SEP_PIC_CTRL `SEP_CORE.u_sep_cpu.u_el2_veer_wrapper.veer.pic_ctrl_inst
    assign pic_rd_data_probe_o = {
        `SEP_PIC_CTRL.picm_rden_ff,
        `SEP_PIC_CTRL.picm_raddr_ff[14:0],
        `SEP_PIC_CTRL.picm_rd_data
    };
`undef SEP_PIC_CTRL
`else
    assign pic_rd_data_probe_o = '0;
`endif
    // Set term and clear pulse of each bridge-fault latch. The register bridges
    // (axi_lite_to_tlul) set on a TL-UL error response; the DMA master bridge
    // (tlul_to_axi_lite) sets on a non-OKAY AXI response or an integrity error.
`define SEP_BRIDGE_ERR_SET(b) (b.tl_i.d_valid & b.tl_i.d_error)
`define SEP_CRYPTO `SEP_CORE.u_sep_crypto
    assign sep_cpu_ctrl_err_pulse_probe_o = {
        `SEP_CORE.u_sep_dma_wrap.u_tlul_to_axi_lite_dma.err_clr_i,
        `SEP_CORE.u_sep_dma_wrap.u_axi_lite_to_tlul_reg.err_clr_i,
        `SEP_CORE.u_sep_wdt_wrap.u_wdt_axi_lite_to_tlul.err_clr_i,
        `SEP_DRBG.u_edn_axi_lite_to_tlul.err_clr_i,
        `SEP_DRBG.u_csrng_axi_lite_to_tlul.err_clr_i,
        `SEP_CRYPTO.u_sep_crypto_otbn_wrapper_s3c_scan.u_axi_lite_to_tlul.err_clr_i,
        `SEP_CRYPTO.u_kmac_wrapper_s3c_scan.u_kmac_axi_lite_to_tlul.err_clr_i,
        `SEP_CRYPTO.u_hmac_wrapper_s3c_scan.u_hmac_axi_lite_to_tlul.err_clr_i,
        `SEP_CRYPTO.u_aes_wrapper_s3c_scan.u_aes_axi_lite_to_tlul.err_clr_i,
        (`SEP_CORE.u_sep_dma_wrap.u_tlul_to_axi_lite_dma.axi_lite_rsp_i.b_valid &
         (`SEP_CORE.u_sep_dma_wrap.u_tlul_to_axi_lite_dma.axi_lite_rsp_i.b.resp != 2'b00)) |
        (`SEP_CORE.u_sep_dma_wrap.u_tlul_to_axi_lite_dma.axi_lite_rsp_i.r_valid &
         (`SEP_CORE.u_sep_dma_wrap.u_tlul_to_axi_lite_dma.axi_lite_rsp_i.r.resp != 2'b00)) |
        `SEP_CORE.u_sep_dma_wrap.u_tlul_to_axi_lite_dma.intg_err,
        `SEP_BRIDGE_ERR_SET(`SEP_CORE.u_sep_dma_wrap.u_axi_lite_to_tlul_reg),
        `SEP_BRIDGE_ERR_SET(`SEP_CORE.u_sep_wdt_wrap.u_wdt_axi_lite_to_tlul),
        `SEP_BRIDGE_ERR_SET(`SEP_DRBG.u_edn_axi_lite_to_tlul),
        `SEP_BRIDGE_ERR_SET(`SEP_DRBG.u_csrng_axi_lite_to_tlul),
        `SEP_BRIDGE_ERR_SET(`SEP_CRYPTO.u_sep_crypto_otbn_wrapper_s3c_scan.u_axi_lite_to_tlul),
        `SEP_BRIDGE_ERR_SET(`SEP_CRYPTO.u_kmac_wrapper_s3c_scan.u_kmac_axi_lite_to_tlul),
        `SEP_BRIDGE_ERR_SET(`SEP_CRYPTO.u_hmac_wrapper_s3c_scan.u_hmac_axi_lite_to_tlul),
        `SEP_BRIDGE_ERR_SET(`SEP_CRYPTO.u_aes_wrapper_s3c_scan.u_aes_axi_lite_to_tlul)
    };
`undef SEP_CRYPTO
`undef SEP_BRIDGE_ERR_SET

    // Fabric-slot W channel, sampled at the AXI-Lite port of each of the 96
    // remap/filter slot register blocks in sep_system_csr (the block that
    // applies WSTRB). A beat counts as fill when a byte lane whose WSTRB bit is
    // 0 carries non-zero data. Slot order as in the signal list. Explicit
    // per-index assigns avoid a genvar-indexed XMR. Observation-only: reads
    // the regblock ports and drives no DUT signal.
    localparam int unsigned FabricSlots = $bits(fabric_slot_w_fill_seen_o);
    logic [FabricSlots-1:0] fabric_slot_w_hs;
    logic [FabricSlots-1:0] fabric_slot_w_fill;

    function automatic logic fabric_w_inactive_data(input logic [63:0] data,
                                                    input logic [7:0] strb);
        logic [63:0] inactive;
        for (int lane = 0; lane < 8; lane++) begin
            inactive[8*lane +: 8] = {8{~strb[lane]}};
        end
        return |(data & inactive);
    endfunction

`define FABRIC_SLOT_W(k, blk) \
    assign fabric_slot_w_hs[k] = \
        (`SEP_CORE.u_sep_system_peripherals.u_sep_system_csr.blk.s_axil_wvalid === 1'b1) && \
        (`SEP_CORE.u_sep_system_peripherals.u_sep_system_csr.blk.s_axil_wready === 1'b1); \
    assign fabric_slot_w_fill[k] = fabric_slot_w_hs[k] && fabric_w_inactive_data( \
        `SEP_CORE.u_sep_system_peripherals.u_sep_system_csr.blk.s_axil_wdata, \
        `SEP_CORE.u_sep_system_peripherals.u_sep_system_csr.blk.s_axil_wstrb)
    `FABRIC_SLOT_W(0, gen_local_master_alias_remap_reg[0].u_local_masters_alias_remap_reg);
    `FABRIC_SLOT_W(1, gen_local_master_alias_remap_reg[1].u_local_masters_alias_remap_reg);
    `FABRIC_SLOT_W(2, gen_local_master_alias_remap_reg[2].u_local_masters_alias_remap_reg);
    `FABRIC_SLOT_W(3, gen_local_master_alias_remap_reg[3].u_local_masters_alias_remap_reg);
    `FABRIC_SLOT_W(4, gen_local_master_alias_remap_reg[4].u_local_masters_alias_remap_reg);
    `FABRIC_SLOT_W(5, gen_local_master_alias_remap_reg[5].u_local_masters_alias_remap_reg);
    `FABRIC_SLOT_W(6, gen_local_master_alias_remap_reg[6].u_local_masters_alias_remap_reg);
    `FABRIC_SLOT_W(7, gen_local_master_alias_remap_reg[7].u_local_masters_alias_remap_reg);
    `FABRIC_SLOT_W(8, gen_local_master_alias_remap_reg[8].u_local_masters_alias_remap_reg);
    `FABRIC_SLOT_W(9, gen_local_master_alias_remap_reg[9].u_local_masters_alias_remap_reg);
    `FABRIC_SLOT_W(10, gen_local_master_alias_remap_reg[10].u_local_masters_alias_remap_reg);
    `FABRIC_SLOT_W(11, gen_local_master_alias_remap_reg[11].u_local_masters_alias_remap_reg);
    `FABRIC_SLOT_W(12, gen_local_master_alias_remap_reg[12].u_local_masters_alias_remap_reg);
    `FABRIC_SLOT_W(13, gen_local_master_alias_remap_reg[13].u_local_masters_alias_remap_reg);
    `FABRIC_SLOT_W(14, gen_local_master_alias_remap_reg[14].u_local_masters_alias_remap_reg);
    `FABRIC_SLOT_W(15, gen_local_master_alias_remap_reg[15].u_local_masters_alias_remap_reg);
    `FABRIC_SLOT_W(16, gen_ap_output_remap_reg[0].u_ap_output_remap_reg);
    `FABRIC_SLOT_W(17, gen_ap_output_remap_reg[1].u_ap_output_remap_reg);
    `FABRIC_SLOT_W(18, gen_ap_output_remap_reg[2].u_ap_output_remap_reg);
    `FABRIC_SLOT_W(19, gen_ap_output_remap_reg[3].u_ap_output_remap_reg);
    `FABRIC_SLOT_W(20, gen_ap_output_remap_reg[4].u_ap_output_remap_reg);
    `FABRIC_SLOT_W(21, gen_ap_output_remap_reg[5].u_ap_output_remap_reg);
    `FABRIC_SLOT_W(22, gen_ap_output_remap_reg[6].u_ap_output_remap_reg);
    `FABRIC_SLOT_W(23, gen_ap_output_remap_reg[7].u_ap_output_remap_reg);
    `FABRIC_SLOT_W(24, gen_ap_output_remap_reg[8].u_ap_output_remap_reg);
    `FABRIC_SLOT_W(25, gen_ap_output_remap_reg[9].u_ap_output_remap_reg);
    `FABRIC_SLOT_W(26, gen_ap_output_remap_reg[10].u_ap_output_remap_reg);
    `FABRIC_SLOT_W(27, gen_ap_output_remap_reg[11].u_ap_output_remap_reg);
    `FABRIC_SLOT_W(28, gen_ap_output_remap_reg[12].u_ap_output_remap_reg);
    `FABRIC_SLOT_W(29, gen_ap_output_remap_reg[13].u_ap_output_remap_reg);
    `FABRIC_SLOT_W(30, gen_ap_output_remap_reg[14].u_ap_output_remap_reg);
    `FABRIC_SLOT_W(31, gen_ap_output_remap_reg[15].u_ap_output_remap_reg);
    `FABRIC_SLOT_W(32, gen_stee_output_remap_reg[0].u_stee_output_remap_reg);
    `FABRIC_SLOT_W(33, gen_stee_output_remap_reg[1].u_stee_output_remap_reg);
    `FABRIC_SLOT_W(34, gen_stee_output_remap_reg[2].u_stee_output_remap_reg);
    `FABRIC_SLOT_W(35, gen_stee_output_remap_reg[3].u_stee_output_remap_reg);
    `FABRIC_SLOT_W(36, gen_stee_output_remap_reg[4].u_stee_output_remap_reg);
    `FABRIC_SLOT_W(37, gen_stee_output_remap_reg[5].u_stee_output_remap_reg);
    `FABRIC_SLOT_W(38, gen_stee_output_remap_reg[6].u_stee_output_remap_reg);
    `FABRIC_SLOT_W(39, gen_stee_output_remap_reg[7].u_stee_output_remap_reg);
    `FABRIC_SLOT_W(40, gen_stee_output_remap_reg[8].u_stee_output_remap_reg);
    `FABRIC_SLOT_W(41, gen_stee_output_remap_reg[9].u_stee_output_remap_reg);
    `FABRIC_SLOT_W(42, gen_stee_output_remap_reg[10].u_stee_output_remap_reg);
    `FABRIC_SLOT_W(43, gen_stee_output_remap_reg[11].u_stee_output_remap_reg);
    `FABRIC_SLOT_W(44, gen_stee_output_remap_reg[12].u_stee_output_remap_reg);
    `FABRIC_SLOT_W(45, gen_stee_output_remap_reg[13].u_stee_output_remap_reg);
    `FABRIC_SLOT_W(46, gen_stee_output_remap_reg[14].u_stee_output_remap_reg);
    `FABRIC_SLOT_W(47, gen_stee_output_remap_reg[15].u_stee_output_remap_reg);
    `FABRIC_SLOT_W(48, gen_outbound_filter_reg[0].u_outbound_filter_reg);
    `FABRIC_SLOT_W(49, gen_outbound_filter_reg[1].u_outbound_filter_reg);
    `FABRIC_SLOT_W(50, gen_outbound_filter_reg[2].u_outbound_filter_reg);
    `FABRIC_SLOT_W(51, gen_outbound_filter_reg[3].u_outbound_filter_reg);
    `FABRIC_SLOT_W(52, gen_outbound_filter_reg[4].u_outbound_filter_reg);
    `FABRIC_SLOT_W(53, gen_outbound_filter_reg[5].u_outbound_filter_reg);
    `FABRIC_SLOT_W(54, gen_outbound_filter_reg[6].u_outbound_filter_reg);
    `FABRIC_SLOT_W(55, gen_outbound_filter_reg[7].u_outbound_filter_reg);
    `FABRIC_SLOT_W(56, gen_outbound_filter_reg[8].u_outbound_filter_reg);
    `FABRIC_SLOT_W(57, gen_outbound_filter_reg[9].u_outbound_filter_reg);
    `FABRIC_SLOT_W(58, gen_outbound_filter_reg[10].u_outbound_filter_reg);
    `FABRIC_SLOT_W(59, gen_outbound_filter_reg[11].u_outbound_filter_reg);
    `FABRIC_SLOT_W(60, gen_outbound_filter_reg[12].u_outbound_filter_reg);
    `FABRIC_SLOT_W(61, gen_outbound_filter_reg[13].u_outbound_filter_reg);
    `FABRIC_SLOT_W(62, gen_outbound_filter_reg[14].u_outbound_filter_reg);
    `FABRIC_SLOT_W(63, gen_outbound_filter_reg[15].u_outbound_filter_reg);
    `FABRIC_SLOT_W(64, gen_outbound_filter_reg[16].u_outbound_filter_reg);
    `FABRIC_SLOT_W(65, gen_outbound_filter_reg[17].u_outbound_filter_reg);
    `FABRIC_SLOT_W(66, gen_outbound_filter_reg[18].u_outbound_filter_reg);
    `FABRIC_SLOT_W(67, gen_outbound_filter_reg[19].u_outbound_filter_reg);
    `FABRIC_SLOT_W(68, gen_outbound_filter_reg[20].u_outbound_filter_reg);
    `FABRIC_SLOT_W(69, gen_outbound_filter_reg[21].u_outbound_filter_reg);
    `FABRIC_SLOT_W(70, gen_outbound_filter_reg[22].u_outbound_filter_reg);
    `FABRIC_SLOT_W(71, gen_outbound_filter_reg[23].u_outbound_filter_reg);
    `FABRIC_SLOT_W(72, gen_outbound_filter_reg[24].u_outbound_filter_reg);
    `FABRIC_SLOT_W(73, gen_outbound_filter_reg[25].u_outbound_filter_reg);
    `FABRIC_SLOT_W(74, gen_outbound_filter_reg[26].u_outbound_filter_reg);
    `FABRIC_SLOT_W(75, gen_outbound_filter_reg[27].u_outbound_filter_reg);
    `FABRIC_SLOT_W(76, gen_outbound_filter_reg[28].u_outbound_filter_reg);
    `FABRIC_SLOT_W(77, gen_outbound_filter_reg[29].u_outbound_filter_reg);
    `FABRIC_SLOT_W(78, gen_outbound_filter_reg[30].u_outbound_filter_reg);
    `FABRIC_SLOT_W(79, gen_outbound_filter_reg[31].u_outbound_filter_reg);
    `FABRIC_SLOT_W(80, gen_inbound_filter_reg[0].u_inbound_filter_reg);
    `FABRIC_SLOT_W(81, gen_inbound_filter_reg[1].u_inbound_filter_reg);
    `FABRIC_SLOT_W(82, gen_inbound_filter_reg[2].u_inbound_filter_reg);
    `FABRIC_SLOT_W(83, gen_inbound_filter_reg[3].u_inbound_filter_reg);
    `FABRIC_SLOT_W(84, gen_inbound_filter_reg[4].u_inbound_filter_reg);
    `FABRIC_SLOT_W(85, gen_inbound_filter_reg[5].u_inbound_filter_reg);
    `FABRIC_SLOT_W(86, gen_inbound_filter_reg[6].u_inbound_filter_reg);
    `FABRIC_SLOT_W(87, gen_inbound_filter_reg[7].u_inbound_filter_reg);
    `FABRIC_SLOT_W(88, gen_inbound_filter_reg[8].u_inbound_filter_reg);
    `FABRIC_SLOT_W(89, gen_inbound_filter_reg[9].u_inbound_filter_reg);
    `FABRIC_SLOT_W(90, gen_inbound_filter_reg[10].u_inbound_filter_reg);
    `FABRIC_SLOT_W(91, gen_inbound_filter_reg[11].u_inbound_filter_reg);
    `FABRIC_SLOT_W(92, gen_inbound_filter_reg[12].u_inbound_filter_reg);
    `FABRIC_SLOT_W(93, gen_inbound_filter_reg[13].u_inbound_filter_reg);
    `FABRIC_SLOT_W(94, gen_inbound_filter_reg[14].u_inbound_filter_reg);
    `FABRIC_SLOT_W(95, gen_inbound_filter_reg[15].u_inbound_filter_reg);
`undef FABRIC_SLOT_W

    always_ff @(posedge clk_i or negedge rst_n_int) begin
        if (!rst_n_int) begin
            fabric_slot_w_beats_o      <= '0;
            fabric_slot_w_fill_beats_o <= '0;
            fabric_slot_w_fill_seen_o  <= '0;
        end else begin
            if (|fabric_slot_w_hs && !(&fabric_slot_w_beats_o)) begin
                fabric_slot_w_beats_o <= fabric_slot_w_beats_o + 1'b1;
            end
            if (|fabric_slot_w_fill && !(&fabric_slot_w_fill_beats_o)) begin
                fabric_slot_w_fill_beats_o <= fabric_slot_w_fill_beats_o + 1'b1;
            end
            fabric_slot_w_fill_seen_o <= fabric_slot_w_fill_seen_o | fabric_slot_w_fill;
        end
    end

    assign entropy_pool_packer_depth_o = `SEP_CORE.u_entropy_fifo.packer_depth;
    assign trng_gated_rst_n_probe_o =
        `SEP_CORE.u_sep_reset_ctrl.sep_crypto_gated_rst_no.trng;
    assign trng_reset_active_probe_o =
        `SEP_CORE.u_sep_crypto.u_sep_trng.trng_reset_active_o;
    assign trng_axi_isolated_probe_o = {
        `SEP_CORE.u_sep_crypto.u_sep_crypto_axi_interconnect.isolated_o.trng_edn,
        `SEP_CORE.u_sep_crypto.u_sep_crypto_axi_interconnect.isolated_o.trng_csrng,
        `SEP_CORE.u_sep_crypto.u_sep_crypto_axi_interconnect.isolated_o.trng_entropy_source
    };

    // HMAC per-IP gated reset and the two isolate-completion bits that domain
    // depends on. The reset sequencer holds the domain until every AXI-Lite
    // path it depends on reports isolated, so the drain-before-reset checks
    // read the reset and both paths.
    assign hmac_gated_rst_n_probe_o =
        `SEP_CORE.u_sep_reset_ctrl.sep_crypto_gated_rst_no.hmac;
    assign hmac_host_isolated_probe_o =
        `SEP_CORE.u_sep_crypto.u_sep_crypto_axi_interconnect.isolated_o.host_hmac;
    assign hmac_km_isolated_probe_o =
        `SEP_CORE.u_sep_crypto.u_sep_crypto_axi_interconnect.isolated_o.km_hmac;
    assign hmac_host_isolate_req_probe_o =
        `SEP_CORE.u_sep_crypto.u_sep_crypto_axi_interconnect.isolate_req_i.host_hmac;

    // KMAC per-IP gated reset and its two isolate-completion bits.
    assign kmac_gated_rst_n_probe_o =
        `SEP_CORE.u_sep_reset_ctrl.sep_crypto_gated_rst_no.kmac;
    assign kmac_host_isolated_probe_o =
        `SEP_CORE.u_sep_crypto.u_sep_crypto_axi_interconnect.isolated_o.host_kmac;
    assign kmac_km_isolated_probe_o =
        `SEP_CORE.u_sep_crypto.u_sep_crypto_axi_interconnect.isolated_o.km_kmac;
    assign kmac_host_isolate_req_probe_o =
        `SEP_CORE.u_sep_crypto.u_sep_crypto_axi_interconnect.isolate_req_i.host_kmac;

    // Adams Bridge per-IP gated reset and the two isolate-completion bits its
    // domain waits on. host_abr is a full-AXI isolate; km_abr is shared with
    // the Key Manager domain and an ABR reset request alone must raise it.
    assign abr_gated_rst_n_probe_o =
        `SEP_CORE.u_sep_reset_ctrl.sep_crypto_gated_rst_no.abr;
    assign abr_host_isolated_probe_o =
        `SEP_CORE.u_sep_crypto.u_sep_crypto_axi_interconnect.isolated_o.host_abr;
    assign abr_km_isolated_probe_o =
        `SEP_CORE.u_sep_crypto.u_sep_crypto_axi_interconnect.isolated_o.km_abr;
    assign abr_host_isolate_req_probe_o =
        `SEP_CORE.u_sep_crypto.u_sep_crypto_axi_interconnect.isolate_req_i.host_abr;

    // AES and OTBN per-IP gated resets. A software reset of either cancels its
    // crypto EDN endpoints before this reset asserts; the isolation test times
    // that cancel against these. Read-only XMR, same class as the KMAC probe.
    assign aes_gated_rst_n_probe_o =
        `SEP_CORE.u_sep_reset_ctrl.sep_crypto_gated_rst_no.aes;
    assign otbn_gated_rst_n_probe_o =
        `SEP_CORE.u_sep_reset_ctrl.sep_crypto_gated_rst_no.otbn;
    // Key Manager warm reset and the full isolate request and isolate-complete
    // vectors. Read-only XMRs, same class as the probes above. Bit x of each
    // vector is VPLAN bench isolate stage x, assigned from the isolate struct
    // field of that path by name, so the tap carries the bench layout.
    assign km_gated_rst_n_probe_o =
        `SEP_CORE.u_sep_reset_ctrl.sep_crypto_gated_rst_no.km;
`define SEP_TB_ISO_BIT(x, f) \
    assign crypto_isolate_req_probe_o[x] = `SEP_CORE.sep_crypto_isolate_req.f; \
    assign crypto_isolated_probe_o[x]    = `SEP_CORE.sep_crypto_isolated.f;
    `SEP_TB_ISO_BIT(0, host_otbn)
    `SEP_TB_ISO_BIT(1, host_aes)
    `SEP_TB_ISO_BIT(2, host_hmac)
    `SEP_TB_ISO_BIT(3, host_kmac)
    `SEP_TB_ISO_BIT(4, host_abr)
    `SEP_TB_ISO_BIT(5, trng_entropy_source)
    `SEP_TB_ISO_BIT(6, trng_csrng)
    `SEP_TB_ISO_BIT(7, trng_edn)
    `SEP_TB_ISO_BIT(8, km_otbn)
    `SEP_TB_ISO_BIT(9, km_aes)
    `SEP_TB_ISO_BIT(10, km_hmac)
    `SEP_TB_ISO_BIT(11, km_kmac)
    `SEP_TB_ISO_BIT(12, km_abr)
    `SEP_TB_ISO_BIT(13, km_efuse)
`undef SEP_TB_ISO_BIT
    // Slave side of each isolate stage (sep_crypto_axi_interconnect.sv), bit x the
    // VPLAN bench isolate stage x, as in the vectors above. Read-only XMRs of the
    // stage ports.
`define SEP_TB_ISO_SLV(i, inst) \
    assign iso_slv_aw_hs_probe_o[i] = `SEP_ISO_IC.inst.slv_req_i.aw_valid & \
                                      `SEP_ISO_IC.inst.slv_resp_o.aw_ready; \
    assign iso_slv_ar_hs_probe_o[i] = `SEP_ISO_IC.inst.slv_req_i.ar_valid & \
                                      `SEP_ISO_IC.inst.slv_resp_o.ar_ready; \
    assign iso_slv_b_hs_probe_o[i]  = `SEP_ISO_IC.inst.slv_resp_o.b_valid & \
                                      `SEP_ISO_IC.inst.slv_req_i.b_ready; \
    assign iso_slv_r_hs_probe_o[i]  = `SEP_ISO_IC.inst.slv_resp_o.r_valid & \
                                      `SEP_ISO_IC.inst.slv_req_i.r_ready; \
    assign iso_slv_bresp_probe_o[2*(i)+:2] = `SEP_ISO_IC.inst.slv_resp_o.b.resp; \
    assign iso_slv_rresp_probe_o[2*(i)+:2] = `SEP_ISO_IC.inst.slv_resp_o.r.resp;
`define SEP_ISO_IC `SEP_CORE.u_sep_crypto.u_sep_crypto_axi_interconnect
    `SEP_TB_ISO_SLV(0, u_otbn_host_isolate)
    `SEP_TB_ISO_SLV(1, u_aes_host_isolate)
    `SEP_TB_ISO_SLV(2, u_hmac_host_isolate)
    `SEP_TB_ISO_SLV(3, u_kmac_host_isolate)
    `SEP_TB_ISO_SLV(4, u_abr_host_isolate)
    `SEP_TB_ISO_SLV(5, u_esrc_host_isolate)
    `SEP_TB_ISO_SLV(6, u_csrng_host_isolate)
    `SEP_TB_ISO_SLV(7, u_edn_host_isolate)
    `SEP_TB_ISO_SLV(8, u_otbn_key_isolate)
    `SEP_TB_ISO_SLV(9, u_aes_key_isolate)
    `SEP_TB_ISO_SLV(10, u_hmac_key_isolate)
    `SEP_TB_ISO_SLV(11, u_kmac_key_isolate)
    `SEP_TB_ISO_SLV(12, u_abr_key_isolate)
    `SEP_TB_ISO_SLV(13, u_km_efuse_isolate)
`undef SEP_TB_ISO_SLV
`undef SEP_ISO_IC
    // Watchdog timer-domain reset and the two Key Manager reset conditioner
    // outputs. Read-only XMRs.
    assign aon_rst_n_probe_o = `SEP_CORE.u_sep_wdt_wrap.rst_wdt_n;
    // sep_reset_n override select on the SEP input port. Read-only XMR.
    assign jtag_sep_reset_n_ovrd_probe_o =
        `SEP_CORE.jtag_sep_reset_ctrl_i.ovrd.sep_reset_n_ovrd;
    assign km_cond_rst_probe_o = {
        `SEP_CORE.u_sep_crypto.u_key_manager_s3c_scan.rst_cold_aasd_n,
        `SEP_CORE.u_sep_crypto.u_key_manager_s3c_scan.rst_warm_sync_n
    };
    // Output of the CPU run-request synchronizer; the CPU stub has none.
`ifndef SEP_CPU_STUB
    assign mpc_run_sync_probe_o = `SEP_CORE.u_sep_cpu.mpc_reset_run_req_sync;
`else
    assign mpc_run_sync_probe_o = 1'b0;
`endif
    // Debug reset input of the core wrapper; the CPU stub has none.
`ifndef SEP_CPU_STUB
    assign dbg_rst_l_probe_o = `SEP_CORE.u_sep_cpu.u_el2_veer_wrapper.dbg_rst_l;
`else
    assign dbg_rst_l_probe_o = 1'b1;
`endif
    // Read source of TIMEOUT_INTERRUPT.reserved, the value a register read returns.
`define SEP_SYS_CSR `SEP_CORE.u_sep_system_peripherals.u_sep_system_csr
    assign timeout_interrupt_probe_o =
        `SEP_SYS_CSR.sep_cpu_ctrl_hwif_in.TIMEOUT_INTERRUPT.reserved.next;
`undef SEP_SYS_CSR

    // Read-only XMRs observe the write-one-to-set demotion lock storage. The lock
    // bits have no DUT output, and firmware owns the AXI frontdoor while they are
    // programmed. These leaf fields sit outside the AXI ready/valid combinational
    // cones and retain whether firmware wrote each lock.
    assign lcc_demote_lock_1_probe_o =
        `SEP_CORE.u_sep_crypto.u_sep_lifecycle_ctrl.demote_reg_1.lock;
    assign lcc_demote_lock_2_probe_o =
        `SEP_CORE.u_sep_crypto.u_sep_lifecycle_ctrl.demote_reg_2.lock;
    // XMR, not AXI: the AXI read is inbound-filtered at PROD_END once sep_debug is 0.
    assign lcc_feat_ctrl_probe_o = `SEP_CORE.feat_ctrl;

    // Boot bring-up debug taps: did the core start fetching from the TCM? The TCM
    // req is a wrapper-internal net (u_sep -> ip_integration).
    assign dbg_iccm_active_o   = |u_dut.sep_cpu_tcm_req.iccm_clken;
    assign dbg_iccm_addr_o     = u_dut.sep_cpu_tcm_req.iccm_addr_bank[0];
    assign dbg_dccm_active_o   = |u_dut.sep_cpu_tcm_req.dccm_clken;
    assign dbg_cpu_trace_exc_o = cpu_trace_w.trace_rv_i_exception_ip;

    // Flatten the sensed shadow array (efuse_map_t, NumEfuseBits wide) to the
    // top-level probe port; word i occupies bits [32*i +: 32], matching values[i].
    assign efuse_shadow_probe_o =
        `SEP_CORE.u_sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller.u_efuse_shadow_regs.shadow_efuse_o;

    assign km_otp_sep_chiplet_id_o =
        `SEP_CORE.u_sep_crypto.u_key_manager_s3c_scan.otp_data_i.sep_chiplet_id;
    assign km_otp_sep_sip_id_o =
        `SEP_CORE.u_sep_crypto.u_key_manager_s3c_scan.otp_data_i.sep_sip_id;
    assign km_otp_sep_sys_id_o =
        `SEP_CORE.u_sep_crypto.u_key_manager_s3c_scan.otp_data_i.sep_sys_id;

    // SEP scratch-cold CSR words [0..7], each `data.value` [31:0]. Explicit
    // per-index assigns avoid a cross-hierarchy indexed XMR (same style as the
    // ESRC decorrelator-SR probe below). The EL2 coexist firmware mirrors its
    // measured summary into these; the cocotb test reads them back as the observer.
`define SCRATCH_COLD(i) \
    assign scratch_cold_probe_o[32*(i) +: 32] = \
        `SEP_CORE.u_sep_system_peripherals.u_sep_system_csr.u_sep_scratch_reg_cold.field_storage.SCRATCH[i].data.value
    `SCRATCH_COLD(0); `SCRATCH_COLD(1); `SCRATCH_COLD(2); `SCRATCH_COLD(3);
    `SCRATCH_COLD(4); `SCRATCH_COLD(5); `SCRATCH_COLD(6); `SCRATCH_COLD(7);
`undef SCRATCH_COLD

    // System-CSR AXI-Lite after u_system_csr_a2l_1. See port comment.
    assign sys_csr_axil_arvalid_o =
        `SEP_CORE.u_sep_system_peripherals.system_csr_axil_req.ar_valid;
    assign sys_csr_axil_arready_o =
        `SEP_CORE.u_sep_system_peripherals.system_csr_axil_resp.ar_ready;
    assign sys_csr_axil_araddr_o =
        `SEP_CORE.u_sep_system_peripherals.system_csr_axil_req.ar.addr[31:0];
    assign sys_csr_axil_awvalid_o =
        `SEP_CORE.u_sep_system_peripherals.system_csr_axil_req.aw_valid;
    assign sys_csr_axil_awready_o =
        `SEP_CORE.u_sep_system_peripherals.system_csr_axil_resp.aw_ready;
    assign sys_csr_axil_awaddr_o =
        `SEP_CORE.u_sep_system_peripherals.system_csr_axil_req.aw.addr[31:0];

    // Local crossbar `ext` initiator (sep.sv smn_inbound_to_sep_axi_*). See port comment.
    assign xbar_ext_in_arvalid_o = `SEP_CORE.smn_inbound_to_sep_axi_req.ar_valid;
    assign xbar_ext_in_arready_o = `SEP_CORE.smn_inbound_to_sep_axi_resp.ar_ready;
    assign xbar_ext_in_araddr_o  = `SEP_CORE.smn_inbound_to_sep_axi_req.ar.addr[31:0];
    assign xbar_ext_in_awvalid_o = `SEP_CORE.smn_inbound_to_sep_axi_req.aw_valid;
    assign xbar_ext_in_awready_o = `SEP_CORE.smn_inbound_to_sep_axi_resp.aw_ready;
    assign xbar_ext_in_awaddr_o  = `SEP_CORE.smn_inbound_to_sep_axi_req.aw.addr[31:0];

    // Fabric observation taps. See the port comments in sep_tb_signal_list.svh.
    // PR-OUT: smn_outbound_axi_req_o (the net smn_outbound_req_w).
    assign pr_out_awvalid_o = smn_outbound_req_w.aw_valid;
    assign pr_out_awready_o = smn_outbound_resp_w.aw_ready;
    assign pr_out_awaddr_o  = smn_outbound_req_w.aw.addr[55:0];
    assign pr_out_awid_o = smn_outbound_req_w.aw.id;
    assign pr_out_awuser_o = smn_outbound_req_w.aw.user;
    assign pr_out_awcache_o = smn_outbound_req_w.aw.cache;
    assign pr_out_awprot_o = smn_outbound_req_w.aw.prot;
    assign pr_out_awlen_o = smn_outbound_req_w.aw.len;
    assign pr_out_awsize_o = smn_outbound_req_w.aw.size;
    assign pr_out_awburst_o = smn_outbound_req_w.aw.burst;
    assign pr_out_arvalid_o = smn_outbound_req_w.ar_valid;
    assign pr_out_arready_o = smn_outbound_resp_w.ar_ready;
    assign pr_out_araddr_o  = smn_outbound_req_w.ar.addr[55:0];
    assign pr_out_arid_o = smn_outbound_req_w.ar.id;
    assign pr_out_aruser_o = smn_outbound_req_w.ar.user;
    assign pr_out_arcache_o = smn_outbound_req_w.ar.cache;
    assign pr_out_arprot_o = smn_outbound_req_w.ar.prot;
    assign pr_out_arlen_o = smn_outbound_req_w.ar.len;
    assign pr_out_arsize_o = smn_outbound_req_w.ar.size;
    assign pr_out_arburst_o = smn_outbound_req_w.ar.burst;
    assign pr_out_wvalid_o = smn_outbound_req_w.w_valid;
    assign pr_out_wready_o = smn_outbound_resp_w.w_ready;
    assign pr_out_wdata_o  = smn_outbound_req_w.w.data;
    assign pr_out_wstrb_o  = smn_outbound_req_w.w.strb;
    assign pr_out_wlast_o  = smn_outbound_req_w.w.last;
    // PR-OUT-RSP: the responses on smn_outbound_axi_resp_i.
    assign pr_out_bvalid_o = smn_outbound_resp_w.b_valid;
    assign pr_out_bready_o = smn_outbound_req_w.b_ready;
    assign pr_out_bresp_o  = smn_outbound_resp_w.b.resp;
    assign pr_out_bid_o    = smn_outbound_resp_w.b.id;
    assign pr_out_rvalid_o = smn_outbound_resp_w.r_valid;
    assign pr_out_rready_o = smn_outbound_req_w.r_ready;
    assign pr_out_rresp_o  = smn_outbound_resp_w.r.resp;
    assign pr_out_rid_o    = smn_outbound_resp_w.r.id;
    assign pr_out_rdata_o  = smn_outbound_resp_w.r.data;
    assign pr_out_rlast_o  = smn_outbound_resp_w.r.last;
    // PR-SMC: sep_ext_to_smc_axi_req_o (the net ext_to_smc_req_w).
    assign pr_smc_awvalid_o = ext_to_smc_req_w.aw_valid;
    assign pr_smc_awready_o = ext_to_smc_resp_w.aw_ready;
    assign pr_smc_awaddr_o  = ext_to_smc_req_w.aw.addr[55:0];
    assign pr_smc_awid_o = ext_to_smc_req_w.aw.id;
    assign pr_smc_awuser_o = ext_to_smc_req_w.aw.user;
    assign pr_smc_awcache_o = ext_to_smc_req_w.aw.cache;
    assign pr_smc_awprot_o = ext_to_smc_req_w.aw.prot;
    assign pr_smc_awlen_o = ext_to_smc_req_w.aw.len;
    assign pr_smc_awsize_o = ext_to_smc_req_w.aw.size;
    assign pr_smc_awburst_o = ext_to_smc_req_w.aw.burst;
    assign pr_smc_arvalid_o = ext_to_smc_req_w.ar_valid;
    assign pr_smc_arready_o = ext_to_smc_resp_w.ar_ready;
    assign pr_smc_araddr_o  = ext_to_smc_req_w.ar.addr[55:0];
    assign pr_smc_arid_o = ext_to_smc_req_w.ar.id;
    assign pr_smc_aruser_o = ext_to_smc_req_w.ar.user;
    assign pr_smc_arcache_o = ext_to_smc_req_w.ar.cache;
    assign pr_smc_arprot_o = ext_to_smc_req_w.ar.prot;
    assign pr_smc_arlen_o = ext_to_smc_req_w.ar.len;
    assign pr_smc_arsize_o = ext_to_smc_req_w.ar.size;
    assign pr_smc_arburst_o = ext_to_smc_req_w.ar.burst;
    assign pr_smc_wvalid_o = ext_to_smc_req_w.w_valid;
    assign pr_smc_wready_o = ext_to_smc_resp_w.w_ready;
    assign pr_smc_wdata_o  = ext_to_smc_req_w.w.data;
    assign pr_smc_wstrb_o  = ext_to_smc_req_w.w.strb;
    assign pr_smc_wlast_o  = ext_to_smc_req_w.w.last;
    // PR-EXT: the AXI Extension port, wrapper net u_dut.axi_extension_axi_req.
    assign pr_ext_awvalid_o = u_dut.axi_extension_axi_req.aw_valid;
    assign pr_ext_awready_o = u_dut.axi_extension_axi_resp.aw_ready;
    assign pr_ext_awaddr_o  = u_dut.axi_extension_axi_req.aw.addr[31:0];
    assign pr_ext_awid_o = u_dut.axi_extension_axi_req.aw.id;
    assign pr_ext_awuser_o = u_dut.axi_extension_axi_req.aw.user;
    assign pr_ext_awcache_o = u_dut.axi_extension_axi_req.aw.cache;
    assign pr_ext_awprot_o = u_dut.axi_extension_axi_req.aw.prot;
    assign pr_ext_awlen_o = u_dut.axi_extension_axi_req.aw.len;
    assign pr_ext_awsize_o = u_dut.axi_extension_axi_req.aw.size;
    assign pr_ext_awburst_o = u_dut.axi_extension_axi_req.aw.burst;
    assign pr_ext_arvalid_o = u_dut.axi_extension_axi_req.ar_valid;
    assign pr_ext_arready_o = u_dut.axi_extension_axi_resp.ar_ready;
    assign pr_ext_araddr_o  = u_dut.axi_extension_axi_req.ar.addr[31:0];
    assign pr_ext_arid_o = u_dut.axi_extension_axi_req.ar.id;
    assign pr_ext_aruser_o = u_dut.axi_extension_axi_req.ar.user;
    assign pr_ext_arcache_o = u_dut.axi_extension_axi_req.ar.cache;
    assign pr_ext_arprot_o = u_dut.axi_extension_axi_req.ar.prot;
    assign pr_ext_arlen_o = u_dut.axi_extension_axi_req.ar.len;
    assign pr_ext_arsize_o = u_dut.axi_extension_axi_req.ar.size;
    assign pr_ext_arburst_o = u_dut.axi_extension_axi_req.ar.burst;
    assign pr_ext_wvalid_o = u_dut.axi_extension_axi_req.w_valid;
    assign pr_ext_wready_o = u_dut.axi_extension_axi_resp.w_ready;
    assign pr_ext_wdata_o  = u_dut.axi_extension_axi_req.w.data;
    assign pr_ext_wstrb_o  = u_dut.axi_extension_axi_req.w.strb;
    assign pr_ext_wlast_o  = u_dut.axi_extension_axi_req.w.last;
    // PR-EXT reply: the B and R channels of the AXI Extension port.
    assign pr_ext_bvalid_o = u_dut.axi_extension_axi_resp.b_valid;
    assign pr_ext_bready_o = u_dut.axi_extension_axi_req.b_ready;
    assign pr_ext_bresp_o  = u_dut.axi_extension_axi_resp.b.resp;
    assign pr_ext_bid_o    = u_dut.axi_extension_axi_resp.b.id;
    assign pr_ext_rvalid_o = u_dut.axi_extension_axi_resp.r_valid;
    assign pr_ext_rready_o = u_dut.axi_extension_axi_req.r_ready;
    assign pr_ext_rresp_o  = u_dut.axi_extension_axi_resp.r.resp;
    assign pr_ext_rid_o    = u_dut.axi_extension_axi_resp.r.id;
    assign pr_ext_rlast_o  = u_dut.axi_extension_axi_resp.r.last;
    // PR-DMACSR: the request at the DMA CSR target port (sep.sv dma_csr_req).
    assign pr_dmacsr_awvalid_o = `SEP_CORE.dma_csr_req.aw_valid;
    assign pr_dmacsr_awready_o = `SEP_CORE.dma_csr_rsp.aw_ready;
    assign pr_dmacsr_awaddr_o  = `SEP_CORE.dma_csr_req.aw.addr[31:0];
    assign pr_dmacsr_arvalid_o = `SEP_CORE.dma_csr_req.ar_valid;
    assign pr_dmacsr_arready_o = `SEP_CORE.dma_csr_rsp.ar_ready;
    assign pr_dmacsr_araddr_o  = `SEP_CORE.dma_csr_req.ar.addr[31:0];
    // PR-INFLT: the request out of u_inbound_filter, before the global-to-local remap.
    assign pr_inflt_awvalid_o = `SEP_CORE.u_sep_system_peripherals.smn_inbound_filtered_axi_req.aw_valid;
    assign pr_inflt_awready_o = `SEP_CORE.u_sep_system_peripherals.smn_inbound_filtered_axi_resp.aw_ready;
    assign pr_inflt_awaddr_o  = `SEP_CORE.u_sep_system_peripherals.smn_inbound_filtered_axi_req.aw.addr[55:0];
    assign pr_inflt_arvalid_o = `SEP_CORE.u_sep_system_peripherals.smn_inbound_filtered_axi_req.ar_valid;
    assign pr_inflt_arready_o = `SEP_CORE.u_sep_system_peripherals.smn_inbound_filtered_axi_resp.ar_ready;
    assign pr_inflt_araddr_o  = `SEP_CORE.u_sep_system_peripherals.smn_inbound_filtered_axi_req.ar.addr[55:0];
    // PR-CPU: AxPROT of the raw CPU LSU and IFU requests, before any remap.
`ifndef SEP_CPU_STUB
    assign pr_cpu_lsu_awvalid_o = `SEP_CORE.u_sep_cpu.lsu_axi_req_raw.aw_valid;
    assign pr_cpu_lsu_awready_o = `SEP_CORE.u_sep_cpu.lsu_axi_resp_raw.aw_ready;
    assign pr_cpu_lsu_awprot_o  = `SEP_CORE.u_sep_cpu.lsu_axi_req_raw.aw.prot;
    assign pr_cpu_lsu_arvalid_o = `SEP_CORE.u_sep_cpu.lsu_axi_req_raw.ar_valid;
    assign pr_cpu_lsu_arready_o = `SEP_CORE.u_sep_cpu.lsu_axi_resp_raw.ar_ready;
    assign pr_cpu_lsu_arprot_o  = `SEP_CORE.u_sep_cpu.lsu_axi_req_raw.ar.prot;
    assign pr_cpu_ifu_arvalid_o = `SEP_CORE.u_sep_cpu.ifu_axi_req_raw.ar_valid;
    assign pr_cpu_ifu_arready_o = `SEP_CORE.u_sep_cpu.ifu_axi_resp_raw.ar_ready;
    assign pr_cpu_ifu_arprot_o  = `SEP_CORE.u_sep_cpu.ifu_axi_req_raw.ar.prot;
`else
    assign pr_cpu_lsu_awvalid_o = 1'b0;
    assign pr_cpu_lsu_awready_o = 1'b0;
    assign pr_cpu_lsu_awprot_o  = '0;
    assign pr_cpu_lsu_arvalid_o = 1'b0;
    assign pr_cpu_lsu_arready_o = 1'b0;
    assign pr_cpu_lsu_arprot_o  = '0;
    assign pr_cpu_ifu_arvalid_o = 1'b0;
    assign pr_cpu_ifu_arready_o = 1'b0;
    assign pr_cpu_ifu_arprot_o  = '0;
`endif
    // PR-DMA-RAW: AxPROT of the raw secure DMA master request.
    assign pr_dma_raw_awvalid_o = `SEP_CORE.u_sep_dma_wrap.dma_axi_req_raw.aw_valid;
    assign pr_dma_raw_awready_o = `SEP_CORE.u_sep_dma_wrap.dma_axi_resp_raw.aw_ready;
    assign pr_dma_raw_awprot_o  = `SEP_CORE.u_sep_dma_wrap.dma_axi_req_raw.aw.prot;
    assign pr_dma_raw_arvalid_o = `SEP_CORE.u_sep_dma_wrap.dma_axi_req_raw.ar_valid;
    assign pr_dma_raw_arready_o = `SEP_CORE.u_sep_dma_wrap.dma_axi_resp_raw.ar_ready;
    assign pr_dma_raw_arprot_o  = `SEP_CORE.u_sep_dma_wrap.dma_axi_req_raw.ar.prot;
    // PR-ALIAS input: the request into u_local_master_remap_wrap.
    assign pr_alias_in_awvalid_o = `SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_axi_req.aw_valid;
    assign pr_alias_in_awready_o = `SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_axi_resp.aw_ready;
    assign pr_alias_in_awaddr_o  = `SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_axi_req.aw.addr[55:0];
    assign pr_alias_in_awcache_o = `SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_axi_req.aw.cache;
    assign pr_alias_in_awprot_o = `SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_axi_req.aw.prot;
    assign pr_alias_in_arvalid_o = `SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_axi_req.ar_valid;
    assign pr_alias_in_arready_o = `SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_axi_resp.ar_ready;
    assign pr_alias_in_araddr_o  = `SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_axi_req.ar.addr[55:0];
    assign pr_alias_in_arcache_o = `SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_axi_req.ar.cache;
    assign pr_alias_in_arprot_o = `SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_axi_req.ar.prot;
    // PR-ALIAS output: the request out of u_local_master_remap_wrap.
    assign pr_alias_out_awvalid_o = `SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_remapped_precut_axi_req.aw_valid;
    assign pr_alias_out_awready_o = `SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_remapped_precut_axi_resp.aw_ready;
    assign pr_alias_out_awaddr_o  = `SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_remapped_precut_axi_req.aw.addr[55:0];
    assign pr_alias_out_awcache_o = `SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_remapped_precut_axi_req.aw.cache;
    assign pr_alias_out_awprot_o = `SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_remapped_precut_axi_req.aw.prot;
    assign pr_alias_out_arvalid_o = `SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_remapped_precut_axi_req.ar_valid;
    assign pr_alias_out_arready_o = `SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_remapped_precut_axi_resp.ar_ready;
    assign pr_alias_out_araddr_o  = `SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_remapped_precut_axi_req.ar.addr[55:0];
    assign pr_alias_out_arcache_o = `SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_remapped_precut_axi_req.ar.cache;
    assign pr_alias_out_arprot_o = `SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_remapped_precut_axi_req.ar.prot;
    // PR-SRAM: the SRAM macro request (wrapper net u_dut.sep_sram_req) and response.
    assign pr_sram_req_o = u_dut.sep_sram_req.req;
    assign pr_sram_gnt_o = u_dut.sep_sram_rsp.gnt;
    assign pr_sram_addr_o = u_dut.sep_sram_req.addr;
    assign pr_sram_we_o = u_dut.sep_sram_req.wenable;
    assign pr_sram_wdata_o = u_dut.sep_sram_req.wdata;
    assign pr_sram_strb_o = u_dut.sep_sram_req.strb;
    assign pr_sram_rvalid_o = u_dut.sep_sram_rsp.rvalid;
    assign pr_sram_rdata_o = u_dut.sep_sram_rsp.rdata;
    // PR-ROM: the boot ROM macro request (wrapper net u_dut.sep_boot_rom_req) and response.
    assign pr_rom_req_o = u_dut.sep_boot_rom_req.req;
    assign pr_rom_gnt_o = u_dut.sep_boot_rom_rsp.gnt;
    assign pr_rom_addr_o = u_dut.sep_boot_rom_req.addr;
    assign pr_rom_we_o = u_dut.sep_boot_rom_req.wenable;
    assign pr_rom_wdata_o = u_dut.sep_boot_rom_req.wdata;
    assign pr_rom_strb_o = u_dut.sep_boot_rom_req.strb;
    assign pr_rom_rvalid_o = u_dut.sep_boot_rom_rsp.rvalid;
    assign pr_rom_rdata_o = u_dut.sep_boot_rom_rsp.rdata;
    // PR-ROM macro side: the request after the ROM interface shim and the read data.
    assign pr_rom_macro_req_o   = `SEP_IPI.rom_macro_req;
    assign pr_rom_macro_addr_o  = `SEP_IPI.rom_macro_addr;
    assign pr_rom_macro_rdata_o = `SEP_IPI.rom_macro_rdata;
    // PR-TCM: the ICCM and DCCM macro request and response (wrapper nets
    // u_dut.sep_cpu_tcm_req and u_dut.sep_cpu_tcm_rsp), bank 0 in the low bits.
    assign pr_tcm_iccm_clken_o = u_dut.sep_cpu_tcm_req.iccm_clken;
    assign pr_tcm_iccm_wren_o  = u_dut.sep_cpu_tcm_req.iccm_wren_bank;
    assign pr_tcm_iccm_addr_o  = u_dut.sep_cpu_tcm_req.iccm_addr_bank;
    assign pr_tcm_iccm_wdata_o = u_dut.sep_cpu_tcm_req.iccm_bank_wr_data;
    assign pr_tcm_iccm_wecc_o  = u_dut.sep_cpu_tcm_req.iccm_bank_wr_ecc;
    assign pr_tcm_iccm_rdata_o = u_dut.sep_cpu_tcm_rsp.iccm_bank_dout;
    assign pr_tcm_iccm_recc_o  = u_dut.sep_cpu_tcm_rsp.iccm_bank_ecc;
    assign pr_tcm_dccm_clken_o = u_dut.sep_cpu_tcm_req.dccm_clken;
    assign pr_tcm_dccm_wren_o  = u_dut.sep_cpu_tcm_req.dccm_wren_bank;
    assign pr_tcm_dccm_addr_o  = u_dut.sep_cpu_tcm_req.dccm_addr_bank;
    assign pr_tcm_dccm_wdata_o = u_dut.sep_cpu_tcm_req.dccm_wr_data_bank;
    assign pr_tcm_dccm_wecc_o  = u_dut.sep_cpu_tcm_req.dccm_wr_ecc_bank;
    assign pr_tcm_dccm_rdata_o = u_dut.sep_cpu_tcm_rsp.dccm_bank_dout;
    assign pr_tcm_dccm_recc_o  = u_dut.sep_cpu_tcm_rsp.dccm_bank_ecc;
    // PR-IFU: the IFU request before the IFU demux and its response; the CPU
    // stub has no IFU.
`ifndef SEP_CPU_STUB
    assign pr_ifu_arvalid_o = `SEP_CORE.u_sep_cpu.ifu_axi_req.ar_valid;
    assign pr_ifu_arready_o = `SEP_CORE.u_sep_cpu.ifu_axi_resp.ar_ready;
    assign pr_ifu_araddr_o = `SEP_CORE.u_sep_cpu.ifu_axi_req.ar.addr;
    assign pr_ifu_arid_o = `SEP_CORE.u_sep_cpu.ifu_axi_req.ar.id;
    assign pr_ifu_arlen_o = `SEP_CORE.u_sep_cpu.ifu_axi_req.ar.len;
    assign pr_ifu_arsize_o = `SEP_CORE.u_sep_cpu.ifu_axi_req.ar.size;
    assign pr_ifu_rvalid_o = `SEP_CORE.u_sep_cpu.ifu_axi_resp.r_valid;
    assign pr_ifu_rready_o = `SEP_CORE.u_sep_cpu.ifu_axi_req.r_ready;
    assign pr_ifu_rresp_o = `SEP_CORE.u_sep_cpu.ifu_axi_resp.r.resp;
    assign pr_ifu_rid_o = `SEP_CORE.u_sep_cpu.ifu_axi_resp.r.id;
    assign pr_ifu_rlast_o = `SEP_CORE.u_sep_cpu.ifu_axi_resp.r.last;
`else
    assign pr_ifu_arvalid_o = 1'b0;
    assign pr_ifu_arready_o = 1'b0;
    assign pr_ifu_araddr_o = '0;
    assign pr_ifu_arid_o = '0;
    assign pr_ifu_arlen_o = '0;
    assign pr_ifu_arsize_o = '0;
    assign pr_ifu_rvalid_o = 1'b0;
    assign pr_ifu_rready_o = 1'b0;
    assign pr_ifu_rresp_o = '0;
    assign pr_ifu_rid_o = '0;
    assign pr_ifu_rlast_o = '0;
`endif
    // PR-IFU-XBAR: the IFU demux port to the local crossbar and its response;
    // the CPU stub has no IFU.
`ifndef SEP_CPU_STUB
    assign pr_ifu_xbar_arvalid_o = `SEP_CORE.ifu_sram_axi_req.ar_valid;
    assign pr_ifu_xbar_arready_o = `SEP_CORE.ifu_sram_axi_resp.ar_ready;
    assign pr_ifu_xbar_araddr_o = `SEP_CORE.ifu_sram_axi_req.ar.addr;
    assign pr_ifu_xbar_arid_o = `SEP_CORE.ifu_sram_axi_req.ar.id;
    assign pr_ifu_xbar_arlen_o = `SEP_CORE.ifu_sram_axi_req.ar.len;
    assign pr_ifu_xbar_arsize_o = `SEP_CORE.ifu_sram_axi_req.ar.size;
    assign pr_ifu_xbar_rvalid_o = `SEP_CORE.ifu_sram_axi_resp.r_valid;
    assign pr_ifu_xbar_rready_o = `SEP_CORE.ifu_sram_axi_req.r_ready;
    assign pr_ifu_xbar_rresp_o = `SEP_CORE.ifu_sram_axi_resp.r.resp;
    assign pr_ifu_xbar_rid_o = `SEP_CORE.ifu_sram_axi_resp.r.id;
    assign pr_ifu_xbar_rlast_o = `SEP_CORE.ifu_sram_axi_resp.r.last;
`else
    assign pr_ifu_xbar_arvalid_o = 1'b0;
    assign pr_ifu_xbar_arready_o = 1'b0;
    assign pr_ifu_xbar_araddr_o = '0;
    assign pr_ifu_xbar_arid_o = '0;
    assign pr_ifu_xbar_arlen_o = '0;
    assign pr_ifu_xbar_arsize_o = '0;
    assign pr_ifu_xbar_rvalid_o = 1'b0;
    assign pr_ifu_xbar_rready_o = 1'b0;
    assign pr_ifu_xbar_rresp_o = '0;
    assign pr_ifu_xbar_rid_o = '0;
    assign pr_ifu_xbar_rlast_o = '0;
`endif
    // PR-LSU-ROM: the LSU demux port to the ROM mux.
    assign pr_lsu_rom_awvalid_o = `SEP_CORE.lsu_rom_axi_req.aw_valid;
    assign pr_lsu_rom_awready_o = `SEP_CORE.lsu_rom_axi_resp.aw_ready;
    assign pr_lsu_rom_awaddr_o = `SEP_CORE.lsu_rom_axi_req.aw.addr;
    assign pr_lsu_rom_awid_o = `SEP_CORE.lsu_rom_axi_req.aw.id;
    assign pr_lsu_rom_awlen_o = `SEP_CORE.lsu_rom_axi_req.aw.len;
    assign pr_lsu_rom_awsize_o = `SEP_CORE.lsu_rom_axi_req.aw.size;
    assign pr_lsu_rom_arvalid_o = `SEP_CORE.lsu_rom_axi_req.ar_valid;
    assign pr_lsu_rom_arready_o = `SEP_CORE.lsu_rom_axi_resp.ar_ready;
    assign pr_lsu_rom_araddr_o = `SEP_CORE.lsu_rom_axi_req.ar.addr;
    assign pr_lsu_rom_arid_o = `SEP_CORE.lsu_rom_axi_req.ar.id;
    assign pr_lsu_rom_arlen_o = `SEP_CORE.lsu_rom_axi_req.ar.len;
    assign pr_lsu_rom_arsize_o = `SEP_CORE.lsu_rom_axi_req.ar.size;
    assign pr_lsu_rom_wvalid_o = `SEP_CORE.lsu_rom_axi_req.w_valid;
    assign pr_lsu_rom_wready_o = `SEP_CORE.lsu_rom_axi_resp.w_ready;
    assign pr_lsu_rom_wstrb_o = `SEP_CORE.lsu_rom_axi_req.w.strb;
    assign pr_lsu_rom_wlast_o = `SEP_CORE.lsu_rom_axi_req.w.last;
    assign pr_lsu_rom_bvalid_o = `SEP_CORE.lsu_rom_axi_resp.b_valid;
    assign pr_lsu_rom_bready_o = `SEP_CORE.lsu_rom_axi_req.b_ready;
    assign pr_lsu_rom_bresp_o = `SEP_CORE.lsu_rom_axi_resp.b.resp;
    assign pr_lsu_rom_bid_o = `SEP_CORE.lsu_rom_axi_resp.b.id;
    assign pr_lsu_rom_rvalid_o = `SEP_CORE.lsu_rom_axi_resp.r_valid;
    assign pr_lsu_rom_rready_o = `SEP_CORE.lsu_rom_axi_req.r_ready;
    assign pr_lsu_rom_rresp_o = `SEP_CORE.lsu_rom_axi_resp.r.resp;
    assign pr_lsu_rom_rid_o = `SEP_CORE.lsu_rom_axi_resp.r.id;
    assign pr_lsu_rom_rlast_o = `SEP_CORE.lsu_rom_axi_resp.r.last;
    // PR-LSU-XBAR: the LSU demux port to the local crossbar.
    assign pr_lsu_xbar_awvalid_o = `SEP_CORE.lsu_xbar_axi_req.aw_valid;
    assign pr_lsu_xbar_awready_o = `SEP_CORE.lsu_xbar_axi_resp.aw_ready;
    assign pr_lsu_xbar_awaddr_o = `SEP_CORE.lsu_xbar_axi_req.aw.addr;
    assign pr_lsu_xbar_awid_o = `SEP_CORE.lsu_xbar_axi_req.aw.id;
    assign pr_lsu_xbar_awlen_o = `SEP_CORE.lsu_xbar_axi_req.aw.len;
    assign pr_lsu_xbar_awsize_o = `SEP_CORE.lsu_xbar_axi_req.aw.size;
    assign pr_lsu_xbar_arvalid_o = `SEP_CORE.lsu_xbar_axi_req.ar_valid;
    assign pr_lsu_xbar_arready_o = `SEP_CORE.lsu_xbar_axi_resp.ar_ready;
    assign pr_lsu_xbar_araddr_o = `SEP_CORE.lsu_xbar_axi_req.ar.addr;
    assign pr_lsu_xbar_arid_o = `SEP_CORE.lsu_xbar_axi_req.ar.id;
    assign pr_lsu_xbar_arlen_o = `SEP_CORE.lsu_xbar_axi_req.ar.len;
    assign pr_lsu_xbar_arsize_o = `SEP_CORE.lsu_xbar_axi_req.ar.size;
    assign pr_lsu_xbar_wvalid_o = `SEP_CORE.lsu_xbar_axi_req.w_valid;
    assign pr_lsu_xbar_wready_o = `SEP_CORE.lsu_xbar_axi_resp.w_ready;
    assign pr_lsu_xbar_wstrb_o = `SEP_CORE.lsu_xbar_axi_req.w.strb;
    assign pr_lsu_xbar_wlast_o = `SEP_CORE.lsu_xbar_axi_req.w.last;
    assign pr_lsu_xbar_bvalid_o = `SEP_CORE.lsu_xbar_axi_resp.b_valid;
    assign pr_lsu_xbar_bready_o = `SEP_CORE.lsu_xbar_axi_req.b_ready;
    assign pr_lsu_xbar_bresp_o = `SEP_CORE.lsu_xbar_axi_resp.b.resp;
    assign pr_lsu_xbar_bid_o = `SEP_CORE.lsu_xbar_axi_resp.b.id;
    assign pr_lsu_xbar_rvalid_o = `SEP_CORE.lsu_xbar_axi_resp.r_valid;
    assign pr_lsu_xbar_rready_o = `SEP_CORE.lsu_xbar_axi_req.r_ready;
    assign pr_lsu_xbar_rresp_o = `SEP_CORE.lsu_xbar_axi_resp.r.resp;
    assign pr_lsu_xbar_rid_o = `SEP_CORE.lsu_xbar_axi_resp.r.id;
    assign pr_lsu_xbar_rlast_o = `SEP_CORE.lsu_xbar_axi_resp.r.last;
    // PR-XBAR-TCM: the crossbar cpu_tcm target (contract name xbar_tcm_req).
    assign pr_xbar_tcm_awvalid_o = `SEP_CORE.cpu_tcm_axi_req.aw_valid;
    assign pr_xbar_tcm_awready_o = `SEP_CORE.cpu_tcm_axi_resp.aw_ready;
    assign pr_xbar_tcm_awaddr_o = `SEP_CORE.cpu_tcm_axi_req.aw.addr;
    assign pr_xbar_tcm_awid_o = `SEP_CORE.cpu_tcm_axi_req.aw.id;
    assign pr_xbar_tcm_awlen_o = `SEP_CORE.cpu_tcm_axi_req.aw.len;
    assign pr_xbar_tcm_awsize_o = `SEP_CORE.cpu_tcm_axi_req.aw.size;
    assign pr_xbar_tcm_arvalid_o = `SEP_CORE.cpu_tcm_axi_req.ar_valid;
    assign pr_xbar_tcm_arready_o = `SEP_CORE.cpu_tcm_axi_resp.ar_ready;
    assign pr_xbar_tcm_araddr_o = `SEP_CORE.cpu_tcm_axi_req.ar.addr;
    assign pr_xbar_tcm_arid_o = `SEP_CORE.cpu_tcm_axi_req.ar.id;
    assign pr_xbar_tcm_arlen_o = `SEP_CORE.cpu_tcm_axi_req.ar.len;
    assign pr_xbar_tcm_arsize_o = `SEP_CORE.cpu_tcm_axi_req.ar.size;
    assign pr_xbar_tcm_wvalid_o = `SEP_CORE.cpu_tcm_axi_req.w_valid;
    assign pr_xbar_tcm_wready_o = `SEP_CORE.cpu_tcm_axi_resp.w_ready;
    assign pr_xbar_tcm_wstrb_o = `SEP_CORE.cpu_tcm_axi_req.w.strb;
    assign pr_xbar_tcm_wlast_o = `SEP_CORE.cpu_tcm_axi_req.w.last;
    assign pr_xbar_tcm_bvalid_o = `SEP_CORE.cpu_tcm_axi_resp.b_valid;
    assign pr_xbar_tcm_bready_o = `SEP_CORE.cpu_tcm_axi_req.b_ready;
    assign pr_xbar_tcm_bresp_o = `SEP_CORE.cpu_tcm_axi_resp.b.resp;
    assign pr_xbar_tcm_bid_o = `SEP_CORE.cpu_tcm_axi_resp.b.id;
    assign pr_xbar_tcm_rvalid_o = `SEP_CORE.cpu_tcm_axi_resp.r_valid;
    assign pr_xbar_tcm_rready_o = `SEP_CORE.cpu_tcm_axi_req.r_ready;
    assign pr_xbar_tcm_rresp_o = `SEP_CORE.cpu_tcm_axi_resp.r.resp;
    assign pr_xbar_tcm_rid_o = `SEP_CORE.cpu_tcm_axi_resp.r.id;
    assign pr_xbar_tcm_rlast_o = `SEP_CORE.cpu_tcm_axi_resp.r.last;
    // PR-DBG-SB: the debug-module system-bus master after its alias remap.
    assign pr_dbg_sb_awvalid_o = `SEP_CORE.dbg_axi_req.aw_valid;
    assign pr_dbg_sb_awready_o = `SEP_CORE.dbg_axi_resp.aw_ready;
    assign pr_dbg_sb_awaddr_o = `SEP_CORE.dbg_axi_req.aw.addr;
    assign pr_dbg_sb_awid_o = `SEP_CORE.dbg_axi_req.aw.id;
    assign pr_dbg_sb_awlen_o = `SEP_CORE.dbg_axi_req.aw.len;
    assign pr_dbg_sb_awsize_o = `SEP_CORE.dbg_axi_req.aw.size;
    assign pr_dbg_sb_arvalid_o = `SEP_CORE.dbg_axi_req.ar_valid;
    assign pr_dbg_sb_arready_o = `SEP_CORE.dbg_axi_resp.ar_ready;
    assign pr_dbg_sb_araddr_o = `SEP_CORE.dbg_axi_req.ar.addr;
    assign pr_dbg_sb_arid_o = `SEP_CORE.dbg_axi_req.ar.id;
    assign pr_dbg_sb_arlen_o = `SEP_CORE.dbg_axi_req.ar.len;
    assign pr_dbg_sb_arsize_o = `SEP_CORE.dbg_axi_req.ar.size;
    assign pr_dbg_sb_wvalid_o = `SEP_CORE.dbg_axi_req.w_valid;
    assign pr_dbg_sb_wready_o = `SEP_CORE.dbg_axi_resp.w_ready;
    assign pr_dbg_sb_wdata_o = `SEP_CORE.dbg_axi_req.w.data;
    assign pr_dbg_sb_wstrb_o = `SEP_CORE.dbg_axi_req.w.strb;
    assign pr_dbg_sb_wlast_o = `SEP_CORE.dbg_axi_req.w.last;
    assign pr_dbg_sb_bvalid_o = `SEP_CORE.dbg_axi_resp.b_valid;
    assign pr_dbg_sb_bready_o = `SEP_CORE.dbg_axi_req.b_ready;
    assign pr_dbg_sb_bresp_o = `SEP_CORE.dbg_axi_resp.b.resp;
    assign pr_dbg_sb_bid_o = `SEP_CORE.dbg_axi_resp.b.id;
    assign pr_dbg_sb_rvalid_o = `SEP_CORE.dbg_axi_resp.r_valid;
    assign pr_dbg_sb_rready_o = `SEP_CORE.dbg_axi_req.r_ready;
    assign pr_dbg_sb_rdata_o = `SEP_CORE.dbg_axi_resp.r.data;
    assign pr_dbg_sb_rresp_o = `SEP_CORE.dbg_axi_resp.r.resp;
    assign pr_dbg_sb_rid_o = `SEP_CORE.dbg_axi_resp.r.id;
    assign pr_dbg_sb_rlast_o = `SEP_CORE.dbg_axi_resp.r.last;
    // PR-DBG-IN / PR-DBG-OUT: the debug-module system-bus request at the input
    // and output of u_dbg_local_alias_remap. The CPU stub has no debug module.
`ifndef SEP_CPU_STUB
    assign pr_dbg_in_awvalid_o = `SEP_CORE.u_sep_cpu.dbg_axi_req_raw.aw_valid;
    assign pr_dbg_in_awready_o = `SEP_CORE.u_sep_cpu.dbg_axi_resp_raw.aw_ready;
    assign pr_dbg_in_awaddr_o = `SEP_CORE.u_sep_cpu.dbg_axi_req_raw.aw.addr;
    assign pr_dbg_in_arvalid_o = `SEP_CORE.u_sep_cpu.dbg_axi_req_raw.ar_valid;
    assign pr_dbg_in_arready_o = `SEP_CORE.u_sep_cpu.dbg_axi_resp_raw.ar_ready;
    assign pr_dbg_in_araddr_o = `SEP_CORE.u_sep_cpu.dbg_axi_req_raw.ar.addr;
    assign pr_dbg_out_awvalid_o = `SEP_CORE.u_sep_cpu.dbg_axi_req_o.aw_valid;
    assign pr_dbg_out_awready_o = `SEP_CORE.u_sep_cpu.dbg_axi_resp_i.aw_ready;
    assign pr_dbg_out_awaddr_o = `SEP_CORE.u_sep_cpu.dbg_axi_req_o.aw.addr;
    assign pr_dbg_out_arvalid_o = `SEP_CORE.u_sep_cpu.dbg_axi_req_o.ar_valid;
    assign pr_dbg_out_arready_o = `SEP_CORE.u_sep_cpu.dbg_axi_resp_i.ar_ready;
    assign pr_dbg_out_araddr_o = `SEP_CORE.u_sep_cpu.dbg_axi_req_o.ar.addr;
`else
    assign pr_dbg_in_awvalid_o = 1'b0;
    assign pr_dbg_in_awready_o = 1'b0;
    assign pr_dbg_in_awaddr_o = '0;
    assign pr_dbg_in_arvalid_o = 1'b0;
    assign pr_dbg_in_arready_o = 1'b0;
    assign pr_dbg_in_araddr_o = '0;
    assign pr_dbg_out_awvalid_o = 1'b0;
    assign pr_dbg_out_awready_o = 1'b0;
    assign pr_dbg_out_awaddr_o = '0;
    assign pr_dbg_out_arvalid_o = 1'b0;
    assign pr_dbg_out_arready_o = 1'b0;
    assign pr_dbg_out_araddr_o = '0;
`endif

    // Read-only XMRs observe the manifest at SRAM word 0 and the decrypted
    // payload at byte offset 0x1000. Firmware owns the SRAM AXI frontdoor during
    // boot, and these memory-array reads sit outside the ready/valid cones.
    assign sram_word0_probe_o = `SEP_IPI.u_sep_sram.gen_ram_inst[0].u_mem.mem['h000];
`define SRAM_PL(i) \
    assign sram_payload_probe_o[64*(i) +: 64] = \
        `SEP_IPI.u_sep_sram.gen_ram_inst[0].u_mem.mem['h200 + (i)]
    `SRAM_PL(0); `SRAM_PL(1); `SRAM_PL(2);
    `SRAM_PL(3); `SRAM_PL(4); `SRAM_PL(5);
`undef SRAM_PL

    // Read-only XMR of the ML-KEM seed Z the Adams Bridge engine holds. See the
    // port comment in sep_tb_signal_list.svh.
`ifdef SEP_ABR_EN
    assign abr_mlkem_seed_z_probe_o =
        `SEP_CORE.u_sep_crypto.u_sep_crypto_abr_wrapper_s3c_scan.u_abr_top.abr_ctrl_inst.abr_scratch_reg.mlkem_enc.seed_z;
`else
    assign abr_mlkem_seed_z_probe_o = '0;
`endif

    // ------------------------------------------------------------------
    // Warm-reset handler seed: +sep_cold_scratch7=<hex32>
    // ------------------------------------------------------------------
    // A one-shot deposit seeds COLD Scratch 7 after both resets release and
    // before the CPU fetches. The CPU owns the system-CSR AXI frontdoor during
    // firmware boot, so the testbench cannot perform this timed write through an
    // independent master. The leaf storage sits outside the AXI ready/valid
    // combinational cones. A deposit allows later ROM writes to remain visible.
    //
    // The two simulators need different deposit mechanics on this leaf, and
    // neither mechanism compiles on the other tool:
    //
    //  * VCS rejects a procedural assignment here (Error-[ICPD]): the field
    //    storage is written by an always_ff in sep_scratch_reg.sv, and the LRM
    //    allows such a variable only one procedural driver. A force is not a
    //    procedural driver, so VCS takes the force. That always_ff writes the
    //    field only on reset or a decoded software write, so the value stands
    //    after release until ROM writes it.
    //  * Verilator cannot force an element of an unpacked array member
    //    (V3Force "opaque force path selector ARRAYSEL"), and the failure lands
    //    on the SCRATCH_COLD probe assigns above, not on the force itself. It
    //    does not implement the single-driver rule, so the assignment stands.
    logic [31:0] cold_scratch7_seed;
    initial begin : cold_scratch7_seed_deposit
        if ($value$plusargs("sep_cold_scratch7=%h", cold_scratch7_seed)) begin
            wait (rst_ni === 1'b1);
            wait (sep_cpu_reset_n_o === 1'b1);
            repeat (4) @(posedge clk_i);
`ifdef VERILATOR
            `SEP_CORE.u_sep_system_peripherals.u_sep_system_csr
                .u_sep_scratch_reg_cold.field_storage.SCRATCH[7].data.value = cold_scratch7_seed;
`else
            force `SEP_CORE.u_sep_system_peripherals.u_sep_system_csr
                .u_sep_scratch_reg_cold.field_storage.SCRATCH[7].data.value = cold_scratch7_seed;
            @(posedge clk_i);
            release `SEP_CORE.u_sep_system_peripherals.u_sep_system_csr
                .u_sep_scratch_reg_cold.field_storage.SCRATCH[7].data.value;
`endif
            $display("[tb] cold_scratch[7] seeded 0x%08x (+sep_cold_scratch7)",
                     cold_scratch7_seed);
        end
    end

    // ------------------------------------------------------------------
    // LC differential-integrity error inject.
    // ------------------------------------------------------------------
    // No legal OTP image can present a broken {~raw, raw} LC_STATE pair: the
    // sense FSM regenerates the pair from the raw nibble. The specification's
    // fail-closed feat_ctrl=0 path therefore has no frontdoor stimulus.
    // When lc_sigint_inject_i=1, force both rails of the LCC decoder input to 0
    // so prim_diff_decode_multi asserts sigint (XNOR of equal rails). The
    // software-visible LC_STATE shadow is not touched -- only the decoder
    // input -- so the stitch test can still value-check the legal pair.
    // Re-issue every clock (Verilator snapshots a force RHS). Release when the
    // port drops so the legal pair returns. Default 0; outside AXI cones.
`define LCC_DEC_DATA \
    `SEP_CORE.u_sep_crypto.u_sep_lifecycle_ctrl.u_lc_state_dec.data_i
    always @(posedge clk_i) begin
        if (lc_sigint_inject_i === 1'b1) begin
            force `LCC_DEC_DATA = '0;
        end else begin
            release `LCC_DEC_DATA;
        end
    end
`undef LCC_DEC_DATA

    // ------------------------------------------------------------------
    // Token-comparator redundancy fault inject.
    // ------------------------------------------------------------------
    // The three digest comparators see the same inputs. A legal token write
    // can only produce a unanimous legal pair (match or mismatch). Collapse
    // and two-instance disagreement have no frontdoor. Common-mode invert
    // of every instance is the documented coverage hole: the detector does
    // not fire when all three flip the same way. Force the gated instance
    // rails of the selected token wrapper; TOKEN_MATCH_FAULT and the
    // match-status CSR stay frontdoor-read. Default 0; released after the
    // check; outside the AXI ready/valid cones. Re-issue every clock
    // (Verilator snapshots a force RHS).
`define TOKEN_PROC \
    `SEP_CORE.u_sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller \
        .gen_mmr_reg.u_efuse_token_processing
`define CMP_SIP  `TOKEN_PROC.u_triple_redundant_comparator_rma_sip_token
`define CMP_CHIP `TOKEN_PROC.u_triple_redundant_comparator_rma_chiplet_token
`define CMP_SEC  `TOKEN_PROC.u_triple_redundant_comparator_sec_disable_token
`define DIGEST_SIP `TOKEN_PROC.u_sha256_rma_sip_token
    // token_cmp_fault_copy_i picks the copy k of a collapse or disagree
    // pattern as a one-hot bit: copy 0 when the select is 0, undriven or
    // unknown, copy 1 for 2'b01, copy 2 for 2'b10. 2'b11 forces nothing. At
    // copy 0 the two patterns force 110/000 and 110/001. The common-mode
    // patterns ignore the select.
    logic [2:0] token_cmp_copy_bit;
    logic       token_cmp_copy_ok;
    always_comb begin
        token_cmp_copy_bit = 3'b001;
        token_cmp_copy_ok = 1'b1;
        if (token_cmp_fault_copy_i === 2'b01) begin
            token_cmp_copy_bit = 3'b010;
        end else if (token_cmp_fault_copy_i === 2'b10) begin
            token_cmp_copy_bit = 3'b100;
        end else if (token_cmp_fault_copy_i === 2'b11) begin
            token_cmp_copy_ok = 1'b0;
        end
    end
    logic [2:0] token_cmp_force_p, token_cmp_force_n;
    logic       token_cmp_do_force;
    always_comb begin
        token_cmp_force_p = 3'b000;
        token_cmp_force_n = 3'b000;
        token_cmp_do_force = 1'b0;
        if (token_cmp_fault_inject_i === 3'b001) begin
            token_cmp_force_p = 3'b111 & ~token_cmp_copy_bit;
            token_cmp_force_n = 3'b000;
            token_cmp_do_force = token_cmp_copy_ok;
        end else if (token_cmp_fault_inject_i === 3'b010) begin
            token_cmp_force_p = 3'b111 & ~token_cmp_copy_bit;
            token_cmp_force_n = token_cmp_copy_bit;
            token_cmp_do_force = token_cmp_copy_ok;
        end else if (token_cmp_fault_inject_i === 3'b011) begin
            token_cmp_force_p = 3'b000;
            token_cmp_force_n = 3'b111;
            token_cmp_do_force = 1'b1;
        end else if (token_cmp_fault_inject_i === 3'b100) begin
            token_cmp_force_p = 3'b111;
            token_cmp_force_n = 3'b000;
            token_cmp_do_force = 1'b1;
        end
    end
    // The forces and releases run on the falling edge of clk_i. Every DUT flop
    // samples on the rising edge, and match_p and match_n are separate forced
    // variables, so a change of both rails at one edge passes through a mixed
    // state. On the rising edge the sticky TOKEN_MATCH_FAULT flop can sample
    // that collapsed pair. Half a clock later both rails have their final
    // value at the next rising edge, so only the injected pattern itself
    // reaches a DUT flop.
    // Drain clock: on the first falling edge after the inject drops, the rails
    // of the comparator that was forced are forced to the value of their own
    // driver ({3{compute_comparison_vld_i}} & match_*_raw), and released on
    // the next falling edge. A Verilator release of a variable keeps the forced
    // value until the driver changes, and match_p and match_n change on
    // different driver inputs, so a release straight from an injected pattern
    // can leave one rail at the injected value. With the drain the value kept
    // at the release is the driver value. A cell releases the inject (select
    // 0, pattern off) before it selects another comparator. No declaration
    // initializers (see the SMC fuse-sense note): the first falling edge sets
    // both variables, and until then the X drain flag selects the release arm.
    logic       token_cmp_drain_q;
    logic [1:0] token_cmp_drain_sel_q;
    always @(negedge clk_i) begin
        if (token_cmp_do_force && token_cmp_fault_sel_i === 2'b00) begin
            force `CMP_SIP.match_p = token_cmp_force_p;
            force `CMP_SIP.match_n = token_cmp_force_n;
            release `CMP_CHIP.match_p;
            release `CMP_CHIP.match_n;
            release `CMP_SEC.match_p;
            release `CMP_SEC.match_n;
        end else if (token_cmp_do_force && token_cmp_fault_sel_i === 2'b01) begin
            release `CMP_SIP.match_p;
            release `CMP_SIP.match_n;
            force `CMP_CHIP.match_p = token_cmp_force_p;
            force `CMP_CHIP.match_n = token_cmp_force_n;
            release `CMP_SEC.match_p;
            release `CMP_SEC.match_n;
        end else if (token_cmp_do_force && token_cmp_fault_sel_i === 2'b10) begin
            release `CMP_SIP.match_p;
            release `CMP_SIP.match_n;
            release `CMP_CHIP.match_p;
            release `CMP_CHIP.match_n;
            force `CMP_SEC.match_p = token_cmp_force_p;
            force `CMP_SEC.match_n = token_cmp_force_n;
        end else if (token_cmp_drain_q && token_cmp_drain_sel_q == 2'b00) begin
            force `CMP_SIP.match_p = {3{`CMP_SIP.compute_comparison_vld_i}} & `CMP_SIP.match_p_raw;
            force `CMP_SIP.match_n = {3{`CMP_SIP.compute_comparison_vld_i}} & `CMP_SIP.match_n_raw;
        end else if (token_cmp_drain_q && token_cmp_drain_sel_q == 2'b01) begin
            force `CMP_CHIP.match_p =
                {3{`CMP_CHIP.compute_comparison_vld_i}} & `CMP_CHIP.match_p_raw;
            force `CMP_CHIP.match_n =
                {3{`CMP_CHIP.compute_comparison_vld_i}} & `CMP_CHIP.match_n_raw;
        end else if (token_cmp_drain_q && token_cmp_drain_sel_q == 2'b10) begin
            force `CMP_SEC.match_p = {3{`CMP_SEC.compute_comparison_vld_i}} & `CMP_SEC.match_p_raw;
            force `CMP_SEC.match_n = {3{`CMP_SEC.compute_comparison_vld_i}} & `CMP_SEC.match_n_raw;
        end else begin
            release `CMP_SIP.match_p;
            release `CMP_SIP.match_n;
            release `CMP_CHIP.match_p;
            release `CMP_CHIP.match_n;
            release `CMP_SEC.match_p;
            release `CMP_SEC.match_n;
        end
        token_cmp_drain_q <= token_cmp_do_force && (token_cmp_fault_sel_i !== 2'b11);
        token_cmp_drain_sel_q <= token_cmp_fault_sel_i;
    end
    // The production DFT input is tied low at this TB boundary. Use the same
    // clock-reissued force/release convention as the comparator hook above to
    // reach the digest latch's scan-freeze gate. Token commands and
    // digest capture remain frontdoor; only this otherwise unreachable input
    // is forced.
    assign token_digest_sticky_o = `DIGEST_SIP.sha_digest_sticky_n0_scan;
    assign token_digest_valid_o = `DIGEST_SIP.digest_vld_sticky_n0_scan;
    assign token_digest_test_en_o = `DIGEST_SIP.test_en_i;
    assign token_digest_latch_en_pre_o = `DIGEST_SIP.digest_latch_en_pre;
    assign token_digest_valid_en_pre_o = `DIGEST_SIP.vld_latch_en_pre;
    assign token_digest_latch_en_o = `DIGEST_SIP.digest_latch_en;
    assign token_digest_valid_en_o = `DIGEST_SIP.vld_latch_en;
    always @(posedge clk_i) begin
        if (token_digest_test_en_inject_i === 1'b1) begin
            force `DIGEST_SIP.test_en_i = 1'b1;
        end else begin
            release `DIGEST_SIP.test_en_i;
        end
    end
    // Gated comparator rails after the force point above (read-only): bit
    // 3c+k is copy k of channel c, 0 RMA_SIP, 1 RMA_CHIPLET, 2 SEC_DIS.
    assign token_cmp_match_p_o = {`CMP_SEC.match_p, `CMP_CHIP.match_p, `CMP_SIP.match_p};
    assign token_cmp_match_n_o = {`CMP_SEC.match_n, `CMP_CHIP.match_n, `CMP_SIP.match_n};
    // The 24 token word registers (read-only). They have no reset.
    assign token_sip_words_o = `TOKEN_PROC.sip_rma_token_raw_n0_scan;
    assign token_chiplet_words_o = `TOKEN_PROC.chiplet_rma_token_raw_n0_scan;
    assign token_sdis_words_o = `TOKEN_PROC.sec_disable_token_raw_n0_scan;
    // Retained digest latches of RMA_CHIPLET and SEC_DIS: read-only probes and
    // the test-enable inject of each latch. Same clock-reissued force/release
    // convention as the RMA_SIP inject above; the production DFT input is tied
    // low, so the freeze has no frontdoor. Token commands, digest capture and
    // the match registers stay frontdoor. Default 0.
`define DIGEST_CHIP `TOKEN_PROC.u_sha256_rma_chiplet_token
`define DIGEST_SEC  `TOKEN_PROC.u_sha256_sec_disable_token
    assign token_digest_chiplet_sticky_o = `DIGEST_CHIP.sha_digest_sticky_n0_scan;
    assign token_digest_chiplet_valid_o = `DIGEST_CHIP.digest_vld_sticky_n0_scan;
    assign token_digest_chiplet_test_en_o = `DIGEST_CHIP.test_en_i;
    assign token_digest_sdis_sticky_o = `DIGEST_SEC.sha_digest_sticky_n0_scan;
    assign token_digest_sdis_valid_o = `DIGEST_SEC.digest_vld_sticky_n0_scan;
    assign token_digest_sdis_test_en_o = `DIGEST_SEC.test_en_i;
    always @(posedge clk_i) begin
        if (token_digest_chiplet_test_en_inject_i === 1'b1) begin
            force `DIGEST_CHIP.test_en_i = 1'b1;
        end else begin
            release `DIGEST_CHIP.test_en_i;
        end
        if (token_digest_sdis_test_en_inject_i === 1'b1) begin
            force `DIGEST_SEC.test_en_i = 1'b1;
        end else begin
            release `DIGEST_SEC.test_en_i;
        end
    end
`undef DIGEST_CHIP
`undef DIGEST_SEC
    // ------------------------------------------------------------------
    // eFuse read/program FSM fail-closed probes and one-cycle illegal-state
    // inject. Same clock-reissued force/release convention as the digest hook
    // above.
    // ------------------------------------------------------------------
`define EFUSE_CTRL `SEP_CORE.u_sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller
`define EFUSE_RD `EFUSE_CTRL.u_efuse_read_interface
`define EFUSE_PG `EFUSE_CTRL.u_efuse_program_interface
    assign efuse_read_state_o = `EFUSE_RD.read_state_q;
    assign efuse_program_state_o = `EFUSE_PG.program_state_q;
    assign efuse_read_error_o = `EFUSE_RD.read_error_o;
    assign efuse_read_done_o = `EFUSE_RD.read_done_o;
    assign efuse_read_busy_o = `EFUSE_RD.read_busy_o;
    assign efuse_read_back_data_o = `EFUSE_RD.read_back_data_o;
    assign efuse_read_cmd_req_valid_o = `EFUSE_RD.fuse_command_req_o.valid;
    assign efuse_program_cmd_req_valid_o = `EFUSE_PG.fuse_command_req_o.valid;
    assign efuse_program_error_o = `EFUSE_PG.program_error_o;
    assign efuse_program_done_o = `EFUSE_PG.program_done_o;
    assign efuse_program_busy_o = `EFUSE_PG.program_busy_o;
    assign efuse_program_read_back_data_o = `EFUSE_PG.program_read_back_data_o;
    // ------------------------------------------------------------------
    // Only legal encodings of these two FSMs are 2'b01 and 2'b10, and the
    // sense and frontdoor paths can never present another, so the fail-closed
    // recovery the RTL specifies for 2'b00 and 2'b11 has no frontdoor
    // stimulus. Scope: the two state registers named below, for one cycle at
    // a time. Seeing the injected encoding on *_state_o confirms the force
    // landed; it is not fail-closed evidence. After release the recovered
    // encoding must be a legal idle/wait value (DUT-driven). Command
    // withdraw and the error/done/busy/data terms are claimed only on the
    // in-flight leg. The legal encodings 2'b01 idle and 2'b10 wait are the
    // design's state encoding in efuse_read_interface.sv and
    // efuse_program_interface.sv; this leaf grades recovery against that set
    // and injects its complement. Owner:
    // sep_efuse_illegal_state_fail_closed_test.
    //
    // The registers are enum-typed and the injected encodings are not members
    // of those enums, which is the property under test; ENUMVALUE is waived
    // for these two forces only.
    /* verilator lint_off ENUMVALUE */
    always @(posedge clk_i) begin
        if (efuse_read_state_inject_en_i === 1'b1) begin
            force `EFUSE_RD.read_state_q = efuse_read_state_inject_i;
        end else begin
            release `EFUSE_RD.read_state_q;
        end
        if (efuse_program_state_inject_en_i === 1'b1) begin
            force `EFUSE_PG.program_state_q = efuse_program_state_inject_i;
        end else begin
            release `EFUSE_PG.program_state_q;
        end
    end
    /* verilator lint_on ENUMVALUE */

    // ------------------------------------------------------------------
    // eFuse and lifecycle observation taps (read-only, no force).
    // ------------------------------------------------------------------
    // The post-guard fuse command at the sep output efuse_shim_command_req_o.
    // The request valids of the read and program interfaces above sit before
    // the guard and cannot show a refusal.
    assign efuse_shim_cmd_valid_o = `SEP_CORE.efuse_shim_command_req_o.valid;
    assign efuse_shim_cmd_command_o = `SEP_CORE.efuse_shim_command_req_o.command;
    assign efuse_shim_cmd_address_o = `SEP_CORE.efuse_shim_command_req_o.address;
    assign efuse_shim_cmd_program_data_o = `SEP_CORE.efuse_shim_command_req_o.program_data;
    assign efuse_shim_cmd_len_o = `SEP_CORE.efuse_shim_command_req_o.access_length_words;
    // The shim response at the sep input efuse_shim_command_resp_i: valid, status
    // and data, after the sense-status inject.
    assign efuse_shim_resp_valid_o = `SEP_CORE.efuse_shim_command_resp_i.valid;
    assign efuse_shim_resp_status_o = `SEP_CORE.efuse_shim_command_resp_i.status;
    assign efuse_shim_resp_data_o = `SEP_CORE.efuse_shim_command_resp_i.data;
    // The 256 bank words that SEP reaches: the bank model decodes paddr[9:0],
    // so words 256..1023 of its register block are unreachable. One assign per
    // word.
    for (genvar g = 0; g < sep_efuse_pkg::NumFuseWords; g++) begin : gen_otp_bank_probe
        assign otp_bank_probe_o[g] =
            `SEP_IPI.u_efuse_bank_model.u_efuse_bank_reg.field_storage.EFUSE_BANK_REG[g].dout.value;
    end
    // Integrity-error flag of the JTAG lifecycle filter decoder.
`define JTAG_LC_DEC `SEP_CORE.u_sep_crypto.u_sep_efuse_wrapper.u_lc_state_jtag_dec
    assign jtag_filter_lc_sigint_err_probe_o = `JTAG_LC_DEC.sigint_o;
    // The sep input jtag_id_i as the DUT receives it.
    assign jtag_id_probe_o = `SEP_CORE.jtag_id_i;

    // ------------------------------------------------------------------
    // JTAG lifecycle filter integrity inject.
    // ------------------------------------------------------------------
    // No legal OTP image presents a broken {~raw, raw} LC_STATE pair to the
    // JTAG lifecycle filter, so its fail-closed path has no frontdoor. When
    // jtag_filter_lc_sigint_inject_i=1, force both rails of the byte at the
    // filter decoder input to 0. The input is connected to an expression of
    // the shadow, so the LC_STATE shadow and the lifecycle controller decoder
    // (lc_sigint_inject_i) are not forced. Re-issue every clock (Verilator
    // snapshots a force RHS); release when the input drops. Default 0.
    always @(posedge clk_i) begin
        if (jtag_filter_lc_sigint_inject_i === 1'b1) begin
            force `JTAG_LC_DEC.data_i = '0;
        end else begin
            release `JTAG_LC_DEC.data_i;
        end
    end
`undef JTAG_LC_DEC

    // ------------------------------------------------------------------
    // eFuse sense status inject.
    // ------------------------------------------------------------------
    // A healthy bank never returns an APB error, so the sense status path has
    // no frontdoor. While efuse_sense_status_inject_i=1, during fuse sense only
    // (fuse_sense_done low), with a READ command at the post-guard port, the
    // bank model APB response to the word efuse_sense_status_word_i carries
    // pslverr=1 at the shim, and the shim copies it to the status bit of that
    // sense response.
    // The force target is the shim's read-path copy of the bank response
    // (u_efuse_interface_shim.apb_fuse_bank_resp_r, the efuse_model_otp_resp_i
    // input routed by the READ command). It is a variable of an always_comb
    // block that also drives the APB request, so the block runs again on the
    // next request change and the released pslverr takes the bank value again
    // within one clock. The bank pslverr itself has a constant driver, so a
    // released force there would keep the value 1 (Verilator release of a
    // variable) and fail every later sense word, also after rst_ni.
    // The sense streams words 0..255 from bit address 0 and the shim reads
    // byte address (bit address >> 3), so word w has paddr[9:2] == w. Program
    // read-back uses another command and frontdoor reads run after sense done,
    // so neither matches. prdata and pready are not forced. The gate is
    // evaluated at the clock edge that starts the APB access phase (psel high,
    // penable not yet high), so the force covers the whole access phase.
    // Re-issued every clock and released when the gate drops. Default 0.
`define EFUSE_OTP_REQ  `SEP_IPI.efuse_model_otp_req
`define EFUSE_SHIM_RESP_R `SEP_IPI.u_efuse_interface_shim.apb_fuse_bank_resp_r
    wire efuse_sense_status_hit =
        (efuse_sense_status_inject_i === 1'b1) &&
        (`EFUSE_CTRL.fuse_sense_done === 1'b0) &&
        (`SEP_CORE.efuse_shim_command_req_o.valid === 1'b1) &&
        (`SEP_CORE.efuse_shim_command_req_o.command === efuse_pkg::FUSE_COMMAND_READ) &&
        (`EFUSE_OTP_REQ.psel === 1'b1) &&
        (`EFUSE_OTP_REQ.paddr[9:2] === efuse_sense_status_word_i);
    always @(posedge clk_i) begin
        if (efuse_sense_status_hit) begin
            force `EFUSE_SHIM_RESP_R.pslverr = 1'b1;
        end else begin
            release `EFUSE_SHIM_RESP_R.pslverr;
        end
    end
`undef EFUSE_OTP_REQ
`undef EFUSE_SHIM_RESP_R

    // ------------------------------------------------------------------
    // eFuse shim response hold.
    // ------------------------------------------------------------------
    // A healthy shim always answers, so a late program response has no
    // frontdoor. While efuse_shim_resp_hold_i=1 and a PROGRAM or
    // PROGRAM_READ_BACK command is at the post-guard port, the valid of the
    // shim response at the sep input efuse_shim_command_resp_i (the
    // sep_wrapper net efuse_shim_command_resp) is forced to 0. A READ command
    // never matches, so sense and read responses are not held. The program
    // interface keeps its request valid until a response arrives, so while
    // held the shim repeats the program of the same bit, and the first
    // response after the release completes the request. Re-issued every clock
    // and released when the gate drops. Default 0.
    wire efuse_shim_resp_hold_hit =
        (efuse_shim_resp_hold_i === 1'b1) &&
        (`SEP_CORE.efuse_shim_command_req_o.valid === 1'b1) &&
        (`SEP_CORE.efuse_shim_command_req_o.command !== efuse_pkg::FUSE_COMMAND_READ);
    always @(posedge clk_i) begin
        if (efuse_shim_resp_hold_hit) begin
            force u_dut.efuse_shim_command_resp.valid = 1'b0;
        end else begin
            release u_dut.efuse_shim_command_resp.valid;
        end
    end
`undef EFUSE_RD
`undef EFUSE_PG
`undef EFUSE_CTRL

`undef DIGEST_SIP
`undef CMP_SIP
`undef CMP_CHIP
`undef CMP_SEC
`undef TOKEN_PROC

    // ------------------------------------------------------------------
    // DMA host-path command-integrity inject.
    // ------------------------------------------------------------------
    // host_path_err is the OR of a fabric non-OKAY on a DMA transfer and a
    // TL-UL command-integrity fail on a DMA-issued command. A legal
    // descriptor can produce the fabric term; it cannot produce a broken
    // command user code -- the engine always emits a matching pair. When
    // dma_host_intg_inject_i=1, force the host-adapter checker input
    // (tlul_cmd_intg_chk.u_chk.data_i) to 0 so the real decoder computes
    // err_o. err_o stays gated on a_valid. STATUS / PIC source 42 (vector
    // bit [41]) / CLEAR stay frontdoor or the aggregate interrupt probe.
    // Re-issue every clock (Verilator snapshots a force RHS). Release when the
    // port drops.
    // Default 0; outside the AXI ready/valid cones.
`define DMA_HOST_CMD_INTG_DI \
    `SEP_CORE.u_sep_dma_wrap.u_tlul_to_axi_lite_dma \
        .gen_cmd_intg_check.u_cmd_intg_chk.u_chk.data_i
    always @(posedge clk_i) begin
        if (dma_host_intg_inject_i === 1'b1) begin
            force `DMA_HOST_CMD_INTG_DI = '0;
        end else begin
            release `DMA_HOST_CMD_INTG_DI;
        end
    end
`undef DMA_HOST_CMD_INTG_DI

    // ------------------------------------------------------------------
    // HMAC message-FIFO drain stall.
    // ------------------------------------------------------------------
    // hmac_fifo_drain_stall_i=1 holds the read side of the message FIFO idle,
    // so the hash engine takes no word and the FIFO fills: the wedge the ROM's
    // bounded FIFO waits must turn into a hash failure. Two hmac-local nets are
    // forced to 0:
    //   * fifo_rready, the read-ready of the FIFO (no word leaves the FIFO);
    //   * u_hmac.sha_rvalid_o, the word valid that hmac_core gives the SHA-2
    //     engine. In SHA-2 mode, and in the message state of HMAC mode, the
    //     core passes the FIFO valid (fifo_rvalid_i) straight to this output,
    //     and its own word count uses it, so it is the core's view of
    //     fifo_rvalid. Without it the engine reads the head word on every
    //     clock while the FIFO does not pop. The force stays off the FIFO's
    //     own rvalid net (hmac fifo_rvalid), so STATUS.fifo_empty, the
    //     fifo_empty interrupt and the idle term keep their real values.
    // While the input is 1 the engine also takes no key-pad word. Re-issued
    // every clock for Verilator, released when the port drops.
`define HMAC_STALL_TT `SEP_CORE.u_sep_crypto.u_hmac_wrapper_s3c_scan.u_tt_hmac
    always @(posedge clk_i) begin
        if (hmac_fifo_drain_stall_i === 1'b1) begin
            force `HMAC_STALL_TT.fifo_rready = 1'b0;
            force `HMAC_STALL_TT.u_hmac.sha_rvalid_o = 1'b0;
        end else begin
            release `HMAC_STALL_TT.fifo_rready;
            release `HMAC_STALL_TT.u_hmac.sha_rvalid_o;
        end
    end
`undef HMAC_STALL_TT

    // ------------------------------------------------------------------
    // KMAC message-FIFO drain stall.
    // ------------------------------------------------------------------
    // kmac_fifo_drain_stall_i=1 holds the read side of the message FIFO idle:
    // the FIFO read-ready and the FIFO valid toward the KMAC core are both 0, so
    // the engine takes no word and the FIFO fills until STATUS.fifo_full reads 1.
    // msgfifo_ready and msgfifo_valid are the kmac-local nets between u_msgfifo
    // and u_kmac_core. After the release the FIFO drains and the message can
    // complete. Re-issued every clock for Verilator, released when the port
    // drops.
`define KMAC_FIFO_RD `SEP_CORE.u_sep_crypto.u_kmac_wrapper_s3c_scan.u_tt_kmac
    always @(posedge clk_i) begin
        if (kmac_fifo_drain_stall_i === 1'b1) begin
            force `KMAC_FIFO_RD.msgfifo_ready = 1'b0;
            force `KMAC_FIFO_RD.msgfifo_valid = 1'b0;
        end else begin
            release `KMAC_FIFO_RD.msgfifo_ready;
            release `KMAC_FIFO_RD.msgfifo_valid;
        end
    end
`undef KMAC_FIFO_RD

    // ------------------------------------------------------------------
    // DMA host-port stall.
    // ------------------------------------------------------------------
    // +sep_dma_host_stall holds the host TL-UL response idle -- a_ready and
    // d_valid both 0 -- so the secure DMA can neither issue a request nor see a
    // response: it stays busy and reports neither DONE nor ERROR, which is the
    // wedge the ROM's bounded completion poll must turn into an error. The whole
    // struct is forced, since d_valid=0 keeps its integrity fields unchecked.
    // The force targets the wrapper-local net the adapter drives, not the
    // engine's input port. Re-issued every clock for Verilator, as above.
    logic dma_host_stall_on;
    initial begin
        dma_host_stall_on = $test$plusargs("sep_dma_host_stall");
        if (dma_host_stall_on) begin
            $display("[tb] +sep_dma_host_stall: secure DMA host port held idle");
        end
    end
`define DMA_HOST_RSP `SEP_CORE.u_sep_dma_wrap.host_tl_h_i
    always @(posedge clk_i) begin
        if (dma_host_stall_on) force `DMA_HOST_RSP = '0;
    end
`undef DMA_HOST_RSP

    // ------------------------------------------------------------------
    // ESRC raw-noise force + entropy datapath probes.
    // ------------------------------------------------------------------
    // The ESRC ring oscillators' `#delay` feedback is ignored under Verilator, so
    // the 12 noise lanes never toggle. Under +esrc_noise_force, drive them from the
    // cocotb-controlled raw-noise port so the real decorrelator/compressor/SHA/
    // CSRNG/EDN math runs on a sequence the Python golden predicts bit-exactly.
    // The downstream drbg_axis/edn nets below are read-only observation taps,
    // never forced.
    logic [11:0] esrc_noise_d;

    assign esrc_noise_d = esrc_noise_ext_i;
    assign esrc_noise_o = esrc_noise_d;
    // Read back lane 0's ACTUAL dcor.noise_i: when the force is active this tracks
    // the driven bit; without the force it is the RTL's (static/X) noise bit. The
    // smoke asserts this matches esrc_noise_o[0] -> proves the force took (not
    // vacuous).
    assign esrc_noise_active_o =
        `SEP_ESRC.u_generator_complex.gen_ecmplx[0].u_generator.u_decorrelator.noise_i;

    // Force the per-lane DECORRELATOR INPUT PORT (dcor.noise_i) directly -- the
    // exact node the SR flop samples. Forcing the upstream
    // `noise_bit` wire instead lets the SR flop sample a different scheduling point
    // under Verilator, so the decorrelator golden cannot reproduce the RTL output.
    // RE-ISSUE the force every clock: a `force` in an `initial` block snapshots the
    // RHS once at t=0 (Verilator), so it would hold the stale value. Update on the
    // falling edge so noise_i is stable before the decorrelator samples it on the
    // rising edge; forcing on that same rising edge creates an ordering race.
    // Explicit per-lane indices avoid a cross-hierarchy genvar-indexed force.
    //
    // A lane whose noise-source stuck-at inject is on (esrc_noise_stuck_en_i[i],
    // block below) is released instead: its decorrelator then takes the real
    // synchronized noise bit, which carries the stuck value. So the two hooks
    // never drive one lane at the same time, and the force on noise_i cannot
    // stand in for the stuck-at value at the noise observe FIFO, even where a
    // simulator merges the noise_i port with its noise_bit net.
`define ESRC_NOISE_FORCE(i) \
    if (esrc_noise_stuck_en_i[i] === 1'b1) \
        release `SEP_ESRC.u_generator_complex.gen_ecmplx[i].u_generator.u_decorrelator.noise_i; \
    else \
        force `SEP_ESRC.u_generator_complex.gen_ecmplx[i].u_generator.u_decorrelator.noise_i = \
            esrc_noise_d[i]
    // `force` is a procedural continuous override, so a plain `always` carries it.
    // The force is gated by `+esrc_noise_force` and each test is its own
    // elaboration, so it ends with the sim; only the stuck-at inject releases it.
    always @(negedge clk_i) begin
        if ($test$plusargs("esrc_noise_force")) begin
            `ESRC_NOISE_FORCE(0);  `ESRC_NOISE_FORCE(1);  `ESRC_NOISE_FORCE(2);
            `ESRC_NOISE_FORCE(3);  `ESRC_NOISE_FORCE(4);  `ESRC_NOISE_FORCE(5);
            `ESRC_NOISE_FORCE(6);  `ESRC_NOISE_FORCE(7);  `ESRC_NOISE_FORCE(8);
            `ESRC_NOISE_FORCE(9);  `ESRC_NOISE_FORCE(10); `ESRC_NOISE_FORCE(11);
        end
    end
`undef ESRC_NOISE_FORCE

    // ------------------------------------------------------------------
    // ESRC noise-source stuck-at inject.
    // ------------------------------------------------------------------
    // While bit i of esrc_noise_stuck_en_i is 1, the output of the noise ring
    // oscillator of lane i (u_noise_source.noise_async, the net between the
    // ring oscillator and the sampling flop u_smpl) is forced to bit i of
    // esrc_noise_stuck_val_i: a stuck noise source. The value passes the
    // sampling flop and the two-flop synchronizer like a real ring output, so it
    // reaches noise_bit, the noise observe FIFO samples and the decorrelator of
    // the lane. The sampling flop runs on the lane's selected sample clock, so a
    // leaf that needs the value on Verilator selects the external sample clock
    // (the ring oscillators do not toggle there). The force is re-issued every
    // clock and released when the bit drops. Default 0: no force.
`define ESRC_NOISE_STUCK(i) \
    if (esrc_noise_stuck_en_i[i] === 1'b1) \
        force `SEP_ESRC.u_generator_complex.gen_ecmplx[i].u_generator.u_noise_source.noise_async = \
            esrc_noise_stuck_val_i[i]; \
    else \
        release `SEP_ESRC.u_generator_complex.gen_ecmplx[i].u_generator.u_noise_source.noise_async
    always @(negedge clk_i) begin
        `ESRC_NOISE_STUCK(0);  `ESRC_NOISE_STUCK(1);  `ESRC_NOISE_STUCK(2);
        `ESRC_NOISE_STUCK(3);  `ESRC_NOISE_STUCK(4);  `ESRC_NOISE_STUCK(5);
        `ESRC_NOISE_STUCK(6);  `ESRC_NOISE_STUCK(7);  `ESRC_NOISE_STUCK(8);
        `ESRC_NOISE_STUCK(9);  `ESRC_NOISE_STUCK(10); `ESRC_NOISE_STUCK(11);
    end
`undef ESRC_NOISE_STUCK
    // Readback of the stuck-at inject and of the real noise path: the
    // synchronized noise bit of each lane, read-only.
`define ESRC_NOISE_BIT_TAP(i) \
    assign esrc_noise_bit_o[i] = `SEP_ESRC.u_generator_complex.gen_ecmplx[i].u_generator.noise_bit
    `ESRC_NOISE_BIT_TAP(0);  `ESRC_NOISE_BIT_TAP(1);  `ESRC_NOISE_BIT_TAP(2);
    `ESRC_NOISE_BIT_TAP(3);  `ESRC_NOISE_BIT_TAP(4);  `ESRC_NOISE_BIT_TAP(5);
    `ESRC_NOISE_BIT_TAP(6);  `ESRC_NOISE_BIT_TAP(7);  `ESRC_NOISE_BIT_TAP(8);
    `ESRC_NOISE_BIT_TAP(9);  `ESRC_NOISE_BIT_TAP(10); `ESRC_NOISE_BIT_TAP(11);
`undef ESRC_NOISE_BIT_TAP

    // ------------------------------------------------------------------
    // ESRC main-FIFO integrity inject.
    // ------------------------------------------------------------------
    // Software cannot store a word with a wrong parity nor move one copy of a
    // hardened pointer, so the FIFO integrity check has no frontdoor stimulus.
    // Both injects target the main FIFO (u_entropy_fifo) only; INTR_STATUS
    // and the stream taps the checkers read are not forced.
    //
    // Parity: while esrc_fifo_parity_inject_i is 1, stored_parity (the parity
    // nibble of the entry at the read pointer, as the read check sees it) is
    // the stored nibble with bit esrc_fifo_parity_bit_i inverted. The stored
    // array is not written, so the error ends at the release.
    //
    // Pointer: at the rise of esrc_fifo_ptr_inject_i the bench captures the
    // selected counter copy of prim_count (cnt_unforced_q of gen_cnts[c] in
    // u_wptr or u_rptr) with bit esrc_fifo_ptr_bit_i inverted, and holds that
    // copy at the captured value while the input stays 1. The other copy moves
    // on, so the two copies disagree. esrc_fifo_ptr_sel_i and
    // esrc_fifo_ptr_bit_i are sampled at the rise.
    //
    // Re-issued on every falling edge for Verilator (the counters and the read
    // pointer change on the rising edge), released when the input drops.
    // Default 0: no force.
`define ESRC_FIFO `SEP_ESRC.u_entropy_fifo
`define ESRC_PTR_W0 `ESRC_FIFO.u_fifo_cnt.gen_secure_ptrs.u_wptr.gen_cnts[0].cnt_unforced_q
`define ESRC_PTR_W1 `ESRC_FIFO.u_fifo_cnt.gen_secure_ptrs.u_wptr.gen_cnts[1].cnt_unforced_q
`define ESRC_PTR_R0 `ESRC_FIFO.u_fifo_cnt.gen_secure_ptrs.u_rptr.gen_cnts[0].cnt_unforced_q
`define ESRC_PTR_R1 `ESRC_FIFO.u_fifo_cnt.gen_secure_ptrs.u_rptr.gen_cnts[1].cnt_unforced_q
    logic       esrc_ptr_inj_on;
    logic [1:0] esrc_ptr_inj_sel;
    logic [6:0] esrc_ptr_inj_val;
    initial begin
        esrc_ptr_inj_on  = 1'b0;
        esrc_ptr_inj_sel = '0;
        esrc_ptr_inj_val = '0;
    end
    always @(negedge clk_i) begin
        if (esrc_fifo_parity_inject_i === 1'b1) begin
            force `ESRC_FIFO.stored_parity =
                `ESRC_FIFO.read_entry[35:32] ^ (4'b0001 << esrc_fifo_parity_bit_i);
        end else begin
            release `ESRC_FIFO.stored_parity;
        end
        if (esrc_fifo_ptr_inject_i === 1'b1) begin
            if (!esrc_ptr_inj_on) begin
                esrc_ptr_inj_on  = 1'b1;
                esrc_ptr_inj_sel = esrc_fifo_ptr_sel_i;
                unique case (esrc_fifo_ptr_sel_i)
                    2'b00:   esrc_ptr_inj_val = `ESRC_PTR_W0;
                    2'b01:   esrc_ptr_inj_val = `ESRC_PTR_W1;
                    2'b10:   esrc_ptr_inj_val = `ESRC_PTR_R0;
                    default: esrc_ptr_inj_val = `ESRC_PTR_R1;
                endcase
                esrc_ptr_inj_val = esrc_ptr_inj_val ^ (7'b000_0001 << esrc_fifo_ptr_bit_i);
                $display("[tb] ESRC FIFO pointer inject: sel=%0d bit=%0d value=0x%02x",
                         esrc_fifo_ptr_sel_i, esrc_fifo_ptr_bit_i, esrc_ptr_inj_val);
            end
            unique case (esrc_ptr_inj_sel)
                2'b00:   force `ESRC_PTR_W0 = esrc_ptr_inj_val;
                2'b01:   force `ESRC_PTR_W1 = esrc_ptr_inj_val;
                2'b10:   force `ESRC_PTR_R0 = esrc_ptr_inj_val;
                default: force `ESRC_PTR_R1 = esrc_ptr_inj_val;
            endcase
        end else begin
            esrc_ptr_inj_on = 1'b0;
            release `ESRC_PTR_W0;
            release `ESRC_PTR_W1;
            release `ESRC_PTR_R0;
            release `ESRC_PTR_R1;
        end
    end
`undef ESRC_PTR_W0
`undef ESRC_PTR_W1
`undef ESRC_PTR_R0
`undef ESRC_PTR_R1
`undef ESRC_FIFO

    // ------------------------------------------------------------------
    // Crypto alert sender inject.
    // ------------------------------------------------------------------
    // While crypto_alert_inject_i is 1, the alert pair (alert_p, alert_n) at
    // the input of crypto alert receiver crypto_alert_inject_idx_i
    // (u_sep_crypto.gen_alert_receivers[i].u_alert_receiver.alert_tx_i) is
    // forced to {v, v}, v = crypto_alert_inject_val_i. Both wires at one value
    // is not a differential code, so the receiver signals an integrity fail
    // into the Crypto alert source. No block can send a malformed pair, so this
    // has no frontdoor. The interrupt vector the checker reads is not forced.
    // An index above 10 forces nothing. Re-issued every clock for Verilator,
    // released when the input drops. Default 0: no force.
`define CRYPTO_ALERT_RX(i) `SEP_CORE.u_sep_crypto.gen_alert_receivers[i].u_alert_receiver.alert_tx_i
`define CRYPTO_ALERT_INJ(i) \
    if (crypto_alert_inject_i === 1'b1 && crypto_alert_inject_idx_i === 4'(i)) \
        force `CRYPTO_ALERT_RX(i) = {crypto_alert_inject_val_i, crypto_alert_inject_val_i}; \
    else \
        release `CRYPTO_ALERT_RX(i)
    always @(negedge clk_i) begin
        `CRYPTO_ALERT_INJ(0);  `CRYPTO_ALERT_INJ(1);  `CRYPTO_ALERT_INJ(2);
        `CRYPTO_ALERT_INJ(3);  `CRYPTO_ALERT_INJ(4);  `CRYPTO_ALERT_INJ(5);
        `CRYPTO_ALERT_INJ(6);  `CRYPTO_ALERT_INJ(7);  `CRYPTO_ALERT_INJ(8);
        `CRYPTO_ALERT_INJ(9);  `CRYPTO_ALERT_INJ(10);
    end
`undef CRYPTO_ALERT_INJ
`undef CRYPTO_ALERT_RX

    // +sep_otbn_cmd_drop -- fault injection, off by default. Makes OTBN ignore
    // every command write, leaving the block powered, idle and error-free while
    // no program ever runs.
    //
    // This is the "the CMD store never landed" case: what an instruction-skip
    // glitch on the store produces deliberately, and what clock or reset
    // mis-sequencing produces by accident. It is worth injecting because the
    // block is indistinguishable from a completed run on STATUS (reads IDLE,
    // the state it was already in) and ERR_BITS (reads 0, nothing ran to
    // fail). INTR_STATE.done is the only signal that separates them, and
    // otbn_execute() requires it.
    logic otbn_cmd_drop_on;
    initial begin
        otbn_cmd_drop_on = $test$plusargs("sep_otbn_cmd_drop");
        if (otbn_cmd_drop_on) begin
            $display("[tb] *** FAULT INJECTION: +sep_otbn_cmd_drop -- OTBN command writes");
            $display("[tb] *** are dropped; no OTBN program will execute.");
        end
    end

// reg2hw.cmd.qe is the write-enable otbn.sv decodes CmdExecute from
// (the CmdExecute case in otbn.sv), so holding it low drops commands without disturbing
// anything else the block reports.
`define OTBN_CMD_QE \
    `SEP_CORE.u_sep_crypto.u_sep_crypto_otbn_wrapper_s3c_scan.u_otbn.reg2hw.cmd.qe
    always @(posedge clk_i) begin
        if (otbn_cmd_drop_on) force `OTBN_CMD_QE = 1'b0;
    end
`undef OTBN_CMD_QE

    // Entropy datapath probe taps (compiled-in XMR reads; no --public-flat-rw).
    assign esrc_ro_enable_o     = `SEP_ESRC.u_generator_complex.jitter_ro_enable_i;
    assign esrc_decor_bytes_o   = `SEP_ESRC.u_generator_complex.entropy_stream_uncompressed_o;
    // Raw 29-bit decorrelator shift register per lane. ff_stage and the sampled
    // byte share the full entropy-source rst_ni. decor_bytes_o lags the
    // true SR reset by a full divider period, so the golden cannot derive
    // the SR phase from decor_bytes_o alone. The scoreboard seeds its golden SR from
    // this exact state once shifting is live, then free-runs the CHK1..CHK5 chain.
    // Explicit per-lane indices avoid a cross-hierarchy genvar-indexed XMR.
`define ESRC_DECOR_SR(i) \
    assign esrc_decor_sr_o[29*(i) +: 29] = \
        `SEP_ESRC.u_generator_complex.gen_ecmplx[i].u_generator.u_decorrelator.ff_stage
    `ESRC_DECOR_SR(0);  `ESRC_DECOR_SR(1);  `ESRC_DECOR_SR(2);
    `ESRC_DECOR_SR(3);  `ESRC_DECOR_SR(4);  `ESRC_DECOR_SR(5);
    `ESRC_DECOR_SR(6);  `ESRC_DECOR_SR(7);  `ESRC_DECOR_SR(8);
    `ESRC_DECOR_SR(9);  `ESRC_DECOR_SR(10); `ESRC_DECOR_SR(11);
`undef ESRC_DECOR_SR
    assign esrc_decor_valid_o   = `SEP_ESRC.entropy_stream_valid;
    // SHA-whitener input handshake: a BIW word is hashed only when the whitener is
    // in its input phase (sha_fifo_valid && sha_fifo_ready). During its SHA compute
    // + 8-word output phase it accepts nothing and the unconnected entropy_ready_o
    // means upstream decor samples are DROPPED -- so the chain golden must be fed a
    // sample ONLY on this strobe, else its SHA 16:1 blocks misframe after block 0.
    assign esrc_whiten_push_o   = `SEP_ESRC.u_sha256_whitener.sha_fifo_valid
                                & `SEP_ESRC.u_sha256_whitener.sha_fifo_ready;
    assign esrc_compress_vld_o  = `SEP_ESRC.entropy_stream_vld_o;
    assign esrc_compress_data_o = `SEP_ESRC.entropy_stream_data_o;
    assign drbg_seed_valid_o    = `SEP_DRBG.u_csrng_seed_adapter.seed_queue_valid_o;
    assign drbg_es_ack_o        = `SEP_DRBG.u_csrng.entropy_src_hw_if_i.es_ack;
    assign drbg_es_bits_o       = `SEP_DRBG.u_csrng.entropy_src_hw_if_i.es_bits;
    assign drbg_genbits_vld_o   = `SEP_DRBG.u_csrng.u_csrng_core.u_csrng_ctr_drbg.bits_vld_o;
    assign drbg_genbits_data_o  = `SEP_DRBG.u_csrng.u_csrng_core.u_csrng_ctr_drbg.bits_data_o;
    assign drbg_genbits_fips_o  = `SEP_DRBG.u_csrng.u_csrng_core.u_csrng_ctr_drbg.bits_fips_o;
    assign drbg_gen_last_o      = `SEP_DRBG.u_csrng.u_csrng_core.gen_last_q;
    // drbg_axil64_lane_adapter arbitration, sampled at each DUT adapter's
    // own AXI-Lite-64 port:
    // {ar_ready, w_ready, aw_ready, ar_valid, w_valid, aw_valid}.
    // Observation-only. No CSR mirrors the three-ready interlock, and a
    // frontdoor timeout names only that the access did not retire. Outside
    // the tb s_axi / m_axi ready/valid cones.
    assign drbg_csrng_axil_chan_o = {
        `SEP_DRBG.u_csrng_axil_adapter.axil64_rsp_o.ar_ready,
        `SEP_DRBG.u_csrng_axil_adapter.axil64_rsp_o.w_ready,
        `SEP_DRBG.u_csrng_axil_adapter.axil64_rsp_o.aw_ready,
        `SEP_DRBG.u_csrng_axil_adapter.axil64_req_i.ar_valid,
        `SEP_DRBG.u_csrng_axil_adapter.axil64_req_i.w_valid,
        `SEP_DRBG.u_csrng_axil_adapter.axil64_req_i.aw_valid
    };
    assign drbg_edn_axil_chan_o = {
        `SEP_DRBG.u_edn_axil_adapter.axil64_rsp_o.ar_ready,
        `SEP_DRBG.u_edn_axil_adapter.axil64_rsp_o.w_ready,
        `SEP_DRBG.u_edn_axil_adapter.axil64_rsp_o.aw_ready,
        `SEP_DRBG.u_edn_axil_adapter.axil64_req_i.ar_valid,
        `SEP_DRBG.u_edn_axil_adapter.axil64_req_i.w_valid,
        `SEP_DRBG.u_edn_axil_adapter.axil64_req_i.aw_valid
    };
    // Each DUT lane adapter's downstream request into its AXI-Lite-32 to
    // TL-UL bridge: {ar_valid, aw_valid | w_valid}. Observation-only. An
    // access the adapter refuses must leave both bits low on every cycle; no
    // CSR shows a request that the bridge then answered without error.
    assign drbg_csrng_fwd_o = {
        `SEP_DRBG.u_csrng_axil_adapter.axil32_req_o.ar_valid,
        `SEP_DRBG.u_csrng_axil_adapter.axil32_req_o.aw_valid
            | `SEP_DRBG.u_csrng_axil_adapter.axil32_req_o.w_valid
    };
    assign drbg_edn_fwd_o = {
        `SEP_DRBG.u_edn_axil_adapter.axil32_req_o.ar_valid,
        `SEP_DRBG.u_edn_axil_adapter.axil32_req_o.aw_valid
            | `SEP_DRBG.u_edn_axil_adapter.axil32_req_o.w_valid
    };

    // ---------------------------------------------------------------------
    // Port-level arbitration vehicle: a TB-owned second instance of
    // drbg_axil64_lane_adapter, driven straight from cocotb.
    //
    // The DUT's own lane adapters sit behind the crossbar, which delivers W a
    // cycle after AW and re-serializes to that order whatever a master
    // presents, so the same-cycle and W-first orderings cannot be presented
    // at a DUT adapter port from the fabric. This instance has its own reset
    // and no fabric in front of it, so every legal ordering is reachable and
    // a wedged cell is cleared by resetting the vehicle alone.
    //
    // Its axil32 side is an always-ready responder: the contract under test
    // is the 64-bit port's channel arbitration, so the downstream leg only
    // has to retire what the adapter forwards. It must not be the thing that
    // stalls, or a stall would be ambiguous.
    // ---------------------------------------------------------------------
    drbg_pkg::drbg_axil64_req_t  tbadp_req;
    drbg_pkg::drbg_axil64_resp_t tbadp_rsp;
    drbg_pkg::drbg_axil32_req_t  tbadp_req32;
    drbg_pkg::drbg_axil32_resp_t tbadp_rsp32;

    always_comb begin
        tbadp_req          = '0;
        tbadp_req.aw_valid = tbadp_aw_valid_i;
        tbadp_req.aw.addr  = tbadp_aw_addr_i;
        tbadp_req.w_valid  = tbadp_w_valid_i;
        tbadp_req.w.data   = tbadp_w_data_i;
        tbadp_req.w.strb   = tbadp_w_strb_i;
        tbadp_req.b_ready  = tbadp_b_ready_i;
        tbadp_req.ar_valid = tbadp_ar_valid_i;
        tbadp_req.ar.addr  = tbadp_ar_addr_i;
        tbadp_req.r_ready  = tbadp_r_ready_i;
    end

    assign tbadp_chan_o = {
        tbadp_rsp.ar_ready,
        tbadp_rsp.w_ready,
        tbadp_rsp.aw_ready,
        tbadp_req.ar_valid,
        tbadp_req.w_valid,
        tbadp_req.aw_valid
    };
    assign tbadp_b_valid_o = tbadp_rsp.b_valid;
    assign tbadp_r_valid_o = tbadp_rsp.r_valid;
    assign tbadp_r_data_o  = tbadp_rsp.r.data;
    // The response CODES, not just the valids. An access the adapter rejects
    // as unsupported answers SLVERR from ST_IDLE without forwarding anything,
    // and retires just as promptly as a real one -- so a control that only
    // watched the valid could not tell a live forwarding path from a rejected
    // access.
    assign tbadp_b_resp_o  = tbadp_rsp.b.resp;
    assign tbadp_r_resp_o  = tbadp_rsp.r.resp;
    // The adapter's downstream request, as the AXI-Lite-32 responder sees it.
    // A refused access must not drive it; a forwarded one must.
    assign tbadp_fwd_o     = {tbadp_req32.ar_valid,
                              tbadp_req32.aw_valid | tbadp_req32.w_valid};

    // Always-ready axil32 responder: every ready is an unconditional 1'b1.
    // Not gated on the peer channel's valid: cross-gating the
    // readys is the exact shape this vehicle exists to catch, and putting it
    // one hop downstream would make a stall ambiguous about which side
    // produced it.
    logic tbadp32_b_pending_q, tbadp32_r_pending_q;
    always_ff @(posedge clk_i or negedge tbadp_rst_ni_i) begin
        if (!tbadp_rst_ni_i) begin
            tbadp32_b_pending_q <= 1'b0;
            tbadp32_r_pending_q <= 1'b0;
        end else begin
            tbadp32_b_pending_q <= (tbadp_req32.aw_valid && tbadp_req32.w_valid)
                                   || (tbadp32_b_pending_q && !tbadp_req32.b_ready);
            tbadp32_r_pending_q <= tbadp_req32.ar_valid
                                   || (tbadp32_r_pending_q && !tbadp_req32.r_ready);
        end
    end
    always_comb begin
        tbadp_rsp32           = '0;
        tbadp_rsp32.aw_ready  = 1'b1;
        tbadp_rsp32.w_ready   = 1'b1;
        tbadp_rsp32.ar_ready  = 1'b1;
        tbadp_rsp32.b_valid   = tbadp32_b_pending_q;
        tbadp_rsp32.b.resp    = axi_pkg::RESP_OKAY;
        tbadp_rsp32.r_valid   = tbadp32_r_pending_q;
        tbadp_rsp32.r.data    = 32'hA5A5_1234;
        tbadp_rsp32.r.resp    = axi_pkg::RESP_OKAY;
    end

    drbg_axil64_lane_adapter #(
        .axil64_req_t(drbg_pkg::drbg_axil64_req_t),
        .axil64_rsp_t(drbg_pkg::drbg_axil64_resp_t),
        .axil32_req_t(drbg_pkg::drbg_axil32_req_t),
        .axil32_rsp_t(drbg_pkg::drbg_axil32_resp_t)
    ) u_tbadp_vehicle (
        .clk_i                     (clk_i),
        .rst_ni                    (tbadp_rst_ni_i),
        .axil64_req_i              (tbadp_req),
        .axil64_rsp_o              (tbadp_rsp),
        .axil32_req_o              (tbadp_req32),
        .axil32_rsp_i              (tbadp_rsp32),
        .unsupported_access_pulse_o(),
        .forwarded_read_pulse_o    (),
        .forwarded_write_pulse_o   ()
    );
    // Post-EXT_TRNG_SRC_SEL-mux: the entropy actually presented to the KM (proves
    // the internal-DRBG leg was selected, not ext_trng). tvalid && tready = the KM
    // consumed a genbits word.
    assign km_entropy_tvalid_o  = `SEP_CORE.u_sep_crypto.entropy_muxed_req[0].tvalid;
    assign km_entropy_tdata_o   = `SEP_CORE.u_sep_crypto.entropy_muxed_req[0].tdata;
    // CHK5 per-sink routing golden: the crypto-leg (mux endpoint [1]) AXIS word
    // stream feeding drbg_axis_edn_adapter. tvalid && tready = one word handed to a
    // crypto endpoint (in `sep_drbg_real_sink_multi_km_aes_test` only AES
    // requests, so this equals AES's post-adapter beats in order). Each word is
    // also a CHK4 genbits-golden word (chained).
    assign axis1_tvalid_o       = `SEP_CORE.u_sep_crypto.entropy_muxed_req[1].tvalid;
    assign axis1_tready_o       = `SEP_CORE.u_sep_crypto.entropy_muxed_rsp[1].tready;
    assign axis1_tdata_o        = `SEP_CORE.u_sep_crypto.entropy_muxed_req[1].tdata;
    assign km_entropy_tready_o  = `SEP_CORE.u_sep_crypto.entropy_muxed_rsp[0].tready;
    // CHK5 pool (mux endpoint [2]): pre-adapter AXIS2 + post-adapter native EDN.
    assign axis2_tvalid_o       = `SEP_CORE.u_sep_crypto.entropy_muxed_req[2].tvalid;
    assign axis2_tready_o       = `SEP_CORE.u_sep_crypto.entropy_muxed_rsp[2].tready;
    assign axis2_tdata_o        = `SEP_CORE.u_sep_crypto.entropy_muxed_req[2].tdata;
    assign pool_edn_req_o       = `SEP_CORE.u_sep_crypto.entropy_pool_edn_req_i.edn_req;
    assign pool_edn_ack_o       = `SEP_CORE.u_sep_crypto.entropy_pool_edn_rsp_o.edn_ack;
    assign pool_edn_bus_o       = `SEP_CORE.u_sep_crypto.entropy_pool_edn_rsp_o.edn_bus;
    assign pool_edn_fips_o      = `SEP_CORE.u_sep_crypto.entropy_pool_edn_rsp_o.edn_fips;

    // Per-client crypto EDN taps (post drbg_axis_edn_adapter). edn_req is the
    // client's request, edn_ack the adapter's grant pulse, edn_bus the delivered
    // 32b entropy word. Explicit per-index assigns avoid a cross-hierarchy
    // genvar-indexed XMR (same style as the ESRC decorrelator-SR probe above).
`define CRYPTO_EDN_TAP(i) \
    assign crypto_edn_req_o[i]              = `SEP_CORE.u_sep_crypto.crypto_edn_req[i].edn_req;  \
    assign crypto_edn_ack_o[i]              = `SEP_CORE.u_sep_crypto.crypto_edn_rsp[i].edn_ack;  \
    assign crypto_edn_bus_o[32*(i) +: 32]   = `SEP_CORE.u_sep_crypto.crypto_edn_rsp[i].edn_bus;  \
    assign crypto_edn_fips_o[i]             = `SEP_CORE.u_sep_crypto.crypto_edn_rsp[i].edn_fips
    `CRYPTO_EDN_TAP(0); `CRYPTO_EDN_TAP(1); `CRYPTO_EDN_TAP(2); `CRYPTO_EDN_TAP(3);
`undef CRYPTO_EDN_TAP

    // ------------------------------------------------------------------
    // External TRNG stream driver and interrupt (top-port drives).
    // ------------------------------------------------------------------
    // The integration wrapper ties the sep inputs ext_trng_axis_req_i[2:0] and
    // ext_trng_irq_i to 0 (hw/top/sep_ip_integration.sv). The bench forces the
    // wrapper nets that carry them into sep (u_dut.ext_trng_axis_req[i],
    // u_dut.ext_trng_irq), one constant index per stream.
    //   * Stream i: while ext_trng_drive_en_i[i] is 1, tvalid, tdata and tstrb
    //     come from ext_trng_tvalid_i[i], ext_trng_tdata_i[32*i +: 32] and
    //     ext_trng_tstrb_i[4*i +: 4]. With the bit 0 the force is released and
    //     the stream keeps the wrapper tie-off.
    //   * Interrupt: while ext_trng_irq_drive_i is 1 the net is forced to 1;
    //     otherwise it is released to the wrapper tie-off 0.
    // The value is re-issued on every falling edge (Verilator snapshots a force
    // RHS), so a pin that cocotb writes after a rising edge reaches sep before
    // the next rising edge, as from a registered source. The response
    // ext_trng_axis_rsp_o is not forced. cocotb/env/sep_ext_trng_stream.py
    // drives the pins and records the beats.
    sep_crypto_pkg::ext_trng_axis_req_t ext_trng_req_drive [3];
    always_comb begin
        for (int i = 0; i < 3; i++) begin
            ext_trng_req_drive[i].tvalid = (ext_trng_tvalid_i[i] === 1'b1);
            ext_trng_req_drive[i].tdata  = ext_trng_tdata_i[32*i +: 32];
            ext_trng_req_drive[i].tstrb  = ext_trng_tstrb_i[4*i +: 4];
        end
    end
`define EXT_TRNG_DRIVE(i) \
    if (ext_trng_drive_en_i[i] === 1'b1) \
        force u_dut.ext_trng_axis_req[i] = ext_trng_req_drive[i]; \
    else \
        release u_dut.ext_trng_axis_req[i]
    always @(negedge clk_i) begin
        `EXT_TRNG_DRIVE(0); `EXT_TRNG_DRIVE(1); `EXT_TRNG_DRIVE(2);
        if (ext_trng_irq_drive_i === 1'b1) begin
            force u_dut.ext_trng_irq = 1'b1;
        end else begin
            release u_dut.ext_trng_irq;
        end
    end
`undef EXT_TRNG_DRIVE

    // External stream response monitor and the internal DRBG endpoint probe
    // (read-only). ext_trng_* is stream i at the sep port, after the drive
    // above; drbg_int_* is the internal DRBG endpoint of stream i before the
    // source mux of sep_crypto.
`define EXT_TRNG_TAP(i) \
    assign ext_trng_tvalid_o[i]          = `SEP_CORE.ext_trng_axis_req_i[i].tvalid; \
    assign ext_trng_tdata_o[32*(i) +: 32] = `SEP_CORE.ext_trng_axis_req_i[i].tdata; \
    assign ext_trng_tstrb_o[4*(i) +: 4]   = `SEP_CORE.ext_trng_axis_req_i[i].tstrb; \
    assign ext_trng_tready_o[i]          = `SEP_CORE.ext_trng_axis_rsp_o[i].tready; \
    assign drbg_int_tvalid_o[i]          = `SEP_CORE.u_sep_crypto.drbg_int_axis_req[i].tvalid; \
    assign drbg_int_tdata_o[32*(i) +: 32] = `SEP_CORE.u_sep_crypto.drbg_int_axis_req[i].tdata; \
    assign drbg_int_tuser_o[i]           = `SEP_CORE.u_sep_crypto.drbg_int_axis_req[i].tuser; \
    assign drbg_int_tready_o[i]          = `SEP_CORE.u_sep_crypto.drbg_int_axis_rsp[i].tready
    `EXT_TRNG_TAP(0); `EXT_TRNG_TAP(1); `EXT_TRNG_TAP(2);
`undef EXT_TRNG_TAP

    // ESRC and OTBN observation probes (read-only).
    //   * esrc_detune_o[i]: the effective ring-oscillator detune select of lane
    //     i (u_generator.detune: the tune FSM state with auto-tune on, else the
    //     manual detune input detune_ro_i).
    //   * esrc_sha256_status_o: the next value of SHA256_STATUS on every clock,
    //     {OUTPUT_COUNT, INPUT_COUNT, BUSY}; a register read samples it once.
    //   * otbn_status_probe_o: OTBN status_q on every clock; a STATUS read
    //     samples it once.
`define ESRC_DETUNE_TAP(i) \
    assign esrc_detune_o[i] = `SEP_ESRC.u_generator_complex.gen_ecmplx[i].u_generator.detune
    `ESRC_DETUNE_TAP(0);  `ESRC_DETUNE_TAP(1);  `ESRC_DETUNE_TAP(2);
    `ESRC_DETUNE_TAP(3);  `ESRC_DETUNE_TAP(4);  `ESRC_DETUNE_TAP(5);
    `ESRC_DETUNE_TAP(6);  `ESRC_DETUNE_TAP(7);  `ESRC_DETUNE_TAP(8);
    `ESRC_DETUNE_TAP(9);  `ESRC_DETUNE_TAP(10); `ESRC_DETUNE_TAP(11);
`undef ESRC_DETUNE_TAP
    //   * esrc_decor_noise_o[i]: the decorrelator input bit of lane i
    //     (u_decorrelator.noise_i), the net the bench noise force drives. The
    //     FCOV lane-pattern and byte-mask points sample it.
`define ESRC_DECOR_NOISE_TAP(i) \
    assign esrc_decor_noise_o[i] = \
        `SEP_ESRC.u_generator_complex.gen_ecmplx[i].u_generator.u_decorrelator.noise_i
    `ESRC_DECOR_NOISE_TAP(0);  `ESRC_DECOR_NOISE_TAP(1);  `ESRC_DECOR_NOISE_TAP(2);
    `ESRC_DECOR_NOISE_TAP(3);  `ESRC_DECOR_NOISE_TAP(4);  `ESRC_DECOR_NOISE_TAP(5);
    `ESRC_DECOR_NOISE_TAP(6);  `ESRC_DECOR_NOISE_TAP(7);  `ESRC_DECOR_NOISE_TAP(8);
    `ESRC_DECOR_NOISE_TAP(9);  `ESRC_DECOR_NOISE_TAP(10); `ESRC_DECOR_NOISE_TAP(11);
`undef ESRC_DECOR_NOISE_TAP
    assign esrc_sha256_status_o = {`SEP_ESRC.reg_in.SHA256_STATUS.OUTPUT_COUNT.next,
                                   `SEP_ESRC.reg_in.SHA256_STATUS.INPUT_COUNT.next,
                                   `SEP_ESRC.reg_in.SHA256_STATUS.BUSY.next};
    assign otbn_status_probe_o =
        8'(`SEP_CORE.u_sep_crypto.u_sep_crypto_otbn_wrapper_s3c_scan.u_otbn.status_q);

    // KM/OTBN memory activity counters from the wrapper-internal req nets.
    // KM SRAM gnt=1 and OTBN req=enable, so a count of the request strobe is
    // a count of accepted accesses (km uses .req/.we; otbn uses .enable/.write).
    logic [31:0] km_rom_req_cnt_q, km_sram_req_cnt_q, km_sram_wr_cnt_q;
    logic [31:0] otbn_imem_req_cnt_q, otbn_imem_wr_cnt_q;
    logic [31:0] otbn_dmem_req_cnt_q, otbn_dmem_wr_cnt_q;
    always_ff @(posedge clk_i or negedge rst_n_int) begin
        if (!rst_n_int) begin
            km_rom_req_cnt_q    <= '0;
            km_sram_req_cnt_q   <= '0;
            km_sram_wr_cnt_q    <= '0;
            otbn_imem_req_cnt_q <= '0;
            otbn_imem_wr_cnt_q  <= '0;
            otbn_dmem_req_cnt_q <= '0;
            otbn_dmem_wr_cnt_q  <= '0;
        end else begin
            if (u_dut.km_rom_mem_req.req)  km_rom_req_cnt_q  <= km_rom_req_cnt_q + 32'd1;
            if (u_dut.km_sram_mem_req.req) begin
                km_sram_req_cnt_q <= km_sram_req_cnt_q + 32'd1;
                if (u_dut.km_sram_mem_req.we) km_sram_wr_cnt_q <= km_sram_wr_cnt_q + 32'd1;
            end
            if (u_dut.sep_crypto_pka_imem_sram_req.enable) begin
                otbn_imem_req_cnt_q <= otbn_imem_req_cnt_q + 32'd1;
                if (u_dut.sep_crypto_pka_imem_sram_req.write)
                    otbn_imem_wr_cnt_q <= otbn_imem_wr_cnt_q + 32'd1;
            end
            if (u_dut.sep_crypto_pka_dmem_sram_req.enable) begin
                otbn_dmem_req_cnt_q <= otbn_dmem_req_cnt_q + 32'd1;
                if (u_dut.sep_crypto_pka_dmem_sram_req.write)
                    otbn_dmem_wr_cnt_q <= otbn_dmem_wr_cnt_q + 32'd1;
            end
        end
    end
    assign km_rom_req_count_o      = km_rom_req_cnt_q;
    assign km_sram_req_count_o     = km_sram_req_cnt_q;
    assign km_sram_write_count_o   = km_sram_wr_cnt_q;
    assign otbn_imem_req_count_o   = otbn_imem_req_cnt_q;
    assign otbn_imem_write_count_o = otbn_imem_wr_cnt_q;
    assign otbn_dmem_req_count_o   = otbn_dmem_req_cnt_q;
    assign otbn_dmem_write_count_o = otbn_dmem_wr_cnt_q;
    // KM SRAM word 0: peek the real macro array. The KM SRAM is one unscrambled
    // prim_ram_1p_adv (sep_ip_integration.u_km_sram) addressed by word index
    // within the 32 KB SRAM window the Key Manager specification places at
    // 0x0000_8000, so base + 0 is mem[0]. Both KM ROM images store their word
    // there. The index is a hierarchical path and does not depend on that base:
    // a firmware store to the wrong window leaves mem[0] untouched and the
    // word0 compare in sep_km_mem_smoke_test fails.
    assign km_sram_word0_o =
        u_dut.u_sep_ip_integration.u_km_sram.gen_ram_inst[0].u_mem.mem[0][31:0];

    localparam int unsigned KmSramProbeWords = $bits(km_sram_probe_o) / 32;
    for (genvar i = 0; i < KmSramProbeWords; i++) begin : g_km_sram_probe
        assign km_sram_probe_o[32*i +: 32] =
            u_dut.u_sep_ip_integration.u_km_sram.gen_ram_inst[0].u_mem.mem[i][31:0];
    end

    // KM SRAM read-response timing at the wrapper port (km_sram_mem_req/rsp,
    // after the KM scrambler). km_sram_interface descrambles a response with
    // the address it loaded on the accepting edge, so a response must arrive
    // exactly one cycle after its accepted read. Counts:
    //   rd_accept   accepted reads (req && !we && gnt)
    //   rd_lat1     rvalid one cycle after an accepted read
    //   rd_lat_err  rvalid with no accept one cycle earlier, or an accept one
    //               cycle earlier with no rvalid (same-cycle, late or lost)
    //   rd_b2b_diff rvalid in the same cycle as a new accepted read of a
    //               different physical address (pipelined back-to-back reads)
    //   scr_rd      accepted reads while the KMCSR SRAM scrambler is enabled
    // Observation-only: continuous reads of the wrapper nets and of the KM
    // scrambler enable; drives nothing; outside the tb s_axi / m_axi
    // ready/valid cones. Reset to 0 by rst_n_int, so every leaf sees 0 or a
    // count, never X.
    logic km_sram_rd_acc, km_sram_rd_acc_q, km_sram_rvalid;
    logic [km_intf_pkg::KM_SRAM_MEM_ADDR_WIDTH-1:0] km_sram_rd_addr_q;
    logic [31:0] km_sram_rd_acc_cnt_q, km_sram_rd_lat1_cnt_q, km_sram_rd_lat_err_cnt_q;
    logic [31:0] km_sram_rd_b2b_diff_cnt_q, km_sram_scr_rd_cnt_q;
    assign km_sram_rd_acc = (u_dut.km_sram_mem_req.req === 1'b1) &&
                            (u_dut.km_sram_mem_req.we === 1'b0) &&
                            (u_dut.km_sram_mem_rsp.gnt === 1'b1);
    assign km_sram_rvalid = (u_dut.km_sram_mem_rsp.rvalid === 1'b1);
    always_ff @(posedge clk_i or negedge rst_n_int) begin
        if (!rst_n_int) begin
            km_sram_rd_acc_q          <= 1'b0;
            km_sram_rd_addr_q         <= '0;
            km_sram_rd_acc_cnt_q      <= '0;
            km_sram_rd_lat1_cnt_q     <= '0;
            km_sram_rd_lat_err_cnt_q  <= '0;
            km_sram_rd_b2b_diff_cnt_q <= '0;
            km_sram_scr_rd_cnt_q      <= '0;
        end else begin
            km_sram_rd_acc_q <= km_sram_rd_acc;
            if (km_sram_rd_acc) begin
                km_sram_rd_addr_q    <= u_dut.km_sram_mem_req.addr;
                km_sram_rd_acc_cnt_q <= km_sram_rd_acc_cnt_q + 32'd1;
                if (`SEP_CORE.u_sep_crypto.u_key_manager_s3c_scan.scrambler_enable === 1'b1)
                    km_sram_scr_rd_cnt_q <= km_sram_scr_rd_cnt_q + 32'd1;
            end
            if (km_sram_rvalid && km_sram_rd_acc_q)
                km_sram_rd_lat1_cnt_q <= km_sram_rd_lat1_cnt_q + 32'd1;
            if (km_sram_rvalid != km_sram_rd_acc_q)
                km_sram_rd_lat_err_cnt_q <= km_sram_rd_lat_err_cnt_q + 32'd1;
            if (km_sram_rvalid && km_sram_rd_acc &&
                (u_dut.km_sram_mem_req.addr != km_sram_rd_addr_q))
                km_sram_rd_b2b_diff_cnt_q <= km_sram_rd_b2b_diff_cnt_q + 32'd1;
        end
    end
    assign km_sram_rd_accept_count_o   = km_sram_rd_acc_cnt_q;
    assign km_sram_rd_lat1_count_o     = km_sram_rd_lat1_cnt_q;
    assign km_sram_rd_lat_err_count_o  = km_sram_rd_lat_err_cnt_q;
    assign km_sram_rd_b2b_diff_count_o = km_sram_rd_b2b_diff_cnt_q;
    assign km_sram_scr_rd_count_o      = km_sram_scr_rd_cnt_q;

    // KM SRAM writes accepted while the KM scrambler is enabled, at the same
    // wrapper port. The scrambler moves the address as well as the data, so a
    // scrambled store lands on a physical row the firmware cannot name. This
    // keeps the physical word address and the wrapper write data of the first
    // KmSramScrWrSlots such writes, and reads the macro array word at each kept
    // address. Observation-only: continuous reads of the wrapper nets, the KM
    // scrambler enable and the macro array; drives nothing; outside the tb
    // s_axi / m_axi ready/valid cones. Reset to 0 by rst_n_int.
    localparam int unsigned KmSramScrWrSlots = 4;
    localparam int unsigned KmSramAw = km_intf_pkg::KM_SRAM_MEM_ADDR_WIDTH;
    logic km_sram_scr_wr;
    logic [31:0] km_sram_scr_wr_cnt_q;
    logic [KmSramAw-1:0] km_sram_scr_wr_addr_q [KmSramScrWrSlots];
    logic [31:0] km_sram_scr_wr_data_q [KmSramScrWrSlots];
    assign km_sram_scr_wr = (u_dut.km_sram_mem_req.req === 1'b1) &&
                            (u_dut.km_sram_mem_req.we === 1'b1) &&
                            (u_dut.km_sram_mem_rsp.gnt === 1'b1) &&
                            (`SEP_CORE.u_sep_crypto.u_key_manager_s3c_scan.scrambler_enable === 1'b1);
    always_ff @(posedge clk_i or negedge rst_n_int) begin
        if (!rst_n_int) begin
            km_sram_scr_wr_cnt_q <= '0;
            for (int i = 0; i < KmSramScrWrSlots; i++) begin
                km_sram_scr_wr_addr_q[i] <= '0;
                km_sram_scr_wr_data_q[i] <= '0;
            end
        end else if (km_sram_scr_wr) begin
            km_sram_scr_wr_cnt_q <= km_sram_scr_wr_cnt_q + 32'd1;
            for (int i = 0; i < KmSramScrWrSlots; i++) begin
                if (km_sram_scr_wr_cnt_q == 32'(i)) begin
                    km_sram_scr_wr_addr_q[i] <= u_dut.km_sram_mem_req.addr;
                    km_sram_scr_wr_data_q[i] <= u_dut.km_sram_mem_req.wdata;
                end
            end
        end
    end
    assign km_sram_scr_wr_count_o = km_sram_scr_wr_cnt_q;
    for (genvar i = 0; i < KmSramScrWrSlots; i++) begin : g_km_sram_scr_wr
        assign km_sram_scr_wr_addr_o[KmSramAw*i +: KmSramAw] = km_sram_scr_wr_addr_q[i];
        assign km_sram_scr_wr_data_o[32*i +: 32] = km_sram_scr_wr_data_q[i];
        assign km_sram_scr_wr_cell_o[32*i +: 32] =
            u_dut.u_sep_ip_integration.u_km_sram.gen_ram_inst[0].u_mem.mem[km_sram_scr_wr_addr_q[i]][31:0];
    end

    // SEP-side KM mailbox register block (km_mailbox_sep_reg, PeakRDL
    // --err-if-bad-addr): count the write requests its own address decode
    // refuses, and keep the 5-bit block offset of the last one. The single
    // BRESP of a split 64-bit beat cannot say which half, or which block,
    // refused it; this names the block and the offset. Observation-only
    // continuous read of the regblock decode; drives nothing; outside the tb
    // s_axi / m_axi ready/valid cones. Reset to 0 by rst_n_int.
    `define KM_MBOX_SEP_REGS `SEP_CORE.u_sep_crypto.u_key_manager_s3c_scan.u_mailbox.u_sep_regs
    logic [31:0] km_mbox_sep_wr_err_cnt_q;
    logic [4:0]  km_mbox_sep_wr_err_addr_q;
    always_ff @(posedge clk_i or negedge rst_n_int) begin
        if (!rst_n_int) begin
            km_mbox_sep_wr_err_cnt_q  <= '0;
            km_mbox_sep_wr_err_addr_q <= '0;
        end else if ((`KM_MBOX_SEP_REGS.decoded_err === 1'b1) &&
                     (`KM_MBOX_SEP_REGS.decoded_req_is_wr === 1'b1)) begin
            km_mbox_sep_wr_err_cnt_q  <= km_mbox_sep_wr_err_cnt_q + 32'd1;
            km_mbox_sep_wr_err_addr_q <= `KM_MBOX_SEP_REGS.decoded_addr;
        end
    end
    `undef KM_MBOX_SEP_REGS
    assign km_mbox_sep_wr_err_count_o = km_mbox_sep_wr_err_cnt_q;
    assign km_mbox_sep_wr_err_addr_o  = km_mbox_sep_wr_err_addr_q;

    // Outbound mailbox responder + firmware-console/PASS-magic monitor. The
    // response control (hold, read SLVERR) is an error inject on
    // smn_outbound_axi_resp_i; both inputs are 0 unless a leaf drives them.
    sep_outbound_mbx u_mbx (
        .clk_i           (clk_i),
        .rst_ni          (rst_n_int),
        .req_i           (smn_outbound_req_w),
        .resp_o          (smn_outbound_resp_w),
        .resp_hold_i     (smn_outbound_resp_hold_i),
        .rd_slverr_i     (smn_outbound_rd_slverr_i),
        .ready_stall_i   (smn_outbound_ready_stall_i),
        .rd_addr_data_i  (smn_outbound_rd_addr_data_i),
        .fw_done_o       (fw_done_o),
        .fw_pass_o       (fw_pass_o),
        .fw_char_o       (fw_char_o),
        .fw_char_valid_o (fw_char_valid_o)
    );

    // Response: present the CPU LSU demux slave response back to the cocotb master.
    assign s_axi_awready = `SEP_CORE.u_sep_cpu.lsu_axi_resp.aw_ready;
    assign s_axi_wready  = `SEP_CORE.u_sep_cpu.lsu_axi_resp.w_ready;
    assign s_axi_bid     = `SEP_CORE.u_sep_cpu.lsu_axi_resp.b.id;
    assign s_axi_bresp   = `SEP_CORE.u_sep_cpu.lsu_axi_resp.b.resp;
    assign s_axi_buser   = `SEP_CORE.u_sep_cpu.lsu_axi_resp.b.user;
    assign s_axi_bvalid  = `SEP_CORE.u_sep_cpu.lsu_axi_resp.b_valid;
    assign s_axi_arready = `SEP_CORE.u_sep_cpu.lsu_axi_resp.ar_ready;
    assign s_axi_rid     = `SEP_CORE.u_sep_cpu.lsu_axi_resp.r.id;
    assign s_axi_rdata   = `SEP_CORE.u_sep_cpu.lsu_axi_resp.r.data;
    assign s_axi_rresp   = `SEP_CORE.u_sep_cpu.lsu_axi_resp.r.resp;
    assign s_axi_rlast   = `SEP_CORE.u_sep_cpu.lsu_axi_resp.r.last;
    assign s_axi_ruser   = `SEP_CORE.u_sep_cpu.lsu_axi_resp.r.user;
    assign s_axi_rvalid  = `SEP_CORE.u_sep_cpu.lsu_axi_resp.r_valid;

    // ------------------------------------------------------------------
    // AXI protocol checkers (hw/common/dv/vip/ocah_axi_vip/sva).
    //
    // Passive readers on the two TB-driven AXI4 buses. They assert the AMBA
    // IHI 0022 rules the VIP implements: handshake stability, VALID held
    // until READY, X/Z hygiene, burst and size legality, WRAP alignment, the
    // 4KB boundary, WLAST position, WSTRB lane legality, response-before-
    // request ordering, and ID outstanding tracking. They drive nothing.
    //
    // Both buses carry TB-sourced stimulus, so a failure here is a stimulus
    // bug in the VIP or a sequence rather than a DUT bug.
    //
    // The Verilator targets pass no --assert, so Verilator drops the
    // two-state rules; the X-hygiene rules are gated by OCAH_INC_ASSERT
    // (hw/common/assert), which Verilator does not define. The rules are
    // live under VCS.
    //
    // m_axi ties en_i high: it is TB-driven in both run modes. s_axi is gated
    // by the run mode, for the reason stated at its instance. A test that needs
    // a further suppression window drives a TB signal here, never drops the
    // instance.
    // ------------------------------------------------------------------
    // Single-beat WRAP inject (+sep_axi_wrap_len1_inject; error inject,
    // docs/SEP_TB_ARCH.adoc). A WRAP burst with AxLEN = 0 is not a legal AXI4
    // length, so the WRAP-length rule of the checker fires on it. With the
    // plusarg, the checker of a master sees AxBURST = INCR on an AW or AR with
    // AxBURST = WRAP and AxLEN = 0, so it tracks that request as a single-beat
    // burst and checks every other rule on it; the DUT gets the WRAP burst. The
    // owner leaf drives that burst as error injection.
    bit axi_wrap_len1_inject = $test$plusargs("sep_axi_wrap_len1_inject");
    function automatic logic [1:0] sva_burst(input logic [1:0] burst, input logic [7:0] len);
        return (axi_wrap_len1_inject && burst == 2'b10 && len == 8'd0) ? 2'b01 : burst;
    endfunction

    ocah_axi_sva #(
        .IS_LITE    (1'b0),
        .ADDR_WIDTH (56),
        .DATA_WIDTH (64),
        .ID_WIDTH   (6)
    ) u_m_axi_sva (                       // external SMN inbound master
        .aclk    (clk_i),
        .aresetn (rst_ni),
        .en_i    (1'b1),
        .awid    (m_axi_awid),
        .awaddr  (m_axi_awaddr),
        .awlen   (m_axi_awlen),
        .awsize  (m_axi_awsize),
        .awburst (sva_burst(m_axi_awburst, m_axi_awlen)),
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
        .arburst (sva_burst(m_axi_arburst, m_axi_arlen)),
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

    // The s_axi checker watches the CPU-LSU splice, which the TB drives only on
    // the stub build. Under +cpu_boot the EL2 owns that bus, so the checker
    // would be judging the core's own traffic rather than TB stimulus. Static
    // initialisation resolves before any initial block, so the value is settled
    // before the first assertion samples. m_axi stays armed in both modes: it is
    // TB-driven throughout. The SV-UVM shape ANDs in the sep_tb_if runtime
    // enable, so a scenario holds the checker off through the interface.
    bit s_axi_sva_en = !$test$plusargs("cpu_boot");

    ocah_axi_sva #(
        .IS_LITE    (1'b0),
        .ADDR_WIDTH (32),
        .DATA_WIDTH (64),
        .ID_WIDTH   (3)
    ) u_s_axi_sva (                       // CPU LSU master (TB-driven when !cpu_boot)
        .aclk    (clk_i),
        .aresetn (rst_ni),
`ifdef UVM
        .en_i    (s_axi_sva_en && u_tb_if.axi_sva_en),
`else
        .en_i    (s_axi_sva_en),
`endif
        .awid    (s_axi_awid),
        .awaddr  (s_axi_awaddr),
        .awlen   (s_axi_awlen),
        .awsize  (s_axi_awsize),
        .awburst (sva_burst(s_axi_awburst, s_axi_awlen)),
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
        .arburst (sva_burst(s_axi_arburst, s_axi_arlen)),
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

    // ------------------------------------------------------------------
    // Key Manager internal AXI-Lite, CPU side. Every access KM firmware makes
    // to KPV, KMCSR, the DRBG sampler and the mailbox crosses this one port:
    // the KM crossbar has a single slave port wired to the internal picorv32,
    // so no testbench master can reach it.
    //
    // Bound rather than instantiated, so the port names resolve in the Key
    // Manager's own scope. Passive: it needs no stimulus and adds none.
    // IS_LITE=1 drops the burst, ID and exclusive rules an AXI-Lite port does
    // not carry.
    //
    // Enabled only once the warm reset is a known 0 or 1. That reset is
    // conditioned and synchronised, so it reads X until the first clock edge,
    // and comparing VALID against a low reset has no meaning while the reset
    // itself is unknown.
    //
    // This checks PROTOCOL, not data. A register that accepts a write, answers
    // OKAY and stores nothing breaks no rule here, so a green run is not
    // evidence that a KM register write landed.
    bind key_manager ocah_axi_sva #(
        .IS_LITE    (1'b1),
        .ADDR_WIDTH (32),
        .DATA_WIDTH (32),
        .ID_WIDTH   (1)
    ) u_km_axil_sva (
        .aclk    (clk_i),
        .aresetn (rst_warm_sync_n),
        // Names resolve in key_manager. The warm reset is conditioned and
        // synchronised and the CPU's valids follow it, so both read X before
        // the first edge; comparing VALID against a low reset says nothing
        // while either is undefined.
        .en_i    (!$isunknown(rst_warm_sync_n)
                  && !$isunknown(cpu_axil_req.aw_valid)
                  && !$isunknown(cpu_axil_req.ar_valid)),
        .awid    (1'b0),
        .awaddr  (cpu_axil_req.aw.addr),
        .awlen   (8'd0),
        .awsize  (3'd2),
        .awburst (2'b01),
        .awlock  (1'b0),
        .awprot  (cpu_axil_req.aw.prot),
        .awvalid (cpu_axil_req.aw_valid),
        .awready (cpu_axil_resp.aw_ready),
        .wdata   (cpu_axil_req.w.data),
        .wstrb   (cpu_axil_req.w.strb),
        .wlast   (1'b1),
        .wvalid  (cpu_axil_req.w_valid),
        .wready  (cpu_axil_resp.w_ready),
        .bid     (1'b0),
        .bresp   (cpu_axil_resp.b.resp),
        .bvalid  (cpu_axil_resp.b_valid),
        .bready  (cpu_axil_req.b_ready),
        .arid    (1'b0),
        .araddr  (cpu_axil_req.ar.addr),
        .arlen   (8'd0),
        .arsize  (3'd2),
        .arburst (2'b01),
        .arlock  (1'b0),
        .arprot  (cpu_axil_req.ar.prot),
        .arvalid (cpu_axil_req.ar_valid),
        .arready (cpu_axil_resp.ar_ready),
        .rid     (1'b0),
        .rdata   (cpu_axil_resp.r.data),
        .rresp   (cpu_axil_resp.r.resp),
        .rlast   (1'b1),
        .rvalid  (cpu_axil_resp.r_valid),
        .rready  (cpu_axil_req.r_ready)
    );


`ifdef UVM
    // ------------------------------------------------------------------
    // SV-UVM harness (`--dut sep --framework uvm`): the four clocks, the
    // shared-VIP interface instances on the CPU-LSU splice, quiescent
    // tie-offs for every other cocotb-driven stimulus pin, uvm_config_db
    // publication, and run_test(). Compiled only when the native uvm flow
    // defines UVM; the cocotb flow sees only the ported module above.
    // ------------------------------------------------------------------
    import uvm_pkg::*;

    sep_tb_if u_tb_if ();

    // Four free-running clocks with the periods the env publishes on
    // sep_tb_if (cocotb SepEnvCfg parity: sys 1.25 ns, WDT 5000 ns,
    // entropy sample 3 ns, reference 10 ns).
    initial begin
        clk_i                     = 1'b0;
        clk_wdt_i                 = 1'b0;
        entropy_rosc_sample_clk_i = 1'b0;
        clk_ref_i                 = 1'b0;
    end
    always #(u_tb_if.sys_clk_period_ns * 0.5ns) clk_i = ~clk_i;
    always #(u_tb_if.wdt_clk_period_ns * 0.5ns) clk_wdt_i = ~clk_wdt_i;
    always #(u_tb_if.entropy_clk_period_ns * 0.5ns)
        entropy_rosc_sample_clk_i = ~entropy_rosc_sample_clk_i;
    always #(u_tb_if.ref_clk_period_ns * 0.5ns) clk_ref_i = ~clk_ref_i;

    // The primary reset and the boot/run controls are test-sequenced through
    // sep_tb_if; the fabric-release and reset observables are mirrored back
    // for the sequences and the scoreboard.
    assign rst_ni              = u_tb_if.rst_n;
    assign ext_boot_seq_done_i = u_tb_if.ext_boot_seq_done;
    assign mpc_reset_run_req   = u_tb_if.mpc_reset_run_req;
    assign wdt_rst_ni_i        = u_tb_if.wdt_rst_n;
    assign dbg_rstb_i          = u_tb_if.dbg_rstb;
    assign test_en_strap_i     = u_tb_if.test_en_strap;
    assign u_tb_if.fuse_sense_done              = sep_fuse_sense_done_o;
    assign u_tb_if.sep_reset_n                  = dbg_sep_reset_n_o;
    assign u_tb_if.sep_cpu_reset_n              = sep_cpu_reset_n_o;
    assign u_tb_if.secure_tm                    = secure_tm_o;
    assign u_tb_if.dbg_disable_smc_otp_jtag2axi = dbg_disable_smc_otp_jtag2axi_o;
    assign u_tb_if.dbg_disable_sep_otp_jtag2axi = dbg_disable_sep_otp_jtag2axi_o;

    // Reset assertion counter: the scoreboard predictors re-baseline their
    // CSR shadows on it.
    logic [31:0] rst_assert_count = '0;
    always @(negedge rst_ni) rst_assert_count <= rst_assert_count + 32'd1;
    assign u_tb_if.rst_assert_count = rst_assert_count;

    // Observation probes the sequences read through sep_tb_if.
    assign u_tb_if.sep_internal_interrupts   = sep_internal_interrupts_probe_o;
    assign u_tb_if.efuse_shadow              = efuse_shadow_probe_o;
    assign u_tb_if.otbn_imem_req_count       = otbn_imem_req_count_o;
    assign u_tb_if.otbn_imem_write_count     = otbn_imem_write_count_o;
    assign u_tb_if.otbn_dmem_req_count       = otbn_dmem_req_count_o;
    assign u_tb_if.otbn_dmem_write_count     = otbn_dmem_write_count_o;
    assign u_tb_if.km_rom_req_count          = km_rom_req_count_o;
    assign u_tb_if.km_sram_probe             = km_sram_probe_o;
    assign u_tb_if.km_sram_rd_accept_count   = km_sram_rd_accept_count_o;
    assign u_tb_if.km_sram_rd_b2b_diff_count = km_sram_rd_b2b_diff_count_o;
    assign u_tb_if.km_sram_rd_lat1_count     = km_sram_rd_lat1_count_o;
    assign u_tb_if.km_sram_rd_lat_err_count  = km_sram_rd_lat_err_count_o;
    assign u_tb_if.km_sram_req_count         = km_sram_req_count_o;
    assign u_tb_if.km_sram_scr_rd_count      = km_sram_scr_rd_count_o;
    assign u_tb_if.km_sram_scr_wr_addr       = km_sram_scr_wr_addr_o;
    assign u_tb_if.km_sram_scr_wr_cell       = km_sram_scr_wr_cell_o;
    assign u_tb_if.km_sram_scr_wr_count      = km_sram_scr_wr_count_o;
    assign u_tb_if.km_sram_scr_wr_data       = km_sram_scr_wr_data_o;
    assign u_tb_if.km_sram_word0             = km_sram_word0_o;
    assign u_tb_if.km_sram_write_count       = km_sram_write_count_o;

    // CPU-LSU initiator: the shared ocah_axi_vip UVM master agent drives the
    // s_axi_* request side (the agent's driver procedurally drives the
    // request payloads and valids plus bready/rready on the master
    // interface, routed into lsu_req_drive above) and the TB wires only the
    // DUT-driven response signals back in. Geometry (32/64/3) lives in the
    // master cfg; the interface uses the default maximum widths.
    ocah_axi_if u_lsu_master_if (.aclk(clk_i), .aresetn(rst_ni));
    assign s_axi_awid     = u_lsu_master_if.awid[2:0];
    assign s_axi_awaddr   = u_lsu_master_if.awaddr[31:0];
    assign s_axi_awlen    = u_lsu_master_if.awlen;
    assign s_axi_awsize   = u_lsu_master_if.awsize;
    assign s_axi_awburst  = u_lsu_master_if.awburst;
    assign s_axi_awlock   = u_lsu_master_if.awlock;
    assign s_axi_awcache  = u_lsu_master_if.awcache;
    assign s_axi_awprot   = u_lsu_master_if.awprot;
    assign s_axi_awqos    = u_lsu_master_if.awqos;
    assign s_axi_awregion = u_lsu_master_if.awregion;
    assign s_axi_awuser   = u_lsu_master_if.awuser[11:0];
    assign s_axi_awvalid  = u_lsu_master_if.awvalid;
    assign s_axi_wdata    = u_lsu_master_if.wdata;
    assign s_axi_wstrb    = u_lsu_master_if.wstrb;
    assign s_axi_wlast    = u_lsu_master_if.wlast;
    assign s_axi_wuser    = u_lsu_master_if.wuser[11:0];
    assign s_axi_wvalid   = u_lsu_master_if.wvalid;
    assign s_axi_bready   = u_lsu_master_if.bready;
    assign s_axi_arid     = u_lsu_master_if.arid[2:0];
    assign s_axi_araddr   = u_lsu_master_if.araddr[31:0];
    assign s_axi_arlen    = u_lsu_master_if.arlen;
    assign s_axi_arsize   = u_lsu_master_if.arsize;
    assign s_axi_arburst  = u_lsu_master_if.arburst;
    assign s_axi_arlock   = u_lsu_master_if.arlock;
    assign s_axi_arcache  = u_lsu_master_if.arcache;
    assign s_axi_arprot   = u_lsu_master_if.arprot;
    assign s_axi_arqos    = u_lsu_master_if.arqos;
    assign s_axi_arregion = u_lsu_master_if.arregion;
    assign s_axi_aruser   = u_lsu_master_if.aruser[11:0];
    assign s_axi_arvalid  = u_lsu_master_if.arvalid;
    assign s_axi_rready   = u_lsu_master_if.rready;

    // Response side: DUT subordinate -> agent driver/monitor.
    assign u_lsu_master_if.awready = s_axi_awready;
    assign u_lsu_master_if.wready  = s_axi_wready;
    assign u_lsu_master_if.bid     = 16'(s_axi_bid);
    assign u_lsu_master_if.bresp   = s_axi_bresp;
    assign u_lsu_master_if.buser   = 16'(s_axi_buser);
    assign u_lsu_master_if.bvalid  = s_axi_bvalid;
    assign u_lsu_master_if.arready = s_axi_arready;
    assign u_lsu_master_if.rid     = 16'(s_axi_rid);
    assign u_lsu_master_if.rdata   = s_axi_rdata;
    assign u_lsu_master_if.rresp   = s_axi_rresp;
    assign u_lsu_master_if.rlast   = s_axi_rlast;
    assign u_lsu_master_if.ruser   = 16'(s_axi_ruser);
    assign u_lsu_master_if.rvalid  = s_axi_rvalid;

    // Passive mirror of the CPU-LSU bus for the shared-VIP monitor (the
    // sep_scoreboard predictors consume its item stream), wired from the
    // DUT-facing flat nets only. The protocol SVA on this bus is the
    // u_s_axi_sva instance of the shared body, enabled through
    // u_tb_if.axi_sva_en in this shape.
    ocah_axi_if u_lsu_axi_if (.aclk(clk_i), .aresetn(rst_ni));
    assign u_lsu_axi_if.awid     = 16'(s_axi_awid);
    assign u_lsu_axi_if.awaddr   = 64'(s_axi_awaddr);
    assign u_lsu_axi_if.awlen    = s_axi_awlen;
    assign u_lsu_axi_if.awsize   = s_axi_awsize;
    assign u_lsu_axi_if.awburst  = s_axi_awburst;
    assign u_lsu_axi_if.awlock   = s_axi_awlock;
    assign u_lsu_axi_if.awcache  = s_axi_awcache;
    assign u_lsu_axi_if.awprot   = s_axi_awprot;
    assign u_lsu_axi_if.awqos    = s_axi_awqos;
    assign u_lsu_axi_if.awregion = s_axi_awregion;
    assign u_lsu_axi_if.awuser   = 16'(s_axi_awuser);
    assign u_lsu_axi_if.awvalid  = s_axi_awvalid;
    assign u_lsu_axi_if.awready  = s_axi_awready;
    assign u_lsu_axi_if.wdata    = s_axi_wdata;
    assign u_lsu_axi_if.wstrb    = s_axi_wstrb;
    assign u_lsu_axi_if.wlast    = s_axi_wlast;
    assign u_lsu_axi_if.wuser    = 16'(s_axi_wuser);
    assign u_lsu_axi_if.wvalid   = s_axi_wvalid;
    assign u_lsu_axi_if.wready   = s_axi_wready;
    assign u_lsu_axi_if.bid      = 16'(s_axi_bid);
    assign u_lsu_axi_if.bresp    = s_axi_bresp;
    assign u_lsu_axi_if.buser    = 16'(s_axi_buser);
    assign u_lsu_axi_if.bvalid   = s_axi_bvalid;
    assign u_lsu_axi_if.bready   = s_axi_bready;
    assign u_lsu_axi_if.arid     = 16'(s_axi_arid);
    assign u_lsu_axi_if.araddr   = 64'(s_axi_araddr);
    assign u_lsu_axi_if.arlen    = s_axi_arlen;
    assign u_lsu_axi_if.arsize   = s_axi_arsize;
    assign u_lsu_axi_if.arburst  = s_axi_arburst;
    assign u_lsu_axi_if.arlock   = s_axi_arlock;
    assign u_lsu_axi_if.arcache  = s_axi_arcache;
    assign u_lsu_axi_if.arprot   = s_axi_arprot;
    assign u_lsu_axi_if.arqos    = s_axi_arqos;
    assign u_lsu_axi_if.arregion = s_axi_arregion;
    assign u_lsu_axi_if.aruser   = 16'(s_axi_aruser);
    assign u_lsu_axi_if.arvalid  = s_axi_arvalid;
    assign u_lsu_axi_if.arready  = s_axi_arready;
    assign u_lsu_axi_if.rid      = 16'(s_axi_rid);
    assign u_lsu_axi_if.rdata    = s_axi_rdata;
    assign u_lsu_axi_if.rresp    = s_axi_rresp;
    assign u_lsu_axi_if.rlast    = s_axi_rlast;
    assign u_lsu_axi_if.ruser    = 16'(s_axi_ruser);
    assign u_lsu_axi_if.rvalid   = s_axi_rvalid;
    assign u_lsu_axi_if.rready   = s_axi_rready;

    // ------------------------------------------------------------------
    // Quiescent tie-offs: every other cocotb-driven stimulus pin at the idle
    // value the cocotb sep_base_test.drive_idle_defaults sets. A scenario
    // that needs one of these pins promotes it into sep_tb_if; nothing here
    // is driven from class code.
    // ------------------------------------------------------------------

    // SMN-inbound external AXI4 master and the SEP-OTP JTAG AXI-Lite master:
    // no initiator attached, request side idle, response acceptors ready.
    assign m_axi_awid     = '0;
    assign m_axi_awaddr   = '0;
    assign m_axi_awlen    = '0;
    assign m_axi_awsize   = '0;
    assign m_axi_awburst  = '0;
    assign m_axi_awlock   = 1'b0;
    assign m_axi_awcache  = '0;
    assign m_axi_awprot   = '0;
    assign m_axi_awqos    = '0;
    assign m_axi_awregion = '0;
    assign m_axi_awuser   = '0;
    assign m_axi_awvalid  = 1'b0;
    assign m_axi_wdata    = '0;
    assign m_axi_wstrb    = '0;
    assign m_axi_wlast    = 1'b0;
    assign m_axi_wuser    = '0;
    assign m_axi_wvalid   = 1'b0;
    assign m_axi_bready   = 1'b1;
    assign m_axi_arid     = '0;
    assign m_axi_araddr   = '0;
    assign m_axi_arlen    = '0;
    assign m_axi_arsize   = '0;
    assign m_axi_arburst  = '0;
    assign m_axi_arlock   = 1'b0;
    assign m_axi_arcache  = '0;
    assign m_axi_arprot   = '0;
    assign m_axi_arqos    = '0;
    assign m_axi_arregion = '0;
    assign m_axi_aruser   = '0;
    assign m_axi_arvalid  = 1'b0;
    assign m_axi_rready   = 1'b1;

    assign j_axi_awaddr  = '0;
    assign j_axi_awprot  = '0;
    assign j_axi_awvalid = 1'b0;
    assign j_axi_wdata   = '0;
    assign j_axi_wstrb   = '0;
    assign j_axi_wvalid  = 1'b0;
    assign j_axi_bready  = 1'b1;
    assign j_axi_araddr  = '0;
    assign j_axi_arprot  = '0;
    assign j_axi_arvalid = 1'b0;
    assign j_axi_rready  = 1'b1;

    // JTAG SW-reset holds released; LC, token-comparator, and DMA integrity
    // injects off; CPU-boot controls idle; raw noise quiet; SPI MISO
    // idle-high.
    assign jtag_otbn_rst_hold_i     = 1'b0;
    assign jtag_aes_rst_hold_i      = 1'b0;
    assign jtag_hmac_rst_hold_i     = 1'b0;
    assign jtag_kmac_rst_hold_i     = 1'b0;
    assign jtag_trng_rst_hold_i     = 1'b0;
    assign jtag_sep_reset_n_ovrd_i  = 1'b0;
    assign jtag_sep_reset_n_val_i   = 1'b0;
    assign jtag_ic_reset_tdr_en_i   = 1'b0;
    assign jtag_ic_reset_tck_i      = 1'b0;
    assign jtag_ic_reset_select_i   = 1'b0;
    assign jtag_ic_reset_capture_en_i = 1'b0;
    assign jtag_ic_reset_shift_en_i = 1'b0;
    assign jtag_ic_reset_update_en_i = 1'b0;
    assign jtag_ic_reset_rst_n_i    = 1'b1;
    assign jtag_ic_reset_trst_n_i   = 1'b1;
    assign jtag_ic_reset_tdi_i      = 1'b0;
    assign lc_sigint_inject_i       = 1'b0;
    assign token_cmp_fault_inject_i = '0;
    assign token_cmp_fault_sel_i    = '0;
    assign token_cmp_fault_copy_i   = '0;
    assign token_digest_test_en_inject_i = 1'b0;
    assign token_digest_chiplet_test_en_inject_i = 1'b0;
    assign token_digest_sdis_test_en_inject_i = 1'b0;
    assign jtag_filter_lc_sigint_inject_i = 1'b0;
    assign efuse_sense_status_inject_i = 1'b0;
    assign efuse_sense_status_word_i = '0;
    assign efuse_shim_resp_hold_i   = 1'b0;
    assign dma_host_intg_inject_i   = 1'b0;
    assign hmac_fifo_drain_stall_i  = 1'b0;
    assign kmac_fifo_drain_stall_i  = 1'b0;
    assign crypto_alert_inject_i    = 1'b0;
    assign crypto_alert_inject_idx_i = '0;
    assign crypto_alert_inject_val_i = 1'b0;
    assign esrc_fifo_parity_inject_i = 1'b0;
    assign esrc_fifo_parity_bit_i   = '0;
    assign esrc_fifo_ptr_inject_i   = 1'b0;
    assign esrc_fifo_ptr_sel_i      = '0;
    assign esrc_fifo_ptr_bit_i      = '0;
    assign esrc_noise_stuck_en_i    = '0;
    assign esrc_noise_stuck_val_i   = '0;
    assign ext_trng_drive_en_i      = '0;
    assign ext_trng_tvalid_i        = '0;
    assign ext_trng_tdata_i         = '0;
    assign ext_trng_tstrb_i         = '0;
    assign ext_trng_irq_drive_i     = 1'b0;
    assign sep_ext_interrupts_i     = '0;
    assign smn_outbound_resp_hold_i = 1'b0;
    assign smn_outbound_rd_slverr_i = 1'b0;
    assign smn_outbound_ready_stall_i = '0;
    assign smn_outbound_rd_addr_data_i = 1'b0;
    assign rst_vec_i                = '0;
    assign jtag_id_i                = '0;
    assign i_cpu_run_req_i          = 1'b0;
    assign tcm_load_i               = 1'b0;
    assign esrc_noise_ext_i         = '0;
    assign spi_miso_i               = 1'b1;
    assign spi_sd_i                 = 4'h0;
    assign test_en_i                = 1'b0;
    assign scan_rst_ni_i            = 1'b1;
    assign dmi_core_enable_i        = 1'b0;
    assign dmi_uncore_enable_i      = 1'b0;
    assign jtag_bench_own_i         = 1'b0;
    assign jtag_tck_i               = 1'b0;
    assign jtag_tms_i               = 1'b0;
    assign jtag_tdi_i               = 1'b0;
    assign jtag_trst_n_i            = 1'b0;
    assign tcm_flip_i               = 1'b0;
    assign tcm_flip_addr_i          = '0;
    assign tcm_flip_mask_i          = '0;
    assign rom_flip_i               = 1'b0;
    assign rom_flip_index_i         = '0;
    assign rom_flip_mask_i          = '0;

    // Test classes compile as part of this top (module scope).
    `include "sep_tests.sv"

    initial begin
        uvm_config_db#(virtual sep_tb_if)::set(null, "*", "tb_vif", u_tb_if);
        uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "lsu_master_vif", u_lsu_master_if);
        uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "lsu_axi_vif", u_lsu_axi_if);
        run_test();
    end
`endif

    // ------------------------------------------------------------------
    // Functional-coverage sampler (docs/SEP_FCOV.adoc).
    //
    // Passive: it drives nothing and has no output. VCS only -- Verilator does
    // not compile `covergroup`, and cov/sv/sep_fcov.sv is `ifndef VERILATOR`,
    // so there is no module to bind on the Verilator targets.
    //
    // The response side (`lsu_axi_resp`) is mirrored to the flat s_axi_* outputs
    // above; the REQUEST side (`lsu_axi_req` AW/W/AR and B/R ready) is read only
    // here and is not one of the named probe ports in sep_tb_signal_list.svh.
    //
    // The flat s_axi_* inputs carry TB stimulus only: under +cpu_boot the EL2 owns
    // this bus and the input ports sit idle, so a port-side sampler scores nothing
    // on any firmware test -- no DMA, SPI-DMA, boot-ROM LSU, mailbox or NMI cell
    // could ever fill. The request bus is the same node the no-CPU builds
    // force-splice (see the CPU-LSU AXI splice above), read-only, with no force
    // and no new hierarchy depth.
    // ------------------------------------------------------------------
`ifndef VERILATOR
    // Fabric sampler taps (docs/SEP_FCOV.adoc, fabric and remap groups, Sampler
    // taps): read-only copies of the filter, alias and output remap register
    // fields, one explicit assign per index.
    logic [15:0]       fcov_in_f_en, fcov_in_f_rd, fcov_in_f_wr, fcov_in_f_ns, fcov_in_f_burst;
    logic [15:0][3:0]  fcov_in_f_src;
    logic [15:0][55:0] fcov_in_f_start, fcov_in_f_end;
    logic [31:0]       fcov_out_f_en, fcov_out_f_rd, fcov_out_f_wr, fcov_out_f_ns, fcov_out_f_burst;
    logic [31:0][3:0]  fcov_out_f_src;
    logic [31:0][55:0] fcov_out_f_start, fcov_out_f_end;
    logic [15:0]       fcov_al_valid, fcov_ap_valid, fcov_stee_valid;
    logic [15:0][3:0]  fcov_al_cache;
    logic [15:0][43:0] fcov_al_start, fcov_al_end, fcov_al_offset;
    assign fcov_in_f_en[0]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[0].FILTER_CONFIG.entry_enabled.value;
    assign fcov_in_f_rd[0]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[0].FILTER_CONFIG.read_allowed.value;
    assign fcov_in_f_wr[0]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[0].FILTER_CONFIG.write_allowed.value;
    assign fcov_in_f_ns[0]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[0].FILTER_CONFIG.allow_ns.value;
    assign fcov_in_f_burst[0] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[0].FILTER_CONFIG.allow_burst.value;
    assign fcov_in_f_src[0]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[0].FILTER_CONFIG.src_id.value;
    assign fcov_in_f_start[0] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[0].START_ADDR.start_addr.value;
    assign fcov_in_f_end[0]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[0].END_ADDR.end_addr.value;
    assign fcov_in_f_en[1]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[1].FILTER_CONFIG.entry_enabled.value;
    assign fcov_in_f_rd[1]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[1].FILTER_CONFIG.read_allowed.value;
    assign fcov_in_f_wr[1]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[1].FILTER_CONFIG.write_allowed.value;
    assign fcov_in_f_ns[1]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[1].FILTER_CONFIG.allow_ns.value;
    assign fcov_in_f_burst[1] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[1].FILTER_CONFIG.allow_burst.value;
    assign fcov_in_f_src[1]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[1].FILTER_CONFIG.src_id.value;
    assign fcov_in_f_start[1] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[1].START_ADDR.start_addr.value;
    assign fcov_in_f_end[1]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[1].END_ADDR.end_addr.value;
    assign fcov_in_f_en[2]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[2].FILTER_CONFIG.entry_enabled.value;
    assign fcov_in_f_rd[2]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[2].FILTER_CONFIG.read_allowed.value;
    assign fcov_in_f_wr[2]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[2].FILTER_CONFIG.write_allowed.value;
    assign fcov_in_f_ns[2]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[2].FILTER_CONFIG.allow_ns.value;
    assign fcov_in_f_burst[2] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[2].FILTER_CONFIG.allow_burst.value;
    assign fcov_in_f_src[2]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[2].FILTER_CONFIG.src_id.value;
    assign fcov_in_f_start[2] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[2].START_ADDR.start_addr.value;
    assign fcov_in_f_end[2]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[2].END_ADDR.end_addr.value;
    assign fcov_in_f_en[3]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[3].FILTER_CONFIG.entry_enabled.value;
    assign fcov_in_f_rd[3]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[3].FILTER_CONFIG.read_allowed.value;
    assign fcov_in_f_wr[3]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[3].FILTER_CONFIG.write_allowed.value;
    assign fcov_in_f_ns[3]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[3].FILTER_CONFIG.allow_ns.value;
    assign fcov_in_f_burst[3] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[3].FILTER_CONFIG.allow_burst.value;
    assign fcov_in_f_src[3]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[3].FILTER_CONFIG.src_id.value;
    assign fcov_in_f_start[3] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[3].START_ADDR.start_addr.value;
    assign fcov_in_f_end[3]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[3].END_ADDR.end_addr.value;
    assign fcov_in_f_en[4]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[4].FILTER_CONFIG.entry_enabled.value;
    assign fcov_in_f_rd[4]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[4].FILTER_CONFIG.read_allowed.value;
    assign fcov_in_f_wr[4]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[4].FILTER_CONFIG.write_allowed.value;
    assign fcov_in_f_ns[4]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[4].FILTER_CONFIG.allow_ns.value;
    assign fcov_in_f_burst[4] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[4].FILTER_CONFIG.allow_burst.value;
    assign fcov_in_f_src[4]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[4].FILTER_CONFIG.src_id.value;
    assign fcov_in_f_start[4] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[4].START_ADDR.start_addr.value;
    assign fcov_in_f_end[4]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[4].END_ADDR.end_addr.value;
    assign fcov_in_f_en[5]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[5].FILTER_CONFIG.entry_enabled.value;
    assign fcov_in_f_rd[5]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[5].FILTER_CONFIG.read_allowed.value;
    assign fcov_in_f_wr[5]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[5].FILTER_CONFIG.write_allowed.value;
    assign fcov_in_f_ns[5]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[5].FILTER_CONFIG.allow_ns.value;
    assign fcov_in_f_burst[5] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[5].FILTER_CONFIG.allow_burst.value;
    assign fcov_in_f_src[5]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[5].FILTER_CONFIG.src_id.value;
    assign fcov_in_f_start[5] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[5].START_ADDR.start_addr.value;
    assign fcov_in_f_end[5]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[5].END_ADDR.end_addr.value;
    assign fcov_in_f_en[6]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[6].FILTER_CONFIG.entry_enabled.value;
    assign fcov_in_f_rd[6]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[6].FILTER_CONFIG.read_allowed.value;
    assign fcov_in_f_wr[6]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[6].FILTER_CONFIG.write_allowed.value;
    assign fcov_in_f_ns[6]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[6].FILTER_CONFIG.allow_ns.value;
    assign fcov_in_f_burst[6] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[6].FILTER_CONFIG.allow_burst.value;
    assign fcov_in_f_src[6]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[6].FILTER_CONFIG.src_id.value;
    assign fcov_in_f_start[6] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[6].START_ADDR.start_addr.value;
    assign fcov_in_f_end[6]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[6].END_ADDR.end_addr.value;
    assign fcov_in_f_en[7]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[7].FILTER_CONFIG.entry_enabled.value;
    assign fcov_in_f_rd[7]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[7].FILTER_CONFIG.read_allowed.value;
    assign fcov_in_f_wr[7]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[7].FILTER_CONFIG.write_allowed.value;
    assign fcov_in_f_ns[7]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[7].FILTER_CONFIG.allow_ns.value;
    assign fcov_in_f_burst[7] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[7].FILTER_CONFIG.allow_burst.value;
    assign fcov_in_f_src[7]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[7].FILTER_CONFIG.src_id.value;
    assign fcov_in_f_start[7] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[7].START_ADDR.start_addr.value;
    assign fcov_in_f_end[7]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[7].END_ADDR.end_addr.value;
    assign fcov_in_f_en[8]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[8].FILTER_CONFIG.entry_enabled.value;
    assign fcov_in_f_rd[8]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[8].FILTER_CONFIG.read_allowed.value;
    assign fcov_in_f_wr[8]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[8].FILTER_CONFIG.write_allowed.value;
    assign fcov_in_f_ns[8]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[8].FILTER_CONFIG.allow_ns.value;
    assign fcov_in_f_burst[8] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[8].FILTER_CONFIG.allow_burst.value;
    assign fcov_in_f_src[8]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[8].FILTER_CONFIG.src_id.value;
    assign fcov_in_f_start[8] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[8].START_ADDR.start_addr.value;
    assign fcov_in_f_end[8]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[8].END_ADDR.end_addr.value;
    assign fcov_in_f_en[9]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[9].FILTER_CONFIG.entry_enabled.value;
    assign fcov_in_f_rd[9]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[9].FILTER_CONFIG.read_allowed.value;
    assign fcov_in_f_wr[9]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[9].FILTER_CONFIG.write_allowed.value;
    assign fcov_in_f_ns[9]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[9].FILTER_CONFIG.allow_ns.value;
    assign fcov_in_f_burst[9] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[9].FILTER_CONFIG.allow_burst.value;
    assign fcov_in_f_src[9]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[9].FILTER_CONFIG.src_id.value;
    assign fcov_in_f_start[9] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[9].START_ADDR.start_addr.value;
    assign fcov_in_f_end[9]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[9].END_ADDR.end_addr.value;
    assign fcov_in_f_en[10]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[10].FILTER_CONFIG.entry_enabled.value;
    assign fcov_in_f_rd[10]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[10].FILTER_CONFIG.read_allowed.value;
    assign fcov_in_f_wr[10]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[10].FILTER_CONFIG.write_allowed.value;
    assign fcov_in_f_ns[10]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[10].FILTER_CONFIG.allow_ns.value;
    assign fcov_in_f_burst[10] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[10].FILTER_CONFIG.allow_burst.value;
    assign fcov_in_f_src[10]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[10].FILTER_CONFIG.src_id.value;
    assign fcov_in_f_start[10] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[10].START_ADDR.start_addr.value;
    assign fcov_in_f_end[10]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[10].END_ADDR.end_addr.value;
    assign fcov_in_f_en[11]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[11].FILTER_CONFIG.entry_enabled.value;
    assign fcov_in_f_rd[11]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[11].FILTER_CONFIG.read_allowed.value;
    assign fcov_in_f_wr[11]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[11].FILTER_CONFIG.write_allowed.value;
    assign fcov_in_f_ns[11]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[11].FILTER_CONFIG.allow_ns.value;
    assign fcov_in_f_burst[11] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[11].FILTER_CONFIG.allow_burst.value;
    assign fcov_in_f_src[11]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[11].FILTER_CONFIG.src_id.value;
    assign fcov_in_f_start[11] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[11].START_ADDR.start_addr.value;
    assign fcov_in_f_end[11]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[11].END_ADDR.end_addr.value;
    assign fcov_in_f_en[12]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[12].FILTER_CONFIG.entry_enabled.value;
    assign fcov_in_f_rd[12]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[12].FILTER_CONFIG.read_allowed.value;
    assign fcov_in_f_wr[12]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[12].FILTER_CONFIG.write_allowed.value;
    assign fcov_in_f_ns[12]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[12].FILTER_CONFIG.allow_ns.value;
    assign fcov_in_f_burst[12] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[12].FILTER_CONFIG.allow_burst.value;
    assign fcov_in_f_src[12]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[12].FILTER_CONFIG.src_id.value;
    assign fcov_in_f_start[12] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[12].START_ADDR.start_addr.value;
    assign fcov_in_f_end[12]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[12].END_ADDR.end_addr.value;
    assign fcov_in_f_en[13]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[13].FILTER_CONFIG.entry_enabled.value;
    assign fcov_in_f_rd[13]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[13].FILTER_CONFIG.read_allowed.value;
    assign fcov_in_f_wr[13]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[13].FILTER_CONFIG.write_allowed.value;
    assign fcov_in_f_ns[13]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[13].FILTER_CONFIG.allow_ns.value;
    assign fcov_in_f_burst[13] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[13].FILTER_CONFIG.allow_burst.value;
    assign fcov_in_f_src[13]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[13].FILTER_CONFIG.src_id.value;
    assign fcov_in_f_start[13] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[13].START_ADDR.start_addr.value;
    assign fcov_in_f_end[13]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[13].END_ADDR.end_addr.value;
    assign fcov_in_f_en[14]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[14].FILTER_CONFIG.entry_enabled.value;
    assign fcov_in_f_rd[14]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[14].FILTER_CONFIG.read_allowed.value;
    assign fcov_in_f_wr[14]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[14].FILTER_CONFIG.write_allowed.value;
    assign fcov_in_f_ns[14]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[14].FILTER_CONFIG.allow_ns.value;
    assign fcov_in_f_burst[14] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[14].FILTER_CONFIG.allow_burst.value;
    assign fcov_in_f_src[14]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[14].FILTER_CONFIG.src_id.value;
    assign fcov_in_f_start[14] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[14].START_ADDR.start_addr.value;
    assign fcov_in_f_end[14]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[14].END_ADDR.end_addr.value;
    assign fcov_in_f_en[15]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[15].FILTER_CONFIG.entry_enabled.value;
    assign fcov_in_f_rd[15]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[15].FILTER_CONFIG.read_allowed.value;
    assign fcov_in_f_wr[15]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[15].FILTER_CONFIG.write_allowed.value;
    assign fcov_in_f_ns[15]    = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[15].FILTER_CONFIG.allow_ns.value;
    assign fcov_in_f_burst[15] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[15].FILTER_CONFIG.allow_burst.value;
    assign fcov_in_f_src[15]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[15].FILTER_CONFIG.src_id.value;
    assign fcov_in_f_start[15] = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[15].START_ADDR.start_addr.value;
    assign fcov_in_f_end[15]   = `SEP_CORE.u_sep_system_peripherals.inbound_filter_ctrl[15].END_ADDR.end_addr.value;
    assign fcov_out_f_en[0]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[0].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[0]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[0].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[0]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[0].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[0]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[0].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[0] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[0].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[0]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[0].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[0] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[0].START_ADDR.start_addr.value;
    assign fcov_out_f_end[0]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[0].END_ADDR.end_addr.value;
    assign fcov_out_f_en[1]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[1].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[1]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[1].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[1]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[1].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[1]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[1].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[1] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[1].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[1]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[1].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[1] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[1].START_ADDR.start_addr.value;
    assign fcov_out_f_end[1]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[1].END_ADDR.end_addr.value;
    assign fcov_out_f_en[2]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[2].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[2]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[2].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[2]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[2].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[2]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[2].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[2] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[2].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[2]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[2].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[2] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[2].START_ADDR.start_addr.value;
    assign fcov_out_f_end[2]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[2].END_ADDR.end_addr.value;
    assign fcov_out_f_en[3]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[3].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[3]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[3].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[3]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[3].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[3]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[3].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[3] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[3].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[3]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[3].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[3] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[3].START_ADDR.start_addr.value;
    assign fcov_out_f_end[3]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[3].END_ADDR.end_addr.value;
    assign fcov_out_f_en[4]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[4].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[4]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[4].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[4]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[4].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[4]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[4].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[4] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[4].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[4]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[4].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[4] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[4].START_ADDR.start_addr.value;
    assign fcov_out_f_end[4]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[4].END_ADDR.end_addr.value;
    assign fcov_out_f_en[5]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[5].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[5]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[5].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[5]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[5].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[5]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[5].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[5] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[5].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[5]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[5].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[5] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[5].START_ADDR.start_addr.value;
    assign fcov_out_f_end[5]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[5].END_ADDR.end_addr.value;
    assign fcov_out_f_en[6]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[6].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[6]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[6].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[6]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[6].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[6]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[6].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[6] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[6].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[6]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[6].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[6] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[6].START_ADDR.start_addr.value;
    assign fcov_out_f_end[6]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[6].END_ADDR.end_addr.value;
    assign fcov_out_f_en[7]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[7].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[7]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[7].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[7]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[7].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[7]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[7].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[7] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[7].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[7]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[7].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[7] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[7].START_ADDR.start_addr.value;
    assign fcov_out_f_end[7]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[7].END_ADDR.end_addr.value;
    assign fcov_out_f_en[8]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[8].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[8]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[8].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[8]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[8].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[8]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[8].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[8] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[8].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[8]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[8].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[8] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[8].START_ADDR.start_addr.value;
    assign fcov_out_f_end[8]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[8].END_ADDR.end_addr.value;
    assign fcov_out_f_en[9]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[9].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[9]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[9].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[9]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[9].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[9]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[9].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[9] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[9].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[9]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[9].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[9] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[9].START_ADDR.start_addr.value;
    assign fcov_out_f_end[9]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[9].END_ADDR.end_addr.value;
    assign fcov_out_f_en[10]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[10].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[10]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[10].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[10]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[10].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[10]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[10].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[10] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[10].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[10]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[10].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[10] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[10].START_ADDR.start_addr.value;
    assign fcov_out_f_end[10]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[10].END_ADDR.end_addr.value;
    assign fcov_out_f_en[11]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[11].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[11]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[11].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[11]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[11].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[11]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[11].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[11] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[11].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[11]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[11].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[11] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[11].START_ADDR.start_addr.value;
    assign fcov_out_f_end[11]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[11].END_ADDR.end_addr.value;
    assign fcov_out_f_en[12]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[12].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[12]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[12].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[12]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[12].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[12]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[12].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[12] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[12].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[12]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[12].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[12] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[12].START_ADDR.start_addr.value;
    assign fcov_out_f_end[12]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[12].END_ADDR.end_addr.value;
    assign fcov_out_f_en[13]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[13].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[13]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[13].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[13]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[13].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[13]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[13].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[13] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[13].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[13]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[13].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[13] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[13].START_ADDR.start_addr.value;
    assign fcov_out_f_end[13]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[13].END_ADDR.end_addr.value;
    assign fcov_out_f_en[14]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[14].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[14]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[14].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[14]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[14].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[14]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[14].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[14] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[14].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[14]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[14].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[14] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[14].START_ADDR.start_addr.value;
    assign fcov_out_f_end[14]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[14].END_ADDR.end_addr.value;
    assign fcov_out_f_en[15]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[15].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[15]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[15].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[15]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[15].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[15]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[15].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[15] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[15].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[15]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[15].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[15] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[15].START_ADDR.start_addr.value;
    assign fcov_out_f_end[15]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[15].END_ADDR.end_addr.value;
    assign fcov_out_f_en[16]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[16].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[16]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[16].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[16]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[16].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[16]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[16].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[16] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[16].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[16]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[16].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[16] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[16].START_ADDR.start_addr.value;
    assign fcov_out_f_end[16]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[16].END_ADDR.end_addr.value;
    assign fcov_out_f_en[17]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[17].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[17]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[17].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[17]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[17].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[17]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[17].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[17] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[17].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[17]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[17].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[17] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[17].START_ADDR.start_addr.value;
    assign fcov_out_f_end[17]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[17].END_ADDR.end_addr.value;
    assign fcov_out_f_en[18]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[18].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[18]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[18].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[18]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[18].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[18]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[18].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[18] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[18].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[18]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[18].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[18] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[18].START_ADDR.start_addr.value;
    assign fcov_out_f_end[18]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[18].END_ADDR.end_addr.value;
    assign fcov_out_f_en[19]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[19].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[19]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[19].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[19]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[19].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[19]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[19].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[19] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[19].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[19]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[19].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[19] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[19].START_ADDR.start_addr.value;
    assign fcov_out_f_end[19]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[19].END_ADDR.end_addr.value;
    assign fcov_out_f_en[20]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[20].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[20]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[20].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[20]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[20].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[20]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[20].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[20] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[20].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[20]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[20].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[20] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[20].START_ADDR.start_addr.value;
    assign fcov_out_f_end[20]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[20].END_ADDR.end_addr.value;
    assign fcov_out_f_en[21]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[21].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[21]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[21].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[21]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[21].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[21]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[21].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[21] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[21].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[21]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[21].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[21] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[21].START_ADDR.start_addr.value;
    assign fcov_out_f_end[21]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[21].END_ADDR.end_addr.value;
    assign fcov_out_f_en[22]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[22].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[22]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[22].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[22]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[22].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[22]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[22].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[22] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[22].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[22]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[22].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[22] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[22].START_ADDR.start_addr.value;
    assign fcov_out_f_end[22]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[22].END_ADDR.end_addr.value;
    assign fcov_out_f_en[23]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[23].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[23]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[23].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[23]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[23].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[23]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[23].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[23] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[23].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[23]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[23].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[23] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[23].START_ADDR.start_addr.value;
    assign fcov_out_f_end[23]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[23].END_ADDR.end_addr.value;
    assign fcov_out_f_en[24]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[24].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[24]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[24].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[24]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[24].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[24]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[24].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[24] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[24].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[24]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[24].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[24] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[24].START_ADDR.start_addr.value;
    assign fcov_out_f_end[24]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[24].END_ADDR.end_addr.value;
    assign fcov_out_f_en[25]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[25].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[25]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[25].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[25]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[25].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[25]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[25].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[25] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[25].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[25]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[25].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[25] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[25].START_ADDR.start_addr.value;
    assign fcov_out_f_end[25]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[25].END_ADDR.end_addr.value;
    assign fcov_out_f_en[26]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[26].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[26]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[26].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[26]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[26].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[26]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[26].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[26] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[26].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[26]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[26].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[26] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[26].START_ADDR.start_addr.value;
    assign fcov_out_f_end[26]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[26].END_ADDR.end_addr.value;
    assign fcov_out_f_en[27]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[27].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[27]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[27].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[27]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[27].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[27]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[27].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[27] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[27].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[27]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[27].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[27] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[27].START_ADDR.start_addr.value;
    assign fcov_out_f_end[27]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[27].END_ADDR.end_addr.value;
    assign fcov_out_f_en[28]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[28].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[28]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[28].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[28]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[28].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[28]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[28].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[28] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[28].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[28]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[28].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[28] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[28].START_ADDR.start_addr.value;
    assign fcov_out_f_end[28]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[28].END_ADDR.end_addr.value;
    assign fcov_out_f_en[29]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[29].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[29]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[29].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[29]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[29].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[29]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[29].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[29] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[29].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[29]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[29].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[29] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[29].START_ADDR.start_addr.value;
    assign fcov_out_f_end[29]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[29].END_ADDR.end_addr.value;
    assign fcov_out_f_en[30]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[30].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[30]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[30].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[30]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[30].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[30]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[30].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[30] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[30].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[30]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[30].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[30] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[30].START_ADDR.start_addr.value;
    assign fcov_out_f_end[30]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[30].END_ADDR.end_addr.value;
    assign fcov_out_f_en[31]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[31].FILTER_CONFIG.entry_enabled.value;
    assign fcov_out_f_rd[31]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[31].FILTER_CONFIG.read_allowed.value;
    assign fcov_out_f_wr[31]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[31].FILTER_CONFIG.write_allowed.value;
    assign fcov_out_f_ns[31]    = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[31].FILTER_CONFIG.allow_ns.value;
    assign fcov_out_f_burst[31] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[31].FILTER_CONFIG.allow_burst.value;
    assign fcov_out_f_src[31]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[31].FILTER_CONFIG.src_id.value;
    assign fcov_out_f_start[31] = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[31].START_ADDR.start_addr.value;
    assign fcov_out_f_end[31]   = `SEP_CORE.u_sep_system_peripherals.outbound_filter_ctrl[31].END_ADDR.end_addr.value;
    assign fcov_al_valid[0]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[0].REGION.region_attrs.valid.value;
    assign fcov_al_cache[0]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[0].REGION.region_attrs.cacheable.value;
    assign fcov_al_start[0]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[0].REGION.region_start.start_addr.value;
    assign fcov_al_end[0]    = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[0].REGION.region_end.end_addr.value;
    assign fcov_al_offset[0] = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[0].REGION.region_attrs.offset.value;
    assign fcov_ap_valid[0]   = `SEP_CORE.u_sep_system_peripherals.ap_output_remap_reg_ctrl[0].REGION.region_attrs.valid.value;
    assign fcov_stee_valid[0] = `SEP_CORE.u_sep_system_peripherals.stee_output_remap_reg_ctrl[0].REGION.region_attrs.valid.value;
    assign fcov_al_valid[1]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[1].REGION.region_attrs.valid.value;
    assign fcov_al_cache[1]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[1].REGION.region_attrs.cacheable.value;
    assign fcov_al_start[1]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[1].REGION.region_start.start_addr.value;
    assign fcov_al_end[1]    = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[1].REGION.region_end.end_addr.value;
    assign fcov_al_offset[1] = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[1].REGION.region_attrs.offset.value;
    assign fcov_ap_valid[1]   = `SEP_CORE.u_sep_system_peripherals.ap_output_remap_reg_ctrl[1].REGION.region_attrs.valid.value;
    assign fcov_stee_valid[1] = `SEP_CORE.u_sep_system_peripherals.stee_output_remap_reg_ctrl[1].REGION.region_attrs.valid.value;
    assign fcov_al_valid[2]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[2].REGION.region_attrs.valid.value;
    assign fcov_al_cache[2]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[2].REGION.region_attrs.cacheable.value;
    assign fcov_al_start[2]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[2].REGION.region_start.start_addr.value;
    assign fcov_al_end[2]    = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[2].REGION.region_end.end_addr.value;
    assign fcov_al_offset[2] = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[2].REGION.region_attrs.offset.value;
    assign fcov_ap_valid[2]   = `SEP_CORE.u_sep_system_peripherals.ap_output_remap_reg_ctrl[2].REGION.region_attrs.valid.value;
    assign fcov_stee_valid[2] = `SEP_CORE.u_sep_system_peripherals.stee_output_remap_reg_ctrl[2].REGION.region_attrs.valid.value;
    assign fcov_al_valid[3]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[3].REGION.region_attrs.valid.value;
    assign fcov_al_cache[3]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[3].REGION.region_attrs.cacheable.value;
    assign fcov_al_start[3]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[3].REGION.region_start.start_addr.value;
    assign fcov_al_end[3]    = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[3].REGION.region_end.end_addr.value;
    assign fcov_al_offset[3] = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[3].REGION.region_attrs.offset.value;
    assign fcov_ap_valid[3]   = `SEP_CORE.u_sep_system_peripherals.ap_output_remap_reg_ctrl[3].REGION.region_attrs.valid.value;
    assign fcov_stee_valid[3] = `SEP_CORE.u_sep_system_peripherals.stee_output_remap_reg_ctrl[3].REGION.region_attrs.valid.value;
    assign fcov_al_valid[4]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[4].REGION.region_attrs.valid.value;
    assign fcov_al_cache[4]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[4].REGION.region_attrs.cacheable.value;
    assign fcov_al_start[4]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[4].REGION.region_start.start_addr.value;
    assign fcov_al_end[4]    = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[4].REGION.region_end.end_addr.value;
    assign fcov_al_offset[4] = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[4].REGION.region_attrs.offset.value;
    assign fcov_ap_valid[4]   = `SEP_CORE.u_sep_system_peripherals.ap_output_remap_reg_ctrl[4].REGION.region_attrs.valid.value;
    assign fcov_stee_valid[4] = `SEP_CORE.u_sep_system_peripherals.stee_output_remap_reg_ctrl[4].REGION.region_attrs.valid.value;
    assign fcov_al_valid[5]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[5].REGION.region_attrs.valid.value;
    assign fcov_al_cache[5]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[5].REGION.region_attrs.cacheable.value;
    assign fcov_al_start[5]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[5].REGION.region_start.start_addr.value;
    assign fcov_al_end[5]    = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[5].REGION.region_end.end_addr.value;
    assign fcov_al_offset[5] = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[5].REGION.region_attrs.offset.value;
    assign fcov_ap_valid[5]   = `SEP_CORE.u_sep_system_peripherals.ap_output_remap_reg_ctrl[5].REGION.region_attrs.valid.value;
    assign fcov_stee_valid[5] = `SEP_CORE.u_sep_system_peripherals.stee_output_remap_reg_ctrl[5].REGION.region_attrs.valid.value;
    assign fcov_al_valid[6]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[6].REGION.region_attrs.valid.value;
    assign fcov_al_cache[6]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[6].REGION.region_attrs.cacheable.value;
    assign fcov_al_start[6]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[6].REGION.region_start.start_addr.value;
    assign fcov_al_end[6]    = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[6].REGION.region_end.end_addr.value;
    assign fcov_al_offset[6] = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[6].REGION.region_attrs.offset.value;
    assign fcov_ap_valid[6]   = `SEP_CORE.u_sep_system_peripherals.ap_output_remap_reg_ctrl[6].REGION.region_attrs.valid.value;
    assign fcov_stee_valid[6] = `SEP_CORE.u_sep_system_peripherals.stee_output_remap_reg_ctrl[6].REGION.region_attrs.valid.value;
    assign fcov_al_valid[7]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[7].REGION.region_attrs.valid.value;
    assign fcov_al_cache[7]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[7].REGION.region_attrs.cacheable.value;
    assign fcov_al_start[7]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[7].REGION.region_start.start_addr.value;
    assign fcov_al_end[7]    = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[7].REGION.region_end.end_addr.value;
    assign fcov_al_offset[7] = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[7].REGION.region_attrs.offset.value;
    assign fcov_ap_valid[7]   = `SEP_CORE.u_sep_system_peripherals.ap_output_remap_reg_ctrl[7].REGION.region_attrs.valid.value;
    assign fcov_stee_valid[7] = `SEP_CORE.u_sep_system_peripherals.stee_output_remap_reg_ctrl[7].REGION.region_attrs.valid.value;
    assign fcov_al_valid[8]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[8].REGION.region_attrs.valid.value;
    assign fcov_al_cache[8]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[8].REGION.region_attrs.cacheable.value;
    assign fcov_al_start[8]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[8].REGION.region_start.start_addr.value;
    assign fcov_al_end[8]    = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[8].REGION.region_end.end_addr.value;
    assign fcov_al_offset[8] = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[8].REGION.region_attrs.offset.value;
    assign fcov_ap_valid[8]   = `SEP_CORE.u_sep_system_peripherals.ap_output_remap_reg_ctrl[8].REGION.region_attrs.valid.value;
    assign fcov_stee_valid[8] = `SEP_CORE.u_sep_system_peripherals.stee_output_remap_reg_ctrl[8].REGION.region_attrs.valid.value;
    assign fcov_al_valid[9]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[9].REGION.region_attrs.valid.value;
    assign fcov_al_cache[9]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[9].REGION.region_attrs.cacheable.value;
    assign fcov_al_start[9]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[9].REGION.region_start.start_addr.value;
    assign fcov_al_end[9]    = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[9].REGION.region_end.end_addr.value;
    assign fcov_al_offset[9] = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[9].REGION.region_attrs.offset.value;
    assign fcov_ap_valid[9]   = `SEP_CORE.u_sep_system_peripherals.ap_output_remap_reg_ctrl[9].REGION.region_attrs.valid.value;
    assign fcov_stee_valid[9] = `SEP_CORE.u_sep_system_peripherals.stee_output_remap_reg_ctrl[9].REGION.region_attrs.valid.value;
    assign fcov_al_valid[10]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[10].REGION.region_attrs.valid.value;
    assign fcov_al_cache[10]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[10].REGION.region_attrs.cacheable.value;
    assign fcov_al_start[10]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[10].REGION.region_start.start_addr.value;
    assign fcov_al_end[10]    = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[10].REGION.region_end.end_addr.value;
    assign fcov_al_offset[10] = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[10].REGION.region_attrs.offset.value;
    assign fcov_ap_valid[10]   = `SEP_CORE.u_sep_system_peripherals.ap_output_remap_reg_ctrl[10].REGION.region_attrs.valid.value;
    assign fcov_stee_valid[10] = `SEP_CORE.u_sep_system_peripherals.stee_output_remap_reg_ctrl[10].REGION.region_attrs.valid.value;
    assign fcov_al_valid[11]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[11].REGION.region_attrs.valid.value;
    assign fcov_al_cache[11]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[11].REGION.region_attrs.cacheable.value;
    assign fcov_al_start[11]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[11].REGION.region_start.start_addr.value;
    assign fcov_al_end[11]    = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[11].REGION.region_end.end_addr.value;
    assign fcov_al_offset[11] = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[11].REGION.region_attrs.offset.value;
    assign fcov_ap_valid[11]   = `SEP_CORE.u_sep_system_peripherals.ap_output_remap_reg_ctrl[11].REGION.region_attrs.valid.value;
    assign fcov_stee_valid[11] = `SEP_CORE.u_sep_system_peripherals.stee_output_remap_reg_ctrl[11].REGION.region_attrs.valid.value;
    assign fcov_al_valid[12]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[12].REGION.region_attrs.valid.value;
    assign fcov_al_cache[12]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[12].REGION.region_attrs.cacheable.value;
    assign fcov_al_start[12]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[12].REGION.region_start.start_addr.value;
    assign fcov_al_end[12]    = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[12].REGION.region_end.end_addr.value;
    assign fcov_al_offset[12] = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[12].REGION.region_attrs.offset.value;
    assign fcov_ap_valid[12]   = `SEP_CORE.u_sep_system_peripherals.ap_output_remap_reg_ctrl[12].REGION.region_attrs.valid.value;
    assign fcov_stee_valid[12] = `SEP_CORE.u_sep_system_peripherals.stee_output_remap_reg_ctrl[12].REGION.region_attrs.valid.value;
    assign fcov_al_valid[13]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[13].REGION.region_attrs.valid.value;
    assign fcov_al_cache[13]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[13].REGION.region_attrs.cacheable.value;
    assign fcov_al_start[13]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[13].REGION.region_start.start_addr.value;
    assign fcov_al_end[13]    = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[13].REGION.region_end.end_addr.value;
    assign fcov_al_offset[13] = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[13].REGION.region_attrs.offset.value;
    assign fcov_ap_valid[13]   = `SEP_CORE.u_sep_system_peripherals.ap_output_remap_reg_ctrl[13].REGION.region_attrs.valid.value;
    assign fcov_stee_valid[13] = `SEP_CORE.u_sep_system_peripherals.stee_output_remap_reg_ctrl[13].REGION.region_attrs.valid.value;
    assign fcov_al_valid[14]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[14].REGION.region_attrs.valid.value;
    assign fcov_al_cache[14]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[14].REGION.region_attrs.cacheable.value;
    assign fcov_al_start[14]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[14].REGION.region_start.start_addr.value;
    assign fcov_al_end[14]    = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[14].REGION.region_end.end_addr.value;
    assign fcov_al_offset[14] = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[14].REGION.region_attrs.offset.value;
    assign fcov_ap_valid[14]   = `SEP_CORE.u_sep_system_peripherals.ap_output_remap_reg_ctrl[14].REGION.region_attrs.valid.value;
    assign fcov_stee_valid[14] = `SEP_CORE.u_sep_system_peripherals.stee_output_remap_reg_ctrl[14].REGION.region_attrs.valid.value;
    assign fcov_al_valid[15]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[15].REGION.region_attrs.valid.value;
    assign fcov_al_cache[15]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[15].REGION.region_attrs.cacheable.value;
    assign fcov_al_start[15]  = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[15].REGION.region_start.start_addr.value;
    assign fcov_al_end[15]    = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[15].REGION.region_end.end_addr.value;
    assign fcov_al_offset[15] = `SEP_CORE.u_sep_system_peripherals.local_masters_alias_remap_reg_ctrl[15].REGION.region_attrs.offset.value;
    assign fcov_ap_valid[15]   = `SEP_CORE.u_sep_system_peripherals.ap_output_remap_reg_ctrl[15].REGION.region_attrs.valid.value;
    assign fcov_stee_valid[15] = `SEP_CORE.u_sep_system_peripherals.stee_output_remap_reg_ctrl[15].REGION.region_attrs.valid.value;
`ifdef SEP_CPU_STUB
    // The stub has no pre-alias LSU net; the twin cells need the real CPU.
    sep_pkg::sep_32_64_3_12_axi_req_t fcov_lsu_raw_req = '0;
    wire                              fcov_lsu_raw_live = 1'b0;
`else
    sep_pkg::sep_32_64_3_12_axi_req_t fcov_lsu_raw_req;
    wire                              fcov_lsu_raw_live = 1'b1;
    assign fcov_lsu_raw_req = `SEP_CORE.u_sep_cpu.lsu_axi_req_raw;
`endif

    // Mailbox, IRQ and PIC sampler taps (docs/SEP_FCOV.adoc, mailbox, IRQ and
    // PIC groups, Signal aliases): read-only hierarchical references into the
    // CPU (PIC, CLAIM, TLU), the mailbox unit (MB[m]) and the inbound filter
    // (FILT). No force. The PIC, CLAIM and TLU exist only with the full core;
    // the stub build ties them to 0.
`ifndef SEP_CPU_STUB
`define SEP_FCOV_PIC `SEP_CORE.u_sep_cpu.u_el2_veer_wrapper.veer.pic_ctrl_inst
`define SEP_FCOV_TLU `SEP_CORE.u_sep_cpu.u_el2_veer_wrapper.veer.dec.tlu
`define SEP_FCOV_LSU `SEP_CORE.u_sep_cpu.u_el2_veer_wrapper.veer.lsu
    wire [255:0][3:0] fcov_pic_prio     = `SEP_FCOV_PIC.intpriority_reg;
    wire [255:0]      fcov_pic_en       = `SEP_FCOV_PIC.intenable_reg;
    wire [255:0][1:0] fcov_pic_gw_cfg   = `SEP_FCOV_PIC.gw_config_reg;
    wire              fcov_pic_cfg      = `SEP_FCOV_PIC.config_reg;
    wire [255:0]      fcov_pic_gw_clr   = `SEP_FCOV_PIC.gw_clear_reg_we;
    wire [255:0]      fcov_pic_req      = `SEP_FCOV_PIC.extintsrc_req;
    wire [255:0]      fcov_pic_req_gw   = `SEP_FCOV_PIC.extintsrc_req_gw;
    wire              fcov_pic_wren     = `SEP_FCOV_PIC.picm_wren_ff;
    wire [14:0]       fcov_pic_waddr    = `SEP_FCOV_PIC.picm_waddr_ff[14:0];
    // Data of a PIC write as the instruction stores it. The LSU ANDs a CPU
    // store to the PIC with the field mask of the target register (the
    // picm_mken read), so picm_wr_data is 0 for a hole, for entry 0 and for
    // meigwclr. The copy takes the M-stage store data before that mask, moves
    // it to the R stage, and to the picm_wren_ff clock on picm_wren, as the
    // core moves picm_wr_data. A DMA write to the PIC has no mask and uses
    // picm_wr_data.
    wire [31:0] fcov_pic_st_m = `SEP_FCOV_LSU.lsu_lsc_ctl.lsu_pkt_m.store_data_bypass_m ?
        `SEP_FCOV_LSU.lsu_lsc_ctl.lsu_result_m : `SEP_FCOV_LSU.lsu_lsc_ctl.store_data_pre_m;
    logic [31:0] fcov_pic_st_r, fcov_pic_st_ff;
    always_ff @(posedge clk_i) begin
        if ((`SEP_FCOV_LSU.lsu_lsc_ctl.lsu_pkt_m.valid === 1'b1) &&
            (`SEP_FCOV_LSU.lsu_lsc_ctl.lsu_pkt_m.store === 1'b1) &&
            (`SEP_FCOV_LSU.lsu_lsc_ctl.addr_in_pic_m === 1'b1))
            fcov_pic_st_r <= fcov_pic_st_m;
        if (`SEP_FCOV_PIC.picm_wren === 1'b1)
            fcov_pic_st_ff <= (`SEP_FCOV_LSU.dma_pic_wen === 1'b1) ? `SEP_FCOV_PIC.picm_wr_data :
                fcov_pic_st_r;
    end
    wire [31:0]       fcov_pic_wdata    = fcov_pic_st_ff;
    wire [7:0]        fcov_pic_claim    = `SEP_CORE.u_sep_cpu.u_el2_veer_wrapper.veer.pic_claimid;
    wire              fcov_tlu_mstatus  = `SEP_FCOV_TLU.mstatus[0];
    wire [5:0]        fcov_tlu_mie      = `SEP_FCOV_TLU.mie;
    wire [5:0]        fcov_tlu_mip      = `SEP_FCOV_TLU.mip;
    wire              fcov_tlu_take_ext = `SEP_FCOV_TLU.take_ext_int;
    wire              fcov_tlu_take_nmi = `SEP_FCOV_TLU.take_nmi;
    wire              fcov_tlu_take_tmr = `SEP_FCOV_TLU.take_timer_int;
    wire              fcov_tlu_take_sw  = `SEP_FCOV_TLU.take_soft_int;
`undef SEP_FCOV_PIC
`undef SEP_FCOV_TLU
`undef SEP_FCOV_LSU
`else
    wire [255:0][3:0] fcov_pic_prio     = '0;
    wire [255:0]      fcov_pic_en       = '0;
    wire [255:0][1:0] fcov_pic_gw_cfg   = '0;
    wire              fcov_pic_cfg      = 1'b0;
    wire [255:0]      fcov_pic_gw_clr   = '0;
    wire [255:0]      fcov_pic_req      = '0;
    wire [255:0]      fcov_pic_req_gw   = '0;
    wire              fcov_pic_wren     = 1'b0;
    wire [14:0]       fcov_pic_waddr    = '0;
    wire [31:0]       fcov_pic_wdata    = '0;
    wire [7:0]        fcov_pic_claim    = '0;
    wire              fcov_tlu_mstatus  = 1'b0;
    wire [5:0]        fcov_tlu_mie      = '0;
    wire [5:0]        fcov_tlu_mip      = '0;
    wire              fcov_tlu_take_ext = 1'b0;
    wire              fcov_tlu_take_nmi = 1'b0;
    wire              fcov_tlu_take_tmr = 1'b0;
    wire              fcov_tlu_take_sw  = 1'b0;
`endif
    // One explicit set of assigns per mailbox index.
    logic [7:0][1:0][3:0] fcov_mb_status;
    logic [7:0][1:0][2:0] fcov_mb_irqs;
    logic [7:0][1:0][2:0] fcov_mb_irqen;
    logic [7:0][1:0][1:0] fcov_mb_error;
    logic [7:0][1:0][7:0] fcov_mb_wirqt;
    logic [7:0][1:0][7:0] fcov_mb_rirqt;
    logic [7:0][1:0]      fcov_mb_irq;
    logic [7:0][1:0][2:0] fcov_mf_usage;
    logic [7:0][1:0]      fcov_mf_full;
    logic [7:0][1:0]      fcov_mf_push;
    logic [7:0][1:0]      fcov_mf_pop;
    logic [7:0][1:0]      fcov_mf_flush;
`define SEP_FCOV_MB(m) `SEP_CORE.u_sep_system_peripherals.u_sep_axil_mailbox.gen_mailbox[m].u_axi_lite_mailbox
`define SEP_FCOV_MB_PORT(m, p) \
    assign fcov_mb_status[m][p] = `SEP_FCOV_MB(m).i_slv_port_``p.status_q; \
    assign fcov_mb_irqs[m][p]   = `SEP_FCOV_MB(m).i_slv_port_``p.irqs_q; \
    assign fcov_mb_irqen[m][p]  = `SEP_FCOV_MB(m).i_slv_port_``p.irqen_q; \
    assign fcov_mb_error[m][p]  = `SEP_FCOV_MB(m).i_slv_port_``p.error_q; \
    assign fcov_mb_wirqt[m][p]  = `SEP_FCOV_MB(m).i_slv_port_``p.wirqt_q[7:0]; \
    assign fcov_mb_rirqt[m][p]  = `SEP_FCOV_MB(m).i_slv_port_``p.rirqt_q[7:0]; \
    assign fcov_mb_irq[m][p]    = `SEP_FCOV_MB(m).i_slv_port_``p.irq_o;
`define SEP_FCOV_MB_FIFO(m, f, inst) \
    assign fcov_mf_usage[m][f] = `SEP_FCOV_MB(m).inst.usage_o; \
    assign fcov_mf_full[m][f]  = `SEP_FCOV_MB(m).inst.full_o; \
    assign fcov_mf_push[m][f]  = `SEP_FCOV_MB(m).inst.push_i; \
    assign fcov_mf_pop[m][f]   = `SEP_FCOV_MB(m).inst.pop_i; \
    assign fcov_mf_flush[m][f] = `SEP_FCOV_MB(m).inst.flush_i;
    `SEP_FCOV_MB_PORT(0, 0)
    `SEP_FCOV_MB_PORT(0, 1)
    `SEP_FCOV_MB_FIFO(0, 0, i_mbox_0_to_1)
    `SEP_FCOV_MB_FIFO(0, 1, i_mbox_1_to_0)
    `SEP_FCOV_MB_PORT(1, 0)
    `SEP_FCOV_MB_PORT(1, 1)
    `SEP_FCOV_MB_FIFO(1, 0, i_mbox_0_to_1)
    `SEP_FCOV_MB_FIFO(1, 1, i_mbox_1_to_0)
    `SEP_FCOV_MB_PORT(2, 0)
    `SEP_FCOV_MB_PORT(2, 1)
    `SEP_FCOV_MB_FIFO(2, 0, i_mbox_0_to_1)
    `SEP_FCOV_MB_FIFO(2, 1, i_mbox_1_to_0)
    `SEP_FCOV_MB_PORT(3, 0)
    `SEP_FCOV_MB_PORT(3, 1)
    `SEP_FCOV_MB_FIFO(3, 0, i_mbox_0_to_1)
    `SEP_FCOV_MB_FIFO(3, 1, i_mbox_1_to_0)
    `SEP_FCOV_MB_PORT(4, 0)
    `SEP_FCOV_MB_PORT(4, 1)
    `SEP_FCOV_MB_FIFO(4, 0, i_mbox_0_to_1)
    `SEP_FCOV_MB_FIFO(4, 1, i_mbox_1_to_0)
    `SEP_FCOV_MB_PORT(5, 0)
    `SEP_FCOV_MB_PORT(5, 1)
    `SEP_FCOV_MB_FIFO(5, 0, i_mbox_0_to_1)
    `SEP_FCOV_MB_FIFO(5, 1, i_mbox_1_to_0)
    `SEP_FCOV_MB_PORT(6, 0)
    `SEP_FCOV_MB_PORT(6, 1)
    `SEP_FCOV_MB_FIFO(6, 0, i_mbox_0_to_1)
    `SEP_FCOV_MB_FIFO(6, 1, i_mbox_1_to_0)
    `SEP_FCOV_MB_PORT(7, 0)
    `SEP_FCOV_MB_PORT(7, 1)
    `SEP_FCOV_MB_FIFO(7, 0, i_mbox_0_to_1)
    `SEP_FCOV_MB_FIFO(7, 1, i_mbox_1_to_0)
`undef SEP_FCOV_MB_FIFO
`undef SEP_FCOV_MB_PORT
`undef SEP_FCOV_MB
    logic [15:0] fcov_filt_locked;
    assign fcov_filt_locked[0] = `SEP_CORE.u_sep_system_peripherals.u_inbound_filter.filters[0].locked;
    assign fcov_filt_locked[1] = `SEP_CORE.u_sep_system_peripherals.u_inbound_filter.filters[1].locked;
    assign fcov_filt_locked[2] = `SEP_CORE.u_sep_system_peripherals.u_inbound_filter.filters[2].locked;
    assign fcov_filt_locked[3] = `SEP_CORE.u_sep_system_peripherals.u_inbound_filter.filters[3].locked;
    assign fcov_filt_locked[4] = `SEP_CORE.u_sep_system_peripherals.u_inbound_filter.filters[4].locked;
    assign fcov_filt_locked[5] = `SEP_CORE.u_sep_system_peripherals.u_inbound_filter.filters[5].locked;
    assign fcov_filt_locked[6] = `SEP_CORE.u_sep_system_peripherals.u_inbound_filter.filters[6].locked;
    assign fcov_filt_locked[7] = `SEP_CORE.u_sep_system_peripherals.u_inbound_filter.filters[7].locked;
    assign fcov_filt_locked[8] = `SEP_CORE.u_sep_system_peripherals.u_inbound_filter.filters[8].locked;
    assign fcov_filt_locked[9] = `SEP_CORE.u_sep_system_peripherals.u_inbound_filter.filters[9].locked;
    assign fcov_filt_locked[10] = `SEP_CORE.u_sep_system_peripherals.u_inbound_filter.filters[10].locked;
    assign fcov_filt_locked[11] = `SEP_CORE.u_sep_system_peripherals.u_inbound_filter.filters[11].locked;
    assign fcov_filt_locked[12] = `SEP_CORE.u_sep_system_peripherals.u_inbound_filter.filters[12].locked;
    assign fcov_filt_locked[13] = `SEP_CORE.u_sep_system_peripherals.u_inbound_filter.filters[13].locked;
    assign fcov_filt_locked[14] = `SEP_CORE.u_sep_system_peripherals.u_inbound_filter.filters[14].locked;
    assign fcov_filt_locked[15] = `SEP_CORE.u_sep_system_peripherals.u_inbound_filter.filters[15].locked;

    // Memory, boot, reset, WDT and clock sampler taps (docs/SEP_FCOV.adoc,
    // memory, boot, reset groups, Sampled signal paths): read-only, no force.
    // The reset-vector TDR and the IFU-side AXI cells exist only with the full
    // core; the stub build ties the TDR to 0 and lists no IFU cell.
`ifndef SEP_CPU_STUB
    wire [30:0] fcov_dmi_rst_vec = `SEP_CORE.u_sep_cpu.u_el2_veer_wrapper.dmi_rst_vec;
    wire [2:0]  fcov_te_cpu = {
        `SEP_CORE.u_sep_cpu.u_ifu_axi_demux.test_i,
        `SEP_CORE.u_sep_cpu.u_ifu_axi_err_slv.test_i,
        `SEP_CORE.u_sep_cpu.u_lsu_axi_demux.test_i
    };
`else
    wire [30:0] fcov_dmi_rst_vec = '0;
    wire [2:0]  fcov_te_cpu = {3{`SEP_CORE.u_sep_cpu.u_lsu_axi_demux.test_i}};
`endif
    // Consumers of test_en_i: the Secure DMA clock gater, and the AXI cell
    // test inputs that test_en_i drives.
`define SEP_FCOV_IC `SEP_CORE.u_sep_crypto.u_sep_crypto_axi_interconnect
    wire        fcov_te_gater = `SEP_CORE.u_sep_dma_wrap.u_secure_dma.dma_clk_gate.test_en_i;
    wire [33:0] fcov_te_axi = {
        fcov_te_cpu,
        `SEP_CORE.u_efuse_shim_demux.test_i,
        `SEP_CORE.u_sram_burst_demux.test_i,
        `SEP_CORE.u_sram_burst_err_slv.test_i,
        `SEP_CORE.u_boot_rom_axi_mux.test_i,
        `SEP_CORE.u_sep_crypto.u_efuse_shim_axi_mux.test_i,
        `SEP_FCOV_IC.u_axi_demux.test_i,
        `SEP_FCOV_IC.u_axi_err_slv.test_i,
        `SEP_FCOV_IC.u_otbn_axi_to_axi_lite.test_i,
        `SEP_FCOV_IC.u_otbn_host_isolate.test_i,
        `SEP_FCOV_IC.u_hmac_axi_to_axi_lite.test_i,
        `SEP_FCOV_IC.u_hmac_host_isolate.test_i,
        `SEP_FCOV_IC.u_aes_axi_to_axi_lite.test_i,
        `SEP_FCOV_IC.u_aes_host_isolate.test_i,
        `SEP_FCOV_IC.u_kmac_axi_to_axi_lite.test_i,
        `SEP_FCOV_IC.u_kmac_host_isolate.test_i,
        `SEP_FCOV_IC.u_otbn_key_isolate.test_i,
        `SEP_FCOV_IC.u_aes_key_isolate.test_i,
        `SEP_FCOV_IC.u_hmac_key_isolate.test_i,
        `SEP_FCOV_IC.u_kmac_key_isolate.test_i,
        `SEP_FCOV_IC.u_abr_key_isolate.test_i,
        `SEP_FCOV_IC.u_km_efuse_isolate.test_i,
        `SEP_FCOV_IC.u_km_axi_to_axi_lite.test_i,
        `SEP_FCOV_IC.u_esrc_axi_to_axi_lite.test_i,
        `SEP_FCOV_IC.u_esrc_host_isolate.test_i,
        `SEP_FCOV_IC.u_csrng_axi_to_axi_lite.test_i,
        `SEP_FCOV_IC.u_csrng_host_isolate.test_i,
        `SEP_FCOV_IC.u_edn_axi_to_axi_lite.test_i,
        `SEP_FCOV_IC.u_edn_host_isolate.test_i,
        `SEP_FCOV_IC.u_trng_axi_to_axi_lite.test_i,
        `SEP_CORE.u_sep_wdt_wrap.u_wdt_axi_to_axi_lite.test_i,
        `SEP_CORE.u_sep_reset_ctrl.u_axi_to_axi_lite.test_i
    };
`undef SEP_FCOV_IC

    // Memory, boot, reset sampler taps of the CPU path (docs/SEP_FCOV.adoc,
    // memory, boot, reset groups, Sampled signal paths): the trap unit
    // (veer.dec.tlu: trap cause, ECC counters, their requests and write
    // strobes, the threshold field of the CSR write data), the LSU M-stage
    // packet and address (veer.lsu) and the DTM output before the core and
    // uncore mux (dmi_en, dmi_addr, dmi_wr_en). Read-only, no force. They
    // exist only with the full core; the stub build ties them to 0.
`ifndef SEP_CPU_STUB
`define SEP_FCOV_TLU `SEP_CORE.u_sep_cpu.u_el2_veer_wrapper.veer.dec.tlu
`define SEP_FCOV_LSU `SEP_CORE.u_sep_cpu.u_el2_veer_wrapper.veer.lsu
    wire [31:0] fcov_tlu_mcause    = `SEP_FCOV_TLU.mcause;
    wire [3:0]  fcov_tlu_mscause   = `SEP_FCOV_TLU.mscause;
    wire [31:0] fcov_tlu_mdccmect  = `SEP_FCOV_TLU.mdccmect;
    wire [31:0] fcov_tlu_miccmect  = `SEP_FCOV_TLU.miccmect;
    wire        fcov_tlu_dccm_ce   = `SEP_FCOV_TLU.mdccme_ce_req;
    wire        fcov_tlu_iccm_ce   = `SEP_FCOV_TLU.miccme_ce_req;
    wire        fcov_tlu_ce_int    = `SEP_FCOV_TLU.ce_int;
    wire        fcov_tlu_wr_dccmect = `SEP_FCOV_TLU.wr_mdccmect_r;
    wire        fcov_tlu_wr_iccmect = `SEP_FCOV_TLU.wr_miccmect_r;
    wire [4:0]  fcov_tlu_csr_wt    = `SEP_FCOV_TLU.dec_csr_wrdata_r[31:27];
    wire        fcov_lsu_m_valid   = `SEP_FCOV_LSU.lsu_pkt_m.valid;
    wire        fcov_lsu_m_load    = `SEP_FCOV_LSU.lsu_pkt_m.load;
    wire        fcov_lsu_m_store   = `SEP_FCOV_LSU.lsu_pkt_m.store;
    wire        fcov_lsu_m_dma     = `SEP_FCOV_LSU.lsu_pkt_m.dma;
    wire [31:0] fcov_lsu_m_addr    = `SEP_FCOV_LSU.lsu_addr_m;
    wire        fcov_dmi_en        = `SEP_CORE.u_sep_cpu.u_el2_veer_wrapper.dmi_en;
    wire [6:0]  fcov_dmi_addr      = `SEP_CORE.u_sep_cpu.u_el2_veer_wrapper.dmi_addr;
    wire        fcov_dmi_wr_en     = `SEP_CORE.u_sep_cpu.u_el2_veer_wrapper.dmi_wr_en;
`undef SEP_FCOV_TLU
`undef SEP_FCOV_LSU
`else
    wire [31:0] fcov_tlu_mcause    = '0;
    wire [3:0]  fcov_tlu_mscause   = '0;
    wire [31:0] fcov_tlu_mdccmect  = '0;
    wire [31:0] fcov_tlu_miccmect  = '0;
    wire        fcov_tlu_dccm_ce   = 1'b0;
    wire        fcov_tlu_iccm_ce   = 1'b0;
    wire        fcov_tlu_ce_int    = 1'b0;
    wire        fcov_tlu_wr_dccmect = 1'b0;
    wire        fcov_tlu_wr_iccmect = 1'b0;
    wire [4:0]  fcov_tlu_csr_wt    = '0;
    wire        fcov_lsu_m_valid   = 1'b0;
    wire        fcov_lsu_m_load    = 1'b0;
    wire        fcov_lsu_m_store   = 1'b0;
    wire        fcov_lsu_m_dma     = 1'b0;
    wire [31:0] fcov_lsu_m_addr    = '0;
    wire        fcov_dmi_en        = 1'b0;
    wire [6:0]  fcov_dmi_addr      = '0;
    wire        fcov_dmi_wr_en     = 1'b0;
`endif

    // Crypto and entropy sampler taps (docs/SEP_FCOV.adoc, crypto and entropy
    // groups, Sampled signals): read-only references, no force.
`define FC_CRY  `SEP_CORE.u_sep_crypto
`define FC_HMAC `FC_CRY.u_hmac_wrapper_s3c_scan.u_tt_hmac
`define FC_AES  `FC_CRY.u_aes_wrapper_s3c_scan.u_tt_aes
`define FC_KMAC `FC_CRY.u_kmac_wrapper_s3c_scan.u_tt_kmac
`define FC_OTBN `FC_CRY.u_sep_crypto_otbn_wrapper_s3c_scan.u_otbn
    // The engine idle outputs are unconnected at the sep_crypto level; the tap
    // reads each port. OTBN reports idle as a multi-bit boolean.
    wire [3:0] fcov_eng_idle = {
        prim_mubi_pkg::mubi4_test_true_strict(`FC_OTBN.idle_o),
        `FC_CRY.u_kmac_wrapper_s3c_scan.idle_o,
        `FC_CRY.u_aes_wrapper_s3c_scan.idle_o,
        `FC_CRY.u_hmac_wrapper_s3c_scan.idle_o
    };
    // The sep port ext_trng_axis_req_i is an unpacked array; one assign per
    // stream packs it for the sampler.
    sep_crypto_pkg::ext_trng_axis_req_t [2:0] fcov_ext_trng_req;
    assign fcov_ext_trng_req[0] = `SEP_CORE.ext_trng_axis_req_i[0];
    assign fcov_ext_trng_req[1] = `SEP_CORE.ext_trng_axis_req_i[1];
    assign fcov_ext_trng_req[2] = `SEP_CORE.ext_trng_axis_req_i[2];
    // The alert pair at the input of each crypto alert receiver. The crypto
    // alert sender inject forces this input, so the sender-side vector
    // u_sep_crypto.crypto_alert_tx does not carry a malformed pair.
    prim_alert_pkg::alert_tx_t [10:0] fcov_alert_rx;
    for (genvar g = 0; g < 11; g++) begin : gen_fcov_alert_rx
        assign fcov_alert_rx[g] = `FC_CRY.gen_alert_receivers[g].u_alert_receiver.alert_tx_i;
    end

    // eFuse and lifecycle sampler taps (docs/SEP_FCOV.adoc, eFuse,
    // lifecycle groups, Sampled signals): read-only, no force.
`define FC_EFCTRL `SEP_CORE.u_sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller
`define FC_TOKEN `FC_EFCTRL.gen_mmr_reg.u_efuse_token_processing
    wire [2:0][7:0][31:0] fcov_tok_words = {
        token_sdis_words_o, token_chiplet_words_o, token_sip_words_o
    };
    wire [2:0][255:0] fcov_latch_sticky = {
        token_digest_sdis_sticky_o, token_digest_chiplet_sticky_o, token_digest_sticky_o
    };

    sep_fcov u_sep_fcov (
        .clk_i                 (clk_i),
        .rst_ni                (rst_n_int),

        .lsu_aw_addr_i         (`SEP_CORE.u_sep_cpu.lsu_axi_req.aw.addr),
        .lsu_aw_valid_i        (`SEP_CORE.u_sep_cpu.lsu_axi_req.aw_valid),
        .lsu_aw_ready_i        (`SEP_CORE.u_sep_cpu.lsu_axi_resp.aw_ready),
        .lsu_w_data_i          (`SEP_CORE.u_sep_cpu.lsu_axi_req.w.data),
        .lsu_w_strb_i          (`SEP_CORE.u_sep_cpu.lsu_axi_req.w.strb),
        .lsu_w_valid_i         (`SEP_CORE.u_sep_cpu.lsu_axi_req.w_valid),
        .lsu_w_ready_i         (`SEP_CORE.u_sep_cpu.lsu_axi_resp.w_ready),
        .lsu_b_resp_i          (`SEP_CORE.u_sep_cpu.lsu_axi_resp.b.resp),
        .lsu_b_valid_i         (`SEP_CORE.u_sep_cpu.lsu_axi_resp.b_valid),
        .lsu_b_ready_i         (`SEP_CORE.u_sep_cpu.lsu_axi_req.b_ready),
        .lsu_aw_size_i         (`SEP_CORE.u_sep_cpu.lsu_axi_req.aw.size),
        .lsu_ar_addr_i         (`SEP_CORE.u_sep_cpu.lsu_axi_req.ar.addr),
        .lsu_ar_valid_i        (`SEP_CORE.u_sep_cpu.lsu_axi_req.ar_valid),
        .lsu_ar_ready_i        (`SEP_CORE.u_sep_cpu.lsu_axi_resp.ar_ready),
        .lsu_ar_size_i         (`SEP_CORE.u_sep_cpu.lsu_axi_req.ar.size),
        .lsu_r_data_i          (`SEP_CORE.u_sep_cpu.lsu_axi_resp.r.data),
        .lsu_r_resp_i          (`SEP_CORE.u_sep_cpu.lsu_axi_resp.r.resp),
        .lsu_r_last_i          (`SEP_CORE.u_sep_cpu.lsu_axi_resp.r.last),
        .lsu_r_valid_i         (`SEP_CORE.u_sep_cpu.lsu_axi_resp.r_valid),
        .lsu_r_ready_i         (`SEP_CORE.u_sep_cpu.lsu_axi_req.r_ready),

        .m_axi_awaddr_i        (m_axi_awaddr),
        .m_axi_awvalid_i       (m_axi_awvalid),
        .m_axi_awready_i       (m_axi_awready),
        .m_axi_bresp_i         (m_axi_bresp),
        .m_axi_bvalid_i        (m_axi_bvalid),
        .m_axi_bready_i        (m_axi_bready),
        .m_axi_araddr_i        (m_axi_araddr),
        .m_axi_arvalid_i       (m_axi_arvalid),
        .m_axi_arready_i       (m_axi_arready),
        .m_axi_rresp_i         (m_axi_rresp),
        .m_axi_rlast_i         (m_axi_rlast),
        .m_axi_rvalid_i        (m_axi_rvalid),
        .m_axi_rready_i        (m_axi_rready),

        .hmac_gated_rst_n_i    (hmac_gated_rst_n_probe_o),
        .hmac_host_isolated_i  (hmac_host_isolated_probe_o),
        .hmac_km_isolated_i    (hmac_km_isolated_probe_o),
        .hmac_host_isolate_req_i (hmac_host_isolate_req_probe_o),
        .abr_gated_rst_n_i     (abr_gated_rst_n_probe_o),
        .abr_host_isolated_i   (abr_host_isolated_probe_o),
        .abr_km_isolated_i     (abr_km_isolated_probe_o),
        .abr_host_isolate_req_i  (abr_host_isolate_req_probe_o),
        // sep.sv wires the WDT bark to the CPU NMI input; read-only, like the
        // LSU request bus above.
        .wdt_bark_irq_i        (`SEP_CORE.intr_wdog_timer_bark),

        .cpu_trace_valid_i     (cpu_trace_valid_o),
        .cpu_trace_addr_i      (cpu_trace_addr_o),
        .cpu_trace_interrupt_i (cpu_trace_interrupt_o),
        .cpu_trace_exc_i       (dbg_cpu_trace_exc_o),
        .fw_done_i             (fw_done_o),
        .fw_pass_i             (fw_pass_o),
        .fw_char_valid_i       (fw_char_valid_o),
        .fuse_sense_done_i     (sep_fuse_sense_done_o),
        .drbg_seed_valid_i     (drbg_seed_valid_o),
        .drbg_genbits_vld_i    (drbg_genbits_vld_o),
        .axis1_tvalid_i        (axis1_tvalid_o),
        .axis1_tready_i        (axis1_tready_o),
        .crypto_edn_ack_i      (crypto_edn_ack_o),
        .km_entropy_tvalid_i   (km_entropy_tvalid_o),
        .km_entropy_tready_i   (km_entropy_tready_o),
        // sep.sv assembles the SEP AXI mailbox onto
        // sep_internal_interrupts[7:0] and km_mbox_irq onto [14]. They are
        // different sources with different owning tests, so both are wired.
        .irq_mailbox_i         (sep_internal_interrupts_probe_o[7:0]),
        .irq_km_mbox_i         (sep_internal_interrupts_probe_o[14]),
        // sep.sv intr_dma_done. sep_dma_hash_test completes through the ISR,
        // which clears STATUS.done before software reads it.
        .irq_dma_done_i        (sep_internal_interrupts_probe_o[8]),
        // Sensed LC nibble out of the shadow probe. The W1S leaves verify
        // their start state through this probe and never read LC_STATE
        // frontdoor first, so the frontdoor path cannot observe RMA_SIP_0 /
        // RMA_CHIP_0 at all.
        .efuse_lc_raw_i        (efuse_shadow_probe_o[
            32 * efuse_pkg::ShadowIdxLcState +: 4]),
        .efuse_read_state_i    (efuse_read_state_o),
        .efuse_program_state_i  (efuse_program_state_o),
        .secure_tm_i           (secure_tm_o),
        .sec_dis_i             (lcc_security_disable_probe_o),
        .demote_1_i            (lcc_demote_state_1_probe_o),
        .demote_2_i            (lcc_demote_state_2_probe_o),
        .cpu_reset_n_i         (sep_cpu_reset_n_o),
        .sep_reset_n_i         (dbg_sep_reset_n_o),
        .spi_cs_n_i            (spi_cs_n_o),
        .spi_sck_i             (spi_sck_o),
        .spi_mosi_i            (spi_mosi_o),
        // Values SEP receives, after the pin-or-TDR mux.
        .jtag_sep_reset_n_ovrd_i (jtag_sep_reset_ctrl_drive.ovrd.sep_reset_n_ovrd),
        .jtag_sep_reset_n_val_i  (jtag_sep_reset_ctrl_drive.val.sep_reset_n_val),

        .in_req_i          (smn_inbound_req_drive),
        .in_resp_i         (smn_inbound_resp_w),
        .xbar_req_i        (`SEP_CORE.smn_inbound_to_sep_axi_req),
        .xbar_resp_i       (`SEP_CORE.smn_inbound_to_sep_axi_resp),
        .sys_csr_arvalid_i (sys_csr_axil_arvalid_o),
        .sys_csr_arready_i (sys_csr_axil_arready_o),
        .sys_csr_awvalid_i (sys_csr_axil_awvalid_o),
        .sys_csr_awready_i (sys_csr_axil_awready_o),
        .lsu_req_i         (`SEP_CORE.u_sep_cpu.lsu_axi_req),
        .lsu_resp_i        (`SEP_CORE.u_sep_cpu.lsu_axi_resp),
        .lsu_raw_req_i     (fcov_lsu_raw_req),
        .lsu_raw_live_i    (fcov_lsu_raw_live),
        .alias_in_req_i    (`SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_axi_req),
        .alias_in_resp_i   (`SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_axi_resp),
        .alias_out_req_i   (`SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_remapped_precut_axi_req),
        .route_req_i       (`SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_remapped_axi_req),
        .route_resp_i      (`SEP_CORE.u_sep_system_peripherals.sep_system_peripheral_56_remapped_axi_resp),
        .route_sel_aw_i    (3'(`SEP_CORE.u_sep_system_peripherals.address_remap_demux_select_aw)),
        .route_sel_ar_i    (3'(`SEP_CORE.u_sep_system_peripherals.address_remap_demux_select_ar)),
        .pre_out_req_i     (`SEP_CORE.u_sep_system_peripherals.pre_outbound_filter_axi_req),
        .pre_out_resp_i    (`SEP_CORE.u_sep_system_peripherals.pre_outbound_filter_axi_resp),
        .out_req_i         (smn_outbound_req_w),
        .out_resp_i        (smn_outbound_resp_w),
        .smc_req_i         (ext_to_smc_req_w),
        .smc_resp_i        (ext_to_smc_resp_w),
        .ext_req_i         (u_dut.axi_extension_axi_req),
        .ext_resp_i        (u_dut.axi_extension_axi_resp),
        .dma_req_i         (`SEP_CORE.dma_axi_req),
        .dma_resp_i        (`SEP_CORE.dma_axi_resp),
        .dma_raw_req_i     (`SEP_CORE.u_sep_dma_wrap.dma_axi_req_raw),
        .dma_csr_req_i     (`SEP_CORE.dma_csr_req),
        .dma_csr_resp_i    (`SEP_CORE.dma_csr_rsp),
        .irq_dma_error_i   (sep_internal_interrupts_probe_o[10]),
        .rom_req_i         (u_dut.sep_boot_rom_req),
        .rom_rsp_i         (u_dut.sep_boot_rom_rsp),
        .iccm_clken_i      (|u_dut.sep_cpu_tcm_req.iccm_clken),
        .iccm_wren_i       (|u_dut.sep_cpu_tcm_req.iccm_wren_bank),
        .dccm_clken_i      (|u_dut.sep_cpu_tcm_req.dccm_clken),
        .dccm_wren_i       (|u_dut.sep_cpu_tcm_req.dccm_wren_bank),
        .in_f_en_i         (fcov_in_f_en),
        .in_f_rd_i         (fcov_in_f_rd),
        .in_f_wr_i         (fcov_in_f_wr),
        .in_f_ns_i         (fcov_in_f_ns),
        .in_f_burst_i      (fcov_in_f_burst),
        .in_f_src_i        (fcov_in_f_src),
        .in_f_start_i      (fcov_in_f_start),
        .in_f_end_i        (fcov_in_f_end),
        .out_f_en_i        (fcov_out_f_en),
        .out_f_rd_i        (fcov_out_f_rd),
        .out_f_wr_i        (fcov_out_f_wr),
        .out_f_ns_i        (fcov_out_f_ns),
        .out_f_burst_i     (fcov_out_f_burst),
        .out_f_src_i       (fcov_out_f_src),
        .out_f_start_i     (fcov_out_f_start),
        .out_f_end_i       (fcov_out_f_end),
        .al_valid_i        (fcov_al_valid),
        .al_cache_i        (fcov_al_cache),
        .al_start_i        (fcov_al_start),
        .al_end_i          (fcov_al_end),
        .al_offset_i       (fcov_al_offset),
        .ap_valid_i        (fcov_ap_valid),
        .stee_valid_i      (fcov_stee_valid),
        .sep_base_i        (`SEP_CORE.u_sep_system_peripherals.sep_global_base_addr),
        .sep_size_i        (`SEP_CORE.u_sep_system_peripherals.sep_region_size),
        .smu_base_i        (`SEP_CORE.u_sep_system_peripherals.smu_global_base_addr),
        .smu_size_i        (`SEP_CORE.u_sep_system_peripherals.smu_region_size),
        .local_base_i      (`SEP_CORE.sep_local_base_addr),
        .smc_base_i        (u_dut.smc_global_base_addr_i),
        .smc_size_i        (u_dut.smc_region_size_i),
        .smc_fuse_done_i   (u_dut.smc_fuse_sense_done_i),
        .sep_debug_i       (`SEP_CORE.feat_ctrl.sep_debug),

        // Phase 2 SPI and DMA taps (docs/SEP_FCOV.adoc, SPI and DMA groups,
        // Sampled signals): read-only, no force.
        .spi_active_i      (`SEP_CORE.u_sep_io.u_sep_ot_spi_wrap.u_spi_host.active),
        .spi_tx_stall_i    (`SEP_CORE.u_sep_io.u_sep_ot_spi_wrap.u_spi_host.tx_stall),
        .spi_rx_stall_i    (`SEP_CORE.u_sep_io.u_sep_ot_spi_wrap.u_spi_host.rx_stall),
        .spi_tx_qd_i       (spi_tx_qd_probe_o),
        .spi_rx_qd_i       (`SEP_CORE.u_sep_io.u_sep_ot_spi_wrap.u_spi_host.rx_qd),
        .spi_cmd_qd_i      (`SEP_CORE.u_sep_io.u_sep_ot_spi_wrap.u_spi_host.cmd_qd),
        .spi_tx_wm_i       (`SEP_CORE.u_sep_io.u_sep_ot_spi_wrap.u_spi_host.tx_wm),
        .spi_tx_empty_i    (`SEP_CORE.u_sep_io.u_sep_ot_spi_wrap.u_spi_host.tx_empty),
        .spi_tx_full_i     (`SEP_CORE.u_sep_io.u_sep_ot_spi_wrap.u_spi_host.tx_full),
        .spi_rx_wm_i       (`SEP_CORE.u_sep_io.u_sep_ot_spi_wrap.u_spi_host.rx_wm),
        .spi_rx_empty_i    (`SEP_CORE.u_sep_io.u_sep_ot_spi_wrap.u_spi_host.rx_empty),
        .spi_rx_full_i     (`SEP_CORE.u_sep_io.u_sep_ot_spi_wrap.u_spi_host.rx_full),
        .spi_cmd_busy_i    (`SEP_CORE.u_sep_io.u_sep_ot_spi_wrap.u_spi_host.command_busy),
        .spi_reg2hw_i      (`SEP_CORE.u_sep_io.u_sep_ot_spi_wrap.u_spi_host.reg2hw),
        .dma_reg2hw_i      (`SEP_CORE.u_sep_dma_wrap.u_secure_dma.reg2hw),
        .dma_aborted_i     (`SEP_CORE.u_sep_dma_wrap.u_secure_dma.u_secure_dma_reg.status_aborted_qs),
        .dma_err_code_i    ({
            `SEP_CORE.u_sep_dma_wrap.u_secure_dma.u_secure_dma_reg.error_code_asid_error_qs,
            `SEP_CORE.u_sep_dma_wrap.u_secure_dma.u_secure_dma_reg.error_code_range_valid_error_qs,
            `SEP_CORE.u_sep_dma_wrap.u_secure_dma.u_secure_dma_reg.error_code_base_limit_error_qs,
            `SEP_CORE.u_sep_dma_wrap.u_secure_dma.u_secure_dma_reg.error_code_bus_error_qs,
            `SEP_CORE.u_sep_dma_wrap.u_secure_dma.u_secure_dma_reg.error_code_size_error_qs,
            `SEP_CORE.u_sep_dma_wrap.u_secure_dma.u_secure_dma_reg.error_code_opcode_error_qs,
            `SEP_CORE.u_sep_dma_wrap.u_secure_dma.u_secure_dma_reg.error_code_dst_addr_error_qs,
            `SEP_CORE.u_sep_dma_wrap.u_secure_dma.u_secure_dma_reg.error_code_src_addr_error_qs}),
        .dma_busy_i        (dma_busy_probe_o),
        .irq_dma_chunk_i   (sep_internal_interrupts_probe_o[9]),
        .irq_spi_i         (sep_internal_interrupts_probe_o[13]),

        // Mailbox, IRQ and PIC taps (docs/SEP_FCOV.adoc, mailbox, IRQ and
        // PIC groups, Signal aliases): read-only, no force.
        .vec_i             (sep_internal_interrupts_probe_o),
        .smc_irq_i         (smc_mailbox_interrupt_o),
        .pic_prio_i        (fcov_pic_prio),
        .pic_en_i          (fcov_pic_en),
        .pic_gw_cfg_i      (fcov_pic_gw_cfg),
        .pic_cfg_i         (fcov_pic_cfg),
        .pic_gw_clr_i      (fcov_pic_gw_clr),
        .pic_req_i         (fcov_pic_req),
        .pic_req_gw_i      (fcov_pic_req_gw),
        .pic_wren_i        (fcov_pic_wren),
        .pic_waddr_i       (fcov_pic_waddr),
        .pic_wdata_i       (fcov_pic_wdata),
        .pic_rd_i          (pic_rd_data_probe_o),
        .pic_claim_i       (fcov_pic_claim),
        .tlu_mstatus_mie_i (fcov_tlu_mstatus),
        .tlu_mie_i         (fcov_tlu_mie),
        .tlu_mip_i         (fcov_tlu_mip),
        .tlu_take_ext_i    (fcov_tlu_take_ext),
        .tlu_take_nmi_i    (fcov_tlu_take_nmi),
        .tlu_take_timer_i  (fcov_tlu_take_tmr),
        .tlu_take_soft_i   (fcov_tlu_take_sw),
        .mb_status_i       (fcov_mb_status),
        .mb_irqs_i         (fcov_mb_irqs),
        .mb_irqen_i        (fcov_mb_irqen),
        .mb_error_i        (fcov_mb_error),
        .mb_wirqt_i        (fcov_mb_wirqt),
        .mb_rirqt_i        (fcov_mb_rirqt),
        .mb_irq_i          (fcov_mb_irq),
        .mf_usage_i        (fcov_mf_usage),
        .mf_full_i         (fcov_mf_full),
        .mf_push_i         (fcov_mf_push),
        .mf_pop_i          (fcov_mf_pop),
        .mf_flush_i        (fcov_mf_flush),
        .mbx_req_i         (`SEP_CORE.u_sep_system_peripherals.mailbox_axil_req),
        .mbx_resp_i        (`SEP_CORE.u_sep_system_peripherals.mailbox_axil_resp),
        .filt_iso_w_i      (`SEP_CORE.u_sep_system_peripherals.u_inbound_filter.isolate_write),
        .filt_iso_r_i      (`SEP_CORE.u_sep_system_peripherals.u_inbound_filter.isolate_read),
        .filt_nwm_i        (`SEP_CORE.u_sep_system_peripherals.u_inbound_filter.no_write_filter_matches),
        .filt_nrm_i        (`SEP_CORE.u_sep_system_peripherals.u_inbound_filter.no_read_filter_matches),
        .filt_hit_i        (`SEP_CORE.u_sep_system_peripherals.u_inbound_filter.write_filter_hit_idx),
        .filt_awvalid_i    (`SEP_CORE.u_sep_system_peripherals.u_inbound_filter.axi_in_req_i.aw_valid),
        .filt_arvalid_i    (`SEP_CORE.u_sep_system_peripherals.u_inbound_filter.axi_in_req_i.ar_valid),
        .filt_locked_i     (fcov_filt_locked),
        .alert_pulse_i     (crypto_alert_pulse_probe_o),
        .err_pulse_i       (sep_cpu_ctrl_err_pulse_probe_o),
        .ext_irq_i         (sep_ext_interrupts_i),
        .out_resp_hold_i   (smn_outbound_resp_hold_i),
        .out_rd_slverr_i   (smn_outbound_rd_slverr_i),
        .spi_irq_field_i   (sep_io_spi_req_w.irq),

        // Memory, boot, reset, WDT and clock taps.
        .clk_wdt_i         (clk_wdt_i),
        .clk_ref_i         (clk_ref_i),
        .wdt_rst_n_i       (wdt_rst_ni_i),
        .dbg_rstb_i        (dbg_rstb_i),
        .scan_rst_n_i      (scan_rst_ni_i !== 1'b0),
        .test_en_i         (test_en_i === 1'b1),
        .jtag_tck_i        (jtag_core_tck),
        .jtag_tms_i        (jtag_core_tms),
        .jtag_tdi_i        (jtag_core_tdi),
        .jtag_trst_n_i     (jtag_core_trst_n),
        .jtag_tdo_i        (jtag_tdo_o),
        .ext_boot_done_i   (ext_boot_seq_done_i),
        .mpc_run_req_i     (mpc_reset_run_req),
        .mpc_run_sync_i    (mpc_run_sync_probe_o),
        .strap_i           (test_en_strap_i),
        .wdt_rst_req_i     (wdt_timer_rst_req_o),
        .ip_rst_n_i        (`SEP_CORE.sep_crypto_gated_rst_n),
        .iso_req_i         (crypto_isolate_req_probe_o),
        .iso_ack_i         (crypto_isolated_probe_o),
        .aon_rst_n_i       (aon_rst_n_probe_o),
        .km_cond_rst_n_i   (km_cond_rst_probe_o),
        .jtag_rst_ctrl_i   (jtag_sep_reset_ctrl_drive),
        .dmi_rst_vec_i     (fcov_dmi_rst_vec),
        .wdt_axi_req_i     (`SEP_CORE.u_sep_wdt_wrap.sep_wdt_tlul_axi_req),
        .wdt_axi_off_req_i (`SEP_CORE.u_sep_wdt_wrap.sep_wdt_tlul_axi_req_offset),
        .wdt_axi_resp_i    (`SEP_CORE.u_sep_wdt_wrap.sep_wdt_tlul_axi_resp),
        .wdt_axil_req_i    (`SEP_CORE.u_sep_wdt_wrap.axi_lite_req),
        .wdt_axil_resp_i   (`SEP_CORE.u_sep_wdt_wrap.axi_lite_resp),
        .wdt_tl_h2d_i      (`SEP_CORE.u_sep_wdt_wrap.tl_d_i),
        .wdt_tl_d2h_i      (`SEP_CORE.u_sep_wdt_wrap.tl_d_o),
        .te_pins_one_i     ({&fcov_te_axi, fcov_te_gater === 1'b1}),
        .te_pins_zero_i    ({~|fcov_te_axi, fcov_te_gater === 1'b0}),

        // Memory, boot, reset taps of the CPU path, the memory macros and
        // the debug interface.
        .cpu_trace_insn_i   (cpu_trace_insn_o),
        .cpu_trace_ecause_i (cpu_trace_ecause_o),
        .cpu_trace_tval_i   (cpu_trace_tval_o),
        .ecc_dbg_i          (ext_debug_bus_o[367:364]),
        .sram_req_i         (u_dut.sep_sram_req),
        .sram_rsp_i         (u_dut.sep_sram_rsp),
        .tcm_axi_req_i      (`SEP_CORE.cpu_tcm_axi_req),
        .tcm_axi_resp_i     (`SEP_CORE.cpu_tcm_axi_resp),
        .tcm_i_clken_i      (pr_tcm_iccm_clken_o),
        .tcm_i_wren_i       (pr_tcm_iccm_wren_o),
        .tcm_i_addr_i       (pr_tcm_iccm_addr_o),
        .tcm_i_wdata_i      (pr_tcm_iccm_wdata_o),
        .tcm_i_wecc_i       (pr_tcm_iccm_wecc_o),
        .tcm_i_rdata_i      (pr_tcm_iccm_rdata_o),
        .tcm_i_recc_i       (pr_tcm_iccm_recc_o),
        .tcm_d_clken_i      (pr_tcm_dccm_clken_o),
        .tcm_d_wren_i       (pr_tcm_dccm_wren_o),
        .tcm_d_addr_i       (pr_tcm_dccm_addr_o),
        .tcm_d_wdata_i      (pr_tcm_dccm_wdata_o),
        .tcm_d_wecc_i       (pr_tcm_dccm_wecc_o),
        .tcm_d_rdata_i      (pr_tcm_dccm_rdata_o),
        .tcm_d_recc_i       (pr_tcm_dccm_recc_o),
        .ifu_arvalid_i      (pr_ifu_arvalid_o),
        .ifu_arready_i      (pr_ifu_arready_o),
        .ifu_araddr_i       (pr_ifu_araddr_o),
        .ifu_arid_i         (pr_ifu_arid_o),
        .ifu_rvalid_i       (pr_ifu_rvalid_o),
        .ifu_rready_i       (pr_ifu_rready_o),
        .ifu_rresp_i        (pr_ifu_rresp_o),
        .ifu_rid_i          (pr_ifu_rid_o),
        .ifu_rlast_i        (pr_ifu_rlast_o),
        .ifu_rom_req_i      (`SEP_CORE.ifu_rom_axi_req),
        .ifu_sram_req_i     (`SEP_CORE.ifu_sram_axi_req),
        .lsu_rom_req_i      (`SEP_CORE.lsu_rom_axi_req),
        .lsu_rom_resp_i     (`SEP_CORE.lsu_rom_axi_resp),
        .lsu_xbar_req_i     (`SEP_CORE.lsu_xbar_axi_req),
        .lsu_xbar_resp_i    (`SEP_CORE.lsu_xbar_axi_resp),
        .rom_macro_req_i    (pr_rom_macro_req_o),
        .rom_macro_addr_i   (pr_rom_macro_addr_o),
        .tlu_mcause_i       (fcov_tlu_mcause),
        .tlu_mscause_i      (fcov_tlu_mscause),
        .tlu_mdccmect_i     (fcov_tlu_mdccmect),
        .tlu_miccmect_i     (fcov_tlu_miccmect),
        .tlu_dccm_ce_req_i  (fcov_tlu_dccm_ce),
        .tlu_iccm_ce_req_i  (fcov_tlu_iccm_ce),
        .tlu_ce_int_i       (fcov_tlu_ce_int),
        .tlu_wr_dccmect_i   (fcov_tlu_wr_dccmect),
        .tlu_wr_iccmect_i   (fcov_tlu_wr_iccmect),
        .tlu_csr_wt_i       (fcov_tlu_csr_wt),
        .lsu_m_valid_i      (fcov_lsu_m_valid),
        .lsu_m_load_i       (fcov_lsu_m_load),
        .lsu_m_store_i      (fcov_lsu_m_store),
        .lsu_m_dma_i        (fcov_lsu_m_dma),
        .lsu_m_addr_i       (fcov_lsu_m_addr),
        .nmi_vec_i          (`SEP_CORE.nmi_vec),
        .dmi_en_i           (fcov_dmi_en),
        .dmi_addr_i         (fcov_dmi_addr),
        .dmi_wr_en_i        (fcov_dmi_wr_en),
        .dmi_core_en_i      (dmi_core_enable_i === 1'b1),
        .dmi_uncore_cfg_i   (dmi_uncore_enable_i === 1'b1),
        .dmi_uncore_en_i    (dmi_uncore_en_o),
        .dmi_uncore_wr_en_i (dmi_uncore_wr_en_o),

        // Crypto and entropy taps.
        .eng_idle_i            (fcov_eng_idle),
        .alert_tx_i            (fcov_alert_rx),
        .drbg_int_req_i        (`FC_CRY.drbg_int_axis_req),
        .drbg_int_rsp_i        (`FC_CRY.drbg_int_axis_rsp),
        .ext_trng_req_i        (fcov_ext_trng_req),
        .ext_trng_tready_i     (ext_trng_tready_o),
        .ext_trng_irq_i        (`SEP_CORE.ext_trng_irq_i),
        .ext_trng_sel_i        (`SEP_CORE.ext_trng_src_sel),
        .pool_level_i          (`SEP_CORE.u_entropy_fifo.fifo_level_o),
        .pool_low_i            (`SEP_CORE.u_entropy_fifo.pool_low_o),
        .pool_fill_stall_i     (`SEP_CORE.u_entropy_fifo.fill_stall_o),
        .pool_clear_i          (`SEP_CORE.u_entropy_fifo.entropy_clear_i),
        .hmac_reg2hw_i         (`FC_HMAC.reg2hw),
        .hmac_hw2reg_i         (`FC_HMAC.hw2reg),
        .hmac_intr_i           ({`FC_CRY.intr_hmac_err_o,
                                 `FC_CRY.intr_hmac_fifo_empty_o,
                                 `FC_CRY.intr_hmac_done_o}),
        .hmac_key_valid_i      (`FC_CRY.u_hmac_wrapper_s3c_scan.hmac_keymgr_key.valid),
        .aes_reg2hw_i          (`FC_AES.reg2hw),
        .aes_hw2reg_i          (`FC_AES.hw2reg),
        .aes_op_i              (`FC_AES.u_aes_core.aes_op_q),
        .aes_mode_i            (`FC_AES.u_aes_core.aes_mode_q),
        .aes_key_len_i         (`FC_AES.u_aes_core.key_len_q),
        .aes_prs_rate_i        (`FC_AES.u_aes_core.prng_reseed_rate_q),
        .aes_sideload_i        (`FC_AES.u_aes_core.sideload_q),
        .aes_manual_op_i       (`FC_AES.u_aes_core.manual_operation_q),
        .aes_ctrl_qe_i         (`FC_AES.u_aes_core.ctrl_qe),
        .aes_ctrl_we_i         (`FC_AES.u_aes_core.ctrl_we),
        .aes_ctrl_err_update_i (`FC_AES.u_aes_core.ctrl_err_update),
        .aes_aux_regwen_i      (`FC_AES.u_reg.ctrl_aux_regwen_qs),
        .aes_key_valid_i       (`FC_CRY.u_aes_wrapper_s3c_scan.aes_keymgr_key.valid),
        .kmac_reg2hw_i         (`FC_KMAC.reg2hw),
        .kmac_hw2reg_i         (`FC_KMAC.hw2reg),
        .kmac_mode_q_i         (`FC_KMAC.gen_entropy.u_entropy.mode_q),
        .kmac_timer_expired_i  (`FC_KMAC.gen_entropy.u_entropy.timer_expired),
        .kmac_hash_cnt_i       (`FC_KMAC.entropy_hash_cnt),
        .kmac_intr_i           ({`FC_CRY.intr_kmac_err_o,
                                 `FC_CRY.intr_kmac_fifo_empty_o,
                                 `FC_CRY.intr_kmac_done_o}),
        .otbn_status_i         (`FC_OTBN.status_q),
        .otbn_errs_fatal_i     (`FC_OTBN.software_errs_fatal_q),
        .otbn_reg2hw_i         (`FC_OTBN.reg2hw),
        .otbn_hw2reg_i         (`FC_OTBN.hw2reg),
        .otbn_done_i           (`FC_OTBN.done),
        .otbn_insn_cnt_i       (`FC_OTBN.insn_cnt),
        .otbn_intr_i           (`FC_CRY.intr_otbn_done_o),
        .csrng_reg2hw_i        (`SEP_DRBG.u_csrng.reg2hw),
        .csrng_hw2reg_i        (`SEP_DRBG.u_csrng.hw2reg),
        .csrng_app0_req_i      (`SEP_DRBG.u_csrng.u_csrng_core.csrng_cmd_i[0]),
        .csrng_app0_ack_i      (`SEP_DRBG.u_csrng.u_csrng_core.csrng_cmd_o[0].csrng_rsp_ack),
        .csrng_intr_i          ({`FC_CRY.intr_cs_fatal_err_o,
                                 `FC_CRY.intr_cs_hw_inst_exc_o,
                                 `FC_CRY.intr_cs_entropy_req_o,
                                 `FC_CRY.intr_cs_cmd_req_done_o}),
        .csrng_regwen_i        (`SEP_DRBG.u_csrng.u_reg.regwen_qs),
        .edn_reg2hw_i          (`SEP_DRBG.u_edn.reg2hw),
        .edn_hw2reg_i          (`SEP_DRBG.u_edn.hw2reg),
        .edn_intr_i            ({`FC_CRY.intr_edn_fatal_err_o,
                                 `FC_CRY.intr_edn_cmd_req_done_o}),
        .edn_regwen_i          (`SEP_DRBG.u_edn.u_reg.regwen_qs),
        .esrc_reg_in_i         (`SEP_ESRC.reg_in),
        .esrc_reg_out_i        (`SEP_ESRC.reg_out),
        .esrc_boot_done_i      (`SEP_ESRC.boot_phase_done),
        .esrc_sm_alert_i       (`SEP_ESRC.main_sm_alert),
        .esrc_sm_idle_i        (`SEP_ESRC.main_sm_idle),
        .esrc_sm_err_i         (`SEP_ESRC.main_sm_err),
        .esrc_ht_fail_i        (`SEP_ESRC.ht_fail_pulse),
        .esrc_pers_fail_i      (`SEP_ESRC.persistent_failure),
        .esrc_autotune_fail_i  (`SEP_ESRC.autotune_fail),
        .esrc_biw_obs_push_i   (`SEP_ESRC.biw_obs_push),
        .esrc_biw_obs_level_i  (`SEP_ESRC.biw_obs_level),
        .esrc_biw_obs_ovf_i    (`SEP_ESRC.biw_obs_overflow),
        .esrc_noise_obs_push_i (`SEP_ESRC.noise_obs_push),
        .esrc_noise_obs_level_i (`SEP_ESRC.noise_obs_level),
        .esrc_noise_obs_ovf_i  (`SEP_ESRC.noise_obs_overflow),
        .esrc_noise_obs_lane_i (`SEP_ESRC.noise_obs_lane_sel_eff),
        .esrc_noise_obs_flush_i (`SEP_ESRC.noise_obs_flush),
        .esrc_fifo_level_i     (`SEP_ESRC.fifo_level),
        .esrc_fifo_ovf_i       (`SEP_ESRC.fifo_overflow),
        .esrc_fifo_unf_i       (`SEP_ESRC.fifo_underflow),
        .esrc_fifo_err_i       (`SEP_ESRC.fifo_error),
        .esrc_fifo_wptr_i      (`SEP_ESRC.fifo_wptr),
        .esrc_fifo_rptr_i      (`SEP_ESRC.fifo_rptr),
        .esrc_detune_i         (esrc_detune_o),
        // ESRC, DRBG and external TRNG taps.
        .trng_rst_i            (trng_reset_active_probe_o),
        .edn_req_i             (crypto_edn_req_o),
        .edn_fips_i            (crypto_edn_fips_o),
        .edn_bus_i             (crypto_edn_bus_o),
        .pool_edn_req_i        (pool_edn_req_o),
        .pool_edn_ack_i        (pool_edn_ack_o),
        .pool_edn_bus_i        (pool_edn_bus_o),
        .pool_edn_fips_i       (pool_edn_fips_o),
        .mux_req_i             (`FC_CRY.entropy_muxed_req),
        .mux_rsp_i             (`FC_CRY.entropy_muxed_rsp),
        .esrc_decor_bytes_i    (esrc_decor_bytes_o),
        .esrc_decor_valid_i    (esrc_decor_valid_o),
        .esrc_compress_vld_i   (esrc_compress_vld_o),
        .esrc_whiten_push_i    (esrc_whiten_push_o),
        .esrc_decor_noise_i    (esrc_decor_noise_o),
        .esrc_par_inj_i        (esrc_fifo_parity_inject_i === 1'b1),
        .esrc_ptr_inj_i        (esrc_fifo_ptr_inject_i === 1'b1),
        // eFuse, lifecycle and SEC_DIS taps.
        .shim_cmd_i            (`SEP_CORE.efuse_shim_command_req_o),
        .shim_resp_i           (`SEP_CORE.efuse_shim_command_resp_i),
        .efuse_shadow_i        (efuse_shadow_probe_o),
        .stored_shadow_i       (`FC_EFCTRL.u_efuse_shadow_regs.shadow_efuse),
        .feat_ctrl_i           (lcc_feat_ctrl_probe_o),
        .lc_sigint_i           (lcc_sigint_err_probe_o),
        .demote_lock_1_i       (lcc_demote_lock_1_probe_o),
        .demote_lock_2_i       (lcc_demote_lock_2_probe_o),
        .sep_fuse_dft_disable_i (sep_fuse_dft_disable_o),
        .smc_fuse_dft_disable_i (smc_fuse_dft_disable_o),
        .jtag_req_i            (j_axil_req_drive),
        .jtag_resp_i           (j_axil_resp_w),
        .irq_token_fault_i     (sep_internal_interrupts_probe_o[39]),
        .tok_sip_i             (ext_debug_bus_o[229:224]),
        .tok_chp_i             (ext_debug_bus_o[213:208]),
        .tok_sdis_i            (`FC_TOKEN.sec_disable_token_match_q),
        .tok_fault_i           (`FC_TOKEN.token_match_fault_sticky_q),
        .token_go_i            ({`FC_TOKEN.secure_disable_token_go,
                                 `FC_TOKEN.rma_chiplet_token_go,
                                 `FC_TOKEN.rma_sip_token_go}),
        .tok_words_i           (fcov_tok_words),
        .sec_disable_expected_i (`FC_TOKEN.sec_disable_token_rev),
        .rd_addr_err_i         (`FC_EFCTRL.read_addr_error),
        .pg_addr_err_i         (`FC_EFCTRL.program_addr_error),
        .req_err_i             (`FC_EFCTRL.efuse_req_err),
        .cmp_match_p_i         (token_cmp_match_p_o),
        .cmp_match_n_i         (token_cmp_match_n_o),
        .latch_sticky_i        (fcov_latch_sticky),
        .latch_valid_i         ({token_digest_sdis_valid_o, token_digest_chiplet_valid_o,
                                 token_digest_valid_o}),
        .latch_test_en_i       ({token_digest_sdis_test_en_o, token_digest_chiplet_test_en_o,
                                 token_digest_test_en_o}),
        .jtag_filt_sigint_i    (jtag_filter_lc_sigint_err_probe_o),
        .jtag_id_i             (jtag_id_probe_o),
        .efuse_read_error_i    (efuse_read_error_o),
        .efuse_read_done_i     (efuse_read_done_o),
        .efuse_read_busy_i     (efuse_read_busy_o),
        .efuse_program_error_i (efuse_program_error_o),
        .efuse_program_done_i  (efuse_program_done_o),
        .efuse_program_busy_i  (efuse_program_busy_o)
    );
`undef FC_EFCTRL
`undef FC_TOKEN
`undef FC_CRY
`undef FC_HMAC
`undef FC_AES
`undef FC_KMAC
`undef FC_OTBN
`endif

`undef SEP_ESRC
`undef SEP_DRBG
`undef SEP_CORE
`undef SEP_IPI

endmodule : sep_uvm_top
