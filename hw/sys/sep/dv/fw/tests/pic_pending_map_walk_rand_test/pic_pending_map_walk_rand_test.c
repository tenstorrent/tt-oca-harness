// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP PIC pending map walk. The CPU drives the PIC map sources, the FIFO-empty
// sources, the crypto and DMA alerts, the gateway cells and the boundary input,
// and prints every meip read. mstatus.MIE stays 0 for the whole leaf, so meip
// is the observation. The cocotb test sep_pic_pending_map_walk_rand_test
// patches the seeded values into g_p, samples the vector probe, the SPI irq
// field, the crypto alert pulse tap and the PIC read-data tap at the "REQ"
// lines, and grades every check from those samples and the records below.
//
// Console lines (sep_console_rec.h shapes; the host parses the k=v fields):
//   M G|C <leg>               leg markers (graded window)
//   REQ m t=<tag>             the host takes a mark of its bit watchers
//   REQ vec t=<tag>           the host samples the vector and the SPI irq field
//   REQ stall on=<0|1>        the host drives hmac_fifo_drain_stall_i
//   REQ ext step=<k> n=<n>    the host drives n bits of sep_ext_interrupts_i
//   REQ win <op>=<0|1>        the host opens or closes a per-clock vector window
//   MEIP t=<tag> w0=.. w7=..  the eight meip words of one read
//   FILL ip=.. full=.. ...    the FIFO-empty set-up of one IP
//   FE ip=.. ...              the FIFO-empty enable-clear cell of one IP
//   SINGLE src=.. meipN=..    a single-source read
//   ALERT k=.. meip1=..       the meip[1] read after one alert kind
//   IDLE-STATUS when=.. ...   the engine statuses of the idle window
//   GW src=.. cell=.. ...     one gateway cell
//   GWCLR v=.. held=.. after=..   one value of the clear-value corner
//   HOLD src=.. ...           the level hold
//   CLRIDLE src=.. ...        the idle clear
// A REQ is followed by a spin, so the host acts before the next bus access.

#include <stdint.h>

// The AES runs are controls; their waits stay short.
#define AES_WAIT_TIMEOUT 4000
#include "aes_test_util.h"
#include "och_sep_common.h"
#include "sep.h"
#include "sep_axil_mailbox.h"
#include "sep_console_rec.h"
#include "sep_entropy.h"
#include "sep_hmac.h"
#include "sep_kmac.h"
#include "sep_mailbox.h"
#include "sep_outbound_filter.h"
#include "sep_pic.h"

// ---- Parameter block (the host patches it; keep in step with the test) ----
#define P_MAGIC_WORD 0x3A1C9E21u
enum {
    P_MAGIC,
    P_SEED,
    P_ORD1,               // 4 words: pass 1 order, 6 map indexes of 5 bits per word
    P_ORD2 = P_ORD1 + 4,  // 4 words: pass 2 order
    P_GAP1 = P_ORD2 + 4,  // 6 words: pass 1 gaps (clocks), 4 of 8 bits per word
    P_GAP2 = P_GAP1 + 6,  // 6 words: pass 2 gaps
    P_AORD = P_GAP2 + 6,  // 2 words: alert kind order, 8 of 4 bits per word
    P_APAIR = P_AORD + 2, // pair kinds k1 [3:0], k2 [7:4], gap [15:8]
    P_AKIND,              // map-pass kind p1 [3:0], p2 [7:4], single [11:8], masked [15:12]
    P_NORD,               // native order: 5 of 3 bits
    P_MASK1,              // pass 1 IP enable mask: bit s for PIC source s
    P_GWCELL,             // gateway cell (2 bits) of the gateway sources, in GW_SRC order
    P_GWORD,              // 2 words: gateway cell order, 8 of 4 bits per word
    P_CLRX = P_GWORD + 2, // drawn meigwclr value
    P_EXT,                // boundary bits b1 [7:0], b2 [15:8], b3 [23:16]
    P_IDLE0,              // meip[0] bits of the excluded idle sources
    P_IDLE1,              // meip[1] bits of the excluded idle sources
    P_HOLD,               // hold window (clocks)
    P_SETTLE,             // settle window (clocks)
    P_FILL,               // bounded number of message-FIFO writes
    P_COUNT
};

volatile uint32_t g_p[P_COUNT] = {
    P_MAGIC_WORD,
    1u,
    // pass 1 order 0..23, pass 2 order 0..23 (directed default)
    0x0A418820u,
    0x16A4A0E6u,
    0x2307B9ACu,
    0x2F6B5272u,
    0x0A418820u,
    0x16A4A0E6u,
    0x2307B9ACu,
    0x2F6B5272u,
    0u,
    0u,
    0u,
    0u,
    0u,
    0u,
    0u,
    0u,
    0u,
    0u,
    0u,
    0u,
    0x76543210u,
    0x00000A98u,
    0x00000310u,
    0x00000000u,
    0x00004688u,
    0x7FFFC000u,
    0x00E4E4E4u,
    0x76543210u,
    0x0000BA98u,
    0x5A5A5A5Au,
    0x00030100u,
    0x0001A000u,
    0x000000E0u,
    2000u,
    64u,
    64u,
};

// ---- Map sources (index = order of this table) ----
enum { K_MBX, K_EVT, K_FE, K_DMA_ALERT, K_ALERT };
struct src {
    uint8_t id;
    uint8_t kind;
    uint8_t mbx; // mailbox index for K_MBX
    uint32_t st, en, tst, bit;
};

#define HM(r) SEP_TOP_HMAC_INTR_##r##_BASE_ADDR
#define KM(r) SEP_TOP_KMAC_INTR_##r##_BASE_ADDR
#define CS(r) SEP_TOP_CSRNG_INTR_##r##_BASE_ADDR
#define ED(r) SEP_TOP_EDN_INTR_##r##_BASE_ADDR
#define OT(r) SEP_TOP_OTBN_INTR_##r##_BASE_ADDR
#define SP(r) SEP_TOP_SPI_CONTROLLER_INTR_##r##_BASE_ADDR
#define IPREGS(m) m(STATE), m(ENABLE), m(TEST)

