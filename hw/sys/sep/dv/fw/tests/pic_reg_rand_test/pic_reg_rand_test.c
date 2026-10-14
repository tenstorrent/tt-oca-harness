// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// PIC register map, reset state, holes, entry 0 and source 0, from firmware.
//
// The host (cocotb/tests/cpu/sep_pic_reg_rand_test.py) draws the entries, the
// values, the meigwclr values, the hole addresses and the group order from the
// run seed and patches them into g_prm. Each leg starts with an M line
// (sep_console_rec.h); each check prints one CHK line:
//
//   CHK-RESET   every PIC field reads its RDL reset value before the first PIC
//               write
//   CHK-HOLE    a hole or past-extent access reads 0, traps nothing and lands in
//               no armed decoded register
//   CHK-RW      each implemented field holds the written value
//   CHK-ENTRY0  entry 0 of the four arrays reads 0 after an all-ones write, and
//               the write does not land in entry 1
//   CHK-GWCLR0  meigwclr reads 0 after a write with the clear bit 1
//   CHK-SRC0    source 0 never sets and never takes a handler
//
// Every compare covers the RDL field bits only; the PASS line logs the other
// bits as rsvd. The six excluded idle bits of meip come in the parameter block.
// Source 1 (mailbox 0 inbound line) is the control source: the CPU pushes one
// word into the inbound WRITE_DATA of mailbox 0 with IRQEN.wtirq 1, WIRQT 0 and
// an inbound filter allow window open over that port, and releases it with a pop of the outbound
// READ_DATA and a write of 1 to inbound IRQS.wtirq.

#include <stdint.h>

#include "filter_ctrl.h"
#include "sep.h"
#include "sep_axil_mailbox.h"
#include "sep_console_rec.h"
#include "sep_mailbox.h"
#include "sep_outbound_filter.h"
#include "sep_pic.h"

#define PRM_MAGIC 0x318E6A11u
#define NE_MAX 12u
#define N_HOLE 6u
#define N_ARM 7u

enum {
    P_MAGIC = 0,
    P_SEED,
    P_NE,
    P_GORDER, // group order of the array corner: three 4-bit group ids, low first
    P_HOLD,   // hold window, loop iterations
    P_WAIT,   // bound of every wait, loop iterations
    P_IDLE,   // 8 words: the excluded idle bits of meip
    P_HOLE = P_IDLE + 8,
    P_ENT = P_HOLE + N_HOLE,
    P_MEIPL = P_ENT + NE_MAX,
    P_MEIE = P_MEIPL + NE_MAX,
    P_GW = P_MEIE + NE_MAX,
    P_GWCLR = P_GW + NE_MAX,
    P_WORDS = P_GWCLR + NE_MAX,
};

// Directed defaults; the host always patches the block.
volatile uint32_t g_prm[P_WORDS] = {
    [P_MAGIC] = PRM_MAGIC, [P_NE] = 0u, [P_GORDER] = 0x210u, [P_HOLD] = 2000u, [P_WAIT] = 200000u,
};

#define MEIPL_BM EL2_PIC__MEIPL__INTPRIORITY_bm
#define MEIE_BM EL2_PIC__MEIE__INTEN_bm
#define GW_BM (EL2_PIC__MEIGWCTRL__POLARITY_bm | EL2_PIC__MEIGWCTRL__IRQ_TYPE_bm)
#define GWCLR_BM EL2_PIC__MEIGWCLR__CLEAR_bm
#define CFG_BM EL2_PIC__MPICCFG__PRIORD_bm
// Reset value of each register, from the generated RDL field resets.
#define MEIPL_RST (EL2_PIC__MEIPL__INTPRIORITY_reset << EL2_PIC__MEIPL__INTPRIORITY_bp)
#define MEIE_RST (EL2_PIC__MEIE__INTEN_reset << EL2_PIC__MEIE__INTEN_bp)
#define GW_RST \
    ((EL2_PIC__MEIGWCTRL__POLARITY_reset << EL2_PIC__MEIGWCTRL__POLARITY_bp) | \
     (EL2_PIC__MEIGWCTRL__IRQ_TYPE_reset << EL2_PIC__MEIGWCTRL__IRQ_TYPE_bp))
