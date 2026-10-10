// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Copyright 2026 Tenstorrent Inc.

// Exchange messages between SEP and KM through two FIFOs behind independent AXI4-Lite
// slave interfaces.
//
// Two synchronous FIFOs sit between the KM-side and SEP-side slaves:
//
// - Inbound FIFO (SEP -> KM): SEP writes via WRITE_DATA, KM reads via READ_DATA.
// - Outbound FIFO (KM -> SEP): KM writes via WRITE_DATA, SEP reads via READ_DATA.
//
// Each FIFO word carries a 1-bit separator tag for message framing, taken from the
// writer's WRITE_SEPARATOR register, which hardware clears after the next push, and
// shown in both sides' STATUS when the reader pops the word. WRITE_DATA /
// READ_DATA addresses are handled as direct FIFO push/pop; STATUS and IRQ registers are
// served by RDL-generated register blocks.
//
// Overflow and underflow responses are configurable per side (SLVERR or OKAY). Both sides
// can flush all FIFOs via CTRL.FLUSH. Each side ORs its IRQ from data-available and
// write-space-available (level) plus sticky overflow / underflow / flushed-by-peer events,
// each masked by that side's IRQ_ENABLE.

module km_mailbox
  import km_mailbox_sep_reg_pkg::km_mailbox_sep__in_t;
  import km_mailbox_sep_reg_pkg::km_mailbox_sep__out_t;
  import km_mailbox_km_reg_pkg::km_mailbox_km__in_t;
  import km_mailbox_km_reg_pkg::km_mailbox_km__out_t;
  import km_mailbox_sep_addrmap_pkg::KM_MAILBOX_SEP_SEP_WRITE_DATA_BASE_ADDR;
  import km_mailbox_sep_addrmap_pkg::KM_MAILBOX_SEP_SEP_READ_DATA_BASE_ADDR;
  import km_mailbox_km_addrmap_pkg::KM_MAILBOX_KM_KM_WRITE_DATA_BASE_ADDR;
  import km_mailbox_km_addrmap_pkg::KM_MAILBOX_KM_KM_READ_DATA_BASE_ADDR;
