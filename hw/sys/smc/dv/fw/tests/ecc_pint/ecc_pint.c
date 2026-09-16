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
#include "tt_smc_ecc.h" // include this custom library for ecc error bit generation
#include "tt_smc_interrupts.h"

// define interrupt controllers
struct metal_cpu *cpu;
struct metal_interrupt *cpu_controller;
struct metal_interrupt *plic_controller;
struct metal_buserror *buserrorunit;

// add flags to check which type was caused
volatile bool serviced_sram_error __attribute__((section(".data")));
volatile bool serviced_single_bit_interrupt __attribute__((section(".data")));
volatile bool serviced_double_bit_interrupt __attribute__((section(".data")));

// add DCACHE stress test array
#define DCACHE_STRESS_ARRAY_ELEMENTS \
    20 // this can mess up test as single bit errors can be detected before double bit errors
       // Can also result in double bit error interrupt not being triggered if too low

// add array to stress test the dcache
volatile uint64_t dcache_stress_array[DCACHE_STRESS_ARRAY_ELEMENTS];
volatile uint64_t dcache_stress_array1[DCACHE_STRESS_ARRAY_ELEMENTS];
volatile uint64_t dcache_stress_array2[DCACHE_STRESS_ARRAY_ELEMENTS];
volatile uint64_t dcache_stress_array3[DCACHE_STRESS_ARRAY_ELEMENTS];

// Global variable for SPM address & value
uint32_t spm_addr = 0x80000;
uint64_t true_mem_val;

