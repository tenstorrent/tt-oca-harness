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
#define HCI_VERSION \
    ((uint64_t)SMC_TOP_OCA_I3C_WRAP_I3C_CSR_I3CBASE_HCI_VERSION_BASE_ADDR(I3C_INSTANCE))
#define HC_CONTROL \
    ((uint64_t)SMC_TOP_OCA_I3C_WRAP_I3C_CSR_I3CBASE_HC_CONTROL_BASE_ADDR(I3C_INSTANCE))

/* Field macros generated from the I3C core's base_registers.rdl. */
#define I3C_BASEREGS(name) \
    BASEREGS_PIO_OFFSET_80_EXT_OFFSET_100_DAT_TABLE_SIZE_7F_DAT_OFFSET_400_DCT_TABLE_SIZE_7F_DCT_OFFSET_800_MIPI_COMMANDS_35__##name
#define HC_CONTROL_FIELD_RESET(field) \
    ((uint32_t)I3C_BASEREGS(HC_CONTROL__##field##_reset) << I3C_BASEREGS(HC_CONTROL__##field##_bp))

#define HCI_VERSION_RESET ((uint32_t)I3C_BASEREGS(HCI_VERSION__VERSION_reset))
#define HC_CONTROL_RESET \
    (HC_CONTROL_FIELD_RESET(IBA_INCLUDE) | HC_CONTROL_FIELD_RESET(AUTOCMD_DATA_RPT) | \
     HC_CONTROL_FIELD_RESET(DATA_BYTE_ORDER_MODE) | HC_CONTROL_FIELD_RESET(MODE_SELECTOR) | \
     HC_CONTROL_FIELD_RESET(I2C_DEV_PRESENT) | HC_CONTROL_FIELD_RESET(HOT_JOIN_CTRL) | \
     HC_CONTROL_FIELD_RESET(HALT_ON_CMD_SEQ_TIMEOUT) | HC_CONTROL_FIELD_RESET(ABORT) | \
     HC_CONTROL_FIELD_RESET(RESUME) | HC_CONTROL_FIELD_RESET(BUS_ENABLE))
#define HC_CONTROL_BUS_ENABLE ((uint32_t)I3C_BASEREGS(HC_CONTROL__BUS_ENABLE_bm))

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
