/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * CPU loads and stores in the CSR window of I3C instance 5.
 *
 * Hart 0 reads HCI_VERSION and HC_CONTROL, sets HC_CONTROL.BUS_ENABLE and reads
 * it back, then writes the reset word back and reads that. Each value read is
 * published in a CPU_CTRL SCRATCH word, so the bench compares it against the
 * vendor RDL as well as this image.
 *
 * The window sees exactly four loads and two stores. The bench counts the
 * accesses completed at each I3C core's CSR port and requires that figure on
 * instance 5 and none on the other five.
 */

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

#define I3C_INSTANCE 5
#define I3C_CSR_BASE ((uint64_t)SMC_TOP_OCA_I3C_WRAP_I3C_CSR_BASE_ADDR(I3C_INSTANCE))

/* Offsets and reset words from the I3C core's base_registers.rdl. */
#define HCI_VERSION (I3C_CSR_BASE + 0x000u)
#define HC_CONTROL (I3C_CSR_BASE + 0x004u)
#define HCI_VERSION_RESET 0x00000120u
#define HC_CONTROL_RESET 0x00000040u /* MODE_SELECTOR = 1 */
#define HC_CONTROL_BUS_ENABLE (1u << 31)

/* SCRATCH words the bench reads after PASS. */
#define SCRATCH_HCI_VERSION 4
#define SCRATCH_HC_CONTROL_ENTRY 5
#define SCRATCH_HC_CONTROL_ENABLED 6
#define SCRATCH_HC_CONTROL_RESTORED 7

static inline void io_fence(void) {
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

static void expect(uint32_t got, uint32_t want, const char *what) {
    if (got != want) {
        info_msg_hex32_s(0, "expected ", want);
        raise_fatal_hex32_s(0, what, got);
    }
}

int main(void) {
    int hartid = metal_cpu_get_current_hartid();

    if (hartid == 0) {
        uint32_t version = read_reg(HCI_VERSION);
        write_scratch(SCRATCH_HCI_VERSION, version);
        expect(version, HCI_VERSION_RESET, "I3C5 HCI_VERSION reads ");
        info_msg_hex32_s(0, "I3C5 HCI_VERSION ", version);

        uint32_t entry = read_reg(HC_CONTROL);
        write_scratch(SCRATCH_HC_CONTROL_ENTRY, entry);
        expect(entry, HC_CONTROL_RESET, "I3C5 HC_CONTROL at entry reads ");

        write_reg(HC_CONTROL, entry | HC_CONTROL_BUS_ENABLE);
        io_fence();
        uint32_t enabled = read_reg(HC_CONTROL);
        write_scratch(SCRATCH_HC_CONTROL_ENABLED, enabled);
        expect(enabled, entry | HC_CONTROL_BUS_ENABLE, "I3C5 HC_CONTROL after BUS_ENABLE reads ");
        info_msg_hex32_s(0, "I3C5 HC_CONTROL with BUS_ENABLE ", enabled);

        write_reg(HC_CONTROL, entry);
        io_fence();
        uint32_t restored = read_reg(HC_CONTROL);
        write_scratch(SCRATCH_HC_CONTROL_RESTORED, restored);
        expect(restored, entry, "I3C5 HC_CONTROL after restore reads ");
        info_msg_hex32_s(0, "I3C5 HC_CONTROL restored ", restored);

        test_pass(0);
    }

    while (true) {
        __asm__("wfi");
    }
}

int secondary_main(void) {
    return main();
}
