/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

int main(void) {
    uint32_t uart_ctrlrs[] = {0, 1}; // indexes of UARTs used for controllers
    uint32_t num_ctrlrs = sizeof(uart_ctrlrs) / sizeof(uart_ctrlrs[0]);
    uint32_t uart_tgts[] = {3, 2}; // indexes of UARTs used for targets
    uint32_t num_tgts = sizeof(uart_ctrlrs) / sizeof(uart_ctrlrs[0]);
    uint32_t num_uarts = num_ctrlrs + num_tgts;

    // Enable every UART in its wrapper; all wrappers share one reset value, so
    // UART0's serves as the template
    uart_log_engine_ctrl__CTRL_t uart_enables;
    uart_enables.w =
        read_reg(SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(0));
    uart_enables.f.UART_EN = 0x1;

    for (int i = 0; i < num_uarts; i++) {
        uint32_t uart_ctrl_reg_addr;
        if (i == 0)
            uart_ctrl_reg_addr =
                SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(0);
        else if (i == 1)
            uart_ctrl_reg_addr =
                SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(1);
        else if (i == 2)
            uart_ctrl_reg_addr =
                SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(2);
        else
            uart_ctrl_reg_addr =
                SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(3);
        write_reg(uart_ctrl_reg_addr, uart_enables.w);
    }

    int divisor = 1; // divide-by-1: fastest baud for simulation

    // Configure each UART: request to send, baud divisor, 8-bit characters,
    // interrupts and FIFO mode
    for (int i = 0; i < num_uarts; i++) {
        uint32_t uart_base_addr;
        if (i == 0)
            uart_base_addr = SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0);
        else if (i == 1)
            uart_base_addr = SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(1);
        else if (i == 2)
            uart_base_addr = SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(2);
        else
            uart_base_addr = SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(3);

        uart_16550_main__MCR_t mcr;
        uart_16550_main__LCR_t lcr;
        uart_16550_main__IER_t ier;

        mcr.w = read_reg(uart_base_addr +
                         (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                          SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        mcr.f.RTS = 0x1;
        write_reg(uart_base_addr +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  mcr.w);

        lcr.w = read_reg(uart_base_addr +
                         (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                          SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));

        // The divisor latch shares the receive and interrupt-enable addresses
        lcr.f.DLAB = 0x1;
        write_reg(uart_base_addr +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  lcr.w);
        write_reg(uart_base_addr +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  divisor & 0xFF);
        write_reg(uart_base_addr +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  (divisor >> 8) & 0xFF);
        lcr.f.DLAB = 0x0;
        write_reg(uart_base_addr +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  lcr.w);

        lcr.f.WLS = 0x3;
        write_reg(uart_base_addr +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  lcr.w);

        ier.f.ERBFI = 0x1;
        ier.f.ETBEI = 0x1;
        ier.f.ELSI = 0x1;
        ier.f.EDSSI = 0x1;
        write_reg(uart_base_addr +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  ier.w);

        // The FIFO control register shares the interrupt-identification address
        write_reg(uart_base_addr +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  0x1);
    }

    // Send one byte from each controller and check what its target receives
    uint32_t send_data[] = {0xa5, 0xb6};
    uint32_t ctrlr_addr_indexed;
    uint32_t tgt_addr_indexed;
    uint32_t this_ctrlr;
    uint32_t this_tgt;
    uint32_t IIR_status;

    for (int i = 0; i < num_ctrlrs; i++) {
        this_ctrlr = uart_ctrlrs[i];
        this_tgt = uart_tgts[i];

        uint32_t ctrlr_uart_base;
        if (this_ctrlr == 0)
            ctrlr_uart_base = SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0);
        else if (this_ctrlr == 1)
            ctrlr_uart_base = SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(1);
        else if (this_ctrlr == 2)
            ctrlr_uart_base = SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(2);
        else
            ctrlr_uart_base = SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(3);

        uint32_t tgt_uart_base;
        if (this_tgt == 0)
            tgt_uart_base = SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0);
        else if (this_tgt == 1)
            tgt_uart_base = SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(1);
        else if (this_tgt == 2)
            tgt_uart_base = SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(2);
        else
            tgt_uart_base = SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(3);

        ctrlr_addr_indexed = ctrlr_uart_base;
        tgt_addr_indexed = tgt_uart_base;

        write_reg(ctrlr_addr_indexed +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  send_data[i]);

        do {
            IIR_status =
                read_reg(tgt_addr_indexed +
                         (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                          SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        } while ((IIR_status & 0xf) != 0x4);

        unsigned char receive_data = read_reg(
            tgt_addr_indexed + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                                SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        write_scratch(1, receive_data);

        if (receive_data != send_data[i]) {
            test_fail(0);
        }
    }

    test_pass(0);
}
