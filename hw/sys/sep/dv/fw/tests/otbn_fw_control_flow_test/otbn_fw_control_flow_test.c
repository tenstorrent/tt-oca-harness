// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP OTBN firmware control flow test: the CPU loads a short OTBN program, starts it
// with CMD = EXECUTE and reads the DMEM result, once ending on the done interrupt
// and once polling STATUS.
//
// The entropy stack comes up first: after reset OTBN is busy with the secure wipe
// of its internal state, and the wipe and every EXECUTE reseed URND from EDN. IMEM
// and DMEM are touched only at IDLE: a memory access while OTBN is busy is a fatal
// ILLEGAL_BUS_ACCESS error.
//
// The firmware prints one INFO-OTBN-FW-LEG line per leg with the values it read
// back. The testbench grades those values against the OTBN ISA. main() returns the
// error count of its own compares; crt0 turns 0 into the PASS magic.

#include <stdint.h>

#include "sep.h"
#include "och_sep_common.h"
#include "sep_entropy.h"
#include "sep_mailbox.h"
#include "sep_outbound_filter.h"
#include "sep_pic.h"

// CMD and STATUS codes of the otbn.hjson CMD and STATUS tables; the generated
// header has no enum for them.
#define OTBN_CMD_EXECUTE 0xD8u
#define OTBN_ST_IDLE 0x00u
#define OTBN_ST_BUSY_EXECUTE 0x01u
#define OTBN_ST_BUSY_SEC_WIPE_INT 0x04u

// OTBN done is internal interrupt 29, PIC source 30 (interrupts.adoc).
#define PIC_SRC_OTBN_DONE 30u

// Bound of each STATUS or interrupt-flag poll.
#define OTBN_POLL_ITERS 100000u

// Largest loop count the firmware accepts.
#define N_MAX 8u

// The OTBN program (OTBN base instruction subset, encodings of base-insns.yml):
//   lw   x2, 0(x0)      a
//   lw   x3, 4(x0)      b
//   lw   x6, 16(x0)     n
//   add  x4, x2, x3     s = a + b
//   xor  x5, x4, x2     s ^ a
//   add  x5, x5, x4     loop: + s
//   addi x6, x6, -1
//   bne  x6, x0, -8     to the loop head, n times in all
//   sw   x4, 8(x0)
//   sw   x5, 12(x0)
//   ecall
static const uint32_t kOtbnProg[] = {
    0x00002103u, 0x00402183u, 0x01002303u, 0x00310233u, 0x002242b3u, 0x004282b3u,
    0xfff30313u, 0xfe031ce3u, 0x00402423u, 0x00502623u, 0x00000073u,
};
#define OTBN_PROG_WORDS (sizeof(kOtbnProg) / sizeof(kOtbnProg[0]))

// DMEM word indexes of the program operands and results.
#define DMEM_A 0u
#define DMEM_B 1u
#define DMEM_S 2u
#define DMEM_T 3u
#define DMEM_N 4u
#define DMEM_ROW_WORDS 8u

// Parameter block the host patches from the run seed (env/sep_dtcm_param_patch.py):
// the magic, then a, b, n of the interrupt leg and of the poll leg, then the
// expected s, t of each leg. s and t seed the DMEM sentinels and the firmware's
// own compare; the testbench grades the printed values itself.
#define OTBN_PARAM_MAGIC 0x0B7EF10Cu
enum {
    P_MAGIC,
    P_A1,
    P_B1,
    P_N1,
    P_A2,
    P_B2,
    P_N2,
    P_S1,
    P_T1,
    P_S2,
    P_T2,
    P_WORDS,
};
volatile uint32_t g_otbn_params[P_WORDS] = {
    OTBN_PARAM_MAGIC, 0x89abcdefu, 0x76543321u, 3u,          0x01234567u, 0x10203040u, 2u,
    0x00000110u,      0x89abd02fu, 0x114375a7u, 0x32e71c0eu,
};

static volatile uint32_t g_irq_count = 0;
static volatile uint32_t g_claim_id = 0;

static inline uint32_t otbn_status(void) {
    return READ_REG(SEP_TOP_OTBN_STATUS_BASE_ADDR) & OTBN__STATUS__STATUS_bm;
}

// Clears INTR_STATE.done at its source. The line is level type, so the claim
// completes when the source drops. The handler touches no OTBN memory.
void __attribute__((interrupt("machine"))) otbn_done_isr(void) {
    uint32_t meihap;
    __asm__ volatile("csrr %0, %1" : "=r"(meihap) : "i"(CSR_MEIHAP));
    g_claim_id = (meihap >> 2) & 0xFFu;
    WRITE_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR, OTBN__INTR_STATE__DONE_bm);
    __asm__ volatile("fence" ::: "memory");
    g_irq_count = g_irq_count + 1u;
}

// Polls STATUS until IDLE. Returns 0 at IDLE, 1 at the bound.
static int otbn_wait_idle(uint32_t *polls) {
    for (uint32_t i = 0; i < OTBN_POLL_ITERS; i++) {
        if (otbn_status() == OTBN_ST_IDLE) {
            *polls = i;
            return 0;
        }
    }
    *polls = OTBN_POLL_ITERS;
    return 1;
}

