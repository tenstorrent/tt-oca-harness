/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief OCTS P0 SEC Test - DUT as PRIMARY, BFM as SECONDARY
 *
 * PRIMARY/SECONDARY OCTS synchronization test.
 *
 * The OCTS SECONDARY datapath cannot be exercised with the DUT strapped SECONDARY in
 * this single-DUT-firmware testbench: the RTL SECONDARY trips ExpectedCountValid_A the
 * instant it sees a credit before being enabled by a sync_load, and that ordering cannot
 * be guaranteed across two independently-booting chiplets. This test therefore runs the
 * DUT as OCTS PRIMARY and the master-BFM chiplet as OCTS SECONDARY (booting the
 * st_octs_p1_credit_test ROM). The DUT PRIMARY generates the sync_load / credit stream on
 * GPIO[58:59]; the BFM SECONDARY receives and tracks it. The cocotb checker
 * (check_primary_secondary_sync) performs the cross-chiplet verification (sync_load/credit
 * alignment + timer_count tracking within a margin), and this firmware reports its own
 * PRIMARY verdict in scratch[0].
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_defines.h"
#include "smc_test.h"
#include "virt_console.h"

#define WAIT_CYCLES 50

static void wait_cycles(uint32_t cycles) {
    for (volatile uint32_t i = 0; i < cycles; i++) {
        __asm__ volatile("nop");
    }
}

static uint64_t timer_get_count(void) {
    uint32_t count_lo, count_hi;

    count_lo = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_COUNT_LO_BASE_ADDR);
    count_hi = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_COUNT_HI_BASE_ADDR);

    return ((uint64_t)count_hi << 32) | count_lo;
}

static uint32_t timer_is_primary(void) {
    uint32_t status = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_STATUS_BASE_ADDR);
    return (status & 0x1) == 0; // Bit 0: 0=PRIMARY, 1=SECONDARY
}

static void timer_init(void) {
    uint32_t ctrl_val;

    simputs("Initializing OCTS PRIMARY timer (octs_p0_sec)\n");

    // CTRL: STEP<<16 | PULSE_WIDTH<<8 | CREDIT_VAL. CREDIT_VAL=0x10, PULSE_WIDTH=0x02,
    // STEP=0x01 (matches the BFM SECONDARY ROM so the SECONDARY tracks cleanly).
    write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CTRL_BASE_ADDR, 0x00010210);

    ctrl_val = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CTRL_BASE_ADDR);
    if (ctrl_val != 0x00010210) {
        simputs("ERROR: CTRL register not set correctly\n");
        write_scratch(0, 0xBAD00000u | ctrl_val);
        test_fail(0);
        while (1) {
            __asm__ volatile("nop");
        }
    }

    // Enable GPIO pad lsio interface so the PRIMARY sync_load / credit pulses are driven
    // onto GPIO[58:59] (and to prevent X-prop on reset).
    write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_GPIO_ENABLE_BASE_ADDR, 1);
    wait_cycles(10);
    uint32_t gpio_enable_val = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_GPIO_ENABLE_BASE_ADDR);
    if ((gpio_enable_val & 0x1) != 1) {
        simputs("ERROR: TIMER_GPIO_ENABLE register not set correctly\n");
        write_scratch(0, 0xBAD00005u | gpio_enable_val);
        test_fail(0);
        while (1) {
            __asm__ volatile("nop");
        }
    }
    simputs("TIMER_GPIO_ENABLE register initialized: 0x1\n");
}

static void timer_start(uint64_t preset_value) {
    uint32_t preset_lo, preset_hi;
    uint64_t preset_read;

    simputs("Starting OCTS PRIMARY timer\n");

    write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_LO_BASE_ADDR,
              (uint32_t)(preset_value & 0xFFFFFFFF));
    write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_HI_BASE_ADDR,
              (uint32_t)(preset_value >> 32));

    preset_lo = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_LO_BASE_ADDR);
    preset_hi = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_HI_BASE_ADDR);
    preset_read = ((uint64_t)preset_hi << 32) | preset_lo;
    if (preset_read != preset_value) {
        simputs("ERROR: PRESET register not set correctly\n");
        write_scratch(0, 0xBAD00001u);
        test_fail(0);
        while (1) {
            __asm__ volatile("nop");
        }
    }

    if (!timer_is_primary()) {
        simputs("ERROR: Timer is not in PRIMARY mode\n");
        write_scratch(0, 0xBAD00002u);
        test_fail(0);
        while (1) {
            __asm__ volatile("nop");
        }
    }

    // Start the PRIMARY timer: hardware emits the sync_load pulse then the credit stream.
    write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_START_BASE_ADDR, 1);

    simputs("PRIMARY timer started successfully\n");
    wait_cycles(50);
    uint64_t count_after = timer_get_count();
    simputshex64("PRIMARY timer count: ", count_after);
}

int main(void) {
    write_scratch(0, 0xcccccccc);
    simputs("octs_p0_sec_test - DUT PRIMARY mode\n");

    wait_cycles(50);

    timer_init();
    write_scratch(0, 0xebedebe4);

    simputs("Starting Test: PRIMARY timer sync/credit generation\n");
    timer_start(0x1000ULL);
    write_scratch(0, 0x01);

    // Confirm the PRIMARY timer counter is advancing (i.e. it is running and driving the
    // sync/credit stream to the SECONDARY).
    wait_cycles(2000);
    uint64_t count1 = timer_get_count();
    simputshex64("PRIMARY count check 1: ", count1);
    wait_cycles(200);
    uint64_t count2 = timer_get_count();
    simputshex64("PRIMARY count check 2: ", count2);

    if (count2 <= count1) {
        simputs("ERROR: PRIMARY counter not incrementing\n");
        write_scratch(0, 0xBAD30005u);
        test_fail(0);
        while (1) {
            __asm__ volatile("nop");
        }
    }

    simputs("All tests passed\n");
    write_scratch(0, 0xacafaca1);
    wait_cycles(5);

    test_pass(0);

    while (1) {
        __asm__("wfi");
    }

    return 0;
}

int other_main(int hartid) {
    (void)hartid;
    while (1) {
        __asm__("wfi");
    }
    return 0;
}

int secondary_main(void) {
    int hartid = metal_cpu_get_current_hartid();
    if (hartid == 0) {
        return main();
    } else {
        return other_main(hartid);
    }
}
