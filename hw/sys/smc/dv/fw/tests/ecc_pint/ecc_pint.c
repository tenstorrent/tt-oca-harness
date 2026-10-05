/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>
#include <stdlib.h>

#include "metal/cpu.h"
#include "metal/drivers/sifive_buserror0.h"
#include "metal/drivers/riscv_cpu.h"
#include "metal/interrupt.h"
#include "smc_io.h"
#include "smc_test.h"
#include "tt_smc_ecc.h" // ECC encoder and bus error interrupt handler
#include "tt_smc_interrupts.h"

struct metal_cpu *cpu;
struct metal_interrupt *cpu_controller;
struct metal_interrupt *plic_controller;
struct metal_buserror *buserrorunit;

// Set by the bus error handler for each error type it services
volatile bool serviced_sram_error __attribute__((section(".data")));
volatile bool serviced_single_bit_interrupt __attribute__((section(".data")));
volatile bool serviced_double_bit_interrupt __attribute__((section(".data")));

/* Too many elements lets a single-bit error be detected before the double-bit
 * error; too few may not raise the double-bit error interrupt at all. */
#define DCACHE_STRESS_ARRAY_ELEMENTS 20

// Data that keeps the data cache busy while the testbench injects errors
volatile uint64_t dcache_stress_array[DCACHE_STRESS_ARRAY_ELEMENTS];
volatile uint64_t dcache_stress_array1[DCACHE_STRESS_ARRAY_ELEMENTS];
volatile uint64_t dcache_stress_array2[DCACHE_STRESS_ARRAY_ELEMENTS];
volatile uint64_t dcache_stress_array3[DCACHE_STRESS_ARRAY_ELEMENTS];

// Scratchpad word under test and the value it must hold
uint32_t spm_addr = 0x80000;
uint64_t true_mem_val;

