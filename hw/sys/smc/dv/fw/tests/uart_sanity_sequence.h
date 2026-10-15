/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef UART_SANITY_SEQUENCE_H
#define UART_SANITY_SEQUENCE_H

/* UART sanity sequence for the cpu_traffic super-loop: 4-UART reset/enable,
 * UART 16550 controller setup, controller->target data transfer + readback
 * compare. */

#include <stdint.h>
#include <time.h>

#include "smc_io.h"
#include "smc_test.h"
#include "virt_console.h"

#define BAUD_RATE 115200
#define CLOCK_PERIOD_NS 10

#define UART_CTRL_ADDR(idx) \
    SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(idx)
#define UART_BASE_ADDR(idx) SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(idx)
#define UART_SUBREG_OFFSET(reg) \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_##reg##_BASE_ADDR(0) - UART_BASE_ADDR(0))

int uart_sanity_sequence(int hartid) {

    info_msg_s(hartid, "uart_sanity_sequence Starting");

    //----------------//
    // Reset & Enable //
    //----------------//

    uart_log_engine_ctrl__CTRL_t uart_enables;
    uart_enables.w = read_reg(
        UART_CTRL_ADDR(0)); // fine to use UART0 since all will be the same default val out of reset
    uart_enables.f.UART_EN = 0x1;

    // Enable all 4 UARTs; the transfer below uses two controller/target pairs.
    uint32_t num_uarts = 4;

    for (int i = 0; i < num_uarts; i++) {
        uint32_t uart_ctrl_reg_addr;
        if (i == 0)
            uart_ctrl_reg_addr = UART_CTRL_ADDR(0);
        else if (i == 1)
            uart_ctrl_reg_addr = UART_CTRL_ADDR(1);
        else if (i == 2)
            uart_ctrl_reg_addr = UART_CTRL_ADDR(2);
        else
            uart_ctrl_reg_addr = UART_CTRL_ADDR(3);
        write_reg(uart_ctrl_reg_addr, uart_enables.w);
    }

    int divisor = 1; // divide-by-1: fastest baud for simulation

    //---------------------------//
    // UART 16550 Controller Setup //
    //---------------------------//

    for (int i = 0; i < num_uarts; i++) {
        uint32_t uart_base_addr;
        if (i == 0)
            uart_base_addr = UART_BASE_ADDR(0);
        else if (i == 1)
            uart_base_addr = UART_BASE_ADDR(1);
        else if (i == 2)
            uart_base_addr = UART_BASE_ADDR(2);
        else
            uart_base_addr = UART_BASE_ADDR(3);

        uart_16550_main__MCR_t mcr;
        uart_16550_main__LCR_t lcr;
        uart_16550_main__IER_t ier;

        mcr.w = read_reg(uart_base_addr + UART_SUBREG_OFFSET(MCR)); // read MCR default
        mcr.f.RTS = 0x1;
        write_reg(uart_base_addr + UART_SUBREG_OFFSET(MCR), mcr.w);

        lcr.w = read_reg(uart_base_addr + UART_SUBREG_OFFSET(LCR)); // read LCR default
        lcr.f.DLAB = 0x1;
        write_reg(uart_base_addr + UART_SUBREG_OFFSET(LCR), lcr.w); // enable divisor set
        write_reg(uart_base_addr + UART_SUBREG_OFFSET(RBR),
                  divisor & 0xFF); // write lower bits of divisor to DLL (same addr as RBR)
        write_reg(uart_base_addr + UART_SUBREG_OFFSET(IER),
                  (divisor >> 8) & 0xFF); // write upper bits of divisor to DLH (same addr as IER)
        lcr.f.DLAB = 0x0;
        write_reg(uart_base_addr + UART_SUBREG_OFFSET(LCR), lcr.w); // disable divisor set

        lcr.f.WLS = 0x3;
        write_reg(uart_base_addr + UART_SUBREG_OFFSET(LCR),
                  lcr.w); // transfer characteristics (DLS = 2'b11)

        ier.f.ERBFI = 0x1;
        ier.f.ETBEI = 0x1;
        ier.f.ELSI = 0x1;
        ier.f.EDSSI = 0x1;
        write_reg(uart_base_addr + UART_SUBREG_OFFSET(IER), ier.w); // enable interrupts
        write_reg(uart_base_addr + UART_SUBREG_OFFSET(IIR),
                  0x1); // set FIFO Mode 1 (FCR has same addr as IIR)
    }

    //------------//
    // Write Data //
    //------------//

    uint32_t send_data[] = {0xa5, 0xb6};
    uint32_t uart_ctrlrs[] = {0, 1}; // controller UART indices
    uint32_t uart_tgts[] = {3, 2};   // target UART indices
    uint32_t num_ctrlrs = sizeof(uart_ctrlrs) / sizeof(uart_ctrlrs[0]);

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
            ctrlr_uart_base = UART_BASE_ADDR(0);
        else if (this_ctrlr == 1)
            ctrlr_uart_base = UART_BASE_ADDR(1);
        else if (this_ctrlr == 2)
            ctrlr_uart_base = UART_BASE_ADDR(2);
        else
            ctrlr_uart_base = UART_BASE_ADDR(3);

        uint32_t tgt_uart_base;
        if (this_tgt == 0)
            tgt_uart_base = UART_BASE_ADDR(0);
        else if (this_tgt == 1)
            tgt_uart_base = UART_BASE_ADDR(1);
        else if (this_tgt == 2)
            tgt_uart_base = UART_BASE_ADDR(2);
        else
            tgt_uart_base = UART_BASE_ADDR(3);

        ctrlr_addr_indexed = ctrlr_uart_base;
        tgt_addr_indexed = tgt_uart_base;

        IIR_status = 0x0000;

        write_reg(ctrlr_addr_indexed + UART_SUBREG_OFFSET(RBR), send_data[i]);

        do {
            IIR_status = read_reg(tgt_addr_indexed + UART_SUBREG_OFFSET(IIR));
        } while ((IIR_status & 0xf) != 0x4);

        unsigned char receive_data = read_reg(tgt_addr_indexed + UART_SUBREG_OFFSET(RBR));
        write_scratch(i, receive_data);

        simputshex32("receive_data = ", receive_data);
        simputshex32("send_data = ", send_data[i]);

        if (receive_data != send_data[i]) {
            raise_error_s(hartid, "uart_sanity_sequence: UART data mis-matched");
        }
    }

    info_msg_s(hartid, "uart_sanity_sequence: UART data matched");

    info_msg_s(hartid, "uart_sanity_sequence Ending");

    return 0;
}

#endif