#define GWCLR_RST (EL2_PIC__MEIGWCLR__CLEAR_reset << EL2_PIC__MEIGWCLR__CLEAR_bp)
#define CFG_RST (EL2_PIC__MPICCFG__PRIORD_reset << EL2_PIC__MPICCFG__PRIORD_bp)
#define MEIP_RST (EL2_PIC__MEIP__INTPEND_reset << EL2_PIC__MEIP__INTPEND_bp)
// meigwctrl cells: level active low (polarity 1, irq_type 0) and edge active
// high (polarity 0, irq_type 1).
#define GW_LEVEL_LOW EL2_PIC__MEIGWCTRL__POLARITY_bm
#define GW_EDGE_HIGH EL2_PIC__MEIGWCTRL__IRQ_TYPE_bm

#define MBOX0_OUT_READ_DATA SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_READ_DATA_BASE_ADDR
#define MBOX0_OUT_STATUS SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_STATUS_BASE_ADDR
#define SRC_CTRL 1u

static const char *const k_grp[3] = {"meipl", "meie", "meigwctrl"};

static volatile uint32_t g_traps;
static volatile uint32_t g_trap_mcause;
static volatile uint32_t g_count_runs;  // counting handlers (every vector but 1)
static volatile uint32_t g_ctrl_runs;   // source 1 control handler
static volatile uint32_t g_ctrl_meip0;  // meip[0] read inside the control handler
static volatile uint32_t g_ctrl_active; // the control handler releases source 1
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

// ---- address helpers (an atomic argument only, see sep_pic.h) ----
static inline uint32_t a_meipl(uint32_t n) {
    return SEP_TOP_PIC_MEIPL_BASE_ADDR(n);
}
static inline uint32_t a_meie(uint32_t n) {
    return SEP_TOP_PIC_MEIE_BASE_ADDR(n);
}
static inline uint32_t a_gw(uint32_t n) {
    return SEP_TOP_PIC_MEIGWCTRL_BASE_ADDR(n);
}
static inline uint32_t a_gwclr(uint32_t n) {
    return SEP_TOP_PIC_MEIGWCLR_BASE_ADDR(n);
}
static inline uint32_t a_grp(uint32_t g, uint32_t n) {
    return g == 0u ? a_meipl(n) : (g == 1u ? a_meie(n) : a_gw(n));
}
static inline uint32_t m_grp(uint32_t g) {
    return g == 0u ? MEIPL_BM : (g == 1u ? MEIE_BM : GW_BM);
}
static inline uint32_t v_grp(uint32_t g, uint32_t i) {
    return g_prm[(g == 0u ? P_MEIPL : (g == 1u ? P_MEIE : P_GW)) + i];
}

// ---- trap counter: every synchronous exception is counted and skipped ----
// Hole accesses are 4-byte instructions (norvc), so mepc + 4 resumes after it.
void __attribute__((interrupt("machine"), aligned(4))) trap_count(void) {
    uint32_t mc, epc;
    __asm__ volatile("csrr %0, mcause" : "=r"(mc));
    g_trap_mcause = mc;
    g_traps++;
    if ((mc & 0x80000000u) == 0u) {
        __asm__ volatile("csrr %0, mepc" : "=r"(epc));
        epc += 4u;
        __asm__ volatile("csrw mepc, %0" ::"r"(epc));
    }
}

static inline uint32_t hole_rd(uint32_t a) {
    uint32_t v = 0;
    __asm__ volatile(".option push\n.option norvc\nlw %0, 0(%1)\n.option pop"
                     : "+r"(v)
                     : "r"(a)
                     : "memory");
    return v;
}

