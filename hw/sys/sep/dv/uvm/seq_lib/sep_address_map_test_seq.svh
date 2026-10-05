// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP no-CPU address-map scenario sequence, carrying the cocotb
// sep_address_map_seq and sep_address_map_test semantics on the CPU-LSU AXI4
// splice:
//   * wait for fuse sense done, since the local fabric answers only after it;
//   * sweep sep_cpu_ctrl by access class (cpu_ctrl_sweep() below): reset
//     compares (CHK-ADDRMAP), response-only reads of the hardware-driven
//     registers, two reads of the REFERENCE_COUNTER low half that must
//     advance (CHK-REFCNT-READ), write/readback/restore of the SEP base/size
//     registers (CHK-BASEADDR-RW) and of the pure read/write storage
//     registers plus CLOCK_GATE_CTRL (CHK-RW-READBACK), and a write to each
//     write-only register;
//   * walk one readable CSR per LSU-reachable block: OKAY, and the reset value
//     where the generated header exports it (CHK-FABRIC-WALK);
//   * read the interior hole of sep_cpu_ctrl, require OKAY with zero data,
//     prove SEP_SW_DEBUG writable, then require a hole write to retire OKAY
//     and leave SEP_SW_DEBUG unchanged (CHK-CPU-CTRL-HOLE);
//   * require the first word of the eFuse-shim window to answer other than
//     DECERR and the word past it to answer DECERR (CHK-EXT-DEMUX-BOUND).
// Every register the pass writes is restored to its reset value, so each pass
// leaves the block as reset left it. Expected values come from the generated
// register header hw/sys/sep/regs/gen/svh/sep_reg.svh (address, reset value,
// field masks), from the written stimulus, and from the access-class table
// below. The cocotb twin is cocotb/tests/system/sep_address_map_test.py with
// cocotb/seq_lib/sep_address_map_seq.py.