int main(void) {
    int hartid = metal_cpu_get_current_hartid();

    if (hartid == 0) {

        // setup CPU & CPU interrupt controller
        cpu = metal_cpu_get(hartid);
        if (cpu == NULL) {
            test_fail(hartid);
        }
        cpu_controller = metal_cpu_interrupt_controller(cpu);
        if (cpu_controller == NULL) {
            test_fail(hartid);
        }
        metal_interrupt_init(cpu_controller);
        if (metal_interrupt_enable(cpu_controller, METAL_INTERRUPT_ID_BASE) != 0) {
            test_fail(hartid);
        }

        // Route bus error unit interrupts to the handler
        buserrorunit = metal_cpu_get_buserror(cpu);
        if (buserrorunit == NULL) {
            test_fail(hartid);
        }

        if (metal_interrupt_register_handler(cpu_controller, METAL_INTERRUPT_ID_EXT,
                                             beu_interrupt_handler, buserrorunit) != 0) {
            test_fail(hartid);
        }

        // Setup PLIC & PLIC interrupt Controller
        plic_controller = metal_interrupt_get_controller(METAL_PLIC_CONTROLLER, 0);
        plic_init(0);
        int plic_int_id = metal_buserror_get_platform_interrupt_id(buserrorunit);
        metal_interrupt_enable(plic_controller, plic_int_id);
        metal_interrupt_register_handler(plic_controller, plic_int_id, beu_interrupt_handler,
                                         buserrorunit);

        // Start with the local error interrupts and every error event disabled
        metal_buserror_set_local_interrupt(buserrorunit, METAL_BUSERROR_EVENT_LOAD_STORE_ERROR,
                                           false); // for SRAM errors
        metal_buserror_set_local_interrupt(buserrorunit,
                                           METAL_BUSERROR_EVENT_DATA_CORRECTABLE_ECC_ERROR,
                                           false); // for dcache 1 bit
        metal_buserror_set_local_interrupt(buserrorunit,
                                           METAL_BUSERROR_EVENT_DATA_UNCORRECTABLE_ECC_ERROR,
                                           false); // for dcache 2 bit

        metal_buserror_set_event_enabled(buserrorunit, METAL_BUSERROR_EVENT_LOAD_STORE_ERROR,
                                         false); // for SRAM errors
        metal_buserror_set_event_enabled(buserrorunit,
                                         METAL_BUSERROR_EVENT_DATA_CORRECTABLE_ECC_ERROR,
                                         false); // for dcache 1 bit
        metal_buserror_set_event_enabled(buserrorunit,
                                         METAL_BUSERROR_EVENT_DATA_UNCORRECTABLE_ECC_ERROR,
                                         false); // for dcache 2 bit

        serviced_sram_error = false;
        serviced_single_bit_interrupt = false;
        serviced_double_bit_interrupt = false;

        // Wait for the testbench to replace the seed request with a seed
        write_scratch(hartid, get_seed);
        while (read_scratch(0) == get_seed) {
            continue;
        }
        srand(read_scratch(0));

        /* SRAM ECC error */
        metal_buserror_set_platform_interrupt(buserrorunit, METAL_BUSERROR_EVENT_LOAD_STORE_ERROR,
                                              true); // for SRAM errors
        metal_buserror_set_event_enabled(buserrorunit, METAL_BUSERROR_EVENT_LOAD_STORE_ERROR,
                                         true); // for SRAM errors

        true_mem_val = (((uint64_t)rand() << 48) | ((uint64_t)rand() << 32) |
                        ((uint64_t)rand() << 16) | (uint64_t)rand());
        uint8_t mem_parity = generate_ecc_bits_for_64bit_data(true_mem_val);

        // Hand the data word and its ECC byte to the testbench, then ask it to load them
        write_scratch(1, (uint32_t)(true_mem_val & 0xFFFFFFFF));
        write_scratch(2, (uint32_t)(true_mem_val >> 32));
        write_scratch(3, mem_parity);
        write_scratch(hartid, sram_start);

        // Read the scratchpad until the double-bit error interrupt is serviced
        while (read_scratch(hartid) == sram_start) {
            read_spm(spm_addr);
        }

        // Then read until the word comes back corrected, and tell the testbench
        while (read_scratch(hartid) == sram_int_done) {
            if (read_spm(spm_addr) == true_mem_val) {
                write_scratch(hartid, sram_doublebit);
            }
        }

        if ((read_spm(spm_addr) != true_mem_val)) {
            test_fail(hartid);
        }

        metal_buserror_set_platform_interrupt(buserrorunit, METAL_BUSERROR_EVENT_LOAD_STORE_ERROR,
                                              false); // for SRAM errors
        metal_buserror_set_event_enabled(buserrorunit, METAL_BUSERROR_EVENT_LOAD_STORE_ERROR,
                                         false); // for SRAM errors

        /* Data-cache ECC errors */
        metal_buserror_set_platform_interrupt(buserrorunit,
                                              METAL_BUSERROR_EVENT_DATA_CORRECTABLE_ECC_ERROR,
                                              true); // for dcache 1 bit
        metal_buserror_set_event_enabled(buserrorunit,
                                         METAL_BUSERROR_EVENT_DATA_CORRECTABLE_ECC_ERROR,
                                         true); // for dcache 1 bit

        // Exercise the data cache until the single-bit error interrupt is serviced
        while (read_scratch(hartid) != dcache_singlebit_done) {
            for (int i = 0; i < DCACHE_STRESS_ARRAY_ELEMENTS; i++) {
                dcache_stress_array[i] = ((uint64_t)i * 0x987654321ULL) + hartid;
                dcache_stress_array1[i] = ((uint64_t)i * 0x123456789ULL) + hartid;
            }

            // Request a single-bit data-cache error
            write_scratch(hartid, dcache_1bit_start);

            // Read the arrays back through the data cache
            uint64_t sum = 0;
            for (int i = 0; i < DCACHE_STRESS_ARRAY_ELEMENTS; i++) {
                sum += dcache_stress_array[i] + dcache_stress_array1[i];
            }
        }

        metal_buserror_set_platform_interrupt(buserrorunit,
                                              METAL_BUSERROR_EVENT_DATA_CORRECTABLE_ECC_ERROR,
                                              false); // for dcache 1 bit
        metal_buserror_set_event_enabled(buserrorunit,
                                         METAL_BUSERROR_EVENT_DATA_CORRECTABLE_ECC_ERROR,
                                         false); // for dcache 1 bit

        metal_buserror_set_platform_interrupt(buserrorunit,
                                              METAL_BUSERROR_EVENT_DATA_UNCORRECTABLE_ECC_ERROR,
                                              true); // for dcache 2 bit
        metal_buserror_set_event_enabled(buserrorunit,
                                         METAL_BUSERROR_EVENT_DATA_UNCORRECTABLE_ECC_ERROR,
                                         true); // for dcache 2 bit

        // Exercise the data cache until the double-bit error interrupt is serviced
        while (read_scratch(hartid) != dcache_doublebit_done) {
            for (int i = 0; i < DCACHE_STRESS_ARRAY_ELEMENTS; i++) {
                dcache_stress_array2[i] = ((uint64_t)i * 0x1636634ULL) + hartid;
                dcache_stress_array3[i] = ((uint64_t)i * 0x1636634ULL) + hartid;
            }

            // Request a double-bit data-cache error
            write_scratch(hartid, dcache_2bit_start);

            // Read the arrays back through the data cache
            uint64_t sum = 0;
            for (int i = 0; i < DCACHE_STRESS_ARRAY_ELEMENTS; i++) {
                sum += dcache_stress_array2[i] + dcache_stress_array3[i];
            }
        }

        // Every injected error must have raised its interrupt
        if (!((serviced_single_bit_interrupt && serviced_double_bit_interrupt) &&
              serviced_sram_error)) {
            test_fail(hartid);
        }

        metal_buserror_set_platform_interrupt(buserrorunit,
                                              METAL_BUSERROR_EVENT_DATA_UNCORRECTABLE_ECC_ERROR,
                                              false); // for dcache 2 bit
        metal_buserror_set_event_enabled(buserrorunit,
                                         METAL_BUSERROR_EVENT_DATA_UNCORRECTABLE_ECC_ERROR,
                                         false); // for dcache 2 bit

        test_pass(hartid);
    }

    while (true) {
        __asm__("wfi");
    }
}

int other_main() {
    while (true) {
        // Keep reading the scratchpad while the SRAM phase runs
        if (read_scratch(0) == sram_start || read_scratch(0) == sram_doublebit ||
            read_scratch(0) == sram_int_done) {
            read_spm(spm_addr);
        }
        // Idle once the data-cache phase starts
        if (read_scratch(0) == dcache_1bit_start) {
            __asm__("wfi");
        }
    }
}

int secondary_main(void) {

    int hartid = metal_cpu_get_current_hartid();

    if (hartid == 0) {
        return main();
    } else {
        return other_main();
    }
}
