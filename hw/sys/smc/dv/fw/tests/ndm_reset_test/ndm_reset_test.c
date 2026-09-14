/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "metal/interrupt.h"
#include "metal/cpu.h"
#include "metal/drivers/riscv_cpu.h"
#include "smc_io.h"
#include "smc_test.h"
#include "virt_console.h"

// NDM reset interrupt: peripheral_interrupts[11] = cpu_interrupts_o[267] (4-core,
// NUM_EXT_INTERRUPTS=256) PLIC interrupt IDs are offset by 1 (ID 0 means "no interrupt")
#define NDM_RESET_PLIC_ID (268)

// Flag to indicate interrupt was received
volatile int ndm_interrupt_received = 0;

void ndm_interrupt_handler(int id, void *priv) {
    info_msg_s(0, "NDM reset interrupt handler invoked");

    uint32_t ndmreset_request =
        read_reg(SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_REQUEST_BASE_ADDR);

    uint32_t timeout = 1000; // Timeout after 1000 iterations
    while (ndmreset_request != 0 && timeout > 0) {
        info_msg_hex32_s(0, "Writing most up-to-date ndmreset_request value to ndmreset_process: ",
                         ndmreset_request);
        write_reg(SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_PROCESS_BASE_ADDR, ndmreset_request);
        ndmreset_request = read_reg(SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_REQUEST_BASE_ADDR);
        timeout--;
    }

    if (timeout == 0) {
        // Do not set ndm_interrupt_received — handshake incomplete must not reach test_pass.
        raise_fatal_s(0, "NDM reset handshake timeout in handler");
    }

    write_reg(SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_PROCESS_BASE_ADDR, 0);
    info_msg_s(0, "Cleared ndmreset_process");

    // Signal that interrupt was received and handshake completed
    ndm_interrupt_received = 1;
}

static void reset_plic_enable_registers() {
    simputs("Clearing PLIC registers\n");
    for (uint64_t addr = SMC_TOP_SMC_CLUSTER_PLIC_CORE0_MEIP_ENABLE_BASE_ADDR(0);
         addr <= SMC_TOP_SMC_CLUSTER_PLIC_CORE3_SEIP_ENABLE_BASE_ADDR(5); addr += 4) {
        write_reg(addr, 0x0);
    }

    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE0_MEIP_THRESHOLD_BASE_ADDR, 0x0);
    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE0_SEIP_THRESHOLD_BASE_ADDR, 0x0);
    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE1_MEIP_THRESHOLD_BASE_ADDR, 0x0);
    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE1_SEIP_THRESHOLD_BASE_ADDR, 0x0);
    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE2_MEIP_THRESHOLD_BASE_ADDR, 0x0);
    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE2_SEIP_THRESHOLD_BASE_ADDR, 0x0);
    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE3_MEIP_THRESHOLD_BASE_ADDR, 0x0);
    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE3_SEIP_THRESHOLD_BASE_ADDR, 0x0);
}

int main(void) {
    // reset scratch registers
    write_scratch(0, 0x0);
    write_scratch(4, 0x0);

    int hartid = metal_cpu_get_current_hartid();

    struct metal_interrupt *plic_controller;
    struct metal_cpu *cpu;
    struct metal_interrupt *cpu_controller;

    info_msg_s(hartid, "Starting NDM reset test");

    // Get PLIC interrupt controller
    plic_controller = metal_interrupt_get_controller(METAL_PLIC_CONTROLLER, hartid);

    cpu = metal_cpu_get(0);
    cpu_controller = metal_cpu_interrupt_controller(cpu);

    // Enable interrupts in the CPU
    metal_interrupt_init(cpu_controller);
    metal_interrupt_enable(cpu_controller, METAL_INTERRUPT_ID_BASE);
    metal_interrupt_register_handler(cpu_controller, METAL_INTERRUPT_ID_EXT, ndm_interrupt_handler,
                                     (void *)plic_controller);

    info_msg_s(hartid, "Enabled CPU interrupt controller");

    // Init the PLIC and register interrupt handler
    metal_interrupt_init(plic_controller);
    info_msg_s(hartid, "initialized PLIC controller");

    // Reset PLIC registers
    reset_plic_enable_registers();
    info_msg_s(hartid, "Reset PLIC registers");

    // Register and enable NDM reset interrupt
    metal_interrupt_set_priority(plic_controller, NDM_RESET_PLIC_ID, 1);
    if (metal_interrupt_register_handler(plic_controller, NDM_RESET_PLIC_ID, ndm_interrupt_handler,
                                         (void *)plic_controller) != 0) {
        raise_fatal_s(hartid, "Failed to register NDM interrupt handler");
        test_fail(hartid);
        return 0;
    }
    info_msg_s(hartid, "Set NDM interrupt handler");
    metal_interrupt_enable(plic_controller, NDM_RESET_PLIC_ID);
    info_msg_s(hartid, "Enabled NDM interrupt in PLIC");

    info_msg_s(hartid, "NDM interrupt registered and enabled");

    // Enable global interrupts
    __metal_interrupt_global_enable();

    // Signal to testbench that interrupt setup is complete
    info_msg_s(hartid, "Writing 0xDEADBEEF to scratch 4 - interrupt setup done");
    write_scratch(4, 0xDEADBEEF);

    uint8_t num_cpu_clusters =
        read_reg(SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_CLUSTER_COUNT_BASE_ADDR) & 0xFF;
    info_msg_hex32_s(0, "Number of CPU Clusters are: ", num_cpu_clusters);

    // Wait for interrupt
    info_msg_s(hartid, "Waiting for NDM reset interrupt...");
    while (ndm_interrupt_received == 0) {
        __asm__ volatile("wfi");
    }

    // Test passed
    info_msg_s(hartid, "NDM reset test completed successfully");
    test_pass(hartid);

    return 0;
}

int other_main(int hartid) {
    while (1) {
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
