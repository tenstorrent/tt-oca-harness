// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Dual-SMC OSS TB top: two hw/top/smc_wrapper.sv instances on a shared I3C0 bus.
//
//   u_dut  the OCCP *target*    -- runs the real production boot ROM
//   u_bfm  the OCCP *controller* -- runs the DV occp_unsecure_boot_test image
//
// Dual-instance OCCP boot testbench, authored against the OSS wrapper's own
// port list. See
// docs/dual_smc_occp_boot_design.md.
//
// Why a second top instead of a define in tb_top.sv: doubling the model is a
// real cost (build time, memory) that every single-instance SMC test would pay.
// Precedent for a second top sharing a DV root is smu / smu_wrapper.
//
// Deliberately narrower than tb_top.sv. Only the surface the OCCP boot flow
// needs is lifted to ports: clocks/resets, one inbound AXI manager per
// instance, the shared I3C0 pads, and scratch/ROM-fetch observability. Every
// other wrapper port is tied off the same way tb_top.sv ties it.
//
// ---------------------------------------------------------------------------
// Shared-pad model (KNOWN RISK -- the most delicate logic in this file)
// ---------------------------------------------------------------------------
// tb_top.sv already reconstructs the I2C/I3C open-drain bus by hand (because
// `pullup` is ignored under Verilator), and its own header flags that block as
// a known risk. Here the same reconstruction has to resolve *two* real drivers
// instead of one DUT plus an external VIP:
//
//     scl = !(dut_pulls_low || bfm_pulls_low || ext_low)
//
// where "<x>_pulls_low" is that instance's own pad OE asserted while its pad
// data is 0. The resolved value is then driven strongly onto pad 27/28 of BOTH
// instances, so each one's input buffer sees the true bus state. This assumes
// the I3C core only asserts pad OE while driving a logic 0 and never pushes a
// strong 1 -- the same assumption tb_top.sv documents. If that is ever
// violated, the two strong drives can contend. Confirm on waveforms.
//
// GPIO 58 is the OCCP "target up" pad (smc_padring.sv: software GPIO, formerly
// pad 61). The controller firmware polls it in wait_for_target_up_gpio()
// (hw/sys/smc/dv/fw/common/occp/occp_interfaces.c), and the target's production
// ROM drives it from set_gpio_status(OCCP_ERROR_NONE)
// (hw/sys/smc/bootrom/prod/lib/src/occp.c:259-279), on the success path of OCCP
// init. It uses the pad number directly rather than the SMC_STATUS_GPIO macro,
// which is why that macro looks unused.
//
// The undriven value is 0, matching the reference environment's pulldown on
// this pad. It must NOT default high: a target that never asserts readiness
// would then be indistinguishable from one that does, and in silicon a real
// host would hang forever waiting for it.

