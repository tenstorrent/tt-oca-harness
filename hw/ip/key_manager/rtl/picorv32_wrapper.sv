// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

// PicoRV32 wrapper that routes ROM, SRAM, and AXI-Lite peripheral traffic.
//
// Instantiates RV32EMC PicoRV32 and steers its native memory bus to
// km_rom_interface, km_sram_interface, and picorv32_axi_adapter. External IRQs
// on bits 3–5 are level-sensitive (KMCSR, mailbox, ABR shared-key). An
// execute-permission whitelist follows sram_exec_mode_i and ROM lockout;
// AXI SLVERR/DECERR pulse to KMCSR. LATCHED_MEM_RDATA enables look-ahead when
// ROM/SRAM keep rdata valid after the request drops.

module picorv32_wrapper
  import km_intf_pkg::*;
  import axi_pkg::*;
#(
  parameter type axil_req_t  = km_axil_req_t,                                    // AXI-Lite request type for peripherals
  parameter type axil_resp_t = km_axil_resp_t,                                   // AXI-Lite response type for peripherals
  parameter int unsigned ROM_ADDR_WIDTH = km_intf_pkg::KM_ROM_MEM_ADDR_WIDTH,    // ROM word-address width
  parameter int unsigned SRAM_ADDR_WIDTH = km_intf_pkg::KM_SRAM_MEM_ADDR_WIDTH,  // SRAM word-address width
  parameter bit LATCHED_MEM_RDATA = 1'b0                                         // 1 if ROM/SRAM latch rdata for look-ahead
) (
  input  logic             clk_i,                               // System clock
  input  logic             rst_ni,                              // Active-low async reset into the core
  input  logic             rst_sync_ni,                         // Active-low synchronous reset companion
  output km_rom_mem_req_t  rom_mem_req_o,                       // ROM hard-macro request
  input  km_rom_mem_rsp_t  rom_mem_rsp_i,                       // ROM hard-macro response
  output logic             rom_parity_err_o,                    // ROM parity error pulse
  output logic             rom_write_err_o,                     // ROM write-attempt pulse
  output km_sram_mem_req_t sram_mem_req_o,                      // SRAM hard-macro request
  input  km_sram_mem_rsp_t sram_mem_rsp_i,                      // SRAM hard-macro response
  output logic             sram_parity_err_o,                   // SRAM parity error pulse
  input  logic [31:0]      scrambler_key_i,                     // Scrambler key passed through to SRAM
  input  logic             scrambler_en_i,                      // Scrambler enable passed through to SRAM
  input  logic [31:0]      sram_lock_bits_i,                    // Write-lock bits from KMCSR
  output logic [31:0]      sram_write_lock_violation_region_o,  // One-hot locked-write violation to KMCSR
  input  logic             sram_exec_mode_i,                    // 0=ROM-only whitelist, 1=write-locked-SRAM whitelist
  output logic             exec_violation_o,                    // Execute-whitelist violation pulse
  output logic             rom_access_violation_o,              // ROM lockout violation pulse
  output axil_req_t        axi_mst_req_o,                       // AXI-Lite master to the crossbar
  input  axil_resp_t       axi_mst_resp_i,                      // AXI-Lite response from the crossbar
  input  logic             irq_i,                               // KMCSR aggregated interrupt (sticky sources)
  input  logic             mbox_irq_i,                          // Mailbox inbound data-available (level)
  input  logic             abr_sharedkey_irq_i,                 // ML-KEM shared-key valid (level)
  input  logic [31:0]      irq_entry_addr_i,                    // Runtime IRQ handler entry PC from KMCSR
  output logic             trap_o,                              // PicoRV32 trap indication
  output logic             axi_slverr_o,                        // AXI SLVERR pulse to KMCSR
  output logic             axi_decerr_o                         // AXI DECERR pulse to KMCSR
);

  //=========================================================================
  // Local Parameters
  //=========================================================================

  // PicoRV32 IRQ configuration: bits 0-2 latched (timer/ebreak/buserror);
  // bits 3-5 level-sensitive (KMCSR, mailbox, ABR). MASKED_IRQ masks 6-31.
  localparam logic [31:0] PICORV32_MASKED_IRQ = 32'hFFFF_FFC0;
  localparam logic [31:0] PICORV32_LATCHED_IRQ = 32'h0000_0007;

  // PicoRV32 boot address.
  localparam logic [31:0] PICORV32_PROGADDR_RESET = km_intf_pkg::ROM_BASE_ADDR;

  // Initial stack pointer (top of SRAM, word-aligned).
  localparam logic [31:0] PICORV32_STACKADDR = km_intf_pkg::SRAM_END_ADDR - 3;

  // IRQ vector geometry.
  localparam int unsigned PICORV32_IRQ_VECTOR_WIDTH = 32;
  localparam int unsigned PICORV32_KMCSR_IRQ_BIT = 3;
  localparam int unsigned PICORV32_MBOX_IRQ_BIT = 4;
  localparam int unsigned PICORV32_ABR_SHAREDKEY_IRQ_BIT = 5;

  // Local copies of address-map bounds for CPU memory routing.
  localparam logic [31:0] ROM_BASE = km_intf_pkg::ROM_BASE_ADDR;
  localparam logic [31:0] ROM_END = km_intf_pkg::ROM_END_ADDR;
  localparam logic [31:0] SRAM_BASE = km_intf_pkg::SRAM_BASE_ADDR;
  localparam logic [31:0] SRAM_END = km_intf_pkg::SRAM_END_ADDR;
  localparam logic [31:0] VROM_BASE = km_intf_pkg::VROM_BASE_ADDR;
  localparam logic [31:0] VROM_END = km_intf_pkg::VROM_END_ADDR;

  //=========================================================================
  // PicoRV32 Native Memory Interface Signals
  //=========================================================================

  // Native PicoRV32 memory interface
  logic        mem_valid;
  logic        mem_instr;
  logic        mem_ready;
  logic [31:0] mem_addr;
  logic [31:0] mem_wdata;
  logic [3:0]  mem_wstrb;
  logic [3:0]  mem_rstrb;
  logic [31:0] mem_rdata;

  // PicoRV32 look-ahead interface (for prefetching)
  // These signals are asserted one cycle before mem_valid to allow
  // pipelined memory to start fetching early
  logic        mem_la_read;
  logic        mem_la_write;
  logic [31:0] mem_la_addr;
  logic [31:0] mem_la_wdata;
  logic [3:0]  mem_la_wstrb;
  logic [3:0]  mem_la_rstrb;

  // Pico Co-Processor Interface (PCPI) for custom CRC instructions
  logic        pcpi_valid;
  logic [31:0] pcpi_insn;
  logic [31:0] pcpi_rs1;
  logic [31:0] pcpi_rs2;
  logic        pcpi_wr;
  logic [31:0] pcpi_rd;
  logic        pcpi_wait;
  logic        pcpi_ready;

  // EOI signal from PicoRV32 (active while ISR is executing)
  logic [PICORV32_IRQ_VECTOR_WIDTH-1:0] eoi_vector;

  //=========================================================================
  // External IRQs — Level Connections
  //=========================================================================
  //
  // Bits 3-5 are non-latched (level-sensitive).  PicoRV32 re-evaluates
  // the live irq level every cycle:
  //
  //   next_irq_pending = (irq_pending & LATCHED_IRQ) | irq;
  //
  // Non-latched bits reset to 0 each cycle and are re-set only while the
  // input is high.  This gives correct level-sensitive behavior:
  //   - Bit 3 (KMCSR): sustained while any sticky error bit is set + enabled
  //   - Bit 4 (Mailbox): sustained while mailbox FIFO has inbound data
  //   - Bit 5 (ABR ML-KEM shared key): sustained while IRQ_STATUS & IRQ_ENABLE

  logic [PICORV32_IRQ_VECTOR_WIDTH-1:0] irq_vector;
  always_comb begin
    irq_vector = '0;
    irq_vector[PICORV32_KMCSR_IRQ_BIT]         = irq_i;
    irq_vector[PICORV32_MBOX_IRQ_BIT]          = mbox_irq_i;
    irq_vector[PICORV32_ABR_SHAREDKEY_IRQ_BIT] = abr_sharedkey_irq_i;
  end

  // Trace outputs from PicoRV32 (unused; connected to satisfy port list and avoid TFIPC)
  logic        trace_unused_valid;
  logic [35:0] trace_unused_data;

  //=========================================================================
  // PicoRV32 Core Instance (Native Interface)
  //=========================================================================

  picorv32 #(
    .ENABLE_COUNTERS     (1'b0),  // Area optimization
    .ENABLE_COUNTERS64   (1'b0),  // Area optimization
    .ENABLE_REGS_16_31   (1'b0),  // RV32E: 16 registers only (x0-x15)
    .ENABLE_REGS_DUALPORT(1'b0),  // Single-port RF for area savings
    .LATCHED_MEM_RDATA   (LATCHED_MEM_RDATA),  // Configurable: set by integrator based on memory support
    .TWO_STAGE_SHIFT     (1'b1),  // Multi-cycle shift
    .BARREL_SHIFTER      (1'b0),  // Area optimization
    .TWO_CYCLE_COMPARE   (1'b0),  // Single-cycle compare
    .TWO_CYCLE_ALU       (1'b0),  // Single-cycle ALU
    .COMPRESSED_ISA      (1'b1),  // C extension for code density
    .CATCH_MISALIGN      (1'b1),  // Trap misaligned accesses
    .CATCH_ILLINSN       (1'b1),  // Trap illegal instructions
    .ENABLE_PCPI         (1'b1),  // External PCPI interface
    .ENABLE_MUL          (1'b1),  // M extension: multiply
    .ENABLE_FAST_MUL     (1'b0),  // Area optimization
    .ENABLE_DIV          (1'b1),  // M extension: divide
    .ENABLE_IRQ          (1'b1),  // Interrupt support
    .ENABLE_IRQ_QREGS    (1'b1),  // Use q-reg IRQ context (q0=retpc, q1=mask)
    .ENABLE_IRQ_TIMER    (1'b0),  // No internal timer
    .ENABLE_TRACE        (1'b0),  // No trace interface
    .REGS_INIT_ZERO      (1'b0),  // Disable GPR zero-init
    .MASKED_IRQ          (PICORV32_MASKED_IRQ),
    .LATCHED_IRQ         (PICORV32_LATCHED_IRQ),
    .PROGADDR_RESET      (PICORV32_PROGADDR_RESET),
    .STACKADDR           (PICORV32_STACKADDR)
  ) u_picorv32 (
    .clk                 (clk_i),
    .resetn              (rst_sync_ni),
    .trap                (trap_o),

    // Native memory interface
    .mem_valid           (mem_valid),
    .mem_instr           (mem_instr),
    .mem_ready           (mem_ready),
    .mem_addr            (mem_addr),
    .mem_wdata           (mem_wdata),
    .mem_wstrb           (mem_wstrb),
    .mem_rstrb           (mem_rstrb),
    .mem_rdata           (mem_rdata),

    // Look-ahead interface (for prefetching with pipelined memory)
    .mem_la_read         (mem_la_read),
    .mem_la_write        (mem_la_write),
    .mem_la_addr         (mem_la_addr),
    .mem_la_wdata        (mem_la_wdata),
    .mem_la_wstrb        (mem_la_wstrb),
    .mem_la_rstrb        (mem_la_rstrb),

    // PCPI interface
    .pcpi_valid          (pcpi_valid),
    .pcpi_insn           (pcpi_insn),
    .pcpi_rs1            (pcpi_rs1),
    .pcpi_rs2            (pcpi_rs2),
    .pcpi_wr             (pcpi_wr),
    .pcpi_rd             (pcpi_rd),
    .pcpi_wait           (pcpi_wait),
    .pcpi_ready          (pcpi_ready),

    // IRQ interface
    .irq                 (irq_vector),
    .irq_entry_addr_i    (irq_entry_addr_i),
    .eoi                 (eoi_vector),

    // Trace interface (unused; tie off to avoid TFIPC warning)
    .trace_valid         (trace_unused_valid),
    .trace_data          (trace_unused_data)
  );

  //=========================================================================
  // PicoRV32 PCPI CRC Accelerator
  //=========================================================================

  picorv32_pcpi_crc u_picorv32_pcpi_crc (
    .clk_i       (clk_i),
    .rst_ni      (rst_ni),
    .pcpi_valid_i(pcpi_valid),
    .pcpi_insn_i (pcpi_insn),
    .pcpi_rs1_i  (pcpi_rs1),
    .pcpi_rs2_i  (pcpi_rs2),
    .pcpi_wr_o   (pcpi_wr),
    .pcpi_rd_o   (pcpi_rd),
    .pcpi_wait_o (pcpi_wait),
    .pcpi_ready_o(pcpi_ready)
  );

  //=========================================================================
  // Address Decoding and Routing
  //=========================================================================

  // Determine if address is ROM, SRAM, virtual ROM, or peripheral
  logic is_rom_addr, is_sram_addr, is_vrom_addr, is_periph_addr;
  assign is_rom_addr   = (mem_addr >= ROM_BASE)   && (mem_addr <= ROM_END);
  assign is_sram_addr  = (mem_addr >= SRAM_BASE)  && (mem_addr <= SRAM_END);
  assign is_vrom_addr  = (mem_addr >= VROM_BASE)  && (mem_addr <= VROM_END);
  assign is_periph_addr = !is_rom_addr && !is_sram_addr && !is_vrom_addr;

  // Look-ahead address qualification
  logic is_la_rom_addr, is_la_sram_addr, is_la_vrom_addr;
  assign is_la_rom_addr  = (mem_la_addr >= ROM_BASE)  && (mem_la_addr <= ROM_END);
  assign is_la_sram_addr = (mem_la_addr >= SRAM_BASE) && (mem_la_addr <= SRAM_END);
  assign is_la_vrom_addr = (mem_la_addr >= VROM_BASE) && (mem_la_addr <= VROM_END);

  //=========================================================================
  // Execute-Permission Whitelist Check
  //=========================================================================
  // A committed instruction fetch (mem_valid && mem_instr && !wstrb) is allowed
  // only from whitelisted regions.  All other fetches pulse exec_violation_o,
  // which triggers an unrecoverable fault via KMCSR IRQ.  A fetch blocked by
  // the ROM lockout instead pulses rom_access_violation_o.
  //
  // Whitelist (controlled by SRAM_EXEC_MODE.enable from KMCSR):
  //   enable == 0 (ROM mode): ROM and VROM only.
  //   enable == 1 (SRAM mode): VROM and write-locked SRAM regions
  //                            (SRAM_LOCK.lock_bits[region] == 1), plus the ROM
  //                            until the lockout engages below.
  //
  // VROM is the testbench virtual ROM (0x1000_0000); it is always executable
  // because block-TB firmware runs .text from VROM (km_exec_from_vrom.ld).
  // VROM does not exist in production silicon, so it carries no security
  // requirement and is exempt from the ROM lockout as well.
  //
  // Region index: SRAM_LOCK_REGION_BYTES-sized regions within the SRAM.  The
  // SRAM base is naturally aligned to its own size, so the index is a plain
  // slice of the byte address, matching write_region in km_sram_interface.
  localparam int unsigned SRAM_REGION_INDEX_W = $clog2(km_intf_pkg::SRAM_NUM_LOCK_REGIONS);
  localparam int unsigned SRAM_REGION_LSB = $clog2(km_intf_pkg::SRAM_LOCK_REGION_BYTES);

  logic        committed_fetch;
  logic        exec_allowed;
  logic        sram_exec_allowed;
  logic        rom_lockout_q;
  logic [SRAM_REGION_INDEX_W-1:0] fetch_region;

  assign committed_fetch = mem_valid && mem_instr && !(|mem_wstrb);
  assign fetch_region    = mem_addr[SRAM_REGION_LSB + SRAM_REGION_INDEX_W - 1 : SRAM_REGION_LSB];
  assign sram_exec_allowed = is_sram_addr && sram_exec_mode_i && sram_lock_bits_i[fetch_region];
  assign exec_allowed      = (is_rom_addr && !rom_lockout_q)
                             || is_vrom_addr
                             || sram_exec_allowed;

  // exec_allowed above is the whitelist as documented; the ROM exclusion here
  // is what keeps the two status bits disjoint, since a ROM fetch refused by
  // the lockout is reported on rom_access_violation_o instead.
  assign exec_violation_o = committed_fetch && !exec_allowed && !is_rom_addr;

  //=========================================================================
  // ROM Lockout
  //=========================================================================
  // Writing SRAM_EXEC_MODE.enable arms the exchange; the ROM is revoked on the
  // first committed fetch from a write-locked SRAM address, which is what keeps
  // the ROM fetches after the arming store legal.  The latch is in the
  // warm-reset domain to match SRAM_EXEC_MODE.enable (resetsignal =
  // WARM_RST_N), so the lockout is cleared only by a warm or cold reset.
  always_ff @(posedge clk_i or negedge rst_sync_ni) begin
    if (!rst_sync_ni) begin
      rom_lockout_q <= 1'b0;
    end else if (committed_fetch && sram_exec_allowed) begin
      rom_lockout_q <= 1'b1;
    end
  end

  // Any ROM fetch or data read once locked out.  Writes are excluded: they are
  // already reported as rom_write_err_o by km_rom_interface.
  assign rom_access_violation_o = rom_lockout_q && mem_valid && is_rom_addr && !(|mem_wstrb);

  // Reads and fetches are refused; writes still reach the ROM interface so it
  // can raise rom_write_err_o.
  logic rom_read_blocked;
  assign rom_read_blocked = rom_lockout_q && !(|mem_wstrb);

  // ROM interface signals
  logic        rom_mem_ready;
  logic [31:0] rom_mem_rdata;
  logic        rom_write_err;

  // SRAM interface signals
  logic        sram_mem_ready;
  logic [31:0] sram_mem_rdata;

  // Virtual ROM interface signals (testbench only)
  // These signals are exposed for testbench to probe and drive directly
  // Testbench will attach to mem_* signals when is_vrom_addr is true
  logic        vrom_mem_ready;
  logic [31:0] vrom_mem_rdata;

  // Virtual ROM memory bus signals (exposed for testbench)
  // Testbench can probe these to detect virtual ROM accesses and drive responses
  logic        vrom_mem_valid;
  logic        vrom_mem_instr;
  logic [31:0] vrom_mem_addr;
  logic [31:0] vrom_mem_wdata;
  logic [3:0]  vrom_mem_wstrb;
  logic        vrom_mem_la_read;
  logic [31:0] vrom_mem_la_addr;

  // AXI adapter interface (for peripherals)
  logic        axi_adapter_mem_valid;
  logic        axi_adapter_mem_instr;
  logic        axi_adapter_mem_ready;
  logic [31:0] axi_adapter_mem_addr;
  logic [31:0] axi_adapter_mem_wdata;
  logic [3:0]  axi_adapter_mem_wstrb;
  logic [31:0] axi_adapter_mem_rdata;

  // Route memory requests based on address
  assign axi_adapter_mem_valid = mem_valid && is_periph_addr;
  assign axi_adapter_mem_instr = mem_instr;
  assign axi_adapter_mem_addr  = mem_addr;
  assign axi_adapter_mem_wdata = mem_wdata;
  assign axi_adapter_mem_wstrb = mem_wstrb;

  // Expose virtual ROM memory bus signals for testbench
  assign vrom_mem_valid = mem_valid && is_vrom_addr;
  assign vrom_mem_instr = mem_instr;
  assign vrom_mem_addr  = mem_addr;
  assign vrom_mem_wdata = mem_wdata;
  assign vrom_mem_wstrb = mem_wstrb;
  assign vrom_mem_la_read = mem_la_read && is_la_vrom_addr;
  assign vrom_mem_la_addr = mem_la_addr;

  // Combine ready signals.  A ROM access refused by the lockout completes
  // immediately: km_rom_interface derives its ready from the ROM response, so
  // suppressing the request without supplying a ready here would stall the CPU
  // forever instead of faulting.
  assign mem_ready = (is_rom_addr && (rom_mem_ready || rom_read_blocked)) ||
                       (is_sram_addr && sram_mem_ready) ||
                       (is_vrom_addr && vrom_mem_ready) ||
                       (is_periph_addr && axi_adapter_mem_ready);

  // Hold the last completed read target so the selected data source stays stable after the
  // transfer. Whether the value itself remains valid is still determined by the target memory.
  typedef enum logic [1:0] {
    MemRdataSelRom,
    MemRdataSelSram,
    MemRdataSelVrom,
    MemRdataSelPeriph
  } mem_rdata_sel_e;

  logic          current_read_complete;
  mem_rdata_sel_e mem_rdata_sel_q;
  mem_rdata_sel_e mem_rdata_sel;

  assign current_read_complete = mem_valid && (|mem_rstrb) && mem_ready;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      mem_rdata_sel_q <= MemRdataSelRom;
    end else if (current_read_complete) begin
      if (is_rom_addr) begin
        mem_rdata_sel_q <= MemRdataSelRom;
      end else if (is_sram_addr) begin
        mem_rdata_sel_q <= MemRdataSelSram;
      end else if (is_vrom_addr) begin
        mem_rdata_sel_q <= MemRdataSelVrom;
      end else begin
        mem_rdata_sel_q <= MemRdataSelPeriph;
      end
    end
  end

  always_comb begin
    if (current_read_complete) begin
      if (is_rom_addr) begin
        mem_rdata_sel = MemRdataSelRom;
      end else if (is_sram_addr) begin
        mem_rdata_sel = MemRdataSelSram;
      end else if (is_vrom_addr) begin
        mem_rdata_sel = MemRdataSelVrom;
      end else begin
        mem_rdata_sel = MemRdataSelPeriph;
      end
    end else begin
      mem_rdata_sel = mem_rdata_sel_q;
    end
  end

  // Once locked out the ROM leg reads as zero, both for the blocked access
  // itself and for any value still held in the prefetch register from before.
  logic [31:0] rom_mem_rdata_gated;
  assign rom_mem_rdata_gated = rom_lockout_q ? 32'h0 : rom_mem_rdata;

  always_comb begin
    unique case (mem_rdata_sel)
      MemRdataSelRom:    mem_rdata = rom_mem_rdata_gated;
      MemRdataSelSram:   mem_rdata = sram_mem_rdata;
      MemRdataSelVrom:   mem_rdata = vrom_mem_rdata;
      MemRdataSelPeriph: mem_rdata = axi_adapter_mem_rdata;
      default:           mem_rdata = axi_adapter_mem_rdata;
    endcase
  end

  //=========================================================================
  // ROM Interface Instance
  //=========================================================================

  km_rom_interface #(
    .ROM_ADDR_WIDTH(ROM_ADDR_WIDTH)
  ) u_rom_if (
    .clk_i          (clk_i),
    .rst_ni         (rst_ni),
    .mem_valid_i    (mem_valid && is_rom_addr && !rom_read_blocked),
    .mem_ready_o    (rom_mem_ready),
    .mem_addr_i     (mem_addr),
    .mem_wdata_i    (mem_wdata),
    .mem_wstrb_i    (mem_wstrb),
    .mem_rstrb_i    (mem_rstrb),
    .mem_rdata_o    (rom_mem_rdata),
    // Look-ahead interface for prefetching
    .mem_la_read_i  (mem_la_read && is_la_rom_addr && !rom_lockout_q),
    .mem_la_addr_i  (mem_la_addr),
    .mem_la_rstrb_i (mem_la_rstrb),
    .rom_mem_req_o  (rom_mem_req_o),
    .rom_mem_rsp_i  (rom_mem_rsp_i),
    .parity_error_o (rom_parity_err_o),
    .rom_write_err_o(rom_write_err)
  );

  // Pass through ROM write error to top level
  assign rom_write_err_o = rom_write_err;

  //=========================================================================
  // SRAM Interface Instance
  //=========================================================================

  km_sram_interface #(
    .SRAM_ADDR_WIDTH(SRAM_ADDR_WIDTH),
    .SRAM_NUM_LOCK_REGIONS(km_intf_pkg::SRAM_NUM_LOCK_REGIONS)
  ) u_sram_if (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .mem_valid_i     (mem_valid && is_sram_addr),
    .mem_ready_o     (sram_mem_ready),
    .mem_addr_i      (mem_addr),
    .mem_wdata_i     (mem_wdata),
    .mem_wstrb_i     (mem_wstrb),
    .mem_rstrb_i     (mem_rstrb),
    .mem_rdata_o     (sram_mem_rdata),
    // Look-ahead interface for prefetching (supports code execution from SRAM)
    .mem_la_read_i   (mem_la_read && is_la_sram_addr),
    .mem_la_addr_i   (mem_la_addr),
    .mem_la_rstrb_i  (mem_la_rstrb),
    .sram_mem_req_o  (sram_mem_req_o),
    .sram_mem_rsp_i  (sram_mem_rsp_i),
    .scrambler_key_i (scrambler_key_i),
    .scrambler_en_i  (scrambler_en_i),
    .sram_lock_bits_i(sram_lock_bits_i),
    .parity_error_o  (sram_parity_err_o),
    .write_lock_violation_region_o(sram_write_lock_violation_region_o)
  );

  //=========================================================================
  // Virtual ROM Interface (testbench only)
  //=========================================================================
  // Virtual ROM memory bus is exposed directly to testbench
  // Testbench will probe vrom_mem_* signals and drive vrom_mem_ready/vrom_mem_rdata
  // Tie off to safe defaults - testbench will drive these via force
  assign vrom_mem_ready = 1'b0;
  assign vrom_mem_rdata = '0;

  //=========================================================================
  // AXI Adapter for Peripherals
  //=========================================================================

  // AXI4-Lite master signals from adapter
  logic        mem_axi_awvalid;
  logic        mem_axi_awready;
  logic [31:0] mem_axi_awaddr;
  logic [2:0]  mem_axi_awprot;

  logic        mem_axi_wvalid;
  logic        mem_axi_wready;
  logic [31:0] mem_axi_wdata;
  logic [3:0]  mem_axi_wstrb;

  logic        mem_axi_bvalid;
  logic        mem_axi_bready;

  logic        mem_axi_arvalid;
  logic        mem_axi_arready;
  logic [31:0] mem_axi_araddr;
  logic [2:0]  mem_axi_arprot;

  logic        mem_axi_rvalid;
  logic        mem_axi_rready;
  logic [31:0] mem_axi_rdata;

  picorv32_axi_adapter u_axi_adapter (
    .clk                 (clk_i),
    .resetn              (rst_sync_ni),

    // Native PicoRV32 memory interface (input)
    .mem_valid           (axi_adapter_mem_valid),
    .mem_instr           (axi_adapter_mem_instr),
    .mem_ready           (axi_adapter_mem_ready),
    .mem_addr            (axi_adapter_mem_addr),
    .mem_wdata           (axi_adapter_mem_wdata),
    .mem_wstrb           (axi_adapter_mem_wstrb),
    .mem_rdata           (axi_adapter_mem_rdata),

    // AXI4-Lite master interface (output)
    .mem_axi_awvalid     (mem_axi_awvalid),
    .mem_axi_awready     (mem_axi_awready),
    .mem_axi_awaddr      (mem_axi_awaddr),
    .mem_axi_awprot      (mem_axi_awprot),

    .mem_axi_wvalid      (mem_axi_wvalid),
    .mem_axi_wready      (mem_axi_wready),
    .mem_axi_wdata       (mem_axi_wdata),
    .mem_axi_wstrb       (mem_axi_wstrb),

    .mem_axi_bvalid      (mem_axi_bvalid),
    .mem_axi_bready      (mem_axi_bready),

    .mem_axi_arvalid     (mem_axi_arvalid),
    .mem_axi_arready     (mem_axi_arready),
    .mem_axi_araddr      (mem_axi_araddr),
    .mem_axi_arprot      (mem_axi_arprot),

    .mem_axi_rvalid      (mem_axi_rvalid),
    .mem_axi_rready      (mem_axi_rready),
    .mem_axi_rdata       (mem_axi_rdata)
  );

  //=========================================================================
  // AXI4-Lite Signal Mapping: Flat -> Struct
  //=========================================================================

  // Write Address Channel
  assign axi_mst_req_o.aw.addr  = mem_axi_awaddr;
  assign axi_mst_req_o.aw.prot  = mem_axi_awprot;
  assign axi_mst_req_o.aw_valid = mem_axi_awvalid;
  assign mem_axi_awready        = axi_mst_resp_i.aw_ready;

  // Write Data Channel
  assign axi_mst_req_o.w.data   = mem_axi_wdata;
  assign axi_mst_req_o.w.strb   = mem_axi_wstrb;
  assign axi_mst_req_o.w_valid  = mem_axi_wvalid;
  assign mem_axi_wready         = axi_mst_resp_i.w_ready;

  // Write Response Channel
  assign mem_axi_bvalid         = axi_mst_resp_i.b_valid;
  assign axi_mst_req_o.b_ready  = mem_axi_bready;

  // Read Address Channel
  assign axi_mst_req_o.ar.addr  = mem_axi_araddr;
  assign axi_mst_req_o.ar.prot  = mem_axi_arprot;
  assign axi_mst_req_o.ar_valid = mem_axi_arvalid;
  assign mem_axi_arready        = axi_mst_resp_i.ar_ready;

  // Read Data Channel
  assign mem_axi_rvalid         = axi_mst_resp_i.r_valid;
  assign mem_axi_rdata          = axi_mst_resp_i.r.data;
  assign axi_mst_req_o.r_ready  = mem_axi_rready;

  //=========================================================================
  // AXI Bus Error Detection
  //=========================================================================
  // Monitor AXI response codes from CPU master interface and detect errors
  // Generate pulse signals when SLVERR or DECERR responses are received

  // Write response error detection
  // Detect errors on the B channel handshake (b_valid && b_ready)
  logic write_b_handshake;
  logic [1:0] write_b_resp_q;
  logic write_slverr, write_decerr;

  assign write_b_handshake = axi_mst_resp_i.b_valid && axi_mst_req_o.b_ready;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      write_b_resp_q <= 2'b00;
    end else if (write_b_handshake) begin
      write_b_resp_q <= axi_mst_resp_i.b.resp;
    end
  end

  assign write_slverr = write_b_handshake && (axi_mst_resp_i.b.resp == axi_pkg::RESP_SLVERR);
  assign write_decerr = write_b_handshake && (axi_mst_resp_i.b.resp == axi_pkg::RESP_DECERR);

  // Read response error detection
  // Detect errors on the R channel handshake (r_valid && r_ready)
  logic read_r_handshake;
  logic [1:0] read_r_resp_q;
  logic read_slverr, read_decerr;

  assign read_r_handshake = axi_mst_resp_i.r_valid && axi_mst_req_o.r_ready;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      read_r_resp_q <= 2'b00;
    end else if (read_r_handshake) begin
      read_r_resp_q <= axi_mst_resp_i.r.resp;
    end
  end

  assign read_slverr = read_r_handshake && (axi_mst_resp_i.r.resp == axi_pkg::RESP_SLVERR);
  assign read_decerr = read_r_handshake && (axi_mst_resp_i.r.resp == axi_pkg::RESP_DECERR);

  // Combine write and read errors into pulse signals
  assign axi_slverr_o = write_slverr || read_slverr;
  assign axi_decerr_o = write_decerr || read_decerr;

endmodule : picorv32_wrapper

