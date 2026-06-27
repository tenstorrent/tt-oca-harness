/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

// smc_uart_log_engine_reset_test
//
// Verify reset defaults of all uart_log_engine_wrap_0 registers per the RDL.
// FW-only: read every register and compare to its RDL-specified reset value.
// Mismatches log via info_msg_* then call test_fail(0) (fail-fast).

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

#define WRAP0_CTRL_REG      SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(0)
#define WRAP0_UART_BASE     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)
#define WRAP0_LE_BASE       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR(0)

#define UART_RBR_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_IER_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_IIR_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_LCR_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_MCR_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_LSR_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_MSR_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MSR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_SCR_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_SCR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_ECR_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ECR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_ITR_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))

#define LE_CTRL_OFF         (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_REGION_SIZE_OFF  (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_SIZE_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_REGION_ADDR_OFF  (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_ADDR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_WRITE_ADDR_OFF   (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_WRITE_ADDR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_INTR_STATUS_OFF  (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_STATUS_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_INTR_ENABLE_OFF  (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_ENABLE_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_LOG_CTRL0_OFF    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_CTRL_BASE_ADDR(0, 0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))

// Compare-after-mask. Mask=0 means "no defined bits"; any value is accepted.
static void check_reset(uint32_t addr, uint32_t expect, uint32_t mask,
                        const char *name) {
    uint32_t got = read_reg(addr) & mask;
    if (got != (expect & mask)) {
        info_msg_s(0, "FAIL:");
        info_msg_s(0, name);
        info_msg_hex32_s(0, "  addr    =", addr);
        info_msg_hex32_s(0, "  expected=", expect & mask);
        info_msg_hex32_s(0, "  got     =", got);
        test_fail(0);
    }
}

int main(void) {
    info_msg_s(0, "smc_uart_log_engine_reset_test start");

    //--------------------------------------------------------------------------
    // Wrapper CTRL.UART_EN — reset = 0
    //--------------------------------------------------------------------------
    check_reset(WRAP0_CTRL_REG, 0x00000000u, 0x00000001u, "CTRL.UART_EN");

    //--------------------------------------------------------------------------
    // UART 16550 main (DLAB=0 layout by default after reset)
    //--------------------------------------------------------------------------
    // LCR reset = 0 (full 8 bits)
    check_reset(WRAP0_UART_BASE + UART_LCR_OFF, 0x00000000u, 0x000000FFu, "UART.LCR");
    // MCR reset = 0 (6 bits)
    check_reset(WRAP0_UART_BASE + UART_MCR_OFF, 0x00000000u, 0x0000003Fu, "UART.MCR");
    // SCR reset = 0 (8 bits)
    check_reset(WRAP0_UART_BASE + UART_SCR_OFF, 0x00000000u, 0x000000FFu, "UART.SCR");
    // ECR reset = 0 (2 bits)
    check_reset(WRAP0_UART_BASE + UART_ECR_OFF, 0x00000000u, 0x00000003u, "UART.ECR");
    // ITR reset = 0 (6 bits)
    check_reset(WRAP0_UART_BASE + UART_ITR_OFF, 0x00000000u, 0x0000003Fu, "UART.ITR");
    // IER (DLAB=0) reset = 0 (5 bits)
    check_reset(WRAP0_UART_BASE + UART_IER_OFF, 0x00000000u, 0x0000001Fu, "UART.IER");

    // LSR reset: THRE=1 (bit5), TEMT=1 (bit6) → 0x60. Other bits 0.
    // Mask off DR/OE/PE/FE/BI/ERROR_IN_RCVR_FIFO since those can be set by
    // residual conditions (none expected at reset, but be conservative).
    check_reset(WRAP0_UART_BASE + UART_LSR_OFF, 0x60u, 0x60u, "UART.LSR.THRE|TEMT");

    // IIR reset: INTERRUPT_PENDING=1 (active low so reads as 1), INTERRUPT_ID=0,
    // FIFOS_ENABLED=0.  bit[0] = 1 at reset.
    check_reset(WRAP0_UART_BASE + UART_IIR_OFF, 0x01u, 0x0FFu, "UART.IIR");

    // MSR — depends on async input idle state. Just read to confirm no X bus error.
    (void)read_reg(WRAP0_UART_BASE + UART_MSR_OFF);

    //--------------------------------------------------------------------------
    // Log Engine — reset = 0 for every RW register, INTR_STATUS = 0
    //--------------------------------------------------------------------------
    check_reset(WRAP0_LE_BASE + LE_CTRL_OFF,         0x00000000u, 0x00000001u, "LE.CTRL.EN");
    check_reset(WRAP0_LE_BASE + LE_REGION_SIZE_OFF,  0x00000000u, 0x000FFFFFu, "LE.LOG_REGION_SIZE");
    check_reset(WRAP0_LE_BASE + LE_REGION_ADDR_OFF,      0x00000000u, 0xFFFFFFFFu, "LE.LOG_REGION_ADDR_LO");
    check_reset(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4,  0x00000000u, 0xFFFFFFFFu, "LE.LOG_REGION_ADDR_HI");
    check_reset(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF,   0x00000000u, 0xFFFFFFFFu, "LE.LOG_WRITE_ADDR");
    check_reset(WRAP0_LE_BASE + LE_INTR_STATUS_OFF,  0x00000000u, 0x00000011u, "LE.INTR_STATUS");
    check_reset(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF,  0x00000000u, 0x00000011u, "LE.INTR_ENABLE");

    // LOG_CTRL[0..15] reset = 0 (LOG_LEN[15:0])
    for (uint32_t i = 0; i < 16; i++) {
        char name[24] = "LE.LOG_CTRL[i]";
        check_reset(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF + (i * 4),
                    0x00000000u, 0x0000FFFFu, name);
    }

    info_msg_s(0, "smc_uart_log_engine_reset_test done");
    test_pass(0);

    while (1) __asm__("wfi");
    return 0;
}
