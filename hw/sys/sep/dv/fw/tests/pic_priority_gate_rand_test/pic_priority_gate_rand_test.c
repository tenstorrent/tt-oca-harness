// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// PIC delivery gates, winner by effective priority, the never value, the order
// flip, and the idle timer and software interrupt paths, from firmware.
//
// The host (cocotb/tests/cpu/sep_pic_priority_gate_rand_test.py) draws the
// rounds (priord, source set, raw priorities, gate kinds, gate-open order,
// never source) and the sweep source from the run seed and patches them into
// g_prm. Each leg starts with an M line (sep_console_rec.h). The firmware
// prints one CHK line per check; the host grades CHK-WINNER and CHK-FLIP from
// the ORDER lines.
//
//   CHK-NONE-BEFORE-PROGRAM  no delivery with the reset meie and meipl
//   CHK-GATED                no delivery through a closed gate (meie 0, never
//                            priority, mstatus.MIE 0); opening it delivers once
//   CHK-STAY-PENDING         a waiting source keeps its meip bit while the
//                            winner handler runs
//   CHK-NEVER                the never value does not deliver; effective 1 does
//   CHK-MIE-LIVE             the mie write lands (control)
//   CHK-MIP-IDLE             mip.MTIP and mip.MSIP read 0
//   CHK-NO-TIMER-TRAP        no timer or software trap is taken
//   CHK-CONTROL              one PIC delivery enters the dispatcher with
//                            mcause.interrupt set, and one ecall enters
//                            trap_dispatch through mtvec and is counted
//                            (control)
//
// Source drive recipe. A mailbox source k + 1 is driven by one CPU push into
// the inbound WRITE_DATA of mailbox k with IRQEN.wtirq 1, WIRQT 0 and an
// inbound filter allow window open over that port (all eight are opened at
// set-up and stay open), and released by a pop of the outbound READ_DATA of mailbox k and a write
// of 1 to inbound IRQS.wtirq. An OpenTitan event source is driven by its INTR_ENABLE bit and its
// INTR_TEST bit, and released by INTR_TEST 0 and a write of 1 to its INTR_STATE bit.
//
// Every external interrupt enters ext_dispatch through the fast-redirect
// vector table (every entry points to it); timer and software interrupts enter
// trap_dispatch through mtvec. Both count the trap class from mcause. The
// control leg takes one ecall through mtvec, so a trap on that path is shown to
// reach the counters that CHK-NO-TIMER-TRAP reads. The
// priority threshold CSRs (meipt, meicurpl) are set to the pass-all value of
// the current order, so only meie, meipl and mstatus.MIE gate delivery.

#include <stdint.h>

#include "filter_ctrl.h"
#include "sep.h"
#include "sep_axil_mailbox.h"
#include "sep_console_rec.h"
#include "sep_mailbox.h"
#include "sep_outbound_filter.h"
#include "sep_pic.h"

#define PRM_MAGIC 0x320B6A7Eu
#define R_MAX 6u
#define S_MAX 5u

enum {
    P_MAGIC = 0,
    P_SEED,
    P_NROUND,
    P_SWEEP,
    P_HOLD,
    P_WAIT,
    P_IDLE, // 8 words: the excluded idle bits of meip
    P_ROUND = P_IDLE + 8,
};
// Per round: priord, n, never index, src[5], raw[5], gate[5], open order[5].
enum {
    R_PRIORD = 0,
    R_N,
    R_NEVER,
    R_SRC,
    R_RAW = R_SRC + S_MAX,
    R_GATE = R_RAW + S_MAX,
    R_ORDER = R_GATE + S_MAX,
    R_WORDS = R_ORDER + S_MAX
};
#define P_WORDS (P_ROUND + R_MAX * R_WORDS)

volatile uint32_t g_prm[P_WORDS] = {
    [P_MAGIC] = PRM_MAGIC,
    [P_HOLD] = 3000u,
    [P_WAIT] = 200000u,
};

