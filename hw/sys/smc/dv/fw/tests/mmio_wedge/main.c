/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "metal/cpu.h"
#include "smc.h"
#include "smc_test.h"

#define MMIO_WEDGE_EXT_ADDR 0xB0000000ull

/* Last cache line of the 1 MiB SPM, above this image, stacks, and heap. */
#define PHASE_FLAG_ADDR (SMC_TOP_SPM_MEMORY_BASE_ADDR + SMC_TOP_SPM_MEMORY_SIZE - 0x40u)
#define GO_FLAG_ADDR (PHASE_FLAG_ADDR + 8u)

#define PHASE2_MAGIC 0x1501C0DEu
#define GO_READ_MAGIC 0x1501600Du
#define GO_WRITE_MAGIC 0x1501600Eu
#define MMIO_RECOVERY_READ_DATA 0x1501CAFEu
#define MMIO_RECOVERY_WRITE_DATA 0x1501FACEu

#define STATUS_PHASE1_READY 0x15010001u
#define STATUS_PHASE1_BROKE 0x1501DEADu
#define STATUS_PHASE2_BOOT 0x15010002u
#define STATUS_PHASE2_DONE 0x15010003u

static inline void io_fence(void) {
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

static void phase1_wedge(void) {
    volatile uint64_t *const phase = (volatile uint64_t *)(uintptr_t)PHASE_FLAG_ADDR;
    volatile uint64_t *const go = (volatile uint64_t *)(uintptr_t)GO_FLAG_ADDR;

    *phase = PHASE2_MAGIC;
    write_scratch(1, STATUS_PHASE1_READY);
    io_fence();

    uint64_t flavor;
    do {
        flavor = *go;
    } while (flavor != GO_READ_MAGIC && flavor != GO_WRITE_MAGIC);
    io_fence();

    if (flavor == GO_WRITE_MAGIC) {
        *(volatile uint64_t *)(uintptr_t)MMIO_WEDGE_EXT_ADDR = 0x1501BEEFu;
        io_fence();
    } else {
        volatile uint64_t sink = *(volatile uint64_t *)(uintptr_t)MMIO_WEDGE_EXT_ADDR;
        (void)sink;
    }

    write_scratch(1, STATUS_PHASE1_BROKE);
    for (;;) {
        __asm__ volatile("wfi");
    }
}

static void phase2_recovery(int hartid) {
    volatile uint64_t *const go = (volatile uint64_t *)(uintptr_t)GO_FLAG_ADDR;
    uint64_t flavor = *go;

    write_scratch(1, STATUS_PHASE2_BOOT);
    io_fence();

    uint64_t timeout = read64_reg(SMC_TOP_SMC_CPU_CTRL_RESET_TIMEOUT_BASE_ADDR);
    info_msg_hex32_s(hartid, "phase2 RESET_TIMEOUT: ", (uint32_t)timeout);

    if (flavor == GO_READ_MAGIC) {
        uint64_t ext = *(volatile uint64_t *)(uintptr_t)MMIO_WEDGE_EXT_ADDR;
        info_msg_hex32_s(hartid, "phase2 external read: ", (uint32_t)ext);
        if (ext != MMIO_RECOVERY_READ_DATA) {
            raise_fatal_hex32_s(hartid, "phase2 external read mismatch: ", (uint32_t)ext);
        }
    } else if (flavor == GO_WRITE_MAGIC) {
        *(volatile uint64_t *)(uintptr_t)MMIO_WEDGE_EXT_ADDR = MMIO_RECOVERY_WRITE_DATA;
        io_fence();
    } else {
        raise_fatal_hex32_s(hartid, "phase2 unknown flavor: ", (uint32_t)flavor);
    }

    write_scratch(1, STATUS_PHASE2_DONE);
    io_fence();
    end_test(hartid);
}

int main(void) {
    int hartid = metal_cpu_get_current_hartid();
    volatile uint64_t *const phase = (volatile uint64_t *)(uintptr_t)PHASE_FLAG_ADDR;
    uint64_t phase_value = *phase;

    init_test(hartid);
    if (phase_value == PHASE2_MAGIC) {
        phase2_recovery(hartid);
    } else {
        phase1_wedge();
    }
    return 0;
}

static int other_main(void) {
    for (;;) {
        __asm__ volatile("wfi");
    }
    return 0;
}

int secondary_main(void) {
    return metal_cpu_get_current_hartid() == 0 ? main() : other_main();
}