static inline void hole_wr(uint32_t a, uint32_t v) {
    __asm__ volatile(".option push\n.option norvc\nsw %0, 0(%1)\n.option pop\nfence" ::"r"(v),
                     "r"(a)
                     : "memory");
}

static inline uint32_t claim_id(void) {
    uint32_t meihap;
    __asm__ volatile("csrr %0, %1" : "=r"(meihap) : "i"(CSR_MEIHAP));
    return (meihap >> 2) & 0xFFu;
}

static void hold(void) {
    for (volatile uint32_t i = 0; i < g_prm[P_HOLD]; i++) {
    }
}

// ---- source 1 drive recipe (mailbox 0 inbound line) ----
static void mbox0_setup(void) {
    sep_axil_mbox_wr(SEP_AXIL_MBOX0_WIRQT, 0u);
    sep_axil_mbox_wr(SEP_AXIL_MBOX0_IRQS, SEP_AXIL_MBOX_IRQ_ALL);
    sep_axil_mbox_wr(SEP_AXIL_MBOX0_IRQEN, SEP_AXIL_MBOX_IRQ_WRITE);
}

static void src1_raise(void) {
    sep_axil_mbox_wr(SEP_AXIL_MBOX0_WRITE_DATA, 0x31800001u);
}

// The pop runs only when the outbound read FIFO holds a word, so a release
// that finds the source already released makes no read of an empty FIFO.
static void src1_release(void) {
    if ((sep_axil_mbox_rd(MBOX0_OUT_STATUS) & AXIL_MAILBOX__STATUS__EMPTY_bm) == 0u) {
        (void)sep_axil_mbox_rd(MBOX0_OUT_READ_DATA);
    }
    sep_axil_mbox_wr(SEP_AXIL_MBOX0_IRQS, SEP_AXIL_MBOX_IRQ_WRITE);
}

// Bounded wait until meip[0] bit 1 reads want; returns 1 on success.
static int wait_meip1(uint32_t want) {
    for (uint32_t i = 0; i < g_prm[P_WAIT]; i++) {
        if (((pic_read_meip(0) >> SRC_CTRL) & 1u) == want) {
            return 1;
        }
    }
    return 0;
}

void __attribute__((interrupt("machine"))) count_isr(void) {
    uint32_t id = claim_id();
    g_count_runs++;
    // Silence the claimed entry so a stray source cannot re-enter forever.
    pic_wr32(a_meie(id), 0u);
}

void __attribute__((interrupt("machine"))) ctrl_isr(void) {
    g_ctrl_meip0 = pic_read_meip(0);
    g_ctrl_runs++;
    pic_wr32(a_meie(SRC_CTRL), 0u);
    if (g_ctrl_active) {
        src1_release();
    }
}

// Reads one register: ORs its field bits into *val and its other bits into
// *rsvd, and counts it in *bad when its field bits differ from exp.
static void rd_field(uint32_t addr, uint32_t mask, uint32_t exp, uint32_t *val, uint32_t *rsvd,
                     uint32_t *bad) {
    uint32_t r = pic_rd32(addr);
    *val |= r & mask;
    *rsvd |= r & ~mask;
    *bad += (r & mask) != (exp & mask);
}

static void chk_end(int pass) {
    rec_end();
    if (!pass) {
        g_err++;
    }
}

