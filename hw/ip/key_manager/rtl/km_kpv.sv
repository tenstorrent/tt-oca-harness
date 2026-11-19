// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

// Store Key Manager key material in the Key and Policy Vault (KPV) behind a PeakRDL CSR
// block.
//
// Key data lives in a dedicated register file (km_kpv_regfile) with one write port (KM CPU, or the
// slot eraser while it runs) and one read port (KM only). A PeakRDL-generated CSR block exposes
// per-slot external req/ack interfaces (no internal flops for key data), which this module bridges
// to the register file through an optional 1024x32 scrambler.
//
// Per-slot CTRL registers implement:
//
// - lock_write / lock_use / seal sticky W1S bits. A slot with seal set is sealed:
//   hardware holds lock_write set alongside it, so the data is readable but not writable.
// - Erase is never blocked, but the seal changes its outcome. An unsealed slot's CTRL is
//   cleared, freeing the slot for reuse. A sealed slot is retired instead: lock_write
//   stays set and lock_use is set, so the destroyed contents cannot be read and the slot
//   cannot be refilled until warm reset.
//
// Scrambler key/ctrl lock: the stored scrambler key is held in a local flop; when locked
// the CSR returns zero to software but hardware scramblers continue using the provisioned
// value.
//
// Wipe: wipe_pulse_i zeroes key data, CTRL sticky bits (via hwclr), and scrambler
// key/ctrl. It releases a sealed or retired slot, which is sound only because no KM CPU
// execution follows a wipe before warm reset: in key_manager a wipe comes from a CPU trap,
// which halts the CPU, or from the wipe_state_i tamper input.
//
// Cold reset clears the entire KPV except key data and the scrambler key CSR, which have no
// reset; warm reset clears the KM-port CPUIF, the SLVERR tracking and every slot's CTRL
// register.

module km_kpv
  import km_intf_pkg::km_axil_req_t;
  import km_intf_pkg::km_axil_resp_t;
