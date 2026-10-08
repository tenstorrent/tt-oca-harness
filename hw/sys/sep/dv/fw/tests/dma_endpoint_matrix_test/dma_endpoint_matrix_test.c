// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP DMA endpoint matrix. The CPU programs the secure DMA for every leg of
// the fabric endpoint matrix and reports what it read back. The cocotb test
// sep_fabric_dma_endpoint_matrix_test patches the seeded values into the
// parameter block g_p, follows the legs through the "M" lines, and grades
// every check from the "R" records and the fabric taps.
//
// Console protocol (one line each):
//   M G <leg>   a graded leg starts; the host opens its coverage window.
//   M C <leg>   a control, set-up or recovery leg starts; the window closes.
//   R <kind> k=0x<v> ...   the values of one leg, printed after the leg.
// After each M line the CPU spins, so the host marks its tap records before
// the leg's first bus access.
//
// Every DMA run is one chunk (CHUNK_DATA_SIZE equals TOTAL_DATA_SIZE) at a
// 4-byte transfer width. Before GO the CPU clears STATUS DONE, ERROR and
// CHUNK_DONE and the DMA bus-error latch, and records the three bits as `pre`.
// The not-connected legs wait for the DMA interrupt in a bounded loop that
// reads only a DTCM flag, so no CPU access reaches the DMA CSR between GO and
// the interrupt.

#include <stdint.h>

#include "sep_dma.h"
#include "sep_mailbox.h"
#include "sep_outbound_filter.h"
#include "sep_pic.h"
#include "filter_ctrl.h"
#include "output_remap.h"
#include "aes.h"
#include "aon_timer.h"
#include "sep_scratch.h"

// ---- Parameter block (the host patches it; keep in step with the test) ----
#define P_MAGIC_WORD 0xDAE9D0A3u
enum {
    P_MAGIC,
    P_ORDER, // pair order: nibble k = pair id run k-th
    P_FORM,  // bit i: SRAM side of pair i uses the local alias form
    P_SEED,  // fill seed
    P0_LEN,  // SRAM to scratch
    P0_SRAM,
    P0_SCR,
    P1_LEN, // scratch to SRAM
    P1_SCR,
    P1_SRAM,
    P2_LEN, // WDT word to SRAM
    P2_SRAM,
    P3_LEN, // AES word to SRAM
    P3_SRAM,
    PD_LEN, // directed SRAM to SRAM copy, direct form
    PD_SRC,
    PD_DST,
    PA_LEN, // alias leg
    PA_OS,
    PA_OD,
    PAP_OFF_LO, // AP region 0 offset
    PAP_OFF_HI,
    PAP_INTRA,  // AP word offset inside region 0
    PSMU,       // SMU window word (low 32 bits)
    PREG_ORDER, // register order: nibble k = register id
    PREG_LEN0,
    PREG_LEN1,
    PREG_LEN2,
    PREG_LAST0,
    PREG_LAST1,
    PREG_LAST2,
    PFILT_SRC,
    PFILT_GRP,
    PSMC_OFF,
    PSMC_LEN,
    P_COUNT
};

// Committed defaults: a directed image that runs stand-alone.
volatile uint32_t g_p[P_COUNT] = {
    P_MAGIC_WORD, 0x3210u,     0x0u,    0x1234567u,  32u,     0x0000u,     0x0u,    32u,     0x0u,
    0x1000u,      16u,         0x2000u, 16u,         0x3000u, 32u,         0x4000u, 0x5000u, 32u,
    0x6000u,      0x7000u,     0x0u,    0xC0u,       0x100u,  0x80004000u, 0x210u,  8u,      8u,
    8u,           0x11111111u, 0x2u,    0x33333333u, 0x5u,    0xAu,        0x1000u, 64u,
};

// ---- Address map ----
#define SRAM SEP_TOP_SEP_SRAM_BASE_ADDR
#define ALIAS SEP_CPU_CTRL__SEP_LOCAL_BASE_ADDR__ADDR_reset
#define SCRATCH SEP_TOP_SEP_SCRATCH_COLD_BASE_ADDR
#define WDT_REGWEN SEP_TOP_WDT_TIMER_WDOG_REGWEN_BASE_ADDR
#define AES_AUX_REGWEN SEP_TOP_AES_CTRL_AUX_REGWEN_BASE_ADDR
// The REGWEN field of each register source as it reads from reset.
#define WDT_REGWEN_SET (AON_TIMER__WDOG_REGWEN__REGWEN_reset << AON_TIMER__WDOG_REGWEN__REGWEN_bp)
#define AES_AUX_REGWEN_SET \
    (AES__CTRL_AUX_REGWEN__CTRL_AUX_REGWEN_reset << AES__CTRL_AUX_REGWEN__CTRL_AUX_REGWEN_bp)
// A scratch register is 8 bytes; its DATA field fills the low lane only.
#define SCRATCH_STRIDE \
    (SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(1) - SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(0))
#define SCRATCH_FIELD_LANE(a) (((a) % SCRATCH_STRIDE) < (SEP_SCRATCH__SCRATCH__DATA_bw / 8u))
#define EXT_WORD (SEP_TOP_SEP_EXTERNAL_BASE_ADDR + 0x100u)
// Top word of the 768 MiB local alias span (hw/sys/sep/doc/fabric.adoc, SEP CPU
// local-alias traffic), through the alias window.
#define LOCAL_ALIAS_SPAN 0x30000000u
#define EXT_TOP_ALIAS ((uint32_t)SEP_CPU_CTRL__SEP_LOCAL_BASE_ADDR_reset + LOCAL_ALIAS_SPAN - 8u)
#define AP_REGION SEP_TOP_AP_REGION_BASE_ADDR
// Byte span of one AP output-remap region: the AP window over its regions.
#define AP_SPAN (SEP_TOP_AP_REGION_SIZE / SEP_TOP_AP_OUTPUT_REMAP_CTRL_REGION_NUM)
// The SMC aperture of the testlist entry (+sep_smc_aperture_base=40000000).
#define SMC_BASE 0x40000000u
#define ROM_BASE SEP_TOP_SEP_BOOT_ROM_BASE_ADDR
#define DMA_CSR_WORD SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR
#define FILT_IN0_CFG SEP_TOP_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(0)
#define N_OUT_ENTRIES SEP_TOP_OUTBOUND_FILTER_CTRL_NUM

