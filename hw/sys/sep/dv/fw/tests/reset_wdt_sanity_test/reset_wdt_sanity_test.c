// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP reset-controller and watchdog sanity test, in one CPU boot on bare `sep`.
//
// Phase A, reset controller:
//   * the software reset register reads its reset default;
//   * for each crypto IP (otbn/aes/hmac/kmac/abr) and the TRNG domain
//     (esrc/csrng/edn), a pulse of only that IP's reset returns its probe
//     register to its reset value, leaves every probe outside that reset bit
//     unchanged, and leaves the probe writable after the release;
//   * the software reset register is back at its default afterwards;
//   * a write and a read to the unmapped gap past the reset-controller window
//     each raise a bus-error NMI; exactly two must be counted.
//
// Phase B, watchdog:
//   * the first bark fires the NMI and the handler disables the watchdog; after
//     one settle window the count reads the same non-zero value across
//     WDT_HOLD_MCYCLE, a pet clears it, and it reads 0 across WDT_HOLD_MCYCLE;
//   * after re-enable the second bark fires, and the watchdog runs on to bite,
//     whose reset request the testbench checks.
//
// One NMI handler serves both phases; the watchdog bark status tells the two
// NMI sources apart.

#include <stdint.h>
#include <stddef.h>

#include "sep_outbound_filter.h"
#include "sep_mailbox.h"
#include "sep_nmi.h"
#include "sep_reset.h"
#include "sep_wdt.h"

// Crypto-IP probe CSRs (sep_top_reg): address, the value written, and the
// register's reset value, which the probe must read after its reset pulse.
// Reset values are composed from the generated per-field *_reset constants.
#define OTBN_INTR_ENABLE_ADDR SEP_TOP_OTBN_INTR_ENABLE_BASE_ADDR
#define OTBN_INTR_ENABLE_WR OTBN__INTR_ENABLE__DONE_bm
#define OTBN_INTR_ENABLE_RST OCH_SEP_FIELD_RESET(OTBN__INTR_ENABLE, DONE)

// CTRL_AUX_REGWEN is rw0c: resets to 1, and a write of 0 is the only change.
#define AES_CTRL_AUX_REGWEN_ADDR SEP_TOP_AES_CTRL_AUX_REGWEN_BASE_ADDR
#define AES_CTRL_AUX_REGWEN_WR 0x0u
#define AES_CTRL_AUX_REGWEN_RST OCH_SEP_FIELD_RESET(AES__CTRL_AUX_REGWEN, CTRL_AUX_REGWEN)

#define HMAC_INTR_ENABLE_ADDR SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR
#define HMAC_INTR_ENABLE_WR \
    (HMAC__INTR_ENABLE__HMAC_DONE_bm | HMAC__INTR_ENABLE__FIFO_EMPTY_bm | \
     HMAC__INTR_ENABLE__HMAC_ERR_bm)
#define HMAC_INTR_ENABLE_RST \
    (OCH_SEP_FIELD_RESET(HMAC__INTR_ENABLE, HMAC_DONE) | \
     OCH_SEP_FIELD_RESET(HMAC__INTR_ENABLE, FIFO_EMPTY) | \
     OCH_SEP_FIELD_RESET(HMAC__INTR_ENABLE, HMAC_ERR))

#define KMAC_INTR_ENABLE_ADDR SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR
#define KMAC_INTR_ENABLE_WR \
    (KMAC__INTR_ENABLE__KMAC_DONE_bm | KMAC__INTR_ENABLE__FIFO_EMPTY_bm | \
     KMAC__INTR_ENABLE__KMAC_ERR_bm)
#define KMAC_INTR_ENABLE_RST \
    (OCH_SEP_FIELD_RESET(KMAC__INTR_ENABLE, KMAC_DONE) | \
     OCH_SEP_FIELD_RESET(KMAC__INTR_ENABLE, FIFO_EMPTY) | \
     OCH_SEP_FIELD_RESET(KMAC__INTR_ENABLE, KMAC_ERR))