#define N_MAP 24
static const struct src k_map[N_MAP] = {
    {1, K_MBX, 0, 0, 0, 0, 0},
    {2, K_MBX, 1, 0, 0, 0, 0},
    {3, K_MBX, 2, 0, 0, 0, 0},
    {4, K_MBX, 3, 0, 0, 0, 0},
    {5, K_MBX, 4, 0, 0, 0, 0},
    {6, K_MBX, 5, 0, 0, 0, 0},
    {7, K_MBX, 6, 0, 0, 0, 0},
    {8, K_MBX, 7, 0, 0, 0, 0},
    {12, K_DMA_ALERT, 0, 0, 0, 0, 0},
    {14, K_EVT, 0, IPREGS(SP), SPI_CONTROLLER__INTR_STATE__ERROR_bm},
    {18, K_EVT, 0, IPREGS(HM), HMAC__INTR_STATE__HMAC_DONE_bm},
    {19, K_FE, 0, IPREGS(HM), HMAC__INTR_STATE__FIFO_EMPTY_bm},
    {20, K_EVT, 0, IPREGS(HM), HMAC__INTR_STATE__HMAC_ERR_bm},
    {21, K_EVT, 0, IPREGS(KM), KMAC__INTR_STATE__KMAC_DONE_bm},
    {22, K_FE, 0, IPREGS(KM), KMAC__INTR_STATE__FIFO_EMPTY_bm},
    {23, K_EVT, 0, IPREGS(KM), KMAC__INTR_STATE__KMAC_ERR_bm},
    {24, K_EVT, 0, IPREGS(CS), CSRNG__INTR_STATE__CS_CMD_REQ_DONE_bm},
    {25, K_EVT, 0, IPREGS(CS), CSRNG__INTR_STATE__CS_ENTROPY_REQ_bm},
    {26, K_EVT, 0, IPREGS(CS), CSRNG__INTR_STATE__CS_HW_INST_EXC_bm},
    {27, K_EVT, 0, IPREGS(CS), CSRNG__INTR_STATE__CS_FATAL_ERR_bm},
    {28, K_EVT, 0, IPREGS(ED), EDN__INTR_STATE__EDN_CMD_REQ_DONE_bm},
    {29, K_EVT, 0, IPREGS(ED), EDN__INTR_STATE__EDN_FATAL_ERR_bm},
    {30, K_EVT, 0, IPREGS(OT), OTBN__INTR_STATE__DONE_bm},
    {33, K_ALERT, 0, 0, 0, 0, 0},
};
#define IDX_SRC24 16
#define IDX_HMAC_FE 11
#define IDX_KMAC_FE 14

// The six IPs whose INTR_ENABLE the map passes write.
static const uint32_t k_ip_en[6] = {HM(ENABLE), KM(ENABLE), CS(ENABLE),
                                    ED(ENABLE), OT(ENABLE), SP(ENABLE)};
static const uint32_t k_ip_st[6] = {HM(STATE), KM(STATE), CS(STATE),
                                    ED(STATE), OT(STATE), SP(STATE)};

// ---- Alert kinds (receiver index ranges: HMAC [0], OTBN [2:1], AES [4:3],
// KMAC [6:5], CSRNG [8:7], EDN [10:9]) ----
#define N_ALERT 11
static const uint32_t k_alert_reg[N_ALERT] = {
    SEP_TOP_HMAC_ALERT_TEST_BASE_ADDR,  SEP_TOP_OTBN_ALERT_TEST_BASE_ADDR,
    SEP_TOP_OTBN_ALERT_TEST_BASE_ADDR,  SEP_TOP_AES_ALERT_TEST_BASE_ADDR,
    SEP_TOP_AES_ALERT_TEST_BASE_ADDR,   SEP_TOP_KMAC_ALERT_TEST_BASE_ADDR,
    SEP_TOP_KMAC_ALERT_TEST_BASE_ADDR,  SEP_TOP_CSRNG_ALERT_TEST_BASE_ADDR,
    SEP_TOP_CSRNG_ALERT_TEST_BASE_ADDR, SEP_TOP_EDN_ALERT_TEST_BASE_ADDR,
    SEP_TOP_EDN_ALERT_TEST_BASE_ADDR,
};
static const uint32_t k_alert_bit[N_ALERT] = {
    HMAC__ALERT_TEST__FATAL_FAULT_bm,
    OTBN__ALERT_TEST__FATAL_bm,
    OTBN__ALERT_TEST__RECOV_bm,
    AES__ALERT_TEST__RECOV_CTRL_UPDATE_ERR_bm,
    AES__ALERT_TEST__FATAL_FAULT_bm,
    KMAC__ALERT_TEST__FATAL_FAULT_ERR_bm,
    KMAC__ALERT_TEST__RECOV_OPERATION_ERR_bm,
    CSRNG__ALERT_TEST__FATAL_ALERT_bm,
    CSRNG__ALERT_TEST__RECOV_ALERT_bm,
    EDN__ALERT_TEST__FATAL_ALERT_bm,
    EDN__ALERT_TEST__RECOV_ALERT_bm,
};

// ---- Native error sources and the alert kind of the same block ----
#define N_NATIVE 5
static const uint8_t k_native_map[N_NATIVE] = {12, 15, 19, 21, 22}; // k_map indexes: 20 23 27 29 30
static const uint8_t k_native_alert[N_NATIVE] = {0, 6, 8, 10, 2};

// ---- Gateway sources (index = order of the cell word) ----
#define N_GW 12
static const uint8_t k_gw_map[N_GW] = {0, 1, 2, 3, 4, 5, 6, 7, 10, 13, 16, 20}; // 1..8 18 21 24 28
#define CELL_LH 0u
#define CELL_LL 1u
#define CELL_EH 2u
#define CELL_EL 3u

