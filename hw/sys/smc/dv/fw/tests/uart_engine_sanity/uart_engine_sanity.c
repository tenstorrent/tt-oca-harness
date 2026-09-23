/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>
#include <string.h>
#include <time.h>

#include "metal/uart.h"
#include "smc_io.h"
#include "smc_test.h"

#include <string.h>

#define BAUD_RATE 115200
#define CLOCK_PERIOD_NS 10

int main(void) {

    uint32_t uart_ctrlrs[] = {0, 1}; // indexes of UARTs used for controllers
    uint32_t num_ctrlrs = sizeof(uart_ctrlrs) / sizeof(uart_ctrlrs[0]);
    uint32_t uart_tgts[] = {3, 2}; // indexes of UARTs used for targets
    uint32_t num_tgts = sizeof(uart_ctrlrs) / sizeof(uart_ctrlrs[0]);
    uint32_t num_uarts = num_ctrlrs + num_tgts;
    uint32_t uart_spacing = 0x400; // each UART allocated 0x400 of space

    uint32_t uart_base_addr = SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0);
    uint32_t uart_ctrl_base_addr =
        SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(0);
    uint32_t uart_engine_base_addr =
        SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0);

    //----------------//
    // Reset & Enable //
    //----------------//

    uart_log_engine_ctrl__CTRL_t uart_enables;
    log_engine__CTRL_t uart_engine_enables;
    uart_enables.w =
        read_reg(SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(
            0)); // fine to use UART0 since all will be the same default val out of reset
    uart_engine_enables.w =
        read_reg(SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR(
            0)); // fine to use UART0 since all will be the same default val out of reset

    uart_enables.f.UART_EN = 0x1;   // enable uart device
    uart_engine_enables.f.EN = 0x1; // enable uart engine

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

    int divisor = 1; // for 115200 --> (int) (1 / (CLOCK_PERIOD_NS * 1e-9)) / (16 * BAUD_RATE); //
                     // DOUBLE CHECK FREQ

    //---------------------------//
    // UART 16550 Controller Setup //
    //---------------------------//

    uint32_t ip_addr_indexed;

    for (int i = 0; i < num_uarts; i++) {
        ip_addr_indexed = uart_base_addr + (i * uart_spacing);

        uart_16550_main__MCR_t mcr;
        uart_16550_main__LCR_t lcr;
        uart_16550_main__IER_t ier;

        read_reg(ip_addr_indexed +
                 (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(
                      0))); // transfer characteristics (DLS = 2'b11)
        read_reg(
            ip_addr_indexed +
            (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
             SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))); // enable interrupts
        read_reg(ip_addr_indexed +
                 (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(
                      0))); // set FIFO Mode 1 (FCR has same addr as IIR)

        mcr.w = read_reg(
            ip_addr_indexed +
            (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
             SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))); // read MCR default
        mcr.f.RTS = 0x1;
        write_reg(ip_addr_indexed +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  mcr.w); // MCR setup

        lcr.w = read_reg(
            ip_addr_indexed +
            (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
             SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))); // read LCR default
        lcr.f.DLAB = 0x1;
        write_reg(ip_addr_indexed +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  lcr.w); // enable divisor set
        write_reg(ip_addr_indexed +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  divisor & 0xFF); // write lower bits of divisor to DLL (same addr as RBR)
        write_reg(ip_addr_indexed +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  (divisor >> 8) & 0xFF); // write upper bits of divisor to DLH (same addr as IER)
        lcr.f.DLAB = 0x0;
        write_reg(ip_addr_indexed +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  lcr.w); // disable divisor set

        lcr.f.WLS = 0x3;
        write_reg(ip_addr_indexed +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  lcr.w); // transfer characteristics (DLS = 2'b11)

        ier.f.ERBFI = 0x1;
        ier.f.ETBEI = 0x1;
        ier.f.ELSI = 0x1;
        ier.f.EDSSI = 0x1;
        write_reg(ip_addr_indexed +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  ier.w); // enable interrupts
        write_reg(ip_addr_indexed +
                      (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  0x1); // set FIFO Mode 1 (FCR has same addr as IIR)
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

        // Configure SMC SRAM log regions
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
            ((sram_addr) >> 32) & 0xFFFFFFFF); // 64 bit reg
        write_reg(
            engine_addr_indexed +
                (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_SIZE_BASE_ADDR(
                     0) -
                 SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0)),
            0x2000);
    }

    write_scratch(4, 0x815); // signal to cocoTB that setup is complete
    write_scratch(7, 0x0);   // scratch7 being initialized to a random big number, zero it out

    uint32_t num_logs;
    uint32_t max_bytes;
    uint32_t IIR_status;
    uint32_t bytes_read;
    uint32_t reset_flag;
    uint32_t end_flag;

    uint32_t this_ctrlr;
    uint32_t this_tgt;

    do { // get number of logs per controller/target pair
        num_logs = read_scratch(6);
    } while (num_logs == 0x0);

    write_scratch(7, 0x2001); // ack that num_logs was received

    do { // wait for scratch6 channel to be reset
        reset_flag = read_scratch(6);
    } while (reset_flag != 0x0);

    write_scratch(7, 0x0);

    for (int i = 0; i < num_ctrlrs; i++) {
        max_bytes = 0x0;
        write_scratch(4, 0x999); // signal that FW is good to start moving UART data
        this_ctrlr = uart_ctrlrs[i];
        this_tgt = uart_tgts[i];
        engine_addr_indexed = uart_engine_base_addr +
                              (this_ctrlr * uart_spacing); // engine needed for controllers only
        ip_addr_indexed =
            uart_base_addr + (this_tgt * uart_spacing); // UART handle only needed for target --
                                                        // uart engine triggers controller UART send

        for (int j = 0; j < num_logs; j++) {

            do {
                max_bytes = read_scratch(6);
            } while (max_bytes == 0x0);

            IIR_status = 0x0000;
            bytes_read = 0;

            unsigned char recvd_bytes[max_bytes];
            // Trigger start of log transfer via LOG_CTRL[n] (upstream:
            // LOG_ENGINE_LOG_CTRL_0__REG_OFFSET = 0x40). j*4 steps entries.
            write_reg(engine_addr_indexed +
                          (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_CTRL_BASE_ADDR(
                               0, 0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0)) +
                          ((i * num_logs) + j) * 4,
                      max_bytes);

            while (bytes_read < max_bytes) {
                do {
                    IIR_status =
                        read_reg(ip_addr_indexed +
                                 (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
                } while ((IIR_status & 0xf) != 0x4);

                unsigned char receive_data = read_reg(
                    ip_addr_indexed +
                    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))); // read data
                write_scratch(
                    5,
                    receive_data); // write received byte to scratch for cocoTB data validity check
                recvd_bytes[bytes_read] = receive_data;
                bytes_read++;
                write_scratch(7, bytes_read); // write counter of bytes received to scratch for
                                              // cocoTB for data validity check
            }

            // wait for 0 from cocoTB side for synchronization
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

    return 0;
}