class sep_address_map_test_seq extends sep_base_test_seq;
  `uvm_object_utils(sep_address_map_test_seq)

  localparam string ChkAddrmap = "CHK-ADDRMAP";
  localparam string ChkRefcnt = "CHK-REFCNT-READ";
  localparam string ChkBaseAddrRw = "CHK-BASEADDR-RW";
  localparam string ChkRwReadback = "CHK-RW-READBACK";
  localparam string ChkHole = "CHK-CPU-CTRL-HOLE";
  localparam string ChkFabricWalk = "CHK-FABRIC-WALK";
  localparam string ChkExtDemux = "CHK-EXT-DEMUX-BOUND";

  // Software access class of one sep_cpu_ctrl sweep row.
  typedef enum {
    READ_CHECK,      // sw=r or sw=rw with a value set only by reset: compare to reset
    READ_ONLY,       // value set by hardware: response check only
    REF_COUNTER,     // free-running counter: must advance between two reads
    BASE_ADDR_RW,    // SEP base/size register: write, readback, restore, readback
    WRITE_READBACK,  // pure sw=rw storage: write, masked readback, restore, readback
    WRITE_ONLY       // sw=w: write only; a read is not part of the contract
  } access_class_e;

  typedef struct {
    string         name;
    bit [63:0]     addr;
    bit [31:0]     reset_value;
    // Storage mask: the bits of the low word that the RDL declares, so a
    // readback compares as `written & mask`.
    bit [31:0]     mask;
    access_class_e cls;
    // Directed write pattern (write classes only).
    bit [31:0]     pattern;
  } cpu_ctrl_row_t;

  typedef struct {
    string     name;
    bit [63:0] addr;
    bit        value_check;
    bit [31:0] expected;
  } fabric_row_t;

  // REFERENCE_COUNTER counts on clk_ref_i. Two bus accesses can retire inside
  // one reference period, so the second low-half read waits this many
  // reference periods after the first.
  localparam int unsigned RefCounterWaitRefPeriods = 2;

  // XOR applied to the SEP_SW_DEBUG value to make the hole-alias control
  // write differ from the value it replaces.
  localparam bit [31:0] SwDebugControlXor = 32'hA5A5_5A5A;

  // Data written to the hole: every bit set, so an alias onto any
  // SEP_SW_DEBUG bit changes it.
  localparam bit [31:0] HoleWriteData = 32'hFFFF_FFFF;

  function new(string name = "sep_address_map_test_seq");
    super.new(name);
  endfunction

  // ------------------------------------------------------------------
  // DV-owned access-class table of sep_cpu_ctrl, in sweep order. The class
  // of each row is transcribed from the field `sw` access property in
  // hw/sys/sep/regs/blocks/sep_cpu_ctrl/sep_cpu_ctrl.rdl, with the registers
  // the cocotb sep_address_map_seq sweeps:
  //   READ_CHECK     sw=rw or sw=r with a fixed reset: CLOCK_GATE_CTRL,
  //                  TIMEOUT_INTERRUPT (sw=r), PKA_CTRL, the TIMEOUT_COUNT_*
  //                  slots not written below, the SEP and SMU base/size
  //                  registers, SEP_NMI_VEC, both woset LOCK registers (never
  //                  written: a set latches until reset), EXT_TRNG_SRC_SEL and
  //                  SEP_VERSION_ID (sw=r, hw=na).
  //   READ_ONLY      sw=r, hw=w: SEP_TEST_CTRL, SEP_FUSE_SENSE_STATUS,
  //                  SMC_FUSE_SENSE_STATUS; and REFERENCE_COUNTER (hw=rw).
  //                  Hardware sets the value, so the RDL reset is not what
  //                  the DUT presents.
  //   REF_COUNTER    REFERENCE_COUNTER (rc[63:0], hw=rw, counts on clk_ref_i).
  //   BASE_ADDR_RW   SEP_GLOBAL_BASE_ADDR, SEP_LOCAL_BASE_ADDR, SEP_REGION_SIZE
  //                  (sw=rw). The SMU registers stay reset compares only.
  //   WRITE_READBACK sw=rw, hw=r storage with no side effect: SEP_SW_DEBUG,
  //                  TIMEOUT_COUNT_DMA, TIMEOUT_COUNT_SYS_IN, TIMEOUT_ENABLE.
  //   WRITE_ONLY     sw=w: TIMEOUT_CLEAR, TIMEOUT_MODE.
  // Every field of these registers declares a reset value in the RDL, so each
  // reset compare is defined on a 4-state simulator. Address, reset value and
  // field masks come from sep_reg.svh symbols. The write patterns are the
  // cocotb patterns; each masked pattern differs from the masked reset value,
  // so a readback separates a stored write from an ignored one (the
  // TIMEOUT_COUNT_DMA pattern is odd because its storage is bit 0 only).
  // ------------------------------------------------------------------
  function void cpu_ctrl_rows(ref cpu_ctrl_row_t rows[$]);
    rows.delete();
    // READ_CHECK.
    rows.push_back('{"CLOCK_GATE_CTRL", 64'(SEP_CPU_CTRL_CLOCK_GATE_CTRL_REG_ADDR),
                   32'(SEP_CPU_CTRL_CLOCK_GATE_CTRL_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_CLOCK_GATE_CTRL_PKA_CG_ENABLE_MASK), READ_CHECK, 32'h0});
    rows.push_back('{"TIMEOUT_INTERRUPT", 64'(SEP_CPU_CTRL_TIMEOUT_INTERRUPT_REG_ADDR),
                   32'(SEP_CPU_CTRL_TIMEOUT_INTERRUPT_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_TIMEOUT_INTERRUPT_RESERVED_MASK), READ_CHECK, 32'h0});
    rows.push_back('{"PKA_CTRL", 64'(SEP_CPU_CTRL_PKA_CTRL_REG_ADDR),
                   32'(SEP_CPU_CTRL_PKA_CTRL_REG_DEFAULT), SepPkaCtrlMask, READ_CHECK, 32'h0});
    rows.push_back('{"TIMEOUT_COUNT_MAILBOX_INBOUND",
                   64'(SEP_CPU_CTRL_TIMEOUT_COUNT_MAILBOX_INBOUND_REG_ADDR),
                   32'(SEP_CPU_CTRL_TIMEOUT_COUNT_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_TIMEOUT_COUNT_RESERVED_MASK), READ_CHECK, 32'h0});
    rows.push_back('{"TIMEOUT_COUNT_MAILBOX_OUTBOUND",
                   64'(SEP_CPU_CTRL_TIMEOUT_COUNT_MAILBOX_OUTBOUND_REG_ADDR),
                   32'(SEP_CPU_CTRL_TIMEOUT_COUNT_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_TIMEOUT_COUNT_RESERVED_MASK), READ_CHECK, 32'h0});
    rows.push_back('{"TIMEOUT_COUNT_ENTROPY_WRITE",
                   64'(SEP_CPU_CTRL_TIMEOUT_COUNT_ENTROPY_WRITE_REG_ADDR),
                   32'(SEP_CPU_CTRL_TIMEOUT_COUNT_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_TIMEOUT_COUNT_RESERVED_MASK), READ_CHECK, 32'h0});
    rows.push_back('{"TIMEOUT_COUNT_ENTROPY_READ",
                   64'(SEP_CPU_CTRL_TIMEOUT_COUNT_ENTROPY_READ_REG_ADDR),
                   32'(SEP_CPU_CTRL_TIMEOUT_COUNT_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_TIMEOUT_COUNT_RESERVED_MASK), READ_CHECK, 32'h0});
    rows.push_back('{"TIMEOUT_COUNT_FILTER_OUT",
                   64'(SEP_CPU_CTRL_TIMEOUT_COUNT_FILTER_OUT_REG_ADDR),
                   32'(SEP_CPU_CTRL_TIMEOUT_COUNT_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_TIMEOUT_COUNT_RESERVED_MASK), READ_CHECK, 32'h0});
    rows.push_back('{"TIMEOUT_COUNT_ALIAS_REMAP",
                   64'(SEP_CPU_CTRL_TIMEOUT_COUNT_ALIAS_REMAP_REG_ADDR),
                   32'(SEP_CPU_CTRL_TIMEOUT_COUNT_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_TIMEOUT_COUNT_RESERVED_MASK), READ_CHECK, 32'h0});
    rows.push_back('{"SEP_GLOBAL_BASE_ADDR", 64'(SEP_CPU_CTRL_SEP_GLOBAL_BASE_ADDR_REG_ADDR),
                   32'(SEP_CPU_CTRL_SEP_GLOBAL_BASE_ADDR_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_SEP_GLOBAL_BASE_ADDR_ADDR_MASK), READ_CHECK, 32'h0});
    rows.push_back('{"SEP_LOCAL_BASE_ADDR", 64'(SEP_CPU_CTRL_SEP_LOCAL_BASE_ADDR_REG_ADDR),
                   32'(SEP_CPU_CTRL_SEP_LOCAL_BASE_ADDR_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_SEP_LOCAL_BASE_ADDR_ADDR_MASK), READ_CHECK, 32'h0});
    rows.push_back('{"SEP_REGION_SIZE", 64'(SEP_CPU_CTRL_SEP_REGION_SIZE_REG_ADDR),
                   32'(SEP_CPU_CTRL_SEP_REGION_SIZE_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_SEP_REGION_SIZE_SIZE_MASK), READ_CHECK, 32'h0});
    rows.push_back('{"SMU_GLOBAL_BASE_ADDR", 64'(SEP_CPU_CTRL_SMU_GLOBAL_BASE_ADDR_REG_ADDR),
                   32'(SEP_CPU_CTRL_SMU_GLOBAL_BASE_ADDR_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_SMU_GLOBAL_BASE_ADDR_ADDR_MASK), READ_CHECK, 32'h0});
    rows.push_back('{"SMU_REGION_SIZE", 64'(SEP_CPU_CTRL_SMU_REGION_SIZE_REG_ADDR),
                   32'(SEP_CPU_CTRL_SMU_REGION_SIZE_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_SMU_REGION_SIZE_SIZE_MASK), READ_CHECK, 32'h0});
    rows.push_back('{"SEP_NMI_VEC", 64'(SEP_CPU_CTRL_SEP_NMI_VEC_REG_ADDR),
                   32'(SEP_CPU_CTRL_SEP_NMI_VEC_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_SEP_NMI_VEC_NMI_VEC_MASK | SEP_CPU_CTRL_SEP_NMI_VEC_RSVD_MASK),
                   READ_CHECK, 32'h0});
    rows.push_back('{"SEP_NMI_VEC_LOCK", 64'(SEP_CPU_CTRL_SEP_NMI_VEC_LOCK_REG_ADDR),
                   32'(SEP_CPU_CTRL_SEP_NMI_VEC_LOCK_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_SEP_NMI_VEC_LOCK_LOCK_MASK), READ_CHECK, 32'h0});
    rows.push_back('{"EXT_TRNG_SRC_SEL", 64'(SEP_CPU_CTRL_EXT_TRNG_SRC_SEL_REG_ADDR),
                   32'(SEP_CPU_CTRL_EXT_TRNG_SRC_SEL_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_EXT_TRNG_SRC_SEL_SEL_MASK), READ_CHECK, 32'h0});
    rows.push_back('{"EXT_TRNG_SRC_SEL_LOCK", 64'(SEP_CPU_CTRL_EXT_TRNG_SRC_SEL_LOCK_REG_ADDR),
                   32'(SEP_CPU_CTRL_EXT_TRNG_SRC_SEL_LOCK_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_EXT_TRNG_SRC_SEL_LOCK_LOCK_MASK), READ_CHECK, 32'h0});
    rows.push_back('{"SEP_VERSION_ID", 64'(SEP_CPU_CTRL_SEP_VERSION_ID_REG_ADDR),
                   32'(SEP_CPU_CTRL_SEP_VERSION_ID_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_SEP_VERSION_ID_VERSION_ID_MASK), READ_CHECK, 32'h0});
    // READ_ONLY.
    rows.push_back('{"REFERENCE_COUNTER", 64'(SEP_CPU_CTRL_REFERENCE_COUNTER_REG_ADDR),
                   32'(SEP_CPU_CTRL_REFERENCE_COUNTER_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_REFERENCE_COUNTER_RC_MASK), READ_ONLY, 32'h0});
    rows.push_back('{"SEP_TEST_CTRL", 64'(SEP_CPU_CTRL_SEP_TEST_CTRL_REG_ADDR),
                   32'(SEP_CPU_CTRL_SEP_TEST_CTRL_REG_DEFAULT), 32'h0, READ_ONLY, 32'h0});
    rows.push_back('{"SEP_FUSE_SENSE_STATUS", 64'(SEP_CPU_CTRL_SEP_FUSE_SENSE_STATUS_REG_ADDR),
                   32'(SEP_CPU_CTRL_SEP_FUSE_SENSE_STATUS_REG_DEFAULT), 32'h0, READ_ONLY, 32'h0});
    rows.push_back('{"SMC_FUSE_SENSE_STATUS", 64'(SEP_CPU_CTRL_SMC_FUSE_SENSE_STATUS_REG_ADDR),
                   32'(SEP_CPU_CTRL_SMC_FUSE_SENSE_STATUS_REG_DEFAULT), 32'h0, READ_ONLY, 32'h0});
    // REF_COUNTER.
    rows.push_back('{"REFERENCE_COUNTER", 64'(SEP_CPU_CTRL_REFERENCE_COUNTER_REG_ADDR),
                   32'(SEP_CPU_CTRL_REFERENCE_COUNTER_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_REFERENCE_COUNTER_RC_MASK), REF_COUNTER, 32'h0});
    // BASE_ADDR_RW.
    rows.push_back('{"SEP_GLOBAL_BASE_ADDR", 64'(SEP_CPU_CTRL_SEP_GLOBAL_BASE_ADDR_REG_ADDR),
                   32'(SEP_CPU_CTRL_SEP_GLOBAL_BASE_ADDR_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_SEP_GLOBAL_BASE_ADDR_ADDR_MASK), BASE_ADDR_RW, 32'h1234_0000});
    rows.push_back('{"SEP_LOCAL_BASE_ADDR", 64'(SEP_CPU_CTRL_SEP_LOCAL_BASE_ADDR_REG_ADDR),
                   32'(SEP_CPU_CTRL_SEP_LOCAL_BASE_ADDR_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_SEP_LOCAL_BASE_ADDR_ADDR_MASK), BASE_ADDR_RW, 32'hE000_0000});
    rows.push_back('{"SEP_REGION_SIZE", 64'(SEP_CPU_CTRL_SEP_REGION_SIZE_REG_ADDR),
                   32'(SEP_CPU_CTRL_SEP_REGION_SIZE_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_SEP_REGION_SIZE_SIZE_MASK), BASE_ADDR_RW, 32'h2000_0000});
    // WRITE_READBACK.
    rows.push_back('{"SEP_SW_DEBUG", 64'(SEP_CPU_CTRL_SEP_SW_DEBUG_REG_ADDR),
                   32'(SEP_CPU_CTRL_SEP_SW_DEBUG_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_SEP_SW_DEBUG_SEP_SW_DEBUG_MASK), WRITE_READBACK, 32'hDEAD_BEEF
                   });
    rows.push_back('{"TIMEOUT_COUNT_DMA", 64'(SEP_CPU_CTRL_TIMEOUT_COUNT_DMA_REG_ADDR),
                   32'(SEP_CPU_CTRL_TIMEOUT_COUNT_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_TIMEOUT_COUNT_RESERVED_MASK), WRITE_READBACK, 32'h0BAD_C0DF});
    rows.push_back('{"TIMEOUT_COUNT_SYS_IN", 64'(SEP_CPU_CTRL_TIMEOUT_COUNT_SYS_IN_REG_ADDR),
                   32'(SEP_CPU_CTRL_TIMEOUT_COUNT_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_TIMEOUT_COUNT_RESERVED_MASK), WRITE_READBACK, 32'hCAFE_F00D});
    rows.push_back('{"TIMEOUT_ENABLE", 64'(SEP_CPU_CTRL_TIMEOUT_ENABLE_REG_ADDR),
                   32'(SEP_CPU_CTRL_TIMEOUT_ENABLE_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_TIMEOUT_ENABLE_RESERVED_MASK), WRITE_READBACK, 32'h0000_00FF});
    // WRITE_ONLY: a zero write is inert (TIMEOUT_CLEAR is a write-1 pulse and
    // TIMEOUT_MODE has no consumer while TIMEOUT_ENABLE is at reset).
    rows.push_back('{"TIMEOUT_CLEAR", 64'(SEP_CPU_CTRL_TIMEOUT_CLEAR_REG_ADDR),
                   32'(SEP_CPU_CTRL_TIMEOUT_CLEAR_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_TIMEOUT_CLEAR_RESERVED_MASK), WRITE_ONLY, 32'h0});
    rows.push_back('{"TIMEOUT_MODE", 64'(SEP_CPU_CTRL_TIMEOUT_MODE_REG_ADDR),
                   32'(SEP_CPU_CTRL_TIMEOUT_MODE_REG_DEFAULT),
                   32'(SEP_CPU_CTRL_TIMEOUT_MODE_RESERVED_MASK), WRITE_ONLY, 32'h0});
  endfunction

  // ------------------------------------------------------------------
  // Fabric walk: one readable CSR per LSU-reachable block, every address a
  // sep_reg.svh symbol. A row value-checks only where the header exports a
  // reset value with every field reset; the others are accessibility checks
  // (OKAY), because the value is set by hardware or state, or the RDL gives
  // no reset (ABR MLDSA_NAME is sw=r with no reset in abr_reg.rdl). The block
  // list and the register chosen per block are the cocotb FABRIC_BLOCKS
  // list. Memory-backed ranges, the OTP-triggering eFuse interface registers
  // and the destructive entropy-pool pop are not read.
  // ------------------------------------------------------------------
  function void fabric_rows(ref fabric_row_t rows[$]);
    rows.delete();
    rows.push_back('{"SECURE_DMA", 64'(SECURE_DMA_REG_MAP_BASE_ADDR), 1'b0, 32'h0});
    rows.push_back('{"WDT_TIMER", 64'(WDT_TIMER_REG_MAP_BASE_ADDR), 1'b0, 32'h0});
    rows.push_back('{"SEP_SCRATCH_COLD", 64'(SEP_SCRATCH_COLD_REG_MAP_BASE_ADDR), 1'b0, 32'h0});
    rows.push_back('{"SEP_SCRATCH_WARM", 64'(SEP_SCRATCH_WARM_REG_MAP_BASE_ADDR), 1'b0, 32'h0});
    rows.push_back('{"SEP_RESET_CTRL", 64'(SEP_RESET_CTRL_SW_RESET_N_REG_ADDR), 1'b1,
                   32'(SEP_RESET_CTRL_SW_RESET_N_REG_DEFAULT)});
    rows.push_back('{"OTBN", 64'(OTBN_INTR_STATE_REG_ADDR), 1'b1, 32'(OTBN_INTR_STATE_REG_DEFAULT)
                   });
    rows.push_back('{"AES", 64'(AES_REG_MAP_BASE_ADDR), 1'b0, 32'h0});
    rows.push_back('{"HMAC", 64'(HMAC_INTR_STATE_REG_ADDR), 1'b1, 32'(HMAC_INTR_STATE_REG_DEFAULT)
                   });
    rows.push_back('{"KMAC", 64'(KMAC_INTR_STATE_REG_ADDR), 1'b1, 32'(KMAC_INTR_STATE_REG_DEFAULT)
                   });
    rows.push_back('{"DRBG_CSRNG", 64'(CSRNG_INTR_STATE_REG_ADDR), 1'b1,
                   32'(CSRNG_INTR_STATE_REG_DEFAULT)});
    rows.push_back('{"DRBG_EDN", 64'(EDN_INTR_STATE_REG_ADDR), 1'b1, 32'(EDN_INTR_STATE_REG_DEFAULT)
                   });
    rows.push_back('{"ENTROPY_SRC", 64'(ENTROPY_SOURCE_COMPONENT_ID_REG_ADDR), 1'b1,
                   32'(ENTROPY_SOURCE_COMPONENT_ID_REG_DEFAULT)});
    rows.push_back('{"ADAMS_BRIDGE", 64'(ABR_MLDSA_NAME_0__REG_ADDR), 1'b0, 32'h0});
    rows.push_back('{"ENTROPY_POOL", 64'(ENTROPY_POOL_STATUS_REG_ADDR), 1'b0, 32'h0});
    rows.push_back('{"SEP_LIFECYCLE", 64'(SEP_LIFECYCLE_CTRL_REG_MAP_BASE_ADDR), 1'b0, 32'h0});
    rows.push_back('{"KM_MAILBOX", 64'(KM_MAILBOX_SEP_SEP_STATUS_REG_ADDR), 1'b0, 32'h0});
    rows.push_back('{"SEP_EFUSE_SHADOW", 64'(SEP_EFUSE_MAP_LC_STATE_REG_ADDR), 1'b0, 32'h0});
    rows.push_back('{"AXIL_MAILBOX", 64'(AXIL_MAILBOX_OUTBOUND_MAILBOX_0_REG_MAP_BASE_ADDR), 1'b0,
                   32'h0});
    rows.push_back('{"INBOUND_FILTER", 64'(INBOUND_FILTER_CTRL_0__FILTER_CONFIG_REG_ADDR), 1'b1,
                   32'(FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT)});
    rows.push_back('{"ALIAS_REMAP", 64'(LOCAL_MASTER_ALIAS_REMAP_CTRL_0__REG_MAP_BASE_ADDR), 1'b0,
                   32'h0});
    rows.push_back('{"AP_OUTPUT_REMAP", 64'(AP_OUTPUT_REMAP_CTRL_0__REG_MAP_BASE_ADDR), 1'b0, 32'h0
                   });
    rows.push_back('{"OT_SPI_HOST", 64'(SPI_CONTROLLER_INTR_STATE_REG_ADDR), 1'b0, 32'h0});
  endfunction

  // ------------------------------------------------------------------
  // Interior hole of sep_cpu_ctrl. sep_cpu_ctrl.rdl places the 64-bit
  // SEP_FUSE_SENSE_STATUS at 0x150 and SEP_SW_DEBUG at 0x178 and declares
  // nothing between. The three words are the first word after
  // SEP_FUSE_SENSE_STATUS (0x158), the word the alias check writes (0x170),
  // and the last word before SEP_SW_DEBUG (0x174).
  // hw/sys/sep/doc/memory_map.adoc states the contract for an offset inside
  // a unit's extent that owns no register: reads return zero and writes are
  // discarded, both OKAY.
  // ------------------------------------------------------------------
  localparam int unsigned FuseSenseStatusBytes = 8;  // regwidth = 64

  function void hole_words(ref bit [63:0] words[$], output bit [63:0] write_word);
    bit [63:0] lo = 64'(SEP_CPU_CTRL_SEP_FUSE_SENSE_STATUS_REG_ADDR) + FuseSenseStatusBytes;
    bit [63:0] sw = 64'(SEP_CPU_CTRL_SEP_SW_DEBUG_REG_ADDR);
    words = '{lo, sw - 8, sw - 4};
    write_word = sw - 8;
    foreach (words[i]) begin
      if (!(words[i] >= lo && words[i] < sw))
        `uvm_fatal(get_type_name(), $sformatf(
                   "hole word 0x%0h is outside [0x%0h, 0x%0h)", words[i], lo, sw))
    end
  endfunction

  // ------------------------------------------------------------------
  // Body.
  // ------------------------------------------------------------------

  task body();
    cpu_ctrl_row_t rows[$];
    fabric_row_t   blocks[$];

    seed_scenario_rng();
    attach_evidence('{ChkCsrResp, ChkAddrmap, ChkRefcnt, ChkBaseAddrRw, ChkRwReadback, ChkHole,
                    ChkFabricWalk, ChkExtDemux});
    cpu_ctrl_rows(rows);
    fabric_rows(blocks);
    `uvm_info(get_type_name(),
              $sformatf({"SEP SV-UVM address map: %0d sep_cpu_ctrl sweep rows, %0d fabric blocks, ",
                         "interior hole, eFuse-shim bound; scenario_seed=%0d random_count=%0d"},
                          rows.size(), blocks.size(), scenario_seed, random_count), UVM_LOW)

    wait_fuse_sense_done();

    log_step("1", "sep_cpu_ctrl sweep by access class");
    cpu_ctrl_sweep(rows);

    log_step("2", "CLOCK_GATE_CTRL write path");
    clock_gate_write();

    log_step("3", "fabric walk");
    fabric_walk(blocks);

    log_step("4", "CLOCK_GATE_CTRL restore");
    clock_gate_restore();

    log_step("5", "sep_cpu_ctrl interior hole");
    cpu_ctrl_hole();

    log_step("6", "eFuse-shim decode bound");
    ext_demux_bound();

    finalize_evidence();
  endtask

  // ------------------------------------------------------------------
  // Steps.
  // ------------------------------------------------------------------

  task cpu_ctrl_sweep(cpu_ctrl_row_t rows[$]);
    bit [31:0] data;
    foreach (rows[i]) begin
      case (rows[i].cls)
        READ_CHECK:
        csr_read_check(ChkAddrmap, rows[i].addr, rows[i].reset_value, {rows[i].name, ".reset"});
        READ_ONLY: csr_read(rows[i].addr, data, {rows[i].name, ".read"});
        REF_COUNTER: reference_counter(rows[i]);
        BASE_ADDR_RW: write_readback_restore(ChkBaseAddrRw, rows[i], rows[i].pattern, "directed");
        WRITE_READBACK: begin
          write_readback_restore(ChkRwReadback, rows[i], rows[i].pattern, "directed");
          // Seeded random patterns on top of the directed one. The SEP base
          // and size registers stay directed: a random SEP_LOCAL_BASE_ADDR
          // can move the local window under the walk.
          for (int unsigned r = 0; r < random_count; r++) begin
            bit [31:0] pattern = 32'(random_pattern(32));
            // A pattern that masks to the reset value cannot separate a
            // stored write from an ignored one: flip the lowest storage bit.
            if ((pattern & rows[i].mask) == (rows[i].reset_value & rows[i].mask))
              pattern ^= rows[i].mask & -rows[i].mask;
            write_readback_restore(ChkRwReadback, rows[i], pattern, $sformatf("random%0d", r));
          end
        end
        WRITE_ONLY: csr_write(rows[i].addr, rows[i].pattern, {rows[i].name, ".write"});
        default: `uvm_fatal(get_type_name(), $sformatf("unhandled access class %s",
                                                       rows[i].cls.name()))
      endcase
    end
  endtask

  // Write a pattern, read it back through the storage mask, restore the reset
  // value, and read the reset value back, all under one check ID.
  task write_readback_restore(string check_id, cpu_ctrl_row_t row, bit [31:0] pattern, string tag);
    bit [31:0] expected = pattern & row.mask;
    if (expected == (row.reset_value & row.mask))
      `uvm_fatal(get_type_name(), $sformatf(
                 "%s %s pattern 0x%08h masks to the reset value under mask 0x%08h",
                 row.name,
                 tag,
                 pattern,
                 row.mask
                 ))
    csr_write(row.addr, pattern, {row.name, ".", tag});
    csr_read_check(check_id, row.addr, expected, {row.name, ".", tag});
    csr_write(row.addr, row.reset_value, {row.name, ".", tag, ".restore"});
    csr_read_check(check_id, row.addr, row.reset_value, {row.name, ".", tag, ".restored"});
  endtask

  // REFERENCE_COUNTER counts on clk_ref_i, which the testbench drives, so no
  // pinned value applies. The low half must advance between two reads a few
  // reference periods apart: a dead decode, a neighbour's storage, a stuck
  // value and a zero return all hold still. The low half wraps every 2**32
  // reference periods, which two reads this close cannot span. The high half
  // is read for the pair and not value-checked.
  task reference_counter(cpu_ctrl_row_t row);
    bit [31:0] first_low, high, second_low;
    csr_read(row.addr, first_low, "REFERENCE_COUNTER.lo");
    csr_read(row.addr + SepCsrBytes, high, "REFERENCE_COUNTER.hi");
    #(RefCounterWaitRefPeriods * env_cfg.ref_clk_period_ns * 1ns);
    csr_read(row.addr, second_low, "REFERENCE_COUNTER.lo_again");
    void'(m_check.expect_true(
        ChkRefcnt,
        second_low > first_low,
        $sformatf(
            {
              "REFERENCE_COUNTER lo 0x%08h -> 0x%08h (hi 0x%08h) ", "after %0d ref periods"
            },
            first_low,
            second_low,
            high,
            RefCounterWaitRefPeriods)
    ));
  endtask

  // CLOCK_GATE_CTRL: write every implemented bit and read it back. The
  // restore follows the fabric walk.
  task clock_gate_write();
    bit [31:0] mask = 32'(SEP_CPU_CTRL_CLOCK_GATE_CTRL_PKA_CG_ENABLE_MASK);
    csr_write(64'(SEP_CPU_CTRL_CLOCK_GATE_CTRL_REG_ADDR), mask, "CLOCK_GATE_CTRL.set");
    csr_read_check(ChkRwReadback, 64'(SEP_CPU_CTRL_CLOCK_GATE_CTRL_REG_ADDR), mask,
                   "CLOCK_GATE_CTRL.set");
  endtask

  task clock_gate_restore();
    bit [31:0] reset_value = 32'(SEP_CPU_CTRL_CLOCK_GATE_CTRL_REG_DEFAULT);
    csr_write(64'(SEP_CPU_CTRL_CLOCK_GATE_CTRL_REG_ADDR), reset_value, "CLOCK_GATE_CTRL.restore");
    csr_read_check(ChkRwReadback, 64'(SEP_CPU_CTRL_CLOCK_GATE_CTRL_REG_ADDR), reset_value,
                   "CLOCK_GATE_CTRL.restored");
  endtask

  task fabric_walk(fabric_row_t blocks[$]);
    bit [31:0] data;
    foreach (blocks[i]) begin
      csr_read_expect(ChkFabricWalk, blocks[i].addr, OCAH_AXI_RESP_OKAY, data, {
                      blocks[i].name, ".resp"});
      if (blocks[i].value_check)
        check_evidence(ChkFabricWalk, {blocks[i].name, ".reset"}, 64'(data),
                       64'(blocks[i].expected), $sformatf("addr=0x%0h", blocks[i].addr));
    end
  endtask

  task cpu_ctrl_hole();
    bit [63:0] words[$];
    bit [63:0] write_word;
    bit [63:0] sw_addr = 64'(SEP_CPU_CTRL_SEP_SW_DEBUG_REG_ADDR);
    bit [31:0] sw_restore, probe, sw_live, sw_after, data;

    hole_words(words, write_word);

    // Positive control for the alias check: SEP_SW_DEBUG is sw=rw, so a
    // write moves it. Without it, "unchanged after the hole write" also holds
    // when the write path is dead.
    csr_read(sw_addr, sw_restore, "SEP_SW_DEBUG.before");
    probe = sw_restore ^ SwDebugControlXor;
    csr_write(sw_addr, probe, "SEP_SW_DEBUG.control");
    csr_read(sw_addr, sw_live, "SEP_SW_DEBUG.control");
    check_evidence(ChkHole, "SEP_SW_DEBUG.control", 64'(sw_live), 64'(probe),
                   "control write must move SEP_SW_DEBUG");

    foreach (words[i]) begin
      string label = $sformatf("hole_0x%0h", words[i]);
      csr_read_expect(ChkHole, words[i], OCAH_AXI_RESP_OKAY, data, {label, ".resp"});
      check_evidence(ChkHole, {label, ".data"}, 64'(data), 64'h0, "hole reads zero");
    end

    csr_write_expect(ChkHole, write_word, HoleWriteData, OCAH_AXI_RESP_OKAY, $sformatf(
                     "hole_0x%0h.write", write_word));
    csr_read(sw_addr, sw_after, "SEP_SW_DEBUG.after_hole_write");
    check_evidence(ChkHole, "SEP_SW_DEBUG.no_alias", 64'(sw_after), 64'(probe), $sformatf(
                   "hole write 0x%0h must not change SEP_SW_DEBUG", write_word));
    csr_read_expect(ChkHole, write_word, OCAH_AXI_RESP_OKAY, data, $sformatf(
                    "hole_0x%0h.after_write", write_word));
    check_evidence(ChkHole, $sformatf("hole_0x%0h.discarded", write_word), 64'(data), 64'h0,
                   "hole write is discarded");

    csr_write(sw_addr, sw_restore, "SEP_SW_DEBUG.restore");
  endtask

  // ext_demux_decode() selects the eFuse-shim port for the shim window and
  // sends the next word out of SEP to the extension error slave. The value
  // behind the shim is adopter-owned and is not graded, only which port the
  // decode selected.
  task ext_demux_bound();
    bit [63:0]    base = 64'(SEP_EXTERNAL_EFUSE_SHIM_CTRL_REG_MAP_BASE_ADDR);
    bit [63:0]    past = base + 64'(SEP_EXTERNAL_EFUSE_SHIM_CTRL_REG_MAP_SIZE);
    bit [31:0]    data;
    ocah_axi_item at_base;

    csr_read_expect(ChkExtDemux, past, OCAH_AXI_RESP_DECERR, data, $sformatf("shim_past_0x%0h", past
                    ));
    bus_read(base, SepCsrSize, at_base, $sformatf("shim_base_0x%0h", base));
    void'(m_check.expect_true(
        ChkExtDemux,
        !at_base.timed_out && at_base.worst_resp() != OCAH_AXI_RESP_DECERR,
        $sformatf(
            "shim_base_0x%0h resp=%s timed_out=%0b: not DECERR",
            base,
            at_base.worst_resp().name(),
            at_base.timed_out)
    ));
  endtask

endclass : sep_address_map_test_seq