#define ESRC_DEBUG_CTRL_ADDR SEP_TOP_ENTROPY_SOURCE_DEBUG_CTRL_BASE_ADDR
#define ESRC_DEBUG_CTRL_WR (1u << ENTROPY_SOURCE__DEBUG_CTRL__SELECT_SIGNAL_bp)
#define ESRC_DEBUG_CTRL_RST \
    (OCH_SEP_FIELD_RESET(ENTROPY_SOURCE__DEBUG_CTRL, SELECT_SIGNAL) | \
     OCH_SEP_FIELD_RESET(ENTROPY_SOURCE__DEBUG_CTRL, SELECT_FREQ_DIV))

#define CSRNG_INTR_ENABLE_ADDR SEP_TOP_CSRNG_INTR_ENABLE_BASE_ADDR
#define CSRNG_INTR_ENABLE_WR CSRNG__INTR_ENABLE__CS_CMD_REQ_DONE_bm
#define CSRNG_INTR_ENABLE_RST \
    (OCH_SEP_FIELD_RESET(CSRNG__INTR_ENABLE, CS_CMD_REQ_DONE) | \
     OCH_SEP_FIELD_RESET(CSRNG__INTR_ENABLE, CS_ENTROPY_REQ) | \
     OCH_SEP_FIELD_RESET(CSRNG__INTR_ENABLE, CS_HW_INST_EXC) | \
     OCH_SEP_FIELD_RESET(CSRNG__INTR_ENABLE, CS_FATAL_ERR))

#define EDN_INTR_ENABLE_ADDR SEP_TOP_EDN_INTR_ENABLE_BASE_ADDR
#define EDN_INTR_ENABLE_WR EDN__INTR_ENABLE__EDN_CMD_REQ_DONE_bm
#define EDN_INTR_ENABLE_RST \
    (OCH_SEP_FIELD_RESET(EDN__INTR_ENABLE, EDN_CMD_REQ_DONE) | \
     OCH_SEP_FIELD_RESET(EDN__INTR_ENABLE, EDN_FATAL_ERR))

// No generated field header exists for the Adams Bridge interrupt block. The
// field values come from global_intr_en_t in
// vendor/chipsalliance/adams-bridge/upstream/src/abr_top/rtl/abr_reg.rdl:
// error_en [0] and notif_en [1], both reset 0.
#define ABR_GLOBAL_INTR_ENABLE_ADDR SEP_TOP_ABR_INTR_BLOCK_RF_GLOBAL_INTR_EN_R_BASE_ADDR
#define ABR_GLOBAL_INTR_ENABLE_WR 0x3u
#define ABR_GLOBAL_INTR_ENABLE_RST 0x0u

#define RESET_CTRL_BAD_ADDR (SEP_RESET_CTRL_SW_RESET_N + 0x8u) // unmapped gap

// WDT thresholds in WDT-clock ticks, small because the WDT clock is much slower
// than the core clock; the bark->NMI and bite->reset paths do not depend on the
// values. Bite > bark so the bark fires first.
#define WDT_BARK_SIM 4u
#define WDT_BITE_SIM 10u

#define NMI_WAIT_ITERS 200000

// Core cycles of each watchdog hold window. The bench runs clk_i at 1.25 ns and
// clk_wdt_i at 5000 ns (cocotb/env/sep_env_cfg.py), so one watchdog tick is
// 4000 core cycles and this window spans ten of them.
//
// vendor/lowRISC/opentitan/overlay/regs/aon_timer/regs/aon_timer.rdl defines
// WDOG_COUNT.count as software read-write, "the current watchdog counter
// value", and vendor/lowRISC/opentitan/upstream/hw/ip/aon_timer/data/
// aon_timer.hjson places the register in the watchdog clock domain
// (async: "clk_aon_i"). A pet writes 0, so the expected read after a pet is
// that written 0. A read issued after the pet completes only once the pet has
// crossed into the watchdog domain, and the bus-side copy a read returns
// re-syncs whenever it differs from the counter, so a pet the counter drops
// reads back the running count, not 0. The copy follows the counter one
// crossing at a time and can lag it by several ticks; each window covers more
// than one refresh, and the disable write needs the same crossing before the
// count stops.
#define WDT_HOLD_MCYCLE 40000u