// ---- step 2: reset reads ----
static void leg_reset(uint32_t ne) {
    static const uint32_t gmask[4] = {MEIPL_BM, MEIE_BM, GW_BM, GWCLR_BM};
    static const uint32_t gexp[4] = {MEIPL_RST, MEIE_RST, GW_RST, GWCLR_RST};
    static const char *const gname[4] = {"meipl", "meie", "meigwctrl", "meigwclr"};
    uint32_t val[4] = {0, 0, 0, 0}, rsvd[4] = {0, 0, 0, 0}, bad[4] = {0, 0, 0, 0};
    for (uint32_t g = 0; g < 4u; g++) {
        for (uint32_t i = 0; i < ne; i++) {
            uint32_t n = g_prm[P_ENT + i];
            uint32_t a =
                g == 0u ? a_meipl(n) : (g == 1u ? a_meie(n) : (g == 2u ? a_gw(n) : a_gwclr(n)));
            rd_field(a, gmask[g], gexp[g], &val[g], &rsvd[g], &bad[g]);
        }
    }
    uint32_t cval = 0, crsvd = 0, cbad = 0;
    rd_field(SEP_TOP_PIC_MPICCFG_BASE_ADDR, CFG_BM, CFG_RST, &cval, &crsvd, &cbad);
    uint32_t meip[8];
    uint32_t pval = 0, pbad = 0;
    for (uint32_t w = 0; w < 8u; w++) {
        meip[w] = pic_read_meip(w);
        uint32_t graded = EL2_PIC__MEIP__INTPEND_bm & ~g_prm[P_IDLE + w];
        pval |= meip[w] & graded;
        pbad += (meip[w] & graded) != (MEIP_RST & graded);
    }
    for (uint32_t g = 0; g < 4u; g++) {
        rec_chk("RESET", bad[g] == 0u);
        rec_str("group", gname[g]);
        rec_num("n", ne);
        rec_num("bad", bad[g]);
        rec_hex("exp", gexp[g]);
        rec_hex("val", val[g]);
        rec_hex("rsvd", rsvd[g]);
        rec_hex("mask", gmask[g]);
        chk_end(bad[g] == 0u);
    }
    rec_chk("RESET", cbad == 0u);
    rec_str("group", "mpiccfg");
    rec_num("n", 1u);
    rec_num("bad", cbad);
    rec_hex("exp", CFG_RST);
    rec_hex("val", cval);
    rec_hex("rsvd", crsvd);
    rec_hex("mask", CFG_BM);
    chk_end(cbad == 0u);
    rec_chk("RESET", pbad == 0u);
    rec_str("group", "meip");
    rec_num("n", 8u);
    rec_num("bad", pbad);
    rec_hex("exp", MEIP_RST);
    rec_hex("val", pval);
    rec_hex("idle_masked", 1u);
    chk_end(pbad == 0u);
    rec_obs("IDLE-UNSTATED");
    rec_num("src13", (meip[0] >> 13) & 1u);
    rec_num("src15", (meip[0] >> 15) & 1u);
    rec_num("src16", (meip[0] >> 16) & 1u);
    rec_num("src37", (meip[1] >> 5) & 1u);
    rec_num("src38", (meip[1] >> 6) & 1u);
    rec_num("src39", (meip[1] >> 7) & 1u);
    rec_end();
}

// ---- step 3: hole corner ----
static void arm_list(uint32_t k, uint32_t *addr, uint32_t *val, uint32_t *mask) {
    addr[0] = a_meipl(255);
    val[0] = 7u;
    mask[0] = MEIPL_BM;
    addr[1] = a_meie(255);
    val[1] = 1u;
    mask[1] = MEIE_BM;
    addr[2] = a_gw(255);
    val[2] = 1u;
    mask[2] = GW_BM;
    addr[3] = a_meipl(k);
    val[3] = 7u;
    mask[3] = MEIPL_BM;
    addr[4] = a_meie(k);
    val[4] = 1u;
    mask[4] = MEIE_BM;
    addr[5] = a_gw(k);
    val[5] = 1u;
    mask[5] = GW_BM;
    addr[6] = SEP_TOP_PIC_MPICCFG_BASE_ADDR;
    val[6] = 1u;
    mask[6] = CFG_BM;
}

static int armed_same(const uint32_t *addr, const uint32_t *val, const uint32_t *mask) {
    int same = 1;
    for (uint32_t j = 0; j < N_ARM; j++) {
        if ((pic_rd32(addr[j]) & mask[j]) != val[j]) {
            same = 0;
        }
    }
    return same;
}