#define GATE_MEIE0 0u
#define GATE_NEVER 1u
// Highest meipl level; meipt and meicurpl take the same encoding.
#define PRI_MAX (EL2_PIC__MEIPL__INTPRIORITY_bm >> EL2_PIC__MEIPL__INTPRIORITY_bp)
#define MIE_MTIE (1u << 7)
#define MIE_MSIE (1u << 3)
#define MIP_MTIP (1u << 7)
#define MIP_MSIP (1u << 3)
#define MIP_MEIP (1u << 11)
#define MIE_WRITE (MIE_MEIE | MIE_MTIE | MIE_MSIE)
#define MCAUSE_IRQ 0x80000000u
#define MCAUSE_ECALL_M 11u // RISC-V privileged spec: environment call from M-mode
#define LOG_MAX 64u
#define SRC_CTRL 1u

#define MBOX_OUT_RD0 SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_READ_DATA_BASE_ADDR
#define MBOX_OUT_ST0 SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_STATUS_BASE_ADDR

struct ot_src {
    uint32_t src;
    uint32_t state;
    uint32_t enable;
    uint32_t test;
    uint32_t bit;
};

static const struct ot_src k_ot[] = {
    {18u, SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR,
     SEP_TOP_HMAC_INTR_TEST_BASE_ADDR, HMAC__INTR_STATE__HMAC_DONE_bm},
    {20u, SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR,
     SEP_TOP_HMAC_INTR_TEST_BASE_ADDR, HMAC__INTR_STATE__HMAC_ERR_bm},
    {21u, SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR,
     SEP_TOP_KMAC_INTR_TEST_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm},
    {23u, SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR,
     SEP_TOP_KMAC_INTR_TEST_BASE_ADDR, KMAC__INTR_STATE__KMAC_ERR_bm},
    {24u, SEP_TOP_CSRNG_INTR_STATE_BASE_ADDR, SEP_TOP_CSRNG_INTR_ENABLE_BASE_ADDR,
     SEP_TOP_CSRNG_INTR_TEST_BASE_ADDR, CSRNG__INTR_STATE__CS_CMD_REQ_DONE_bm},
    {28u, SEP_TOP_EDN_INTR_STATE_BASE_ADDR, SEP_TOP_EDN_INTR_ENABLE_BASE_ADDR,
     SEP_TOP_EDN_INTR_TEST_BASE_ADDR, EDN__INTR_STATE__EDN_CMD_REQ_DONE_bm},
    {30u, SEP_TOP_OTBN_INTR_STATE_BASE_ADDR, SEP_TOP_OTBN_INTR_ENABLE_BASE_ADDR,
     SEP_TOP_OTBN_INTR_TEST_BASE_ADDR, OTBN__INTR_STATE__DONE_bm},
};
#define N_OT (sizeof(k_ot) / sizeof(k_ot[0]))

static volatile uint32_t g_runs[256];
static volatile uint32_t g_total;
static volatile uint32_t g_log[LOG_MAX];
static volatile uint32_t g_log_n;
static volatile uint32_t g_first_meip0;
static volatile uint32_t g_cls_ext, g_cls_timer, g_cls_sw, g_cls_other;
static volatile uint32_t g_last_mcause;
static int g_err;

// ---- Inbound filter allow window over the inbound port of mailbox m ----
// The source drive recipe opens one read and write window per inbound mailbox
// port it uses, before the first push, and keeps it open for the leaf.
#define MBX_IN_SPAN 0x800u
#define FILT_CFG_RW_EN \
    (FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm | FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm | \
     FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm)

static void mbx_window(uint32_t idx, uint32_t m) {
    volatile uint32_t *cfg =
        (volatile uint32_t *)SEP_TOP_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(idx);
    volatile uint32_t *st =
        (volatile uint32_t *)SEP_TOP_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR(idx);
    volatile uint32_t *en =
        (volatile uint32_t *)SEP_TOP_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR(idx);
    uint32_t s =
        SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_WRITE_DATA_BASE_ADDR + m * SEP_AXIL_MBOX_STRIDE;
    cfg[0] = 0u;
    cfg[1] = 0u;
    st[0] = s;
    st[1] = 0u;
    en[0] = s + MBX_IN_SPAN - 1u;
    en[1] = 0u;
    cfg[0] = FILT_CFG_RW_EN;
    __asm__ volatile("fence" ::: "memory");
    rec_ctl("MBX-WINDOW");
    rec_num("mbox", m);
    rec_hex("FILTER_CONFIG", cfg[0]);
    rec_hex("START_ADDR", st[0]);
    rec_hex("END_ADDR", en[0]);
    rec_end();
}