static inline uint32_t rd_mcycle(void) {
    uint32_t c;
    __asm__ volatile("csrr %0, mcycle" : "=r"(c));
    return c;
}

// Spin for at least n core cycles; returns the cycles that elapsed.
static uint32_t wait_mcycle(uint32_t n) {
    uint32_t start = rd_mcycle();
    uint32_t now;
    do {
        now = rd_mcycle();
    } while ((uint32_t)(now - start) < n);
    return now - start;
}

static volatile uint32_t g_bad_addr_nmi = 0;
static volatile uint32_t g_wdt_bark = 0;

// Unified NMI handler. WDT bark (Phase B) vs D-bus error (Phase A) is told apart
// by the WDT bark status bit; the two sources never overlap in time.
void nmi_handler(void) {
    if (wdt_get_intr_state() & WDT_INTR_BARK) {
        wdt_clear_bark(); // deassert nmi_int before mret
        g_wdt_bark++;
        if (g_wdt_bark == 1u) {
            wdt_disable(); // freeze for the pet/disable checks
        }
        // 2nd bark: leave the WDT enabled so it advances to BITE.
    } else {
        // D-bus error NMI: read and unlock the captured error address (mdseac,
        // mdeau) so the NMI deasserts, then count it.
        uint32_t mdseac;
        __asm__ volatile("csrr %0, 0xFC0" : "=r"(mdseac));
        (void)mdseac;
        __asm__ volatile("csrw 0xBC0, zero");
        g_bad_addr_nmi++;
    }
    __asm__ volatile("fence" ::: "memory");
}

// One reset-wire probe: a CSR in the reset domain of `bit`, the value written
// to it, and the register's reset value.
typedef struct {
    const char *name;
    uint32_t bit;
    uint32_t addr;
    uint32_t wr;
    uint32_t rst;
} reset_probe_t;

static const reset_probe_t k_probes[] = {
    {"otbn", SEP_SW_RESET_N_OTBN_BIT, OTBN_INTR_ENABLE_ADDR, OTBN_INTR_ENABLE_WR,
     OTBN_INTR_ENABLE_RST},
    {"aes", SEP_SW_RESET_N_AES_BIT, AES_CTRL_AUX_REGWEN_ADDR, AES_CTRL_AUX_REGWEN_WR,
     AES_CTRL_AUX_REGWEN_RST},
    {"hmac", SEP_SW_RESET_N_HMAC_BIT, HMAC_INTR_ENABLE_ADDR, HMAC_INTR_ENABLE_WR,
     HMAC_INTR_ENABLE_RST},
    {"kmac", SEP_SW_RESET_N_KMAC_BIT, KMAC_INTR_ENABLE_ADDR, KMAC_INTR_ENABLE_WR,
     KMAC_INTR_ENABLE_RST},
    {"abr", SEP_SW_RESET_N_ABR_BIT, ABR_GLOBAL_INTR_ENABLE_ADDR, ABR_GLOBAL_INTR_ENABLE_WR,
     ABR_GLOBAL_INTR_ENABLE_RST},
    {"esrc", SEP_SW_RESET_N_TRNG_BIT, ESRC_DEBUG_CTRL_ADDR, ESRC_DEBUG_CTRL_WR,
     ESRC_DEBUG_CTRL_RST},
    {"csrng", SEP_SW_RESET_N_TRNG_BIT, CSRNG_INTR_ENABLE_ADDR, CSRNG_INTR_ENABLE_WR,
     CSRNG_INTR_ENABLE_RST},
    {"edn", SEP_SW_RESET_N_TRNG_BIT, EDN_INTR_ENABLE_ADDR, EDN_INTR_ENABLE_WR, EDN_INTR_ENABLE_RST},
};
#define NUM_PROBES (sizeof(k_probes) / sizeof(k_probes[0]))