// SRAM bands (offsets from SRAM) of the legs whose offsets are not seeded.
#define B_EXT 0x8000u
#define B_ALX 0x8100u
#define B_OUT 0x8200u
#define B_REG 0x9000u
#define B_SMC_SRC 0xA000u
#define B_SMC_DST 0xB000u
#define B_NC 0xC000u
#define B_REC_SRC 0xD000u
#define B_REC_DST 0xE000u
#define REC_LEN 32u

#define ST3 \
    (SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__ERROR_bm | SECURE_DMA__STATUS__CHUNK_DONE_bm)
#define DONE_OR_ERR (SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__ERROR_bm)
#define POLL_ITERS 20000
#define IRQ_WAIT_ITERS 100000
#define MARK_SPIN 300

// PIC sources of the secure DMA done and error interrupts.
#define EXT_INT_DMA_DONE 9
#define EXT_INT_DMA_ERROR 11

static inline uint32_t rd(uint32_t a) {
    return *(volatile uint32_t *)a;
}
static inline void wr(uint32_t a, uint32_t v) {
    *(volatile uint32_t *)a = v;
}

static int g_err;

// ---- Console ----
static void spin(uint32_t n) {
    for (volatile uint32_t i = 0; i < n; i++) {
    }
}
static void mark(char kind, const char *leg) {
    sep_mbx_puts("M ");
    sep_mbx_putc(kind);
    sep_mbx_putc(' ');
    sep_mbx_puts(leg);
    sep_mbx_putc('\n');
    spin(MARK_SPIN);
}
static void rec(const char *kind) {
    sep_mbx_puts("R ");
    sep_mbx_puts(kind);
}
static void kv(const char *k, uint32_t v) {
    sep_mbx_putc(' ');
    sep_mbx_puts(k);
    sep_mbx_putc('=');
    sep_mbx_puthex(v);
}
static void end(void) {
    sep_mbx_putc('\n');
}

// ---- Data model shared with the host (env side of the test) ----
static uint32_t seed_of(uint32_t tag) {
    return g_p[P_SEED] ^ (tag * 0x9E3779B9u);
}
static uint32_t lcg(uint32_t *x) {
    *x = *x * 1664525u + 1013904223u;
    return *x;
}
static uint32_t fnv(uint32_t h, uint32_t w) {
    return (h ^ w) * 0x01000193u;
}
#define FNV0 0x811C9DC5u

// Stage n source words from seed `tag`; returns nothing, the host knows them.
static void stage_src(uint32_t a, uint32_t n, uint32_t tag) {
    uint32_t x = seed_of(tag);
    for (uint32_t i = 0; i < n; i++) wr(a + 4u * i, lcg(&x));
}
// Destination pattern: the complement of the source model, so no word of the
// destination equals its source before the copy.
static void stage_dst_not(uint32_t a, uint32_t n, uint32_t tag) {
    uint32_t x = seed_of(tag);
    for (uint32_t i = 0; i < n; i++) wr(a + 4u * i, ~lcg(&x));
}

