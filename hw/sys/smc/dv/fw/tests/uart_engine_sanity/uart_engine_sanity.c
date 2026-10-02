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
    uint32_t uart_spacing = 0x400; // address stride between UART instances

    uint32_t uart_base_addr = SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0);
    uint32_t uart_ctrl_base_addr =
        SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(0);
    uint32_t uart_engine_base_addr =
        SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0);

    //--------//
    // Enable //
    //--------//

    uart_log_engine_ctrl__CTRL_t uart_enables;
    log_engine__CTRL_t uart_engine_enables;
    // All UARTs share the same reset value, so UART0's value is the template.
    uart_enables.w =
        read_reg(SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(0));
    uart_engine_enables.w =
        read_reg(SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR(0));

    uart_enables.f.UART_EN = 0x1;
    uart_engine_enables.f.EN = 0x1;

    for (int i = 0; i < num_uarts; i++) {
        write_reg(
            uart_ctrl_base_addr +
                (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(0) -
                 SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_BASE_ADDR(0)) +
                (i * uart_spacing),
            uart_enables.w);
        write_reg(uart_engine_base_addr +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0)) +
                      (i * uart_spacing),
                  uart_engine_enables.w);
    }

    // The smallest divisor keeps simulation time short.
    int divisor = 1;

    //------------------//
    // UART 16550 Setup //
    //------------------//

    uint32_t ip_addr_indexed;

    for (int i = 0; i < num_uarts; i++) {
        ip_addr_indexed = uart_base_addr + (i * uart_spacing);

        uart_16550_main__MCR_t mcr;
        uart_16550_main__LCR_t lcr;
        uart_16550_main__IER_t ier;

        read_reg(ip_addr_indexed +
                 (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        read_reg(ip_addr_indexed +
                 (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        read_reg(ip_addr_indexed +
                 (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));

        mcr.w = read_reg(ip_addr_indexed +
                         (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                          SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        mcr.f.RTS = 0x1;
        write_reg(ip_addr_indexed +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  mcr.w);

        // Divisor latch access is open only while programming the divisor.
        lcr.w = read_reg(ip_addr_indexed +
                         (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                          SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        lcr.f.DLAB = 0x1;
        write_reg(ip_addr_indexed +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  lcr.w);
        write_reg(ip_addr_indexed +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  divisor & 0xFF);
        write_reg(ip_addr_indexed +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  (divisor >> 8) & 0xFF);
        lcr.f.DLAB = 0x0;
        write_reg(ip_addr_indexed +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  lcr.w);

        // 8-bit words.
        lcr.f.WLS = 0x3;
        write_reg(ip_addr_indexed +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  lcr.w);

        ier.f.ERBFI = 0x1;
        ier.f.ETBEI = 0x1;
        ier.f.ELSI = 0x1;
        ier.f.EDSSI = 0x1;
        write_reg(ip_addr_indexed +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  ier.w);
        // Enable the FIFOs.
        write_reg(ip_addr_indexed +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  0x1);
    }

    //------------------------//
    // Start UART Engine Test //
    //------------------------//

    uint32_t engine_addr_indexed;
    uint32_t sram_addr;
    uint32_t this_uart;

    sram_addr = SMC_TOP_SPM_MEMORY_BASE_ADDR + 0x30000;

    for (int i = 0; i < num_ctrlrs; i++) {

        this_uart = uart_ctrlrs[i];
        engine_addr_indexed = uart_engine_base_addr + (this_uart * uart_spacing);

        write_reg(
            engine_addr_indexed +
                (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_ADDR_BASE_ADDR(
                     0) -
                 SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0)),
            (sram_addr)&0xFFFFFFFF);
        write_reg(
            engine_addr_indexed +
                (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_ADDR_BASE_ADDR(
                     0) -
                 SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0)) +
                0x4,
            ((sram_addr) >> 32) & 0xFFFFFFFF);
        write_reg(
            engine_addr_indexed +
                (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_SIZE_BASE_ADDR(
                     0) -
                 SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0)),
            0x2000);
    }

    // Tell the testbench setup is complete, and clear the byte-count channel,
    // which does not start at zero.
    write_scratch(4, 0x815);
    write_scratch(7, 0x0);

    uint32_t num_logs;
    uint32_t max_bytes;
    uint32_t IIR_status;
    uint32_t bytes_read;
    uint32_t reset_flag;
    uint32_t end_flag;

    uint32_t this_ctrlr;
    uint32_t this_tgt;

    // Receive the number of logs per controller/target pair, acknowledge it, and
    // wait for the testbench to clear the channel.
    do {
        num_logs = read_scratch(6);
    } while (num_logs == 0x0);

    write_scratch(7, 0x2001);

    do {
        reset_flag = read_scratch(6);
    } while (reset_flag != 0x0);

    write_scratch(7, 0x0);

    for (int i = 0; i < num_ctrlrs; i++) {
        max_bytes = 0x0;
        write_scratch(4, 0x999);
        this_ctrlr = uart_ctrlrs[i];
        this_tgt = uart_tgts[i];
        // The controller's log engine drives its UART, so firmware reads only the target UART.
        engine_addr_indexed = uart_engine_base_addr + (this_ctrlr * uart_spacing);
        ip_addr_indexed = uart_base_addr + (this_tgt * uart_spacing);

        for (int j = 0; j < num_logs; j++) {

            // The testbench supplies the length of each log.
            do {
                max_bytes = read_scratch(6);
            } while (max_bytes == 0x0);

            IIR_status = 0x0000;
            bytes_read = 0;

            // Start the transfer of this log entry.
            write_reg(engine_addr_indexed +
                          (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_CTRL_BASE_ADDR(
                               0, 0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0)) +
                          ((i * num_logs) + j) * 4,
                      max_bytes);

            while (bytes_read < max_bytes) {
                // Wait for the target to report received data.
                do {
                    IIR_status =
                        read_reg(ip_addr_indexed +
                                 (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
                } while ((IIR_status & 0xf) != 0x4);

                // Report each byte and the running count for the testbench to check.
                unsigned char receive_data =
                    read_reg(ip_addr_indexed +
                             (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                              SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
                write_scratch(5, receive_data);
                bytes_read++;
                write_scratch(7, bytes_read);
            }

            // Wait for the testbench to clear the channel before the next log.
            do {
                end_flag = read_scratch(6);
            } while (end_flag != 0x0);

            write_scratch(7, 0);
        }

        write_scratch(4, 0x444);
    }

    test_pass(0);

    while (true) {
        __asm__("wfi");
    }
}