#(
  parameter type axil_req_t  = km_axil_req_t,  // KM-side AXI-Lite request type.
  parameter type axil_resp_t = km_axil_resp_t  // KM-side AXI-Lite response type.
) (
  input  logic clk_i,        // System clock.
  input  logic cold_rst_ni,  // Cold reset: AASD; resets the entire KPV.
  input  logic warm_rst_ni,  // Warm reset: synchronous; resets the KM-port CPUIF, the SLVERR
                             // tracking and every slot's CTRL register.

  input  axil_req_t  km_axil_req_i,        // KM port request from the crossbar (base
                                           // 0x0001_2000); only address bits [12:0] are
                                           // decoded.
  output axil_resp_t      km_axil_resp_o,  // KM port response to the crossbar; SLVERR on a
                                           // key-data write to a write-locked or sealed slot
                                           // and on a key-data read of a use-locked slot.

  input  logic        wipe_pulse_i  // Wipe: pulse high for one cycle to zero the entire KPV
                                    // on the next cycle.
);

  `include "prim_assert.sv"

  // Internal register address width, from the generated register map.
  localparam int unsigned AddrW = km_kpv_reg_pkg::KM_KPV_REG_MIN_ADDR_WIDTH;

  // Key slots in the vault, and the index width that addresses them.
  localparam int unsigned NumSlots = 64;
  localparam int unsigned SlotW = $clog2(NumSlots);
  localparam int unsigned WordsPerSlot = 16;
  localparam int unsigned WordW = $clog2(WordsPerSlot);

  // Key-data word width, spanning the eraser, scrambler and regfile.
  //
  // Distinct from the KM AXI-Lite bus width even though both are 32: a key word is what
  // one KEY_ENTRY sub-word holds, so it follows the RDL regwidth rather than the fabric.
  // The KEY_ENTRY/CTRL address slices below assume that same regwidth, so changing it
  // means regenerating the register block, not just editing this line.
  localparam int unsigned DataW = 32;

  // Regfile/scrambler address width: {slot, word}.
  localparam int unsigned RfAddrW = SlotW + WordW;

  // =========================================================================
  // KM: AXI struct -> flat (to KPV reg block)
  //==========================================================================
  logic km_reg_awready, km_reg_awvalid;
  logic [AddrW-1:0] km_reg_awaddr;
  logic [2:0] km_reg_awprot;
  logic km_reg_wready, km_reg_wvalid;
  logic [31:0] km_reg_wdata;
  logic [3:0] km_reg_wstrb;
  logic km_reg_bready, km_reg_bvalid;
  logic [1:0] km_reg_bresp;
  logic km_reg_arready, km_reg_arvalid;
  logic [AddrW-1:0] km_reg_araddr;
  logic [2:0] km_reg_arprot;
  logic km_reg_rready, km_reg_rvalid;
  logic [31:0] km_reg_rdata;
  logic [1:0] km_reg_rresp;

  assign km_reg_awvalid = km_axil_req_i.aw_valid;
  assign km_reg_awaddr  = km_axil_req_i.aw.addr[AddrW-1:0];
  assign km_reg_awprot  = km_axil_req_i.aw.prot;
  assign km_reg_wvalid  = km_axil_req_i.w_valid;
  assign km_reg_wdata   = km_axil_req_i.w.data;
  assign km_reg_wstrb   = km_axil_req_i.w.strb;
  assign km_reg_bready  = km_axil_req_i.b_ready;
  assign km_reg_arvalid = km_axil_req_i.ar_valid;
  assign km_reg_araddr  = km_axil_req_i.ar.addr[AddrW-1:0];
  assign km_reg_arprot  = km_axil_req_i.ar.prot;
  assign km_reg_rready  = km_axil_req_i.r_ready;

  //==========================================================================
  // KPV register block (KM port) -- CTRL, scrambler, and external key data
  //==========================================================================
  km_kpv_reg_pkg::km_kpv__in_t  kpv_hwif_in;
  km_kpv_reg_pkg::km_kpv__out_t kpv_hwif_out;

  // Drive warm reset into the KM-port regblock via hwif_in struct field
  assign kpv_hwif_in.WARM_RST_N = warm_rst_ni;

  km_kpv_reg u_km_kpv_reg (
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
    .hwif_in        (kpv_hwif_in),
    .hwif_out       (kpv_hwif_out)
  );

  //==========================================================================
  // Per-slot erase controller (LFSR + FSM)
  //
  // When a slot's CTRL.erase bit is set, the eraser walks the 16 words of
  // that slot, emitting a logical {slot, word} address and pseudo-random
  // data.  These are routed through the shared KPV scrambler and the regfile
  // write port (the eraser takes priority while busy).  On completion an
  // erase_done pulse either clears the slot CTRL register or, on a sealed
  // slot, retires it (see the hwif drives below).
  //==========================================================================
  logic [NumSlots-1:0]  erase_req;
  logic                 erase_wr_en;
  logic [SlotW-1:0]     erase_slot;
  logic [WordW-1:0]     erase_word;
  logic [DataW-1:0]     erase_wr_data;
  logic [NumSlots-1:0]  erase_done;
  logic                 erase_busy;

  // Per-slot seal state, which decides an erase's outcome.
  logic [NumSlots-1:0] slot_sealed;

  always_comb begin
    for (int i = 0; i < NumSlots; i++) begin
      erase_req[i]   = kpv_hwif_out.CTRL[i].erase.value;
      slot_sealed[i] = kpv_hwif_out.CTRL[i].seal.value;
    end
  end

  km_kpv_eraser #(
    .NUM_SLOTS     (NumSlots),
    .WORDS_PER_SLOT(WordsPerSlot),
    .DATA_WIDTH    (DataW)
  ) u_eraser (
    .clk_i        (clk_i),
    .cold_rst_ni  (cold_rst_ni),
    .erase_req_i  (erase_req),
    .wr_en_o      (erase_wr_en),
    .wr_slot_o    (erase_slot),
    .wr_word_o    (erase_word),
    .wr_data_o    (erase_wr_data),
    .erase_done_o (erase_done),
    .busy_o       (erase_busy)
  );

  //==========================================================================
  // KPV hwif_in: CTRL lock/retire drives, scrambler key/ctrl lock, wipe
  //==========================================================================

  // Scrambler key stored separately for HW use.
  // When locked, the CSR register is zeroed via hwif_in.next so SW reads 0;
  // scramblers use this stored copy which preserves the provisioned value.
  logic        scrambler_lock_q;
  logic [31:0] scrambler_key_stored;

  always_ff @(posedge clk_i or negedge cold_rst_ni) begin
    if (!cold_rst_ni) begin
      scrambler_lock_q     <= 1'b0;
      scrambler_key_stored <= 32'h0;
    end else if (wipe_pulse_i) begin
      scrambler_lock_q     <= 1'b0;
      scrambler_key_stored <= 32'h0;
    end else begin
      if (kpv_hwif_out.KPV_SCRAMBLER_CTRL.lock.value && !scrambler_lock_q) scrambler_lock_q <= 1'b1;
      if (!scrambler_lock_q) scrambler_key_stored <= kpv_hwif_out.KPV_SCRAMBLER_KEY.key.value;
    end
  end

  logic kpv_scrambler_enable;
  assign kpv_scrambler_enable = kpv_hwif_out.KPV_SCRAMBLER_CTRL.enable.value;

  always_comb begin
    for (int i = 0; i < NumSlots; i++) begin
      // A seal implies a write lock, so hardware holds lock_write set for
      // as long as the slot is sealed.  That also carries lock_write
      // through a retiring erase, which is what stops the slot being
      // refilled once its key has been destroyed.
      kpv_hwif_in.CTRL[i].lock_write.hwset = slot_sealed[i] & ~wipe_pulse_i;
      // Retirement: completing an erase on a sealed slot read-locks it so
      // the destroyed contents cannot be read back.
      kpv_hwif_in.CTRL[i].lock_use.hwset   = erase_done[i] & slot_sealed[i] &
                                                   ~wipe_pulse_i;
      // Erasing an unsealed slot frees it: the whole CTRL register clears.
      // A wipe frees every slot, sealed or not.
      kpv_hwif_in.CTRL[i].lock_write.hwclr = wipe_pulse_i |
                                                   (erase_done[i] & ~slot_sealed[i]);
      kpv_hwif_in.CTRL[i].lock_use.hwclr   = wipe_pulse_i |
                                                   (erase_done[i] & ~slot_sealed[i]);
      kpv_hwif_in.CTRL[i].seal.hwclr       = wipe_pulse_i;
      kpv_hwif_in.CTRL[i].erase.hwclr      = wipe_pulse_i | erase_done[i];
    end
    // Scrambler key/ctrl lock
    kpv_hwif_in.KPV_SCRAMBLER_KEY.key.swwel =
            kpv_hwif_out.KPV_SCRAMBLER_CTRL.lock.value;
    kpv_hwif_in.KPV_SCRAMBLER_CTRL.enable.swwel =
            kpv_hwif_out.KPV_SCRAMBLER_CTRL.lock.value;
    // Scrambler key: when locked, zero CSR so SW reads 0; else hold value.
    // Wipe also clears via hwclr.
    kpv_hwif_in.KPV_SCRAMBLER_KEY.key.hwclr = wipe_pulse_i;
    kpv_hwif_in.KPV_SCRAMBLER_KEY.key.next  =
            scrambler_lock_q ? 32'h0 :
            kpv_hwif_out.KPV_SCRAMBLER_KEY.key.value;
    // Scrambler ctrl: wipe clears enable and lock via hwclr
    kpv_hwif_in.KPV_SCRAMBLER_CTRL.enable.hwclr = wipe_pulse_i;
    kpv_hwif_in.KPV_SCRAMBLER_CTRL.lock.hwclr   = wipe_pulse_i;
  end

  //==========================================================================
  // KM external key data bridge
  //
  // PeakRDL generates one external interface per slot.  At most one
  // KEY_ENTRY[i].req is active per cycle.  We mux to find the active
  // slot, feed through the scrambler, access the register file, and
  // respond with ack + rd_data.
  //==========================================================================
  // Mux: find active KM external slot
  logic              km_ext_active;
  logic              km_ext_is_wr;
  logic [SlotW-1:0]  km_ext_slot;
  logic [WordW-1:0]  km_ext_word;
  logic [DataW-1:0]  km_ext_wr_data;

  always_comb begin
    km_ext_active  = 1'b0;
    km_ext_is_wr   = 1'b0;
    km_ext_slot    = '0;
    km_ext_word    = '0;
    km_ext_wr_data = '0;
    for (int i = 0; i < NumSlots; i++) begin
      if (!km_ext_active && kpv_hwif_out.KEY_ENTRY[i].req) begin
        km_ext_active  = 1'b1;
        km_ext_is_wr   = kpv_hwif_out.KEY_ENTRY[i].req_is_wr;
        km_ext_slot    = SlotW'(i);
        km_ext_word    = kpv_hwif_out.KEY_ENTRY[i].addr[WordW+1:2];
        km_ext_wr_data = kpv_hwif_out.KEY_ENTRY[i].wr_data;
      end
    end
  end

  // KM lock checks (at external req time).  A seal counts as a write lock in
  // its own right: lock_write follows a seal write through hwset a cycle
  // later, and a write arriving in that cycle must not slip through.
  logic km_ext_lock_write, km_ext_lock_use;
  assign km_ext_lock_write =
        kpv_hwif_out.CTRL[km_ext_slot].lock_write.value |
        slot_sealed[km_ext_slot];
  assign km_ext_lock_use =
        kpv_hwif_out.CTRL[km_ext_slot].lock_use.value;

  // --- KM scrambler (write path: scramble; read path: descramble) ---
  // Inputs are muxed: while the eraser is busy it borrows the scrambler to
  // produce scrambled random data.  The KM CPU does not drive a key-data
  // access through the scrambler during an erase (it only polls CTRL.erase
  // via the regblock), so there is no contention.
  logic [RfAddrW-1:0]  km_scrambler_addr;
  logic [DataW-1:0]    km_scrambler_in_data;
  logic [RfAddrW-1:0]  km_scrambler_phys_addr;
  logic [DataW-1:0]    km_scrambler_write_out;
  logic [DataW-1:0]    km_scrambler_read_out;
  logic [DataW-1:0]    rf_rd_data;

  assign km_scrambler_addr = erase_busy ? {erase_slot, erase_word}
                                          : {km_ext_slot, km_ext_word};
  assign km_scrambler_in_data = erase_busy ? erase_wr_data : km_ext_wr_data;

  scrambler_1024x32 #(
    .ADDR_WIDTH(RfAddrW),
    .DATA_WIDTH(DataW)
  ) u_scrambler_km (
    .addr_i                (km_scrambler_addr),
    // scrambler_512x32 reserves byte_mask_i for future byte-masked write support (hw/ip/scrambler/doc/architecture.adoc)
    // Tie it to 0 rather than leaving it open, as the km_sram_interface call sites do.
    .byte_mask_i           ('0),
    .scrambler_key_i       (scrambler_key_stored),
    .scrambled_addr_o      (km_scrambler_phys_addr),
    .write_data_i          (km_scrambler_in_data),
    .scrambled_write_data_o(km_scrambler_write_out),
    .scrambled_read_data_i (rf_rd_data),
    .read_data_o           (km_scrambler_read_out)
  );

  // KM external read data: handle lock_use in rd_data
  logic [DataW-1:0] km_ext_rd_data;
  assign km_ext_rd_data =
        km_ext_lock_use      ? '0 :
        kpv_scrambler_enable ? km_scrambler_read_out :
                               rf_rd_data;

  // Respond to every per-slot interface (only the active one matters)
  always_comb begin
    for (int i = 0; i < NumSlots; i++) begin
      kpv_hwif_in.KEY_ENTRY[i].rd_ack =
                kpv_hwif_out.KEY_ENTRY[i].req &
                ~kpv_hwif_out.KEY_ENTRY[i].req_is_wr;
      kpv_hwif_in.KEY_ENTRY[i].rd_data = km_ext_rd_data;
      kpv_hwif_in.KEY_ENTRY[i].wr_ack =
                kpv_hwif_out.KEY_ENTRY[i].req &
                kpv_hwif_out.KEY_ENTRY[i].req_is_wr;
    end
  end

  //==========================================================================
  // Key data register file (KM write + read)
  //==========================================================================
  logic                 rf_wr_a_en;
  logic [RfAddrW-1:0]   rf_wr_a_addr;
  logic [DataW-1:0]     rf_wr_a_data;
  logic [RfAddrW-1:0]   rf_rd_addr;

  // Write port: eraser (priority while busy) or KM external write
  // (external req, write, !lock_write).  Erase is not gated by lock_write.
  assign rf_wr_a_en = erase_busy ? erase_wr_en
                                   : (km_ext_active & km_ext_is_wr & ~km_ext_lock_write);
  assign rf_wr_a_addr = kpv_scrambler_enable ? km_scrambler_phys_addr :
        (erase_busy ? {erase_slot, erase_word} : {km_ext_slot, km_ext_word});
  assign rf_wr_a_data = kpv_scrambler_enable ? km_scrambler_write_out :
        (erase_busy ? erase_wr_data : km_ext_wr_data);

  // KM read port: physical addr when scrambled, else logical
  assign rf_rd_addr = kpv_scrambler_enable ?
        km_scrambler_phys_addr : {km_ext_slot, km_ext_word};

  // The eraser borrows the shared scrambler and regfile write port while
  // busy (it has priority), so a concurrent KM external key-data write would
  // be silently dropped even though its wr_ack still asserts.  Firmware only
  // polls CTRL.erase (a regblock read) during an erase and never issues a key
  // write while one is in flight, so this collision must never occur.
  `OCAH_OT_ASSERT_NEVER(KmNoKeyWriteDuringErase, erase_busy && km_ext_active && km_ext_is_wr,
                        clk_i, !cold_rst_ni || !warm_rst_ni)

  km_kpv_regfile #(
    .NUM_SLOTS     (NumSlots),
    .WORDS_PER_SLOT(WordsPerSlot),
    .DATA_WIDTH    (DataW)
  ) u_key_regfile (
    .clk_i           (clk_i),
    .wipe_i          (wipe_pulse_i),
    .wr_a_en_i       (rf_wr_a_en),
    .wr_a_addr_i     (rf_wr_a_addr),
    .wr_a_data_i     (rf_wr_a_data),
    .rd_addr_i       (rf_rd_addr),
    .rd_data_o       (rf_rd_data)
  );

  //==========================================================================
  // KM response override: SLVERR on violation
  //
  // Key read data is served directly by the external rd_data path
  // (lock_use is handled there).  The FIFO tracks
  // only SLVERR information.
  //==========================================================================
  logic km_is_key, km_is_ctrl;
  logic [SlotW-1:0] km_slot;
  logic km_wr_violation, km_rd_violation;
  logic [AddrW-1:0] km_addr_accept;

  assign km_addr_accept =
        km_reg_awvalid ? km_reg_awaddr : km_reg_araddr;
  assign km_is_key =
        (km_addr_accept < AddrW'(km_kpv_addrmap_pkg::KM_KPV_CTRL_BASE_ADDR(0)));
  assign km_is_ctrl =
        (km_addr_accept >= AddrW'(km_kpv_addrmap_pkg::KM_KPV_CTRL_BASE_ADDR(0))) &&
        (km_addr_accept <= AddrW'(km_kpv_addrmap_pkg::KM_KPV_CTRL_BASE_ADDR(NumSlots-1)));
  // Key entries are 0x40 apart, so the slot sits above the 6 word/byte bits;
  // CTRL registers are one word apart, so it sits directly above bit 1.
  assign km_slot =
        km_is_key ? km_addr_accept[SlotW+5:6] : km_addr_accept[SlotW+1:2];

  always_comb begin
    // Key data writes to write-locked slots are protocol violations.
    // CTRL writes are always AXI-OKAY so lock_use can still be set after
    // lock_write; other fields retain their existing field-level behavior.
    km_wr_violation = km_is_key &
            (kpv_hwif_out.CTRL[km_slot].lock_write.value | slot_sealed[km_slot]);
    km_rd_violation = km_is_key &
            kpv_hwif_out.CTRL[km_slot].lock_use.value;
  end

  // KM-port response override metadata (tracks SLVERR for lock violations).
  typedef struct packed {
    logic       is_wr;
    logic       wr_violation;
    logic       rd_violation;
  } km_resp_override_t;

  km_resp_override_t km_fifo[2];
  logic [1:0] km_fifo_wptr, km_fifo_rptr;
  logic km_fifo_push, km_fifo_pop;
  km_resp_override_t km_override;

  assign km_fifo_push =
        (km_reg_awready && km_reg_awvalid) ||
        (km_reg_arready && km_reg_arvalid);
  assign km_fifo_pop =
        (km_reg_bvalid && km_reg_bready) ||
        (km_reg_rvalid && km_reg_rready);

  always_ff @(posedge clk_i or negedge cold_rst_ni) begin
    if (!cold_rst_ni) begin
      km_fifo_wptr <= '0;
      km_fifo_rptr <= '0;
      for (int i = 0; i < 2; i++) km_fifo[i] <= '0;
    end else if (!warm_rst_ni) begin
      km_fifo_wptr <= '0;
      km_fifo_rptr <= '0;
      for (int i = 0; i < 2; i++) km_fifo[i] <= '0;
    end else begin
      if (km_fifo_push) begin
        if (km_reg_awready && km_reg_awvalid)
          km_fifo[km_fifo_wptr[0]] <= '{
              is_wr: 1'b1,
              wr_violation: km_wr_violation,
              rd_violation: 1'b0
          };
        else
          km_fifo[km_fifo_wptr[0]] <= '{
              is_wr: 1'b0,
              wr_violation: 1'b0,
              rd_violation: km_rd_violation
          };
        km_fifo_wptr <= km_fifo_wptr + 1'b1;
      end
      if (km_fifo_pop) km_fifo_rptr <= km_fifo_rptr + 1'b1;
    end
  end

  assign km_override = km_fifo[km_fifo_rptr[0]];

  // KM response output
  assign km_axil_resp_o.aw_ready = km_reg_awready;
  assign km_axil_resp_o.w_ready  = km_reg_wready;
  assign km_axil_resp_o.b_valid  = km_reg_bvalid;
  assign km_axil_resp_o.b.resp =
        (km_override.is_wr && km_override.wr_violation) ?
        2'b10 : km_reg_bresp;
  assign km_axil_resp_o.ar_ready = km_reg_arready;
  assign km_axil_resp_o.r_valid  = km_reg_rvalid;

  // Key reads: CSR returns external rd_data (already handles
  // lock_use->0).  Non-key reads: CSR returns
  // internal flop data.  No override needed.
  assign km_axil_resp_o.r.data = km_reg_rdata;

  assign km_axil_resp_o.r.resp =
        (!km_override.is_wr && km_override.rd_violation) ?
        2'b10 : km_reg_rresp;

endmodule : km_kpv

