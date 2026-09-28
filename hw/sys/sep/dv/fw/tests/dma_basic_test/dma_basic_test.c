// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP Secure-DMA basic-breadth firmware test (OSS rep DMA basic breadth). reference provenance:
// uvm_tests/dma sep_dma_uvm_reg_rw / reg_reset / cfg_regwen / range_regwen /
// addr_fixed / addr_wrap / addr_combo / mem_copy(width sweep) / err_opcode.
//
// EL2 firmware drives the Secure DMA (sep_dma.h, base 0x1080_0000) over the CPU
// LSU and proves the DMA CSR + copy-datapath basic contracts on bare sep. The
// transfers are SRAM->SRAM (DMA master -> SEP local xbar -> SRAM). Distinct from
// the DMA trio (dma_hash SHA-256 + SRAM->DCCM + IRQ; dma_cpu_contention
// mid-flight BUSY + dual-master; spi_ot_dma_rx lsio handshake): DMA basic breadth adds the
// CSR/REGWEN breadth + address-mode/width matrix + one opcode-error.
//
// main() returns the error count; start.S turns 0 -> PASS magic / non-zero ->
// FAIL magic on the 0x8000_0000 mailbox. Every checker logs a positive PASS line
// so the kept log is auditable (absence of FAIL is not evidence).
//
// Checks:
//   CHK-RESET      : DMA config registers read their documented reset values.
//   CHK-CFG-REGWEN : CFG_REGWEN auto-locks (0x9) while BUSY -> a config write is
//                    rejected; unlocks (0x6) when idle -> the write then lands.
//   CHK-RANGE-REGWEN: RANGE_VALID=0 gates a transfer (RANGE_VALID_ERROR); then a
//                    full valid range is locked via RANGE_REGWEN rw0c (0x9) and a
//                    range-register write is rejected (one-way until reset).
//   CHK-COPY-MODE  : SRAM->SRAM data integrity per address mode with a per-mode
//                    expected image + untouched-neighbor: INCR linear, FIXED-src
//                    replicates, FIXED-dst overwrites one location, WRAP (chunk <
//                    total) accumulates num_chunks copies.
//   CHK-WIDTH      : copy integrity for 1B/2B/4B transfer widths.
//   CHK-DONE-RW1C  : STATUS.done observed -> W1C -> reads back 0 (polled status).
//   CHK-ERR-OPCODE : invalid opcode 0xF -> ERROR_CODE.opcode_error + STATUS.error;
//                    W1C clear; a subsequent good copy recovers.
//   CHK-ERR-ADDR   : four misaligned descriptors raise the matching ERROR_CODE
//                    bit exclusively; a subsequent good copy recovers.
//   CHK-ERR-ASID   : an unencoded ASID on src and on dst each raise asid_error
//                    exclusively; a subsequent good copy recovers.
//   CHK-ERR-SIZE   : an unencoded transfer width raises size_error exclusively;
//                    a subsequent good copy recovers.
//   CHK-ICCM       : SRAM->ICCM->SRAM round trip through the DMA returns every
//                    word over a sentinel pre-fill (every other copy here stays
//                    in SRAM; the CPU cannot access ICCM as data).
//   CHK-HOSTINTG   : a DMA-issued host command under dma_host_intg_inject_i
//                    raises exclusive host_path_err; CLEAR returns STATUS 0;
//                    a subsequent good copy recovers.
//   CHK-HOSTFABRIC : a DMA transfer whose destination is past the DMA CSR
//                    window completes a fabric non-OKAY and raises exclusive
//                    host_path_err with the inject pin low; CLEAR; recovery.

#include <stdint.h>

#include "sep_outbound_filter.h"
#include "sep_mailbox.h"
#include "sep_dma.h"

#define SRAM_BASE OCH_SEP_TOP_SEP_SRAM_BASE_ADDR
#define SRAM_SIZE OCH_SEP_TOP_SEP_SRAM_SIZE
#define DMA_PARAM_MAGIC 0xDA0A11C0u
#define ASID_OT_BOTH \
    SEP_DMA_ASID_PAIR(SECURE_DMA__ADDR_SPACE_ID__SRC_ASID_reset, \
                      SECURE_DMA__ADDR_SPACE_ID__SRC_ASID_reset)
#define DONE_OR_ERR (SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__ERROR_bm)
#define STATUS_RW1C \
    (SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__ERROR_bm | SECURE_DMA__STATUS__CHUNK_DONE_bm)
// Bounded so a transfer that never completes fails its checker (returns a STATUS
// with neither DONE nor ERROR) instead of wedging the whole run on one poll. A
// real 256 B copy completes in well under this many CSR-read iterations.
#define POLL_ITERS 4000
#define MAX_COPY_WORDS 8u
// Bound between ARM and GO: inject must be high on the host a_valid
// (tlul_cmd_intg_chk.err_o is gated on a_valid).
#define HOSTINTG_ARM_SPIN 4000u

// Scenario block. Layout: [0]=magic, [1]=src_off, [2]=dst_off, [3]=copy_bytes
// (16 or 32, 4-byte aligned), [4]=fill seed. The cocotb test patches this from
// the run seed; committed defaults keep a standalone directed image.
volatile uint32_t g_dma_params[5] = {
    DMA_PARAM_MAGIC, 0x0u, 0x800u, 0x10u, 0x1234567u,
};

static uint32_t src_base;
static uint32_t dst_base;
static uint32_t copy_bytes;
static uint32_t fill_seed;

static inline uint32_t rd(uint32_t a) {
    return *(volatile uint32_t *)a;
}
static inline void wr(uint32_t a, uint32_t v) {
    *(volatile uint32_t *)a = v;
}

