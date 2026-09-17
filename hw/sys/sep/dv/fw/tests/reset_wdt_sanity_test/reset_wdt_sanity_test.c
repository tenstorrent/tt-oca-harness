// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP reset-controller + WDT sanity firmware test (OSS port combining the reference suite
// sep_reset_ctrl_csr_test and wdt_sanity_test). Two phases, one EL2 boot:
//
// PHASE A -- reset controller (sep_reset_ctrl):
//   * SW_RESET_N reads its reset default (km held; crypto/TRNG/ABR released).
//   * For each released crypto IP (otbn/aes/hmac/kmac/abr): write a probe CSR, confirm
//     it landed, pulse ONLY that IP's SW_RESET_N bit low->high, and confirm the
//     probe returned to its reset default -- proving the reset wire reached the IP.
//   * SW_RESET_N is back at default afterwards.
//   * A write + a read to the unmapped gap just past the reset_ctrl window each
//     raise a D-bus error -> VeeR NMI; exactly 2 NMIs must be counted.
//
// PHASE B -- watchdog (wdt_sanity):
//   * Arm the WDT; the bark fires the NMI (sep.sv nmi_int = intr_wdog_timer_bark).
//   * 1st bark: the handler disables the WDT; main then sees the count frozen
//     non-zero, pets it to 0, and confirms it stays 0 while disabled.
//   * Re-enable: the 2nd bark fires; the firmware reports PASS and lets the WDT
//     run on to BITE, whose reset request (wdt_timer_rst_req_o) the cocotb test
//     observes.
//
// All paths are internal to bare `sep`. A unified NMI handler serves both NMI
// sources, distinguished by the WDT bark status bit (Phase A has the WDT
// disabled, Phase B sets the bark bit). Checks accumulate into `errors`; main()
// returns it (start.S emits PASS/FAIL magic). Mirrors the reference suite checking; PASS is
// signalled by returning from main (reference suite calls test_pass()).

#include <stdint.h>
#include <stddef.h>

#include "sep_outbound_filter.h"
#include "sep_mailbox.h"
#include "sep_nmi.h"
#include "abr_mldsa.h"
#include "sep_reset.h"
#include "sep_wdt.h"

// Crypto-IP probe CSRs (och_sep_top_reg): default, the value we write, and the
// value expected back after the reset pulse (== default if the reset cleared it).
#define OTBN_INTR_ENABLE_ADDR OCH_SEP_TOP_OTBN_INTR_ENABLE_BASE_ADDR
#define AES_CTRL_AUX_REGWEN_ADDR OCH_SEP_TOP_AES_CTRL_AUX_REGWEN_BASE_ADDR
#define HMAC_INTR_ENABLE_ADDR OCH_SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR
#define KMAC_INTR_ENABLE_ADDR OCH_SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR
#define ESRC_DEBUG_CTRL_ADDR OCH_SEP_TOP_ENTROPY_SOURCE_DEBUG_CTRL_BASE_ADDR
#define CSRNG_INTR_ENABLE_ADDR OCH_SEP_TOP_CSRNG_INTR_ENABLE_BASE_ADDR
#define EDN_INTR_ENABLE_ADDR OCH_SEP_TOP_EDN_INTR_ENABLE_BASE_ADDR
#define ABR_GLOBAL_INTR_ENABLE_ADDR (ABR_BASE + 0x8100u)

#define RESET_CTRL_BAD_ADDR (SEP_RESET_CTRL_SW_RESET_N + 0x8u) // unmapped gap

// WDT thresholds in WDT-clock ticks. Small for Verilator throughput (clk_wdt_i is
// ~1000x slower than the core clock); the bark->NMI and bite->reset mechanisms
// are threshold-independent. Bite > bark so bark fires first.
#define WDT_BARK_SIM 4u
#define WDT_BITE_SIM 10u

#define NMI_WAIT_ITERS 200000

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
        // D-bus error NMI: read + unlock the captured error address so nmi_int
        // deasserts (mdseac=0xFC0 capture, mdeau=0xBC0 unlock), then count it.
        uint32_t mdseac;
        __asm__ volatile("csrr %0, 0xFC0" : "=r"(mdseac));
        (void)mdseac;
        __asm__ volatile("csrw 0xBC0, zero");
        g_bad_addr_nmi++;
    }
    __asm__ volatile("fence" ::: "memory");
}

