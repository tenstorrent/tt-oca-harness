/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include "tt_smc_interrupts.h"

#include "metal/cpu.h"
#include "riscv_plic0.h"

void plic_init(uint8_t core_id) {
    struct metal_cpu *cpu = metal_cpu_get(core_id);
    struct metal_interrupt *cpu_ctrl = metal_cpu_interrupt_controller(cpu);
    metal_interrupt_init(cpu_ctrl);
    metal_interrupt_enable(cpu_ctrl, METAL_INTERRUPT_ID_EXT);

    struct metal_interrupt *plic = metal_interrupt_get_controller(METAL_PLIC_CONTROLLER, core_id);
    metal_interrupt_init(plic);
    metal_interrupt_set_threshold(plic, 0);
}

void global_interrupt_enable(void) {
    __metal_interrupt_global_enable();
}