#(
  parameter int unsigned MAILBOX_DEPTH = 16,  // Words per FIFO direction.

  parameter type km_axil_req_t  = km_intf_pkg::km_axil_req_t,   // KM-side AXI-Lite request type;
                                                                // defaults to km_intf_pkg.
  parameter type km_axil_resp_t = km_intf_pkg::km_axil_resp_t,  // KM-side AXI-Lite response
                                                                // type; defaults to km_intf_pkg.
  parameter type sep_axil_req_t  = logic,                       // SEP-side AXI-Lite request
                                                                // type; must be provided
                                                                // explicitly (not defined in
                                                                // km_intf_pkg).
  parameter type sep_axil_resp_t = logic                        // SEP-side AXI-Lite response
                                                                // type; must be provided
                                                                // explicitly.
) (
  input  logic clk_i,        // System clock.
  input  logic cold_rst_ni,  // Cold reset: AASD; resets the FIFOs and SEP-facing interfaces.
  input  logic warm_rst_ni,  // Warm reset: synchronous; resets the KM-CPU-facing interfaces.
  input  logic test_en_i,    // DFT test-enable; unused.

  input  km_axil_req_t km_axil_req_i,    // KM CPU AXI4-Lite slave request: pushes the outbound
                                         // FIFO, pops the inbound FIFO and reaches the KM-side
                                         // registers.
  output km_axil_resp_t km_axil_resp_o,  // KM CPU AXI4-Lite slave response.

  input  sep_axil_req_t sep_axil_req_i,    // SEP host AXI4-Lite slave request: pushes the
                                           // inbound FIFO, pops the outbound FIFO and reaches
                                           // the SEP-side registers.
  output sep_axil_resp_t sep_axil_resp_o,  // SEP host AXI4-Lite slave response.


  output logic        mbox_irq_to_km_o,  // Level IRQ to the KM CPU: OR of the KM-side sources
                                         // masked by KM_IRQ_ENABLE.
  output logic        mbox_irq_to_sep_o  // Level IRQ to the SEP host: OR of the SEP-side sources
                                         // masked by SEP_IRQ_ENABLE.
);

  `include "prim_assert.sv"
  `include "ocah_assert.svh"

  //=========================================================================
  // Local Parameters
  //=========================================================================

  // FIFO word width: 32-bit data plus 1 separator bit for message framing.
  localparam int unsigned FifoWidth = 33;
  // FIFO depth counter width (sized to represent 0..MAILBOX_DEPTH).
  localparam int unsigned FifoDepthW = $clog2(MAILBOX_DEPTH + 1);

  //=========================================================================
  // Inbound FIFO (SEP→KM)
  //=========================================================================

  logic inbound_wvalid, inbound_wready;
  logic inbound_rvalid, inbound_rready;
  logic [32:0] inbound_wdata, inbound_rdata;  // [31:0] data, [32] separator
  logic inbound_full, inbound_empty;
  logic [FifoDepthW-1:0] inbound_depth;

  // Flush: when either side sets CTRL.FLUSH=1, clear both FIFOs
  // Hardware monitors the register bits and clears them after flush completes
  logic km_flush_active, sep_flush_active, fifo_clr;
  assign fifo_clr = km_flush_active || sep_flush_active;

  prim_fifo_sync #(
    .Width(FifoWidth),
    .Depth(MAILBOX_DEPTH),
    .Pass(1'b0),  // No pass-through
    .OutputZeroIfEmpty(1'b1)
  ) u_inbound_fifo (
    .clk_i,
    .rst_ni  (cold_rst_ni),
    .clr_i(fifo_clr),
    .wvalid_i(inbound_wvalid),
    .wready_o(inbound_wready),
    .wdata_i(inbound_wdata),
    .rvalid_o(inbound_rvalid),
    .rready_i(inbound_rready),
    .rdata_o(inbound_rdata),
    .full_o(inbound_full),
    .depth_o(inbound_depth),
    .err_o()
  );

  assign inbound_empty = (inbound_depth == 0);

  //=========================================================================
  // Outbound FIFO (KM→SEP)
  //=========================================================================

  logic outbound_wvalid, outbound_wready;
  logic outbound_rvalid, outbound_rready;
  logic [32:0] outbound_wdata, outbound_rdata;  // [31:0] data, [32] separator
  logic outbound_full, outbound_empty;
  logic [FifoDepthW-1:0] outbound_depth;

  prim_fifo_sync #(
    .Width(FifoWidth),
    .Depth(MAILBOX_DEPTH),
    .Pass(1'b0),  // No pass-through
    .OutputZeroIfEmpty(1'b1)
  ) u_outbound_fifo (
    .clk_i,
    .rst_ni  (cold_rst_ni),
    .clr_i(fifo_clr),
    .wvalid_i(outbound_wvalid),
    .wready_o(outbound_wready),
    .wdata_i(outbound_wdata),
    .rvalid_o(outbound_rvalid),
    .rready_i(outbound_rready),
    .rdata_o(outbound_rdata),
    .full_o(outbound_full),
    .depth_o(outbound_depth),
    .err_o()
  );

  assign outbound_empty = (outbound_depth == 0);

  //=========================================================================
  // SEP AXI Interface - Direct FIFO Access + Register Block
  //=========================================================================

  // Combinational address decode for SEP (used for immediate routing decisions)
  logic [11:0] sep_aw_addr, sep_ar_addr;
  logic sep_aw_is_write_data, sep_ar_is_read_data, sep_aw_is_reg_block, sep_ar_is_reg_block;

  assign sep_aw_addr = sep_axil_req_i.aw.addr[11:0];
  assign sep_ar_addr = sep_axil_req_i.ar.addr[11:0];

  assign sep_aw_is_write_data = (sep_aw_addr == KM_MAILBOX_SEP_SEP_WRITE_DATA_BASE_ADDR);
  assign sep_ar_is_read_data = (sep_ar_addr == KM_MAILBOX_SEP_SEP_READ_DATA_BASE_ADDR);
  assign sep_aw_is_reg_block = !sep_aw_is_write_data;
  assign sep_ar_is_reg_block = !sep_ar_is_read_data;

  // SEP register block (for STATUS, IRQ_STATUS, IRQ_ENABLE)
  km_mailbox_sep__in_t  sep_hwif_in;
  km_mailbox_sep__out_t sep_hwif_out;

  // SEP-side CTRL register bits (for overflow/underflow response configuration)
  // Declared early so they can be used in SEP write/read state machines
  logic inbound_overflow_resp_okay;   // SEP-side CTRL: inbound overflow response (0=SLVERR, 1=OKAY)
  logic outbound_underflow_resp_okay; // SEP-side CTRL: outbound underflow response (0=SLVERR, 1=OKAY)
  assign inbound_overflow_resp_okay = sep_hwif_out.SEP_CTRL.inbound_overflow_resp.value;
  assign outbound_underflow_resp_okay = sep_hwif_out.SEP_CTRL.outbound_underflow_resp.value;

  //-------------------------------------------------------------------------
  // SEP Write Channel State Machine (for FIFO writes)
  //-------------------------------------------------------------------------
  // Proper AXI-Lite: accept AW and W independently, respond with B after both

  logic sep_fifo_aw_pending_q;  // AW handshake done, waiting for W
  logic sep_fifo_b_valid_q;     // B response pending
  logic sep_fifo_b_resp_q;      // B response: 0=OKAY, 1=SLVERR

  // Handshake signals for FIFO write path
  logic sep_fifo_aw_handshake, sep_fifo_w_handshake;
  assign sep_fifo_aw_handshake = sep_axil_req_i.aw_valid && sep_aw_is_write_data &&
                                   !sep_fifo_aw_pending_q && !sep_fifo_b_valid_q;
  assign sep_fifo_w_handshake = sep_axil_req_i.w_valid &&
                                  (sep_fifo_aw_pending_q || sep_fifo_aw_handshake) &&
                                  !sep_fifo_b_valid_q;

  always_ff @(posedge clk_i or negedge cold_rst_ni) begin
    if (!cold_rst_ni) begin
      sep_fifo_aw_pending_q <= 1'b0;
      sep_fifo_b_valid_q <= 1'b0;
      sep_fifo_b_resp_q <= 1'b0;
    end else begin
      // AW handshake
      if (sep_fifo_aw_handshake && !sep_fifo_w_handshake) begin
        sep_fifo_aw_pending_q <= 1'b1;
      end

      // W handshake - perform FIFO write and generate B response
      if (sep_fifo_w_handshake) begin
        sep_fifo_aw_pending_q <= 1'b0;
        sep_fifo_b_valid_q <= 1'b1;
        // Use config-controlled response: OKAY if configured, SLVERR if full (default)
        sep_fifo_b_resp_q <= inbound_full && !inbound_overflow_resp_okay;
      end

      // B handshake - clear response
      if (sep_fifo_b_valid_q && sep_axil_req_i.b_ready) begin
        sep_fifo_b_valid_q <= 1'b0;
      end
    end
  end

  // FIFO write happens on W handshake when not full; [32]=separator, [31:0]=data
  assign inbound_wvalid = sep_fifo_w_handshake && !inbound_full;
  assign inbound_wdata = { sep_hwif_out.SEP_WRITE_SEPARATOR.set.value, sep_axil_req_i.w.data };

  //-------------------------------------------------------------------------
  // SEP Read Channel State Machine (for FIFO reads)
  //-------------------------------------------------------------------------
  // Proper AXI-Lite: accept AR, respond with R on next cycle

  logic sep_fifo_r_valid_q;     // R response pending
  logic sep_fifo_r_resp_q;      // R response: 0=OKAY, 1=SLVERR
  logic [31:0] sep_fifo_r_data_q;  // R data captured from FIFO

  // AR handshake for FIFO read path
  logic sep_fifo_ar_handshake;
  assign sep_fifo_ar_handshake = sep_axil_req_i.ar_valid && sep_ar_is_read_data && !sep_fifo_r_valid_q;

  always_ff @(posedge clk_i or negedge cold_rst_ni) begin
    if (!cold_rst_ni) begin
      sep_fifo_r_valid_q <= 1'b0;
      sep_fifo_r_resp_q <= 1'b0;
      sep_fifo_r_data_q <= 32'h0;
    end else begin
      // AR handshake - capture FIFO data and generate R response
      if (sep_fifo_ar_handshake) begin
        sep_fifo_r_valid_q <= 1'b1;
        // Use config-controlled response: OKAY if configured, SLVERR if empty (default)
        sep_fifo_r_resp_q <= outbound_empty && !outbound_underflow_resp_okay;
        sep_fifo_r_data_q <= outbound_empty ? 32'h0 : outbound_rdata[31:0];
      end

      // R handshake - clear response
      if (sep_fifo_r_valid_q && sep_axil_req_i.r_ready) begin
        sep_fifo_r_valid_q <= 1'b0;
      end
    end
  end

  // FIFO read (pop) happens on AR handshake when not empty
  assign outbound_rready = sep_fifo_ar_handshake && !outbound_empty;


  // SEP-side overflow/underflow detection signals (defined after handshake signals)
  logic sep_inbound_overflow_detected;   // SEP writes to full inbound FIFO
  logic sep_outbound_underflow_detected; // SEP reads from empty outbound FIFO
  assign sep_inbound_overflow_detected = sep_fifo_w_handshake && inbound_full;
  assign sep_outbound_underflow_detected = sep_fifo_ar_handshake && outbound_empty;

  //-------------------------------------------------------------------------
  // SEP Register Block Interface
  //-------------------------------------------------------------------------
  logic sep_reg_awready, sep_reg_awvalid;
  logic [km_mailbox_sep_reg_pkg::KM_MAILBOX_SEP_REG_MIN_ADDR_WIDTH-1:0] sep_reg_awaddr;
  logic [2:0] sep_reg_awprot;
  logic sep_reg_wready, sep_reg_wvalid;
  logic [31:0] sep_reg_wdata;
  logic [3:0] sep_reg_wstrb;
  logic sep_reg_bready, sep_reg_bvalid;
  logic [1:0] sep_reg_bresp;
  logic sep_reg_arready, sep_reg_arvalid;
  logic [km_mailbox_sep_reg_pkg::KM_MAILBOX_SEP_REG_MIN_ADDR_WIDTH-1:0] sep_reg_araddr;
  logic [2:0] sep_reg_arprot;
  logic sep_reg_rready, sep_reg_rvalid;
  logic [31:0] sep_reg_rdata;
  logic [1:0] sep_reg_rresp;

  // Route to register block only for register addresses
  assign sep_reg_awvalid = sep_axil_req_i.aw_valid && sep_aw_is_reg_block;
  assign sep_reg_awaddr  = sep_axil_req_i.aw.addr[km_mailbox_sep_reg_pkg::KM_MAILBOX_SEP_REG_MIN_ADDR_WIDTH-1:0];
  assign sep_reg_awprot  = sep_axil_req_i.aw.prot;
  assign sep_reg_wvalid  = sep_axil_req_i.w_valid && sep_aw_is_reg_block;
  assign sep_reg_wdata   = sep_axil_req_i.w.data;
  assign sep_reg_wstrb   = sep_axil_req_i.w.strb;
  assign sep_reg_bready  = sep_axil_req_i.b_ready;
  assign sep_reg_arvalid = sep_axil_req_i.ar_valid && sep_ar_is_reg_block;
  assign sep_reg_araddr  = sep_axil_req_i.ar.addr[km_mailbox_sep_reg_pkg::KM_MAILBOX_SEP_REG_MIN_ADDR_WIDTH-1:0];
  assign sep_reg_arprot  = sep_axil_req_i.ar.prot;
  assign sep_reg_rready  = sep_axil_req_i.r_ready;

  // Register block instantiation (SEP-facing: cold reset only)
  km_mailbox_sep_reg u_sep_regs (
    .clk            (clk_i),
    .arst_n         (cold_rst_ni),
    .s_axil_awready (sep_reg_awready),
    .s_axil_awvalid (sep_reg_awvalid),
    .s_axil_awaddr  (sep_reg_awaddr),
    .s_axil_awprot  (sep_reg_awprot),
    .s_axil_wready  (sep_reg_wready),
    .s_axil_wvalid  (sep_reg_wvalid),
    .s_axil_wdata   (sep_reg_wdata),
    .s_axil_wstrb   (sep_reg_wstrb),
    .s_axil_bready  (sep_reg_bready),
    .s_axil_bvalid  (sep_reg_bvalid),
    .s_axil_bresp   (sep_reg_bresp),
    .s_axil_arready (sep_reg_arready),
    .s_axil_arvalid (sep_reg_arvalid),
    .s_axil_araddr  (sep_reg_araddr),
    .s_axil_arprot  (sep_reg_arprot),
    .s_axil_rready  (sep_reg_rready),
    .s_axil_rvalid  (sep_reg_rvalid),
    .s_axil_rdata   (sep_reg_rdata),
    .s_axil_rresp   (sep_reg_rresp),
    .hwif_in        (sep_hwif_in),
    .hwif_out       (sep_hwif_out)
  );

  //-------------------------------------------------------------------------
  // SEP Response Muxing
  //-------------------------------------------------------------------------
  // Mux between register block and FIFO state machines

  // Write address channel
  assign sep_axil_resp_o.aw_ready = sep_aw_is_reg_block ? sep_reg_awready :
                                      sep_aw_is_write_data ? sep_fifo_aw_handshake : 1'b0;

  // Write data channel
  assign sep_axil_resp_o.w_ready = sep_aw_is_reg_block ? sep_reg_wready :
                                     sep_fifo_w_handshake;

  // Write response channel
  assign sep_axil_resp_o.b_valid = sep_reg_bvalid || sep_fifo_b_valid_q;
  assign sep_axil_resp_o.b.resp = sep_reg_bvalid ? sep_reg_bresp :
                                    sep_fifo_b_resp_q ? axi_pkg::RESP_SLVERR : axi_pkg::RESP_OKAY;

  // Read address channel
  assign sep_axil_resp_o.ar_ready = sep_ar_is_reg_block ? sep_reg_arready :
                                      sep_ar_is_read_data ? sep_fifo_ar_handshake : 1'b0;

  // Read data channel
  assign sep_axil_resp_o.r_valid = sep_reg_rvalid || sep_fifo_r_valid_q;
  assign sep_axil_resp_o.r.data = sep_reg_rvalid ? sep_reg_rdata : sep_fifo_r_data_q;
  assign sep_axil_resp_o.r.resp = sep_reg_rvalid ? sep_reg_rresp :
                                    sep_fifo_r_resp_q ? axi_pkg::RESP_SLVERR : axi_pkg::RESP_OKAY;

  // SEP IRQ enable from register (controls SEP's interrupt for outbound data)
  logic sep_irq_enable;
  assign sep_irq_enable = sep_hwif_out.SEP_IRQ_ENABLE.outbound_read_data_avail_en.value;

  //=========================================================================
  // KM AXI Interface - Direct FIFO Access + Register Block
  //=========================================================================

  // Combinational address decode for KM (used for immediate routing decisions)
  //
  // Portal compares span the register block's address width: a wider slice
  // would match every address that repeats a portal's offset.
  localparam int unsigned KmRegAddrW = km_mailbox_km_reg_pkg::KM_MAILBOX_KM_REG_MIN_ADDR_WIDTH;

  logic [KmRegAddrW-1:0] km_aw_addr, km_ar_addr;
  logic km_aw_is_write_data, km_ar_is_read_data, km_aw_is_reg_block, km_ar_is_reg_block;

  assign km_aw_addr = km_axil_req_i.aw.addr[KmRegAddrW-1:0];
  assign km_ar_addr = km_axil_req_i.ar.addr[KmRegAddrW-1:0];

  assign km_aw_is_write_data = (km_aw_addr == KM_MAILBOX_KM_KM_WRITE_DATA_BASE_ADDR);
  assign km_ar_is_read_data = (km_ar_addr == KM_MAILBOX_KM_KM_READ_DATA_BASE_ADDR);
  assign km_aw_is_reg_block = !km_aw_is_write_data;
  assign km_ar_is_reg_block = !km_ar_is_read_data;

  // Captured separator bits: updated when receiver pops (not sticky)
  logic inbound_separator_q, outbound_separator_q;

  // KM register block (for STATUS, IRQ_STATUS, IRQ_ENABLE)
  km_mailbox_km__in_t  km_hwif_in;
  km_mailbox_km__out_t km_hwif_out;

  // KM-side CTRL register bits
  logic outbound_overflow_resp_okay;   // KM-side CTRL: outbound overflow response (0=SLVERR, 1=OKAY)
  logic inbound_underflow_resp_okay;   // KM-side CTRL: inbound underflow response (0=SLVERR, 1=OKAY)
  // Assignments moved after register block instantiation

  // Hardware inputs to register block
  assign km_hwif_in.KM_STATUS.inbound_empty.next = inbound_empty;
  assign km_hwif_in.KM_STATUS.inbound_full.next  = inbound_full;
  assign km_hwif_in.KM_STATUS.outbound_empty.next = outbound_empty;
  assign km_hwif_in.KM_STATUS.outbound_full.next  = outbound_full;
  // Zero-extend depth to 8 bits to prevent X propagation
  assign km_hwif_in.KM_STATUS.inbound_depth.next  = {{(8-FifoDepthW){1'b0}}, inbound_depth};
  assign km_hwif_in.KM_STATUS.outbound_depth.next = {{(8-FifoDepthW){1'b0}}, outbound_depth};
  assign km_hwif_in.KM_STATUS.inbound_separator.next  = inbound_separator_q;
  assign km_hwif_in.KM_STATUS.outbound_separator.next = outbound_separator_q;
  assign km_hwif_in.KM_WRITE_SEPARATOR.set.next =
        (outbound_wvalid && outbound_wready) ? 1'b0 : km_hwif_out.KM_WRITE_SEPARATOR.set.value;
  assign km_hwif_in.KM_CTRL.flush.next =
        km_flush_active ? 1'b0 : km_hwif_out.KM_CTRL.flush.value;
  assign km_hwif_in.KM_IRQ_STATUS.inbound_read_data_avail.next = !inbound_empty;
  assign km_hwif_in.KM_IRQ_STATUS.outbound_write_space_avail.next = !outbound_full;

  // SEP register block hardware inputs
  assign sep_hwif_in.SEP_STATUS.inbound_empty.next = inbound_empty;
  assign sep_hwif_in.SEP_STATUS.inbound_full.next  = inbound_full;
  assign sep_hwif_in.SEP_STATUS.outbound_empty.next = outbound_empty;
  assign sep_hwif_in.SEP_STATUS.outbound_full.next  = outbound_full;
  // Zero-extend depth to 8 bits to prevent X propagation
  assign sep_hwif_in.SEP_STATUS.inbound_depth.next  = {{(8-FifoDepthW){1'b0}}, inbound_depth};
  assign sep_hwif_in.SEP_STATUS.outbound_depth.next = {{(8-FifoDepthW){1'b0}}, outbound_depth};
  assign sep_hwif_in.SEP_STATUS.inbound_separator.next  = inbound_separator_q;
  assign sep_hwif_in.SEP_STATUS.outbound_separator.next = outbound_separator_q;
  assign sep_hwif_in.SEP_WRITE_SEPARATOR.set.next =
        (inbound_wvalid && inbound_wready) ? 1'b0 : sep_hwif_out.SEP_WRITE_SEPARATOR.set.value;
  assign sep_hwif_in.SEP_CTRL.flush.next =
        sep_flush_active ? 1'b0 : sep_hwif_out.SEP_CTRL.flush.value;

  assign sep_hwif_in.SEP_IRQ_STATUS.outbound_read_data_avail.next = !outbound_empty;
  assign sep_hwif_in.SEP_IRQ_STATUS.inbound_write_space_avail.next = !inbound_full;

  // KM IRQ enable from register (controls KM's interrupt for inbound data)
  logic km_irq_enable;
  assign km_irq_enable = km_hwif_out.KM_IRQ_ENABLE.inbound_read_data_avail_en.value;

  //-------------------------------------------------------------------------
  // KM Write Channel State Machine (for FIFO writes)
  //-------------------------------------------------------------------------
  // Proper AXI-Lite: accept AW and W independently, respond with B after both

  logic km_fifo_aw_pending_q;  // AW handshake done, waiting for W
  logic km_fifo_w_pending_q;   // W handshake done, waiting for AW
  logic km_fifo_b_valid_q;     // B response pending
  logic km_fifo_b_resp_q;      // B response: 0=OKAY, 1=SLVERR

  // Handshake signals for FIFO write path
  logic km_fifo_aw_handshake, km_fifo_w_handshake;
  assign km_fifo_aw_handshake = km_axil_req_i.aw_valid && km_aw_is_write_data &&
                                  !km_fifo_aw_pending_q && !km_fifo_b_valid_q;
  assign km_fifo_w_handshake = km_axil_req_i.w_valid &&
                                 (km_fifo_aw_pending_q || km_fifo_aw_handshake) &&
                                 !km_fifo_w_pending_q && !km_fifo_b_valid_q;

  always_ff @(posedge clk_i or negedge cold_rst_ni) begin
    if (!cold_rst_ni) begin
      km_fifo_aw_pending_q <= 1'b0;
      km_fifo_w_pending_q <= 1'b0;
      km_fifo_b_valid_q <= 1'b0;
      km_fifo_b_resp_q <= 1'b0;
    end else if (!warm_rst_ni) begin
      km_fifo_aw_pending_q <= 1'b0;
      km_fifo_w_pending_q <= 1'b0;
      km_fifo_b_valid_q <= 1'b0;
      km_fifo_b_resp_q <= 1'b0;
    end else begin
      // AW handshake
      if (km_fifo_aw_handshake && !km_fifo_w_handshake) begin
        km_fifo_aw_pending_q <= 1'b1;
      end

      // W handshake - perform FIFO write and generate B response
      if (km_fifo_w_handshake) begin
        km_fifo_aw_pending_q <= 1'b0;
        km_fifo_b_valid_q <= 1'b1;
        // Use config-controlled response: OKAY if configured, SLVERR if full (default)
        km_fifo_b_resp_q <= outbound_full && !outbound_overflow_resp_okay;
      end

      // B handshake - clear response
      if (km_fifo_b_valid_q && km_axil_req_i.b_ready) begin
        km_fifo_b_valid_q <= 1'b0;
      end
    end
  end

  // FIFO write happens on W handshake when not full; [32]=separator, [31:0]=data
  assign outbound_wvalid = km_fifo_w_handshake && !outbound_full;
  assign outbound_wdata = { km_hwif_out.KM_WRITE_SEPARATOR.set.value, km_axil_req_i.w.data };

  // KM-side overflow detection signal
  logic km_outbound_overflow_detected;  // KM writes to full outbound FIFO
  assign km_outbound_overflow_detected = km_fifo_w_handshake && outbound_full;

  //-------------------------------------------------------------------------
  // KM Read Channel (for FIFO reads)
  //-------------------------------------------------------------------------
  // Proper AXI-Lite: accept AR, respond with R on next cycle

  logic        km_fifo_r_valid_q;       // R response pending
  logic        km_fifo_r_resp_q;        // R response: 0=OKAY, 1=SLVERR
  logic [31:0] km_fifo_r_data_q;        // R data captured from FIFO

  logic        km_fifo_ar_ready;        // Ready to accept AR for FIFO reads
  logic        km_fifo_ar_handshake;    // AR handshake
  logic        km_fifo_pop_handshake;   // FIFO pop handshake (rvalid && rready)

  assign km_fifo_ar_ready = km_ar_is_read_data && !km_fifo_r_valid_q;
  assign km_fifo_ar_handshake = km_axil_req_i.ar_valid && km_fifo_ar_ready;

  always_ff @(posedge clk_i or negedge cold_rst_ni) begin
    if (!cold_rst_ni) begin
      km_fifo_r_valid_q <= 1'b0;
      km_fifo_r_resp_q <= 1'b0;
      km_fifo_r_data_q <= 32'h0;
    end else if (!warm_rst_ni) begin
      km_fifo_r_valid_q <= 1'b0;
      km_fifo_r_resp_q <= 1'b0;
      km_fifo_r_data_q <= 32'h0;
    end else begin
      // AR handshake - capture FIFO data and generate R response
      if (km_fifo_ar_handshake) begin
        km_fifo_r_valid_q <= 1'b1;
        // Use config-controlled response: OKAY if configured, SLVERR if empty (default)
        km_fifo_r_resp_q <= inbound_empty && !inbound_underflow_resp_okay;
        km_fifo_r_data_q <= inbound_empty ? 32'h0 : inbound_rdata[31:0];
      end

      // R handshake - clear response
      if (km_fifo_r_valid_q && km_axil_req_i.r_ready) begin
        km_fifo_r_valid_q <= 1'b0;
      end
    end
  end

  // FIFO read (pop) happens on AR handshake when not empty
  assign inbound_rready = km_fifo_ar_handshake && !inbound_empty;
  assign km_fifo_pop_handshake = inbound_rvalid && inbound_rready;

  // Capture separator bits when receiver pops (INBOUND when KM pops, OUTBOUND when SEP pops).
  // Both stay on cold reset: they reflect FIFO content which is cold-reset-only.
  always_ff @(posedge clk_i or negedge cold_rst_ni) begin
    if (!cold_rst_ni) begin
      inbound_separator_q  <= 1'b0;
      outbound_separator_q <= 1'b0;
    end else begin
      if (km_fifo_pop_handshake) begin
        inbound_separator_q <= inbound_rdata[32];
      end
      if (sep_fifo_ar_handshake && !outbound_empty) begin
        outbound_separator_q <= outbound_rdata[32];
      end
    end
  end

  // KM-side underflow detection signal (defined after read handshake signal)
  logic km_inbound_underflow_detected;  // KM reads from empty inbound FIFO
  assign km_inbound_underflow_detected = km_fifo_ar_handshake && inbound_empty;

  // Overflow/underflow status and IRQ bits
  // STATUS sticky bits use hwset (not .next) because they have hwset=true and stickybit=true in RDL
  // But we also need to set .next to 0 to prevent X propagation
  // All four overflow/underflow bits are visible on both sides

  // KM-side STATUS register assignments
  assign km_hwif_in.KM_STATUS.inbound_overflow.hwset = sep_inbound_overflow_detected;
  assign km_hwif_in.KM_STATUS.inbound_overflow.next = 1'b0;
  assign km_hwif_in.KM_STATUS.outbound_overflow.hwset = km_outbound_overflow_detected;
  assign km_hwif_in.KM_STATUS.outbound_overflow.next = 1'b0;
  assign km_hwif_in.KM_STATUS.inbound_underflow.hwset = km_inbound_underflow_detected;
  assign km_hwif_in.KM_STATUS.inbound_underflow.next = 1'b0;
  assign km_hwif_in.KM_STATUS.outbound_underflow.hwset = sep_outbound_underflow_detected;
  assign km_hwif_in.KM_STATUS.outbound_underflow.next = 1'b0;
  assign km_hwif_in.KM_IRQ_STATUS.outbound_overflow.hwset = km_outbound_overflow_detected;
  assign km_hwif_in.KM_IRQ_STATUS.outbound_overflow.next = 1'b0;
  assign km_hwif_in.KM_IRQ_STATUS.inbound_underflow.hwset = km_inbound_underflow_detected;
  assign km_hwif_in.KM_IRQ_STATUS.inbound_underflow.next = 1'b0;
  assign km_hwif_in.KM_IRQ_STATUS.flushed_by_sep.hwset = sep_flush_active;
  assign km_hwif_in.KM_IRQ_STATUS.flushed_by_sep.next = 1'b0;

  // SEP-side STATUS register assignments
  assign sep_hwif_in.SEP_STATUS.inbound_overflow.hwset = sep_inbound_overflow_detected;
  assign sep_hwif_in.SEP_STATUS.inbound_overflow.next = 1'b0;
  assign sep_hwif_in.SEP_STATUS.outbound_overflow.hwset = km_outbound_overflow_detected;
  assign sep_hwif_in.SEP_STATUS.outbound_overflow.next = 1'b0;
  assign sep_hwif_in.SEP_STATUS.inbound_underflow.hwset = km_inbound_underflow_detected;
  assign sep_hwif_in.SEP_STATUS.inbound_underflow.next = 1'b0;
  assign sep_hwif_in.SEP_STATUS.outbound_underflow.hwset = sep_outbound_underflow_detected;
  assign sep_hwif_in.SEP_STATUS.outbound_underflow.next = 1'b0;
  assign sep_hwif_in.SEP_IRQ_STATUS.inbound_overflow.hwset = sep_inbound_overflow_detected;
  assign sep_hwif_in.SEP_IRQ_STATUS.inbound_overflow.next = 1'b0;
  assign sep_hwif_in.SEP_IRQ_STATUS.outbound_underflow.hwset = sep_outbound_underflow_detected;
  assign sep_hwif_in.SEP_IRQ_STATUS.outbound_underflow.next = 1'b0;
  assign sep_hwif_in.SEP_IRQ_STATUS.flushed_by_km.hwset = km_flush_active;
  assign sep_hwif_in.SEP_IRQ_STATUS.flushed_by_km.next = 1'b0;

  //-------------------------------------------------------------------------
  // KM Register Block Interface
  //-------------------------------------------------------------------------
  logic km_reg_awready, km_reg_awvalid;
  logic [KmRegAddrW-1:0] km_reg_awaddr;
  logic [2:0] km_reg_awprot;
  logic km_reg_wready, km_reg_wvalid;
  logic [31:0] km_reg_wdata;
  logic [3:0] km_reg_wstrb;
  logic km_reg_bready, km_reg_bvalid;
  logic [1:0] km_reg_bresp;
  logic km_reg_arready, km_reg_arvalid;
  logic [KmRegAddrW-1:0] km_reg_araddr;
  logic [2:0] km_reg_arprot;
  logic km_reg_rready, km_reg_rvalid;
  logic [31:0] km_reg_rdata;
  logic [1:0] km_reg_rresp;

  // Route to register block only for register addresses
  assign km_reg_awvalid = km_axil_req_i.aw_valid && km_aw_is_reg_block;
  assign km_reg_awaddr  = km_axil_req_i.aw.addr[KmRegAddrW-1:0];
  assign km_reg_awprot  = km_axil_req_i.aw.prot;
  assign km_reg_wvalid  = km_axil_req_i.w_valid && km_aw_is_reg_block;
  assign km_reg_wdata   = km_axil_req_i.w.data;
  assign km_reg_wstrb   = km_axil_req_i.w.strb;
  assign km_reg_bready  = km_axil_req_i.b_ready;
  assign km_reg_arvalid = km_axil_req_i.ar_valid && km_ar_is_reg_block;
  assign km_reg_araddr  = km_axil_req_i.ar.addr[KmRegAddrW-1:0];
  assign km_reg_arprot  = km_axil_req_i.ar.prot;
  assign km_reg_rready  = km_axil_req_i.r_ready;

  // Drive warm reset into the KM-port regblock via hwif_in struct field
  assign km_hwif_in.WARM_RST_N = warm_rst_ni;

  // Register block instantiation (KM-CPU-facing: cold AASD + warm CPUIF reset via hwif_in)
  km_mailbox_km_reg u_km_regs (
    .clk            (clk_i),
    .arst_n         (cold_rst_ni),
    .s_axil_awready (km_reg_awready),
    .s_axil_awvalid (km_reg_awvalid),
    .s_axil_awaddr  (km_reg_awaddr),
    .s_axil_awprot  (km_reg_awprot),
    .s_axil_wready  (km_reg_wready),
    .s_axil_wvalid  (km_reg_wvalid),
    .s_axil_wdata   (km_reg_wdata),
    .s_axil_wstrb   (km_reg_wstrb),
    .s_axil_bready  (km_reg_bready),
    .s_axil_bvalid  (km_reg_bvalid),
    .s_axil_bresp   (km_reg_bresp),
    .s_axil_arready (km_reg_arready),
    .s_axil_arvalid (km_reg_arvalid),
    .s_axil_araddr  (km_reg_araddr),
    .s_axil_arprot  (km_reg_arprot),
    .s_axil_rready  (km_reg_rready),
    .s_axil_rvalid  (km_reg_rvalid),
    .s_axil_rdata   (km_reg_rdata),
    .s_axil_rresp   (km_reg_rresp),
    .hwif_in        (km_hwif_in),
    .hwif_out       (km_hwif_out)
  );

  // Assign KM-side CTRL register bits (after register block instantiation)
  assign outbound_overflow_resp_okay = km_hwif_out.KM_CTRL.outbound_overflow_resp.value;
  assign inbound_underflow_resp_okay = km_hwif_out.KM_CTRL.inbound_underflow_resp.value;

  // Flush detection: monitor register bits
  // When either side sets CTRL.FLUSH=1, hardware clears both FIFOs and then clears the flush bit
  assign km_flush_active = km_hwif_out.KM_CTRL.flush.value;
  assign sep_flush_active = sep_hwif_out.SEP_CTRL.flush.value;

  //-------------------------------------------------------------------------
  // KM Response Muxing
  //-------------------------------------------------------------------------
  // Mux between register block and FIFO state machines

  // Write address channel
  assign km_axil_resp_o.aw_ready = km_aw_is_reg_block ? km_reg_awready :
                                     km_aw_is_write_data ? km_fifo_aw_handshake : 1'b0;

  // Write data channel
  assign km_axil_resp_o.w_ready = km_aw_is_reg_block ? km_reg_wready :
                                    km_fifo_w_handshake;

  // Write response channel
  assign km_axil_resp_o.b_valid = km_reg_bvalid || km_fifo_b_valid_q;
  assign km_axil_resp_o.b.resp = km_reg_bvalid ? km_reg_bresp :
                                   km_fifo_b_resp_q ? axi_pkg::RESP_SLVERR : axi_pkg::RESP_OKAY;

  // Read address channel
  assign km_axil_resp_o.ar_ready = km_ar_is_reg_block ? km_reg_arready :
                                     km_ar_is_read_data ? km_fifo_ar_ready : 1'b0;

  // Read data channel
  assign km_axil_resp_o.r_valid = km_reg_rvalid || km_fifo_r_valid_q;
  assign km_axil_resp_o.r.data = km_reg_rvalid ? km_reg_rdata : km_fifo_r_data_q;
  assign km_axil_resp_o.r.resp = km_reg_rvalid ? km_reg_rresp :
                                   km_fifo_r_resp_q ? axi_pkg::RESP_SLVERR : axi_pkg::RESP_OKAY;

  //=========================================================================
  // Interrupt Logic
  //=========================================================================

  // IRQ aggregation logic
  // KM-side IRQ: combines inbound_read_data_avail (level) + outbound_write_space_avail (level) +
  //              outbound overflow + inbound underflow + flushed_by_sep (sticky status bits)
  logic km_inbound_read_data_avail_irq;
  logic km_outbound_write_space_avail_irq;
  logic km_outbound_overflow_irq, km_inbound_underflow_irq, km_flushed_by_sep_irq;

  assign km_inbound_read_data_avail_irq = !inbound_empty && km_hwif_out.KM_IRQ_ENABLE.inbound_read_data_avail_en.value;
  assign km_outbound_write_space_avail_irq = !outbound_full &&
                                                km_hwif_out.KM_IRQ_ENABLE.outbound_write_space_avail_en.value;
  assign km_outbound_overflow_irq = km_hwif_out.KM_IRQ_STATUS.outbound_overflow.value &&
                                      km_hwif_out.KM_IRQ_ENABLE.outbound_overflow_en.value;
  assign km_inbound_underflow_irq = km_hwif_out.KM_IRQ_STATUS.inbound_underflow.value &&
                                      km_hwif_out.KM_IRQ_ENABLE.inbound_underflow_en.value;
  assign km_flushed_by_sep_irq = km_hwif_out.KM_IRQ_STATUS.flushed_by_sep.value &&
                                    km_hwif_out.KM_IRQ_ENABLE.flushed_by_sep_en.value;

  // SEP-side IRQ: combines outbound_read_data_avail (level) + inbound_write_space_avail (level) +
  //               inbound overflow + outbound underflow + flushed_by_km (sticky status bits)
  logic sep_outbound_read_data_avail_irq;
  logic sep_inbound_write_space_avail_irq;
  logic sep_inbound_overflow_irq, sep_outbound_underflow_irq, sep_flushed_by_km_irq;

  assign sep_outbound_read_data_avail_irq = !outbound_empty && sep_hwif_out.SEP_IRQ_ENABLE.outbound_read_data_avail_en.value;
  assign sep_inbound_write_space_avail_irq = !inbound_full &&
                                                sep_hwif_out.SEP_IRQ_ENABLE.inbound_write_space_avail_en.value;
  assign sep_inbound_overflow_irq = sep_hwif_out.SEP_IRQ_STATUS.inbound_overflow.value &&
                                      sep_hwif_out.SEP_IRQ_ENABLE.inbound_overflow_en.value;
  assign sep_outbound_underflow_irq = sep_hwif_out.SEP_IRQ_STATUS.outbound_underflow.value &&
                                        sep_hwif_out.SEP_IRQ_ENABLE.outbound_underflow_en.value;
  assign sep_flushed_by_km_irq = sep_hwif_out.SEP_IRQ_STATUS.flushed_by_km.value &&
                                   sep_hwif_out.SEP_IRQ_ENABLE.flushed_by_km_en.value;

  // Aggregated IRQ outputs (level-sensitive)
  assign mbox_irq_to_km_o = km_inbound_read_data_avail_irq | km_outbound_write_space_avail_irq |
                              km_outbound_overflow_irq |
                              km_inbound_underflow_irq | km_flushed_by_sep_irq;
  assign mbox_irq_to_sep_o = sep_outbound_read_data_avail_irq | sep_inbound_write_space_avail_irq |
                               sep_inbound_overflow_irq |
                               sep_outbound_underflow_irq | sep_flushed_by_km_irq;

  //=========================================================================
  // Assertions
  //=========================================================================

  `OCAH_ASSERT_STATIC(MAILBOX_DEPTH_GT_0, MAILBOX_DEPTH > 0)
  `OCAH_ASSERT_STATIC(MAILBOX_DEPTH_LE_256, MAILBOX_DEPTH <= 256)

  // Accepted KM FIFO AR implies an R beat the next cycle.
  `OCAH_OT_ASSERT(KmFifoReadCompletesAfterAccept_A, km_fifo_ar_handshake |=> km_fifo_r_valid_q,
                  clk_i, !cold_rst_ni || !warm_rst_ni)

endmodule : km_mailbox