// ---- DMA ----
static uint32_t g_pre;
static void dma_init(void) {
    wr(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR, 0x0u);
    wr(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR, 0xFFFFFFFFu);
    wr(SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR, 0x1u);
    wr(SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR, SEP_DMA_WIDTH_4B);
    wr(SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR,
       SEP_DMA_ASID_PAIR(SECURE_DMA__ADDR_SPACE_ID__SRC_ASID_reset,
                         SECURE_DMA__ADDR_SPACE_ID__SRC_ASID_reset));
    wr(SEP_TOP_SECURE_DMA_INTR_ENABLE_BASE_ADDR,
       SECURE_DMA__INTR_ENABLE__DMA_DONE_bm | SECURE_DMA__INTR_ENABLE__DMA_ERROR_bm);
}
static void dma_clear(void) {
    wr(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, ST3);
    wr(SEP_TOP_SEP_CPU_CTRL_DMA_BUS_ERR_CLEAR_BASE_ADDR, SEP_CPU_CTRL__DMA_BUS_ERR_CLEAR__CLR_bm);
}
static void dma_prep(uint32_t src, uint32_t dst, uint32_t len, int src_inc, int dst_inc) {
    wr(SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR, src);
    wr(SEP_TOP_SECURE_DMA_SRC_ADDR_HI_BASE_ADDR, 0x0u);
    wr(SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR, dst);
    wr(SEP_TOP_SECURE_DMA_DST_ADDR_HI_BASE_ADDR, 0x0u);
    wr(SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, len);
    wr(SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR, len);
    wr(SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR,
       src_inc ? SECURE_DMA__SRC_CONFIG__INCREMENT_bm : 0u);
    wr(SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR,
       dst_inc ? SECURE_DMA__DST_CONFIG__INCREMENT_bm : 0u);
    dma_clear();
    g_pre = rd(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR) & ST3;
}
static inline void dma_go(void) {
    wr(SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR,
       SECURE_DMA__CONTROL__GO_bm | SECURE_DMA__CONTROL__INITIAL_TRANSFER_bm | SEP_DMA_OPCODE_COPY);
}
// Polled run. Returns STATUS; a bounded wait that ends in neither DONE nor
// ERROR returns the last STATUS, which the host fails.
static uint32_t dma_run(uint32_t src, uint32_t dst, uint32_t len, int src_inc, int dst_inc) {
    dma_prep(src, dst, len, src_inc, dst_inc);
    dma_go();
    uint32_t st;
    int t = POLL_ITERS;
    do {
        st = rd(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
    } while (!(st & DONE_OR_ERR) && --t > 0);
    if (!(st & DONE_OR_ERR)) {
        sep_mbx_puts("FAIL: DMA run neither done nor error\n");
        g_err++;
    }
    return st;
}
static void rec_run(uint32_t st) {
    kv("pre", g_pre);
    kv("st", st);
    kv("ec", rd(SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR));
}

// Recovery copy: clear the error state, copy seeded SRAM words and compare.
static uint32_t g_rec_n;
static int recovery(const char *after) {
    mark('C', "recovery");
    dma_clear();
    uint32_t tag = 0x100u + g_rec_n++;
    uint32_t n = REC_LEN / 4u;
    stage_src(SRAM + B_REC_SRC, n, tag);
    stage_dst_not(SRAM + B_REC_DST, n, tag);
    uint32_t st = dma_run(SRAM + B_REC_SRC, SRAM + B_REC_DST, REC_LEN, 1, 1);
    uint32_t h = FNV0, bad = 0, x = seed_of(tag);
    for (uint32_t i = 0; i < n; i++) {
        uint32_t v = rd(SRAM + B_REC_DST + 4u * i);
        h = fnv(h, v);
        if (v != lcg(&x)) bad++;
    }
    rec("RECOV");
    sep_mbx_puts(" after=");
    sep_mbx_puts(after);
    kv("tag", tag);
    rec_run(st);
    kv("nbad", bad);
    kv("dsum", h);
    end();
    dma_clear();
    return (st & SECURE_DMA__STATUS__DONE_bm) && !(st & SECURE_DMA__STATUS__ERROR_bm) && bad == 0;
}

// ---- Step 3: the four random pairs and the directed direct copy ----
static uint32_t sram_side(int pair, uint32_t off) {
    return ((g_p[P_FORM] >> pair) & 1u) ? ALIAS + off : SRAM + off;
}

static void pair_sram_to_scratch(void) {
    uint32_t len = g_p[P0_LEN], n = len / 4u;
    uint32_t src = sram_side(0, g_p[P0_SRAM]), src_d = SRAM + g_p[P0_SRAM];
    uint32_t dst = SCRATCH + g_p[P0_SCR];
    stage_src(src_d, n, 0x10u);
    uint32_t x = seed_of(0x10u);
    for (uint32_t i = 0; i < n; i++) {
        uint32_t m = lcg(&x);
        if (SCRATCH_FIELD_LANE(dst + 4u * i)) wr(dst + 4u * i, ~m);
    }
    mark('G', "pair_sram_scratch");
    uint32_t st = dma_run(src, dst, len, 1, 1);
    uint32_t h = FNV0, ng = 0, bad = 0, hr = FNV0;
    x = seed_of(0x10u);
    for (uint32_t i = 0; i < n; i++) {
        uint32_t a = dst + 4u * i;
        uint32_t m = lcg(&x);
        if (SCRATCH_FIELD_LANE(a)) {
            uint32_t v = rd(a);
            h = fnv(h, v);
            ng++;
            if (v != m) bad++;
        } else {
            hr = fnv(hr, rd(a));
        }
    }
    rec("PAIR");
    kv("id", 0);
    kv("src", src);
    kv("dst", dst);
    kv("len", len);
    rec_run(st);
    kv("ng", ng);
    kv("nbad", bad);
    kv("dsum", h);
    kv("rsum", hr);
    end();
    dma_clear();
}

static void pair_scratch_to_sram(void) {
    uint32_t len = g_p[P1_LEN], n = len / 4u;
    uint32_t src = SCRATCH + g_p[P1_SCR];
    uint32_t dst = sram_side(1, g_p[P1_SRAM]), dst_d = SRAM + g_p[P1_SRAM];
    uint32_t x = seed_of(0x11u);
    for (uint32_t i = 0; i < n; i++) {
        uint32_t m = lcg(&x);
        if (SCRATCH_FIELD_LANE(src + 4u * i)) wr(src + 4u * i, m);
    }
    stage_dst_not(dst_d, n, 0x11u);
    mark('G', "pair_scratch_sram");
    uint32_t st = dma_run(src, dst, len, 1, 1);
    uint32_t h = FNV0, ng = 0, bad = 0, hr = FNV0;
    x = seed_of(0x11u);
    for (uint32_t i = 0; i < n; i++) {
        uint32_t v = rd(dst_d + 4u * i);
        uint32_t m = lcg(&x);
        if (SCRATCH_FIELD_LANE(src + 4u * i)) {
            h = fnv(h, v);
            ng++;
            if (v != m) bad++;
        } else {
            hr = fnv(hr, v);
        }
    }
    rec("PAIR");
    kv("id", 1);
    kv("src", src);
    kv("dst", dst);
    kv("len", len);
    rec_run(st);
    kv("ng", ng);
    kv("nbad", bad);
    kv("dsum", h);
    kv("rsum", hr);
    end();
    dma_clear();
}

// A register source at a fixed address. Its REGWEN field (`set`) reads set
// from reset and the leaf never writes the register; the destination is
// staged with that field clear.
static void pair_reg_to_sram(int id, uint32_t reg, uint32_t set, uint32_t len, uint32_t off,
                             const char *leg) {
    uint32_t n = len / 4u;
    uint32_t dst = sram_side(id, off), dst_d = SRAM + off;
    uint32_t x = seed_of(0x10u + (uint32_t)id);
    for (uint32_t i = 0; i < n; i++) wr(dst_d + 4u * i, lcg(&x) & ~set);
    uint32_t pre_v = rd(reg);
    mark('G', leg);
    uint32_t st = dma_run(reg, dst, len, 0, 1);
    uint32_t post_v = rd(reg);
    uint32_t dor = 0, dand = 0xFFFFFFFFu, nb0 = 0, h = FNV0;
    for (uint32_t i = 0; i < n; i++) {
        uint32_t v = rd(dst_d + 4u * i);
        dor |= v;
        dand &= v;
        h = fnv(h, v);
        if ((v & set) != set) nb0++;
    }
    rec("PAIR");
    kv("id", (uint32_t)id);
    kv("src", reg);
    kv("dst", dst);
    kv("len", len);
    rec_run(st);
    kv("regpre", pre_v);
    kv("regpost", post_v);
    kv("nbit0bad", nb0);
    kv("dor", dor);
    kv("dand", dand);
    kv("dsum", h);
    end();
    dma_clear();
}

static void direct_copy(void) {
    uint32_t len = g_p[PD_LEN], n = len / 4u;
    uint32_t src = SRAM + g_p[PD_SRC], dst = SRAM + g_p[PD_DST];
    stage_src(src, n, 0x20u);
    stage_dst_not(dst, n, 0x20u);
    mark('G', "direct_copy");
    uint32_t st = dma_run(src, dst, len, 1, 1);
    uint32_t h = FNV0, bad = 0, x = seed_of(0x20u);
    for (uint32_t i = 0; i < n; i++) {
        uint32_t v = rd(dst + 4u * i);
        h = fnv(h, v);
        if (v != lcg(&x)) bad++;
    }
    rec("ALIAS");
    sep_mbx_puts(" form=direct");
    kv("src", src);
    kv("dst", dst);
    kv("len", len);
    rec_run(st);
    kv("nbad", bad);
    kv("dsum", h);
    end();
    dma_clear();
}

// ---- Step 4: extension port, one beat each way ----
static void ext_legs(void) {
    uint32_t d = SRAM + B_EXT;
    wr(d, 0x5A5A5A5Au);
    mark('G', "ext_r");
    uint32_t st = dma_run(EXT_WORD, d, 4u, 1, 1);
    rec("EXT");
    sep_mbx_puts(" dir=R");
    rec_run(st);
    kv("dst_word", rd(d));
    end();
    recovery("ext_r");

    stage_src(SRAM + B_EXT + 0x10u, 1u, 0x30u);
    mark('G', "ext_w");
    st = dma_run(SRAM + B_EXT + 0x10u, EXT_WORD, 4u, 1, 1);
    rec("EXT");
    sep_mbx_puts(" dir=W");
    rec_run(st);
    end();
    recovery("ext_w");
}

// ---- Step 5: alias forms ----
static void alias_legs(void) {
    uint32_t len = g_p[PA_LEN], n = len / 4u;
    uint32_t os = g_p[PA_OS], od = g_p[PA_OD];
    stage_src(SRAM + os, n, 0x40u);
    stage_dst_not(SRAM + od, n, 0x40u);
    uint32_t hc = FNV0, cbad = 0, xc = seed_of(0x40u);
    for (uint32_t i = 0; i < n; i++) {
        uint32_t v = rd(SRAM + os + 4u * i);
        hc = fnv(hc, v);
        if (v != lcg(&xc)) cbad++;
    }
    mark('G', "alias_copy");
    uint32_t st = dma_run(ALIAS + os, ALIAS + od, len, 1, 1);
    uint32_t h = FNV0, bad = 0, x = seed_of(0x40u);
    for (uint32_t i = 0; i < n; i++) {
        uint32_t v = rd(SRAM + od + 4u * i);
        h = fnv(h, v);
        if (v != lcg(&x)) bad++;
    }
    rec("ALIAS");
    sep_mbx_puts(" form=alias");
    kv("src", ALIAS + os);
    kv("dst", ALIAS + od);
    kv("len", len);
    rec_run(st);
    kv("ctl_nbad", cbad);
    kv("ctl_sum", hc);
    kv("nbad", bad);
    kv("dsum", h);
    end();
    dma_clear();

    stage_src(SRAM + B_ALX, 2u, 0x41u);
    mark('G', "alias_ext_top");
    st = dma_run(SRAM + B_ALX, EXT_TOP_ALIAS, 8u, 1, 1);
    rec("ALIASEXT");
    rec_run(st);
    end();
    recovery("alias_ext_top");
}

// ---- Outbound filter entries ----
static uint32_t g_frb_bad, g_frb_rng, g_frb_sum, g_frb_idx, g_frb_c;
// CONFIG goes first with the entry disabled, so START and END are written
// under the final allow_burst granule, then CONFIG enables the entry.
static void out_entry(uint32_t i, uint64_t start, uint64_t endv, uint32_t cfg) {
    wr(SEP_TOP_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(i),
       cfg & ~FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm);
    WRITE_REG64(SEP_TOP_OUTBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR(i), start);
    WRITE_REG64(SEP_TOP_OUTBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR(i), endv);
    wr(SEP_TOP_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(i), cfg);
}
// FILTER_CONFIG field bits of the low word (the locked bit is in the high word).
#define CFG_FIELDS_LO \
    ((uint32_t)(FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm | \
                FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm | \
                FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm | \
                FILTER_CTRL__FILTER_CONFIG__ALLOW_NS_bm | \
                FILTER_CTRL__FILTER_CONFIG__DATA_BUS_WIDTH_bm | \
                FILTER_CTRL__FILTER_CONFIG__SRC_ID_bm | FILTER_CTRL__FILTER_CONFIG__GROUP_ID_bm | \
                FILTER_CTRL__FILTER_CONFIG__ALLOW_BURST_bm))
// Read an entry back. The field bits of FILTER_CONFIG are graded (the sum lets
// the host check them). The specification states no write-back timing for
// START and END, so their read-back is counted and logged only.
static void out_entry_check(uint32_t i, uint64_t start, uint64_t endv, uint32_t cfg) {
    uint32_t c = rd(SEP_TOP_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(i)) & CFG_FIELDS_LO;
    uint64_t s = READ_REG64(SEP_TOP_OUTBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR(i)) &
                 FILTER_CTRL__START_ADDR__START_ADDR_bm;
    uint64_t e = READ_REG64(SEP_TOP_OUTBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR(i)) &
                 FILTER_CTRL__END_ADDR__END_ADDR_bm;
    uint32_t want_c = (cfg | ((uint32_t)FILTER_CTRL__FILTER_CONFIG__DATA_BUS_WIDTH_reset
                              << FILTER_CTRL__FILTER_CONFIG__DATA_BUS_WIDTH_bp)) &
                      CFG_FIELDS_LO;
    if (s != start || e != endv) g_frb_rng++;
    if (c != want_c) {
        if (g_frb_bad == 0u) {
            g_frb_idx = i;
            g_frb_c = c;
        }
        g_frb_bad++;
    }
    g_frb_sum = fnv(g_frb_sum, c);
}
#define CFG_RW_EN \
    (FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm | FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm | \
     FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm)
#define CFG_NS FILTER_CTRL__FILTER_CONFIG__ALLOW_NS_bm
#define CFG_SRC(s) ((uint32_t)(s) << FILTER_CTRL__FILTER_CONFIG__SRC_ID_bp)

static uint64_t ap_out_addr(void) {
    uint64_t off = ((uint64_t)g_p[PAP_OFF_HI] << 32) | g_p[PAP_OFF_LO];
    return (off & ~(uint64_t)(AP_SPAN - 1u)) | (g_p[PAP_INTRA] & (AP_SPAN - 1u));
}

// ---- Step 6: outbound legs ----
static void outbound_legs(void) {
    uint64_t ap_o = ap_out_addr();
    uint64_t smu = g_p[PSMU];
    uint32_t attrs = SEP_TOP_AP_OUTPUT_REMAP_CTRL_REGION_REGION_ATTRS_BASE_ADDR(0);
    uint64_t want = (((uint64_t)g_p[PAP_OFF_HI] << 32) | g_p[PAP_OFF_LO]) &
                    OUTPUT_REMAP__OUTPUT_REMAP_REGION__REGION_ATTRS__OFFSET_bm;
    want |= OUTPUT_REMAP__OUTPUT_REMAP_REGION__REGION_ATTRS__VALID_bm;
    mark('C', "out_setup");
    WRITE_REG64(attrs, want);
    uint64_t got = READ_REG64(attrs);
    g_frb_bad = 0;
    g_frb_rng = 0;
    g_frb_sum = FNV0;
    out_entry(1, ap_o, ap_o + 7u, CFG_RW_EN);
    out_entry(2, ap_o, ap_o + 7u, CFG_RW_EN | CFG_NS);
    out_entry(3, smu, smu + 7u, CFG_RW_EN);
    out_entry(4, smu, smu + 7u, CFG_RW_EN | CFG_NS);
    out_entry_check(1, ap_o, ap_o + 7u, CFG_RW_EN);
    out_entry_check(2, ap_o, ap_o + 7u, CFG_RW_EN | CFG_NS);
    out_entry_check(3, smu, smu + 7u, CFG_RW_EN);
    out_entry_check(4, smu, smu + 7u, CFG_RW_EN | CFG_NS);
    rec("OUTSET");
    kv("attrs_lo", (uint32_t)got);
    kv("attrs_hi", (uint32_t)(got >> 32));
    kv("rb_bad", g_frb_bad);
    kv("rng_diff", g_frb_rng);
    kv("rb_sum", g_frb_sum);
    end();

    stage_src(SRAM + B_OUT, 2u, 0x50u);
    mark('G', "out_ap");
    uint32_t st = dma_run(SRAM + B_OUT, AP_REGION + (g_p[PAP_INTRA] & (AP_SPAN - 1u)), 8u, 1, 1);
    rec("OUT");
    sep_mbx_puts(" tgt=ap");
    rec_run(st);
    end();
    dma_clear();

    stage_src(SRAM + B_OUT + 0x10u, 2u, 0x51u);
    mark('G', "out_smu");
    st = dma_run(SRAM + B_OUT + 0x10u, (uint32_t)smu, 8u, 1, 1);
    rec("OUT");
    sep_mbx_puts(" tgt=smu");
    rec_run(st);
    end();
    dma_clear();

    mark('C', "out_cpu");
    wr((uint32_t)smu, 0xC0DE0001u);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    rec("OUTCPU");
    kv("addr", (uint32_t)smu);
    end();
}

// ---- Step 7: source-ID stack over the SMU window word ----
// The stack covers the mailbox entry too, so nothing is printed from the
// first entry write until entry 0 is restored.
static void stack_leg(void) {
    uint64_t smu = g_p[PSMU];
    stage_src(SRAM + B_OUT + 0x20u, 2u, 0x52u);
    mark('C', "stack");
    g_frb_bad = 0;
    g_frb_rng = 0;
    g_frb_sum = FNV0;
    for (uint32_t i = 0; i < 15u; i++) out_entry(i, smu, smu + 7u, CFG_RW_EN | CFG_SRC(i + 1u));
    for (uint32_t i = 0; i < 15u; i++)
        out_entry(15u + i, smu, smu + 7u, CFG_RW_EN | CFG_NS | CFG_SRC(i + 1u));
    uint32_t ro =
        FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm | FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm;
    out_entry(30, smu, smu + 7u, ro);
    out_entry(31, smu, smu + 7u, ro | CFG_NS);
    for (uint32_t i = 0; i < 15u; i++)
        out_entry_check(i, smu, smu + 7u, CFG_RW_EN | CFG_SRC(i + 1u));
    for (uint32_t i = 0; i < 15u; i++)
        out_entry_check(15u + i, smu, smu + 7u, CFG_RW_EN | CFG_NS | CFG_SRC(i + 1u));
    out_entry_check(30, smu, smu + 7u, ro);
    out_entry_check(31, smu, smu + 7u, ro | CFG_NS);
    uint32_t rb1_bad = g_frb_bad, rb1_sum = g_frb_sum, rng1 = g_frb_rng;
    uint32_t bad_idx = g_frb_idx, bad_c = g_frb_c;

    uint32_t st1 = dma_run(SRAM + B_OUT + 0x20u, (uint32_t)smu, 8u, 1, 1);
    uint32_t pre1 = g_pre;
    uint32_t ec1 = rd(SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    dma_clear();
    // Recovery copy inside the stack window; its record is printed below.
    uint32_t tag = 0x100u + g_rec_n++;
    uint32_t n = REC_LEN / 4u;
    stage_src(SRAM + B_REC_SRC, n, tag);
    stage_dst_not(SRAM + B_REC_DST, n, tag);
    uint32_t rst = dma_run(SRAM + B_REC_SRC, SRAM + B_REC_DST, REC_LEN, 1, 1);
    uint32_t rpre = g_pre;
    uint32_t rec_ec = rd(SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    uint32_t rh = FNV0, rbad = 0, rx = seed_of(tag);
    for (uint32_t i = 0; i < n; i++) {
        uint32_t v = rd(SRAM + B_REC_DST + 4u * i);
        rh = fnv(rh, v);
        if (v != lcg(&rx)) rbad++;
    }
    dma_clear();

    g_frb_bad = 0;
    g_frb_rng = 0;
    g_frb_sum = FNV0;
    out_entry(30, smu, smu + 7u, CFG_RW_EN);
    out_entry(31, smu, smu + 7u, CFG_RW_EN | CFG_NS);
    out_entry_check(30, smu, smu + 7u, CFG_RW_EN);
    out_entry_check(31, smu, smu + 7u, CFG_RW_EN | CFG_NS);
    uint32_t rb2_bad = g_frb_bad, rb2_sum = g_frb_sum, rng2 = g_frb_rng;
    uint32_t st2 = dma_run(SRAM + B_OUT + 0x20u, (uint32_t)smu, 8u, 1, 1);
    uint32_t pre2 = g_pre;
    uint32_t ec2 = rd(SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    dma_clear();

    // Restore: entry 0 is the mailbox window, every other entry at reset.
    for (uint32_t i = 1; i < N_OUT_ENTRIES; i++)
        out_entry(i, FILTER_CTRL__START_ADDR__START_ADDR_reset,
                  FILTER_CTRL__END_ADDR__END_ADDR_reset, 0u);
    sep_outbound_filter_init();

    rec("STACK");
    kv("rb1_bad", rb1_bad);
    kv("rb1_sum", rb1_sum);
    if (rb1_bad) {
        kv("bad_idx", bad_idx);
        kv("bad_cfg", bad_c);
    }
    kv("pre", pre1);
    kv("st", st1);
    kv("ec", ec1);
    kv("rb2_bad", rb2_bad);
    kv("rb2_sum", rb2_sum);
    kv("rng1_diff", rng1);
    kv("rng2_diff", rng2);
    kv("ctl_pre", pre2);
    kv("ctl_st", st2);
    kv("ctl_ec", ec2);
    end();
    rec("RECOV");
    sep_mbx_puts(" after=stack");
    kv("tag", tag);
    kv("pre", rpre);
    kv("st", rst);
    kv("ec", rec_ec);
    kv("nbad", rbad);
    kv("dsum", rh);
    end();

    // AP region 0 back to reset.
    WRITE_REG64(SEP_TOP_AP_OUTPUT_REMAP_CTRL_REGION_REGION_ATTRS_BASE_ADDR(0), 0ull);
}

// ---- Step 8: register endpoints ----
static const uint32_t k_reg_addr[3] = {
    SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(0),
    SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR,
    SEP_TOP_SEP_CPU_CTRL_SEP_SW_DEBUG_BASE_ADDR,
};
static const char *const k_reg_name[3] = {"scratch0", "spi_csid", "sep_sw_debug"};
static const char *const k_reg_wleg[3] = {"reg_w_scratch0", "reg_w_spi_csid", "reg_w_sep_sw_debug"};
static const char *const k_reg_rleg[3] = {"reg_r_scratch0", "reg_r_spi_csid", "reg_r_sep_sw_debug"};

static void reg_leg(uint32_t id, uint32_t pre) {
    uint32_t reg = k_reg_addr[id];
    uint32_t len = g_p[PREG_LEN0 + id], n = len / 4u;
    uint32_t last = g_p[PREG_LAST0 + id];
    if (last == pre) last ^= 1u;
    uint32_t src = SRAM + B_REG + 0x100u * id, dst = src + 0x80u;
    stage_src(src, n, 0x60u + id);
    wr(src + 4u * (n - 1u), last);
    for (uint32_t i = 0; i < n; i++) wr(dst + 4u * i, ~last);
    mark('G', k_reg_wleg[id]);
    uint32_t st_w = dma_run(src, reg, len, 1, 0);
    uint32_t pre_w = g_pre, ec_w = rd(SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    uint32_t rb = rd(reg);
    dma_clear();
    uint32_t ctl_a = rd(reg);
    mark('G', k_reg_rleg[id]);
    uint32_t st_r = dma_run(reg, dst, len, 0, 1);
    uint32_t pre_r = g_pre, ec_r = rd(SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    uint32_t ctl_b = rd(reg);
    uint32_t bad = 0, dor = 0, dand = 0xFFFFFFFFu;
    for (uint32_t i = 0; i < n; i++) {
        uint32_t v = rd(dst + 4u * i);
        dor |= v;
        dand &= v;
        if (v != last) bad++;
    }
    dma_clear();
    wr(reg, pre);
    rec("REG");
    sep_mbx_puts(" name=");
    sep_mbx_puts(k_reg_name[id]);
    kv("id", id);
    kv("addr", reg);
    kv("len", len);
    kv("regpre", pre);
    kv("last", last);
    kv("w_pre", pre_w);
    kv("w_st", st_w);
    kv("w_ec", ec_w);
    kv("rb", rb);
    kv("ctl_a", ctl_a);
    kv("r_pre", pre_r);
    kv("r_st", st_r);
    kv("r_ec", ec_r);
    kv("ctl_b", ctl_b);
    kv("nbad", bad);
    kv("dor", dor);
    kv("dand", dand);
    kv("restored", rd(reg));
    end();
}

static void reg_legs(void) {
    uint32_t pre[3];
    mark('C', "reg_pre");
    for (uint32_t i = 0; i < 3u; i++) pre[i] = rd(k_reg_addr[i]);
    rec("REGPRE");
    kv("scratch0", pre[0]);
    kv("spi_csid", pre[1]);
    kv("sep_sw_debug", pre[2]);
    end();
    for (uint32_t k = 0; k < 3u; k++) {
        uint32_t id = (g_p[PREG_ORDER] >> (4u * k)) & 0xFu;
        if (id > 2u) {
            sep_mbx_puts("FAIL: bad register order\n");
            g_err++;
            continue;
        }
        reg_leg(id, pre[id]);
    }

    // SW_RESET_N read.
    uint32_t d = SRAM + B_REG + 0x400u;
    wr(d, 0xFFFFFF00u);
    uint32_t lsu = rd(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR);
    mark('G', "rst_r");
    uint32_t st = dma_run(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR, d, 4u, 0, 1);
    rec("RST");
    kv("lsu", lsu);
    rec_run(st);
    kv("dma", rd(d));
    end();
    dma_clear();

    // Inbound entry 0 FILTER_CONFIG with seeded src_id and group_id; the
    // entry stays disabled.
    uint32_t fw = ((g_p[PFILT_SRC] << FILTER_CTRL__FILTER_CONFIG__SRC_ID_bp) &
                   FILTER_CTRL__FILTER_CONFIG__SRC_ID_bm) |
                  ((g_p[PFILT_GRP] << FILTER_CTRL__FILTER_CONFIG__GROUP_ID_bp) &
                   FILTER_CTRL__FILTER_CONFIG__GROUP_ID_bm) |
                  ((uint32_t)FILTER_CTRL__FILTER_CONFIG__DATA_BUS_WIDTH_reset
                   << FILTER_CTRL__FILTER_CONFIG__DATA_BUS_WIDTH_bp);
    mark('C', "filt_set");
    wr(FILT_IN0_CFG, fw);
    uint32_t flsu = rd(FILT_IN0_CFG);
    d = SRAM + B_REG + 0x410u;
    wr(d, 0x0u);
    mark('G', "filt_r");
    st = dma_run(FILT_IN0_CFG, d, 4u, 0, 1);
    rec("FILT");
    kv("written", fw);
    kv("lsu", flsu);
    rec_run(st);
    kv("dma", rd(d));
    dma_clear();
    wr(FILT_IN0_CFG, (uint32_t)FILTER_CTRL__FILTER_CONFIG__DATA_BUS_WIDTH_reset
                         << FILTER_CTRL__FILTER_CONFIG__DATA_BUS_WIDTH_bp);
    kv("restored", rd(FILT_IN0_CFG));
    end();
}

// ---- Step 9: SMC port ----
static void smc_legs(void) {
    mark('C', "smc_fuse");
    uint32_t polls = 0, fs = 0;
    for (; polls < 2000u; polls++) {
        fs = rd(SEP_TOP_SEP_CPU_CTRL_SMC_FUSE_SENSE_STATUS_BASE_ADDR);
        if (fs & SEP_CPU_CTRL__SMC_FUSE_SENSE_STATUS__SMC_FUSE_SENSE_DONE_bm) break;
    }
    // A request to the SMC before smc_fuse_sense_done hangs, so the SMC legs
    // run only after the poll sees it.
    if (!(fs & SEP_CPU_CTRL__SMC_FUSE_SENSE_STATUS__SMC_FUSE_SENSE_DONE_bm)) {
        sep_mbx_puts(
            "FAIL: smc_fuse_sense_done still 0 after the bounded poll; SMC legs skipped\n");
        g_err++;
        return;
    }
    uint32_t len = g_p[PSMC_LEN], n = len / 4u;
    uint32_t smc = SMC_BASE + g_p[PSMC_OFF];
    stage_src(SRAM + B_SMC_SRC, n, 0x70u);
    stage_dst_not(SRAM + B_SMC_DST, n, 0x70u);
    mark('G', "smc_w");
    uint32_t st_w = dma_run(SRAM + B_SMC_SRC, smc, len, 1, 1);
    uint32_t pre_w = g_pre, ec_w = rd(SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    dma_clear();
    mark('G', "smc_r");
    uint32_t st_r = dma_run(smc, SRAM + B_SMC_DST, len, 1, 1);
    uint32_t pre_r = g_pre, ec_r = rd(SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    dma_clear();
    uint32_t h = FNV0, bad = 0, x = seed_of(0x70u);
    for (uint32_t i = 0; i < n; i++) {
        uint32_t v = rd(SRAM + B_SMC_DST + 4u * i);
        h = fnv(h, v);
        if (v != lcg(&x)) bad++;
    }
    mark('C', "smc_cpu");
    uint32_t cpu = rd(smc);
    rec("SMC");
    kv("fuse", fs);
    kv("polls", polls);
    kv("addr", smc);
    kv("len", len);
    kv("w_pre", pre_w);
    kv("w_st", st_w);
    kv("w_ec", ec_w);
    kv("r_pre", pre_r);
    kv("r_st", st_r);
    kv("r_ec", ec_r);
    kv("nbad", bad);
    kv("dsum", h);
    kv("cpu", cpu);
    end();
}

// ---- Step 10: not-connected targets, interrupt-paced ----
static volatile uint32_t g_fired, g_isr_st, g_isr_ec;

void __attribute__((interrupt("machine"))) dma_nc_isr(void) {
    g_isr_st = rd(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
    g_isr_ec = rd(SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    g_fired = 1u;
    wr(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, ST3);
    __asm__ volatile("fence" ::: "memory");
}

// Returns 0 done, 1 error, 2 timeout.
static uint32_t nc_run(uint32_t src, uint32_t dst) {
    dma_prep(src, dst, 4u, 1, 1);
    g_fired = 0u;
    g_isr_st = 0u;
    g_isr_ec = 0u;
    pic_enable_interrupts();
    dma_go();
    // Bounded wait: a missed interrupt ends in a named failure, not a hang.
    for (uint32_t t = 0; t < IRQ_WAIT_ITERS && !g_fired; t++) {
    }
    pic_disable_interrupts();
    if (!g_fired) {
        sep_mbx_puts("FAIL: DMA not-connected leg: done/error interrupt did not fire, src=");
        sep_mbx_puthex(src);
        sep_mbx_puts(" dst=");
        sep_mbx_puthex(dst);
        sep_mbx_putc('\n');
        g_err++;
        return 2u;
    }
    return (g_isr_st & SECURE_DMA__STATUS__ERROR_bm) ? 1u : 0u;
}

static void nc_rec(const char *tgt, uint32_t endc, uint32_t extra_k, uint32_t extra_v,
                   uint32_t dst_v) {
    rec("NC");
    sep_mbx_puts(" tgt=");
    sep_mbx_puts(tgt);
    kv("end", endc);
    kv("pre", g_pre);
    kv("st", g_isr_st);
    kv("ec", g_isr_ec);
    kv("dst", dst_v);
    if (extra_k) kv("src_v", extra_v);
    end();
}

static void nc_legs(void) {
    mark('C', "nc_ctl");
    uint32_t rom0 = rd(ROM_BASE);
    uint32_t csr0 = rd(DMA_CSR_WORD);
    rec("NCCTL");
    kv("rom", rom0);
    kv("csr", csr0);
    end();

    pic_register_handler(EXT_INT_DMA_DONE, dma_nc_isr);
    pic_register_handler(EXT_INT_DMA_ERROR, dma_nc_isr);
    pic_set_gateway(EXT_INT_DMA_DONE, 0, 0);
    pic_set_gateway(EXT_INT_DMA_ERROR, 0, 0);
    pic_set_priority(EXT_INT_DMA_DONE, 1);
    pic_set_priority(EXT_INT_DMA_ERROR, 1);
    pic_enable_source(EXT_INT_DMA_DONE);
    pic_enable_source(EXT_INT_DMA_ERROR);

    uint32_t d = SRAM + B_NC;
    uint32_t stage = ~rom0;
    if (stage == csr0) stage ^= 2u;
    int timed_out = 0;

    // Boot ROM base as the source.
    wr(d, stage);
    mark('G', "nc_rom_src");
    uint32_t e = nc_run(ROM_BASE, d);
    nc_rec("rom_src", e, 1, rom0, rd(d));
    if (e == 2u)
        timed_out = 1;
    else
        recovery("nc_rom_src");

    // Boot ROM base as the destination.
    if (!timed_out) {
        stage_src(SRAM + B_NC + 0x10u, 1u, 0x80u);
        mark('G', "nc_rom_dst");
        e = nc_run(SRAM + B_NC + 0x10u, ROM_BASE);
        nc_rec("rom_dst", e, 0, 0, 0);
        if (e == 2u)
            timed_out = 1;
        else
            recovery("nc_rom_dst");
    }

    // A DMA CSR word as the source.
    if (!timed_out) {
        wr(d, stage);
        mark('G', "nc_csr_src");
        e = nc_run(DMA_CSR_WORD, d);
        nc_rec("dma_csr_src", e, 1, csr0, rd(d));
        if (e == 2u)
            timed_out = 1;
        else
            recovery("nc_csr_src");
    }

    pic_disable_interrupts();
    pic_disable_source(EXT_INT_DMA_DONE);
    pic_disable_source(EXT_INT_DMA_ERROR);

    mark('C', "nc_ctl_end");
    rec("NCCTL2");
    kv("rom", rd(ROM_BASE));
    kv("csr", rd(DMA_CSR_WORD));
    kv("timed_out", (uint32_t)timed_out);
    end();
}

int main(void) {
    sep_outbound_filter_init();
    sep_mbx_puts("SEP DMA endpoint matrix test\n");
    if (g_p[P_MAGIC] != P_MAGIC_WORD) {
        sep_mbx_puts("FAIL: parameter block magic\n");
        return 1;
    }
    rec("PARAMS");
    kv("seed", g_p[P_SEED]);
    kv("order", g_p[P_ORDER]);
    kv("form", g_p[P_FORM]);
    kv("smu", g_p[PSMU]);
    kv("smc_off", g_p[PSMC_OFF]);
    end();

    dma_init();

    for (uint32_t k = 0; k < 4u; k++) {
        switch ((g_p[P_ORDER] >> (4u * k)) & 0xFu) {
        case 0:
            pair_sram_to_scratch();
            break;
        case 1:
            pair_scratch_to_sram();
            break;
        case 2:
            pair_reg_to_sram(2, WDT_REGWEN, WDT_REGWEN_SET, g_p[P2_LEN], g_p[P2_SRAM],
                             "pair_wdt_sram");
            break;
        case 3:
            pair_reg_to_sram(3, AES_AUX_REGWEN, AES_AUX_REGWEN_SET, g_p[P3_LEN], g_p[P3_SRAM],
                             "pair_aes_sram");
            break;
        default:
            sep_mbx_puts("FAIL: bad pair order\n");
            g_err++;
        }
    }
    direct_copy();
    ext_legs();
    alias_legs();
    outbound_legs();
    stack_leg();
    reg_legs();
    smc_legs();
    nc_legs();
    mark('C', "end");
    sep_mbx_puts("DONE\n");
    return g_err;
}