`timescale 1ps/1fs

module smc_dual_uvm_top
    import smc_pkg::*;
(
    input wire logic clk_smc_i /*verilator public_flat_rw*/,
    input wire logic clk_ref_i /*verilator public_flat_rw*/,
    input wire logic clk_periph_i /*verilator public_flat_rw*/,

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

    // Shared I3C0 bus (pads 27/28). *_ext_low lets a cocotb VIP join the same
    // wired-AND as a third driver; unused by the dual-firmware flow.
    input  wire logic tb_i3c0_scl_ext_low /*verilator public_flat_rw*/,
    input  wire logic tb_i3c0_sda_ext_low /*verilator public_flat_rw*/,
    output logic      tb_i3c0_scl /*verilator public_flat_rw*/,
    output logic      tb_i3c0_sda /*verilator public_flat_rw*/,
    output logic      tb_i3c0_scl_dut_low /*verilator public_flat_rw*/,
    output logic      tb_i3c0_sda_dut_low /*verilator public_flat_rw*/,
    output logic      tb_i3c0_scl_bfm_low /*verilator public_flat_rw*/,
    output logic      tb_i3c0_sda_bfm_low /*verilator public_flat_rw*/,
    // Bus activity counters: cheap non-vacuity evidence that the two
    // instances actually talked, independent of any firmware-reported result.
    // Per-channel view of the three cross-wired I3C channels {0, 1, 3}. Index
    // is the position in that list, not the I3C instance number.
    //
    // Per-channel I3C activity, one flat scalar per position -- deliberately NOT
    // an unpacked-array port.
    //
    // Measured 2026-08-24: an unpacked-array port declared `logic [7:0] x [3]`
    // and assigned '{0,1,3} read back through cocotb as [0,0,0]. Whether that is
    // a general property of unpacked-array handles or something narrower was not
    // established -- what matters is that it failed silently and mis-attributed
    // every per-channel count. Flat scalars sidestep the question entirely, and
    // tb_i3c_channel_id_N carries the instance each position watches so the
    // mapping is asserted (smc_dual_elaboration_test) rather than assumed.
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

    // Per-instance boot-stall hold (pad 57), driven by cocotb during bring-up.
    input wire logic dut_boot_stall_hold /*verilator public_flat_rw*/,
    input wire logic bfm_boot_stall_hold /*verilator public_flat_rw*/,

    // Per-instance GPIO strap override (pads read by smc_padring straps).
    input wire logic [smc_pkg::NUM_GPIO_WRAPS-1:0] dut_gpio_ext_drive_en /*verilator public_flat_rw*/,
    input wire logic [smc_pkg::NUM_GPIO_WRAPS-1:0] dut_gpio_ext_drive_value /*verilator public_flat_rw*/,
    input wire logic [smc_pkg::NUM_GPIO_WRAPS-1:0] bfm_gpio_ext_drive_en /*verilator public_flat_rw*/,
    input wire logic [smc_pkg::NUM_GPIO_WRAPS-1:0] bfm_gpio_ext_drive_value /*verilator public_flat_rw*/,

    // ------------------------------------------------------------------
    // Inbound AXI manager into u_dut (SEP_IN). Same flat shape and prefix as
    // tb_top.sv's s_axi so the existing SmcSysAxiAgent binds unchanged.
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
);

    /* verilator public_module */

    // I3C pad numbers live in SharedI3c*Pad below, next to the channel list.
    localparam int unsigned OCCP_TARGET_UP_PAD = 58;
    localparam int unsigned BOOT_STALL_PAD = 57;

    // ------------------------------------------------------------------
    // Per-instance AXI bundles
    // ------------------------------------------------------------------
    smc_sep_in_56_64_6_12_axi_req_t  dut_sep_axi_req, bfm_sep_axi_req;
    smc_sep_in_56_64_6_12_axi_resp_t dut_sep_axi_resp, bfm_sep_axi_resp;
    smc_sys_out_56_64_8_12_axi_req_t  dut_out_axi_req, bfm_out_axi_req;
    smc_sys_out_56_64_8_12_axi_resp_t dut_out_axi_resp, bfm_out_axi_resp;

    // ------------------------------------------------------------------
    // Flat -> struct packing. `atop` is forced to 0 on both ingresses for the
    // same reason tb_top.sv does it: the outbound filter's err_slv assumes
    // atop == '0 and a fatal fires if the field X-propagates.
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
    // SYS_OUT terminators, one per instance (pulp axi_sim_mem -- the same VIP
    // and the same ApplDelay/AcqDelay floor tb_top.sv uses).
    // ------------------------------------------------------------------
    smc_sys_out_56_64_8_12_axi_req_t  [0:0] dut_out_mem_req, bfm_out_mem_req;
    smc_sys_out_56_64_8_12_axi_resp_t [0:0] dut_out_mem_resp, bfm_out_mem_resp;

    assign dut_out_mem_req[0] = dut_out_axi_req;
    assign dut_out_axi_resp   = dut_out_mem_resp[0];
    assign bfm_out_mem_req[0] = bfm_out_axi_req;
    assign bfm_out_axi_resp   = bfm_out_mem_resp[0];

    axi_sim_mem #(
        .AddrWidth         (56),
        .DataWidth         (64),
        .IdWidth           (8),
        .UserWidth         (12),
        .NumPorts          (1),
        .axi_req_t         (smc_sys_out_56_64_8_12_axi_req_t),
        .axi_rsp_t         (smc_sys_out_56_64_8_12_axi_resp_t),
        .WarnUninitialized (1'b0),
        .UninitializedData ("zeros"),
        .ClearErrOnAccess  (1'b1),
        .ApplDelay         (1ns),
        .AcqDelay          (2ns)
    ) u_dut_output_mem (
        .clk_i     (clk_smc_i),
        .rst_ni    (rst_cold_ni),
        .axi_req_i (dut_out_mem_req),
        .axi_rsp_o (dut_out_mem_resp)
    );

    axi_sim_mem #(
        .AddrWidth         (56),
        .DataWidth         (64),
        .IdWidth           (8),
        .UserWidth         (12),
        .NumPorts          (1),
        .axi_req_t         (smc_sys_out_56_64_8_12_axi_req_t),
        .axi_rsp_t         (smc_sys_out_56_64_8_12_axi_resp_t),
        .WarnUninitialized (1'b0),
        .UninitializedData ("zeros"),
        .ClearErrOnAccess  (1'b1),
        .ApplDelay         (1ns),
        .AcqDelay          (2ns)
    ) u_bfm_output_mem (
        .clk_i     (clk_smc_i),
        .rst_ni    (rst_cold_ni),
        .axi_req_i (bfm_out_mem_req),
        .axi_rsp_o (bfm_out_mem_resp)
    );

    // ------------------------------------------------------------------
    // Shared I3C open-drain resolve (see header risk note).
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
    // firmware's RNG. Forcing the choice would be weakening the test, so all
    // three selectable channels are wired instead.
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

    // Channel 0 is lifted under the historical tb_i3c0_* names so cocotb code
    // written against the single-instance TB reads the same signals.
    assign tb_i3c0_scl_dut_low = i3c_scl_dut_low[0];
    assign tb_i3c0_sda_dut_low = i3c_sda_dut_low[0];
    assign tb_i3c0_scl_bfm_low = i3c_scl_bfm_low[0];
    assign tb_i3c0_sda_bfm_low = i3c_sda_bfm_low[0];
    assign tb_i3c0_scl         = i3c_scl_bus[0];
    assign tb_i3c0_sda         = i3c_sda_bus[0];


    // Per-channel bus-activity counters. A firmware "pass" with a static SCL
    // would mean the two halves never met on the wire, so count SCL falls and
    // START conditions (SDA falling while SCL high) independently of anything
    // the firmware reports. The per-channel split also tells the test which
    // channel the controller's RNG actually picked.
    logic [NumSharedI3c-1:0] scl_q, sda_q;
    logic [31:0] scl_fall_q [NumSharedI3c];
    logic [31:0] start_q    [NumSharedI3c];

    always_ff @(posedge clk_periph_i or negedge rst_cold_ni) begin
        if (!rst_cold_ni) begin
            scl_q <= '1;
            sda_q <= '1;
            for (int unsigned ch = 0; ch < NumSharedI3c; ch++) begin
                scl_fall_q[ch] <= '0;
                start_q[ch]    <= '0;
            end
        end else begin
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
    always_ff @(posedge clk_periph_i or negedge rst_cold_ni) begin
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

    // ------------------------------------------------------------------
    // OCCP target-up pad 58: the target drives, the controller senses.
    // Undriven resolves LOW (pulldown semantics) so the handshake reflects the
    // target rather than the testbench -- see the header note.
    // ------------------------------------------------------------------
    assign tb_gpio58_from_dut = u_dut.u_smc_wrapper.u_smc.core2pad_en_o[OCCP_TARGET_UP_PAD]
                                ? u_dut.u_smc_wrapper.u_smc.core2pad_o[OCCP_TARGET_UP_PAD]
                                : 1'b0;
    assign tb_gpio58_bus = tb_gpio58_from_dut;

    // ------------------------------------------------------------------
    // Per-instance pad buses. Only 27/28 (shared I3C0) and 58 (target-up) are
    // cross-driven; every other pad is that instance's own.
    // ------------------------------------------------------------------
    wire [smc_pkg::NUM_GPIO_WRAPS-1:0] dut_gpio_pad_io;
    wire [smc_pkg::NUM_GPIO_WRAPS-1:0] bfm_gpio_pad_io;

    logic [smc_pkg::NUM_GPIO_WRAPS-1:0] dut_pad_drive_en, dut_pad_drive_val;
    logic [smc_pkg::NUM_GPIO_WRAPS-1:0] bfm_pad_drive_en, bfm_pad_drive_val;

    always_comb begin
        dut_pad_drive_en  = '0;
        dut_pad_drive_val = '1;
        bfm_pad_drive_en  = '0;
        bfm_pad_drive_val = '1;

        for (int unsigned i = 0; i < smc_pkg::NUM_GPIO_WRAPS; i++) begin
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

        // Target-up: the controller senses what the target drives, unless a
        // test is holding the pad itself. Guarded exactly like BOOT_STALL
        // below: without the guard this unconditional assignment comes after
        // the ext-override loop above and silently wins, which made
        // set_gpio_override(..., 58, ...) dead code and turned the payload
        // staging window into a race against the controller firmware.
        if (!bfm_gpio_ext_drive_en[OCCP_TARGET_UP_PAD]) begin
            bfm_pad_drive_en[OCCP_TARGET_UP_PAD]  = 1'b1;
            bfm_pad_drive_val[OCCP_TARGET_UP_PAD] = tb_gpio58_bus;
        end

        // Boot stall, per instance, unless a test overrides pad 57 directly.
        if (!dut_gpio_ext_drive_en[BOOT_STALL_PAD]) begin
            dut_pad_drive_en[BOOT_STALL_PAD]  = 1'b1;
            dut_pad_drive_val[BOOT_STALL_PAD] = dut_boot_stall_hold;
        end
        if (!bfm_gpio_ext_drive_en[BOOT_STALL_PAD]) begin
            bfm_pad_drive_en[BOOT_STALL_PAD]  = 1'b1;
            bfm_pad_drive_val[BOOT_STALL_PAD] = bfm_boot_stall_hold;
        end
    end

    for (genvar i = 0; i < smc_pkg::NUM_GPIO_WRAPS; i++) begin : gen_pad_drive
        pullup u_dut_pu (dut_gpio_pad_io[i]);
        pullup u_bfm_pu (bfm_gpio_pad_io[i]);
        assign dut_gpio_pad_io[i] = dut_pad_drive_en[i] ? dut_pad_drive_val[i] : 1'bz;
        assign bfm_gpio_pad_io[i] = bfm_pad_drive_en[i] ? bfm_pad_drive_val[i] : 1'bz;
    end

    // ------------------------------------------------------------------
    // The two SMC instances.
    //
    // Every constant tie-off lives once, in smc_dual_inst below, instead of
    // being repeated per instance or hidden in a multi-line macro (whose
    // positional argument binding is both hard to read and hard to debug when
    // it goes wrong). Only the signals that genuinely differ between the
    // controller and the target are ports of that helper.
    // ------------------------------------------------------------------
    smc_dual_inst u_dut (
        .clk_smc_i            (clk_smc_i),
        .clk_ref_i            (clk_ref_i),
        .clk_periph_i         (clk_periph_i),
        .powergood_i          (powergood_i),
        .rst_cold_ni          (rst_cold_ni),
        .rst_cool_ni          (rst_cool_ni),
        .gpio_pad_io          (dut_gpio_pad_io),
        .sep_axi_in_req_i     (dut_sep_axi_req),
        .sep_axi_in_resp_o    (dut_sep_axi_resp),
        .output_axi_req_o     (dut_out_axi_req),
        .output_axi_resp_i    (dut_out_axi_resp),
        .chiplet_is_primary_i (dut_chiplet_is_primary),
        .powergood_stable_o   (dut_powergood_stable_o),
        .rst_primary_smc_clk_no (dut_rst_primary_smc_clk_no),
        .fuse_sense_done_o    (dut_fuse_sense_done_o),
        .init_mem_done_o      (dut_init_mem_done_o),
        .rom_read_count_o     (dut_rom_read_count),
        .scratch_write_count_o(dut_scratch_write_count),
        .scratch_read_count_o (dut_scratch_read_count)
    );

    smc_dual_inst u_bfm (
        .clk_smc_i            (clk_smc_i),
        .clk_ref_i            (clk_ref_i),
        .clk_periph_i         (clk_periph_i),
        .powergood_i          (powergood_i),
        .rst_cold_ni          (rst_cold_ni),
        .rst_cool_ni          (rst_cool_ni),
        .gpio_pad_io          (bfm_gpio_pad_io),
        .sep_axi_in_req_i     (bfm_sep_axi_req),
        .sep_axi_in_resp_o    (bfm_sep_axi_resp),
        .output_axi_req_o     (bfm_out_axi_req),
        .output_axi_resp_i    (bfm_out_axi_resp),
        .chiplet_is_primary_i (bfm_chiplet_is_primary),
        .powergood_stable_o   (bfm_powergood_stable_o),
        .rst_primary_smc_clk_no (bfm_rst_primary_smc_clk_no),
        .fuse_sense_done_o    (bfm_fuse_sense_done_o),
        .init_mem_done_o      (bfm_init_mem_done_o),
        .rom_read_count_o     (bfm_rom_read_count)
    );


    // ------------------------------------------------------------------
    // Firmware observability (scratch 0/1 and retired PC per instance).
    // ------------------------------------------------------------------
    assign dut_scratch2 = u_dut.u_smc_wrapper.u_smc.u_smc_cpu_wrapper.u_smc_cpu_ctrl_wrap.scratch_reg[2];
    assign bfm_scratch2 = u_bfm.u_smc_wrapper.u_smc.u_smc_cpu_wrapper.u_smc_cpu_ctrl_wrap.scratch_reg[2];
    assign dut_wb_pc0 =
        u_dut.u_smc_wrapper.u_smc.u_smc_cpu_wrapper.gen_4core_cpu.u_smc_cpu.wb_reg_pc_raw[0];
    assign bfm_wb_pc0 =
        u_bfm.u_smc_wrapper.u_smc.u_smc_cpu_wrapper.gen_4core_cpu.u_smc_cpu.wb_reg_pc_raw[0];

    // ------------------------------------------------------------------
    // Controller I3C TX-port snoop (see the port comment). Passive: it only
    // watches the AXI-Lite write handshake, and drives nothing into the DUT.
    // ------------------------------------------------------------------
    localparam logic [31:0] I3C_TX_PORT_OFFSET = 32'h0000_0088;

    logic [31:0] bfm_tx_count_q;
    logic [31:0] bfm_tx_words_q [8];
    logic        bfm_tx_hit;
    logic [31:0] bfm_aw_addr_q;

    // Count completed W-channel handshakes, not cycles where valid happens to
    // be high: AXI-Lite holds valid until ready, so counting cycles inflates
    // (or with a stalled channel, distorts) the total. The address comes from
    // the last accepted AW, since AW and W handshake independently.
    always_ff @(posedge clk_periph_i or negedge rst_cold_ni) begin
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
        ((bfm_aw_addr_q & 32'h0000_0FFF) == I3C_TX_PORT_OFFSET);

    always_ff @(posedge clk_periph_i or negedge rst_cold_ni) begin
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

    // Scratch SRAM striping, from chipyard_4core_mem_pkg: 32 banks, round-robin
    // every 64 bytes, 8 bytes per entry. Used by the peek decode below.
    //
    // This decode is only known-correct at offset 0. Measured by
    // smc_dual_axi_sram_probe_test: patterns written and read back over AXI at
    // 0xC0066400/+8/+0x40 all verify while this formula reports zero for every
    // one of them. Nothing gates on the peek for that reason -- see
    // docs/occp_dual_boot_jump_rootcause.md.
    localparam int unsigned SCRATCH_BANK_STRIPE_BYTES = 64;
    localparam int unsigned SCRATCH_BYTES_PER_ENTRY   = 8;
    localparam int unsigned SCRATCH_ENTRIES_PER_STRIPE =
        SCRATCH_BANK_STRIPE_BYTES / SCRATCH_BYTES_PER_ENTRY;
    localparam int unsigned SCRATCH_NUM_BANKS = chipyard_4core_mem_pkg::NUM_SRAM_BANKS;

    // ------------------------------------------------------------------
    // Target scratch peek (read-only; see the port comment).
    //
    // Same 64-byte round-robin stripe decode the rest of this file uses, then a
    // per-bank mux. The bank selector has to be a mux over constant generate
    // indices, because a hierarchical reference into a generate block needs a
    // constant index.
    // ------------------------------------------------------------------
    logic [$clog2(SCRATCH_NUM_BANKS)-1:0] peek_bank;
    logic [$clog2(SCRATCH_NUM_BANKS)-1:0] bfm_peek_bank;
    logic [chipyard_4core_mem_pkg::SMC_4CORE_SCRATCH_RAM_ADDR_WIDTH-1:0] bfm_peek_entry;
    logic [chipyard_4core_mem_pkg::SMC_4CORE_SCRATCH_RAM_DATA_WIDTH-1:0]
        bfm_peek_bank_data [SCRATCH_NUM_BANKS];
    logic [chipyard_4core_mem_pkg::SMC_4CORE_SCRATCH_RAM_DATA_WIDTH-1:0] bfm_peek_word;
    logic [chipyard_4core_mem_pkg::SMC_4CORE_SCRATCH_RAM_ADDR_WIDTH-1:0] peek_entry;
    logic [chipyard_4core_mem_pkg::SMC_4CORE_SCRATCH_RAM_DATA_WIDTH-1:0]
        peek_bank_data [SCRATCH_NUM_BANKS];
    logic [chipyard_4core_mem_pkg::SMC_4CORE_SCRATCH_RAM_DATA_WIDTH-1:0] peek_word;

    always_comb begin
        peek_bank  = (tb_dut_scratch_peek_offset / SCRATCH_BANK_STRIPE_BYTES)
                     % SCRATCH_NUM_BANKS;
        peek_entry = (tb_dut_scratch_peek_offset /
                        (SCRATCH_BANK_STRIPE_BYTES * SCRATCH_NUM_BANKS))
                     * SCRATCH_ENTRIES_PER_STRIPE
                     + (tb_dut_scratch_peek_offset % SCRATCH_BANK_STRIPE_BYTES)
                       / SCRATCH_BYTES_PER_ENTRY;
    end

    for (genvar b = 0; b < SCRATCH_NUM_BANKS; b++) begin : gen_peek_bank
        assign peek_bank_data[b] =
            u_dut.u_smc_wrapper.u_smc_cpu_mem_integration.u_mems
                .gen_scratch_rams[b].mem.mem.mem[peek_entry];
    end

    always_comb begin
        bfm_peek_bank  = (tb_bfm_scratch_peek_offset / SCRATCH_BANK_STRIPE_BYTES)
                         % SCRATCH_NUM_BANKS;
        bfm_peek_entry = (tb_bfm_scratch_peek_offset /
                            (SCRATCH_BANK_STRIPE_BYTES * SCRATCH_NUM_BANKS))
                         * SCRATCH_ENTRIES_PER_STRIPE
                         + (tb_bfm_scratch_peek_offset % SCRATCH_BANK_STRIPE_BYTES)
                           / SCRATCH_BYTES_PER_ENTRY;
    end

    for (genvar b = 0; b < SCRATCH_NUM_BANKS; b++) begin : gen_bfm_peek_bank
        assign bfm_peek_bank_data[b] =
            u_bfm.u_smc_wrapper.u_smc_cpu_mem_integration.u_mems
                .gen_scratch_rams[b].mem.mem.mem[bfm_peek_entry];
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
    // smc_cpu_mem_integration's backdoor (#0.2), so this override always wins.
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
                          u_bfm.u_smc_wrapper.u_smc_cpu_mem_integration.u_mems.rom_mem.mem.mem);
                $display("[tb_top_dual] u_bfm ROM override (hex) %s", bfm_rom_path);
            end else begin
                $error("[tb_top_dual] missing +bfm_rom_hex image %s", bfm_rom_path);
            end
        end else if ($value$plusargs("bfm_rom_bin64=%s", bfm_rom_path)) begin
            bfm_rom_fd = $fopen(bfm_rom_path, "r");
            if (bfm_rom_fd != 0) begin
                $fclose(bfm_rom_fd);
                $readmemb(bfm_rom_path,
                          u_bfm.u_smc_wrapper.u_smc_cpu_mem_integration.u_mems.rom_mem.mem.mem);
                $display("[tb_top_dual] u_bfm ROM override (bin64) %s", bfm_rom_path);
            end else begin
                $error("[tb_top_dual] missing +bfm_rom_bin64 image %s", bfm_rom_path);
            end
        end else begin
            $display("[tb_top_dual] no +bfm_rom_hex/+bfm_rom_bin64: both instances run the same image");
        end
    end


endmodule : smc_dual_uvm_top

//-----------------------------------------------------------------------------
// One SMC instance with every constant tie-off applied.
//
// Exists so the dual top instantiates it twice instead of repeating ~130 tie-off
// connections per instance. Each tie-off value matches the single-instance
// hw/sys/smc/dv/tb/tb_top.sv, so a behavioural difference between the two tops
// cannot come from a stray default. Only the ports below differ per instance.
//-----------------------------------------------------------------------------
module smc_dual_inst
    import smc_pkg::*;
(
    input  logic clk_smc_i,
    input  logic clk_ref_i,
    input  logic clk_periph_i,
    input  logic powergood_i,
    input  logic rst_cold_ni,
    input  logic rst_cool_ni,

    inout  wire [smc_pkg::NUM_GPIO_WRAPS-1:0] gpio_pad_io,

    input  smc_sep_in_56_64_6_12_axi_req_t   sep_axi_in_req_i,
    output smc_sep_in_56_64_6_12_axi_resp_t  sep_axi_in_resp_o,
    output smc_sys_out_56_64_8_12_axi_req_t  output_axi_req_o,
    input  smc_sys_out_56_64_8_12_axi_resp_t output_axi_resp_i,

    input  logic chiplet_is_primary_i,

    output logic        powergood_stable_o,
    output logic        rst_primary_smc_clk_no,
    output logic        fuse_sense_done_o,
    output logic        init_mem_done_o,
    output logic [31:0] rom_read_count_o,
    output logic [31:0] scratch_write_count_o,
    output logic [31:0] scratch_read_count_o
);

    // Idle inbound buses. Declared rather than inlined as '0 so the struct
    // types are explicit at the tie-off site.
    smc_sys_in_56_64_6_12_axi_req_t sys_axi_idle_req;
    smc_jtag_56_64_2_12_axi_req_t   jtag_axi_idle_req;
    smc_axil_32_32_req_t            axil_idle_req;
    smc_axil_32_32_resp_t           axil_idle_resp;

    assign sys_axi_idle_req  = '0;
    assign jtag_axi_idle_req = '0;
    assign axil_idle_req     = '0;
    // DTP CSR: no TB err_slv, matching tb_top.sv's no-placeholder policy.
    assign axil_idle_resp    = '0;

    telemetry_receiver_pkg::telemetry_data_t
        [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_idle_data;
    telemetry_receiver_pkg::atb_id_t
        [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_idle_id;
    assign telemetry_idle_data = '0;
    assign telemetry_idle_id   = '0;

    // Product lc_state_i idle = complementary TEST_DEV ({~0, 0}), same encoding
    // smc_base_test drives onto tb_lc_state in the single-instance TB.
    logic [2*smc_pkg::LC_STATE_WIDTH-1:0] lc_state_idle;
    assign lc_state_idle = {{smc_pkg::LC_STATE_WIDTH{1'b1}},
                            {smc_pkg::LC_STATE_WIDTH{1'b0}}};

    // I3C DAT/DCT/RLT table memories, one set per instance.
    //
    // smc_wrapper exposes these as boundary ports and hands out the gated I3C
    // peripheral clock to run them (gated_clk_periph_i3c_o) plus the peripheral
    // reset -- a complete "attach your memories here" interface. Attaching them
    // above the wrapper is the same composition pattern
    // hw/sys/smu/dv/tb/tb_wrapper_top.sv uses for smc_cpu_mem_integration on
    // smu_wrapper's passthrough CPU memory ports, and it keeps the technology
    // choice out of the wrapper.
    //
    // Instantiated here in smc_dual_inst rather than in the top body so each of
    // u_dut and u_bfm gets its own independent set, which is what the OCCP flow
    // needs: the controller's ENTDAA writes its own DAT and the target's core
    // reads a different one.
    i3c_pkg::dat_mem_src_t  [smc_config_pkg::NUM_I3C-1:0] i3c_dat_mem_src;
    i3c_pkg::dat_mem_sink_t [smc_config_pkg::NUM_I3C-1:0] i3c_dat_mem_sink;
    i3c_pkg::dct_mem_src_t  [smc_config_pkg::NUM_I3C-1:0] i3c_dct_mem_src;
    i3c_pkg::dct_mem_sink_t [smc_config_pkg::NUM_I3C-1:0] i3c_dct_mem_sink;
    i3c_pkg::rlt_mem_src_t  [smc_config_pkg::NUM_I3C-1:0] i3c_rlt_mem_src;
    i3c_pkg::rlt_mem_sink_t [smc_config_pkg::NUM_I3C-1:0] i3c_rlt_mem_sink;

    logic gated_clk_periph_i3c;
    logic rst_primary_periph_clk_n;

    smc_i3c_mem_integration u_smc_i3c_mem_integration (
        .clk_i          (gated_clk_periph_i3c),
        .rst_ni         (rst_primary_periph_clk_n),
        .dat_mem_src_o  (i3c_dat_mem_src),
        .dat_mem_sink_i (i3c_dat_mem_sink),
        .dct_mem_src_o  (i3c_dct_mem_src),
        .dct_mem_sink_i (i3c_dct_mem_sink),
        .rlt_mem_src_o  (i3c_rlt_mem_src),
        .rlt_mem_sink_i (i3c_rlt_mem_sink)
    );

    smc_wrapper u_smc_wrapper (
        .clk_smc_i                  (clk_smc_i),
        .clk_ref_i                  (clk_ref_i),
        .clk_periph_i               (clk_periph_i),
        .powergood_i                (powergood_i),
        .powergood_stable_o         (powergood_stable_o),
        .rst_cold_ni                (rst_cold_ni),
        .rst_cold_stable_ref_clk_no (),
        .rst_primary_ref_clk_no     (),
        .rst_primary_smc_clk_no     (rst_primary_smc_clk_no),
        .rst_wdt_smc_clk_no         (),
        .rst_primary_periph_clk_no  (rst_primary_periph_clk_n),
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
        .clk_telemetry_i            (clk_smc_i),
        .rst_telemetry_ni           (rst_cold_ni),
        .telemetry_atdata_i         (telemetry_idle_data),
        .telemetry_atid_i           (telemetry_idle_id),
        .telemetry_atready_o        (),
        .telemetry_atvalid_i        ('0),
        .telemetry_afvalid_o        (),
        .telemetry_afready_i        ('1),
        .cluster_ded_o              (),
        .wdt_first_timeout_o        (),
        .wdt_second_timeout_o       (),
        .smc_global_base_o          (),
        .smc_region_size_o          (),
        .ext_interrupts_i           ('0),
        .sep_mailbox_interrupts_i   ('0),
        .sep_wdt_reset_n_i          (1'b1),
        .fuse_sense_done_o          (fuse_sense_done_o),
        .fuse_reset_n_delayed_o     (),
        .skip_mem_repair_o          (),
        .ext_boot_seq_done_i        (1'b1),
        .sep_security_disable_i     (1'b0),
        .temp_interrupt_i           (1'b0),
        .lc_state_i                 (lc_state_idle),
        .lc_sigint_err_o            (),
        .ras_bank_chip_o            (),
        .ras_bank_instance_o        (),
        .ndmreset_request_i         ('0),
        .ndmreset_process_o         (),
        .ext_mailbox_interrupts_o   (),
        .cfg_flr_pf_active_i        (1'b0),
        .isolate_req_o              (),
        .ss_reset_complete_i        ('1),
        .ss_config_o                (),
        .ss_reset_ctrl_o            (),
        .sync_irq_o                 (),
        .cpu_rom_read_count_o       (rom_read_count_o),
        .cpu_scratch_read_count_o   (scratch_read_count_o),
        .cpu_scratch_write_count_o  (scratch_write_count_o),
        .cpu_dcache_write_count_o   (),
        .cpu_ecc_inject_sbe_i       (1'b0),
        .cpu_ecc_inject_dbe_i       (1'b0),
        .cpu_scratch0_inject_fire_o (),
        .disable_sram_auto_init_i   (1'b1),
        .init_mem_done_o            (init_mem_done_o),
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
        .trace_mem_req_o            (),
        .trace_mem_resp_i           ('0),
        .ext_debug_bus_i            ('0),
        .test_en_i                  (1'b0),
        .scan_rst_ni                (1'b1),
        .captured_straps_i          ('0),
        // Without an external BISR/MBIST agent the boot sequencer waits forever
        // if these stay low (same fix as tb_top.sv / tb_wrapper_top.sv).
        .mem_repair_done_i          (1'b1),
        .mem_repair_success_i       (1'b1),
        .mem_repair_abort_i         (1'b0),
        .mbist_done_i               (1'b1),
        .mbist_pass_i               (1'b1),
        .mbist_abort_i              (1'b0),
        .smc_cpu_jtag_TCK_i         (1'b0),
        .smc_cpu_jtag_TMS_i         (1'b1),
        .smc_cpu_jtag_TDI_i         (1'b0),
        .smc_cpu_jtag_TDO_data_o    (),
        .smc_cpu_jtag_reset_i       (1'b1),
        .smc_cpu_jtag_mfr_id_i      (11'h2AA),
        .smc_cpu_jtag_part_number_i (16'h0CA0),
        .smc_cpu_jtag_version_i     (4'h1),
        .gated_clk_periph_i3c_o     (gated_clk_periph_i3c),
        .i3c_dat_mem_src_i          (i3c_dat_mem_src),
        .i3c_dat_mem_sink_o         (i3c_dat_mem_sink),
        .i3c_dct_mem_src_i          (i3c_dct_mem_src),
        .i3c_dct_mem_sink_o         (i3c_dct_mem_sink),
        .i3c_rlt_mem_src_i          (i3c_rlt_mem_src),
        .i3c_rlt_mem_sink_o         (i3c_rlt_mem_sink),
        .gpio_interrupt_o           (),
        .uart_interrupt_o           (),
        .efuse_debug_bus_o          ()
    );

endmodule : smc_dual_inst