// One IP reset-wire check, both halves of CHK-SWRST-WIRE: write this IP's probe
// and a neighbour domain's probe, pulse only this IP's reset bit, then require
// this probe back at its reset default AND the neighbour probe unchanged. The
// neighbour is what makes the pulse per-IP rather than global: without it a
// reset network that pulsed every domain on any single-bit write would pass
// identically. nb_addr must sit in a different SW_RESET_N domain from bit_mask
// (esrc/csrng/edn all share SEP_SW_RESET_N_TRNG_BIT, so their neighbour is a
// non-TRNG block). Returns 1 on failure.
static int check_reset_wire(const char *name, uint32_t bit_mask, uint32_t probe_addr,
                            uint32_t write_val, uint32_t expect_after_rst, const char *nb_name,
                            uint32_t nb_addr, uint32_t nb_val) {
    sep_reset_wr(probe_addr, write_val);
    if (sep_reset_rd(probe_addr) != write_val) {
        sep_mbx_puts("FAIL: probe write did not land: ");
        sep_mbx_puts(name);
        sep_mbx_putc('\n');
        return 1;
    }
    // Neighbour probe, held across the pulse. Confirmed landed first, so a
    // neighbour read of nb_val after the pulse cannot be a write that never
    // took.
    sep_reset_wr(nb_addr, nb_val);
    if (sep_reset_rd(nb_addr) != nb_val) {
        sep_mbx_puts("FAIL: neighbour probe write did not land: ");
        sep_mbx_puts(nb_name);
        sep_mbx_putc('\n');
        return 1;
    }
    // Pulse only this IP's reset bit, then restore the default.
    sep_reset_wr(SEP_RESET_CTRL_SW_RESET_N, SEP_SW_RESET_N_DEFAULT & ~bit_mask);
    sep_reset_wr(SEP_RESET_CTRL_SW_RESET_N, SEP_SW_RESET_N_DEFAULT);
    if (sep_reset_rd(probe_addr) != expect_after_rst) {
        sep_mbx_puts("FAIL: reset wire did not clear probe: ");
        sep_mbx_puts(name);
        sep_mbx_putc('\n');
        return 1;
    }
    if (sep_reset_rd(nb_addr) != nb_val) {
        sep_mbx_puts("FAIL: neighbour domain disturbed: ");
        sep_mbx_puts(name);
        sep_mbx_puts(" reset changed ");
        sep_mbx_puts(nb_name);
        sep_mbx_putc('\n');
        return 1;
    }
    sep_mbx_puts(name);
    sep_mbx_puts(" reset wire OK, neighbour ");
    sep_mbx_puts(nb_name);
    sep_mbx_puts(" survived\n");
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

    errors += check_reset_wire("otbn", SEP_SW_RESET_N_OTBN_BIT, OTBN_INTR_ENABLE_ADDR, 0x1u, 0x0u,
                               "hmac", HMAC_INTR_ENABLE_ADDR, 0x7u);
    errors += check_reset_wire("aes", SEP_SW_RESET_N_AES_BIT, AES_CTRL_AUX_REGWEN_ADDR, 0x0u, 0x1u,
                               "hmac", HMAC_INTR_ENABLE_ADDR, 0x7u);
    errors += check_reset_wire("hmac", SEP_SW_RESET_N_HMAC_BIT, HMAC_INTR_ENABLE_ADDR, 0x7u, 0x0u,
                               "kmac", KMAC_INTR_ENABLE_ADDR, 0x7u);
    errors += check_reset_wire("kmac", SEP_SW_RESET_N_KMAC_BIT, KMAC_INTR_ENABLE_ADDR, 0x7u, 0x0u,
                               "hmac", HMAC_INTR_ENABLE_ADDR, 0x7u);
    errors += check_reset_wire("abr", SEP_SW_RESET_N_ABR_BIT, ABR_GLOBAL_INTR_ENABLE_ADDR, 0x3u, 0x0u,
                               "hmac", HMAC_INTR_ENABLE_ADDR, 0x7u);
    errors += check_reset_wire("esrc", SEP_SW_RESET_N_TRNG_BIT, ESRC_DEBUG_CTRL_ADDR, 0x1u, 0x0u,
                               "hmac", HMAC_INTR_ENABLE_ADDR, 0x7u);
    errors += check_reset_wire("csrng", SEP_SW_RESET_N_TRNG_BIT, CSRNG_INTR_ENABLE_ADDR, 0x1u, 0x0u,
                               "hmac", HMAC_INTR_ENABLE_ADDR, 0x7u);
    errors += check_reset_wire("edn", SEP_SW_RESET_N_TRNG_BIT, EDN_INTR_ENABLE_ADDR, 0x1u, 0x0u,
                               "hmac", HMAC_INTR_ENABLE_ADDR, 0x7u);

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

    // CHK-WDT-PET: WDT is disabled -> count is frozen non-zero; pet -> 0; stays 0.
    uint32_t cnt = wdt_get_count();
    int pet_ok = 1;
    if (cnt == 0u) {
        sep_mbx_puts("FAIL: WDT count 0 before pet (expected non-zero)\n");
        errors++;
        pet_ok = 0;
    }
    wdt_pet();
    if (wdt_get_count() != 0u) {
        sep_mbx_puts("FAIL: WDT pet did not clear count\n");
        errors++;
        pet_ok = 0;
    }
    for (volatile int i = 0; i < 500; i++) {
        __asm__ volatile("nop");
    }
    if (wdt_get_count() != 0u) {
        sep_mbx_puts("FAIL: disabled WDT kept counting\n");
        errors++;
        pet_ok = 0;
    }
    if (pet_ok) {
        sep_mbx_puts("CHK-WDT-PET PASS: count frozen non-zero, pet->0, stays 0 while disabled\n");
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