static void leg_hole(void) {
    for (uint32_t h = 0; h < N_HOLE; h++) {
        uint32_t ha = g_prm[P_HOLE + h];
        uint32_t k = (ha >> 2) & 0xFFu;
        uint32_t addr[N_ARM], val[N_ARM], mask[N_ARM];
        arm_list(k, addr, val, mask);
        for (uint32_t j = 0; j < N_ARM; j++) {
            pic_wr32(addr[j], val[j]);
        }
        uint32_t t0 = g_traps;
        int ctl = armed_same(addr, val, mask);
        uint32_t rd0 = hole_rd(ha);
        hole_wr(ha, 0u);
        uint32_t rd1 = hole_rd(ha);
        int same0 = armed_same(addr, val, mask);
        hole_wr(ha, 0xFFFFFFFFu);
        uint32_t rd2 = hole_rd(ha);
        int same1 = armed_same(addr, val, mask);
        uint32_t traps = g_traps - t0;
        for (uint32_t j = 0; j < N_ARM; j++) {
            pic_wr32(addr[j], 0u);
        }
        int pass = ctl && rd0 == 0u && rd1 == 0u && rd2 == 0u && same0 && same1 && traps == 0u;
        rec_chk("HOLE", pass);
        rec_hex("addr", ha);
        rec_num("k", k);
        rec_hex("rd0", rd0);
        rec_hex("rd_after_wr0", rd1);
        rec_hex("rd_after_wr1", rd2);
        rec_num("armed_regs", N_ARM);
        rec_num("armed_ctl", (uint32_t)ctl);
        rec_num("armed_same_after_wr0", (uint32_t)same0);
        rec_num("armed_same_after_wr1", (uint32_t)same1);
        rec_num("trap", traps);
        if (traps) {
            rec_hex("mcause", g_trap_mcause);
        }
        chk_end(pass);
    }
}

// ---- step 4: array corner ----
// A cell with ``with_inv`` first wrote ``mask`` and read it back as ``raw_inv``; the
// cell passes only when that read-back holds every implemented bit, so a field that
// ignores writes cannot pass a drawn 0 by reading its reset value.
static void rw_line(const char *grp, uint32_t src, uint32_t wr, uint32_t raw, uint32_t mask,
                    int with_src, int with_inv, uint32_t raw_inv) {
    uint32_t rd = raw & mask;
    int pass = rd == wr && (!with_inv || (raw_inv & mask) == mask);
    rec_chk("RW", pass);
    rec_str("group", grp);
    if (with_src) {
        rec_num("src", src);
    }
    rec_hex("wr", wr);
    rec_hex("rd", rd);
    rec_hex("raw", raw);
    rec_hex("rsvd", raw & ~mask);
    rec_hex("mask", mask);
    if (with_inv) {
        rec_hex("inv", mask);
        rec_hex("raw_inv", raw_inv);
    }
    chk_end(pass);
}

static void leg_array(uint32_t ne) {
    uint32_t go = g_prm[P_GORDER];
    for (uint32_t i = 0; i < ne; i++) {
        uint32_t n = g_prm[P_ENT + i];
        for (uint32_t s = 0; s < 3u; s++) {
            uint32_t g = (go >> (4u * s)) & 0xFu;
            uint32_t m = m_grp(g);
            uint32_t v = v_grp(g, i) & m;
            // The field holds 0 here; a drawn 0 first takes the inverse and reads
            // it back, so each graded read-back differs from the value before it.
            int inv = v == 0u;
            uint32_t raw_inv = 0u;
            if (inv) {
                pic_wr32(a_grp(g, n), m);
                raw_inv = pic_rd32(a_grp(g, n));
            }
            pic_wr32(a_grp(g, n), v);
            uint32_t raw = pic_rd32(a_grp(g, n));
            rw_line(k_grp[g], n, v, raw, m, 1, inv, raw_inv);
        }
        pic_wr32(a_meipl(n), 0u);
        pic_wr32(a_meie(n), 0u);
        pic_wr32(a_gw(n), 0u);
    }
    pic_wr32(SEP_TOP_PIC_MPICCFG_BASE_ADDR, 1u);
    rw_line("mpiccfg", 0u, 1u, pic_read_mpiccfg(), CFG_BM, 0, 0, 0u);
    pic_wr32(SEP_TOP_PIC_MPICCFG_BASE_ADDR, 0u);
    rw_line("mpiccfg", 0u, 0u, pic_read_mpiccfg(), CFG_BM, 0, 0, 0u);
}