static inline uint32_t rd32(uint32_t a) {
    return *(volatile uint32_t *)a;
}
static inline void wr32(uint32_t a, uint32_t v) {
    *(volatile uint32_t *)a = v;
    __asm__ volatile("fence" ::: "memory");
}

static inline uint32_t rprm(uint32_t r, uint32_t k) {
    return g_prm[P_ROUND + r * R_WORDS + k];
}

static inline uint32_t mcycle(void) {
    uint32_t v;
    __asm__ volatile("csrr %0, mcycle" : "=r"(v));
    return v;
}

static inline void mstatus_mie(int on) {
    if (on) {
        __asm__ volatile("csrs mstatus, %0" ::"r"(MSTATUS_MIE));
    } else {
        __asm__ volatile("csrc mstatus, %0" ::"r"(MSTATUS_MIE));
    }
}

static inline uint32_t read_mip(void) {
    uint32_t v;
    __asm__ volatile("csrr %0, mip" : "=r"(v));
    return v;
}

static inline uint32_t never_val(uint32_t p) {
    return p ? PRI_MAX : 0u;
}

// priord with the threshold CSRs at the pass-all value of that order.
static void set_order(uint32_t p) {
    pic_write_priord(p);
    uint32_t t = p ? PRI_MAX : 0u;
    __asm__ volatile("csrw %0, %1" ::"i"(CSR_MEIPT), "r"(t));
    __asm__ volatile("csrw %0, %1" ::"i"(CSR_MEICURPL), "r"(t));
}

static const struct ot_src *ot_of(uint32_t s) {
    for (uint32_t i = 0; i < N_OT; i++) {
        if (k_ot[i].src == s) {
            return &k_ot[i];
        }
    }
    return 0;
}

static inline uint32_t mbox_in(uint32_t k, uint32_t reg0) {
    return reg0 + k * SEP_AXIL_MBOX_STRIDE;
}

static void mbox_setup_all(void) {
    for (uint32_t k = 0; k < SEP_AXIL_MBOX_N; k++) {
        wr32(mbox_in(k, SEP_AXIL_MBOX0_WIRQT), 0u);
        wr32(mbox_in(k, SEP_AXIL_MBOX0_IRQS), SEP_AXIL_MBOX_IRQ_ALL);
        wr32(mbox_in(k, SEP_AXIL_MBOX0_IRQEN), SEP_AXIL_MBOX_IRQ_WRITE);
    }
}

// Raise source s; returns its IP-side state read back (control, never a golden).
static uint32_t src_raise(uint32_t s) {
    if (s >= 1u && s <= 8u) {
        uint32_t k = s - 1u;
        wr32(mbox_in(k, SEP_AXIL_MBOX0_WRITE_DATA), 0x32000000u | s);
        return rd32(mbox_in(k, SEP_AXIL_MBOX0_IRQS)) & SEP_AXIL_MBOX_IRQ_WRITE ? 1u : 0u;
    }
    const struct ot_src *o = ot_of(s);
    if (o == 0) {
        return 0u;
    }
    wr32(o->enable, rd32(o->enable) | o->bit);
    wr32(o->test, o->bit);
    return (rd32(o->state) & o->bit) ? 1u : 0u;
}

static void src_release(uint32_t s) {
    if (s >= 1u && s <= 8u) {
        uint32_t k = s - 1u;
        // Pop only a held word: a source already released makes no read of an
        // empty FIFO.
        if ((rd32(MBOX_OUT_ST0 + k * SEP_AXIL_MBOX_STRIDE) & AXIL_MAILBOX__STATUS__EMPTY_bm) ==
            0u) {
            (void)rd32(MBOX_OUT_RD0 + k * SEP_AXIL_MBOX_STRIDE);
        }
        wr32(mbox_in(k, SEP_AXIL_MBOX0_IRQS), SEP_AXIL_MBOX_IRQ_WRITE);
        (void)rd32(mbox_in(k, SEP_AXIL_MBOX0_IRQS));
        return;
    }
    const struct ot_src *o = ot_of(s);
    if (o == 0) {
        return;
    }
    wr32(o->test, 0u);
    wr32(o->state, o->bit);
    (void)rd32(o->state);
}