// Checks one IP reset wire: write this IP's probe and every probe outside its
// reset bit, pulse only this IP's reset, then require this probe back at its
// reset value and every other-domain probe unchanged, so a reset bit wired to
// any other domain fails. The probe write is then repeated and must read back,
// so a domain left in reset fails; a second pulse returns the probe to its reset
// value for the next check. esrc, csrng and edn share the TRNG reset bit, so
// none of them is a neighbour of the others. Returns 1 on failure.
static int check_reset_wire(const reset_probe_t *p) {
    uint32_t neighbours = 0;
    sep_reset_wr(p->addr, p->wr);
    if (sep_reset_rd(p->addr) != p->wr) {
        sep_mbx_puts("FAIL: probe write did not land: ");
        sep_mbx_puts(p->name);
        sep_mbx_putc('\n');
        return 1;
    }
    // Other-domain probes, held across the pulse. Each is confirmed landed
    // first, so a read of its written value after the pulse cannot be a write
    // that never took.
    for (uint32_t j = 0; j < NUM_PROBES; j++) {
        const reset_probe_t *nb = &k_probes[j];
        if (nb->bit == p->bit) {
            continue;
        }
        sep_reset_wr(nb->addr, nb->wr);
        if (sep_reset_rd(nb->addr) != nb->wr) {
            sep_mbx_puts("CHK-SWRST-WIRE FAIL: neighbour probe write did not land: ");
            sep_mbx_puts(nb->name);
            sep_mbx_putc('\n');
            return 1;
        }
    }
    // Pulse only this IP's reset bit, then restore the default.
    sep_reset_wr(SEP_RESET_CTRL_SW_RESET_N, SEP_SW_RESET_N_DEFAULT & ~p->bit);
    sep_reset_wr(SEP_RESET_CTRL_SW_RESET_N, SEP_SW_RESET_N_DEFAULT);
    if (sep_reset_rd(p->addr) != p->rst) {
        sep_mbx_puts("FAIL: reset wire did not clear probe: ");
        sep_mbx_puts(p->name);
        sep_mbx_putc('\n');
        return 1;
    }
    for (uint32_t j = 0; j < NUM_PROBES; j++) {
        const reset_probe_t *nb = &k_probes[j];
        if (nb->bit == p->bit) {
            continue;
        }
        if (sep_reset_rd(nb->addr) != nb->wr) {
            sep_mbx_puts("CHK-SWRST-WIRE FAIL: neighbour domain disturbed: ");
            sep_mbx_puts(p->name);
            sep_mbx_puts(" reset changed ");
            sep_mbx_puts(nb->name);
            sep_mbx_putc('\n');
            return 1;
        }
        neighbours++;
    }
    sep_reset_wr(p->addr, p->wr);
    if (sep_reset_rd(p->addr) != p->wr) {
        sep_mbx_puts("FAIL: probe not writable after reset release: ");
        sep_mbx_puts(p->name);
        sep_mbx_putc('\n');
        return 1;
    }
    sep_reset_wr(SEP_RESET_CTRL_SW_RESET_N, SEP_SW_RESET_N_DEFAULT & ~p->bit);
    sep_reset_wr(SEP_RESET_CTRL_SW_RESET_N, SEP_SW_RESET_N_DEFAULT);
    if (sep_reset_rd(p->addr) != p->rst) {
        sep_mbx_puts("FAIL: second reset pulse did not clear probe: ");
        sep_mbx_puts(p->name);
        sep_mbx_putc('\n');
        return 1;
    }
    sep_mbx_puts(p->name);
    sep_mbx_puts(" reset wire OK, writable after release, other-domain probes unchanged ");
    sep_mbx_puthex(neighbours);
    sep_mbx_putc('\n');
    return 0;
}