// ---- step 5: entry 0 corner ----
static void leg_entry0(void) {
    pic_wr32(a_meipl(1), 5u);
    pic_wr32(a_gw(1), 1u);
    pic_wr32(a_meie(1), 0u);
    pic_wr32(a_meipl(0), 0xFFFFFFFFu);
    pic_wr32(a_meie(0), 0xFFFFFFFFu);
    pic_wr32(a_gw(0), 0xFFFFFFFFu);
    pic_wr32(a_gwclr(0), 0xFFFFFFFFu);
    uint32_t r_pl = pic_rd32(a_meipl(0));
    uint32_t r_ie = pic_rd32(a_meie(0));
    uint32_t r_gw = pic_rd32(a_gw(0));
    uint32_t r_gc = pic_rd32(a_gwclr(0));
    uint32_t e1_pl = pic_rd32(a_meipl(1)) & MEIPL_BM;
    uint32_t e1_ie = pic_rd32(a_meie(1)) & MEIE_BM;
    uint32_t e1_gw = pic_rd32(a_gw(1)) & GW_BM;
    int e1_same = e1_pl == 5u && e1_ie == 0u && e1_gw == 1u;
    // Control: the all-ones value of each field lands in entry 1.
    pic_wr32(a_meipl(1), MEIPL_BM);
    pic_wr32(a_meie(1), MEIE_BM);
    pic_wr32(a_gw(1), GW_BM);
    uint32_t c_pl = pic_rd32(a_meipl(1)) & MEIPL_BM;
    uint32_t c_ie = pic_rd32(a_meie(1)) & MEIE_BM;
    uint32_t c_gw = pic_rd32(a_gw(1)) & GW_BM;
    int ctl = c_pl == MEIPL_BM && c_ie == MEIE_BM && c_gw == GW_BM;
    pic_wr32(a_meie(1), 0u);
    pic_wr32(a_meipl(1), 0u);
    pic_wr32(a_gw(1), 0u);
    int z = (r_pl & MEIPL_BM) == 0u && (r_ie & MEIE_BM) == 0u && (r_gw & GW_BM) == 0u &&
            (r_gc & GWCLR_BM) == 0u;
    int pass = z && e1_same && ctl;
    rec_chk("ENTRY0", pass);
    rec_hex("meipl0", r_pl & MEIPL_BM);
    rec_hex("meie0", r_ie & MEIE_BM);
    rec_hex("gwctrl0", r_gw & GW_BM);
    rec_hex("gwclr0", r_gc & GWCLR_BM);
    rec_hex("rsvd", (r_pl & ~MEIPL_BM) | (r_ie & ~MEIE_BM) | (r_gw & ~GW_BM) | (r_gc & ~GWCLR_BM));
    rec_num("entry1_same", (uint32_t)e1_same);
    rec_hex("entry1_rd", (e1_pl << 8) | (e1_ie << 4) | e1_gw);
    rec_num("entry1_ctl", (uint32_t)ctl);
    chk_end(pass);
}

// ---- steps 6 and 7: meigwclr corner and its control ----
static void leg_gwclr(uint32_t ne, uint32_t *rd) {
    for (uint32_t i = 0; i < ne; i++) {
        uint32_t n = g_prm[P_ENT + i];
        pic_wr32(a_gw(n), GW_EDGE_HIGH);
        pic_write_meigwclr(n, g_prm[P_GWCLR + i]);
        rd[i] = pic_read_meigwclr(n);
        pic_wr32(a_gw(n), 0u);
    }
}