static void classify(uint32_t mc) {
    g_last_mcause = mc;
    if ((mc & MCAUSE_IRQ) == 0u) {
        g_cls_other++;
        return;
    }
    switch (mc & 0x7FFFFFFFu) {
    case 11u:
        g_cls_ext++;
        break;
    case 7u:
        g_cls_timer++;
        break;
    case 3u:
        g_cls_sw++;
        break;
    default:
        g_cls_other++;
        break;
    }
}

// The per-source handler: read meip, log the source, release it by the recipe,
// and wait (bounded) for its meip bit to drop so mret does not re-enter.
static void src_handler(uint32_t id) {
    uint32_t meip0 = pic_read_meip(0);
    if (g_log_n == 0u) {
        g_first_meip0 = meip0;
    }
    if (g_log_n < LOG_MAX) {
        g_log[g_log_n] = id;
    }
    g_log_n++;
    g_runs[id]++;
    g_total++;
    if (ot_of(id) == 0 && !(id >= 1u && id <= 8u)) {
        pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(id), 0u); // a stray source
        return;
    }
    src_release(id);
    for (uint32_t i = 0; i < 2000u; i++) {
        if (((pic_read_meip(id >> 5) >> (id & 31u)) & 1u) == 0u) {
            break;
        }
    }
    rec_spin(8u);
}

// meihap points at the meivt table entry of the claimed source (crt0 sets
// meivt to INTVEC_BASE), so the entry index is the claim id. An index outside
// the PIC source range returns the reserved source 0.
static inline uint32_t claim_id(void) {
    uint32_t meihap;
    __asm__ volatile("csrr %0, %1" : "=r"(meihap) : "i"(CSR_MEIHAP));
    uint32_t idx = (meihap - (uint32_t)(uintptr_t)INTVEC_BASE) / sizeof(uint32_t);
    return idx < SEP_TOP_PIC_MEIE_NUM ? idx : 0u;
}

void __attribute__((interrupt("machine"))) ext_dispatch(void) {
    uint32_t mc;
    __asm__ volatile("csrr %0, mcause" : "=r"(mc));
    classify(mc);
    src_handler(claim_id());
}

void __attribute__((interrupt("machine"), aligned(4))) trap_dispatch(void) {
    uint32_t mc, epc;
    __asm__ volatile("csrr %0, mcause" : "=r"(mc));
    classify(mc);
    if ((mc & MCAUSE_IRQ) == 0u) {
        __asm__ volatile("csrr %0, mepc" : "=r"(epc));
        epc += 4u;
        __asm__ volatile("csrw mepc, %0" ::"r"(epc));
    } else if ((mc & 0x7FFFFFFFu) == 7u || (mc & 0x7FFFFFFFu) == 3u) {
        // A timer or software trap cannot be released from here: mask it.
        __asm__ volatile("csrc mie, %0" ::"r"(MIE_MTIE | MIE_MSIE));
    }
}

static uint32_t hold(void) {
    uint32_t t0 = mcycle();
    for (volatile uint32_t i = 0; i < g_prm[P_HOLD]; i++) {
    }
    return mcycle() - t0;
}

static int wait_runs(uint32_t s, uint32_t want) {
    for (uint32_t i = 0; i < g_prm[P_WAIT]; i++) {
        if (g_runs[s] >= want) {
            return 1;
        }
    }
    return 0;
}

static int wait_total(uint32_t want) {
    for (uint32_t i = 0; i < g_prm[P_WAIT]; i++) {
        if (g_total >= want) {
            return 1;
        }
    }
    return 0;
}

static void clear_log(void) {
    g_log_n = 0u;
    g_first_meip0 = 0u;
}