static void put_field(const char *name, uint32_t v) {
    sep_mbx_putc(' ');
    sep_mbx_puts(name);
    sep_mbx_putc('=');
    sep_mbx_puthex(v);
}

typedef struct {
    uint32_t st0;
    uint32_t st_end;
    uint32_t err;
    uint32_t insn;
    uint32_t intr;
    uint32_t intr_clr;
    uint32_t polls;
    uint32_t busy_reads;
    uint32_t bad_code;
    uint32_t s;
    uint32_t t;
} leg_result_t;

// Writes the operands and the sentinels ~s, ~t to DMEM row 0. OTBN is at IDLE.
static void stage_dmem(uint32_t a, uint32_t b, uint32_t n, uint32_t s, uint32_t t) {
    for (uint32_t i = 0; i < DMEM_ROW_WORDS; i++) {
        WRITE_MEM_WORD(SEP_TOP_OTBN_DMEM_BASE_ADDR, i, 0u);
    }
    WRITE_MEM_WORD(SEP_TOP_OTBN_DMEM_BASE_ADDR, DMEM_A, a);
    WRITE_MEM_WORD(SEP_TOP_OTBN_DMEM_BASE_ADDR, DMEM_B, b);
    WRITE_MEM_WORD(SEP_TOP_OTBN_DMEM_BASE_ADDR, DMEM_S, ~s);
    WRITE_MEM_WORD(SEP_TOP_OTBN_DMEM_BASE_ADDR, DMEM_T, ~t);
    WRITE_MEM_WORD(SEP_TOP_OTBN_DMEM_BASE_ADDR, DMEM_N, n);
    WRITE_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR, OTBN__INTR_STATE__DONE_bm);
}

// Reads the end state of a leg. OTBN must be at IDLE before the DMEM reads.
static int read_end(leg_result_t *r) {
    uint32_t polls;
    r->st_end = otbn_status();
    int rc = otbn_wait_idle(&polls);
    r->err = READ_REG(SEP_TOP_OTBN_ERR_BITS_BASE_ADDR);
    r->insn = READ_REG(SEP_TOP_OTBN_INSN_CNT_BASE_ADDR);
    r->intr = READ_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR) & OTBN__INTR_STATE__DONE_bm;
    if (rc != 0) {
        sep_mbx_puts("[FAIL] OTBN not IDLE at the end of the leg, STATUS=");
        sep_mbx_puthex(otbn_status());
        sep_mbx_putc('\n');
        r->s = 0u;
        r->t = 0u;
        return 1;
    }
    r->s = READ_MEM_WORD(SEP_TOP_OTBN_DMEM_BASE_ADDR, DMEM_S);
    r->t = READ_MEM_WORD(SEP_TOP_OTBN_DMEM_BASE_ADDR, DMEM_T);
    return 0;
}

// Interrupt leg: INTR_ENABLE.done = 1, wait for the handler.
static int run_irq_leg(uint32_t a, uint32_t b, uint32_t n, uint32_t s, uint32_t t,
                       leg_result_t *r) {
    int e = 0;
    stage_dmem(a, b, n, s, t);
    WRITE_REG(SEP_TOP_OTBN_INTR_ENABLE_BASE_ADDR, OTBN__INTR_ENABLE__DONE_bm);
    WRITE_REG(SEP_TOP_OTBN_CMD_BASE_ADDR, OTBN_CMD_EXECUTE);
    r->st0 = otbn_status();
    uint32_t i = 0;
    while (g_irq_count == 0u && i < OTBN_POLL_ITERS) i++;
    r->polls = i;
    r->busy_reads = 0u;
    r->bad_code = 0u;
    if (g_irq_count == 0u) {
        sep_mbx_puts("[FAIL] no OTBN done interrupt within the bound\n");
        e++;
    }
    e += read_end(r);
    r->intr_clr = r->intr;
    WRITE_REG(SEP_TOP_OTBN_INTR_ENABLE_BASE_ADDR, 0u);
    return e;
}

// Poll leg: INTR_ENABLE.done = 0, poll STATUS until IDLE, then clear done.
static int run_poll_leg(uint32_t a, uint32_t b, uint32_t n, uint32_t s, uint32_t t,
                        leg_result_t *r) {
    int e = 0;
    stage_dmem(a, b, n, s, t);
    WRITE_REG(SEP_TOP_OTBN_CMD_BASE_ADDR, OTBN_CMD_EXECUTE);
    r->st0 = otbn_status();
    r->busy_reads = 0u;
    r->bad_code = 0u;
    uint32_t i = 0;
    uint32_t st = r->st0;
    while (st != OTBN_ST_IDLE && i < OTBN_POLL_ITERS) {
        if (st == OTBN_ST_BUSY_EXECUTE || st == OTBN_ST_BUSY_SEC_WIPE_INT) {
            r->busy_reads++;
        } else {
            r->bad_code = st;
        }
        st = otbn_status();
        i++;
    }
    r->polls = i;
    if (st != OTBN_ST_IDLE) {
        sep_mbx_puts("[FAIL] OTBN poll leg did not reach IDLE within the bound\n");
        e++;
    }
    e += read_end(r);
    WRITE_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR, OTBN__INTR_STATE__DONE_bm);
    r->intr_clr = READ_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR) & OTBN__INTR_STATE__DONE_bm;
    return e;
}