static void gwclr_ctrl(uint32_t *before, uint32_t *after, int *ok) {
    pic_wr32(a_gw(SRC_CTRL), GW_EDGE_HIGH);
    pic_wr32(a_meie(SRC_CTRL), 1u);
    pic_wr32(a_meipl(SRC_CTRL), 1u);
    src1_raise();
    *ok = wait_meip1(1u);
    src1_release();
    *before = (pic_read_meip(0) >> SRC_CTRL) & 1u;
    pic_write_meigwclr(SRC_CTRL, g_prm[P_GWCLR + 0]);
    *after = (pic_read_meip(0) >> SRC_CTRL) & 1u;
    pic_wr32(a_gw(SRC_CTRL), 0u);
    pic_wr32(a_meie(SRC_CTRL), 0u);
    pic_wr32(a_meipl(SRC_CTRL), 0u);
}

int main(void) {
    sep_outbound_filter_init();
    sep_mbx_puts("SEP PIC register map test\n");
    if (g_prm[P_MAGIC] != PRM_MAGIC || g_prm[P_NE] == 0u || g_prm[P_NE] > NE_MAX) {
        sep_mbx_puts("FAIL: parameter block not patched\n");
        return 1;
    }
    uint32_t ne = g_prm[P_NE];
    sep_mbx_puts("PARAMS");
    rec_hex("seed", g_prm[P_SEED]);
    rec_num("ne", ne);
    rec_hex("gorder", g_prm[P_GORDER]);
    rec_num("hold", g_prm[P_HOLD]);
    rec_hex("hole0", g_prm[P_HOLE]);
    rec_hex("ent0", g_prm[P_ENT]);
    rec_end();

    __asm__ volatile("csrw mtvec, %0" ::"r"((uint32_t)(uintptr_t)&trap_count));
    for (uint32_t v = 0; v < 256u; v++) {
        pic_register_handler(v, v == SRC_CTRL ? ctrl_isr : count_isr);
    }
    mbx_window(0u, 0u);
    mbox0_setup();

    rec_mark(1, "reset");
    leg_reset(ne);

    rec_mark(1, "hole");
    leg_hole();

    rec_mark(1, "array");
    leg_array(ne);

    rec_mark(1, "entry0");
    leg_entry0();

    rec_mark(1, "gwclr");
    uint32_t gwrd[NE_MAX];
    leg_gwclr(ne, gwrd);

    rec_mark(0, "gwclr_ctrl");
    uint32_t cb = 0, ca = 0;
    int cok = 0;
    gwclr_ctrl(&cb, &ca, &cok);
    int ctl_ok = cok && cb == 1u && ca == 0u;
    rec_ctl("GWCLR-CTRL");
    rec_num("raised", (uint32_t)cok);
    rec_num("meip_before", cb);
    rec_num("meip_after", ca);
    rec_end();
    for (uint32_t i = 0; i < ne; i++) {
        // The graded bit must be written 1, so a meigwclr that reads back the
        // written value cannot read 0 there.
        int pass = (g_prm[P_GWCLR + i] & GWCLR_BM) != 0u && (gwrd[i] & GWCLR_BM) == 0u && ctl_ok;
        rec_chk("GWCLR0", pass);
        rec_num("src", g_prm[P_ENT + i]);
        rec_hex("wr", g_prm[P_GWCLR + i]);
        rec_hex("rd", gwrd[i] & GWCLR_BM);
        rec_hex("rsvd", gwrd[i] & ~GWCLR_BM);
        rec_hex("gwctrl", GW_EDGE_HIGH);
        rec_num("ctrl_meip_before", cb);
        rec_num("ctrl_meip_after", ca);
        chk_end(pass);
    }

    // Step 8: the source 0 cell on idle source 1 (level, active low) is pending.
    rec_mark(0, "src0_cell_ctrl");
    pic_wr32(a_gw(SRC_CTRL), GW_LEVEL_LOW);
    pic_wr32(a_meie(SRC_CTRL), 1u);
    pic_wr32(a_meipl(SRC_CTRL), 15u);
    uint32_t cell1 = wait_meip1(1u) ? 1u : 0u;
    pic_wr32(a_gw(SRC_CTRL), 0u);
    pic_wr32(a_meie(SRC_CTRL), 0u);
    pic_wr32(a_meipl(SRC_CTRL), 0u);
    rec_ctl("SRC0-CELL");
    rec_num("ctrl_cell_meip1", cell1);
    rec_end();

    // Step 9: entry 0 all ones, delivery open.
    rec_mark(1, "src0_allones");
    pic_wr32(a_meipl(0), 0xFFFFFFFFu);
    pic_wr32(a_meie(0), 0xFFFFFFFFu);
    pic_wr32(a_gw(0), 0xFFFFFFFFu);
    pic_wr32(a_gwclr(0), 0xFFFFFFFFu);
    pic_enable_interrupts();
    hold();
    uint32_t m0 = pic_read_meip(0);
    uint32_t runs_a = g_count_runs + g_ctrl_runs;
    int pass_a = (m0 & 1u) == 0u && runs_a == 0u;
    rec_chk("SRC0", pass_a);
    rec_str("leg", "allones");
    rec_num("meip0_bit0", m0 & 1u);
    rec_num("handler_runs", runs_a);
    chk_end(pass_a);

    // Step 10: entry 0 in the level, active-low cell.
    rec_mark(1, "src0_lowlevel");
    pic_wr32(a_gw(0), GW_LEVEL_LOW);
    pic_wr32(a_meie(0), 1u);
    pic_wr32(a_meipl(0), 15u);
    hold();
    m0 = pic_read_meip(0);
    uint32_t runs_l = g_count_runs + g_ctrl_runs;
    pic_wr32(a_gw(0), 0u);
    pic_wr32(a_meie(0), 0u);
    pic_wr32(a_meipl(0), 0u);
    int pass_l = (m0 & 1u) == 0u && runs_l == 0u && cell1 == 1u;
    rec_chk("SRC0", pass_l);
    rec_str("leg", "lowlevel");
    rec_num("meip0_bit0", m0 & 1u);
    rec_num("handler_runs", runs_l);
    rec_num("ctrl_cell_meip1", cell1);
    chk_end(pass_l);

    // Step 11: the source 1 handler control.
    rec_mark(0, "src0_handler_ctrl");
    g_ctrl_active = 1u;
    pic_wr32(a_meie(SRC_CTRL), 1u);
    pic_wr32(a_meipl(SRC_CTRL), 1u);
    src1_raise();
    uint32_t w = 0;
    while (g_ctrl_runs == 0u && w < g_prm[P_WAIT]) {
        w++;
    }
    hold();
    pic_disable_interrupts();
    g_ctrl_active = 0u;
    pic_wr32(a_meie(SRC_CTRL), 0u);
    pic_wr32(a_meipl(SRC_CTRL), 0u);
    uint32_t b1 = (g_ctrl_meip0 >> SRC_CTRL) & 1u;
    uint32_t b0 = g_ctrl_meip0 & 1u;
    int pass_c = g_ctrl_runs == 1u && b1 == 1u && b0 == 0u && g_count_runs == 0u;
    rec_chk("SRC0", pass_c);
    rec_num("control_runs", g_ctrl_runs);
    rec_num("ctrl_meip_bit1", b1);
    rec_num("ctrl_meip_bit0", b0);
    rec_num("count_runs", g_count_runs);
    chk_end(pass_c);

    rec_mark(0, "end");
    if (g_err == 0) {
        sep_mbx_puts("PASS: PIC register map\n");
    }
    return g_err;
}
