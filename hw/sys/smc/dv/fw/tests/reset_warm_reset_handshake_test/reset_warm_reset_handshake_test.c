/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "metal/cpu.h"
#include "smc_io.h"
#include "smc_test.h"
#include "virt_console.h"

// Warm reset handshake: a subsystem's reset-complete falls and rises while its warm reset is held
//
// Scratch protocol (scratch[1]):
//   0xC7000000 | (ss_idx << 8) | stage
// stages:
//   0x01: warm reset asserted (waiting for ss_reset_complete to go low)
//   0x02: observed ss_reset_complete low (waiting for it to reassert high)
//   0x03: observed ss_reset_complete high (handshake done)
//   0x04: warm reset deasserted (complete)
//
// Done marker:
//   0xC700FFAA

static inline void set_stage(uint32_t ss_idx, uint32_t stage) {
    write_scratch(1, 0xC7000000u | ((ss_idx & 0xFFu) << 8) | (stage & 0xFFu));
}

static inline uint32_t get_ss_complete_bit(uint32_t ss_idx) {
    return (read_reg(SMC_TOP_SMC_RESET_UNIT_SS_RESET_COMPLETE_BASE_ADDR) >> ss_idx) & 0x1u;
}

/* Bound for each half of the handshake.
 *
 * `ss_reset_complete_i` is a TB pin, not something the SMC wrapper drives, so
 * an absent peer responder must be reported rather than waited on.
 */
#define SS_COMPLETE_BOUND 200000u

static void warm_reset_handshake(int hartid, uint32_t ss_idx) {
    info_msg_hex32_s(hartid, "Warm reset handshake start ss_idx=", ss_idx);

    // Assert warm reset (active low) for the chosen subsystem
    uint32_t warm_reset_n = read_reg(SMC_TOP_SMC_RESET_UNIT_SS_WARM_RESET_N_BASE_ADDR);
    warm_reset_n &= ~(1u << ss_idx);
    write_reg(SMC_TOP_SMC_RESET_UNIT_SS_WARM_RESET_N_BASE_ADDR, warm_reset_n);

    set_stage(ss_idx, 0x01);

    // Wait for subsystem to indicate reset in-progress by deasserting complete (1->0)
    uint32_t i;

    for (i = 0; i < SS_COMPLETE_BOUND; i++) {
        if (get_ss_complete_bit(ss_idx) == 0u) {
            break;
        }
        __asm__ volatile("nop");
    }
    if (i == SS_COMPLETE_BOUND) {
        raise_error_s(hartid, "SS_RESET_COMPLETE never fell after warm reset asserted");
        info_msg_hex32_s(hartid, "  ss_idx=", ss_idx);
        return;
    }

    set_stage(ss_idx, 0x02);

    // Wait for subsystem to indicate reset complete by reasserting complete (0->1)
    for (i = 0; i < SS_COMPLETE_BOUND; i++) {
        if (get_ss_complete_bit(ss_idx) == 1u) {
            break;
        }
        __asm__ volatile("nop");
    }
    if (i == SS_COMPLETE_BOUND) {
        raise_error_s(hartid, "SS_RESET_COMPLETE never rose again after the reset window");
        info_msg_hex32_s(hartid, "  ss_idx=", ss_idx);
        return;
    }

    set_stage(ss_idx, 0x03);

    // Deassert warm reset
    warm_reset_n = read_reg(SMC_TOP_SMC_RESET_UNIT_SS_WARM_RESET_N_BASE_ADDR);
    warm_reset_n |= (1u << ss_idx);
    write_reg(SMC_TOP_SMC_RESET_UNIT_SS_WARM_RESET_N_BASE_ADDR, warm_reset_n);

    set_stage(ss_idx, 0x04);

    info_msg_hex32_s(hartid, "Warm reset handshake done ss_idx=", ss_idx);
}

int main(void) {
    int hartid = metal_cpu_get_current_hartid();

    init_test(hartid);

    write_scratch(0, 0x0);
    write_scratch(1, 0x0);

    // Ensure warm reset is deasserted for all subsystems before starting.
    write_reg(SMC_TOP_SMC_RESET_UNIT_SS_WARM_RESET_N_BASE_ADDR, 0xFFFFFFFFu);

    warm_reset_handshake(hartid, 0);
    warm_reset_handshake(hartid, 1);

    // Signal completion to testbench.
    write_scratch(1, 0xC700FFAAu);

    end_test(hartid);
    return 0;
}

int other_main(int hartid) {
    while (true) {
        __asm__("wfi");
    }
}

int secondary_main(void) {
    int hartid = metal_cpu_get_current_hartid();
    if (hartid == 0) {
        return main();
    } else {
        return other_main(hartid);
    }
}