static int report_leg(const char *leg, uint32_t a, uint32_t b, uint32_t n, uint32_t s, uint32_t t,
                      const leg_result_t *r) {
    sep_mbx_puts("INFO-OTBN-FW-LEG leg=");
    sep_mbx_puts(leg);
    put_field("a", a);
    put_field("b", b);
    put_field("n", n);
    put_field("st0", r->st0);
    put_field("st_end", r->st_end);
    put_field("err", r->err);
    put_field("insn", r->insn);
    put_field("intr", r->intr);
    put_field("intr_clr", r->intr_clr);
    put_field("irqs", g_irq_count);
    put_field("claim", g_claim_id);
    put_field("polls", r->polls);
    put_field("busy_reads", r->busy_reads);
    put_field("bad_code", r->bad_code);
    put_field("s", r->s);
    put_field("t", r->t);
    sep_mbx_putc('\n');
    return (r->s != s || r->t != t || r->err != 0u) ? 1 : 0;
}

int main(void) {
    int errors = 0;
    sep_outbound_filter_init();
    sep_mbx_puts("SEP OTBN firmware control flow test\n");

    if (g_otbn_params[P_MAGIC] != OTBN_PARAM_MAGIC) {
        sep_mbx_puts("[FAIL] bad parameter magic ");
        sep_mbx_puthex(g_otbn_params[P_MAGIC]);
        sep_mbx_putc('\n');
        return 1;
    }
    const uint32_t n1 = g_otbn_params[P_N1];
    const uint32_t n2 = g_otbn_params[P_N2];
    if (n1 < 1u || n1 > N_MAX || n2 < 1u || n2 > N_MAX) {
        sep_mbx_puts("[FAIL] loop count out of range ");
        sep_mbx_puthex(n1);
        sep_mbx_putc(' ');
        sep_mbx_puthex(n2);
        sep_mbx_putc('\n');
        return 1;
    }

    int rc = sep_entropy_bringup();
    if (rc != SEP_ENTROPY_OK) {
        sep_mbx_puts("[FAIL] entropy bring-up rc=");
        sep_mbx_puthex((uint32_t)rc);
        sep_mbx_putc('\n');
        return 1;
    }

    // The secure wipe after reset ends at IDLE once EDN delivers.
    uint32_t polls;
    if (otbn_wait_idle(&polls) != 0) {
        sep_mbx_puts("[FAIL] OTBN not IDLE after the reset wipe, STATUS=");
        sep_mbx_puthex(otbn_status());
        sep_mbx_putc('\n');
        return 1;
    }
    sep_mbx_puts("INFO-OTBN-FW-INIT");
    put_field("polls", polls);
    put_field("intr", READ_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR));
    sep_mbx_putc('\n');
    WRITE_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR, OTBN__INTR_STATE__DONE_bm);
    WRITE_REG(SEP_TOP_OTBN_INTR_ENABLE_BASE_ADDR, 0u);

    for (uint32_t i = 0; i < OTBN_PROG_WORDS; i++) {
        WRITE_MEM_WORD(SEP_TOP_OTBN_IMEM_BASE_ADDR, i, kOtbnProg[i]);
    }

    pic_register_handler(PIC_SRC_OTBN_DONE, otbn_done_isr);
    pic_set_gateway(PIC_SRC_OTBN_DONE, 0, 0); // level-triggered, active-high
    pic_set_priority(PIC_SRC_OTBN_DONE, 1);
    pic_enable_source(PIC_SRC_OTBN_DONE);
    pic_enable_interrupts();

    leg_result_t r;
    const uint32_t a1 = g_otbn_params[P_A1];
    const uint32_t b1 = g_otbn_params[P_B1];
    const uint32_t s1 = g_otbn_params[P_S1];
    const uint32_t t1 = g_otbn_params[P_T1];
    errors += run_irq_leg(a1, b1, n1, s1, t1, &r);
    errors += report_leg("irq", a1, b1, n1, s1, t1, &r);

    const uint32_t a2 = g_otbn_params[P_A2];
    const uint32_t b2 = g_otbn_params[P_B2];
    const uint32_t s2 = g_otbn_params[P_S2];
    const uint32_t t2 = g_otbn_params[P_T2];
    errors += run_poll_leg(a2, b2, n2, s2, t2, &r);
    errors += report_leg("poll", a2, b2, n2, s2, t2, &r);

    sep_mbx_puts("INFO-OTBN-FW-END errors=");
    sep_mbx_puthex((uint32_t)errors);
    sep_mbx_putc('\n');
    return errors;
}
