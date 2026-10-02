// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP CPU-trace diagnostics firmware: deterministic ground truth for the
// testbench's processor-state monitor (env/sep_cpu_trace_monitor.py).
//
// It exercises exactly the events the monitor reconstructs from the EL2
// retirement trace, then reports the architectural view so the cocotb side can
// cross-check the reconstruction against it:
//   * a >=3-deep noinline call chain (main -> diag_leaf1 -> diag_leaf2 ->
//     diag_leaf3) drives the shadow call stack through real jal/ret pairs;
//   * a forced-uncompressed `ebreak` in the innermost frame takes a breakpoint
//     trap into a firmware-installed mtvec handler, which records
//     mcause/mepc, advances mepc past the ebreak, and mret-returns;
//   * mcause/mepc are printed on the console (sep_mbx_puthex format), giving
//     the cocotb test CSR ground truth for the trap PC to symbolize.
//
// Checks accumulate into `errors`; main() returns it (0 -> PASS magic via
// startup/crt0.s, non-zero -> FAIL).

#include <stdint.h>

#include "sep_mailbox.h"
#include "sep_outbound_filter.h"

static volatile uint32_t g_trap_count;
static volatile uint32_t g_trap_mcause;
static volatile uint32_t g_trap_mepc;

static inline uint32_t csr_read_mcause(void) {
    uint32_t v;
    __asm__ volatile("csrr %0, mcause" : "=r"(v));
    return v;
}

static inline uint32_t csr_read_mepc(void) {
    uint32_t v;
    __asm__ volatile("csrr %0, mepc" : "=r"(v));
    return v;
}

static inline void csr_write_mepc(uint32_t v) {
    __asm__ volatile("csrw mepc, %0" ::"r"(v));
}

static inline void csr_write_mtvec(uint32_t v) {
    __asm__ volatile("csrw mtvec, %0" ::"r"(v));
}

// Machine trap handler (GCC emits the register save/restore and the mret).
// Records the trap, then resumes past the ebreak: the ebreak below is forced
// uncompressed, so the resume PC is architecturally mepc + 4 with no need to
// read back the faulting encoding from ICCM.
static void __attribute__((interrupt, aligned(16))) trap_diag_handler(void) {
    g_trap_mcause = csr_read_mcause();
    g_trap_mepc = csr_read_mepc();
    g_trap_count++;
    csr_write_mepc(g_trap_mepc + 4u);
}

// noinline + post-call arithmetic on every level: each call must be a real
// linking jal (no inlining, no tail call), so the shadow stack sees the full
// chain while the ebreak frame is live.
static uint32_t __attribute__((noinline)) diag_leaf3(uint32_t x) {
    __asm__ volatile(".option push\n\t.option norvc\n\tebreak\n\t.option pop");
    return x + 3u;
}

static uint32_t __attribute__((noinline)) diag_leaf2(uint32_t x) {
    return diag_leaf3(x + 1u) + 1u;
}

static uint32_t __attribute__((noinline)) diag_leaf1(uint32_t x) {
    return diag_leaf2(x + 1u) + 1u;
}

int main(void) {
    int errors = 0;
    volatile uint32_t seed = 0; // volatile: keep the chain unfoldable

    sep_outbound_filter_init();
    sep_mbx_puts("SEP CPU trace diag test\n");

    csr_write_mtvec((uint32_t)&trap_diag_handler);

    // CHK-CHAIN: run the call chain; each level adds its own constant, so the
    // returned value proves every frame actually executed and returned.
    uint32_t v = diag_leaf1(seed);
    if (v != 7u) {
        sep_mbx_puts("FAIL: call chain result ");
        sep_mbx_puthex(v);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_mbx_puts("CHK-CHAIN PASS: v=");
        sep_mbx_puthex(v);
        sep_mbx_putc('\n');
    }

    // CHK-TRAP: exactly one breakpoint trap, taken at the ebreak.
    if (g_trap_count != 1u || g_trap_mcause != 3u) {
        sep_mbx_puts("FAIL: trap count=");
        sep_mbx_puthex(g_trap_count);
        sep_mbx_puts(" mcause=");
        sep_mbx_puthex(g_trap_mcause);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_mbx_puts("CHK-TRAP PASS: mcause=");
        sep_mbx_puthex(g_trap_mcause);
        sep_mbx_puts(" mepc=");
        sep_mbx_puthex(g_trap_mepc);
        sep_mbx_putc('\n');
    }

    return errors;
}