static void zero_set(uint32_t r) {
    for (uint32_t i = 0; i < rprm(r, R_N); i++) {
        uint32_t s = rprm(r, R_SRC + i);
        pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(s), 0u);
        pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(s), 0u);
    }
}

static void put_ids(const char *key, uint32_t from, uint32_t n) {
    sep_mbx_putc(' ');
    sep_mbx_puts(key);
    sep_mbx_putc('=');
    for (uint32_t i = 0; i < n && from + i < LOG_MAX; i++) {
        if (i) {
            sep_mbx_putc(',');
        }
        rec_dec(g_log[from + i]);
    }
    if (n == 0u) {
        sep_mbx_puts("none");
    }
}

static void put_list(const char *key, uint32_t r, uint32_t base) {
    sep_mbx_putc(' ');
    sep_mbx_puts(key);
    sep_mbx_putc('=');
    for (uint32_t i = 0; i < rprm(r, R_N); i++) {
        if (i) {
            sep_mbx_putc(',');
        }
        rec_dec(rprm(r, base + i));
    }
}

static void chk_end(int pass) {
    rec_end();
    if (!pass) {
        g_err++;
    }
}

static void meip_obs(uint32_t s) {
    rec_obs("NEVER-MEIP");
    rec_num("src", s);
    rec_num("meip_bit", (pic_read_meip(s >> 5) >> (s & 31u)) & 1u);
    rec_end();
}

