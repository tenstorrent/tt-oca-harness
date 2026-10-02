// SPDX-License-Identifier: Apache-2.0
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
// `sep` core from hw/sys/sep/rtl/sep.sv) for the OSS cocotb flow: brings
// clocks/reset/boot controls out as top-level ports and ties every unused DUT
// port to a benign idle value. Stimulus is injected on the SEP CPU's own LSU AXI
// master bus: the core (VeeR EL2) is held off (`mpc_reset_run_req=0`) and an
// external cocotbext-axi AxiMaster is spliced onto the CPU's LSU AXI master
// ``SEP_CORE.u_sep_cpu.lsu_axi_req` / `lsu_axi_resp`, sep_32_64_3_12
// (addr32/data64/id3/user12). The stub build (`SEP_CPU_STUB`) is the sole
// driver of that bus and drives lsu_axi_req from the tb's assembled request
// (`assign`, no `force`; see shims/cpu/sep_cpu_stub.sv). On the full-CPU VCS
// build a no_cpu test force-splices the same post-remap `lsu_axi_req` and
// holds `lsu_axi_resp_raw` idle. The tb reads lsu_axi_resp back by name.
// Driving the demux slave-side LSU bus reaches the SEP-local fabric through the
// same ROM/xbar routing point as the core would, so the external SMN inbound
// filter is NOT in the path. Every other DUT port is tied to a benign idle
// value so nothing X-props.
//
// A flat cocotb AXI interface is spliced onto these same CPU master ports.
// The CPU LSU splice is the primary stimulus
// path. `smn_inbound` is additionally brought out as the flat `m_axi_*` master
// (the DUT's real external inbound port, which traverses the inbound filter);
// it idles unless a test drives it, and is used by the inbound-filter-gating
// test to prove external AXI is blocked/allowed by feat_ctrl.sep_debug.
//
// Two run modes, selected by the `+cpu_boot` plusarg:
//   * no-CPU (default): the core is held off (mpc_reset_run_req=0) and cocotb
//     drives the SEP fabric over s_axi. The stub build presents that request
//     on the LSU master (`assign`). The full-CPU VCS build force-splices the
//     same post-remap net. Verilator no_cpu stays on the stub.
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
// The CPU LSU req/resp struct (deps/axi AXI_TYPEDEF_ALL) is bridged to flat
// `s_axi_*` ports so cocotb binds via AxiBus.from_prefix(dut, "s_axi").

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
    // the `sep` core. Every
    // sep-internal XMR read routes through `SEP_CORE / `SEP_IPI so one probe text
    // is used throughout.
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
    sep_pkg::sep_system_peripherals_internal_axi_resp_t ext_to_smc_resp_idle   = '0;
    // SEP->SMC external AXI. Tied idle by default; with SEP_SMC_MEM_MODEL the
    // shared AXI slave agent responds (real R/W to SMC scratch + SRAM) so the
    // Boot ROM can run its SMC scratch round-trip + non-SPI manifest fetch.
    sep_pkg::sep_system_peripherals_internal_axi_req_t  ext_to_smc_req_w;
    sep_pkg::sep_system_peripherals_internal_axi_resp_t ext_to_smc_resp_w;
    // SEP-OTP JTAG AXI-Lite: assembled from the flat j_axi_* master inputs (below).
    sep_efuse_pkg::efuse_axil_req_t   j_axil_req_drive;
    sep_efuse_pkg::efuse_axil_resp_t  j_axil_resp_w;
    sep_pkg::jtag_sep_reset_ctrl_t   jtag_sep_reset_ctrl_drive;
    // IC_RESET TDR storage for the SEP slice. Width is the integrator SEP-slice
    // table: 8 ports when SEP=1 (doc/integrator/src/smu.adoc). The TAP
    // instruction that selects the TDR is outside this DUT. tdr_en selects
    // the register; otherwise the per-port pins drive the same struct.
    localparam int unsigned SEP_IC_RESET_PORTS = 8;
    prim_jtag_pkg::jtag_scan_ctrl_t ic_reset_scan_ctrl;
    prim_jtag_pkg::jtag_tap_ctrl_t  ic_reset_tap_ctrl;
    logic [SEP_IC_RESET_PORTS-1:0]  ic_reset_ovrd_w;
    logic [SEP_IC_RESET_PORTS-1:0]  ic_reset_ctrl_n_w;
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
        .NUM_IC_RESET_PORTS(SEP_IC_RESET_PORTS)
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
    // cancel contracts, and FipsWindowFloor_A.
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
        // endpoint of SEP_CRYPTO_AXIS_EDN_CLIENT_COUNT (AES, KMAC, OTBN RND,
        // OTBN URND).
        $asserton(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
            .gen_ep[0].AxisEdnNoAckDuringClear_A);
        $asserton(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
            .gen_ep[1].AxisEdnNoAckDuringClear_A);
        $asserton(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
            .gen_ep[2].AxisEdnNoAckDuringClear_A);
        $asserton(0, `SEP_CORE.u_sep_crypto.u_axis_edn_crypto_s3c_scan
            .gen_ep[3].AxisEdnNoAckDuringClear_A);
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
        // entropy_source.sv:1348 FipsWindowFloor_A -- fips_lock |-> window >= 1024.
        // sep_drbg_esrc_fips_lock_test writes FIPS_LOCK.LOCK, so a locked
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

    // otbn_rnd.sv:233 UrndNoReseedOnReset_A cannot pass on this instance. It arms
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
    // in-reset cycle is checked in any test. The flop at otbn_rnd.sv:205-213
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

    // TB-owned JTAG pins used to program the EL2 reset-vector TDR in +cpu_boot
    // mode. They remain at the idle TAP-reset values for no-CPU tests.
    logic jtag_tck   = 1'b0;
    logic jtag_tms   = 1'b0;
    logic jtag_tdi   = 1'b0;
    logic jtag_trst_n = 1'b0;

    localparam logic [4:0] RESET_VECTOR_TDR_IR = 5'h18;

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
            jtag_tb_clock(bit_idx == 4, RESET_VECTOR_TDR_IR[bit_idx]);
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
    // The OSS top has no external JTAG client. Program RSTVEC while the primary
    // reset is asserted, before the cocotb CPU-boot flow releases reset. Poll on the
    // clock edge rather than a bare level `wait`: a cocotb (VPI)-driven rst_vec_i
    // update does not reliably re-trigger a `wait` under Verilator, so the one-shot
    // could fire late (after reset release) and latch a stale/zero vector. Program
    // exactly once on the first clock where reset is asserted and rst_vec_i is a
    // known non-zero entry (clocks start while rst_ni is still low, so the window is
    // always seen). RSTVEC stores PC[31:1] = rst_vec_i.
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
    // EXT_TRNG_NUM_AXIS must equal sep_crypto_pkg::SEP_CRYPTO_EDN_ENDPOINT_COUNT (3):
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
    localparam bit [255:0] SEC_DIS_TB_DIGEST =
        256'h66687aad_f862bd77_6c8fc18b_8e9f8e20_08971485_6ee233b3_902a591d_0d5f2925;
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

    sep_wrapper #(
        .EXT_TRNG_NUM_AXIS     (3),
        .SEP_SEC_DISABLE_TOKEN (SEC_DIS_TB_DIGEST)
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

        // JTAG (TB-driven only during +cpu_boot reset-vector TDR setup)
        .jtag_tck_i                   (jtag_tck),
        .jtag_tms_i                   (jtag_tms),
        .jtag_tdi_i                   (jtag_tdi),
        .jtag_trst_ni                 (jtag_trst_n),
        .jtag_tdo_o                   (),
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

        // DFT: functional mode (see the bare-sep note below on test_en_i).
        .test_en_i                    (1'b0),
        .scan_rst_ni                  (1'b1),
        .ext_boot_seq_done_i          (ext_boot_seq_done_i),

        // DMI uncore (idle)
        .dmi_core_enable              (1'b0),
        .dmi_uncore_enable            (1'b0),
        .dmi_uncore_en                (),
        .dmi_uncore_wr_en             (),
        .dmi_uncore_addr              (),
        .dmi_uncore_wdata             (),
        .dmi_uncore_rdata             ('0),
        .dmi_active                   (),

        .sep_cpu_trace                (cpu_trace_w),
        // Direct reset-vector input.
        .rst_vec                      (rst_vec_i),
        .jtag_id                      ('0),

        // Interrupts (idle)
        .timer_int                    (1'b0),
        .soft_int                     (1'b0),
        .sep_ext_interrupts_i         ('0),

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

        // SPI: quad-lane struct boundary, bridged below to the
        // single-lane pad ports (sck/cs_n from req; MOSI = sd[0] out;
        // MISO returns on rsp.sd[1]).
        .sep_io_spi_req_o             (sep_io_spi_req_w),
        .sep_io_spi_rsp_i             ('{sd: {2'b00, spi_miso_i, 1'b0}}),

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
        // Route the SMC region (scratch 0x4003_9080+, straps 0x4040_5800, SMC SRAM
        // 0x4006_0000+ manifest) out the sep_ext_to_smc AXI to the TB's SMC
        // responder. The ROM boots secondary (non-SPI) and DMAs the manifest+BL1
        // from SMC SRAM.
        .smc_global_base_addr_i       (56'h4000_0000),
        .smc_region_size_i            (56'h0100_0000),
`else
        .smc_global_base_addr_i       ('0),
        .smc_region_size_i            ('0),
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
    localparam logic [55:0] SmcStrapsLoAddr = 56'h4040_5800;
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
        56'h0000_0008
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
                $error("[tb] SMC ADDRESS DECODE: write to 0x%0h is outside every register window in smc_addr.h -- the ROM is using an offset this design does not implement",
                       ext_to_smc_req_w.aw.addr);
            end
            if (smc_ar_violation) begin
                $error("[tb] SMC ADDRESS DECODE: read from 0x%0h is outside every register window in smc_addr.h -- the ROM is using an offset this design does not implement",
                       ext_to_smc_req_w.ar.addr);
            end
        end
    end

`else
    assign ext_to_smc_resp_w = ext_to_smc_resp_idle;
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

    localparam logic [38:0] BD_OTBN_ZERO = prim_secded_pkg::SecdedInv3932ZeroWord;

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
            `SEP_IPI.u_otbn_imem_sram.mem[i] = BD_OTBN_ZERO;
        for (int i = 0; i < 1024; i++)
            `SEP_IPI.u_otbn_dmem_sram.mem[i] = {8{BD_OTBN_ZERO}};
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
    end
`undef BD_ICCM
`undef BD_DCCM

    // ------------------------------------------------------------------
    // CPU-LSU AXI splice.
    //
    // Inject: assemble the LSU req struct from the flat cocotb master inputs into
    // `lsu_req_drive` (always_comb). The sep_cpu stub reads this by upward
    // reference and drives its lsu_axi_req from it (single driver, plain assign,
    // no force — see shims/cpu/sep_cpu_stub.sv). Whole-signal only; no per-field
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
    // from the CPU wrapper — the same hierarchical-read style used for the LSU
    // response above.
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
    // map to bits [23:26], EDN to [27:28] (sep.sv:548-553).
    assign sep_internal_interrupts_probe_o = `SEP_CORE.sep_internal_interrupts;

    // CPU/DMA SRAM contention. BUSY is a job-level status and does not prove
    // that both masters requested the SRAM together; no CSR mirrors per-cycle
    // crossbar arbitration. Count cycles
    // where both local-crossbar inputs present the same SRAM address channel.
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

    // Read-only XMRs observe the write-one-to-set demotion lock storage. The lock
    // bits have no DUT output, and firmware owns the AXI frontdoor while they are
    // programmed. These leaf fields sit outside the AXI ready/valid combinational
    // cones and retain whether firmware wrote each lock.
    assign lcc_demote_lock_1_probe_o =
        `SEP_CORE.u_sep_crypto.u_sep_lifecycle_ctrl.demote_reg_1.lock;
    assign lcc_demote_lock_2_probe_o =
        `SEP_CORE.u_sep_crypto.u_sep_lifecycle_ctrl.demote_reg_2.lock;

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
    logic [2:0] token_cmp_force_p, token_cmp_force_n;
    logic       token_cmp_do_force;
    always_comb begin
        token_cmp_force_p = 3'b000;
        token_cmp_force_n = 3'b000;
        token_cmp_do_force = 1'b0;
        if (token_cmp_fault_inject_i === 3'b001) begin
            token_cmp_force_p = 3'b110;
            token_cmp_force_n = 3'b000;
            token_cmp_do_force = 1'b1;
        end else if (token_cmp_fault_inject_i === 3'b010) begin
            token_cmp_force_p = 3'b110;
            token_cmp_force_n = 3'b001;
            token_cmp_do_force = 1'b1;
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
    always @(posedge clk_i) begin
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
        end else begin
            release `CMP_SIP.match_p;
            release `CMP_SIP.match_n;
            release `CMP_CHIP.match_p;
            release `CMP_CHIP.match_n;
            release `CMP_SEC.match_p;
            release `CMP_SEC.match_n;
        end
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
    // ------------------------------------------------------------------
    // eFuse read/program FSM fail-closed observability and fault injection.
    //
    // Forcing an illegal FSM encoding is the only way to provoke the
    // fail-closed behaviour `efuse_read_interface` and
    // `efuse_program_interface` assert on it. Both states are two bits whose
    // legal encodings are 2'b01 and 2'b10, and no frontdoor stimulus can
    // produce 2'b00 or 2'b11 -- the design is what guarantees that. The force
    // targets the state register only, for one cycle. Seeing the injected
    // encoding on *_state_o confirms the force landed. After release the
    // recovered encoding must be a legal idle/wait value. Command withdraw
    // and the error/done/busy/data terms are claimed only on the in-flight
    // leg. Same clock-reissued force/release convention as the digest hook
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
    // SIGNED OFF 2026-09-11 by yenhenglai, SEP TB owner.
    // ------------------------------------------------------------------
    // Only legal encodings of these two FSMs are 2'b01 and 2'b10, and the
    // sense and frontdoor paths can never present another, so the fail-closed
    // recovery the RTL specifies for 2'b00 and 2'b11 has no frontdoor
    // stimulus. Scope: the two state registers named below, for one cycle at
    // a time. Seeing the injected encoding on *_state_o confirms the force
    // landed; it is not fail-closed evidence. After release the recovered
    // encoding must be a legal idle/wait value (DUT-driven). Command
    // withdraw and the error/done/busy/data terms are claimed only on the
    // in-flight leg. Accepted claim: the legal encodings 2'b01 idle and
    // 2'b10 wait are taken from the design's state encoding, because no
    // document names them; this leaf grades recovery against that set and
    // injects its complement. Owner: sep_efuse_illegal_state_fail_closed_test.
    // Approved against ad4ae87ec, the commit that set both encodings.
    // Review at the next change to the state encoding in
    // efuse_read_interface.sv or efuse_program_interface.sv.
    //
    // The registers are enum-typed and the injected encodings are, by
    // construction, not members of those enums -- that is the property under
    // test. The conversion is therefore deliberate and scoped to these two
    // forces rather than waived file-wide.
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
    // bit [41]) / CLEAR stay frontdoor or the aggregate interrupt probe. Re-issue every clock
    // (Verilator snapshots a force RHS). Release when the port drops.
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
    // hmac_fifo_drain_stall_i=1 holds the message FIFO's rready low, so the hash
    // engine stops consuming and the FIFO fills: the wedge the ROM's bounded
    // FIFO waits must turn into a hash failure. fifo_rready is the hmac-local
    // net that drives the FIFO's read side. Re-issued every clock for Verilator,
    // released when the port drops.
`define HMAC_FIFO_RREADY `SEP_CORE.u_sep_crypto.u_hmac_wrapper_s3c_scan.u_tt_hmac.fifo_rready
    always @(posedge clk_i) begin
        if (hmac_fifo_drain_stall_i === 1'b1) begin
            force `HMAC_FIFO_RREADY = 1'b0;
        end else begin
            release `HMAC_FIFO_RREADY;
        end
    end
`undef HMAC_FIFO_RREADY

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
    // This is the one permitted force (raw noise at the source); the downstream
    // drbg_axis/edn nets below are read-only observation taps, never forced.
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
`define ESRC_NOISE_FORCE(i) \
    force `SEP_ESRC.u_generator_complex.gen_ecmplx[i].u_generator.u_decorrelator.noise_i = esrc_noise_d[i]
    // `force` is a procedural continuous override, so a plain `always` carries it.
    // The force is gated by `+esrc_noise_force` and each test is its own
    // elaboration, so it ends with the sim and needs no `release`.
    always @(negedge clk_i) begin
        if ($test$plusargs("esrc_noise_force")) begin
            `ESRC_NOISE_FORCE(0);  `ESRC_NOISE_FORCE(1);  `ESRC_NOISE_FORCE(2);
            `ESRC_NOISE_FORCE(3);  `ESRC_NOISE_FORCE(4);  `ESRC_NOISE_FORCE(5);
            `ESRC_NOISE_FORCE(6);  `ESRC_NOISE_FORCE(7);  `ESRC_NOISE_FORCE(8);
            `ESRC_NOISE_FORCE(9);  `ESRC_NOISE_FORCE(10); `ESRC_NOISE_FORCE(11);
        end
    end
`undef ESRC_NOISE_FORCE

    // +sep_crypto_edn_force -- DV SHORTCUT, off by default. Grants OTBN's EDN
    // RND/URND handshakes directly so OTBN can leave UrndRefresh and run; the
    // real entropy_source -> CSRNG -> EDN path is bypassed and NOT exercised.
    //
    // Prefer +esrc_noise_force. The SEP boot ROM brings the real entropy chain up
    // itself (src/sep_entropy.c), so a crypto test needs only raw noise injected
    // -- the ring oscillators do not self-oscillate in simulation -- and the
    // DRBG/CSRNG/EDN handshakes stay real. This force cannot do that: forcing
    // edn_ack violates the EDN req/ack data-hold protocol and trips
    // prim_sync_reqack_data's SyncReqAckDataHold* assertions. Testlist entries
    // still passing it are being migrated.
    //
    // Kept for now as a debug lever only. It is a candidate for deletion once
    // the real-entropy path has some mileage.
    logic edn_force_on;
    logic otbn_rnd_ack_q, otbn_urnd_ack_q;
    initial begin
        edn_force_on = $test$plusargs("sep_crypto_edn_force");
        if (edn_force_on) begin
            $display("[tb] *** DV SHORTCUT: +sep_crypto_edn_force -- OTBN EDN grants are");
            $display("[tb] *** forced; the entropy_source/CSRNG/EDN chain is NOT exercised.");
        end
    end

// Target the driver-side net inside sep_crypto rather than the wrapper's input
// port -- a `force` on a module instance input is rejected (ASSIGNIN).
// Client indices from sep_crypto.sv: 0 = AES, 1 = KMAC, 2 = OTBN RND,
// 3 = OTBN URND. KMAC is not forced -- the ROM's SHA-256 goes through HMAC.
`define OTBN_RND_RSP  `SEP_CORE.u_sep_crypto.crypto_edn_rsp[2]
`define OTBN_URND_RSP `SEP_CORE.u_sep_crypto.crypto_edn_rsp[3]
`define OTBN_RND_REQ  `SEP_CORE.u_sep_crypto.crypto_edn_req[2]
`define OTBN_URND_REQ `SEP_CORE.u_sep_crypto.crypto_edn_req[3]
    // ack pulses for one cycle per request rather than sitting high, so a
    // multi-word reseed is delivered as a sequence of beats like the real EDN.
    always @(posedge clk_i) begin
        if (edn_force_on) begin
            otbn_rnd_ack_q  <= `OTBN_RND_REQ.edn_req  & ~otbn_rnd_ack_q;
            otbn_urnd_ack_q <= `OTBN_URND_REQ.edn_req & ~otbn_urnd_ack_q;
            force `OTBN_RND_RSP.edn_ack   = otbn_rnd_ack_q;
            force `OTBN_RND_RSP.edn_fips  = 1'b1;
            force `OTBN_RND_RSP.edn_bus   = $urandom();
            force `OTBN_URND_RSP.edn_ack  = otbn_urnd_ack_q;
            force `OTBN_URND_RSP.edn_fips = 1'b1;
            force `OTBN_URND_RSP.edn_bus  = $urandom();
        end
    end
`undef AES_RSP
`undef AES_REQ
`undef OTBN_RND_RSP
`undef OTBN_URND_RSP
`undef OTBN_RND_REQ
`undef OTBN_URND_REQ

    // +sep_otbn_cmd_drop -- fault injection, off by default. Makes OTBN ignore
    // every command write, leaving the block powered, idle and error-free while
    // no program ever runs.
    //
    // This is the "the CMD store never landed" case: what an instruction-skip
    // glitch on the store produces deliberately, and what clock or reset
    // mis-sequencing produces by accident. It is worth injecting because the
    // block is indistinguishable from a completed run on the two registers the
    // ROM used to consult -- STATUS reads IDLE (the state it was already in) and
    // ERR_BITS reads 0 (nothing ran to fail). INTR_STATE.done is the only signal
    // that separates them, which is what otbn_execute() now requires.
    logic otbn_cmd_drop_on;
    initial begin
        otbn_cmd_drop_on = $test$plusargs("sep_otbn_cmd_drop");
        if (otbn_cmd_drop_on) begin
            $display("[tb] *** FAULT INJECTION: +sep_otbn_cmd_drop -- OTBN command writes");
            $display("[tb] *** are dropped; no OTBN program will execute.");
        end
    end

// reg2hw.cmd.qe is the write-enable otbn.sv decodes CmdExecute from
// (otbn.sv:852-854), so holding it low drops commands without disturbing
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
    // Observation-only. No CSR mirrors
    // the three-ready interlock, and a frontdoor timeout names only that the
    // access did not retire. Outside the tb s_axi / m_axi ready/valid cones.
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

    // Outbound mailbox responder + firmware-console/PASS-magic monitor.
    sep_outbound_mbx u_mbx (
        .clk_i           (clk_i),
        .rst_ni          (rst_n_int),
        .req_i           (smn_outbound_req_w),
        .resp_o          (smn_outbound_resp_w),
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
    // bug in the VIP or a sequence rather than a DUT bug. That is the value:
    // it stops an illegal transaction being blamed on the DUT.
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

    // ------------------------------------------------------------------
    // Key Manager internal AXI-Lite, CPU side. Every access KM firmware makes
    // to KPV, KMCSR, the DRBG
    // sampler and the mailbox crosses this one port: the KM crossbar has a
    // single slave port wired to the internal picorv32, so no testbench
    // master can reach it.
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
    // SV-UVM harness (`--dut sep --framework uvm`): the three clocks, the
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
    assign token_digest_test_en_inject_i = 1'b0;
    assign dma_host_intg_inject_i   = 1'b0;
    assign hmac_fifo_drain_stall_i  = 1'b0;
    assign rst_vec_i                = '0;
    assign i_cpu_run_req_i          = 1'b0;
    assign tcm_load_i               = 1'b0;
    assign esrc_noise_ext_i         = '0;
    assign spi_miso_i               = 1'b1;

    // Non-reusable test classes compile as part of this top (module scope).
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
        // sep.sv:534 assembles the SEP AXI mailbox onto
        // sep_internal_interrupts[7:0] and km_mbox_irq onto [14]. They are
        // different sources with different owning tests, so both are wired.
        .irq_mailbox_i         (sep_internal_interrupts_probe_o[7:0]),
        .irq_km_mbox_i         (sep_internal_interrupts_probe_o[14]),
        // sep.sv:535 intr_dma_done. dma_hash_test completes through the ISR,
        // which clears STATUS.done before software reads it.
        .irq_dma_done_i        (sep_internal_interrupts_probe_o[8]),
        // Sensed LC nibble out of the shadow probe. The W1S leaves verify
        // their start state through this probe and never read LC_STATE
        // frontdoor first, so the frontdoor path cannot observe RMA_SIP_0 /
        // RMA_CHIP_0 at all.
        .efuse_lc_raw_i        (efuse_shadow_probe_o[
            32 * efuse_pkg::SHADOW_IDX_LC_STATE +: 4]),
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
        .jtag_sep_reset_n_val_i  (jtag_sep_reset_ctrl_drive.val.sep_reset_n_val)
    );
`endif

`undef SEP_ESRC
`undef SEP_DRBG
`undef SEP_CORE
`undef SEP_IPI

endmodule : sep_uvm_top