int main(void) {
    int errors = 0;

    sep_outbound_filter_init();
    sep_mbx_puts("SEP reset+WDT sanity test\n");

    nmi_register_handler(nmi_handler);
    nmi_set_vector_reg();
    nmi_lock_vector_reg();

    // ---- PHASE A: reset controller ----
    uint32_t sw_reset_n = sep_reset_rd(SEP_RESET_CTRL_SW_RESET_N);
    if (sw_reset_n != SEP_SW_RESET_N_DEFAULT) {
        sep_mbx_puts("FAIL: SW_RESET_N default ");
        sep_mbx_puthex(sw_reset_n);
        sep_mbx_putc('\n');
        errors++;
    }

    for (uint32_t i = 0; i < NUM_PROBES; i++) {
        errors += check_reset_wire(&k_probes[i]);
    }

    if (sep_reset_rd(SEP_RESET_CTRL_SW_RESET_N) != SEP_SW_RESET_N_DEFAULT) {
        sep_mbx_puts("FAIL: SW_RESET_N not restored to default\n");
        errors++;
    }

    // Bad-address: a write and a read to the unmapped gap (SW_RESET_N is a single
    // 64-bit register at offset 0, so the 0x8 window ends there) each raise a
    // D-bus error -> NMI; expect exactly 2. The STORE error is IMPRECISE, so it
    // must be allowed to land before the next bus access -- otherwise it coalesces
    // with the precise LOAD-error NMI and only one is counted. Settle after each.
    g_bad_addr_nmi = 0;
    __asm__ volatile("fence" ::: "memory");
    *(volatile uint32_t *)RESET_CTRL_BAD_ADDR = 0xDEADBEEFu;
    for (volatile int i = 0; i < 200; i++) {
        __asm__ volatile("nop");
    }
    (void)(*(volatile uint32_t *)(RESET_CTRL_BAD_ADDR + 0x8u));
    for (volatile int i = 0; i < 200; i++) {
        __asm__ volatile("nop");
    }
    if (g_bad_addr_nmi != 2u) {
        sep_mbx_puts("FAIL: bad-address NMI count ");
        sep_mbx_puthex(g_bad_addr_nmi);
        sep_mbx_puts(" (expected 2)\n");
        errors++;
    } else {
        sep_mbx_puts("reset_ctrl bad-address NMI count == 2 OK\n");
    }

    // ---- PHASE B: watchdog ----
    g_wdt_bark = 0;
    __asm__ volatile("fence" ::: "memory");
    wdt_set_count(0);
    wdt_set_bark(WDT_BARK_SIM);
    wdt_set_bite(WDT_BITE_SIM);
    wdt_enable();
    sep_mbx_puts("STEP watchdog configured (small bark/bite thresholds) and enabled\n");

    // Wait for the 1st bark NMI (handler disables the WDT).
    int timeout = NMI_WAIT_ITERS;
    while (timeout-- > 0) {
        __asm__ volatile("wfi");
        if (g_wdt_bark >= 1u) {
            break;
        }
    }
    if (g_wdt_bark < 1u) {
        sep_mbx_puts("FAIL: WDT bark NMI never fired\n");
        return errors + 1;
    }
    sep_mbx_puts("CHK-WDT-NMI PASS: 1st bark fired NMI, handler ran\n");

    // CHK-WDT-CLEAR: the handler's clear/disable contract stuck -- bark status bit
    // reads back cleared (W1C) and WDOG_CTRL reads back disabled.
    uint32_t intr_after = wdt_get_intr_state();
    uint32_t ctrl_after = wdt_get_ctrl();
    if (intr_after & WDT_INTR_BARK) {
        sep_mbx_puts("FAIL: WDT bark not cleared after NMI ");
        sep_mbx_puthex(intr_after);
        sep_mbx_putc('\n');
        errors++;
    } else if (ctrl_after != 0u) {
        sep_mbx_puts("FAIL: WDT not disabled after NMI ");
        sep_mbx_puthex(ctrl_after);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_mbx_puts("CHK-WDT-CLEAR PASS: INTR_STATE.bark cleared and WDOG_CTRL disabled\n");
    }

    // CHK-WDT-PET: WDT is disabled -> after one window for the disable and
    // the last count refresh to cross the CDC, the count reads the same non-zero
    // value across one more window; pet -> 0; it reads 0 across one more window.
    int pet_ok = 1;
    uint32_t settle_cyc = wait_mcycle(WDT_HOLD_MCYCLE);
    uint32_t cnt = wdt_get_count();
    uint32_t frz_cyc = wait_mcycle(WDT_HOLD_MCYCLE);
    uint32_t cnt2 = wdt_get_count();
    if (cnt == 0u) {
        sep_mbx_puts("CHK-WDT-PET FAIL: WDT count 0 before pet (expected non-zero)\n");
        errors++;
        pet_ok = 0;
    } else if (cnt2 != cnt) {
        sep_mbx_puts("CHK-WDT-PET FAIL: disabled WDT count moved ");
        sep_mbx_puthex(cnt);
        sep_mbx_puts(" -> ");
        sep_mbx_puthex(cnt2);
        sep_mbx_putc('\n');
        errors++;
        pet_ok = 0;
    }
    wdt_pet();
    uint32_t pet_cnt = wdt_get_count();
    if (pet_cnt != 0u) {
        sep_mbx_puts("CHK-WDT-PET FAIL: WDT pet did not clear count ");
        sep_mbx_puthex(pet_cnt);
        sep_mbx_putc('\n');
        errors++;
        pet_ok = 0;
    }
    uint32_t hold_cyc = wait_mcycle(WDT_HOLD_MCYCLE);
    uint32_t hold_cnt = wdt_get_count();
    if (hold_cnt != 0u) {
        sep_mbx_puts("CHK-WDT-PET FAIL: disabled WDT kept counting ");
        sep_mbx_puthex(hold_cnt);
        sep_mbx_putc('\n');
        errors++;
        pet_ok = 0;
    }
    if (pet_ok) {
        sep_mbx_puts("CHK-WDT-PET PASS: disabled, after ");
        sep_mbx_puthex(settle_cyc);
        sep_mbx_puts(" mcycles settle, count ");
        sep_mbx_puthex(cnt);
        sep_mbx_puts(" == ");
        sep_mbx_puthex(cnt2);
        sep_mbx_puts(" across ");
        sep_mbx_puthex(frz_cyc);
        sep_mbx_puts(" mcycles; pet -> 0, still 0 after ");
        sep_mbx_puthex(hold_cyc);
        sep_mbx_puts(" mcycles\n");
    }

    // Re-enable and wait for the 2nd bark; then let it run on to BITE (the cocotb
    // test observes wdt_timer_rst_req_o).
    wdt_enable();
    timeout = NMI_WAIT_ITERS;
    while (timeout-- > 0) {
        __asm__ volatile("wfi");
        if (g_wdt_bark >= 2u) {
            break;
        }
    }
    if (g_wdt_bark < 2u) {
        sep_mbx_puts("FAIL: WDT re-enable did not re-bark\n");
        errors++;
    } else {
        sep_mbx_puts("CHK-WDT-REBARK PASS: re-enable re-fired the bark NMI (running on to BITE)\n");
    }

    if (errors == 0) {
        sep_mbx_puts("PASS: SW_RESET_N default + per-IP/TRNG/ABR reset wires + bad-addr NMI x2 "
                     "+ WDT bark/pet/disable/re-bark (BITE pending)\n");
    }
    return errors;
}