static void run_round(uint32_t r) {
    uint32_t p = rprm(r, R_PRIORD);
    uint32_t n = rprm(r, R_N);
    uint32_t setmask = 0;
    for (uint32_t i = 0; i < n; i++) {
        setmask |= 1u << rprm(r, R_SRC + i);
    }
    zero_set(r);
    set_order(p);
    sep_mbx_puts("ROUND");
    rec_num("r", r);
    rec_num("priord", p);
    put_list("srcs", r, R_SRC);
    put_list("raws", r, R_RAW);
    put_list("gates", r, R_GATE);
    rec_num("never_src", rprm(r, R_SRC + rprm(r, R_NEVER)));
    rec_end();

    // Gate corner: each source behind its drawn closed gate, all asserted.
    for (uint32_t i = 0; i < n; i++) {
        uint32_t s = rprm(r, R_SRC + i);
        if (rprm(r, R_GATE + i) == GATE_MEIE0) {
            pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(s), rprm(r, R_RAW + i));
            pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(s), 0u);
        } else {
            pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(s), EL2_PIC__MEIE__INTEN_bm);
            pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(s), never_val(p));
        }
    }
    uint32_t t0 = g_total;
    uint32_t raised = 0;
    for (uint32_t i = 0; i < n; i++) {
        raised += src_raise(rprm(r, R_SRC + i));
    }
    (void)hold();
    uint32_t gated_runs = g_total - t0;
    for (uint32_t i = 0; i < n; i++) {
        meip_obs(rprm(r, R_SRC + i));
    }
    for (uint32_t j = 0; j < n; j++) {
        uint32_t i = rprm(r, R_ORDER + j);
        uint32_t s = rprm(r, R_SRC + i);
        uint32_t g = rprm(r, R_GATE + i);
        uint32_t before = g_total;
        uint32_t own0 = g_runs[s];
        if (g == GATE_MEIE0) {
            pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(s), EL2_PIC__MEIE__INTEN_bm);
        } else {
            pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(s), rprm(r, R_RAW + i));
        }
        (void)wait_runs(s, own0 + 1u);
        (void)hold();
        uint32_t own = g_runs[s] - own0;
        uint32_t other = (g_total - before) - own;
        int pass = gated_runs == 0u && raised == n && own == 1u && other == 0u;
        rec_chk("GATED", pass);
        rec_num("src", s);
        rec_str("gate", g == GATE_MEIE0 ? "meie0" : "never");
        rec_num("handler_runs", gated_runs);
        rec_num("then_open_runs", own);
        rec_num("other_runs", other);
        rec_num("raised", raised);
        chk_end(pass);
    }

    // mstatus.MIE gate.
    clear_log();
    mstatus_mie(0);
    for (uint32_t i = 0; i < n; i++) {
        uint32_t s = rprm(r, R_SRC + i);
        pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(s), EL2_PIC__MEIE__INTEN_bm);
        pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(s), rprm(r, R_RAW + i));
    }
    uint32_t meip_before = pic_read_meip(0) & setmask;
    t0 = g_total;
    raised = 0;
    for (uint32_t i = 0; i < n; i++) {
        raised += src_raise(rprm(r, R_SRC + i));
    }
    uint32_t hclk = hold();
    uint32_t mie0_runs = g_total - t0;

    // Winner corner: one MIE write; the handlers run to completion.
    clear_log();
    t0 = g_total;
    mstatus_mie(1);
    int done = wait_total(t0 + n);
    (void)hold();
    uint32_t open_runs = g_total - t0;
    uint32_t first = g_log[0];
    sep_mbx_puts("ORDER");
    rec_str("corner", "winner");
    rec_num("r", r);
    rec_num("priord", p);
    rec_num("n", g_log_n);
    put_ids("ids", 0u, g_log_n);
    rec_end();
    int pass = mie0_runs == 0u && raised == n && open_runs == n && done;
    rec_chk("GATED", pass);
    put_list("srcs", r, R_SRC);
    rec_str("gate", "mie0");
    rec_num("handler_runs", mie0_runs);
    rec_num("then_open_runs", open_runs);
    rec_num("hold_clk", hclk);
    chk_end(pass);
    uint32_t waiting = setmask & ~(1u << first);
    uint32_t during = g_first_meip0 & setmask;
    pass = meip_before == 0u && (during & waiting) == waiting && g_log_n >= 1u;
    rec_chk("STAY-PENDING", pass);
    rec_num("winner", first);
    rec_hex("waiting", waiting);
    rec_hex("meip_bits_before_assert", meip_before);
    rec_hex("meip_bits_during_handler", during);
    chk_end(pass);

    // Never corner.
    zero_set(r);
    uint32_t ni = rprm(r, R_NEVER);
    uint32_t sn = rprm(r, R_SRC + ni);
    uint32_t own0 = g_runs[sn];
    pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(sn), EL2_PIC__MEIE__INTEN_bm);
    pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(sn), never_val(p));
    raised = src_raise(sn);
    (void)hold();
    uint32_t nruns = g_runs[sn] - own0;
    meip_obs(sn);
    uint32_t eff1 = p ? 14u : 1u;
    pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(sn), eff1);
    (void)wait_runs(sn, own0 + nruns + 1u);
    (void)hold();
    uint32_t twin = g_runs[sn] - own0 - nruns;
    pass = raised == 1u && nruns == 0u && twin == 1u;
    rec_chk("NEVER", pass);
    rec_num("src", sn);
    rec_num("raw", never_val(p));
    rec_num("priord", p);
    rec_num("runs", nruns);
    rec_num("twin_runs", twin);
    rec_num("twin_raw", eff1);
    chk_end(pass);

    // Flip corner: opposite order, mirrored priorities.
    zero_set(r);
    mstatus_mie(0);
    set_order(p ^ 1u);
    for (uint32_t i = 0; i < n; i++) {
        uint32_t s = rprm(r, R_SRC + i);
        pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(s), PRI_MAX - rprm(r, R_RAW + i));
        pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(s), EL2_PIC__MEIE__INTEN_bm);
    }
    clear_log();
    t0 = g_total;
    for (uint32_t i = 0; i < n; i++) {
        (void)src_raise(rprm(r, R_SRC + i));
    }
    (void)hold();
    mstatus_mie(1);
    (void)wait_total(t0 + n);
    (void)hold();
    sep_mbx_puts("ORDER");
    rec_str("corner", "flip");
    rec_num("r", r);
    rec_num("priord_from", p);
    rec_num("priord_to", p ^ 1u);
    rec_num("n", g_log_n);
    put_ids("ids", 0u, g_log_n);
    rec_end();
    zero_set(r);
    set_order(0u);
}