#define MBX_OUT(m, reg) \
    sep_axil_mbox_ch((m), SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_##reg##_BASE_ADDR)
#define MBX_IN(m, reg) \
    sep_axil_mbox_ch((m), SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_##reg##_BASE_ADDR)

#define REQ_SPIN 96u
#define WAIT_ITERS 20000u
#define DRIVE_WORD 0x9E21DA7Au
#define N_MEIP 8u
#define FIRST_BAND 44u
#define LAST_SRC 255u
#define SRC17 17u

static int g_err;
static uint32_t g_ip_en[6]; // INTR_ENABLE values the map pass wrote

static inline uint32_t rd(uint32_t a) {
    return *(volatile uint32_t *)a;
}
static inline void wr(uint32_t a, uint32_t v) {
    *(volatile uint32_t *)a = v;
    __asm__ volatile("fence" ::: "memory");
}
static inline uint32_t cycles(void) {
    uint32_t c;
    __asm__ volatile("csrr %0, mcycle" : "=r"(c));
    return c;
}
static void wait_clk(uint32_t n) {
    uint32_t t0 = cycles();
    while ((uint32_t)(cycles() - t0) < n) {
    }
}
static uint32_t field(uint32_t base, uint32_t i, uint32_t bits) {
    uint32_t per = 32u / bits;
    return (g_p[base + i / per] >> (bits * (i % per))) & ((1u << bits) - 1u);
}

static void fail(const char *what) {
    sep_mbx_puts("FAIL: ");
    sep_mbx_puts(what);
    rec_end();
    g_err++;
}

// ---- Host requests ----
static void req_tag(const char *what, const char *tag) {
    rec_req(what);
    rec_str("t", tag);
    rec_end();
    rec_spin(REQ_SPIN);
}
static void req_tag_n(const char *what, const char *tag, uint32_t n) {
    rec_req(what);
    sep_mbx_puts(" t=");
    sep_mbx_puts(tag);
    rec_dec(n);
    rec_end();
    rec_spin(REQ_SPIN);
}
static void req_kv(const char *what, const char *key, uint32_t v) {
    rec_req(what);
    rec_hex(key, v);
    rec_end();
    rec_spin(REQ_SPIN);
}

static void dump_meip(const char *tag) {
    uint32_t w[N_MEIP];
    for (uint32_t i = 0; i < N_MEIP; i++) {
        w[i] = pic_read_meip(i);
    }
    sep_mbx_puts("MEIP");
    rec_str("t", tag);
    static const char *k[N_MEIP] = {"w0", "w1", "w2", "w3", "w4", "w5", "w6", "w7"};
    for (uint32_t i = 0; i < N_MEIP; i++) {
        rec_hex(k[i], w[i]);
    }
    rec_end();
}

static uint32_t meip_bit(uint32_t src) {
    return pic_source_pending(src);
}

static uint32_t band_count(void) {
    uint32_t n = 0;
    for (uint32_t w = 1; w < N_MEIP; w++) {
        uint32_t v = pic_read_meip(w);
        if (w == 1u) {
            v &= ~((1u << (FIRST_BAND - 32u)) - 1u);
        }
        while (v) {
            n += v & 1u;
            v >>= 1;
        }
    }
    return n;
}

// ---- Source drive recipe ----
static void mbx_arm(uint32_t m) {
    wr(MBX_IN(m, IRQS), SEP_AXIL_MBOX_IRQ_ALL);
    wr(MBX_IN(m, WIRQT), 0u);
    wr(MBX_IN(m, IRQEN), SEP_AXIL_MBOX_IRQ_WRITE);
}
static void assert_src(const struct src *s, uint32_t alert_kind) {
    switch (s->kind) {
    case K_MBX:
        wr(MBX_IN(s->mbx, WRITE_DATA), DRIVE_WORD + s->id);
        break;
    case K_EVT:
        wr(s->tst, s->bit);
        break;
    case K_FE:
        wr(s->en, rd(s->en) | s->bit);
        break;
    case K_DMA_ALERT:
        wr(SEP_TOP_SECURE_DMA_ALERT_TEST_BASE_ADDR, SECURE_DMA__ALERT_TEST__FATAL_FAULT_bm);
        break;
    default:
        wr(k_alert_reg[alert_kind], k_alert_bit[alert_kind]);
        break;
    }
}
static void release_src(const struct src *s) {
    switch (s->kind) {
    case K_MBX:
        (void)rd(MBX_OUT(s->mbx, READ_DATA));
        wr(MBX_IN(s->mbx, IRQS), SEP_AXIL_MBOX_IRQ_WRITE);
        break;
    case K_EVT:
        wr(s->tst, 0u);
        wr(s->st, s->bit);
        break;
    case K_FE:
        wr(s->en, rd(s->en) & ~s->bit);
        break;
    case K_DMA_ALERT:
        pic_write_meigwclr(s->id, 0u);
        break;
    default:
        pic_write_meigwclr(s->id, 0u);
        break;
    }
}

// ---- FIFO-empty set-up ----
static int g_kmac_graded;

static void hmac_start(void) {
    wr(SEP_TOP_HMAC_CFG_BASE_ADDR,
       HMAC__CFG__SHA_EN_bm | HMAC__CFG__DIGEST_SWAP_bm |
           (SEP_HMAC_DIGEST_SIZE_SHA2_256 << HMAC__CFG__DIGEST_SIZE_bp));
    wr(SEP_TOP_HMAC_CMD_BASE_ADDR, HMAC__CMD__HASH_START_bm);
}
// The done bit can hold an earlier INTR_TEST event, so it is cleared before Process.
static int hmac_finish(uint32_t iters) {
    wr(HM(STATE), HMAC__INTR_STATE__HMAC_DONE_bm);
    wr(SEP_TOP_HMAC_CMD_BASE_ADDR, HMAC__CMD__HASH_PROCESS_bm);
    uint32_t t = iters;
    while (!(rd(SEP_TOP_HMAC_STATUS_BASE_ADDR) & HMAC__STATUS__HMAC_IDLE_bm) && --t > 0u) {
    }
    t = iters;
    while (!(rd(HM(STATE)) & HMAC__INTR_STATE__HMAC_DONE_bm) && --t > 0u) {
    }
    int ok = (rd(HM(STATE)) & HMAC__INTR_STATE__HMAC_DONE_bm) != 0u;
    if (!ok) {
        rec_ctl("HMAC-FINISH");
        rec_hex("status", rd(SEP_TOP_HMAC_STATUS_BASE_ADDR));
        rec_hex("err", rd(SEP_TOP_HMAC_ERR_CODE_BASE_ADDR));
        rec_hex("intr_state", rd(HM(STATE)));
        rec_end();
    }
    wr(HM(STATE), HMAC__INTR_STATE__HMAC_DONE_bm);
    return ok;
}
static void kmac_start(void) {
    uint32_t t = WAIT_ITERS;
    while (!(rd(SEP_TOP_KMAC_STATUS_BASE_ADDR) & KMAC__STATUS__SHA3_IDLE_bm) && --t > 0u) {
    }
    uint32_t cfg = (SEP_KMAC_KSTRENGTH_L256 << KMAC__CFG_SHADOWED__KSTRENGTH_bp) |
                   (SEP_KMAC_MODE_SHA3 << KMAC__CFG_SHADOWED__MODE_bp) |
                   (SEP_KMAC_ENTROPY_MODE_SW << KMAC__CFG_SHADOWED__ENTROPY_MODE_bp);
    sep_kmac_cfg_write(cfg);
    sep_kmac_cfg_write(cfg | KMAC__CFG_SHADOWED__ENTROPY_READY_bm);
    for (int i = 0; i < SEP_KMAC_NUM_SEED_WORDS; i++) {
        wr(SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0x6B6D6163u + (uint32_t)i);
    }
    wr(SEP_TOP_KMAC_CMD_BASE_ADDR, SEP_KMAC_CMD_START);
}
static int kmac_finish(void) {
    wr(KM(STATE), KMAC__INTR_STATE__KMAC_DONE_bm);
    wr(SEP_TOP_KMAC_CMD_BASE_ADDR, SEP_KMAC_CMD_PROCESS);
    uint32_t t = WAIT_ITERS;
    while (!(rd(KM(STATE)) & KMAC__INTR_STATE__KMAC_DONE_bm) && --t > 0u) {
    }
    int ok = (rd(KM(STATE)) & KMAC__INTR_STATE__KMAC_DONE_bm) != 0u;
    if (!ok) {
        rec_ctl("KMAC-FINISH");
        rec_hex("status", rd(SEP_TOP_KMAC_STATUS_BASE_ADDR));
        rec_hex("err", rd(SEP_TOP_KMAC_ERR_CODE_BASE_ADDR));
        rec_hex("intr_state", rd(KM(STATE)));
        rec_end();
    }
    wr(KM(STATE), KMAC__INTR_STATE__KMAC_DONE_bm);
    wr(SEP_TOP_KMAC_CMD_BASE_ADDR, SEP_KMAC_CMD_DONE);
    t = WAIT_ITERS;
    while (!(rd(SEP_TOP_KMAC_STATUS_BASE_ADDR) & KMAC__STATUS__SHA3_IDLE_bm) && --t > 0u) {
    }
    return ok;
}

// Fill the message FIFO; return the number of writes when STATUS shows fifo_full, else 0.
static uint32_t fill(uint32_t fifo, uint32_t status, uint32_t full_bm) {
    for (uint32_t i = 1; i <= g_p[P_FILL]; i++) {
        wr(fifo, 0xF1F0F1F0u ^ i);
        if (rd(status) & full_bm) {
            return i;
        }
    }
    return 0u;
}
static uint32_t wait_set(uint32_t addr, uint32_t bm) {
    uint32_t t = WAIT_ITERS;
    while (!(rd(addr) & bm) && --t > 0u) {
    }
    return (rd(addr) & bm) ? 1u : 0u;
}

static void fifo_setup(void) {
    // HMAC (source 19): the drain stall makes the FIFO reach fifo_full.
    req_kv("stall", "on", 1u);
    hmac_start();
    uint32_t n = fill(SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR, SEP_TOP_HMAC_STATUS_BASE_ADDR,
                      HMAC__STATUS__FIFO_FULL_bm);
    req_kv("stall", "on", 0u);
    uint32_t emp = n ? wait_set(SEP_TOP_HMAC_STATUS_BASE_ADDR, HMAC__STATUS__FIFO_EMPTY_bm) : 0u;
    sep_mbx_puts("FILL");
    rec_str("ip", "hmac");
    rec_num("full", n ? 1u : 0u);
    rec_num("writes", n);
    rec_num("empty", emp);
    rec_hex("status", rd(SEP_TOP_HMAC_STATUS_BASE_ADDR));
    rec_end();

    // KMAC (source 22): no drain stall exists; graded only when fifo_full shows.
    kmac_start();
    n = fill(SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR, SEP_TOP_KMAC_STATUS_BASE_ADDR,
             KMAC__STATUS__FIFO_FULL_bm);
    emp = n ? wait_set(SEP_TOP_KMAC_STATUS_BASE_ADDR, KMAC__STATUS__FIFO_EMPTY_bm) : 0u;
    uint32_t ist = rd(KM(STATE));
    g_kmac_graded = n != 0u;
    if (!g_kmac_graded) {
        sep_mbx_puts("CTRL-MISSING ip=kmac fifo_full=0\n");
    }
    sep_mbx_puts("FILL");
    rec_str("ip", "kmac");
    rec_num("full", n ? 1u : 0u);
    rec_num("writes", n);
    rec_num("empty", emp);
    rec_hex("status", rd(SEP_TOP_KMAC_STATUS_BASE_ADDR));
    rec_hex("intr_state", ist);
    rec_end();
}

// ---- Map pass ----
static void program_map(void) {
    for (uint32_t i = 0; i < N_MAP; i++) {
        uint32_t id = k_map[i].id;
        pic_set_priority(id, 1u);
        pic_enable_source(id);
        pic_set_gateway(id, (id == 12u || id == 33u) ? 1u : 0u, 0u);
    }
    for (uint32_t m = 0; m < 8u; m++) {
        mbx_arm(m);
    }
}

static void write_enables(int pass) {
    uint32_t mask = g_p[P_MASK1];
    for (uint32_t k = 0; k < 6u; k++) {
        g_ip_en[k] = 0u;
    }
    for (uint32_t i = 0; i < N_MAP; i++) {
        const struct src *s = &k_map[i];
        if (s->kind != K_EVT) {
            continue;
        }
        uint32_t on = (mask >> s->id) & 1u;
        if (pass == 2) {
            on ^= 1u;
        }
        for (uint32_t k = 0; k < 6u; k++) {
            if (k_ip_en[k] == s->en && on) {
                g_ip_en[k] |= s->bit;
            }
        }
    }
    for (uint32_t k = 0; k < 6u; k++) {
        wr(k_ip_en[k], g_ip_en[k]);
    }
}

static void ctl_fifo_empty(const char *tag) {
    rec_ctl("FIFO-EMPTY");
    rec_str("t", tag);
    rec_str("intr_state_hmac", "na");
    rec_hex("intr_enable_hmac", rd(HM(ENABLE)));
    rec_hex("intr_state_kmac", rd(KM(STATE)));
    rec_hex("intr_enable_kmac", rd(KM(ENABLE)));
    rec_end();
}

static void map_assert(int pass) {
    uint32_t ord = pass == 1 ? P_ORD1 : P_ORD2;
    uint32_t gap = pass == 1 ? P_GAP1 : P_GAP2;
    uint32_t kind = (g_p[P_AKIND] >> (pass == 1 ? 0u : 4u)) & 0xFu;
    req_tag_n("m", "p", (uint32_t)pass);
    for (uint32_t i = 0; i < N_MAP; i++) {
        const struct src *s = &k_map[field(ord, i, 5u)];
        if (pass == 2 && s->kind == K_FE) {
            continue;
        }
        assert_src(s, kind);
        wait_clk(field(gap, i, 8u));
    }
    wait_clk(g_p[P_SETTLE]);
    req_tag_n("vec", "p", (uint32_t)pass);
    dump_meip(pass == 1 ? "p1" : "p2");
    if (pass == 1) {
        ctl_fifo_empty("p1");
    }
}

static void map_release(int pass) {
    for (uint32_t i = 0; i < N_MAP; i++) {
        const struct src *s = &k_map[i];
        if (s->kind == K_FE) {
            continue; // released by the enable clear
        }
        release_src(s);
    }
    wait_clk(g_p[P_SETTLE]);
    req_tag_n("vec", "r", (uint32_t)pass);
    dump_meip(pass == 1 ? "r1" : "r2");
}

// The enable-clear cell of one FIFO-empty source, then the message completes.
static void fe_cell(const char *ip, uint32_t src, uint32_t en, uint32_t bit, int graded) {
    req_tag("vec", ip[0] == 'h' ? "feh0" : "fek0");
    uint32_t before = meip_bit(src);
    ctl_fifo_empty(ip);
    wr(en, rd(en) & ~bit);
    wait_clk(g_p[P_SETTLE]);
    req_tag("vec", ip[0] == 'h' ? "feh1" : "fek1");
    uint32_t after = meip_bit(src);
    sep_mbx_puts("FE");
    rec_str("ip", ip);
    rec_num("src", src);
    rec_num("graded", (uint32_t)graded);
    rec_num("meip_before", before);
    rec_num("meip_after", after);
    rec_end();
}

// ---- Alerts ----
static void alert_kind(uint32_t k) {
    req_tag_n("m", "aq", k);
    wait_clk(g_p[P_SETTLE]);
    req_tag_n("m", "aw", k);
    wr(k_alert_reg[k], k_alert_bit[k]);
    wait_clk(g_p[P_SETTLE]);
    req_tag_n("m", "ae", k);
    sep_mbx_puts("ALERT");
    rec_num("k", k);
    rec_hex("meip1", pic_read_meip(1));
    rec_end();
    pic_write_meigwclr(33u, 0u);
}

static void native_leg(uint32_t n) {
    const struct src *s = &k_map[k_native_map[n]];
    uint32_t k = k_native_alert[n];
    wr(s->en, rd(s->en) | s->bit);
    req_tag_n("m", "na", s->id);
    wr(s->tst, s->bit);
    wait_clk(g_p[P_HOLD]);
    req_tag_n("vec", "nb", s->id);
    wr(k_alert_reg[k], k_alert_bit[k]);
    wait_clk(g_p[P_SETTLE]);
    req_tag_n("m", "nc", s->id);
    wr(s->tst, 0u);
    wr(s->st, s->bit);
    wr(s->en, rd(s->en) & ~s->bit);
    pic_write_meigwclr(33u, 0u);
}

// ---- OTBN program: a counted loop that outlasts the hold window ----
static const uint32_t k_otbn_loop[] = {
    0x00004137u, // lui  x2, 0x4
    0xFFF10113u, // addi x2, x2, -1
    0xFE011EE3u, // bne  x2, x0, -4
    0x00000073u, // ecall
};
#define OTBN_CMD_EXECUTE 0xD8u
#define OTBN_STATUS_IDLE 0x00u

static void otbn_start(void) {
    uint32_t t = WAIT_ITERS;
    while (rd(SEP_TOP_OTBN_STATUS_BASE_ADDR) != OTBN_STATUS_IDLE && --t > 0u) {
    }
    for (uint32_t i = 0; i < sizeof(k_otbn_loop) / sizeof(k_otbn_loop[0]); i++) {
        wr(SEP_TOP_OTBN_IMEM_BASE_ADDR + 4u * i, k_otbn_loop[i]);
    }
    wr(SEP_TOP_OTBN_CMD_BASE_ADDR, OTBN_CMD_EXECUTE);
}

// ---- AES ----
static const uint32_t k_aes_key[4] = {0x03020100u, 0x07060504u, 0x0B0A0908u, 0x0F0E0D0Cu};
static const uint32_t k_aes_iv[4] = {0u, 0u, 0u, 0u};
static const uint32_t k_aes_pt[4] = {0x33221100u, 0x77665544u, 0xBBAA9988u, 0xFFEEDDCCu};

static uint32_t aes_encrypt_one(void) {
    uint32_t out[4];
    if (configure_aes(0x1u, 0x1u, k_aes_key, k_aes_iv) != 0) {
        return 0u;
    }
    write_data_in(k_aes_pt);
    if (wait_for_output_valid() != 0) {
        return rd(SEP_TOP_AES_STATUS_BASE_ADDR);
    }
    read_data_out(out);
    (void)wait_for_idle();
    return rd(SEP_TOP_AES_STATUS_BASE_ADDR);
}

// ---- Gateway cells ----
static void gw_assert(const struct src *s) {
    assert_src(s, 0u);
}
static void gw_deassert(const struct src *s) {
    release_src(s);
}

static void gw_cell(uint32_t g) {
    const struct src *s = &k_map[k_gw_map[g]];
    uint32_t cell = (g_p[P_GWCELL] >> (2u * g)) & 3u;
    uint32_t id = s->id;
    uint32_t clr = g_p[P_CLRX];
    if (s->kind == K_EVT) {
        wr(s->en, rd(s->en) | s->bit);
    } else {
        mbx_arm(s->mbx);
    }
    pic_set_priority(id, 1u);
    pic_enable_source(id);
    pic_set_gateway(id, cell >> 1, cell & 1u);
    if (cell >> 1) {
        // The edge latch holds any earlier assertion of the source (the map
        // passes assert it in level mode); clear it with the input deasserted.
        pic_write_meigwclr(id, clr);
    }
    wait_clk(g_p[P_SETTLE]);
    uint32_t idle = meip_bit(id);
    gw_assert(s);
    wait_clk(g_p[P_SETTLE]);
    uint32_t a1 = meip_bit(id);
    gw_deassert(s);
    wait_clk(g_p[P_SETTLE]);
    uint32_t d1 = meip_bit(id);
    uint32_t c1 = 0u, a2 = 0u, c2 = 0u;
    if (cell == CELL_EH) {
        pic_write_meigwclr(id, clr);
        c1 = meip_bit(id);
    } else if (cell == CELL_EL) {
        gw_assert(s);
        wait_clk(g_p[P_SETTLE]);
        a2 = meip_bit(id);
        pic_write_meigwclr(id, clr);
        c2 = meip_bit(id);
        gw_deassert(s);
        wait_clk(g_p[P_SETTLE]);
    }
    sep_mbx_puts("GW");
    rec_num("src", id);
    rec_num("cell", cell);
    rec_hex("cfg", pic_read_gateway(id));
    rec_num("idle", idle);
    rec_num("asserted", a1);
    rec_num("deasserted", d1);
    rec_num("after_clr", c1);
    rec_num("reasserted", a2);
    rec_num("after_clr2", c2);
    rec_hex("clr_val", clr);
    rec_end();
    pic_set_gateway(id, 0u, 0u);
    if (s->kind == K_EVT) {
        wr(s->en, rd(s->en) & ~s->bit);
    }
}

static uint32_t gw_src_of_cell(uint32_t want_cell, int event) {
    for (uint32_t g = 0; g < N_GW; g++) {
        const struct src *s = &k_map[k_gw_map[g]];
        if (((g_p[P_GWCELL] >> (2u * g)) & 3u) == want_cell && (s->kind == K_EVT) == event) {
            return g;
        }
    }
    return 0u;
}

static void gwclr_corner(uint32_t g) {
    const struct src *s = &k_map[k_gw_map[g]];
    static const uint32_t vals[4] = {0x0u, 0x1u, 0x80000000u, 0xFFFFFFFFu};
    wr(s->en, rd(s->en) | s->bit);
    pic_set_gateway(s->id, 1u, 0u);
    for (uint32_t i = 0; i < 5u; i++) {
        uint32_t v = i < 4u ? vals[i] : g_p[P_CLRX];
        gw_assert(s);
        wait_clk(g_p[P_SETTLE]);
        gw_deassert(s);
        wait_clk(g_p[P_SETTLE]);
        uint32_t held = meip_bit(s->id);
        pic_write_meigwclr(s->id, v);
        uint32_t after = meip_bit(s->id);
        sep_mbx_puts("GWCLR");
        rec_num("src", s->id);
        rec_hex("v", v);
        rec_num("held", held);
        rec_num("after", after);
        rec_end();
    }
    // Idle clear on the same EH source: input deasserted, pending bit 0.
    uint32_t before = meip_bit(s->id);
    pic_write_meigwclr(s->id, g_p[P_CLRX]);
    uint32_t after = meip_bit(s->id);
    sep_mbx_puts("CLRIDLE");
    rec_num("src", s->id);
    rec_num("meip_before", before);
    rec_hex("clr_val", g_p[P_CLRX]);
    rec_num("meip_after", after);
    rec_end();
    pic_set_gateway(s->id, 0u, 0u);
    wr(s->en, rd(s->en) & ~s->bit);
}

static void level_hold(uint32_t g) {
    const struct src *s = &k_map[k_gw_map[g]];
    wr(s->en, rd(s->en) | s->bit);
    pic_set_gateway(s->id, 0u, 0u);
    gw_assert(s);
    wait_clk(g_p[P_HOLD]);
    uint32_t held = meip_bit(s->id);
    wr(s->tst, 0u);
    wr(s->st, s->bit);
    wait_clk(g_p[P_SETTLE]);
    uint32_t after = meip_bit(s->id);
    sep_mbx_puts("HOLD");
    rec_num("src", s->id);
    rec_num("meip", held);
    rec_num("after_ip_clear", after);
    rec_hex("hold_clk", g_p[P_HOLD]);
    rec_end();
    wr(s->en, rd(s->en) & ~s->bit);
}

// ---- Control source 24 ----
static const struct src *ctrl_src(void) {
    return &k_map[IDX_SRC24];
}
static void ctrl_on(void) {
    const struct src *s = ctrl_src();
    wr(s->en, rd(s->en) | s->bit);
    assert_src(s, 0u);
}
static void ctrl_off(void) {
    release_src(ctrl_src());
}

static uint32_t wait_band(uint32_t want_min, uint32_t want_zero) {
    uint32_t t = WAIT_ITERS / 16u;
    uint32_t n = band_count();
    while (t-- > 0u) {
        n = band_count();
        if (want_zero ? n == 0u : n >= want_min) {
            break;
        }
    }
    return n;
}

// Idle window: HMAC and KMAC hold an open message, OTBN runs a loop longer than
// the hold window and AES streams blocks. It runs before the FIFO-empty set-up,
// because the HMAC drain stall leaves the HMAC message unable to complete.
static void idle_window(void) {
    rec_mark(1, "alert_idle");
    req_tag("m", "ia");
    hmac_start();
    for (uint32_t i = 0; i < 4u; i++) {
        wr(SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR, 0x1D1E0000u + i);
    }
    kmac_start();
    for (uint32_t i = 0; i < 4u; i++) {
        wr(SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR, 0x1D1E1000u + i);
    }
    otbn_start();
    (void)configure_aes(0x1u, 0x1u, k_aes_key, k_aes_iv);
    write_data_in(k_aes_pt);
    (void)wait_for_input_ready();
    write_data_in(k_aes_key);
    for (int when = 0; when < 2; when++) {
        if (when == 1) {
            req_tag("m", "i0");
            wait_clk(g_p[P_HOLD]);
            req_tag("m", "i1");
        }
        sep_mbx_puts("IDLE-STATUS");
        rec_str("when", when ? "after" : "before");
        rec_hex("hmac", rd(SEP_TOP_HMAC_STATUS_BASE_ADDR));
        rec_hex("kmac", rd(SEP_TOP_KMAC_STATUS_BASE_ADDR));
        rec_hex("otbn", rd(SEP_TOP_OTBN_STATUS_BASE_ADDR));
        rec_hex("aes", rd(SEP_TOP_AES_STATUS_BASE_ADDR));
        rec_end();
    }
    uint32_t out[4];
    if (wait_for_output_valid() == 0) {
        read_data_out(out);
    }
    if (wait_for_output_valid() == 0) {
        read_data_out(out);
    }
    cleanup_aes();
    if (!hmac_finish(WAIT_ITERS)) {
        fail("HMAC idle-window message did not complete");
    }
    if (!kmac_finish()) {
        fail("KMAC idle-window message did not complete");
    }
    uint32_t t = WAIT_ITERS;
    while (rd(SEP_TOP_OTBN_STATUS_BASE_ADDR) != OTBN_STATUS_IDLE && --t > 0u) {
    }
    wr(OT(STATE), OTBN__INTR_STATE__DONE_bm);
    rec_ctl("ENGINES-DONE");
    rec_hex("otbn", rd(SEP_TOP_OTBN_STATUS_BASE_ADDR));
    rec_hex("hmac_st", rd(HM(STATE)));
    rec_hex("kmac_st", rd(KM(STATE)));
    rec_end();
}

static void print_params(void) {
    sep_mbx_puts("PARAMS");
    rec_hex("seed", g_p[P_SEED]);
    rec_hex("mask1", g_p[P_MASK1]);
    rec_hex("gwcell", g_p[P_GWCELL]);
    rec_hex("clrx", g_p[P_CLRX]);
    rec_hex("ext", g_p[P_EXT]);
    rec_hex("akind", g_p[P_AKIND]);
    rec_hex("apair", g_p[P_APAIR]);
    rec_hex("nord", g_p[P_NORD]);
    rec_end();
    sep_mbx_puts("PARAMS2");
    rec_hex("o1a", g_p[P_ORD1]);
    rec_hex("o1d", g_p[P_ORD1 + 3]);
    rec_hex("o2a", g_p[P_ORD2]);
    rec_hex("o2d", g_p[P_ORD2 + 3]);
    rec_hex("g1a", g_p[P_GAP1]);
    rec_hex("g2a", g_p[P_GAP2]);
    rec_hex("aord0", g_p[P_AORD]);
    rec_hex("gword0", g_p[P_GWORD]);
    rec_hex("idle0", g_p[P_IDLE0]);
    rec_hex("idle1", g_p[P_IDLE1]);
    rec_end();
}

int main(void) {
    sep_outbound_filter_init();
    sep_mbx_puts("SEP PIC pending map walk test\n");
    if (g_p[P_MAGIC] != P_MAGIC_WORD) {
        sep_mbx_puts("FAIL: parameter block magic\n");
        return 1;
    }
    print_params();

    // Reset baseline: no PIC write before these reads.
    rec_mark(1, "baseline");
    req_tag("vec", "reset");
    dump_meip("reset");

    // Entropy stack: AES masking and the OTBN URND draw from EDN.
    rec_mark(0, "entropy");
    int erc = sep_entropy_bringup();
    rec_ctl("ENTROPY");
    rec_hex("rc", (uint32_t)erc);
    rec_end();
    if (erc != SEP_ENTROPY_OK) {
        fail("entropy bring-up");
    }
    idle_window();

    rec_mark(1, "map_setup");
    program_map();
    write_enables(1);

    // FIFO-empty set-up of sources 19 and 22.
    fifo_setup();

    // Map pass 1, the FIFO-empty cells, the SPI cell and the release.
    map_assert(1);
    rec_mark(1, "fifo_empty");
    fe_cell("hmac", 19u, HM(ENABLE), HMAC__INTR_ENABLE__FIFO_EMPTY_bm, 1);
    fe_cell("kmac", 22u, KM(ENABLE), KMAC__INTR_ENABLE__FIFO_EMPTY_bm, g_kmac_graded);
    // The drain stall holds only the FIFO read side, so the hash engine reads
    // the FIFO head while the stall is on and the message cannot complete. The
    // completion is logged, not graded.
    uint32_t hdone = (uint32_t)hmac_finish(WAIT_ITERS / 16u);
    rec_ctl("HMAC-AFTER-STALL");
    rec_num("done", hdone);
    rec_end();
    if (!kmac_finish()) {
        fail("KMAC message did not complete");
    }

    rec_mark(1, "spi");
    wr(SP(ENABLE), rd(SP(ENABLE)) | SPI_CONTROLLER__INTR_ENABLE__ERROR_bm);
    wait_clk(g_p[P_SETTLE]);
    req_tag("vec", "spi1");
    wr(SP(TEST), 0u);
    wr(SP(STATE), SPI_CONTROLLER__INTR_STATE__ERROR_bm);
    wait_clk(g_p[P_SETTLE]);
    req_tag("vec", "spi0");

    rec_mark(1, "map_release");
    map_release(1);

    // Map pass 2: complement enables, sources 19 and 22 not driven.
    rec_mark(1, "map_p2");
    write_enables(2);
    map_assert(2);
    map_release(2);

    // Single-source reads.
    rec_mark(1, "single");
    wr(CS(ENABLE), CSRNG__INTR_ENABLE__CS_CMD_REQ_DONE_bm);
    ctrl_on();
    wait_clk(g_p[P_SETTLE]);
    sep_mbx_puts("SINGLE");
    rec_num("src", 24u);
    rec_hex("meip0", pic_read_meip(0));
    rec_end();
    ctrl_off();
    wait_clk(g_p[P_SETTLE]);
    uint32_t ks = (g_p[P_AKIND] >> 8) & 0xFu;
    wr(k_alert_reg[ks], k_alert_bit[ks]);
    wait_clk(g_p[P_SETTLE]);
    sep_mbx_puts("SINGLE");
    rec_num("src", 33u);
    rec_hex("meip1", pic_read_meip(1));
    rec_end();
    pic_write_meigwclr(33u, 0u);

    // Alert kinds, the no-write window and the pair trial.
    rec_mark(1, "alerts");
    for (uint32_t i = 0; i < N_ALERT; i++) {
        alert_kind(field(P_AORD, i, 4u));
    }
    rec_mark(1, "alert_none");
    req_tag("m", "nw0");
    wait_clk(g_p[P_HOLD]);
    req_tag("m", "nw1");
    rec_mark(1, "alert_pair");
    uint32_t k1 = g_p[P_APAIR] & 0xFu, k2 = (g_p[P_APAIR] >> 4) & 0xFu;
    req_tag("m", "pr0");
    wr(k_alert_reg[k1], k_alert_bit[k1]);
    wait_clk((g_p[P_APAIR] >> 8) & 0xFFu);
    wr(k_alert_reg[k2], k_alert_bit[k2]);
    wait_clk(g_p[P_SETTLE]);
    req_tag("m", "pr1");
    pic_write_meigwclr(33u, 0u);

    // Native errors and the OTBN done interrupt, each with an alert control.
    rec_mark(1, "native");
    for (uint32_t i = 0; i < N_NATIVE; i++) {
        native_leg((g_p[P_NORD] >> (3u * i)) & 7u);
    }

    // DMA alert on source 12.
    rec_mark(1, "alert12");
    req_tag("m", "d0");
    wait_clk(g_p[P_SETTLE]);
    req_tag("m", "d1");
    wr(SEP_TOP_SECURE_DMA_ALERT_TEST_BASE_ADDR, SECURE_DMA__ALERT_TEST__FATAL_FAULT_bm);
    wait_clk(g_p[P_SETTLE]);
    req_tag("m", "d2");
    pic_write_meigwclr(12u, 0u);

    // Masked report (logged).
    rec_mark(0, "masked");
    uint32_t km = (g_p[P_AKIND] >> 12) & 0xFu;
    wr(SEP_TOP_SECURE_DMA_ALERT_TEST_BASE_ADDR, SECURE_DMA__ALERT_TEST__FATAL_FAULT_bm);
    wr(k_alert_reg[km], k_alert_bit[km]);
    wait_clk(g_p[P_SETTLE]);
    pic_disable_source(12u);
    pic_set_priority(12u, 0u);
    pic_disable_source(33u);
    pic_set_priority(33u, 0u);
    uint32_t m0 = pic_read_meip(0), m1 = pic_read_meip(1);
    rec_obs("MASKED-VISIBLE");
    rec_num("src", 33u);
    rec_num("meie", 0u);
    rec_num("pri", 0u);
    rec_num("meip1_bit1", (m1 >> 1) & 1u);
    rec_num("src12_bit", (m0 >> 12) & 1u);
    rec_end();
    pic_enable_source(12u);
    pic_set_priority(12u, 1u);
    pic_enable_source(33u);
    pic_set_priority(33u, 1u);
    pic_write_meigwclr(12u, 0u);
    pic_write_meigwclr(33u, 0u);
    dump_meip("masked_clr");

    // Control window: source 17 and the band above 43 armed.
    rec_mark(1, "ctrl_window");
    ctrl_on();
    pic_set_priority(SRC17, 1u);
    pic_enable_source(SRC17);
    for (uint32_t s = FIRST_BAND; s <= LAST_SRC; s++) {
        pic_set_priority(s, 1u);
        pic_enable_source(s);
    }
    wait_clk(g_p[P_SETTLE]);
    req_tag("vec", "ctrl");
    dump_meip("ctrl");

    // Quiet window set-up: no IP interrupt can rise except the control bit.
    rec_mark(0, "quiet_setup");
    for (uint32_t k = 0; k < 6u; k++) {
        if (k_ip_en[k] == CS(ENABLE)) {
            wr(k_ip_en[k], CSRNG__INTR_ENABLE__CS_CMD_REQ_DONE_bm);
            wr(k_ip_st[k], ~CSRNG__INTR_STATE__CS_CMD_REQ_DONE_bm);
        } else {
            wr(k_ip_en[k], 0u);
            wr(k_ip_st[k], 0xFFFFFFFFu);
        }
    }
    rec_ctl("QUIET");
    rec_hex("en_hmac", rd(HM(ENABLE)));
    rec_hex("en_kmac", rd(KM(ENABLE)));
    rec_hex("en_csrng", rd(CS(ENABLE)));
    rec_hex("en_edn", rd(ED(ENABLE)));
    rec_hex("en_otbn", rd(OT(ENABLE)));
    rec_hex("en_spi", rd(SP(ENABLE)));
    rec_end();

    // Slotless blocks, with control source 24 asserted.
    rec_mark(1, "slotless");
    req_kv("win", "aes", 1u);
    uint32_t aes_st = aes_encrypt_one();
    req_kv("win", "aes", 0u);
    rec_ctl("AES-STATUS");
    rec_hex("status", aes_st);
    rec_end();
    req_kv("win", "otp", 1u);
    uint32_t otp = rd(SEP_TOP_SEP_EFUSE_MAP_LC_STATE_BASE_ADDR);
    wait_clk(g_p[P_SETTLE]);
    req_kv("win", "otp", 0u);
    req_kv("win", "lcc", 1u);
    uint32_t lcc = rd(SEP_TOP_SEP_LIFECYCLE_CTRL_FEAT_CTRL_BASE_ADDR);
    wait_clk(g_p[P_SETTLE]);
    req_kv("win", "lcc", 0u);
    rec_ctl("SLOTLESS-READS");
    rec_hex("otp", otp);
    rec_hex("lcc", lcc);
    rec_end();
    rec_mark(0, "slotless_end");
    ctrl_off();
    cleanup_aes();

    // Gateway cells in the drawn order.
    rec_mark(1, "gw");
    for (uint32_t i = 0; i < N_GW; i++) {
        gw_cell(field(P_GWORD, i, 4u));
    }
    rec_mark(1, "gwclr");
    gwclr_corner(gw_src_of_cell(CELL_EH, 1));
    rec_mark(1, "hold");
    level_hold(gw_src_of_cell(CELL_LH, 1));

    // Boundary input.
    rec_mark(1, "ext");
    ctrl_on();
    wait_clk(g_p[P_SETTLE]);
    dump_meip("ext_base");
    // Step k: the host drives no bit (k odd), bit b1 (k 0) or bits b2 and b3 (k 2).
    static const uint32_t want[4] = {1u, 0u, 2u, 0u};
    static const char *tags[4] = {"ext1", "ext1r", "ext2", "ext2r"};
    for (uint32_t step = 0; step < 4u; step++) {
        rec_req("ext");
        rec_num("step", step);
        rec_num("n", want[step]);
        rec_end();
        rec_spin(REQ_SPIN);
        (void)wait_band(want[step], want[step] == 0u);
        wait_clk(g_p[P_SETTLE]);
        dump_meip(tags[step]);
    }

    // Final release and clean-up of every touched entry.
    rec_mark(1, "final");
    ctrl_off();
    wr(CS(ENABLE), 0u);
    pic_write_meigwclr(12u, 0u);
    pic_write_meigwclr(33u, 0u);
    for (uint32_t i = 0; i < N_MAP; i++) {
        uint32_t id = k_map[i].id;
        pic_disable_source(id);
        pic_set_priority(id, 0u);
        pic_set_gateway(id, 0u, 0u);
    }
    pic_disable_source(SRC17);
    pic_set_priority(SRC17, 0u);
    for (uint32_t s = FIRST_BAND; s <= LAST_SRC; s++) {
        pic_disable_source(s);
        pic_set_priority(s, 0u);
    }
    for (uint32_t m = 0; m < 8u; m++) {
        wr(MBX_IN(m, IRQEN), 0u);
        wr(MBX_IN(m, IRQS), SEP_AXIL_MBOX_IRQ_ALL);
    }
    wait_clk(g_p[P_SETTLE]);
    req_tag("vec", "final");
    dump_meip("final");
    rec_mark(0, "end");
    sep_mbx_puts("DONE\n");
    return g_err;
}