// Program + start one transfer (caller has set the locked full range), poll until
// DONE or ERROR (robust against BUSY-assert latency), and return final STATUS.
static uint32_t dma_run_asid(uint32_t src, uint32_t dst, uint32_t total, uint32_t chunk,
                             uint32_t width, uint32_t src_cfg, uint32_t dst_cfg, uint32_t opcode,
                             uint32_t asid) {
    wr(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR, src);
    wr(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_HI_BASE_ADDR, 0);
    wr(OCH_SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR, dst);
    wr(OCH_SEP_TOP_SECURE_DMA_DST_ADDR_HI_BASE_ADDR, 0);
    wr(OCH_SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR, asid);
    wr(OCH_SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR, width);
    wr(OCH_SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, total);
    wr(OCH_SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR, chunk);
    wr(OCH_SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR, src_cfg);
    wr(OCH_SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR, dst_cfg);
    wr(OCH_SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR, SECURE_DMA__CONTROL__GO_bm |
                                                     SECURE_DMA__CONTROL__INITIAL_TRANSFER_bm |
                                                     (opcode << SECURE_DMA__CONTROL__OPCODE_bp));

    uint32_t st = 0;
    int t = POLL_ITERS;
    do {
        st = rd(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
    } while (!(st & DONE_OR_ERR) && --t > 0);
    return st;
}

// The ASID every transfer uses unless it is the ASID itself under test.
static uint32_t dma_run(uint32_t src, uint32_t dst, uint32_t total, uint32_t chunk, uint32_t width,
                        uint32_t src_cfg, uint32_t dst_cfg, uint32_t opcode) {
    return dma_run_asid(src, dst, total, chunk, width, src_cfg, dst_cfg, opcode, ASID_OT_BOTH);
}

// Multi-chunk transfer (chunk < total). In pure memory-to-memory mode the Secure
// DMA completes ONE chunk per GO (it raises CHUNK_DONE and drops BUSY, with no
// LSIO handshake wired for SRAM on bare sep), so firmware paces the chunks: clear
// CHUNK_DONE and re-GO with INITIAL_TRANSFER=0 until the final chunk raises DONE.
// Returns the final STATUS (DONE on success, ERROR, or the last poll on timeout).
static uint32_t dma_run_chunked(uint32_t src, uint32_t dst, uint32_t total, uint32_t chunk,
                                uint32_t width, uint32_t src_cfg, uint32_t dst_cfg,
                                uint32_t opcode) {
    wr(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR, src);
    wr(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_HI_BASE_ADDR, 0);
    wr(OCH_SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR, dst);
    wr(OCH_SEP_TOP_SECURE_DMA_DST_ADDR_HI_BASE_ADDR, 0);
    wr(OCH_SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR, ASID_OT_BOTH);
    wr(OCH_SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR, width);
    wr(OCH_SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, total);
    wr(OCH_SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR, chunk);
    wr(OCH_SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR, src_cfg);
    wr(OCH_SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR, dst_cfg);

    uint32_t st = 0;
    uint32_t initial = SECURE_DMA__CONTROL__INITIAL_TRANSFER_bm;
    for (uint32_t guard = 0; guard < 64; guard++) { // bounded chunk count
        wr(OCH_SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR,
           SECURE_DMA__CONTROL__GO_bm | initial | (opcode << SECURE_DMA__CONTROL__OPCODE_bp));
        int t = POLL_ITERS;
        do {
            st = rd(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
        } while (!(st & (DONE_OR_ERR | SECURE_DMA__STATUS__CHUNK_DONE_bm)) && --t > 0);
        if (st & (SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__ERROR_bm)) {
            return st; // whole transfer finished (or errored)
        }
        if (!(st & SECURE_DMA__STATUS__CHUNK_DONE_bm)) {
            return st; // timed out with no progress
        }
        wr(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR,
           SECURE_DMA__STATUS__CHUNK_DONE_bm); // arm the next chunk
        initial = 0;
    }
    return st;
}

static void fill_src_words(uint32_t n, uint32_t *snap) {
    volatile uint32_t *s = (volatile uint32_t *)src_base;
    uint32_t lfsr = fill_seed;
    for (uint32_t i = 0; i < n; i++) {
        lfsr = lfsr * 1664525u + 1013904223u;
        s[i] = lfsr;
        if (snap != 0) {
            snap[i] = lfsr;
        }
    }
}

// Clear ``n`` destination words to a sentinel so untouched-neighbor checks are real.
static void clear_dst_words(uint32_t n, uint32_t sentinel) {
    volatile uint32_t *d = (volatile uint32_t *)dst_base;
    for (uint32_t i = 0; i < n; i++) {
        d[i] = sentinel;
    }
}

// ---- CHK-RESET: read the documented reset values (call FIRST, before any write) ----

// One field's generated RDL reset, placed at its generated bit position.
#define DMA_FRST(reg, fld) \
    ((uint32_t)SECURE_DMA__##reg##__##fld##_reset << SECURE_DMA__##reg##__##fld##_bp)

// Whole-register reset of the multi-field registers: the OR of every field's
// generated reset (secure_dma.h), so a changed RDL field reset moves the
// expectation with it.
#define DMA_CONTROL_RESET \
    (DMA_FRST(CONTROL, OPCODE) | DMA_FRST(CONTROL, HARDWARE_HANDSHAKE_ENABLE) | \
     DMA_FRST(CONTROL, DIGEST_SWAP) | DMA_FRST(CONTROL, INITIAL_TRANSFER) | \
     DMA_FRST(CONTROL, ABORT) | DMA_FRST(CONTROL, GO))
#define DMA_SRC_CONFIG_RESET (DMA_FRST(SRC_CONFIG, INCREMENT) | DMA_FRST(SRC_CONFIG, WRAP))
#define DMA_DST_CONFIG_RESET (DMA_FRST(DST_CONFIG, INCREMENT) | DMA_FRST(DST_CONFIG, WRAP))
#define DMA_STATUS_RESET \
    (DMA_FRST(STATUS, BUSY) | DMA_FRST(STATUS, DONE) | DMA_FRST(STATUS, ABORTED) | \
     DMA_FRST(STATUS, ERROR) | DMA_FRST(STATUS, SHA2_DIGEST_VALID) | DMA_FRST(STATUS, CHUNK_DONE))
#define DMA_ERROR_CODE_RESET \
    (DMA_FRST(ERROR_CODE, SRC_ADDR_ERROR) | DMA_FRST(ERROR_CODE, DST_ADDR_ERROR) | \
     DMA_FRST(ERROR_CODE, OPCODE_ERROR) | DMA_FRST(ERROR_CODE, SIZE_ERROR) | \
     DMA_FRST(ERROR_CODE, BUS_ERROR) | DMA_FRST(ERROR_CODE, BASE_LIMIT_ERROR) | \
     DMA_FRST(ERROR_CODE, RANGE_VALID_ERROR) | DMA_FRST(ERROR_CODE, ASID_ERROR))

static int chk_reset(void) {
    int e = 0;
    struct {
        const char *name;
        uint32_t addr;
        uint32_t exp;
    } regs[] = {
        // Single-field registers use the generated field reset. Multi-field
        // CONTROL / SRC_CONFIG / DST_CONFIG / STATUS / ERROR_CODE have only
        // per-field resets, so the whole-register expectation is their OR
        // (DMA_*_RESET above).
        {"TRANSFER_WIDTH", OCH_SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR,
         SECURE_DMA__TRANSFER_WIDTH__TRANSACTION_WIDTH_reset},
        {"CONTROL", OCH_SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR, DMA_CONTROL_RESET},
        {"SRC_CONFIG", OCH_SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR, DMA_SRC_CONFIG_RESET},
        {"DST_CONFIG", OCH_SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR, DMA_DST_CONFIG_RESET},
        {"CFG_REGWEN", OCH_SEP_TOP_SECURE_DMA_CFG_REGWEN_BASE_ADDR, SEP_DMA_REGWEN_UNLOCKED},
        {"RANGE_REGWEN", OCH_SEP_TOP_SECURE_DMA_RANGE_REGWEN_BASE_ADDR, SEP_DMA_REGWEN_UNLOCKED},
        {"RANGE_VALID", OCH_SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR,
         SECURE_DMA__RANGE_VALID__RANGE_VALID_reset},
        {"STATUS", OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, DMA_STATUS_RESET},
        {"ERROR_CODE", OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR, DMA_ERROR_CODE_RESET},
        {"SRC_ADDR_LO", OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR,
         SECURE_DMA__SRC_ADDR_LO__SRC_ADDR_LO_reset},
        {"DST_ADDR_LO", OCH_SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR,
         SECURE_DMA__DST_ADDR_LO__DST_ADDR_LO_reset},
        {"TOTAL_DATA_SIZE", OCH_SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR,
         SECURE_DMA__TOTAL_DATA_SIZE__DATA_SIZE_reset},
        {"CHUNK_DATA_SIZE", OCH_SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR,
         SECURE_DMA__CHUNK_DATA_SIZE__DATA_SIZE_reset},
    };
    for (unsigned i = 0; i < sizeof(regs) / sizeof(regs[0]); i++) {
        uint32_t got = rd(regs[i].addr);
        if (got != regs[i].exp) {
            sep_mbx_puts("FAIL: CHK-RESET ");
            sep_mbx_puts(regs[i].name);
            sep_mbx_puts(" got ");
            sep_mbx_puthex(got);
            sep_mbx_putc('\n');
            e++;
        }
    }
    if (!e) {
        sep_mbx_puts("CHK-RESET PASS: DMA config registers at documented reset values\n");
    }
    return e;
}

// ---- CHK-CFG-REGWEN: HW auto-lock while BUSY rejects a config write ----
static int chk_cfg_regwen(void) {
    int e = 0;
    // A 256 B copy (64 beats) stays BUSY long enough for the CPU to observe the
    // lock on its very next CSR read, without bloating sim time.
    const uint32_t len = 0x100u;
    fill_src_words(len / 4, 0);
    wr(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR, src_base);
    wr(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_HI_BASE_ADDR, 0);
    wr(OCH_SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR, dst_base);
    wr(OCH_SEP_TOP_SECURE_DMA_DST_ADDR_HI_BASE_ADDR, 0);
    wr(OCH_SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR, ASID_OT_BOTH);
    wr(OCH_SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR, SEP_DMA_WIDTH_4B);
    wr(OCH_SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, len);
    wr(OCH_SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR, len);
    wr(OCH_SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR, SECURE_DMA__SRC_CONFIG__INCREMENT_bm);
    wr(OCH_SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR, SECURE_DMA__DST_CONFIG__INCREMENT_bm);
    wr(OCH_SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR,
       SECURE_DMA__CONTROL__GO_bm | SECURE_DMA__CONTROL__INITIAL_TRANSFER_bm | SEP_DMA_OPCODE_COPY);

    // Sample BUSY + CFG_REGWEN immediately; the copy must still be running.
    uint32_t st = rd(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
    uint32_t regwen_busy = rd(OCH_SEP_TOP_SECURE_DMA_CFG_REGWEN_BASE_ADDR);
    if (!(st & SECURE_DMA__STATUS__BUSY_bm)) {
        sep_mbx_puts("FAIL: CHK-CFG-REGWEN copy finished too fast to observe BUSY\n");
        return e + 1;
    }
    if (regwen_busy != SEP_DMA_REGWEN_LOCKED) {
        sep_mbx_puts("FAIL: CHK-CFG-REGWEN not locked while BUSY, got ");
        sep_mbx_puthex(regwen_busy);
        sep_mbx_putc('\n');
        e++;
    }
    // A config write while locked must be rejected (SRC_ADDR_LO holds src_base).
    wr(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR, 0xDEADBEEFu);
    uint32_t after = rd(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR);
    if (after != src_base) {
        sep_mbx_puts("FAIL: CHK-CFG-REGWEN config write not rejected while locked, got ");
        sep_mbx_puthex(after);
        sep_mbx_putc('\n');
        e++;
    }
    // Drain the copy.
    int t = POLL_ITERS;
    do {
        st = rd(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
    } while (!(st & DONE_OR_ERR) && --t > 0);
    wr(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, STATUS_RW1C);

    uint32_t regwen_idle = rd(OCH_SEP_TOP_SECURE_DMA_CFG_REGWEN_BASE_ADDR);
    if (regwen_idle != SEP_DMA_REGWEN_UNLOCKED) {
        sep_mbx_puts("FAIL: CHK-CFG-REGWEN not unlocked when idle, got ");
        sep_mbx_puthex(regwen_idle);
        sep_mbx_putc('\n');
        e++;
    }
    // The same config write now lands.
    wr(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR, 0xDEADBEEFu);
    if (rd(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR) != 0xDEADBEEFu) {
        sep_mbx_puts("FAIL: CHK-CFG-REGWEN config write rejected while idle\n");
        e++;
    }
    if (!e) {
        sep_mbx_puts("CHK-CFG-REGWEN PASS: locked 0x9 while BUSY (write rejected), "
                     "unlocked 0x6 when idle (write lands)\n");
    }
    return e;
}

// ---- CHK-RANGE-REGWEN: range gating + rw0c lock (one-way until reset) ----
static int chk_range_regwen(void) {
    int e = 0;
    // (a) Range gating: RANGE_VALID still 0 (reset) -> a transfer errors.
    uint32_t st = dma_run(src_base, dst_base, 0x10u, 0x10u, SEP_DMA_WIDTH_4B,
                          SECURE_DMA__SRC_CONFIG__INCREMENT_bm,
                          SECURE_DMA__DST_CONFIG__INCREMENT_bm, SEP_DMA_OPCODE_COPY);
    uint32_t err = rd(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    if (!(st & SECURE_DMA__STATUS__ERROR_bm) ||
        !(err & SECURE_DMA__ERROR_CODE__RANGE_VALID_ERROR_bm)) {
        sep_mbx_puts("FAIL: CHK-RANGE-REGWEN RANGE_VALID=0 did not gate (status ");
        sep_mbx_puthex(st);
        sep_mbx_puts(" err ");
        sep_mbx_puthex(err);
        sep_mbx_puts(")\n");
        e++;
    }
    wr(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, STATUS_RW1C); // clear the error

    // (a2) An inverted range: limit below base raises base_limit_error. This has
    // to run here, while the range registers are still writable -- RANGE_REGWEN
    // below is rw0c and one-way until reset, so after it latches, a write to
    // BASE or LIMIT is rejected and the range stays whatever was locked in.
    wr(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR, 0x00002000u);
    wr(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR, 0x00001000u);
    wr(OCH_SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR, 0x1u);
    st = dma_run(src_base, dst_base, 0x10u, 0x10u, SEP_DMA_WIDTH_4B,
                 SECURE_DMA__SRC_CONFIG__INCREMENT_bm, SECURE_DMA__DST_CONFIG__INCREMENT_bm,
                 SEP_DMA_OPCODE_COPY);
    err = rd(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    // EXCLUSIVE compare: an ERROR_CODE that raises base_limit_error together with
    // an address or width bit means the block mis-classified the fault, and a
    // subset test would call that a pass.
    if (!(st & SECURE_DMA__STATUS__ERROR_bm) ||
        err != SECURE_DMA__ERROR_CODE__BASE_LIMIT_ERROR_bm) {
        sep_mbx_puts("FAIL: CHK-RANGE-REGWEN limit below base did not raise "
                     "base_limit_error alone (status ");
        sep_mbx_puthex(st);
        sep_mbx_puts(" err ");
        sep_mbx_puthex(err);
        sep_mbx_puts(")\n");
        e++;
    }
    if (st & SECURE_DMA__STATUS__DONE_bm) {
        sep_mbx_puts("FAIL: CHK-RANGE-REGWEN inverted range set STATUS.done\n");
        e++;
    }
    wr(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, STATUS_RW1C);

    // (b) Program a full valid range, then lock it via RANGE_REGWEN rw0c.
    // Positive control first: write a NON-reset value and prove it lands. Otherwise the
    // post-lock "still reads the old value" check below is satisfied identically by a
    // working REGWEN, a read-only register, and a missing decode.
    wr(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR, 0x00001000u);
    if (rd(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR) != 0x00001000u) {
        sep_mbx_puts("FAIL: CHK-RANGE-REGWEN RANGE_BASE not writable before lock\n");
        return e + 1;
    }
    wr(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR, 0x0u);
    wr(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR, 0xFFFFFFFFu);
    wr(OCH_SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR, 0x1u);
    wr(OCH_SEP_TOP_SECURE_DMA_RANGE_REGWEN_BASE_ADDR, SEP_DMA_REGWEN_LOCKED);
    if (rd(OCH_SEP_TOP_SECURE_DMA_RANGE_REGWEN_BASE_ADDR) != SEP_DMA_REGWEN_LOCKED) {
        sep_mbx_puts("FAIL: CHK-RANGE-REGWEN did not latch locked\n");
        e++;
    }
    // (c) A range-register write must now be rejected (one-way until reset).
    wr(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR, 0xCAFE0000u);
    if (rd(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR) != 0x0u) {
        sep_mbx_puts("FAIL: CHK-RANGE-REGWEN range write not rejected after lock\n");
        e++;
    }
    if (!e) {
        sep_mbx_puts("CHK-RANGE-REGWEN PASS: RANGE_VALID=0 gated (range_valid_error), "
                     "limit-below-base raised base_limit_error exclusively with no "
                     "STATUS.done, full range locked rw0c (range write rejected)\n");
    }
    return e;
}

// Verify ``n`` destination words match ``expect[i]`` and ``DST[n]`` is the sentinel.
static int check_words(const uint32_t *expect, uint32_t n, uint32_t sentinel, const char *tag) {
    volatile uint32_t *d = (volatile uint32_t *)dst_base;
    for (uint32_t i = 0; i < n; i++) {
        if (d[i] != expect[i]) {
            sep_mbx_puts("FAIL: ");
            sep_mbx_puts(tag);
            sep_mbx_puts(" word ");
            sep_mbx_puthex(i);
            sep_mbx_puts(" got ");
            sep_mbx_puthex(d[i]);
            sep_mbx_puts(" exp ");
            sep_mbx_puthex(expect[i]);
            sep_mbx_putc('\n');
            return 1;
        }
    }
    if (d[n] != sentinel) {
        sep_mbx_puts("FAIL: ");
        sep_mbx_puts(tag);
        sep_mbx_puts(" neighbor word clobbered ");
        sep_mbx_puthex(d[n]);
        sep_mbx_putc('\n');
        return 1;
    }
    return 0;
}

// Run one address-mode copy and verify its expected image + neighbor. Always logs
// the STATUS + ERROR_CODE on a no-clean-DONE failure (no silent short-circuit), so
// the kept log names which mode failed and why.
static int run_mode(const char *tag, uint32_t total, uint32_t chunk, uint32_t src_cfg,
                    uint32_t dst_cfg, const uint32_t *exp, uint32_t nexp, uint32_t sentinel) {
    clear_dst_words(nexp + 1, sentinel);
    uint32_t st = (chunk < total)
                      ? dma_run_chunked(src_base, dst_base, total, chunk, SEP_DMA_WIDTH_4B, src_cfg,
                                        dst_cfg, SEP_DMA_OPCODE_COPY)
                      : dma_run(src_base, dst_base, total, chunk, SEP_DMA_WIDTH_4B, src_cfg,
                                dst_cfg, SEP_DMA_OPCODE_COPY);
    int bad = 0;
    if (!(st & SECURE_DMA__STATUS__DONE_bm) || (st & SECURE_DMA__STATUS__ERROR_bm)) {
        sep_mbx_puts("FAIL: ");
        sep_mbx_puts(tag);
        sep_mbx_puts(" no clean DONE, status ");
        sep_mbx_puthex(st);
        sep_mbx_puts(" err ");
        sep_mbx_puthex(rd(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR));
        sep_mbx_putc('\n');
        bad = 1;
    } else if (check_words(exp, nexp, sentinel, tag)) {
        bad = 1;
    }
    wr(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, STATUS_RW1C);
    return bad;
}

// ---- CHK-COPY-MODE: per address-mode expected image + neighbor ----
static int chk_copy_mode(void) {
    int e = 0;
    const uint32_t SENT = 0xA5A5A5A5u;
    uint32_t snap[MAX_COPY_WORDS];
    uint32_t exp[MAX_COPY_WORDS];
    const uint32_t nwords = copy_bytes / 4u;
    const uint32_t half = nwords / 2u;

    fill_src_words(nwords, snap); // independent expected image, not re-read from SRAM

    // (1) INCR/INCR linear copy: dst[i] = src[i].
    for (uint32_t i = 0; i < nwords; i++) {
        exp[i] = snap[i];
    }
    e +=
        run_mode("CHK-COPY-MODE INCR", copy_bytes, copy_bytes, SECURE_DMA__SRC_CONFIG__INCREMENT_bm,
                 SECURE_DMA__DST_CONFIG__INCREMENT_bm, exp, nwords, SENT);

    // (2) FIXED src (re-read in place) + INCR dst: dst[i] = src[0] (replicate).
    for (uint32_t i = 0; i < nwords; i++) {
        exp[i] = snap[0];
    }
    e +=
        run_mode("CHK-COPY-MODE FIXED-src", copy_bytes, copy_bytes, SECURE_DMA__SRC_CONFIG__WRAP_bm,
                 SECURE_DMA__DST_CONFIG__INCREMENT_bm, exp, nwords, SENT);

    // (3) INCR src + FIXED dst (overwrite in place): dst[0] = src[last], dst[1] untouched.
    exp[0] = snap[nwords - 1u];
    e += run_mode("CHK-COPY-MODE FIXED-dst", copy_bytes, copy_bytes,
                  SECURE_DMA__SRC_CONFIG__INCREMENT_bm, SECURE_DMA__DST_CONFIG__WRAP_bm, exp, 1,
                  SENT);

    // (4) WRAP src (chunk < total) + INCR dst: two chunks of half words; the source
    // wraps to its start each chunk, so dst = first half twice.
    for (uint32_t i = 0; i < half; i++) {
        exp[i] = snap[i];
        exp[half + i] = snap[i];
    }
    e += run_mode("CHK-COPY-MODE WRAP-src", copy_bytes, copy_bytes / 2u,
                  (SECURE_DMA__SRC_CONFIG__INCREMENT_bm | SECURE_DMA__SRC_CONFIG__WRAP_bm),
                  SECURE_DMA__DST_CONFIG__INCREMENT_bm, exp, nwords, SENT);

    if (!e) {
        sep_mbx_puts("CHK-COPY-MODE PASS: INCR linear / FIXED-src replicate / "
                     "FIXED-dst overwrite / WRAP chunk-accumulate, neighbors intact\n");
    }
    return e;
}

// ---- CHK-WIDTH: INCR copy integrity at 1B / 2B / 4B ----
static int chk_width(void) {
    int e = 0;
    const uint32_t SENT = 0x5A5A5A5Au;
    const uint32_t bytes = copy_bytes;
    volatile uint8_t *sb = (volatile uint8_t *)src_base;
    volatile uint8_t *db = (volatile uint8_t *)dst_base;
    uint32_t widths[3] = {SEP_DMA_WIDTH_1B, SEP_DMA_WIDTH_2B, SEP_DMA_WIDTH_4B};

    fill_src_words(bytes / 4, 0);
    for (int w = 0; w < 3; w++) {
        clear_dst_words(bytes / 4 + 1, SENT);
        uint32_t st = dma_run(src_base, dst_base, bytes, bytes, widths[w],
                              SECURE_DMA__SRC_CONFIG__INCREMENT_bm,
                              SECURE_DMA__DST_CONFIG__INCREMENT_bm, SEP_DMA_OPCODE_COPY);
        // Read the width back. Without this the three iterations are indistinguishable:
        // 16 bytes is a whole multiple of 1, 2 and 4, so a TRANSFER_WIDTH that ignored
        // writes and stayed at its 0x2 reset produced a byte-identical copy all three
        // times and the check could not tell 1B from 4B.
        uint32_t wr_rb = rd(OCH_SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR) &
                         SECURE_DMA__TRANSFER_WIDTH__TRANSACTION_WIDTH_bm;
        if (wr_rb != widths[w]) {
            sep_mbx_puts("FAIL: CHK-WIDTH TRANSFER_WIDTH readback ");
            sep_mbx_puthex(wr_rb);
            sep_mbx_puts(" != written ");
            sep_mbx_puthex(widths[w]);
            sep_mbx_putc('\n');
            e++;
        }
        int bad = (!(st & SECURE_DMA__STATUS__DONE_bm) || (st & SECURE_DMA__STATUS__ERROR_bm));
        for (uint32_t i = 0; i < bytes && !bad; i++) {
            if (db[i] != sb[i]) bad = 1;
        }
        if (bad) {
            sep_mbx_puts("FAIL: CHK-WIDTH width-enc ");
            sep_mbx_puthex(widths[w]);
            sep_mbx_puts(" copy mismatch (status ");
            sep_mbx_puthex(st);
            sep_mbx_puts(")\n");
            e++;
        }
        wr(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, STATUS_RW1C);
    }
    if (!e) {
        sep_mbx_puts("CHK-WIDTH PASS: TRANSFER_WIDTH 1B/2B/4B each read back as written, copies "
                     "byte-exact\n");
    }
    return e;
}

// ---- CHK-DONE-RW1C: STATUS.done observed -> W1C -> reads back 0 ----
static int chk_done_rw1c(void) {
    int e = 0;
    const uint32_t SENT = 0x33333333u;
    const uint32_t nwords = copy_bytes / 4u;
    fill_src_words(nwords, 0);
    clear_dst_words(nwords + 1, SENT);
    uint32_t st = dma_run(src_base, dst_base, copy_bytes, copy_bytes, SEP_DMA_WIDTH_4B,
                          SECURE_DMA__SRC_CONFIG__INCREMENT_bm,
                          SECURE_DMA__DST_CONFIG__INCREMENT_bm, SEP_DMA_OPCODE_COPY);
    if (!(st & SECURE_DMA__STATUS__DONE_bm)) {
        sep_mbx_puts("FAIL: CHK-DONE-RW1C STATUS.done not observed\n");
        return e + 1;
    }
    wr(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, SECURE_DMA__STATUS__DONE_bm); // W1C
    uint32_t after = rd(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
    if (after & SECURE_DMA__STATUS__DONE_bm) {
        sep_mbx_puts("FAIL: CHK-DONE-RW1C STATUS.done did not clear, got ");
        sep_mbx_puthex(after);
        sep_mbx_putc('\n');
        e++;
    }
    if (!e) {
        sep_mbx_puts("CHK-DONE-RW1C PASS: STATUS.done set then W1C-cleared to 0\n");
    }
    return e;
}

// ---- CHK-ERR-ADDR: the engine's address validation ----
// Four cells: a transfer whose source or destination address does not meet the
// alignment its width requires, at both the 4-byte and the 2-byte width. Each
// cell asserts its error EXCLUSIVELY, so a fault that raises a different bit is
// a failure rather than a pass, and a clean transfer after the four proves the
// engine recovers. The inverted-range leg (limit below base) is NOT here: it
// must run before chk_range_regwen closes the one-way RANGE_REGWEN lock, so it
// lives in that function.
static int chk_err_addr(void) {
    int e = 0;
    struct {
        const char *name;
        uint32_t src, dst, width, want;
    } cells[] = {
        // The RDL describes SRC_ADDR_LO / DST_ADDR_LO as "Must be aligned to the
        // transfer width", so a 4-byte transfer demands addr[1:0] == 0 on each
        // side and the misaligned side is the one that raises its error bit.
        {"src misaligned for 4B", src_base + 1u, dst_base, SEP_DMA_WIDTH_4B,
         SECURE_DMA__ERROR_CODE__SRC_ADDR_ERROR_bm},
        {"dst misaligned for 4B", src_base, dst_base + 2u, SEP_DMA_WIDTH_4B,
         SECURE_DMA__ERROR_CODE__DST_ADDR_ERROR_bm},
        // 2-byte width demands bit 0 clear on both.
        {"src misaligned for 2B", src_base + 1u, dst_base, SEP_DMA_WIDTH_2B,
         SECURE_DMA__ERROR_CODE__SRC_ADDR_ERROR_bm},
        {"dst misaligned for 2B", src_base, dst_base + 1u, SEP_DMA_WIDTH_2B,
         SECURE_DMA__ERROR_CODE__DST_ADDR_ERROR_bm},
    };
    const uint32_t ncells = (uint32_t)(sizeof(cells) / sizeof(cells[0]));
    const uint32_t nwords = copy_bytes / 4u;

    for (uint32_t c = 0; c < ncells; c++) {
        uint32_t st = dma_run(cells[c].src, cells[c].dst, copy_bytes, copy_bytes, cells[c].width,
                              SECURE_DMA__SRC_CONFIG__INCREMENT_bm,
                              SECURE_DMA__DST_CONFIG__INCREMENT_bm, SEP_DMA_OPCODE_COPY);
        uint32_t err = rd(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
        if (!(st & SECURE_DMA__STATUS__ERROR_bm) || err != cells[c].want) {
            sep_mbx_puts("FAIL: CHK-ERR-ADDR ");
            sep_mbx_puts(cells[c].name);
            sep_mbx_puts(" expected err ");
            sep_mbx_puthex(cells[c].want);
            sep_mbx_puts(" got ");
            sep_mbx_puthex(err);
            sep_mbx_puts(" status ");
            sep_mbx_puthex(st);
            sep_mbx_putc('\n');
            e++;
        }
        if (st & SECURE_DMA__STATUS__DONE_bm) {
            sep_mbx_puts("FAIL: CHK-ERR-ADDR ");
            sep_mbx_puts(cells[c].name);
            sep_mbx_puts(" set STATUS.done on a refused transfer\n");
            e++;
        }
        wr(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, STATUS_RW1C);
    }

    // Prove the engine still copies after the refusals. The range registers are
    // locked by now, so they are left alone; the inverted-range leg lives in
    // CHK-RANGE-REGWEN, which runs while they are still writable.
    uint32_t snap[MAX_COPY_WORDS];
    fill_src_words(nwords, snap);
    clear_dst_words(nwords + 1, 0xA5A5A5A5u);
    uint32_t st = dma_run(src_base, dst_base, copy_bytes, copy_bytes, SEP_DMA_WIDTH_4B,
                          SECURE_DMA__SRC_CONFIG__INCREMENT_bm,
                          SECURE_DMA__DST_CONFIG__INCREMENT_bm, SEP_DMA_OPCODE_COPY);
    uint32_t err = rd(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    if (!(st & SECURE_DMA__STATUS__DONE_bm) || (st & SECURE_DMA__STATUS__ERROR_bm) || err != 0) {
        sep_mbx_puts("FAIL: CHK-ERR-ADDR recovery copy did not succeed\n");
        e++;
    } else {
        volatile uint32_t *d = (volatile uint32_t *)dst_base;
        for (uint32_t i = 0; i < nwords; i++) {
            if (d[i] != snap[i]) {
                sep_mbx_puts("FAIL: CHK-ERR-ADDR recovery copy mismatch at word ");
                sep_mbx_puthex(i);
                sep_mbx_putc('\n');
                e++;
                break;
            }
        }
    }
    if (!e) {
        sep_mbx_puts("CHK-ERR-ADDR PASS: 4 misaligned descriptors, covering the "
                     "source and destination alignment checks at both 4-byte and "
                     "2-byte width, each raised exactly the expected ERROR_CODE bit "
                     "and no other, none set STATUS.done, and the engine copied "
                     "correctly afterwards\n");
    }
    return e;
}

// ---- CHK-ERR-OPCODE: invalid opcode -> opcode_error -> clear -> recovery ----
static int chk_err_opcode(void) {
    int e = 0;
    const uint32_t SENT = 0xC3C3C3C3u;
    const uint32_t nwords = copy_bytes / 4u;
    uint32_t snap[MAX_COPY_WORDS];
    fill_src_words(nwords, snap);
    uint32_t st = dma_run(src_base, dst_base, copy_bytes, copy_bytes, SEP_DMA_WIDTH_4B,
                          SECURE_DMA__SRC_CONFIG__INCREMENT_bm,
                          SECURE_DMA__DST_CONFIG__INCREMENT_bm, SEP_DMA_OPCODE_INVALID);
    uint32_t err = rd(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    // Exclusive: ONLY opcode_error must be set (no other ERROR_CODE bit), matching
    // the reference suite err_opcode error-exclusivity check.
    if (!(st & SECURE_DMA__STATUS__ERROR_bm) || err != SECURE_DMA__ERROR_CODE__OPCODE_ERROR_bm) {
        sep_mbx_puts("FAIL: CHK-ERR-OPCODE invalid opcode did not set opcode_error "
                     "exclusively (status ");
        sep_mbx_puthex(st);
        sep_mbx_puts(" err ");
        sep_mbx_puthex(err);
        sep_mbx_puts(")\n");
        e++;
    }
    if (st & SECURE_DMA__STATUS__DONE_bm) {
        sep_mbx_puts("FAIL: CHK-ERR-OPCODE STATUS.done set on an errored transfer\n");
        e++;
    }
    wr(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, STATUS_RW1C); // clear error

    // Recovery: a subsequent good COPY succeeds with no error.
    clear_dst_words(nwords + 1, SENT);
    st = dma_run(src_base, dst_base, copy_bytes, copy_bytes, SEP_DMA_WIDTH_4B,
                 SECURE_DMA__SRC_CONFIG__INCREMENT_bm, SECURE_DMA__DST_CONFIG__INCREMENT_bm,
                 SEP_DMA_OPCODE_COPY);
    err = rd(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    if (!(st & SECURE_DMA__STATUS__DONE_bm) || (st & SECURE_DMA__STATUS__ERROR_bm) || err != 0) {
        sep_mbx_puts("FAIL: CHK-ERR-OPCODE recovery copy did not succeed (status ");
        sep_mbx_puthex(st);
        sep_mbx_puts(" err ");
        sep_mbx_puthex(err);
        sep_mbx_puts(")\n");
        e++;
    } else {
        volatile uint32_t *d = (volatile uint32_t *)dst_base;
        for (uint32_t i = 0; i < nwords; i++) {
            if (d[i] != snap[i]) {
                sep_mbx_puts("FAIL: CHK-ERR-OPCODE recovery copy word ");
                sep_mbx_puthex(i);
                sep_mbx_puts(" got ");
                sep_mbx_puthex(d[i]);
                sep_mbx_puts(" exp ");
                sep_mbx_puthex(snap[i]);
                sep_mbx_putc('\n');
                e++;
            }
        }
    }
    wr(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, STATUS_RW1C);
    if (!e) {
        sep_mbx_puts("CHK-ERR-OPCODE PASS: opcode 0xF -> opcode_error EXCLUSIVE + "
                     "STATUS.error, W1C clear, recovery copy matches source\n");
    }
    return e;
}

// ---- CHK-HOSTINTG: DMA-issued command + inject -> exclusive host_path_err ----
static int chk_host_intg(void) {
    int e = 0;
    const uint32_t SENT = 0x5A5A5A5Au;
    const uint32_t nwords = copy_bytes / 4u;
    uint32_t snap[MAX_COPY_WORDS];
    const uint32_t host_bit = SEP_CPU_CTRL__DMA_BUS_ERR_STATUS__HOST_PATH_ERR_bm;
    const uint32_t status_addr = OCH_SEP_TOP_SEP_CPU_CTRL_DMA_BUS_ERR_STATUS_BASE_ADDR;
    const uint32_t clear_addr = OCH_SEP_TOP_SEP_CPU_CTRL_DMA_BUS_ERR_CLEAR_BASE_ADDR;

    uint32_t bus = rd(status_addr);
    if (bus != 0) {
        sep_mbx_puts("FAIL: CHK-HOSTINTG DMA_BUS_ERR_STATUS=0x");
        sep_mbx_puthex(bus);
        sep_mbx_puts(" at baseline, expected 0\n");
        return 1;
    }

    fill_src_words(nwords, snap);
    clear_dst_words(nwords + 1, SENT);

    // Inject must be high before GO. err_o is a_valid-gated.
    sep_mbx_puts("CHK-HOSTINTG-ARM\n");
    for (volatile uint32_t i = 0; i < HOSTINTG_ARM_SPIN; i++) {
    }

    // The engine must actually terminate. err_o is a_valid-gated, so a DMA that
    // issues one command and then wedges still latches host_path_err: without
    // this the liveness half of the leg goes unchecked.
    uint32_t st_intg = dma_run(src_base, dst_base, copy_bytes, copy_bytes, SEP_DMA_WIDTH_4B,
                               SECURE_DMA__SRC_CONFIG__INCREMENT_bm,
                               SECURE_DMA__DST_CONFIG__INCREMENT_bm, SEP_DMA_OPCODE_COPY);
    if (!(st_intg & DONE_OR_ERR)) {
        sep_mbx_puts("FAIL: CHK-HOSTINTG DMA neither completed nor errored, STATUS=0x");
        sep_mbx_puthex(st_intg);
        sep_mbx_putc('\n');
        e++;
    }
    bus = rd(status_addr);
    if (bus != host_bit) {
        sep_mbx_puts("FAIL: CHK-HOSTINTG DMA_BUS_ERR_STATUS=0x");
        sep_mbx_puthex(bus);
        sep_mbx_puts(" after the injected command, expected exclusive host_path_err\n");
        e++;
    }

    sep_mbx_puts("CHK-HOSTINTG-RELEASE\n");
    for (volatile uint32_t i = 0; i < HOSTINTG_ARM_SPIN; i++) {
    }

    // DMA_BUS_ERR_CLEAR is sw=w singlepulse and always reads 0, so reading it
    // back proves nothing the DUT could fail. STATUS returning to 0 is the
    // contract.
    wr(clear_addr, SEP_CPU_CTRL__DMA_BUS_ERR_CLEAR__CLR_bm);
    bus = rd(status_addr);
    if (bus != 0) {
        sep_mbx_puts("FAIL: CHK-HOSTINTG after CLEAR STATUS=0x");
        sep_mbx_puthex(bus);
        sep_mbx_puts(", expected 0\n");
        e++;
    }
    wr(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, STATUS_RW1C);

    clear_dst_words(nwords + 1, SENT);
    uint32_t st = dma_run(src_base, dst_base, copy_bytes, copy_bytes, SEP_DMA_WIDTH_4B,
                          SECURE_DMA__SRC_CONFIG__INCREMENT_bm,
                          SECURE_DMA__DST_CONFIG__INCREMENT_bm, SEP_DMA_OPCODE_COPY);
    uint32_t err = rd(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    if (!(st & SECURE_DMA__STATUS__DONE_bm) || (st & SECURE_DMA__STATUS__ERROR_bm) || err != 0) {
        sep_mbx_puts("FAIL: CHK-HOSTINTG recovery copy did not succeed (status ");
        sep_mbx_puthex(st);
        sep_mbx_puts(" err ");
        sep_mbx_puthex(err);
        sep_mbx_puts(")\n");
        e++;
    } else {
        volatile uint32_t *d = (volatile uint32_t *)dst_base;
        for (uint32_t i = 0; i < nwords; i++) {
            if (d[i] != snap[i]) {
                sep_mbx_puts("FAIL: CHK-HOSTINTG recovery copy word ");
                sep_mbx_puthex(i);
                sep_mbx_puts(" got ");
                sep_mbx_puthex(d[i]);
                sep_mbx_puts(" exp ");
                sep_mbx_puthex(snap[i]);
                sep_mbx_putc('\n');
                e++;
            }
        }
    }
    wr(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, STATUS_RW1C);
    if (!e) {
        sep_mbx_puts("CHK-HOSTINTG PASS: exclusive host_path_err after injected "
                     "command integrity; CLEAR; recovery copy matches source\n");
    }
    return e;
}

// ---- CHK-HOSTFABRIC: DMA dest past the CSR window -> exclusive host_path_err ----
static int chk_host_fabric(void) {
    int e = 0;
    const uint32_t SENT = 0x3C3C3C3Cu;
    const uint32_t nwords = copy_bytes / 4u;
    uint32_t snap[MAX_COPY_WORDS];
    const uint32_t host_bit = SEP_CPU_CTRL__DMA_BUS_ERR_STATUS__HOST_PATH_ERR_bm;
    const uint32_t status_addr = OCH_SEP_TOP_SEP_CPU_CTRL_DMA_BUS_ERR_STATUS_BASE_ADDR;
    const uint32_t clear_addr = OCH_SEP_TOP_SEP_CPU_CTRL_DMA_BUS_ERR_CLEAR_BASE_ADDR;
    // First word past the DMA CSR xbar window. RANGE is locked 0..0xFFFFFFFF,
    // so the engine issues the command; the xbar returns DECERR.
    const uint32_t dead = OCH_SEP_TOP_SECURE_DMA_BASE_ADDR + OCH_SEP_TOP_SECURE_DMA_SIZE;

    uint32_t bus = rd(status_addr);
    if (bus != 0) {
        sep_mbx_puts("FAIL: CHK-HOSTFABRIC DMA_BUS_ERR_STATUS=0x");
        sep_mbx_puthex(bus);
        sep_mbx_puts(" at baseline, expected 0\n");
        return 1;
    }

    fill_src_words(nwords, snap);
    sep_mbx_puts("CHK-HOSTFABRIC-ARM\n");
    // As above: the transfer must terminate, or a wedged engine passes on a
    // latch the fabric raised from its first beat.
    uint32_t st_fab = dma_run(src_base, dead, copy_bytes, copy_bytes, SEP_DMA_WIDTH_4B,
                              SECURE_DMA__SRC_CONFIG__INCREMENT_bm,
                              SECURE_DMA__DST_CONFIG__INCREMENT_bm, SEP_DMA_OPCODE_COPY);
    if (!(st_fab & DONE_OR_ERR)) {
        sep_mbx_puts("FAIL: CHK-HOSTFABRIC DMA neither completed nor errored, STATUS=0x");
        sep_mbx_puthex(st_fab);
        sep_mbx_putc('\n');
        e++;
    }
    bus = rd(status_addr);
    if (bus != host_bit) {
        sep_mbx_puts("FAIL: CHK-HOSTFABRIC DMA_BUS_ERR_STATUS=0x");
        sep_mbx_puthex(bus);
        sep_mbx_puts(" after dest 0x");
        sep_mbx_puthex(dead);
        sep_mbx_puts(", expected exclusive host_path_err\n");
        e++;
    }

    // DMA_BUS_ERR_CLEAR is sw=w singlepulse and always reads 0, so reading it
    // back proves nothing the DUT could fail. STATUS returning to 0 is the
    // contract.
    wr(clear_addr, SEP_CPU_CTRL__DMA_BUS_ERR_CLEAR__CLR_bm);
    bus = rd(status_addr);
    if (bus != 0) {
        sep_mbx_puts("FAIL: CHK-HOSTFABRIC after CLEAR STATUS=0x");
        sep_mbx_puthex(bus);
        sep_mbx_puts(", expected 0\n");
        e++;
    }
    wr(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, STATUS_RW1C);

    clear_dst_words(nwords + 1, SENT);
    uint32_t st = dma_run(src_base, dst_base, copy_bytes, copy_bytes, SEP_DMA_WIDTH_4B,
                          SECURE_DMA__SRC_CONFIG__INCREMENT_bm,
                          SECURE_DMA__DST_CONFIG__INCREMENT_bm, SEP_DMA_OPCODE_COPY);
    uint32_t err = rd(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    if (!(st & SECURE_DMA__STATUS__DONE_bm) || (st & SECURE_DMA__STATUS__ERROR_bm) || err != 0) {
        sep_mbx_puts("FAIL: CHK-HOSTFABRIC recovery copy did not succeed (status ");
        sep_mbx_puthex(st);
        sep_mbx_puts(" err ");
        sep_mbx_puthex(err);
        sep_mbx_puts(")\n");
        e++;
    } else {
        volatile uint32_t *d = (volatile uint32_t *)dst_base;
        for (uint32_t i = 0; i < nwords; i++) {
            if (d[i] != snap[i]) {
                sep_mbx_puts("FAIL: CHK-HOSTFABRIC recovery copy word ");
                sep_mbx_puthex(i);
                sep_mbx_puts(" got ");
                sep_mbx_puthex(d[i]);
                sep_mbx_puts(" exp ");
                sep_mbx_puthex(snap[i]);
                sep_mbx_putc('\n');
                e++;
            }
        }
    }
    wr(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, STATUS_RW1C);
    if (!e) {
        sep_mbx_puts("CHK-HOSTFABRIC PASS: exclusive host_path_err after fabric "
                     "DECERR dest; CLEAR; recovery copy matches source\n");
    }
    return e;
}

// ---- CHK-ERR-ASID: an unencoded ASID -> asid_error -> clear -> recovery ----
// The legal ASID encodings are the DV-owned table in fw/drivers/sep_dma.h,
// transcribed there from the IP register specification; SEP_DMA_ASID_INVALID is
// outside that enumeration. The expected ERROR_CODE bit comes from the
// generated register header, whose RDL describes ASID_ERROR as "The source or
// destination ASID contains an invalid value.".
static int chk_err_asid(void) {
    int e = 0;
    const uint32_t SENT = 0xA5A5A5A5u;
    const uint32_t nwords = copy_bytes / 4u;
    const uint32_t ASID_BAD = SEP_DMA_ASID_INVALID;
    uint32_t snap[MAX_COPY_WORDS];
    fill_src_words(nwords, snap);

    struct {
        const char *name;
        uint32_t asid;
    } cells[] = {
        // ADDR_SPACE_ID packs SRC_ASID in [3:0] and DST_ASID in [7:4].
        {"src asid unencoded", SEP_DMA_ASID_PAIR(ASID_BAD, SEP_DMA_ASID_OT)},
        {"dst asid unencoded", SEP_DMA_ASID_PAIR(SEP_DMA_ASID_OT, ASID_BAD)},
    };
    const uint32_t ncells = (uint32_t)(sizeof(cells) / sizeof(cells[0]));

    for (uint32_t c = 0; c < ncells; c++) {
        uint32_t st =
            dma_run_asid(src_base, dst_base, copy_bytes, copy_bytes, SEP_DMA_WIDTH_4B,
                         SECURE_DMA__SRC_CONFIG__INCREMENT_bm, SECURE_DMA__DST_CONFIG__INCREMENT_bm,
                         SEP_DMA_OPCODE_COPY, cells[c].asid);
        uint32_t err = rd(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
        // Exclusive, like the opcode and address cells: an ERROR_CODE that also
        // raises another bit is a different defect and must not read as a pass.
        if (!(st & SECURE_DMA__STATUS__ERROR_bm) || err != SECURE_DMA__ERROR_CODE__ASID_ERROR_bm) {
            sep_mbx_puts("FAIL: CHK-ERR-ASID ");
            sep_mbx_puts(cells[c].name);
            sep_mbx_puts(" did not set asid_error exclusively (status ");
            sep_mbx_puthex(st);
            sep_mbx_puts(" err ");
            sep_mbx_puthex(err);
            sep_mbx_puts(")\n");
            e++;
        }
        if (st & SECURE_DMA__STATUS__DONE_bm) {
            sep_mbx_puts("FAIL: CHK-ERR-ASID STATUS.done set on an errored transfer\n");
            e++;
        }
        wr(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, STATUS_RW1C);
    }

    // Recovery: a good COPY at the legal ASID still succeeds.
    clear_dst_words(nwords + 1, SENT);
    uint32_t st = dma_run(src_base, dst_base, copy_bytes, copy_bytes, SEP_DMA_WIDTH_4B,
                          SECURE_DMA__SRC_CONFIG__INCREMENT_bm,
                          SECURE_DMA__DST_CONFIG__INCREMENT_bm, SEP_DMA_OPCODE_COPY);
    uint32_t err = rd(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    if (!(st & SECURE_DMA__STATUS__DONE_bm) || (st & SECURE_DMA__STATUS__ERROR_bm) || err != 0) {
        sep_mbx_puts("FAIL: CHK-ERR-ASID recovery copy did not succeed (status ");
        sep_mbx_puthex(st);
        sep_mbx_puts(" err ");
        sep_mbx_puthex(err);
        sep_mbx_puts(")\n");
        e++;
    } else {
        volatile uint32_t *d = (volatile uint32_t *)dst_base;
        for (uint32_t i = 0; i < nwords; i++) {
            if (d[i] != snap[i]) {
                sep_mbx_puts("FAIL: CHK-ERR-ASID recovery copy word ");
                sep_mbx_puthex(i);
                sep_mbx_putc('\n');
                e++;
            }
        }
    }
    wr(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, STATUS_RW1C);
    if (!e) {
        sep_mbx_puts("CHK-ERR-ASID PASS: unencoded src and dst ASID each raised "
                     "asid_error EXCLUSIVE + STATUS.error, W1C clear, recovery copy "
                     "matches source\n");
    }
    return e;
}

// ---- CHK-ERR-SIZE: an unencoded transfer width -> size_error -> recovery ----
// fw/drivers/sep_dma.h is the DV-owned encoding table: TRANSFER_WIDTH is 1B/2B/4B
// as 0/1/2 and SEP_DMA_WIDTH_INVALID (0x3) is outside it, which the header
// already records as raising size_error. Distinct from CHK-ERR-ADDR, where the
// width is legal and the address is not.
static int chk_err_size(void) {
    int e = 0;
    const uint32_t SENT = 0x5A5A5A5Au;
    const uint32_t nwords = copy_bytes / 4u;
    const uint32_t WIDTH_BAD = SEP_DMA_WIDTH_INVALID;
    uint32_t snap[MAX_COPY_WORDS];
    fill_src_words(nwords, snap);

    uint32_t st = dma_run(src_base, dst_base, copy_bytes, copy_bytes, WIDTH_BAD,
                          SECURE_DMA__SRC_CONFIG__INCREMENT_bm,
                          SECURE_DMA__DST_CONFIG__INCREMENT_bm, SEP_DMA_OPCODE_COPY);
    uint32_t err = rd(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    if (!(st & SECURE_DMA__STATUS__ERROR_bm) || err != SECURE_DMA__ERROR_CODE__SIZE_ERROR_bm) {
        sep_mbx_puts("FAIL: CHK-ERR-SIZE width 0x3 did not set size_error exclusively (status ");
        sep_mbx_puthex(st);
        sep_mbx_puts(" err ");
        sep_mbx_puthex(err);
        sep_mbx_puts(")\n");
        e++;
    }
    if (st & SECURE_DMA__STATUS__DONE_bm) {
        sep_mbx_puts("FAIL: CHK-ERR-SIZE STATUS.done set on an errored transfer\n");
        e++;
    }
    wr(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, STATUS_RW1C);

    clear_dst_words(nwords + 1, SENT);
    st = dma_run(src_base, dst_base, copy_bytes, copy_bytes, SEP_DMA_WIDTH_4B,
                 SECURE_DMA__SRC_CONFIG__INCREMENT_bm, SECURE_DMA__DST_CONFIG__INCREMENT_bm,
                 SEP_DMA_OPCODE_COPY);
    err = rd(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    if (!(st & SECURE_DMA__STATUS__DONE_bm) || (st & SECURE_DMA__STATUS__ERROR_bm) || err != 0) {
        sep_mbx_puts("FAIL: CHK-ERR-SIZE recovery copy did not succeed (status ");
        sep_mbx_puthex(st);
        sep_mbx_puts(")\n");
        e++;
    } else {
        volatile uint32_t *d = (volatile uint32_t *)dst_base;
        for (uint32_t i = 0; i < nwords; i++) {
            if (d[i] != snap[i]) {
                sep_mbx_puts("FAIL: CHK-ERR-SIZE recovery copy word ");
                sep_mbx_puthex(i);
                sep_mbx_putc('\n');
                e++;
            }
        }
    }
    wr(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, STATUS_RW1C);
    if (!e) {
        sep_mbx_puts("CHK-ERR-SIZE PASS: transfer width 0x3 -> size_error EXCLUSIVE + "
                     "STATUS.error, W1C clear, recovery copy matches source\n");
    }
    return e;
}

// ---- CHK-ICCM: SRAM -> ICCM -> SRAM round trip through the DMA ----
// Every other copy in this test lands in SRAM. ICCM is a separate destination
// memory on a different port, so a DMA that can reach SRAM and not ICCM passes
// every check above.
//
// The CPU cannot stand in as the witness here: a store to ICCM from the core
// takes a store access fault (mcause 7) on this configuration, so the check
// cannot pre-fill or read back ICCM directly. Instead the DMA carries the data
// out to ICCM and back to a second SRAM region, and the comparison is done
// there. Only the DMA touches ICCM, which is what the check is about.
//
// The return region is pre-filled with a sentinel by the CPU, so a round trip
// that moved nothing leaves the sentinel in place and fails the compare rather
// than matching by accident.
#define ICCM_DMA_OFFSET 0x20000u
#define ICCM_DMA_DST (OCH_SEP_TOP_SEP_ICCM_BASE_ADDR + ICCM_DMA_OFFSET)
// Every SRAM offset in main() is range-checked; this one is a constant, so it
// is checked at build time instead. The copy must also fit above the offset.
_Static_assert(ICCM_DMA_OFFSET + (MAX_COPY_WORDS * 4u) <= OCH_SEP_TOP_SEP_ICCM_SIZE,
               "ICCM DMA destination runs past the end of the instruction memory");
static int chk_iccm_copy(void) {
    int e = 0;
    const uint32_t nwords = copy_bytes / 4u;
    const uint32_t SENT = 0x1CC11CC1u;
    uint32_t snap[MAX_COPY_WORDS];
    fill_src_words(nwords, snap);

    // Return region, placed 0x80 clear of dst_base so it cannot collide with the
    // untouched-neighbour word the later checkers inspect at dst_base. main()
    // guarantees dst_base + 0x100 is still inside SRAM.
    const uint32_t ret_base = dst_base + 0x80u;
    volatile uint32_t *ret = (volatile uint32_t *)ret_base;
    for (uint32_t i = 0; i < nwords; i++) {
        ret[i] = SENT;
    }
    __asm__ volatile("fence" ::: "memory");

    // Outbound: SRAM -> ICCM.
    uint32_t st = dma_run(src_base, ICCM_DMA_DST, copy_bytes, copy_bytes, SEP_DMA_WIDTH_4B,
                          SECURE_DMA__SRC_CONFIG__INCREMENT_bm,
                          SECURE_DMA__DST_CONFIG__INCREMENT_bm, SEP_DMA_OPCODE_COPY);
    uint32_t err = rd(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    if (!(st & SECURE_DMA__STATUS__DONE_bm) || (st & SECURE_DMA__STATUS__ERROR_bm) || err != 0) {
        sep_mbx_puts("FAIL: CHK-ICCM SRAM->ICCM leg did not complete cleanly (status ");
        sep_mbx_puthex(st);
        sep_mbx_puts(" err ");
        sep_mbx_puthex(err);
        sep_mbx_puts(")\n");
        e++;
        wr(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, STATUS_RW1C);
        return e;
    }
    wr(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, STATUS_RW1C);

    // Return: ICCM -> SRAM.
    st = dma_run(ICCM_DMA_DST, ret_base, copy_bytes, copy_bytes, SEP_DMA_WIDTH_4B,
                 SECURE_DMA__SRC_CONFIG__INCREMENT_bm, SECURE_DMA__DST_CONFIG__INCREMENT_bm,
                 SEP_DMA_OPCODE_COPY);
    err = rd(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    if (!(st & SECURE_DMA__STATUS__DONE_bm) || (st & SECURE_DMA__STATUS__ERROR_bm) || err != 0) {
        sep_mbx_puts("FAIL: CHK-ICCM ICCM->SRAM leg did not complete cleanly (status ");
        sep_mbx_puthex(st);
        sep_mbx_puts(" err ");
        sep_mbx_puthex(err);
        sep_mbx_puts(")\n");
        e++;
    } else {
        __asm__ volatile("fence" ::: "memory");
        uint32_t moved = 0;
        for (uint32_t i = 0; i < nwords; i++) {
            uint32_t got = ret[i];
            if (got != snap[i]) {
                sep_mbx_puts("FAIL: CHK-ICCM round-trip word ");
                sep_mbx_puthex(i);
                sep_mbx_puts(" got ");
                sep_mbx_puthex(got);
                sep_mbx_puts(" exp ");
                sep_mbx_puthex(snap[i]);
                sep_mbx_putc('\n');
                e++;
            }
            if (got != SENT) moved++;
        }
        // A source image that happened to equal the sentinel everywhere would
        // make the compare above pass with nothing written, so report how many
        // words actually changed and fail if none did.
        if (moved == 0) {
            sep_mbx_puts("FAIL: CHK-ICCM no word changed from the sentinel -- nothing "
                         "came back from ICCM\n");
            e++;
        }
    }
    wr(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, STATUS_RW1C);
    if (!e) {
        sep_mbx_puts("CHK-ICCM PASS: SRAM->ICCM->SRAM round trip through the DMA "
                     "returned every word equal to the source over the sentinel\n");
    }
    return e;
}

int main(void) {
    int errors = 0;

    sep_outbound_filter_init(); // open the 0x8000_0000 console window
    sep_mbx_puts("SEP DMA basic test\n");

    if (g_dma_params[0] != DMA_PARAM_MAGIC) {
        sep_mbx_puts("FAIL: bad DMA param magic\n");
        return 1;
    }
    src_base = SRAM_BASE + g_dma_params[1];
    dst_base = SRAM_BASE + g_dma_params[2];
    copy_bytes = g_dma_params[3];
    fill_seed = g_dma_params[4];
    if (copy_bytes < 16u || copy_bytes > (MAX_COPY_WORDS * 4u) || (copy_bytes & 0xFu) ||
        (g_dma_params[1] & 0xFu) || (g_dma_params[2] & 0xFu) ||
        (g_dma_params[1] + 0x100u) > SRAM_SIZE || (g_dma_params[2] + 0x100u) > SRAM_SIZE) {
        sep_mbx_puts("FAIL: bad DMA param range\n");
        return 1;
    }
    sep_mbx_puts("SCENARIO src=");
    sep_mbx_puthex(src_base);
    sep_mbx_puts(" dst=");
    sep_mbx_puthex(dst_base);
    sep_mbx_puts(" nbytes=");
    sep_mbx_puthex(copy_bytes);
    sep_mbx_puts(" fill=");
    sep_mbx_puthex(fill_seed);
    sep_mbx_putc('\n');

    errors += chk_reset();        // must run before any DMA write
    errors += chk_range_regwen(); // proves gating, then locks a full valid range
                                  // that all later transfers rely on
    errors += chk_cfg_regwen();
    errors += chk_copy_mode();
    errors += chk_width();
    errors += chk_done_rw1c();
    errors += chk_err_opcode();
    errors += chk_err_addr();
    errors += chk_err_asid();
    errors += chk_err_size();
    errors += chk_iccm_copy();
    errors += chk_host_intg();
    errors += chk_host_fabric();

    if (errors == 0) {
        sep_mbx_puts("PASS: DMA basic -- reset/cfg-regwen/range-regwen/copy-mode/"
                     "width/done-rw1c/err-opcode/err-addr/err-asid/err-size/iccm/"
                     "host-intg/host-fabric all OK\n");
    }
    return errors;
}