int main(void) {
    sep_outbound_filter_init();
    sep_mbx_puts("SEP PIC priority gate test\n");
    uint32_t nr = g_prm[P_NROUND];
    if (g_prm[P_MAGIC] != PRM_MAGIC || nr == 0u || nr > R_MAX) {
        sep_mbx_puts("FAIL: parameter block not patched\n");
        return 1;
    }
    sep_mbx_puts("PARAMS");
    rec_hex("seed", g_prm[P_SEED]);
    rec_num("rounds", nr);
    rec_num("sweep", g_prm[P_SWEEP]);
    rec_num("hold", g_prm[P_HOLD]);
    rec_end();

    __asm__ volatile("csrw mtvec, %0" ::"r"((uint32_t)(uintptr_t)&trap_dispatch));
    for (uint32_t v = 0; v < 256u; v++) {
        pic_register_handler(v, ext_dispatch);
    }
    for (uint32_t k = 0; k < SEP_AXIL_MBOX_N; k++) {
        mbx_window(k, k);
    }
    mbox_setup_all();
    set_order(0u);

    rec_mark(0, "setup");
    __asm__ volatile("csrw mie, %0" ::"r"(MIE_WRITE));
    uint32_t mie_rd;
    __asm__ volatile("csrr %0, mie" : "=r"(mie_rd));
    int pass = mie_rd == MIE_WRITE;
    rec_chk("MIE-LIVE", pass);
    rec_hex("wrote", MIE_WRITE);
    rec_hex("read", mie_rd);
    chk_end(pass);
    uint32_t mip = read_mip();
    pass = (mip & (MIP_MTIP | MIP_MSIP)) == 0u;
    rec_chk("MIP-IDLE", pass);
    rec_str("when", "reset");
    rec_num("mip_mtip", (mip >> 7) & 1u);
    rec_num("mip_msip", (mip >> 3) & 1u);
    chk_end(pass);
    mstatus_mie(1);

    // Reset-state window: round 1 sources asserted with reset meie and meipl.
    rec_mark(1, "reset_window");
    uint32_t n0 = g_prm[P_ROUND + R_N];
    uint32_t t0 = g_total;
    uint32_t raised = 0;
    for (uint32_t i = 0; i < n0; i++) {
        raised += src_raise(rprm(0, R_SRC + i));
    }
    uint32_t hclk = hold();
    uint32_t runs = g_total - t0;
    for (uint32_t i = 0; i < n0; i++) {
        src_release(rprm(0, R_SRC + i));
    }
    pass = runs == 0u && raised == n0;
    rec_chk("NONE-BEFORE-PROGRAM", pass);
    rec_num("srcs", n0);
    rec_num("handler_runs", runs);
    rec_num("hold_clk", hclk);
    rec_num("raised", raised);
    chk_end(pass);

    // Encoding sweep (log only, window closed).
    rec_mark(0, "sweep");
    uint32_t sw = g_prm[P_SWEEP];
    for (uint32_t p = 0; p < 2u; p++) {
        set_order(p);
        for (uint32_t v = 0; v < 16u; v++) {
            pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(sw), v);
            rec_obs("LEVEL-SWEEP");
            rec_num("src", sw);
            rec_num("priord", p);
            rec_num("wrote", v);
            rec_num("read",
                    pic_rd32(SEP_TOP_PIC_MEIPL_BASE_ADDR(sw)) & EL2_PIC__MEIPL__INTPRIORITY_bm);
            rec_end();
        }
    }
    pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(sw), 0u);
    set_order(0u);

    for (uint32_t r = 0; r < nr; r++) {
        rec_mark(1, "round");
        run_round(r);
    }

    // Idle window: no PIC source enabled, MIE, MTIE and MSIE set.
    rec_mark(1, "idle");
    uint32_t tt0 = g_cls_timer, ts0 = g_cls_sw;
    hclk = hold();
    uint32_t idle_t = g_cls_timer - tt0, idle_s = g_cls_sw - ts0;
    uint32_t mst;
    __asm__ volatile("csrr %0, mstatus" : "=r"(mst));
    mip = read_mip();
    pass = (mip & (MIP_MTIP | MIP_MSIP)) == 0u && (mst & MSTATUS_MIE) != 0u;
    rec_chk("MIP-IDLE", pass);
    rec_str("when", "hold");
    rec_num("mstatus_mie", (mst >> 3) & 1u);
    rec_num("mip_mtip", (mip >> 7) & 1u);
    rec_num("mip_msip", (mip >> 3) & 1u);
    chk_end(pass);

    // Control: one PIC delivery through the dispatcher.
    rec_mark(0, "control");
    mstatus_mie(0);
    uint32_t tot_t = g_cls_timer, tot_s = g_cls_sw, tot_o = g_cls_other;
    g_cls_ext = 0u;
    g_cls_timer = 0u;
    g_cls_sw = 0u;
    uint32_t c0 = g_runs[SRC_CTRL];
    pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(SRC_CTRL), EL2_PIC__MEIE__INTEN_bm);
    pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(SRC_CTRL), 1u);
    (void)src_raise(SRC_CTRL);
    for (uint32_t i = 0; i < g_prm[P_WAIT]; i++) {
        if (read_mip() & MIP_MEIP) {
            break;
        }
    }
    mip = read_mip();
    pass = (mip & (MIP_MTIP | MIP_MSIP)) == 0u && (mip & MIP_MEIP) != 0u;
    rec_chk("MIP-IDLE", pass);
    rec_str("when", "after_control");
    rec_num("mip_mtip", (mip >> 7) & 1u);
    rec_num("mip_msip", (mip >> 3) & 1u);
    rec_num("ctrl_mip_meip", (mip >> 11) & 1u);
    chk_end(pass);
    mstatus_mie(1);
    (void)wait_runs(SRC_CTRL, c0 + 1u);
    (void)hold();
    uint32_t cruns = g_runs[SRC_CTRL] - c0;
    uint32_t mc = g_last_mcause;
    // Trap-path control: mtvec holds trap_dispatch, and one ecall enters it
    // through mtvec, the entry of a timer or software trap, and is counted as
    // a synchronous trap (mcause 11, environment call from M-mode).
    uint32_t mtvec_rd;
    __asm__ volatile("csrr %0, mtvec" : "=r"(mtvec_rd));
    uint32_t o0 = g_cls_other;
    __asm__ volatile("ecall" ::: "memory");
    uint32_t trap_n = g_cls_other - o0;
    uint32_t trap_mc = g_last_mcause;
    g_cls_other = o0;
    uint32_t mtvec_ok = mtvec_rd == (uint32_t)(uintptr_t)&trap_dispatch;
    pass = cruns == 1u && (mc & MCAUSE_IRQ) != 0u && mtvec_ok && trap_n == 1u &&
           trap_mc == MCAUSE_ECALL_M;
    rec_chk("CONTROL", pass);
    rec_num("mie_meie", (mie_rd >> 11) & 1u);
    rec_num("mcause_irq_bit", mc >> 31);
    rec_hex("mcause", mc);
    rec_num("runs", cruns);
    rec_num("mtvec_ok", mtvec_ok);
    rec_num("mtvec_traps", trap_n);
    rec_hex("mtvec_mcause", trap_mc);
    chk_end(pass);
    pass = tot_t == 0u && tot_s == 0u && idle_t == 0u && idle_s == 0u && g_cls_ext == 1u &&
           g_cls_timer == 0u && g_cls_sw == 0u && tot_o == 0u && g_cls_other == 0u;
    rec_chk("NO-TIMER-TRAP", pass);
    rec_num("traps_timer", tot_t);
    rec_num("traps_sw", tot_s);
    rec_num("hold_clk", hclk);
    rec_num("hold_timer", idle_t);
    rec_num("hold_sw", idle_s);
    rec_num("ctrl_class_ext", g_cls_ext);
    rec_num("ctrl_class_timer", g_cls_timer);
    rec_num("ctrl_class_sw", g_cls_sw);
    rec_num("traps_other", tot_o + g_cls_other);
    chk_end(pass);
    mstatus_mie(0);
    pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(SRC_CTRL), 0u);
    pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(SRC_CTRL), 0u);
    for (uint32_t i = 0; i < N_OT; i++) {
        wr32(k_ot[i].enable, 0u);
    }

    rec_mark(0, "end");
    if (g_err == 0) {
        sep_mbx_puts("PASS: PIC priority gate\n");
    }
    return g_err;
}