int main(void) {
    int hartid = metal_cpu_get_current_hartid();

    if (hartid == 0) {

        // /* ************ PLATFORM Interrupt Setup ************** */

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

        // enable the buserror unit
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

        // Set all interrupts to be disabled
        metal_buserror_set_local_interrupt(buserrorunit, METAL_BUSERROR_EVENT_LOAD_STORE_ERROR,
                                           false); // for SRAM errors
        metal_buserror_set_local_interrupt(buserrorunit,
                                           METAL_BUSERROR_EVENT_DATA_CORRECTABLE_ECC_ERROR,
                                           false); // for dcache 1 bit
        metal_buserror_set_local_interrupt(buserrorunit,
                                           METAL_BUSERROR_EVENT_DATA_UNCORRECTABLE_ECC_ERROR,
                                           false); // for dcache 2 bit

        // Set causes to be disabled
        metal_buserror_set_event_enabled(buserrorunit, METAL_BUSERROR_EVENT_LOAD_STORE_ERROR,
                                         false); // for SRAM errors
        metal_buserror_set_event_enabled(buserrorunit,
                                         METAL_BUSERROR_EVENT_DATA_CORRECTABLE_ECC_ERROR,
                                         false); // for dcache 1 bit
        metal_buserror_set_event_enabled(buserrorunit,
                                         METAL_BUSERROR_EVENT_DATA_UNCORRECTABLE_ECC_ERROR,
                                         false); // for dcache 2 bit

        /* ****************** PLATFORM Interrupt setup End **************** */

        // initialize the flags
        serviced_sram_error = false;
        serviced_single_bit_interrupt = false;
        serviced_double_bit_interrupt = false;

        // set the random seed
        write_scratch(hartid, get_seed);
        volatile uint32_t current_scratch_val;
        while (read_scratch(0) == get_seed) {
            continue;
        }
        srand(read_scratch(0));

        /* ************** SRAM PINT Test Start ************** */
        metal_buserror_set_platform_interrupt(buserrorunit, METAL_BUSERROR_EVENT_LOAD_STORE_ERROR,
                                              true); // for SRAM errors
        metal_buserror_set_event_enabled(buserrorunit, METAL_BUSERROR_EVENT_LOAD_STORE_ERROR,
                                         true); // for SRAM errors

        // randomize true_mem_val
        true_mem_val = (((uint64_t)rand() << 48) | ((uint64_t)rand() << 32) |
                        ((uint64_t)rand() << 16) | (uint64_t)rand());
        uint8_t mem_parity = generate_ecc_bits_for_64bit_data(true_mem_val);

        // sync with coco_tb
        write_scratch(1, (uint32_t)(true_mem_val &
                                    0xFFFFFFFF)); // write to scratch the value to be written to SPM
        write_scratch(2, (uint32_t)(true_mem_val >> 32)); // write upper 32 bits to SPM
        write_scratch(3, mem_parity);                     // write the memory parity to scratch
        write_scratch(
            hartid,
            sram_start); // write to scratch to signal for coco_tb to load values in to memory

        // waiting for double bit error to be caught
        while (read_scratch(hartid) == sram_start) {
            read_spm(spm_addr);
        }

        // After interrupt ran for double bit error, poll memory to check for single bit error
        // correction
        while (read_scratch(hartid) == sram_int_done) {
            if (read_spm(spm_addr) == true_mem_val) {
                write_scratch(hartid, sram_doublebit);
            }
        }

        // check if the value is correct
        if ((read_spm(spm_addr) != true_mem_val)) {
            test_fail(hartid);
        }

        metal_buserror_set_platform_interrupt(buserrorunit, METAL_BUSERROR_EVENT_LOAD_STORE_ERROR,
                                              false); // for SRAM errors
        metal_buserror_set_event_enabled(buserrorunit, METAL_BUSERROR_EVENT_LOAD_STORE_ERROR,
                                         false); // for SRAM errors
        /* ************** SRAM PINT Test End ************** */

        /* ************* DCACHE PINT Test Start **************** */
        metal_buserror_set_platform_interrupt(buserrorunit,
                                              METAL_BUSERROR_EVENT_DATA_CORRECTABLE_ECC_ERROR,
                                              true); // for dcache 1 bit
        metal_buserror_set_event_enabled(buserrorunit,
                                         METAL_BUSERROR_EVENT_DATA_CORRECTABLE_ECC_ERROR,
                                         true); // for dcache 1 bit

        // while dcache_singlebit_done is not in scratch reg repeat
        while (read_scratch(hartid) != dcache_singlebit_done) {
            // write to the entire array to fill the dcache, while waiting for interrupt
            for (int i = 0; i < DCACHE_STRESS_ARRAY_ELEMENTS; i++) {
                dcache_stress_array[i] =
                    ((uint64_t)i * 0x987654321ULL) + hartid; // Arbitrary data pattern
                dcache_stress_array1[i] =
                    ((uint64_t)i * 0x123456789ULL) + hartid; // Arbitrary data pattern
            }

            // write to scratch to signal for testbench to do dcache 1 bit error
            write_scratch(hartid, dcache_1bit_start);

            // sum the array to ensure it is not optimized out
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

        // while dcache_doublebit_done is not in scratch reg repeat
        while (read_scratch(hartid) != dcache_doublebit_done) {
            // write to the entire array to fill the dcache, while waiting for interrupt
            for (int i = 0; i < DCACHE_STRESS_ARRAY_ELEMENTS; i++) {
                dcache_stress_array2[i] =
                    ((uint64_t)i * 0x1636634ULL) + hartid; // Arbitrary data pattern
                dcache_stress_array3[i] =
                    ((uint64_t)i * 0x1636634ULL) + hartid; // Arbitrary data pattern
            }

            // write to scratch to signal for testbench to do dcache 2 bit error
            write_scratch(hartid, dcache_2bit_start);

            // sum the array to ensure it is not optimized out
            uint64_t sum = 0;
            for (int i = 0; i < DCACHE_STRESS_ARRAY_ELEMENTS; i++) {
                sum += dcache_stress_array2[i] + dcache_stress_array3[i];
            }
        }

        // check if all errors triggered interrupts
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
        /* ************* DCACHE PINT Test End **************** */

        test_pass(hartid);
    }

    while (true) {
        __asm__("wfi");
    }

    return 0;
}

int other_main() {
    while (true) {
        // For SRAM test, need to read from dcache to write into spm
        // this runs while waiting for interrupt to be called and after it is called
        if (read_scratch(0) == sram_start || read_scratch(0) == sram_doublebit ||
            read_scratch(0) == sram_int_done) {
            read_spm(spm_addr);
        }
        // if you are done with the SRAM test, loop
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
