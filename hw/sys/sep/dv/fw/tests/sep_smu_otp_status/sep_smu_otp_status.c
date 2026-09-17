/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_otp_status - firmware reference read of eFuse STATUS.
 *
 * After fuse-sense, read 0x10930400, require bit0 (sense-done)=1, publish the
 * full 32-bit value on cold scratch7 and OTP_STATUS_PUBLISH on scratch6. Cocotb
 * uses that value as otp_status_ref for the JTAG2AXI allow/block compare.
 */

#include <stdint.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_efuse.h"
#include "sep_smu_otp_status_protocol.h"

#define OTP_STATUS_SCRATCH6 OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(6)
#define OTP_STATUS_SCRATCH7 OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(7)
#define OTP_STATUS_SENSE_LIMIT 2000000u

__attribute__((used, noinline, noreturn)) void sep_smu_otp_status_pass_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn)) void sep_smu_otp_status_fail_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

int main(void) {
    uint32_t status;
    uint32_t i;

    for (i = 0; i < OTP_STATUS_SENSE_LIMIT; i++) {
        status = READ_REG(SEP_EFUSE_IFC_STATUS);
        if ((status & SEP_EFUSE_SENSE_DONE) != 0u) {
            break;
        }
    }
    if ((status & SEP_EFUSE_SENSE_DONE) == 0u) {
        WRITE_REG(OTP_STATUS_SCRATCH6, OTP_STATUS_FAIL);
        sep_smu_otp_status_fail_loop();
    }

    WRITE_REG(OTP_STATUS_SCRATCH7, status);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    if (READ_REG(OTP_STATUS_SCRATCH7) != status) {
        WRITE_REG(OTP_STATUS_SCRATCH6, OTP_STATUS_FAIL);
        sep_smu_otp_status_fail_loop();
    }

    WRITE_REG(OTP_STATUS_SCRATCH6, OTP_STATUS_PUBLISH);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    sep_smu_otp_status_pass_loop();
    return 0;
}
